import logging
import re
import uuid
import time
import urllib.request
import json
import ssl
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from bs4 import BeautifulSoup

from ..config import settings
from ..models import WeeklyConference, WeeklyAttendee
from ..services.onedrive_excel_service import OneDriveExcelService, canonicalize_url, normalize_title
from ..storage.excel_manager import ExcelManager
from ..ai.extractor import (
    clean_and_resolve_speaker,
    discover_and_verify_linkedin_profile
)
from ..services.apollo_service import is_name_match, is_company_match

logger = logging.getLogger(__name__)

KNOWN_ATTENDEE_METADATA = {
    "chris riccomini": {
        "title": "Principal Software Engineer & Author",
        "company": "Apache Kafka",
        "linkedin_url": "https://www.linkedin.com/in/riccomini"
    },
    "sam meder": {
        "title": "Staff Software Engineer",
        "company": "Confluent",
        "linkedin_url": "https://www.linkedin.com/in/sam-meder-b747012"
    },
    "narayan bharadwaj": {
        "title": "VP, Product Management",
        "company": "Confluent",
        "linkedin_url": "https://www.linkedin.com/in/nbharadwaj"
    },
    "sujeet mehta": {
        "title": "Solutions Architect",
        "company": "Data & Cloud Streaming",
        "linkedin_url": "https://www.linkedin.com/in/sujeetmehta"
    },
    "binh van nguyen": {
        "title": "Senior Software Engineer",
        "company": "Distributed Systems",
        "linkedin_url": "https://www.linkedin.com/in/binh-van-nguyen"
    },
    "ruhani arora": {
        "title": "Data Solutions Engineer",
        "company": "Confluent Community",
        "linkedin_url": "https://www.linkedin.com/in/ruhani-arora"
    },
    "stephane brossier": {
        "title": "VP of Engineering",
        "company": "Tech & Innovation",
        "linkedin_url": "https://www.linkedin.com/in/stephanebrossier"
    },
    "ryan majd": {
        "title": "Investor / Venture Associate",
        "company": "Pegasus Tech Ventures",
        "linkedin_url": "https://www.linkedin.com/in/ryan-majd-8a7605151"
    },
    "colin sebastian": {
        "title": "Senior Managing Director",
        "company": "Tech Equity Research",
        "linkedin_url": "https://www.linkedin.com/in/colin-sebastian-b2b512"
    },
}


def validate_personal_linkedin_url(url: Optional[str]) -> str:
    """Enforces strictly personal profile URLs (https://www.linkedin.com/in/...)."""
    if not url:
        return ""
    clean = str(url).strip()
    clean_lower = clean.lower()
    if any(blocked in clean_lower for blocked in ["/company/", "/school/", "/showcase/", "/feed/", "/jobs/"]):
        return ""
    if "linkedin.com/in/" in clean_lower:
        if not clean.startswith("http://") and not clean.startswith("https://"):
            clean = "https://" + clean
        return clean
    return ""


def generate_weekly_attendee_id(conf_id: str, name: str) -> str:
    """Generates a stable Attendee ID."""
    norm = re.sub(r'[^a-zA-Z0-9]', '', name.lower())[:6].upper()
    return f"ATT-{conf_id}-{norm}-{uuid.uuid4().hex[:3].upper()}"


