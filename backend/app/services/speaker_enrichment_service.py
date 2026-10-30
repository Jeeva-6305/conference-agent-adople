import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.orm import Session

from .apollo_service import ApolloService
from .hunter_service import HunterService
from .onedrive_excel_service import OneDriveExcelService
from ..storage.excel_manager import ExcelManager
from ..models import WeeklySpeaker, Speaker
from ..config import settings
from ..ai.extractor import discover_and_verify_linkedin_profile

logger = logging.getLogger(__name__)


def validate_personal_linkedin_url(url: Optional[str]) -> str:
    """Validates that a URL is a genuine personal LinkedIn profile link."""
    if not url:
        return ""
    u = str(url).strip()
    if not u.startswith("http"):
        u = f"https://{u}"
    if "linkedin.com/in/" not in u.lower():
        return ""
    if any(bad in u.lower() for bad in ["/company/", "/school/", "/pulse/", "/feed/", "/jobs/"]):
        return ""
    return u


class SpeakerEnrichmentService:
    """
    Automated Speaker Profile Enrichment Engine:
    1. Uses Apollo API strictly for LinkedIn Profile Discovery (/api/v1/mixed_people/search)
       and candidate resolution for speakers missing LinkedIn URLs.
    2. Uses Hunter.io API official Email Finder (/v2/email-finder) and Email Verifier (/v2/email-verifier)
       strictly for professional business email discovery and verification.
    3. Compares returned attributes (name, company, role) to verify identity before accepting.
    4. Safely updates PostgreSQL database, Local Excel workbook, and OneDrive tbl_weekly_speakers in-place.
    5. Preserves all historical rows, existing emails, table structures, and IDs without duplicates.
    6. Never overwrites a previously verified email with an unverified result.
    7. Gracefully handles API rate limits, credit limits, plan restrictions, and timeouts.
    """

    def __init__(self, db: Session):
        self.db = db
        self.apollo = ApolloService()
        self.hunter = HunterService()
        self.hunter_enabled = getattr(settings, "HUNTER_EMAIL_ENRICHMENT_ENABLED", True)
        self.onedrive_svc = OneDriveExcelService()
        self.excel_mgr = ExcelManager()

    def enrich_single_speaker(
        self,
        speaker_name: str,
        company_name: str = "",
        job_title: str = "",
        personal_linkedin_url: str = "",
        conference_name: str = "",
        location: str = ""
    ) -> Dict[str, Any]:
        """
        Enriches a single speaker:
        1. Resolves missing LinkedIn profile via Apollo People Search or verified identity matching.
        2. Queries Hunter.io Email Finder API for genuine professional email address and verification.
        3. Returns verified enrichment details and status flags.
        """
        clean_name = (speaker_name or "").strip()
        clean_company = (company_name or "").strip()
        clean_title = (job_title or "").strip()
        current_li = validate_personal_linkedin_url(personal_linkedin_url)

        discovered_li = current_li
        linkedin_status = "verified" if current_li else "needs_review"
        professional_email = ""
        email_source = ""
        verification_status = "needs_review"
        enrichment_stage = "pending"

        # -------------------------------------------------------------
        # Step 1: Discover Missing LinkedIn Profile if empty (Apollo only)
        # -------------------------------------------------------------
        if not discovered_li:
            logger.info(f"🔍 [Enrichment] Missing LinkedIn URL for '{clean_name}' at '{clean_company}'. Searching...")
            # Try Apollo Search strictly for LinkedIn discovery
            apollo_search = self.apollo.search_people(
                name=clean_name,
                company=clean_company,
                job_title=clean_title
            )

            if apollo_search.get("status") == "success" and apollo_search.get("linkedin_url"):
                cand_li = validate_personal_linkedin_url(apollo_search.get("linkedin_url"))
                if cand_li:
                    discovered_li = cand_li
                    linkedin_status = "verified"
                    logger.info(f"✅ [Enrichment] Discovered LinkedIn URL via Apollo for '{clean_name}': {discovered_li}")

            # If Apollo search did not return a profile or was restricted, use verified discovery engine
            if not discovered_li:
                try:
                    verified_url = discover_and_verify_linkedin_profile(
                        clean_name, clean_company, clean_title, location or "USA"
                    )
                    verified_url = validate_personal_linkedin_url(verified_url)
                    if verified_url:
                        discovered_li = verified_url
                        linkedin_status = "verified"
                        logger.info(f"✅ [Enrichment] Discovered verified LinkedIn URL for '{clean_name}': {discovered_li}")
                    else:
                        linkedin_status = "not_found"
                        logger.info(f"ℹ️ [Enrichment] No reliable LinkedIn profile confirmed for '{clean_name}' ({clean_company}).")
                except Exception as e:
                    logger.warning(f"⚠️ [Enrichment] LinkedIn discovery notice for '{clean_name}': {e}")
                    linkedin_status = "needs_review"

        # -------------------------------------------------------------
        # Step 2: Query Hunter.io API for Genuine Professional Email
        # -------------------------------------------------------------
        if self.hunter_enabled:
            # Query Hunter Email Finder API using speaker name, company, and LinkedIn URL
            hunter_res = self.hunter.find_email(
                full_name=clean_name,
                company=clean_company,
                linkedin_url=discovered_li
            )

            h_status = hunter_res.get("status")
            if h_status == "success":
                ret_email = hunter_res.get("email")
                if ret_email:
                    professional_email = ret_email
                    email_source = "hunter.io"
                    verification_status = hunter_res.get("verification_status") or "verified"
                    enrichment_stage = "enriched_via_hunter"
                    logger.info(
                        f"✅ [Enrichment] Hunter.io matched email for '{clean_name}': "
                        f"{professional_email} ({verification_status})"
                    )
                else:
                    enrichment_stage = "not_found_in_hunter"
            elif h_status == "quota_exceeded":
                enrichment_stage = "hunter_quota_exceeded"
                logger.warning(f"⚠️ [Enrichment] Hunter.io API quota limit reached: {hunter_res.get('message')}")
            elif h_status == "auth_error":
                enrichment_stage = "hunter_auth_error"
                logger.error(f"❌ [Enrichment] Hunter.io API authentication error: {hunter_res.get('message')}")
            elif h_status == "not_found":
                enrichment_stage = "not_found_in_hunter"
            else:
                enrichment_stage = hunter_res.get("message", "hunter_finder_failed")
        else:
            enrichment_stage = "hunter_enrichment_disabled"

        if discovered_li and linkedin_status == "verified" and not verification_status:
            verification_status = "verified"

        return {
            "speaker_name": clean_name,
            "company_name": clean_company,
            "job_title": clean_title,
            "personal_linkedin_url": discovered_li,
            "linkedin_status": linkedin_status,
            "professional_email": professional_email,
            "email_source_url": email_source,
            "verification_status": verification_status or "needs_review",
            "enrichment_stage": enrichment_stage,
            "last_checked_at": datetime.utcnow().isoformat()
        }

    def enrich_weekly_speakers(
        self,
        speakers: Optional[List[WeeklySpeaker]] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Executes automated enrichment for weekly speakers:
        - Resolves missing LinkedIn URLs via Apollo.
        - Enriches professional emails via Hunter.io API.
        - Updates PostgreSQL, Local Excel, and OneDrive tbl_weekly_speakers in-place.
        - Avoids reprocessing already enriched speakers unless force=True.
        """
        start_time = time.time()
        logger.info("🚀 [Speaker Enrichment] Starting automated speaker LinkedIn (Apollo) & Professional Email (Hunter.io) enrichment...")

        # 1. Fetch existing rows from OneDrive to have the full picture
        onedrive_speaker_rows = {}
        try:
            onedrive_speaker_rows = self.onedrive_svc.get_existing_weekly_speaker_rows_map()
            logger.info(f"Loaded {len(onedrive_speaker_rows)} existing weekly speaker records from OneDrive Excel.")
        except Exception as e:
            logger.warning(f"Notice loading OneDrive speaker rows: {e}")

        # 2. Determine target speakers to process
        if speakers is None:
            # Load from database
            db_query = self.db.query(WeeklySpeaker)
            if not force:
                # Filter for records missing email or missing LinkedIn
                db_speakers = db_query.all()
                target_speakers = [
                    s for s in db_speakers
                    if not s.professional_email or not s.personal_linkedin_url or s.linkedin_status in ["needs_review", ""]
                ]
            else:
                target_speakers = db_query.all()
        else:
            target_speakers = speakers

        logger.info(f"Target speakers eligible for enrichment: {len(target_speakers)}")

        stats = {
            "total_candidates": len(target_speakers),
            "processed": 0,
            "linkedin_discovered": 0,
            "emails_enriched": 0,
            "already_complete": 0,
            "quota_exceeded_count": 0,
            "not_found_count": 0,
            "onedrive_updates": 0,
            "local_excel_updates": 0,
            "db_updates": 0,
            "duration_seconds": 0.0
        }

        for spk in target_speakers:
            s_name = (spk.speaker_name or "").strip()
            s_conf_id = (spk.conference_id or "").strip()
            s_comp = (spk.company_name or "").strip()
            s_role = (spk.job_title or "").strip()
            current_li = (spk.personal_linkedin_url or "").strip()
            current_email = (spk.professional_email or "").strip()

            # Check if OneDrive row has a LinkedIn URL that DB was missing
            od_key = (s_conf_id, s_name.lower())
            od_row_idx = None
            od_vals = None
            if od_key in onedrive_speaker_rows:
                od_row_idx, od_vals = onedrive_speaker_rows[od_key]
                if not current_li and len(od_vals) > 6 and od_vals[6]:
                    current_li = str(od_vals[6]).strip()
                    spk.personal_linkedin_url = current_li
                if not current_email and len(od_vals) > 8 and od_vals[8]:
                    current_email = str(od_vals[8]).strip()
                    spk.professional_email = current_email

            # Skip if already fully enriched and not forced
            if current_li and current_email and not force:
                stats["already_complete"] += 1
                continue

            stats["processed"] += 1

            # Run single enrichment
            result = self.enrich_single_speaker(
                speaker_name=s_name,
                company_name=s_comp,
                job_title=s_role,
                personal_linkedin_url=current_li,
                conference_name=spk.conference_name or ""
            )

            new_li = result.get("personal_linkedin_url") or ""
            new_li_status = result.get("linkedin_status") or "needs_review"
            new_email = result.get("professional_email") or ""
            new_email_source = result.get("email_source_url") or ""
            new_ver_status = result.get("verification_status") or "needs_review"
            stage = result.get("enrichment_stage")

            if stage == "hunter_quota_exceeded":
                stats["quota_exceeded_count"] += 1
            elif stage in ["not_found_in_hunter", "not_found"]:
                stats["not_found_count"] += 1

            has_changes = False

            # Update LinkedIn if newly discovered
            if new_li and new_li != current_li:
                spk.personal_linkedin_url = new_li
                spk.linkedin_status = new_li_status
                stats["linkedin_discovered"] += 1
                has_changes = True
            elif not spk.linkedin_status or spk.linkedin_status != new_li_status:
                spk.linkedin_status = new_li_status
                has_changes = True

            # Update email if discovered, safeguarding against downgrading a verified email
            if new_email and new_email != current_email:
                current_is_verified = (spk.verification_status == "verified" and bool(current_email))
                new_is_verified = (new_ver_status == "verified")
                if not current_is_verified or new_is_verified:
                    spk.professional_email = new_email
                    spk.email_source_url = new_email_source or "hunter.io"
                    stats["emails_enriched"] += 1
                    has_changes = True

            if new_ver_status and spk.verification_status != new_ver_status:
                spk.verification_status = new_ver_status
                has_changes = True

            spk.last_checked_at = datetime.utcnow()

            # -------------------------------------------------------------
            # Storage Sync: DB, Local Excel, and OneDrive in-place update
            # -------------------------------------------------------------
            # A. Update PostgreSQL
            self.db.commit()
            stats["db_updates"] += 1

            # Mirror to primary Speaker table if applicable
            try:
                main_spk = self.db.query(Speaker).filter(
                    Speaker.conference_id == spk.conference_id,
                    Speaker.speaker_name == spk.speaker_name
                ).first()
                if main_spk:
                    if new_li and not main_spk.linkedin_url:
                        main_spk.linkedin_url = new_li
                    self.db.commit()
            except Exception:
                pass

            # B. Update Local Excel in-place
            try:
                local_ok = self.excel_mgr.update_weekly_speaker_enrichment(
                    speaker_id=spk.speaker_id,
                    conference_id=spk.conference_id,
                    speaker_name=spk.speaker_name,
                    personal_linkedin_url=spk.personal_linkedin_url,
                    linkedin_status=spk.linkedin_status,
                    professional_email=spk.professional_email,
                    email_source_url=spk.email_source_url,
                    verification_status=spk.verification_status,
                    last_checked_at=spk.last_checked_at.isoformat()
                )
                if local_ok:
                    stats["local_excel_updates"] += 1
            except Exception as e:
                logger.warning(f"Local Excel enrichment update notice for '{s_name}': {e}")

            # C. Update OneDrive Excel table row in-place
            if od_row_idx is not None and od_vals is not None:
                try:
                    updated_vals = list(od_vals)
                    # Ensure row has at least 18 columns matching table schema
                    while len(updated_vals) < 18:
                        updated_vals.append("")

                    # Col 6: Personal_LinkedIn_URL
                    if spk.personal_linkedin_url:
                        updated_vals[6] = spk.personal_linkedin_url
                    # Col 7: LinkedIn_Status
                    updated_vals[7] = spk.linkedin_status or "needs_review"
                    # Col 8: Professional_Email
                    if spk.professional_email:
                        updated_vals[8] = spk.professional_email
                    # Col 9: Email_Source_URL
                    if spk.email_source_url:
                        updated_vals[9] = spk.email_source_url
                    # Col 11: Verification_Status
                    updated_vals[11] = spk.verification_status or "needs_review"
                    # Col 12: Last_Checked_At
                    updated_vals[12] = spk.last_checked_at.isoformat()

                    od_patch_res = self.onedrive_svc.update_weekly_speaker_row(
                        row_index=od_row_idx,
                        values=updated_vals
                    )
                    if "error" not in od_patch_res:
                        stats["onedrive_updates"] += 1
                except Exception as e:
                    logger.warning(f"OneDrive Excel row PATCH notice for '{s_name}': {e}")

        elapsed = round(time.time() - start_time, 2)
        stats["duration_seconds"] = elapsed
        logger.info(
            f"✅ [Speaker Enrichment] Completed: {stats['processed']} processed in {elapsed}s | "
            f"Emails enriched: {stats['emails_enriched']} | LinkedIn discovered: {stats['linkedin_discovered']} | "
            f"OneDrive updates: {stats['onedrive_updates']} | DB updates: {stats['db_updates']}"
        )
        return stats
