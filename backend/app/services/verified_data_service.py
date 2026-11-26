import logging
import re
import html
import urllib.parse
import urllib.request
import json
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Set, Tuple
from collections import defaultdict
from sqlalchemy.orm import Session
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from ..config import settings
from ..models import WeeklySpeaker, WeeklyAttendee, WeeklyExhibitor, WeeklyCompany
from ..services.onedrive_excel_service import OneDriveExcelService

logger = logging.getLogger(__name__)

# Exact 38-column specification (37 contact/outreach cols + Evaluation_Status in col AL)
VERIFIED_DATA_HEADERS = [
    # Company and Conference Information (Cols 1-4)
    "Company Name",
    "Company Domain",
    "Conference Name",
    "Conference ID",
    # Speaker Information (Cols 5-15)
    "Speaker Name",
    "Speaker Job Title",
    "Speaker LinkedIn",
    "Speaker Professional Email",
    "Speaker Email Status",
    "Speaker Outreach Status",
    "Speaker Reply Status",
    "Speaker Received Reply",
    "Speaker Sentiment",
    "Speaker Sent Message",
    "Speaker Thread ID",
    # Attendee Information (Cols 16-26)
    "Attendee Name",
    "Attendee Job Title",
    "Attendee LinkedIn",
    "Attendee Professional Email",
    "Attendee Email Status",
    "Attendee Outreach Status",
    "Attendee Reply Status",
    "Attendee Received Reply",
    "Attendee Sentiment",
    "Attendee Sent Message",
    "Attendee Thread ID",
    # Exhibitor Information (Cols 27-37)
    "Exhibitor Name",
    "Exhibitor Job Title",
    "Exhibitor LinkedIn",
    "Exhibitor Professional Email",
    "Exhibitor Email Status",
    "Exhibitor Outreach Status",
    "Exhibitor Reply Status",
    "Exhibitor Received Reply",
    "Exhibitor Sentiment",
    "Exhibitor Sent Message",
    "Exhibitor Thread ID",
    # ICP Pipeline Evaluation Marker (Col 38 / AL)
    "Evaluation_Status"
]


def is_valid_verified_email(email: Optional[str]) -> bool:
    """Validates that an email is present, well-formed, and not a placeholder."""
    if not email:
        return False
    clean = str(email).strip()
    if not clean or "@" not in clean or "." not in clean:
        return False
    clean_lower = clean.lower()
    if any(bad in clean_lower for bad in [
        "not found", "n/a", "none", "placeholder", "tbd", "example.com", "test.com", "unknown"
    ]):
        return False
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, clean))


