
import html
import os
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
from ..scrapers.base_scraper import BaseScraper, clean_html_text
from ..scrapers.orchestrator import ScraperOrchestrator
from ..scrapers.live_speaker_scraper import (
    fetch_official_site_speakers,
    is_valid_speaker_name,
    _azure_extract_speakers_from_text,
)
from ..ai.extractor import (
    AIConferenceExtractor,
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
    effective_lead = lead_days if lead_days is not None else getattr(settings, "WEEKLY_SCRAPE_LEAD_DAYS", 6)

    # 1. Check if explicit target dates are specified in settings or env (e.g. 15th-21st)
    env_start = getattr(settings, "WEEKLY_TARGET_START_DATE", None) or os.getenv("WEEKLY_TARGET_START_DATE")
    env_end = getattr(settings, "WEEKLY_TARGET_END_DATE", None) or os.getenv("WEEKLY_TARGET_END_DATE")
    if env_start and env_end and not ref_date:
        try:
            target_sunday = date.fromisoformat(str(env_start).strip())
            target_saturday = date.fromisoformat(str(env_end).strip())
            run_id = f"WEEK-{target_sunday.isoformat()}_{target_saturday.isoformat()}"
            return target_sunday, target_saturday, run_id
        except Exception:
            pass

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

    def run_weekly_workflow(
        self,
        force: bool = False,
        target_date: Optional[date] = None,
        candidate_events: Optional[List[Any]] = None
    ) -> Dict[str, Any]:
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
        tz_str = getattr(settings, "WEEKLY_TIMEZONE", "Asia/Kolkata") or "Asia/Kolkata"
        try:
            today = datetime.now(ZoneInfo(tz_str)).date()
        except Exception:
            today = date.today()
        target_sunday, target_saturday, run_id = calculate_weekly_target_range(ref_date=target_date)
        logger.info(
            f"📅 [Weekly Workflow] Starting weekly conference run: {run_id} "
            f"(Target Window: Sunday {target_sunday} to Saturday {target_saturday})..."
        )

        # 1. Harvest raw candidate events across all configured sources
        raw_events = self.orchestrator.collect_all()
        if candidate_events:
            raw_events.extend(candidate_events)
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
        confs_with_speaker_status_flip: set = set()

        # Load existing conferences for this week to prevent DB duplicates
        existing_weekly_confs = self.db.query(WeeklyConference).filter(
            WeeklyConference.start_date >= target_sunday,
            WeeklyConference.start_date <= target_saturday
        ).all()
        existing_conf_map = {
            (normalize_title(c.conference_name), c.start_date.isoformat()): c
            for c in existing_weekly_confs
        }
        existing_canon_map = {
            canonicalize_url(c.official_event_url): c
            for c in existing_weekly_confs
            if canonicalize_url(c.official_event_url) and len(canonicalize_url(c.official_event_url)) > 12
        }

        def _persist_speaker_candidates(
            conf_record: WeeklyConference,
            candidate_speakers: List[Dict[str, str]],
            source_fallback_url: str,
            src_key: str = "",
        ) -> int:
            existing_spks = self.db.query(WeeklySpeaker).filter(
                WeeklySpeaker.conference_id == conf_record.conference_id
            ).all()
            existing_spk_names = {s.speaker_name.strip().lower() for s in existing_spks}
            new_cnt = 0

            for cand in candidate_speakers:
                s_name = clean_html_text(cand.get("name", "")).strip()
                n_key = s_name.lower()
                if not s_name or n_key in existing_spk_names:
                    continue

                raw_role = clean_html_text(cand.get("role", "")).strip()
                raw_comp = clean_html_text(cand.get("company", "")).strip()
                cand_li = validate_personal_linkedin_url(cand.get("linkedin", ""))

                c_name, c_role, c_comp, _, c_li = clean_and_resolve_speaker(
                    s_name,
                    raw_role,
                    raw_comp,
                    conf_title=conf_record.conference_name,
                    location=conf_record.city,
                )
                if not c_name:
                    continue
                if c_name.lower() in existing_spk_names:
                    continue
                existing_spk_names.add(c_name.lower())

                li_url = validate_personal_linkedin_url(cand_li or c_li)
                if not li_url:
                    li_url = validate_personal_linkedin_url(
                        discover_and_verify_linkedin_profile(c_name, c_comp, c_role, conf_record.city)
                    ) or ""

                li_status = "verified" if li_url else "needs_review"
                # Only an actual verified email counts as verification_status == "verified"
                ver_status = "needs_review"

                speaker_id = generate_weekly_speaker_id(conf_record.conference_id, c_name)
                spk_record = WeeklySpeaker(
                    speaker_id=speaker_id,
                    conference_id=conf_record.conference_id,
                    conference_name=conf_record.conference_name,
                    speaker_name=c_name,
                    job_title=c_role or "",
                    company_name=c_comp or "",
                    personal_linkedin_url=li_url,
                    linkedin_status=li_status,
                    professional_email="",
                    email_source_url="",
                    speaker_source_url=cand.get("source_url") or source_fallback_url or conf_record.official_event_url,
                    verification_status=ver_status,
                    weekly_run_id=run_id,
                    last_checked_at=datetime.utcnow()
                )
                self.db.add(spk_record)
                accepted_speakers.append(spk_record)
                new_cnt += 1
                if src_key and src_key in log_by_source:
                    log_by_source[src_key]["speakers_found"] += 1

            if len(existing_spk_names) > 0:
                if (conf_record.speaker_status or "No") != "Yes":
                    confs_with_speaker_status_flip.add(conf_record.conference_id)
                conf_record.speaker_status = "Yes"
            return new_cnt

        # Pre-deduplicate identical raw events sharing (title, date, canonical_url) across discovery feeds
        deduped_raw_events = []
        seen_raw_sigs = set()
        for r_ev in raw_events:
            sig = (
                normalize_title(clean_html_text(r_ev.raw_title or "")),
                str(r_ev.raw_date or "")[:10],
                canonicalize_url(r_ev.source_url or ""),
            )
            if sig in seen_raw_sigs:
                continue
            seen_raw_sigs.add(sig)
            deduped_raw_events.append(r_ev)

        events_to_extract = []
        for raw in deduped_raw_events:
            pre_title_key = normalize_title(clean_html_text(raw.raw_title or ""))
            pre_date_str = str(raw.raw_date or "")[:10]
            pre_key = (pre_title_key, pre_date_str)
            canon_raw = canonicalize_url(raw.source_url or "")
            existing_fast = existing_conf_map.get(pre_key) or (
                existing_canon_map.get(canon_raw) if canon_raw and len(canon_raw) > 12 else None
            )
            if existing_fast and (existing_fast.speaker_status or "No") == "Yes":
                fast_key = (normalize_title(existing_fast.conference_name), existing_fast.start_date.isoformat())
                if fast_key not in seen_conf_keys:
                    seen_conf_keys.add(fast_key)
                    if raw.source_name in log_by_source:
                        log_by_source[raw.source_name]["conferences_accepted"] += 1
                if existing_fast not in accepted_conferences:
                    accepted_conferences.append(existing_fast)
                continue
            events_to_extract.append(raw)

        extracted_by_idx: Dict[int, Any] = {}
        if events_to_extract:
            from concurrent.futures import ThreadPoolExecutor
            logger.info(f"⚡ [Weekly Workflow] Extracting & validating {len(events_to_extract)} candidate events concurrently...")

            def _extract_one(idx_item: Tuple[int, Any]):
                i, r_ev = idx_item
                try:
                    return i, self.extractor.extract_conference_details(r_ev, mode="weekly")
                except Exception as ex:
                    logger.debug(f"Concurrent extraction notice for '{r_ev.raw_title}': {ex}")
                    return i, None

            with ThreadPoolExecutor(max_workers=4) as epool:
                futs = [epool.submit(_extract_one, (i, r_ev)) for i, r_ev in enumerate(events_to_extract)]
                for fut in futs:
                    try:
                        idx_r, ext_res = fut.result(timeout=60)
                        extracted_by_idx[idx_r] = ext_res
                    except Exception:
                        pass

        for idx_r, raw in enumerate(events_to_extract):
            try:
                extracted = extracted_by_idx.get(idx_r)
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

                title_norm = clean_html_text(extracted.conference_title).strip()
                title_key = normalize_title(title_norm)
                dedup_key = (title_key, conf_start.isoformat())
                canon_off_url = canonicalize_url(extracted.official_conference_url or raw.source_url)
                is_first_in_batch = dedup_key not in seen_conf_keys
                seen_conf_keys.add(dedup_key)

                # Track accepted count for source telemetry
                src_key = raw.source_name
                if is_first_in_batch and src_key in log_by_source:
                    log_by_source[src_key]["conferences_accepted"] += 1

                # Clean City / State split without duplicating state inside city
                raw_city = clean_html_text(extracted.city or "").strip()
                if "," in raw_city:
                    c_parts = [p.strip() for p in raw_city.split(",", 1)]
                    city_val = c_parts[0]
                    state_val = c_parts[1][:10]
                else:
                    city_val = "" if raw_city.upper() == "USA" else raw_city
                    state_val = ""

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

                # Check if conference already exists in DB (by normalized title+date or canonical URL)
                existing_match = existing_conf_map.get(dedup_key) or (
                    existing_canon_map.get(canon_off_url) if canon_off_url else None
                )
                if existing_match:
                    conf_record = existing_match
                    conf_record.last_checked_at = datetime.utcnow()
                    conf_record.link_status = link_status
                    if not (conf_record.city or "").strip() and city_val:
                        conf_record.city = city_val
                    if not (conf_record.state or "").strip() and state_val:
                        conf_record.state = state_val
                    if not (conf_record.industry or "").strip() and extracted.industry_category:
                        conf_record.industry = extracted.industry_category
                else:
                    conf_id = generate_weekly_conference_id(title_norm, conf_start)
                    conf_record = WeeklyConference(
                        conference_id=conf_id,
                        conference_name=title_norm,
                        start_date=conf_start,
                        end_date=conf_end,
                        city=city_val,
                        state=state_val,
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
                    if canon_off_url and len(canon_off_url) > 12:
                        existing_canon_map[canon_off_url] = conf_record

                if conf_record not in accepted_conferences:
                    accepted_conferences.append(conf_record)

                # 4. Extract genuine speakers for this conference (zero placeholder fallbacks)
                candidate_speakers: List[Dict[str, str]] = []
                if extracted.speaker_details:
                    for spk_d in extracted.speaker_details:
                        s_name = clean_html_text(spk_d.speaker_name or "").strip()
                        if s_name and is_valid_speaker_name(s_name):
                            s_role = (spk_d.job_role_designation or "").strip()
                            if s_role.lower() in ("speaker", "keynote speaker", "featured guest", "event host & organizer", "n/a", "tbd"):
                                s_role = ""
                            s_comp = (spk_d.company_name or spk_d.company_organization or "").strip()
                            if s_comp.lower() in ("industry organization", "industry trade organizer", "n/a", "tbd", conf_record.conference_name.lower()):
                                s_comp = ""
                            candidate_speakers.append({
                                "name": s_name,
                                "role": s_role,
                                "company": s_comp,
                                "linkedin": getattr(spk_d, "linkedin_url", "") or ""
                            })

                if extracted.speakers:
                    for idx, s_name in enumerate(extracted.speakers):
                        s_name = clean_html_text(s_name or "").strip()
                        if s_name and is_valid_speaker_name(s_name):
                            if not any(cs["name"].lower() == s_name.lower() for cs in candidate_speakers):
                                t_comp = (
                                    extracted.speaker_titles_companies[idx]
                                    if (extracted.speaker_titles_companies and idx < len(extracted.speaker_titles_companies))
                                    else ""
                                )
                                candidate_speakers.append({
                                    "name": s_name,
                                    "role": "",
                                    "company": t_comp or "",
                                    "linkedin": ""
                                })

                # Also crawl official event URL / speaker subpages if < 3 speakers extracted from summary text
                if len(candidate_speakers) < 3:
                    for target_url in [conf_record.official_event_url, raw.source_url]:
                        if target_url and target_url.startswith("http"):
                            try:
                                live_spks = fetch_official_site_speakers(target_url, conf_record.conference_name)
                                for lspk in live_spks:
                                    l_name = clean_html_text(lspk.get("speaker_name") or lspk.get("name") or "").strip()
                                    if l_name and is_valid_speaker_name(l_name) and not any(cs["name"].lower() == l_name.lower() for cs in candidate_speakers):
                                        candidate_speakers.append({
                                            "name": l_name,
                                            "role": lspk.get("job_role_designation") or lspk.get("role") or "",
                                            "company": lspk.get("company_name") or lspk.get("organization") or "",
                                            "linkedin": lspk.get("linkedin_url", ""),
                                            "source_url": lspk.get("source_url", target_url),
                                        })
                            except Exception as e:
                                logger.debug(f"Weekly speaker retry notice for {conf_record.conference_name}: {e}")

                _persist_speaker_candidates(
                    conf_record,
                    candidate_speakers,
                    conf_record.official_event_url or raw.source_url,
                    src_key=src_key,
                )

            except Exception as e:
                logger.error(f"Error processing weekly event: {e}", exc_info=True)

        self.db.flush()

        # 4b. Recover speakers for ANY target-window conference that still has 0 speakers (official site + Tavily)
        window_confs = self.db.query(WeeklyConference).filter(
            WeeklyConference.start_date >= target_sunday,
            WeeklyConference.start_date <= target_saturday
        ).order_by(WeeklyConference.start_date.asc()).all()

        tavily_helper = BaseScraper("weekly_speaker_recovery", "")
        confs_needing_recovery = []
        for conf_rec in window_confs:
            spk_cnt = self.db.query(WeeklySpeaker).filter(
                WeeklySpeaker.conference_id == conf_rec.conference_id
            ).count()
            if spk_cnt > 0:
                if (conf_rec.speaker_status or "No") != "Yes":
                    conf_rec.speaker_status = "Yes"
                    confs_with_speaker_status_flip.add(conf_rec.conference_id)
                continue
            confs_needing_recovery.append(conf_rec)

        def _recover_one_conf_speakers(conf_id: str, conf_name: str, off_url: str, src_url: str) -> Tuple[str, List[Dict[str, str]]]:
            recovered: List[Dict[str, str]] = []
            for u in [off_url, src_url]:
                if u and u.startswith("http"):
                    try:
                        live_spks = fetch_official_site_speakers(u, conf_name)
                        for lspk in live_spks:
                            l_name = clean_html_text(lspk.get("speaker_name") or lspk.get("name") or "").strip()
                            if l_name and is_valid_speaker_name(l_name) and not any(r["name"].lower() == l_name.lower() for r in recovered):
                                recovered.append({
                                    "name": l_name,
                                    "role": lspk.get("job_role_designation") or lspk.get("role") or "",
                                    "company": lspk.get("company_name") or lspk.get("organization") or "",
                                    "linkedin": lspk.get("linkedin_url", ""),
                                    "source_url": lspk.get("source_url", u),
                                })
                    except Exception:
                        pass

            # Sanctioned Tavily speaker lookup when official URL yielded 0 speakers
            if len(recovered) == 0 and getattr(settings, "TAVILY_API_KEY", ""):
                try:
                    t_results = tavily_helper.tavily_search(
                        f'"{conf_name}" 2026 (speakers OR keynote OR faculty OR panelists)',
                        max_results=5,
                    )
                    snippet_blocks: List[str] = []
                    for tr in t_results:
                        r_url = tr.get("url", "")
                        r_content = clean_html_text(f"{tr.get('title', '')}\n{tr.get('content', '')}")
                        if r_content:
                            snippet_blocks.append(f"[{r_url}]\n{r_content}")
                        if r_url and any(k in r_url.lower() for k in ["speaker", "agenda", "program", "faculty", "lineup"]):
                            for lspk in fetch_official_site_speakers(r_url, conf_name):
                                l_name = clean_html_text(lspk.get("speaker_name") or lspk.get("name") or "").strip()
                                if l_name and is_valid_speaker_name(l_name) and not any(r["name"].lower() == l_name.lower() for r in recovered):
                                    recovered.append({
                                        "name": l_name,
                                        "role": lspk.get("job_role_designation") or "",
                                        "company": lspk.get("company_name") or "",
                                        "linkedin": lspk.get("linkedin_url", ""),
                                        "source_url": lspk.get("source_url", r_url),
                                    })
                    if len(recovered) == 0 and snippet_blocks:
                        ai_spks = _azure_extract_speakers_from_text(
                            "\n\n".join(snippet_blocks),
                            conf_name,
                            off_url or src_url or "",
                        )
                        for lspk in ai_spks:
                            l_name = clean_html_text(lspk.get("speaker_name") or "").strip()
                            if l_name and is_valid_speaker_name(l_name) and not any(r["name"].lower() == l_name.lower() for r in recovered):
                                recovered.append({
                                    "name": l_name,
                                    "role": lspk.get("job_role_designation") or "",
                                    "company": lspk.get("company_name") or "",
                                    "linkedin": lspk.get("linkedin_url", ""),
                                    "source_url": lspk.get("source_url") or off_url or src_url,
                                })
                except Exception as e:
                    logger.debug(f"Tavily speaker recovery notice for '{conf_name}': {e}")
            return conf_id, recovered

        if confs_needing_recovery:
            from concurrent.futures import ThreadPoolExecutor
            recovery_results: Dict[str, List[Dict[str, str]]] = {}
            with ThreadPoolExecutor(max_workers=5) as rpool:
                futs = [
                    rpool.submit(
                        _recover_one_conf_speakers,
                        c.conference_id,
                        c.conference_name,
                        c.official_event_url or "",
                        c.source_url or "",
                    )
                    for c in confs_needing_recovery
                ]
                for fut in futs:
                    try:
                        cid_r, recs = fut.result(timeout=45)
                        if recs:
                            recovery_results[cid_r] = recs
                    except Exception:
                        pass

            for conf_rec in confs_needing_recovery:
                recs = recovery_results.get(conf_rec.conference_id, [])
                if recs:
                    added_rec = _persist_speaker_candidates(
                        conf_rec,
                        recs,
                        conf_rec.official_event_url or conf_rec.source_url or "",
                        src_key=conf_rec.source_name or "",
                    )
                    if added_rec > 0:
                        logger.info(f"✅ Recovered {added_rec} genuine speaker(s) for '{conf_rec.conference_name}'.")

        self.db.commit()

        # Re-load all conferences & speakers in target Sunday-Saturday window so downstream sync/enrichment sees complete state
        window_confs = self.db.query(WeeklyConference).filter(
            WeeklyConference.start_date >= target_sunday,
            WeeklyConference.start_date <= target_saturday
        ).order_by(WeeklyConference.start_date.asc()).all()
        window_conf_ids = [c.conference_id for c in window_confs]
        window_speakers = (
            self.db.query(WeeklySpeaker).filter(WeeklySpeaker.conference_id.in_(window_conf_ids)).all()
            if window_conf_ids else []
        )

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
                conferences=window_confs,
                speakers=window_speakers,
                logs=source_run_logs
            )
            logger.info(f"✅ [Weekly Workflow] Local Excel sync complete ({len(window_confs)} confs, {len(window_speakers)} spks).")
        except Exception as e:
            logger.warning(f"⚠️ [Weekly Workflow] Local Excel sync warning: {e}", exc_info=True)

        # 7. Mirror into primary Conference and Speaker tables (status='scheduled') for UI visibility
        try:
            from ..models import Conference, Speaker
            for conf_rec in window_confs:
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
                        city=conf_rec.city or "",
                        country=conf_rec.country or "USA",
                        venue=f"{conf_rec.city} Convention Center" if conf_rec.city else "Convention Center",
                        industry_category=conf_rec.industry or "Enterprise AI / Technology",
                        official_conference_url=conf_rec.official_event_url,
                        registration_url=conf_rec.official_event_url,
                        source_url=conf_rec.source_url or conf_rec.official_event_url,
                        source_name=conf_rec.source_name,
                        is_published_to_excel=False,
                        speakers_available="Yes" if conf_rec.speaker_status == "Yes" else "No",
                        status="scheduled"
                    )
                    self.db.add(main_conf)
                else:
                    exist_main.speakers_available = "Yes" if conf_rec.speaker_status == "Yes" else exist_main.speakers_available

            for spk_rec in window_speakers:
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
            f"☁️ [Weekly Workflow] Syncing {len(window_confs)} conferences, "
            f"{len(window_speakers)} speakers, and {len(source_run_logs)} logs to OneDrive Excel..."
        )
        try:
            excel_sync_res = self.onedrive_svc.sync_all_weekly(
                conferences=window_confs,
                speakers=window_speakers,
                logs=source_run_logs,
                run_id=run_id
            )
            for flip_cid in confs_with_speaker_status_flip:
                try:
                    self.onedrive_svc.update_weekly_conference_speaker_status(flip_cid, "Yes")
                except Exception:
                    pass
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

        # 8b. Automated Speaker LinkedIn Resolution & Professional Email Enrichment (Prospeo / Apollo / Hunter)
        enrichment_res = {}
        speaker_enrichment_enabled = (
            getattr(settings, "PROSPEO_ENRICHMENT_ENABLED", True)
            or getattr(settings, "APOLLO_ENRICHMENT_ENABLED", True)
            or getattr(settings, "HUNTER_EMAIL_ENRICHMENT_ENABLED", True)
        )
        speakers_needing_enrichment = [
            s for s in window_speakers
            if not (s.professional_email or "").strip() or not (s.personal_linkedin_url or "").strip()
        ]
        if speaker_enrichment_enabled and speakers_needing_enrichment:
            try:
                from .speaker_enrichment_service import SpeakerEnrichmentService
                enrich_svc = SpeakerEnrichmentService(self.db)
                enrichment_res = enrich_svc.enrich_weekly_speakers(speakers=speakers_needing_enrichment, sync_verified=False)
                logger.info(f"✅ [Weekly Workflow] Automated speaker enrichment complete: {enrichment_res}")
            except Exception as e:
                logger.warning(f"⚠️ [Weekly Workflow] Speaker enrichment notice: {e}")

        # 8c. Automated Weekly Attendee Collection & OneDrive Sync
        attendee_res = {}
        if getattr(settings, "WEEKLY_ATTENDEE_COLLECTION_ENABLED", True):
            try:
                from .weekly_attendee_service import WeeklyAttendeeService
                att_svc = WeeklyAttendeeService(self.db)
                attendee_res = att_svc.collect_weekly_attendees(run_id=run_id, force=False, sync_verified=False)
                logger.info(f"✅ [Weekly Workflow] Automated attendee collection complete: {attendee_res}")
            except Exception as e:
                logger.warning(f"⚠️ [Weekly Workflow] Attendee collection notice: {e}")

        # 8d. Automated Weekly Exhibitor Collection & OneDrive Sync
        exhibitor_res = {}
        if getattr(settings, "WEEKLY_EXHIBITOR_COLLECTION_ENABLED", True):
            try:
                from .weekly_exhibitor_service import WeeklyExhibitorService
                exh_svc = WeeklyExhibitorService(self.db)
                exhibitor_res = exh_svc.collect_weekly_exhibitors(run_id=run_id, force=False, sync_verified=False)
                logger.info(f"✅ [Weekly Workflow] Automated exhibitor collection complete: {exhibitor_res}")
            except Exception as e:
                logger.warning(f"⚠️ [Weekly Workflow] Exhibitor collection notice: {e}")

        # 8e. Automated Sync to Verified Data Sheet (Aggregates new speakers, attendees, exhibitors)
        verified_res = {}
        try:
            from .verified_data_service import VerifiedDataService
            v_svc = VerifiedDataService(self.db)
            verified_res = v_svc.sync_all_verified_data()
            logger.info(f"✅ [Weekly Workflow] Automated Verified Data sync complete: {verified_res}")
        except Exception as e:
            logger.warning(f"⚠️ [Weekly Workflow] Verified Data sync notice: {e}", exc_info=True)

        # 8f. Automated Strategic ICP Scoring & Latest Week Scoring Sheet Sync (Runs on new Verified Data)
        icp_res = {}
        if getattr(settings, "WEEKLY_ICP_SCORING_ENABLED", True):
            try:
                from .icp_scoring_service import ICPScoringService
                icp_svc = ICPScoringService(self.db)
                icp_res = icp_svc.score_and_publish_weekly_run(run_id=run_id)
                logger.info(f"✅ [Weekly Workflow] Automated ICP scoring & lead segregation complete: {icp_res}")
            except Exception as e:
                logger.warning(f"⚠️ [Weekly Workflow] ICP scoring notice: {e}", exc_info=True)

        # 7. One General Weekly Inbound Summary Teams Card
        # Industry-wise conference counts across all active target-window conferences
        industry_counts: Dict[str, int] = {}
        for c in window_confs:
            cat = c.industry or "Enterprise AI / Technology"
            main_cat = cat.split("/")[0].strip()
            industry_counts[main_cat] = industry_counts.get(main_cat, 0) + 1

        teams_res = self.teams_svc.send_weekly_summary_card(
            db=self.db,
            weekly_run_id=run_id,
            start_date=target_sunday,
            end_date=target_saturday,
            total_conferences=len(window_confs),
            industry_counts=industry_counts,
            force=force
        )

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            f"🎉 [Weekly Workflow] Completed run {run_id} in {elapsed}s: "
            f"{len(window_confs)} unique conferences, {len(window_speakers)} speakers "
            f"({len(accepted_speakers)} newly added)."
        )

        return {
            "status": "success",
            "weekly_run_id": run_id,
            "target_window": {
                "sunday": target_sunday.isoformat(),
                "saturday": target_saturday.isoformat()
            },
            "total_conferences": len(window_confs),
            "total_speakers": len(window_speakers),
            "newly_added_speakers": len(accepted_speakers),
            "industry_breakdown": industry_counts,
            "onedrive_excel": excel_sync_res,
            "speaker_enrichment": enrichment_res,
            "attendees": attendee_res,
            "exhibitors": exhibitor_res,
            "icp_scoring": icp_res,
            "teams_card": teams_res,
            "duration_seconds": elapsed
        }
