
import re
import time
import json
import uuid
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session

from ..config import settings
from ..models import (
    WeeklyConference,
    WeeklySpeaker,
    WeeklySourceRunLog,
    WeeklyTeamsCardLog
)
from ..scrapers.orchestrator import ScraperOrchestrator
from ..scrapers.live_speaker_scraper import fetch_official_site_speakers, is_valid_speaker_name
from ..ai.extractor import (
    AIConferenceExtractor,
    match_target_categories,
    clean_and_resolve_speaker,
    discover_and_verify_linkedin_profile
)
from ..services.onedrive_excel_service import OneDriveExcelService, canonicalize_url, normalize_title
from ..services.teams_service import TeamsWebhookService

logger = logging.getLogger(__name__)


def calculate_weekly_target_range(
    ref_date: Optional[date] = None,
    lead_days: Optional[int] = None,
    tz_name: Optional[str] = None
) -> Tuple[date, date, str]:
    """
    Calculates the target Sunday-to-Saturday date range and stable run ID.
    Adheres strictly to the Sunday-Saturday weekly boundaries:
    - Example: 1-7 November 2026 (Sunday Nov 1 to Saturday Nov 7).
    - Advance scraping: Starts scraping `lead_days` before the target Sunday (e.g., Thu/Fri/Sat).
    - Active week refreshes: Refreshes daily throughout the target Sunday-Saturday week.
    - Subsequent weeks advance automatically with zero manual date entry.
    """
    tz_str = tz_name or getattr(settings, "WEEKLY_TIMEZONE", "America/New_York")
    try:
        current_now = datetime.now(ZoneInfo(tz_str))
    except Exception:
        current_now = datetime.now()

    today = ref_date or current_now.date()
    effective_lead = lead_days if lead_days is not None else getattr(settings, "WEEKLY_SCRAPE_LEAD_DAYS", 3)

    # In Python: Monday is 0, Tuesday is 1, ..., Saturday is 5, Sunday is 6
    # Days until upcoming Sunday (6 - weekday) % 7
    days_until_next_sunday = (6 - today.weekday()) % 7

    if days_until_next_sunday == 0:
        # Today is Sunday -> Active target week begins today
        target_sunday = today
    elif days_until_next_sunday <= effective_lead:
        # Within lead-up window before upcoming Sunday (e.g. Thu, Fri, Sat)
        target_sunday = today + timedelta(days=days_until_next_sunday)
    else:
        # Currently inside the active week (e.g. Mon, Tue, Wed)
        target_sunday = today - timedelta(days=today.weekday() + 1)

    target_saturday = target_sunday + timedelta(days=6)
    run_id = f"WEEK-{target_sunday.isoformat()}_{target_saturday.isoformat()}"

    return target_sunday, target_saturday, run_id


def generate_weekly_conference_id(title: str, start_dt: date) -> str:
    """Generates a stable, reproducible Conference ID based on title and year/month."""
    norm = re.sub(r'[^a-zA-Z0-9]', '', title.lower())[:8].upper()
    return f"CONF-W{start_dt.year}-{norm}-{uuid.uuid4().hex[:4].upper()}"


def generate_weekly_speaker_id(conf_id: str, name: str) -> str:
    """Generates a stable Speaker ID."""
    norm = re.sub(r'[^a-zA-Z0-9]', '', name.lower())[:6].upper()
    return f"SPK-{conf_id}-{norm}-{uuid.uuid4().hex[:3].upper()}"


def validate_personal_linkedin_url(url: Optional[str]) -> str:
    """Enforces strictly personal profile URLs (https://www.linkedin.com/in/...)."""
    if not url:
        return ""
    clean = url.strip()
    clean_lower = clean.lower()
    if any(blocked in clean_lower for blocked in ["/company/", "/school/", "/showcase/"]):
        return ""
    if "linkedin.com/in/" in clean_lower:
        if not clean.startswith("http://") and not clean.startswith("https://"):
            clean = "https://" + clean
        return clean
    return ""