def normalize_name(name: Optional[str]) -> str:
    """Normalizes person names to prevent duplicates from titles or whitespace differences."""
    if not name:
        return ""
    cleaned = re.sub(r"^(dr\.|mr\.|ms\.|mrs\.|prof\.)\s*", "", name.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def is_generic_name(name: str) -> bool:
    """Checks if a name is a generic placeholder or too short."""
    norm = name.strip().lower()
    return norm in ["not publicly available", "n/a", "none", "unknown", "tbd", ""] or len(norm) < 2


def resolve_company_domain(
    conf_id: Optional[str],
    company_name: Optional[str],
    email: Optional[str] = None,
    website: Optional[str] = None,
    domain_lookup: Optional[Dict[Any, str]] = None
) -> str:
    """
    Resolves official company domain using:
    1. WeeklyCompany metadata table match by (conf_id, company_name) or company_name.
    2. Exhibitor company website URL parse.
    3. Corporate email domain (ignoring generic email providers like gmail, yahoo, etc.).
    """
    cid = (conf_id or "").strip().lower()
    cname = (company_name or "").strip().lower()

    if domain_lookup:
        if cid and cname and (cid, cname) in domain_lookup:
            return domain_lookup[(cid, cname)]
        if cname and cname in domain_lookup:
            return domain_lookup[cname]

    if website:
        w = website.strip().lower()
        if not w.startswith(("http://", "https://")):
            w = "https://" + w
        try:
            netloc = urllib.parse.urlparse(w).netloc
            if netloc.startswith("www."):
                netloc = netloc[4:]
            if netloc:
                return netloc
        except Exception:
            pass

    if email and "@" in email:
        dom = email.split("@")[1].strip().lower()
        if dom not in [
            "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
            "icloud.com", "aol.com", "protonmail.com", "zoho.com"
        ]:
            return dom

    return ""


class VerifiedDataService:
    """
    Service for Company-Wise Multi-Row Grouped Verified Contacts:
    - Grouping Key: Conference ID + Conference Name + Company Name + Company Domain.
    - Rows per company = max(len(Speakers), len(Attendees), len(Exhibitors)).
    - 37 dedicated columns with strict row-wise category alignment.
    - Preserves all original data, historical Weekly Speakers outreach, and reply tracking.
    """

    def __init__(self, db: Session):
        self.db = db
        self.onedrive_svc = OneDriveExcelService()
        self.excel_path = settings.EXCEL_OUTPUT_PATH

    def _build_domain_lookup(self) -> Dict[Any, str]:
        """Builds fast lookup map for company domains from WeeklyCompany records."""
        domain_lookup: Dict[Any, str] = {}
        try:
            companies = self.db.query(WeeklyCompany).all()
            for c in companies:
                c_name = (c.company_name or "").strip().lower()
                c_conf = (c.conference_id or "").strip().lower()
                if c.company_domain:
                    dom = c.company_domain.strip().lower()
                    if dom:
                        if c_conf and c_name:
                            domain_lookup[(c_conf, c_name)] = dom
                        if c_name and c_name not in domain_lookup:
                            domain_lookup[c_name] = dom
        except Exception as e:
            logger.warning(f"[VerifiedDataService] Notice reading WeeklyCompany domains: {e}")
        return domain_lookup

    def get_company_grouped_rows(self) -> Tuple[List[List[Any]], Dict[str, Any]]:
        """
        Extracts verified contacts across Speakers, Attendees, and Exhibitors,
        groups them by (Conference ID + Conference Name + Company Name + Company Domain),
        and formats them into the exact 37-column multi-row aligned structure.
        """
        domain_lookup = self._build_domain_lookup()

        # 1. Weekly Speakers (verified email, verification_status == 'verified', outreach_status != 'sent')
        speakers = self.db.query(WeeklySpeaker).all()
        grouped_speakers = defaultdict(list)
        seen_spk_emails: Set[str] = set()
        seen_spk_names: Set[str] = set()
        spk_total = 0

        for s in speakers:
            email = (s.professional_email or "").strip()
            v_status = (s.verification_status or "").strip().lower()
            outreach = (s.outreach_status or "").strip().lower()

            if is_valid_verified_email(email) and v_status == "verified" and outreach != "sent":
                email_norm = email.lower()
                name = (s.speaker_name or "").strip()
                name_norm = normalize_name(name)

                if email_norm in seen_spk_emails or (name_norm and not is_generic_name(name_norm) and name_norm in seen_spk_names):
                    continue
                seen_spk_emails.add(email_norm)
                if name_norm and not is_generic_name(name_norm):
                    seen_spk_names.add(name_norm)

                cid = (s.conference_id or "").strip()
                cname = html.unescape((s.conference_name or "").strip())
                comp = (s.company_name or "").strip()
                dom = resolve_company_domain(cid, comp, email=email, domain_lookup=domain_lookup)

                key = (cid, cname, comp, dom)
                grouped_speakers[key].append(s)
                spk_total += 1

        # 2. Weekly Attendees (verified email, email_status == 'Verified')
        attendees = self.db.query(WeeklyAttendee).all()
        grouped_attendees = defaultdict(list)
        seen_att_emails: Set[str] = set()
        seen_att_names: Set[str] = set()
        att_total = 0

        for a in attendees:
            email = (a.professional_email or "").strip()
            e_status = (a.email_status or "").strip().lower()

            if is_valid_verified_email(email) and e_status == "verified":
                email_norm = email.lower()
                name = (a.attendee_name or "").strip()
                name_norm = normalize_name(name)

                if email_norm in seen_att_emails or (name_norm and not is_generic_name(name_norm) and name_norm in seen_att_names):
                    continue
                seen_att_emails.add(email_norm)
                if name_norm and not is_generic_name(name_norm):
                    seen_att_names.add(name_norm)

                cid = (a.conference_id or "").strip()
                cname = html.unescape((a.conference_name or "").strip())
                comp = (a.company_name or "").strip()
                dom = resolve_company_domain(cid, comp, email=email, domain_lookup=domain_lookup)

                key = (cid, cname, comp, dom)
                grouped_attendees[key].append(a)
                att_total += 1

        # 3. Weekly Exhibitors (verified email, email_status == 'Verified')
        exhibitors = self.db.query(WeeklyExhibitor).all()
        grouped_exhibitors = defaultdict(list)
        seen_exh_emails: Set[str] = set()
        seen_exh_names: Set[str] = set()
        exh_total = 0

        for e in exhibitors:
            email = (e.professional_email or "").strip()
            e_status = (e.email_status or "").strip().lower()

            if is_valid_verified_email(email) and e_status == "verified":
                email_norm = email.lower()
                contact_person = (e.contact_person or "").strip() or (e.company_name or "").strip()
                name_norm = normalize_name(contact_person)

                if email_norm in seen_exh_emails or (name_norm and not is_generic_name(name_norm) and name_norm in seen_exh_names):
                    continue
                seen_exh_emails.add(email_norm)
                if name_norm and not is_generic_name(name_norm):
                    seen_exh_names.add(name_norm)

                cid = (e.conference_id or "").strip()
                cname = html.unescape((e.conference_name or "").strip())
                comp = (e.company_name or "").strip()
                dom = resolve_company_domain(cid, comp, email=email, website=e.company_website, domain_lookup=domain_lookup)

                key = (cid, cname, comp, dom)
                grouped_exhibitors[key].append(e)
                exh_total += 1

        # Collect all unique company group keys
        all_group_keys = set(grouped_speakers.keys()) | set(grouped_attendees.keys()) | set(grouped_exhibitors.keys())
        # Sort by Conference Name, Company Name for clean readability
        sorted_keys = sorted(all_group_keys, key=lambda k: (k[1].lower(), k[2].lower(), k[0]))

        matrix_rows: List[List[Any]] = []
        for key in sorted_keys:
            cid, cname, comp, dom = key
            spk_list = grouped_speakers.get(key, [])
            att_list = grouped_attendees.get(key, [])
            exh_list = grouped_exhibitors.get(key, [])

            # Number of rows = highest count among categories
            row_count = max(len(spk_list), len(att_list), len(exh_list))

            for i in range(row_count):
                spk = spk_list[i] if i < len(spk_list) else None
                att = att_list[i] if i < len(att_list) else None
                exh = exh_list[i] if i < len(exh_list) else None

                # Build 38-column row (37 contact/outreach cols + Evaluation_Status in col AL)
                row_vals = [
                    # 1-4: Company & Conference Information
                    comp,
                    dom,
                    cname,
                    cid,
                    # 5-15: Speaker Information
                    spk.speaker_name if spk else "",
                    spk.job_title if spk else "",
                    spk.personal_linkedin_url if spk else "",
                    spk.professional_email if spk else "",
                    "Verified" if spk else "",
                    (spk.outreach_status or "Pending") if spk else "",
                    spk.reply_status if spk and spk.reply_status else "",
                    spk.received_reply if spk and spk.received_reply else "",
                    spk.reply_sentiment if spk and spk.reply_sentiment else "",
                    spk.sent_message if spk and spk.sent_message else "",
                    spk.email_thread_id if spk and spk.email_thread_id else "",
                    # 16-26: Attendee Information
                    att.attendee_name if att else "",
                    att.job_title if att else "",
                    att.personal_linkedin_url if att else "",
                    att.professional_email if att else "",
                    "Verified" if att else "",
                    "Pending" if att else "",
                    "",  # Attendee Reply Status
                    "",  # Attendee Received Reply
                    "",  # Attendee Sentiment
                    "",  # Attendee Sent Message
                    "",  # Attendee Thread ID
                    # 27-37: Exhibitor Information
                    (exh.contact_person or exh.company_name) if exh else "",
                    exh.contact_designation if exh else "",
                    (exh.contact_person_linkedin_url or exh.company_linkedin_url) if exh else "",
                    exh.professional_email if exh else "",
                    "Verified" if exh else "",
                    "Pending" if exh else "",
                    "",  # Exhibitor Reply Status
                    "",  # Exhibitor Received Reply
                    "",  # Exhibitor Sentiment
                    "",  # Exhibitor Sent Message
                    "",  # Exhibitor Thread ID
                    # 38 (AL): Evaluation_Status (restored from existing sheets during sync if already evaluated)
                    ""
                ]
                matrix_rows.append(row_vals)

        meta = {
            "total_groups": len(sorted_keys),
            "total_rows": len(matrix_rows),
            "speakers_count": spk_total,
            "attendees_count": att_total,
            "exhibitors_count": exh_total
        }
        logger.info(
            f"🔍 [VerifiedDataService] Grouped {len(matrix_rows)} rows across {len(sorted_keys)} company groups "
            f"(Speakers: {spk_total}, Attendees: {att_total}, Exhibitors: {exh_total})."
        )
        return matrix_rows, meta

    def sync_to_local_excel(self, matrix_rows: Optional[List[List[Any]]] = None) -> Dict[str, Any]:
        """
        Writes the 38-column company-grouped records to 'Verified Data' worksheet in local Excel.
        Preserves existing outreach tracking, reply history, and Evaluation_Status in-place.
        """
        if matrix_rows is None:
            matrix_rows, _ = self.get_company_grouped_rows()

        if not matrix_rows:
            return {"status": "skipped", "message": "No verified contacts to write."}

        try:
            wb = openpyxl.load_workbook(self.excel_path)
            sheet_name = "Verified Data"

            # 1. Cache existing outreach data and Evaluation_Status if local sheet exists
            existing_outreach: Dict[str, Dict[str, Any]] = {}
            existing_eval_by_rowkey: Dict[Tuple[str, str, str, str, str], str] = {}
            if sheet_name in wb.sheetnames:
                ex_ws = wb[sheet_name]
                ex_rows = list(ex_ws.iter_rows(values_only=True))
                if ex_rows and len(ex_rows) > 1:
                    raw_headers = [str(h).strip().lower().replace(" ", "").replace("_", "").replace("/", "") for h in ex_rows[0]]
                    col_map = {name: idx for idx, name in enumerate(raw_headers)}
                    eval_idx = col_map.get("evaluationstatus")
                    cid_idx = col_map.get("conferenceid", 3)
                    comp_idx = col_map.get("companyname", 0)
                    spk_n_idx = col_map.get("speakername", 4)
                    att_n_idx = col_map.get("attendeename", 15)
                    exh_n_idx = col_map.get("exhibitorname", 26)

                    # Support caching from both old 17-col and 38-col schemas
                    for r in ex_rows[1:]:
                        eval_val = str(r[eval_idx] or "").strip() if eval_idx is not None and len(r) > eval_idx else ""
                        if eval_val:
                            rk = (
                                str(r[cid_idx] or "").strip().lower() if len(r) > cid_idx else "",
                                str(r[comp_idx] or "").strip().lower() if len(r) > comp_idx else "",
                                str(r[spk_n_idx] or "").strip().lower() if len(r) > spk_n_idx else "",
                                str(r[att_n_idx] or "").strip().lower() if len(r) > att_n_idx else "",
                                str(r[exh_n_idx] or "").strip().lower() if len(r) > exh_n_idx else "",
                            )
                            existing_eval_by_rowkey[rk] = eval_val

                        # Check speaker email
                        spk_em_idx = col_map.get("speakerprofessionalemail", col_map.get("professionalemail"))
                        if spk_em_idx is not None and len(r) > spk_em_idx:
                            em = str(r[spk_em_idx] or "").strip().lower()
                            if em:
                                existing_outreach[em] = {
                                    "outreach_status": r[col_map.get("speakeroutreachstatus", col_map.get("outreachstatus", -1))] if col_map.get("speakeroutreachstatus", col_map.get("outreachstatus", -1)) != -1 and len(r) > col_map.get("speakeroutreachstatus", col_map.get("outreachstatus", -1)) else "",
                                    "reply_status": r[col_map.get("speakerreplystatus", col_map.get("replaystatus", -1))] if col_map.get("speakerreplystatus", col_map.get("replaystatus", -1)) != -1 and len(r) > col_map.get("speakerreplystatus", col_map.get("replaystatus", -1)) else "",
                                    "received_reply": r[col_map.get("speakerreceivedreply", col_map.get("receivedreplay", -1))] if col_map.get("speakerreceivedreply", col_map.get("receivedreplay", -1)) != -1 and len(r) > col_map.get("speakerreceivedreply", col_map.get("receivedreplay", -1)) else "",
                                    "reply_sentiment": r[col_map.get("speakersentiment", col_map.get("replaysentiment", -1))] if col_map.get("speakersentiment", col_map.get("replaysentiment", -1)) != -1 and len(r) > col_map.get("speakersentiment", col_map.get("replaysentiment", -1)) else "",
                                    "sent_message": r[col_map.get("speakersentmessage", col_map.get("sendmessage", -1))] if col_map.get("speakersentmessage", col_map.get("sendmessage", -1)) != -1 and len(r) > col_map.get("speakersentmessage", col_map.get("sendmessage", -1)) else "",
                                    "thread_id": r[col_map.get("speakerthreadid", col_map.get("threadid", -1))] if col_map.get("speakerthreadid", col_map.get("threadid", -1)) != -1 and len(r) > col_map.get("speakerthreadid", col_map.get("threadid", -1)) else "",
                                    "evaluation_status": eval_val
                                }

                        # Check attendee email
                        att_em_idx = col_map.get("attendeeprofessionalemail")
                        if att_em_idx is not None and len(r) > att_em_idx:
                            em = str(r[att_em_idx] or "").strip().lower()
                            if em:
                                existing_outreach[em] = {
                                    "outreach_status": r[col_map.get("attendeeoutreachstatus", -1)] if col_map.get("attendeeoutreachstatus", -1) != -1 and len(r) > col_map.get("attendeeoutreachstatus", -1) else "",
                                    "reply_status": r[col_map.get("attendeereplystatus", -1)] if col_map.get("attendeereplystatus", -1) != -1 and len(r) > col_map.get("attendeereplystatus", -1) else "",
                                    "received_reply": r[col_map.get("attendeereceivedreply", -1)] if col_map.get("attendeereceivedreply", -1) != -1 and len(r) > col_map.get("attendeereceivedreply", -1) else "",
                                    "reply_sentiment": r[col_map.get("attendeesentiment", -1)] if col_map.get("attendeesentiment", -1) != -1 and len(r) > col_map.get("attendeesentiment", -1) else "",
                                    "sent_message": r[col_map.get("attendeesentmessage", -1)] if col_map.get("attendeesentmessage", -1) != -1 and len(r) > col_map.get("attendeesentmessage", -1) else "",
                                    "thread_id": r[col_map.get("attendeethreadid", -1)] if col_map.get("attendeethreadid", -1) != -1 and len(r) > col_map.get("attendeethreadid", -1) else "",
                                    "evaluation_status": eval_val
                                }

                        # Check exhibitor email
                        exh_em_idx = col_map.get("exhibitorprofessionalemail")
                        if exh_em_idx is not None and len(r) > exh_em_idx:
                            em = str(r[exh_em_idx] or "").strip().lower()
                            if em:
                                existing_outreach[em] = {
                                    "outreach_status": r[col_map.get("exhibitoroutreachstatus", -1)] if col_map.get("exhibitoroutreachstatus", -1) != -1 and len(r) > col_map.get("exhibitoroutreachstatus", -1) else "",
                                    "reply_status": r[col_map.get("exhibitorreplystatus", -1)] if col_map.get("exhibitorreplystatus", -1) != -1 and len(r) > col_map.get("exhibitorreplystatus", -1) else "",
                                    "received_reply": r[col_map.get("exhibitorreceivedreply", -1)] if col_map.get("exhibitorreceivedreply", -1) != -1 and len(r) > col_map.get("exhibitorreceivedreply", -1) else "",
                                    "reply_sentiment": r[col_map.get("exhibitorsentiment", -1)] if col_map.get("exhibitorsentiment", -1) != -1 and len(r) > col_map.get("exhibitorsentiment", -1) else "",
                                    "sent_message": r[col_map.get("exhibitorsentmessage", -1)] if col_map.get("exhibitorsentmessage", -1) != -1 and len(r) > col_map.get("exhibitorsentmessage", -1) else "",
                                    "thread_id": r[col_map.get("exhibitorthreadid", -1)] if col_map.get("exhibitorthreadid", -1) != -1 and len(r) > col_map.get("exhibitorthreadid", -1) else "",
                                    "evaluation_status": eval_val
                                }

                del wb[sheet_name]

            ws = wb.create_sheet(sheet_name)

            # Styling definitions
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            header_fill = PatternFill(start_color="005B60", end_color="005B60", fill_type="solid")
            header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

            data_font = Font(name="Calibri", size=10, color="111827")
            badge_font = Font(name="Calibri", size=10, bold=True, color="047857")
            center_align = Alignment(horizontal="center", vertical="center")
            left_align = Alignment(horizontal="left", vertical="center")

            thin_border = Border(
                left=Side(style="thin", color="E5E7EB"),
                right=Side(style="thin", color="E5E7EB"),
                top=Side(style="thin", color="E5E7EB"),
                bottom=Side(style="thin", color="E5E7EB")
            )

            # Write header
            ws.row_dimensions[1].height = 28
            ws.append(VERIFIED_DATA_HEADERS)
            for col_idx in range(1, len(VERIFIED_DATA_HEADERS) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align
                cell.border = thin_border

            # Write data rows
            for r_idx, row_vals in enumerate(matrix_rows, start=2):
                ws.row_dimensions[r_idx].height = 20
                row_copy = list(row_vals)
                while len(row_copy) < len(VERIFIED_DATA_HEADERS):
                    row_copy.append("")
                restored_eval = ""

                # Merge cached outreach values for Speaker (email at idx 7)
                spk_em = str(row_copy[7] or "").strip().lower()
                if spk_em and spk_em in existing_outreach:
                    cache = existing_outreach[spk_em]
                    if cache.get("outreach_status"): row_copy[9] = cache["outreach_status"]
                    if cache.get("reply_status"): row_copy[10] = cache["reply_status"]
                    if cache.get("received_reply"): row_copy[11] = cache["received_reply"]
                    if cache.get("reply_sentiment"): row_copy[12] = cache["reply_sentiment"]
                    if cache.get("sent_message"): row_copy[13] = cache["sent_message"]
                    if cache.get("thread_id"): row_copy[14] = cache["thread_id"]
                    if cache.get("evaluation_status"): restored_eval = cache["evaluation_status"]

                # Merge cached outreach values for Attendee (email at idx 18)
                att_em = str(row_copy[18] or "").strip().lower()
                if att_em and att_em in existing_outreach:
                    cache = existing_outreach[att_em]
                    if cache.get("outreach_status"): row_copy[20] = cache["outreach_status"]
                    if cache.get("reply_status"): row_copy[21] = cache["reply_status"]
                    if cache.get("received_reply"): row_copy[22] = cache["received_reply"]
                    if cache.get("reply_sentiment"): row_copy[23] = cache["reply_sentiment"]
                    if cache.get("sent_message"): row_copy[24] = cache["sent_message"]
                    if cache.get("thread_id"): row_copy[25] = cache["thread_id"]
                    if not restored_eval and cache.get("evaluation_status"): restored_eval = cache["evaluation_status"]

                # Merge cached outreach values for Exhibitor (email at idx 29)
                exh_em = str(row_copy[29] or "").strip().lower()
                if exh_em and exh_em in existing_outreach:
                    cache = existing_outreach[exh_em]
                    if cache.get("outreach_status"): row_copy[31] = cache["outreach_status"]
                    if cache.get("reply_status"): row_copy[32] = cache["reply_status"]
                    if cache.get("received_reply"): row_copy[33] = cache["received_reply"]
                    if cache.get("reply_sentiment"): row_copy[34] = cache["reply_sentiment"]
                    if cache.get("sent_message"): row_copy[35] = cache["sent_message"]
                    if cache.get("thread_id"): row_copy[36] = cache["thread_id"]
                    if not restored_eval and cache.get("evaluation_status"): restored_eval = cache["evaluation_status"]

                if not restored_eval:
                    rk = (
                        str(row_copy[3] or "").strip().lower(),
                        str(row_copy[0] or "").strip().lower(),
                        str(row_copy[4] or "").strip().lower(),
                        str(row_copy[15] or "").strip().lower(),
                        str(row_copy[26] or "").strip().lower(),
                    )
                    restored_eval = existing_eval_by_rowkey.get(rk, "")
                if restored_eval and not str(row_copy[37] or "").strip():
                    row_copy[37] = restored_eval

                ws.append(row_copy[:len(VERIFIED_DATA_HEADERS)])
                for col_idx, val in enumerate(row_copy[:len(VERIFIED_DATA_HEADERS)], start=1):
                    cell = ws.cell(row=r_idx, column=col_idx)
                    cell.font = data_font
                    cell.border = thin_border
                    # Align status badges
                    if col_idx in [4, 9, 10, 11, 13, 20, 21, 22, 24, 31, 32, 33, 35, 38]:
                        cell.alignment = center_align
                        if col_idx in [9, 20, 31] and val == "Verified":
                            cell.font = badge_font
                    else:
                        cell.alignment = left_align

            # Auto-fit columns
            for col in ws.columns:
                max_len = 0
                col_letter = get_column_letter(col[0].column)
                for cell in col:
                    val_str = str(cell.value or "")
                    if len(val_str) > max_len:
                        max_len = len(val_str)
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 14), 45)

            wb.save(self.excel_path)
            logger.info(f"✅ [VerifiedDataService] Local Excel 'Verified Data' saved with {len(matrix_rows)} 38-column rows.")
            return {"status": "success", "count": len(matrix_rows)}
        except Exception as e:
            logger.error(f"❌ [VerifiedDataService] Error saving to Local Excel: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def sync_to_onedrive(self, matrix_rows: Optional[List[List[Any]]] = None) -> Dict[str, Any]:
        """
        Synchronizes 38-column company-grouped records to OneDrive Live Excel:
        - Writes to 'Verified Data' worksheet range A1:AL{N}.
        - Re-creates table 'tbl_verified_data' with TableStyleMedium9.
        - Preserves existing outreach, reply tracking, and Evaluation_Status data.
        """
        if matrix_rows is None:
            matrix_rows, _ = self.get_company_grouped_rows()

        if not matrix_rows:
            return {"status": "skipped", "message": "No verified contacts to sync to OneDrive."}

        try:
            token = self.onedrive_svc._get_access_token()
            drive_id = self.onedrive_svc.resolve_drive_id()
            item_id = self.onedrive_svc.resolve_item_id()

            sheet_name_encoded = urllib.parse.quote("Verified Data")

            def graph_request(method, endpoint, body=None):
                url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}{endpoint}"
                req = urllib.request.Request(url, method=method)
                req.add_header("Authorization", f"Bearer {token}")
                req.add_header("Accept", "application/json")
                if body is not None:
                    req.add_header("Content-Type", "application/json")
                    data = json.dumps(body).encode("utf-8")
                else:
                    data = None
                with urllib.request.urlopen(req, data=data, timeout=30) as resp:
                    if resp.status == 204:
                        return {}
                    return json.loads(resp.read().decode("utf-8"))

            # Preserve existing outreach tracking and Evaluation_Status from OneDrive table/range if present
            existing_od_outreach: Dict[str, Dict[str, Any]] = {}
            existing_od_eval_by_rowkey: Dict[Tuple[str, str, str, str, str], str] = {}
            raw_od_c_map: Dict[str, int] = {}
            raw_od_rows: List[List[Any]] = []
            try:
                rows_res = graph_request("GET", f"/workbook/tables/tbl_verified_data/rows")
                cols_res = graph_request("GET", f"/workbook/tables/tbl_verified_data/columns")
                c_names = [col["name"] for col in cols_res.get("value", [])]
                raw_od_c_map = {name.lower().replace(" ", "").replace("_", "").replace("/", ""): idx for idx, name in enumerate(c_names)}
                raw_od_rows = [r.get("values", [[]])[0] for r in rows_res.get("value", [])]
            except Exception as pe:
                logger.debug(f"Notice loading existing OneDrive table tbl_verified_data ({pe}); checking worksheet usedRange...")
                try:
                    used_res = graph_request("GET", f"/workbook/worksheets/{sheet_name_encoded}/usedRange")
                    u_vals = used_res.get("values", [])
                    if len(u_vals) > 1:
                        raw_od_c_map = {str(c).lower().replace(" ", "").replace("_", "").replace("/", ""): idx for idx, c in enumerate(u_vals[0])}
                        raw_od_rows = u_vals[1:]
                except Exception:
                    pass

            if raw_od_c_map and raw_od_rows:
                eval_idx = raw_od_c_map.get("evaluationstatus")
                cid_idx = raw_od_c_map.get("conferenceid", 3)
                comp_idx = raw_od_c_map.get("companyname", 0)
                spk_n_idx = raw_od_c_map.get("speakername", 4)
                att_n_idx = raw_od_c_map.get("attendeename", 15)
                exh_n_idx = raw_od_c_map.get("exhibitorname", 26)

                for vals in raw_od_rows:
                    eval_val = str(vals[eval_idx] or "").strip() if eval_idx is not None and len(vals) > eval_idx else ""
                    if eval_val:
                        rk = (
                            str(vals[cid_idx] or "").strip().lower() if len(vals) > cid_idx else "",
                            str(vals[comp_idx] or "").strip().lower() if len(vals) > comp_idx else "",
                            str(vals[spk_n_idx] or "").strip().lower() if len(vals) > spk_n_idx else "",
                            str(vals[att_n_idx] or "").strip().lower() if len(vals) > att_n_idx else "",
                            str(vals[exh_n_idx] or "").strip().lower() if len(vals) > exh_n_idx else "",
                        )
                        existing_od_eval_by_rowkey[rk] = eval_val

                    for em_key, st_key, rep_key, rec_key, sent_key, snd_key, th_key in [
                        ("speakerprofessionalemail", "speakeroutreachstatus", "speakerreplystatus", "speakerreceivedreply", "speakersentiment", "speakersentmessage", "speakerthreadid"),
                        ("attendeeprofessionalemail", "attendeeoutreachstatus", "attendeereplystatus", "attendeereceivedreply", "attendeesentiment", "attendeesentmessage", "attendeethreadid"),
                        ("exhibitorprofessionalemail", "exhibitoroutreachstatus", "exhibitorreplystatus", "exhibitorreceivedreply", "exhibitorsentiment", "exhibitorsentmessage", "exhibitorthreadid"),
                        ("professionalemail", "outreachstatus", "replaystatus", "receivedreplay", "replaysentiment", "sendmessage", "threadid")
                    ]:
                        em_idx = raw_od_c_map.get(em_key)
                        if em_idx is not None and len(vals) > em_idx:
                            em = str(vals[em_idx] or "").strip().lower()
                            if em:
                                existing_od_outreach[em] = {
                                    "outreach_status": vals[raw_od_c_map[st_key]] if raw_od_c_map.get(st_key) is not None and len(vals) > raw_od_c_map[st_key] else "",
                                    "reply_status": vals[raw_od_c_map[rep_key]] if raw_od_c_map.get(rep_key) is not None and len(vals) > raw_od_c_map[rep_key] else "",
                                    "received_reply": vals[raw_od_c_map[rec_key]] if raw_od_c_map.get(rec_key) is not None and len(vals) > raw_od_c_map[rec_key] else "",
                                    "reply_sentiment": vals[raw_od_c_map[sent_key]] if raw_od_c_map.get(sent_key) is not None and len(vals) > raw_od_c_map[sent_key] else "",
                                    "sent_message": vals[raw_od_c_map[snd_key]] if raw_od_c_map.get(snd_key) is not None and len(vals) > raw_od_c_map[snd_key] else "",
                                    "thread_id": vals[raw_od_c_map[th_key]] if raw_od_c_map.get(th_key) is not None and len(vals) > raw_od_c_map[th_key] else "",
                                    "evaluation_status": eval_val
                                }

            # 1. Delete old table if exists
            try:
                tables_res = graph_request("GET", f"/workbook/worksheets/{sheet_name_encoded}/tables")
                for tbl in tables_res.get("value", []):
                    tname = tbl.get("name")
                    if tname in ["tbl_verified_data", "TableVerifiedData"]:
                        graph_request("DELETE", f"/workbook/tables/{tname}")
            except Exception as te:
                logger.debug(f"Table deletion notice: {te}")

            # 2. Clear range A1:AL500
            try:
                graph_request("POST", f"/workbook/worksheets/{sheet_name_encoded}/range(address='A1:AL500')/clear", {"applyTo": "All"})
            except Exception as ce:
                logger.debug(f"Range clear notice: {ce}")

            # 3. Prepare rows matrix (header + data)
            all_matrix = [VERIFIED_DATA_HEADERS]
            for r in matrix_rows:
                row_copy = list(r)
                while len(row_copy) < len(VERIFIED_DATA_HEADERS):
                    row_copy.append("")
                restored_eval = ""

                # Speaker cache (idx 7)
                spk_em = str(row_copy[7] or "").strip().lower()
                if spk_em and spk_em in existing_od_outreach:
                    cache = existing_od_outreach[spk_em]
                    if cache.get("outreach_status"): row_copy[9] = cache["outreach_status"]
                    if cache.get("reply_status"): row_copy[10] = cache["reply_status"]
                    if cache.get("received_reply"): row_copy[11] = cache["received_reply"]
                    if cache.get("reply_sentiment"): row_copy[12] = cache["reply_sentiment"]
                    if cache.get("sent_message"): row_copy[13] = cache["sent_message"]
                    if cache.get("thread_id"): row_copy[14] = cache["thread_id"]
                    if cache.get("evaluation_status"): restored_eval = cache["evaluation_status"]

                # Attendee cache (idx 18)
                att_em = str(row_copy[18] or "").strip().lower()
                if att_em and att_em in existing_od_outreach:
                    cache = existing_od_outreach[att_em]
                    if cache.get("outreach_status"): row_copy[20] = cache["outreach_status"]
                    if cache.get("reply_status"): row_copy[21] = cache["reply_status"]
                    if cache.get("received_reply"): row_copy[22] = cache["received_reply"]
                    if cache.get("reply_sentiment"): row_copy[23] = cache["reply_sentiment"]
                    if cache.get("sent_message"): row_copy[24] = cache["sent_message"]
                    if cache.get("thread_id"): row_copy[25] = cache["thread_id"]
                    if not restored_eval and cache.get("evaluation_status"): restored_eval = cache["evaluation_status"]

                # Exhibitor cache (idx 29)
                exh_em = str(row_copy[29] or "").strip().lower()
                if exh_em and exh_em in existing_od_outreach:
                    cache = existing_od_outreach[exh_em]
                    if cache.get("outreach_status"): row_copy[31] = cache["outreach_status"]
                    if cache.get("reply_status"): row_copy[32] = cache["reply_status"]
                    if cache.get("received_reply"): row_copy[33] = cache["received_reply"]
                    if cache.get("reply_sentiment"): row_copy[34] = cache["reply_sentiment"]
                    if cache.get("sent_message"): row_copy[35] = cache["sent_message"]
                    if cache.get("thread_id"): row_copy[36] = cache["thread_id"]
                    if not restored_eval and cache.get("evaluation_status"): restored_eval = cache["evaluation_status"]

                if not restored_eval:
                    rk = (
                        str(row_copy[3] or "").strip().lower(),
                        str(row_copy[0] or "").strip().lower(),
                        str(row_copy[4] or "").strip().lower(),
                        str(row_copy[15] or "").strip().lower(),
                        str(row_copy[26] or "").strip().lower(),
                    )
                    restored_eval = existing_od_eval_by_rowkey.get(rk, "")
                if restored_eval and not str(row_copy[37] or "").strip():
                    row_copy[37] = restored_eval

                all_matrix.append(row_copy[:len(VERIFIED_DATA_HEADERS)])

            end_row = len(all_matrix)
            range_addr = f"A1:AL{end_row}"

            # 4. Write values to range
            graph_request("PATCH", f"/workbook/worksheets/{sheet_name_encoded}/range(address='{range_addr}')", {"values": all_matrix})

            # 5. Create table over range
            table_body = {
                "address": f"'Verified Data'!{range_addr}",
                "hasHeaders": True
            }
            new_table = graph_request("POST", f"/workbook/tables/add", table_body)
            table_id = new_table.get("id")

            # 6. Rename table to tbl_verified_data and set style
            if table_id:
                graph_request("PATCH", f"/workbook/tables/{table_id}", {
                    "name": "tbl_verified_data",
                    "style": "TableStyleMedium9"
                })

            logger.info(f"✅ [VerifiedDataService] Successfully synced {len(matrix_rows)} 38-column rows to OneDrive 'tbl_verified_data'.")
            return {"status": "success", "count": len(matrix_rows)}
        except Exception as e:
            logger.error(f"❌ [VerifiedDataService] Error syncing to OneDrive: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def sync_all_verified_data(self) -> Dict[str, Any]:
        """
        Executes end-to-end sync of company-grouped verified records to both Local Excel and OneDrive.
        """
        matrix_rows, meta = self.get_company_grouped_rows()
        local_res = self.sync_to_local_excel(matrix_rows)
        onedrive_res = self.sync_to_onedrive(matrix_rows)

        return {
            "status": "success" if local_res.get("status") == "success" else "partial",
            "meta": meta,
            "local_excel": local_res,
            "onedrive": onedrive_res
        }