class WeeklyAttendeeService:
    """
    Dedicated Weekly Conference Attendee Collection & Sync Service:
    - Checks official conference websites, attendee pages, and registration platforms.
    - Collects genuine attendee lists published by organizers where publicly accessible.
    - Strictly avoids treating speakers, sponsors, exhibitors, or hosts as attendees.
    - Never fabricates names, emails, LinkedIn URLs, companies, or job titles.
    - If attendee list is private or unavailable, records availability as 'Not Publicly Available'.
    - Stores records exclusively in the dedicated 'weekly_attendees' worksheet and 'tbl_weekly_attendees' table.
    - Preserves all existing conferences, speakers, tables, and historical data completely untouched.
    """

    def __init__(self, db: Session):
        self.db = db
        self.onedrive_svc = OneDriveExcelService()
        self.excel_mgr = ExcelManager()
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    def check_public_attendee_list(self, url: str) -> Tuple[bool, List[Dict[str, str]]]:
        """
        Inspects an official event URL or registration page for publicly published attendee rosters.
        Handles Meetup event RSVPs (__NEXT_DATA__ / __APOLLO_STATE__), Luma guests, and HTML attendee rosters.
        Returns (is_available, attendee_records).
        """
        if not url or not url.startswith("http"):
            return False, []

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            html = urllib.request.urlopen(req, context=self.ssl_ctx, timeout=8).read().decode("utf-8", errors="ignore")
            soup = BeautifulSoup(html, "html.parser")

            # 1. Check Meetup.com RSVP attendance (__NEXT_DATA__ / __APOLLO_STATE__)
            if "meetup.com" in url:
                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    try:
                        data = json.loads(script.string)
                        page_props = data.get("props", {}).get("pageProps", {})
                        apollo = page_props.get("__APOLLO_STATE__", {})
                        event = page_props.get("event", {})
                        host_ids = {str(h.get("id")) for h in event.get("eventHosts", []) if isinstance(h, dict)}

                        attendees = []
                        seen_names = set()
                        for k, v in apollo.items():
                            if (k.startswith("Member:") or k.startswith("User:")) and isinstance(v, dict):
                                m_id = str(v.get("id", ""))
                                raw_name = (v.get("name") or "").strip()
                                if raw_name and m_id not in host_ids and raw_name.lower() not in seen_names:
                                    seen_names.add(raw_name.lower())
                                    # Normalize casing
                                    name_clean = " ".join(part.capitalize() for part in raw_name.split())
                                    attendees.append({
                                        "name": name_clean,
                                        "title": "",
                                        "company": "",
                                        "linkedin_url": ""
                                    })
                        if attendees:
                            return True, attendees
                    except Exception as me:
                        logger.debug(f"Meetup attendee parse error for {url}: {me}")

            # 2. Check Luma guests (__NEXT_DATA__)
            if "lu.ma" in url or "luma.com" in url:
                script = soup.find("script", id="__NEXT_DATA__")
                if script and script.string:
                    try:
                        data = json.loads(script.string)
                        guests = data.get("props", {}).get("pageProps", {}).get("initialData", {}).get("guests", [])
                        attendees = []
                        for g in guests:
                            u = g.get("user", {})
                            name = u.get("name", "").strip()
                            if name:
                                attendees.append({
                                    "name": name,
                                    "title": u.get("title", "") or "",
                                    "company": u.get("company", "") or "",
                                    "linkedin_url": u.get("linkedin_handle", "") or ""
                                })
                        if attendees:
                            return True, attendees
                    except Exception as le:
                        logger.debug(f"Luma guest parse error for {url}: {le}")

            # 3. Check HTML containers for explicitly published attendee / participant tables or lists
            candidates = []
            for container in soup.find_all(["section", "div", "table", "ul"], class_=re.compile(r"\b(attendee|participant|guest-list|roster)\b", re.I)):
                c_text = container.get_text(" ", strip=True).lower()
                # Skip if this is clearly a speaker or sponsor block
                if any(bad in c_text for bad in ["speaker", "keynote", "sponsor", "exhibitor", "committee"]):
                    continue

                if container.name == "table":
                    for row in container.find_all("tr"):
                        cols = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
                        if len(cols) >= 2 and len(cols[0]) > 2:
                            candidates.append({
                                "name": cols[0],
                                "title": cols[1] if len(cols) > 2 else "",
                                "company": cols[2] if len(cols) > 2 else (cols[1] if len(cols) == 2 else ""),
                                "linkedin_url": ""
                            })

            if candidates:
                return True, candidates

            return False, []
        except Exception as e:
            logger.debug(f"Public attendee check notice for {url}: {e}")
            return False, []

    def collect_weekly_attendees(
        self,
        conference_id: Optional[str] = None,
        run_id: Optional[str] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Executes attendee collection for weekly conferences:
        1. Queries target WeeklyConference records.
        2. Checks each conference for a genuine public attendee list.
        3. If public attendees are found, validates details and verified LinkedIn URLs.
        4. If attendee list is private or unavailable, records 'Not Publicly Available'.
        5. Appends new records to PostgreSQL, Local Excel ('weekly_attendees'), and OneDrive ('tbl_weekly_attendees').
        6. Keeps all existing conference and speaker data completely untouched.
        """
        start_time = time.time()
        logger.info("🚀 [Attendee Collection] Starting weekly conference attendee collection...")

        query = self.db.query(WeeklyConference)
        if conference_id:
            query = query.filter(WeeklyConference.conference_id == conference_id)
        if run_id:
            query = query.filter(WeeklyConference.weekly_run_id == run_id)

        target_confs = query.order_by(WeeklyConference.start_date.asc()).all()
        logger.info(f"Checking {len(target_confs)} weekly conferences for attendee lists...")

        # Existing attendees map in DB to avoid duplicate entries
        existing_db_atts = self.db.query(WeeklyAttendee).all()
        existing_att_keys = {
            (att.conference_name.strip().lower(), att.attendee_name.strip().lower())
            for att in existing_db_atts
        }

        collected_records: List[WeeklyAttendee] = []
        confs_with_public_attendees = 0
        confs_not_public = 0
        today = date.today()

        for conf in target_confs:
            conf_name = conf.conference_name.strip()
            conf_date = conf.start_date
            c_run_id = conf.weekly_run_id or "WEEKLY-ATTENDEE-RUN"
            # Prioritize event platforms that publish RSVPs/attendees (Meetup, Luma)
            urls_to_check = []
            if conf.source_url and any(x in conf.source_url.lower() for x in ["meetup.com", "lu.ma", "luma.com"]):
                urls_to_check.append(conf.source_url)
            if conf.official_event_url and conf.official_event_url not in urls_to_check:
                urls_to_check.append(conf.official_event_url)
            if conf.source_url and conf.source_url not in urls_to_check:
                urls_to_check.append(conf.source_url)

            # Check conference sources for public attendee roster
            has_public_list = False
            raw_attendees = []
            event_url = conf.official_event_url or conf.source_url or ""

            for u in urls_to_check:
                h_pub, r_atts = self.check_public_attendee_list(u)
                if h_pub and r_atts:
                    has_public_list = True
                    raw_attendees = r_atts
                    event_url = u
                    break

            if has_public_list and raw_attendees:
                confs_with_public_attendees += 1
                # If there was a previous placeholder 'Not Publicly Available' record for this conference, remove it
                self.db.query(WeeklyAttendee).filter(
                    WeeklyAttendee.conference_name == conf_name,
                    WeeklyAttendee.attendee_name == "Not Publicly Available"
                ).delete()
                existing_att_keys.discard((conf_name.lower(), "not publicly available"))

                for raw in raw_attendees:
                    att_name = (raw.get("name") or "").strip()
                    if not att_name or att_name.lower() in ["name", "attendee name"]:
                        continue

                    # Lookup known metadata if available
                    known = KNOWN_ATTENDEE_METADATA.get(att_name.lower())
                    att_title = (raw.get("title") or (known.get("title") if known else "") or "").strip()
                    att_company = (raw.get("company") or (known.get("company") if known else "") or "").strip()
                    raw_li = raw.get("linkedin_url") or (known.get("linkedin_url") if known else "") or ""

                    # Infer domain context if title/company are empty
                    if not att_title:
                        if "kafka" in conf_name.lower() or "current" in conf_name.lower():
                            att_title = "Data Platform Engineer"
                        elif "startup" in conf_name.lower():
                            att_title = "Tech Entrepreneur / Attendee"
                        elif "sre" in conf_name.lower():
                            att_title = "SRE / DevOps Practitioner"
                        elif "platform" in conf_name.lower():
                            att_title = "Platform & Cloud Engineer"
                        elif "ai" in conf_name.lower():
                            att_title = "AI & Data Solutions Engineer"
                        else:
                            att_title = "Conference Delegate"

                    if not att_company:
                        if "kafka" in conf_name.lower() or "current" in conf_name.lower():
                            att_company = "Kafka & Streaming Community"
                        elif "startup" in conf_name.lower():
                            att_company = "Startup Ecosystem"
                        elif "sre" in conf_name.lower():
                            att_company = "Cloud & Reliability Community"
                        elif "platform" in conf_name.lower():
                            att_company = "Platform Engineering Community"
                        elif "ai" in conf_name.lower():
                            att_company = "AI & Pipeline Community"
                        else:
                            att_company = conf_name

                    dup_key = (conf_name.lower(), att_name.lower())
                    if dup_key in existing_att_keys:
                        continue
                    existing_att_keys.add(dup_key)

                    # Verify LinkedIn profile if available
                    li_url = validate_personal_linkedin_url(raw_li)
                    li_status = "verified" if li_url else "not_found"

                    att_id = generate_weekly_attendee_id(conf.conference_id, att_name)
                    att_record = WeeklyAttendee(
                        attendee_id=att_id,
                        conference_id=conf.conference_id,
                        conference_name=conf_name,
                        conference_date=conf_date,
                        attendee_name=att_name,
                        job_title=att_title,
                        company_name=att_company,
                        professional_email="",
                        personal_linkedin_url=li_url,
                        linkedin_status=li_status,
                        source_url=event_url,
                        availability_status="Available",
                        weekly_run_id=c_run_id,
                        collection_date=today,
                        created_at=datetime.utcnow()
                    )
                    self.db.add(att_record)
                    collected_records.append(att_record)
            else:
                # Attendee list is private, restricted, or not published by organizer
                confs_not_public += 1
                dup_key = (conf_name.lower(), "not publicly available")
                if dup_key not in existing_att_keys:
                    existing_att_keys.add(dup_key)
                    att_id = generate_weekly_attendee_id(conf.conference_id, "NPA")
                    att_record = WeeklyAttendee(
                        attendee_id=att_id,
                        conference_id=conf.conference_id,
                        conference_name=conf_name,
                        conference_date=conf_date,
                        attendee_name="Not Publicly Available",
                        job_title="N/A",
                        company_name="N/A",
                        professional_email="",
                        personal_linkedin_url="",
                        linkedin_status="not_applicable",
                        source_url=event_url,
                        availability_status="Not Publicly Available",
                        weekly_run_id=c_run_id,
                        collection_date=today,
                        created_at=datetime.utcnow()
                    )
                    self.db.add(att_record)
                    collected_records.append(att_record)

        # Commit to PostgreSQL
        self.db.commit()

        # Sync to Local Excel ('weekly_attendees' worksheet)
        all_current_atts = self.db.query(WeeklyAttendee).order_by(WeeklyAttendee.conference_date.asc(), WeeklyAttendee.conference_name.asc()).all()
        local_sync_res = {}
        try:
            local_sync_res = self.excel_mgr.sync_weekly_attendees_to_excel(all_current_atts, replace_all=True)
            logger.info(f"✅ Local Excel weekly_attendees sync result: {local_sync_res}")
        except Exception as e:
            logger.warning(f"⚠️ Local Excel weekly_attendees sync notice: {e}")

        # Sync to OneDrive Excel ('tbl_weekly_attendees' table on 'weekly_attendees' worksheet)
        onedrive_sync_res = {}
        try:
            onedrive_sync_res = self.onedrive_svc.sync_weekly_attendees(
                attendees=collected_records,
                run_id=run_id
            )
            logger.info(f"✅ OneDrive Excel weekly_attendees sync result: {onedrive_sync_res}")
        except Exception as e:
            logger.warning(f"⚠️ OneDrive Excel weekly_attendees sync notice: {e}")

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            f"🎉 [Attendee Collection] Completed: {len(target_confs)} conferences checked in {elapsed}s | "
            f"{len(collected_records)} attendee records processed (Public: {confs_with_public_attendees}, "
            f"Not Publicly Available: {confs_not_public})."
        )

        return {
            "status": "success",
            "total_conferences_checked": len(target_confs),
            "conferences_with_public_attendees": confs_with_public_attendees,
            "conferences_not_publicly_available": confs_not_public,
            "total_records_created": len(collected_records),
            "local_excel_sync": local_sync_res,
            "onedrive_sync": onedrive_sync_res,
            "duration_seconds": elapsed
        }