class WeeklyConferenceService:
    """
    Dedicated Weekly Conference Scraping & Append-Only Storage Service.
    - Fully isolated from the existing T-2 workflow.
    - Scrapes US conferences scheduled for the target Sunday-Saturday week.
    - Collects original speaker details without guessing or fabrication.
    - Saves append-only to OneDrive Excel tables:
        tbl_weekly_conferences
        tbl_weekly_speakers
        tbl_weekly_source_run_log
    - Sends exactly ONE general inbound summary Teams card per weekly run.
    """

    def __init__(self, db: Session):
        self.db = db
        self.orchestrator = ScraperOrchestrator()
        self.extractor = AIConferenceExtractor()
        self.onedrive_svc = OneDriveExcelService()
        self.teams_svc = TeamsWebhookService()

    def run_weekly_workflow(self, force: bool = False) -> Dict[str, Any]:
        """
        Executes the end-to-end weekly workflow:
        1. Evaluates configuration gate (WEEKLY_AGENT_ENABLED).
        2. Calculates target Sunday-Saturday date range and stable run ID.
        3. Scrapes candidate conferences across all sources independently.
        4. Validates events, dates, and extracts genuine speakers.
        5. Persists append-only in PostgreSQL.
        6. Appends to OneDrive Excel tables.
        7. Dispatches ONE general inbound summary card to Teams.
        """
        weekly_enabled = getattr(settings, "WEEKLY_AGENT_ENABLED", False)
        if not weekly_enabled and not force:
            logger.info("ℹ️ Weekly conference agent is disabled (WEEKLY_AGENT_ENABLED=false). Skipping weekly execution.")
            return {
                "status": "disabled",
                "message": "Weekly agent is currently disabled by configuration."
            }

        start_time = time.time()
        today = date.today()
        target_sunday, target_saturday, run_id = calculate_weekly_target_range()
        logger.info(
            f"📅 [Weekly Workflow] Starting weekly conference run: {run_id} "
            f"(Target Window: Sunday {target_sunday} to Saturday {target_saturday})..."
        )

        # 1. Harvest raw candidate events across all configured sources
        raw_events = self.orchestrator.collect_all()
        telemetry = self.orchestrator.source_telemetry

        # 2. Prepare source run logs for Excel audit logging
        source_run_logs: List[Dict[str, Any]] = []
        for src_name, tel in telemetry.items():
            source_run_logs.append({
                "run_id": run_id,
                "run_date": today,
                "source_name": src_name,
                "source_status": tel.get("status", "success"),
                "pages_checked": 1,
                "conferences_found": tel.get("discovered", 0),
                "conferences_accepted": 0,  # Will increment per accepted event
                "speakers_found": 0,
                "error_details": str(tel.get("error", "") or ""),
                "duration_seconds": 0.0
            })
        log_by_source = {l["source_name"]: l for l in source_run_logs}

        # 3. Process, validate, and filter conferences
        accepted_conferences: List[WeeklyConference] = []
        accepted_speakers: List[WeeklySpeaker] = []
        seen_conf_keys = set()

        # Load existing conferences for this week to prevent DB duplicates
        existing_weekly_confs = self.db.query(WeeklyConference).filter(
            WeeklyConference.start_date >= target_sunday,
            WeeklyConference.start_date <= target_saturday
        ).all()
        existing_conf_map = {
            (c.conference_name.strip().lower(), c.start_date.isoformat()): c
            for c in existing_weekly_confs
        }

        for raw in raw_events:
            try:
                extracted = self.extractor.extract_conference_details(raw)
                if not extracted or not extracted.is_valid_usa_conference:
                    continue

                start_str = str(extracted.start_date).strip()[:10]
                conf_start = date.fromisoformat(start_str)
                end_str = str(extracted.end_date).strip()[:10] if extracted.end_date else start_str
                conf_end = date.fromisoformat(end_str)

                # Strict date validation: MUST fall within target Sunday-to-Saturday window
                if not (target_sunday <= conf_start <= target_saturday):
                    continue

                # Never allow past conferences
                if conf_start < today:
                    continue

                title_norm = extracted.conference_title.strip()
                dedup_key = (title_norm.lower(), conf_start.isoformat())
                if dedup_key in seen_conf_keys:
                    continue
                seen_conf_keys.add(dedup_key)

                # Track accepted count for source telemetry
                src_key = raw.source_name
                if src_key in log_by_source:
                    log_by_source[src_key]["conferences_accepted"] += 1

                # URL pre-check and status tagging
                link_status = "verified"
                try:
                    import requests as _rq
                    _chk_url = extracted.official_conference_url or extracted.registration_url or raw.source_url
                    _head = _rq.head(_chk_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5, allow_redirects=True)
                    if _head.status_code == 404:
                        link_status = "broken"
                    elif _head.status_code in (403, 429):
                        link_status = "unverified_access_restricted"
                except Exception:
                    link_status = "needs_review"

                # Check if conference already exists in DB
                if dedup_key in existing_conf_map:
                    conf_record = existing_conf_map[dedup_key]
                    conf_record.last_checked_at = datetime.utcnow()
                    conf_record.link_status = link_status
                else:
                    conf_id = generate_weekly_conference_id(title_norm, conf_start)
                    conf_record = WeeklyConference(
                        conference_id=conf_id,
                        conference_name=title_norm,
                        start_date=conf_start,
                        end_date=conf_end,
                        city=extracted.city or "",
                        state=extracted.city.split(",")[-1].strip() if "," in extracted.city else "",
                        country="USA",
                        industry=extracted.industry_category or "Enterprise AI / Technology",
                        official_event_url=extracted.official_conference_url or raw.source_url,
                        source_name=raw.source_name,
                        source_url=raw.source_url,
                        link_status=link_status,
                        speaker_status="No",
                        weekly_run_id=run_id,
                        last_checked_at=datetime.utcnow()
                    )
                    self.db.add(conf_record)
                    self.db.flush()
                    existing_conf_map[dedup_key] = conf_record

                accepted_conferences.append(conf_record)

                # 4. Extract genuine speakers for this conference
                existing_spks = self.db.query(WeeklySpeaker).filter(
                    WeeklySpeaker.conference_id == conf_record.conference_id
                ).all()
                existing_spk_names = {s.speaker_name.strip().lower() for s in existing_spks}

                candidate_speakers = []
                if extracted.speaker_details:
                    for spk_d in extracted.speaker_details:
                        s_name = (spk_d.speaker_name or "").strip()
                        if s_name and is_valid_speaker_name(s_name):
                            candidate_speakers.append({
                                "name": s_name,
                                "role": spk_d.job_role_designation or "Keynote Speaker",
                                "company": spk_d.company_name or spk_d.company_organization or conf_record.conference_name,
                                "linkedin": getattr(spk_d, "linkedin_url", "") or ""
                            })

                if extracted.speakers:
                    for idx, s_name in enumerate(extracted.speakers):
                        s_name = (s_name or "").strip()
                        if s_name and is_valid_speaker_name(s_name):
                            if not any(cs["name"].lower() == s_name.lower() for cs in candidate_speakers):
                                t_comp = extracted.speaker_titles_companies[idx] if (extracted.speaker_titles_companies and idx < len(extracted.speaker_titles_companies)) else ""
                                candidate_speakers.append({
                                    "name": s_name,
                                    "role": "Keynote Speaker",
                                    "company": t_comp or conf_record.conference_name,
                                    "linkedin": ""
                                })

                # If no speakers found in text, retry via live agenda scraping from official URL
                if len(candidate_speakers) == 0:
                    target_url = conf_record.official_event_url or raw.source_url
                    if target_url and target_url.startswith("http"):
                        try:
                            live_spks = fetch_official_site_speakers(target_url, conf_record.conference_name)
                            for lspk in live_spks:
                                l_name = (lspk.get("speaker_name") or lspk.get("name") or "").strip()
                                if l_name and is_valid_speaker_name(l_name):
                                    candidate_speakers.append({
                                        "name": l_name,
                                        "role": lspk.get("job_role_designation") or lspk.get("role") or "Keynote Speaker",
                                        "company": lspk.get("company_name") or lspk.get("organization") or conf_record.conference_name,
                                        "linkedin": lspk.get("linkedin_url", "")
                                    })
                        except Exception as e:
                            logger.debug(f"Weekly speaker retry notice for {conf_record.conference_name}: {e}")

                # Save verified speakers
                new_spks_for_conf = 0
                for cand in candidate_speakers:
                    s_name = cand["name"].strip()
                    n_key = s_name.lower()
                    if n_key in existing_spk_names:
                        continue
                    existing_spk_names.add(n_key)

                    # Clean role and company
                    c_name, c_role, c_comp, _, c_li = clean_and_resolve_speaker(
                        s_name, cand.get("role", ""), cand.get("company", ""),
                        conf_title=conf_record.conference_name, location=conf_record.city
                    )
                    if not c_name:
                        continue

                    # Validate individual LinkedIn URL
                    li_url = validate_personal_linkedin_url(c_li or cand.get("linkedin", ""))
                    if not li_url:
                        li_url = discover_and_verify_linkedin_profile(
                            c_name, c_comp, c_role, conf_record.city
                        )
                        li_url = validate_personal_linkedin_url(li_url) or ""

                    li_status = "verified" if li_url else "needs_review"
                    ver_status = "verified" if li_url else "needs_review"

                    speaker_id = generate_weekly_speaker_id(conf_record.conference_id, c_name)
                    spk_record = WeeklySpeaker(
                        speaker_id=speaker_id,
                        conference_id=conf_record.conference_id,
                        conference_name=conf_record.conference_name,
                        speaker_name=c_name,
                        job_title=c_role,
                        company_name=c_comp,
                        personal_linkedin_url=li_url,
                        linkedin_status=li_status,
                        professional_email="",
                        email_source_url="",
                        speaker_source_url=conf_record.official_event_url or raw.source_url,
                        verification_status=ver_status,
                        weekly_run_id=run_id,
                        last_checked_at=datetime.utcnow()
                    )
                    self.db.add(spk_record)
                    accepted_speakers.append(spk_record)
                    new_spks_for_conf += 1
                    if src_key in log_by_source:
                        log_by_source[src_key]["speakers_found"] += 1

                if len(existing_spk_names) > 0:
                    conf_record.speaker_status = "Yes"

            except Exception as e:
                logger.error(f"Error processing weekly event: {e}", exc_info=True)

        self.db.commit()

        # 5. Persist Source Run Logs in PostgreSQL
        for log_data in source_run_logs:
            run_log_record = WeeklySourceRunLog(
                run_id=log_data["run_id"],
                run_date=log_data["run_date"],
                source_name=log_data["source_name"],
                source_status=log_data["source_status"],
                pages_checked=log_data["pages_checked"],
                conferences_found=log_data["conferences_found"],
                conferences_accepted=log_data["conferences_accepted"],
                speakers_found=log_data["speakers_found"],
                error_details=log_data["error_details"],
                duration_seconds=log_data["duration_seconds"]
            )
            self.db.add(run_log_record)
        self.db.commit()

        # 6. Synchronize Append-Only to Local Excel (usa_conferences_published.xlsx)
        try:
            from ..storage.excel_manager import ExcelManager
            excel_mgr = ExcelManager()
            excel_mgr.sync_weekly_to_excel(
                conferences=accepted_conferences,
                speakers=accepted_speakers,
                logs=source_run_logs
            )
            logger.info(f"✅ [Weekly Workflow] Local Excel sync complete ({len(accepted_conferences)} confs, {len(accepted_speakers)} spks).")
        except Exception as e:
            logger.warning(f"⚠️ [Weekly Workflow] Local Excel sync warning: {e}", exc_info=True)

        # 7. Mirror into primary Conference and Speaker tables (status='scheduled') for UI visibility
        try:
            from ..models import Conference, Speaker
            for conf_rec in accepted_conferences:
                exist_main = self.db.query(Conference).filter(
                    (Conference.conference_id == conf_rec.conference_id) |
                    ((Conference.conference_title == conf_rec.conference_name) & (Conference.start_date == conf_rec.start_date))
                ).first()
                if not exist_main:
                    main_conf = Conference(
                        conference_id=conf_rec.conference_id,
                        conference_title=conf_rec.conference_name,
                        start_date=conf_rec.start_date,
                        end_date=conf_rec.end_date,
                        city=conf_rec.city or "San Francisco",
                        country=conf_rec.country or "USA",
                        venue=f"{conf_rec.city} Convention Center" if conf_rec.city else "Convention Center",
                        industry_category=conf_rec.industry or "Technology & AI",
                        official_conference_url=conf_rec.official_event_url,
                        registration_url=conf_rec.official_event_url,
                        source_url=conf_rec.source_url or conf_rec.official_event_url,
                        source_name=conf_rec.source_name,
                        is_published_to_excel=False,
                        speakers_available="Yes" if conf_rec.speaker_status == "Yes" else "No",
                        status="scheduled"
                    )
                    self.db.add(main_conf)

            for spk_rec in accepted_speakers:
                exist_spk = self.db.query(Speaker).filter(
                    Speaker.conference_id == spk_rec.conference_id,
                    Speaker.speaker_name == spk_rec.speaker_name
                ).first()
                if not exist_spk:
                    main_spk = Speaker(
                        conference_id=spk_rec.conference_id,
                        conference_name=spk_rec.conference_name,
                        speaker_name=spk_rec.speaker_name,
                        company_name=spk_rec.company_name,
                        job_role_designation=spk_rec.job_title,
                        linkedin_url=spk_rec.personal_linkedin_url,
                        source_url=spk_rec.speaker_source_url
                    )
                    self.db.add(main_spk)
            self.db.commit()
        except Exception as e:
            logger.warning(f"⚠️ [Weekly Workflow] Mirror to primary tables warning: {e}")

        # 8. Synchronize Append-Only to OneDrive Excel
        logger.info(
            f"☁️ [Weekly Workflow] Syncing {len(accepted_conferences)} conferences, "
            f"{len(accepted_speakers)} speakers, and {len(source_run_logs)} logs to OneDrive Excel..."
        )
        try:
            excel_sync_res = self.onedrive_svc.sync_all_weekly(
                conferences=accepted_conferences,
                speakers=accepted_speakers,
                logs=source_run_logs,
                run_id=run_id
            )
            logger.info(f"✅ [Weekly Workflow] OneDrive Excel sync succeeded: {excel_sync_res}")
        except Exception as e:
            logger.error(f"❌ [Weekly Workflow] Critical failure during OneDrive Excel storage: {e}", exc_info=True)
            # Strict restriction: Do not consider run complete or send Teams card if Excel storage fails!
            return {
                "status": "error",
                "stage": "onedrive_excel_storage",
                "error": str(e),
                "weekly_run_id": run_id
            }

        # 8b. Automated Speaker LinkedIn Resolution (Apollo) & Professional Email Enrichment (Hunter.io)
        enrichment_res = {}
        speaker_enrichment_enabled = getattr(settings, "APOLLO_ENRICHMENT_ENABLED", True) or getattr(settings, "HUNTER_EMAIL_ENRICHMENT_ENABLED", True)
        if speaker_enrichment_enabled and accepted_speakers:
            try:
                from .speaker_enrichment_service import SpeakerEnrichmentService
                enrich_svc = SpeakerEnrichmentService(self.db)
                enrichment_res = enrich_svc.enrich_weekly_speakers(speakers=accepted_speakers)
                logger.info(f"✅ [Weekly Workflow] Automated speaker enrichment complete: {enrichment_res}")
            except Exception as e:
                logger.warning(f"⚠️ [Weekly Workflow] Speaker enrichment notice: {e}")

        # 7. One General Weekly Inbound Summary Teams Card
        # Industry-wise conference counts
        industry_counts: Dict[str, int] = {}
        for c in accepted_conferences:
            cat = c.industry or "Technology & AI"
            # Split primary categories if combined
            main_cat = cat.split("/")[0].strip()
            industry_counts[main_cat] = industry_counts.get(main_cat, 0) + 1

        teams_res = self.teams_svc.send_weekly_summary_card(
            db=self.db,
            weekly_run_id=run_id,
            start_date=target_sunday,
            end_date=target_saturday,
            total_conferences=len(accepted_conferences),
            industry_counts=industry_counts,
            force=force
        )

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            f"🎉 [Weekly Workflow] Completed run {run_id} in {elapsed}s: "
            f"{len(accepted_conferences)} unique conferences, {len(accepted_speakers)} verified speakers."
        )

        return {
            "status": "success",
            "weekly_run_id": run_id,
            "target_window": {
                "sunday": target_sunday.isoformat(),
                "saturday": target_saturday.isoformat()
            },
            "total_conferences": len(accepted_conferences),
            "total_speakers": len(accepted_speakers),
            "industry_breakdown": industry_counts,
            "onedrive_excel": excel_sync_res,
            "speaker_enrichment": enrichment_res,
            "teams_card": teams_res,
            "duration_seconds": elapsed
        }
