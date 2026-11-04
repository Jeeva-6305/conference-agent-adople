import logging
import re
import html
import urllib.parse
import urllib.request
import json
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Set, Tuple
from sqlalchemy.orm import Session
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from ..config import settings
from ..models import WeeklySpeaker, WeeklyAttendee, WeeklyExhibitor
from ..services.onedrive_excel_service import OneDriveExcelService

logger = logging.getLogger(__name__)

VERIFIED_DATA_HEADERS = [
    "Contact Type",
    "Conference Name",
    "Name",
    "Job Title / Designation",
    "Company Name",
    "Professional Email",
    "Email Status",
    "Personal LinkedIn URL",
    "Outreach Status",
    "Source / Profile URL",
    "Collection Date"
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


class VerifiedDataService:
    """
    Dedicated Service for Automated Verified Contact Aggregation:
    - Scans Weekly Speakers, Weekly Attendees, and Weekly Exhibitors.
    - Selects only records having valid, verified professional emails.
    - Strictly prevents duplicates by unique professional email and unique contact name.
    - Prioritizes original primary source data (Speakers > Attendees > Exhibitors).
    - Synchronizes full contact details to:
      1. Local Excel workbook ('Verified Data' sheet).
      2. OneDrive Live Excel ('tbl_verified_data' table on 'Verified Data' sheet).
    - Preserves existing records without data loss.
    - Does not alter or disrupt any external sources or existing pipelines.
    """

    def __init__(self, db: Session):
        self.db = db
        self.onedrive_svc = OneDriveExcelService()
        self.excel_path = settings.EXCEL_OUTPUT_PATH

    def get_all_verified_contacts(self) -> List[Dict[str, Any]]:
        """
        Gathers all genuine contacts with verified emails from:
        - Weekly Speakers (verification_status == 'verified', outreach_status != 'sent')
        - Weekly Attendees (email_status == 'Verified')
        - Weekly Exhibitors (email_status == 'Verified')
        Enforces strict uniqueness by email and contact name so each individual
        appears exactly once with their primary original authentic data.
        """
        contacts: List[Dict[str, Any]] = []
        seen_emails: Set[str] = set()
        seen_names: Set[str] = set()

        # 1. Weekly Speakers (Primary priority role)
        speakers = self.db.query(WeeklySpeaker).all()
        spk_count = 0
        for s in speakers:
            email = (s.professional_email or "").strip()
            v_status = (s.verification_status or "").strip().lower()
            outreach = (s.outreach_status or "").strip().lower()

            if is_valid_verified_email(email) and v_status == "verified" and outreach != "sent":
                c_name = html.unescape((s.conference_name or "").strip())
                name = (s.speaker_name or "").strip()
                name_norm = normalize_name(name)
                email_norm = email.lower()

                if email_norm in seen_emails or (name_norm and not is_generic_name(name_norm) and name_norm in seen_names):
                    logger.debug(f"[VerifiedDataService] Skipping duplicate speaker: {name} ({email})")
                    continue

                seen_emails.add(email_norm)
                if name_norm and not is_generic_name(name_norm):
                    seen_names.add(name_norm)

                spk_count += 1
                c_date = ""
                if s.last_checked_at:
                    c_date = s.last_checked_at.strftime("%Y-%m-%d") if hasattr(s.last_checked_at, "strftime") else str(s.last_checked_at)[:10]
                else:
                    c_date = date.today().isoformat()

                contacts.append({
                    "contact_type": "Speaker",
                    "conference_name": c_name,
                    "name": name,
                    "job_title": (s.job_title or "").strip(),
                    "company_name": (s.company_name or "").strip(),
                    "professional_email": email,
                    "email_status": "Verified",
                    "personal_linkedin_url": (s.personal_linkedin_url or "").strip(),
                    "outreach_status": (s.outreach_status or "").strip() or "Pending",
                    "source_url": (s.speaker_source_url or "").strip(),
                    "collection_date": c_date
                })

        # 2. Weekly Attendees
        attendees = self.db.query(WeeklyAttendee).all()
        att_count = 0
        for a in attendees:
            email = (a.professional_email or "").strip()
            em_status = (a.email_status or "").strip().lower()

            if is_valid_verified_email(email) and em_status == "verified":
                c_name = html.unescape((a.conference_name or "").strip())
                name = (a.attendee_name or "").strip()
                name_norm = normalize_name(name)
                email_norm = email.lower()

                if email_norm in seen_emails or (name_norm and not is_generic_name(name_norm) and name_norm in seen_names):
                    logger.debug(f"[VerifiedDataService] Skipping duplicate attendee: {name} ({email})")
                    continue

                seen_emails.add(email_norm)
                if name_norm and not is_generic_name(name_norm):
                    seen_names.add(name_norm)

                att_count += 1
                c_date = ""
                if a.collection_date:
                    c_date = a.collection_date.isoformat() if hasattr(a.collection_date, "isoformat") else str(a.collection_date)[:10]
                else:
                    c_date = date.today().isoformat()

                contacts.append({
                    "contact_type": "Attendee",
                    "conference_name": c_name,
                    "name": name,
                    "job_title": (a.job_title or "").strip(),
                    "company_name": (a.company_name or "").strip(),
                    "professional_email": email,
                    "email_status": "Verified",
                    "personal_linkedin_url": (a.personal_linkedin_url or "").strip(),
                    "outreach_status": "Pending",
                    "source_url": (a.source_url or "").strip(),
                    "collection_date": c_date
                })

        # 3. Weekly Exhibitors
        exhibitors = self.db.query(WeeklyExhibitor).all()
        exh_count = 0
        for e in exhibitors:
            email = (e.professional_email or "").strip()
            em_status = (e.email_status or "").strip().lower()

            if is_valid_verified_email(email) and em_status == "verified":
                c_name = html.unescape((e.conference_name or "").strip())
                contact_person = (e.contact_person or "").strip() or (e.company_name or "").strip()
                name_norm = normalize_name(contact_person)
                email_norm = email.lower()

                if email_norm in seen_emails or (name_norm and not is_generic_name(name_norm) and name_norm in seen_names):
                    logger.debug(f"[VerifiedDataService] Skipping duplicate exhibitor: {contact_person} ({email})")
                    continue

                seen_emails.add(email_norm)
                if name_norm and not is_generic_name(name_norm):
                    seen_names.add(name_norm)

                exh_count += 1
                c_date = ""
                if e.collection_date:
                    c_date = e.collection_date.isoformat() if hasattr(e.collection_date, "isoformat") else str(e.collection_date)[:10]
                else:
                    c_date = date.today().isoformat()

                li_url = (e.contact_person_linkedin_url or "").strip() or (e.company_linkedin_url or "").strip()

                contacts.append({
                    "contact_type": "Exhibitor",
                    "conference_name": c_name,
                    "name": contact_person,
                    "job_title": (e.contact_designation or "").strip(),
                    "company_name": (e.company_name or "").strip(),
                    "professional_email": email,
                    "email_status": "Verified",
                    "personal_linkedin_url": li_url,
                    "outreach_status": "Pending",
                    "source_url": (e.source_url or "").strip() or (e.company_website or "").strip(),
                    "collection_date": c_date
                })

        logger.info(
            f"🔍 [VerifiedDataService] Identified {len(contacts)} unique verified contacts "
            f"(Speakers: {spk_count}, Attendees: {att_count}, Exhibitors: {exh_count})."
        )
        return contacts

    def sync_to_local_excel(self, contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Updates the 'Verified Data' worksheet in the local published Excel file.
        Applies professional corporate styling and auto-adjusts column widths.
        """
        if not contacts:
            return {"status": "skipped", "message": "No verified contacts to write."}

        try:
            wb = openpyxl.load_workbook(self.excel_path)
            sheet_name = "Verified Data"

            if sheet_name in wb.sheetnames:
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
            ws.row_dimensions[1].height = 26
            ws.append(VERIFIED_DATA_HEADERS)
            for col_idx in range(1, len(VERIFIED_DATA_HEADERS) + 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = header_align
                cell.border = thin_border

            # Write data rows
            for r_idx, c in enumerate(contacts, start=2):
                ws.row_dimensions[r_idx].height = 20
                row_vals = [
                    c["contact_type"],
                    c["conference_name"],
                    c["name"],
                    c["job_title"],
                    c["company_name"],
                    c["professional_email"],
                    c["email_status"],
                    c["personal_linkedin_url"],
                    c["outreach_status"],
                    c["source_url"],
                    c["collection_date"]
                ]
                ws.append(row_vals)
                for col_idx, val in enumerate(row_vals, start=1):
                    cell = ws.cell(row=r_idx, column=col_idx)
                    cell.font = data_font
                    cell.border = thin_border
                    if col_idx in [1, 7, 9, 11]:  # Contact Type, Email Status, Outreach, Date
                        cell.alignment = center_align
                        if col_idx == 7:
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
                ws.column_dimensions[col_letter].width = max(max_len + 3, 14)

            wb.save(self.excel_path)
            logger.info(f"✅ [VerifiedDataService] Local Excel 'Verified Data' sheet saved with {len(contacts)} rows.")
            return {"status": "success", "count": len(contacts)}
        except Exception as e:
            logger.error(f"❌ [VerifiedDataService] Error saving to Local Excel: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def sync_to_onedrive(self, contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Synchronizes contacts to OneDrive Live Excel:
        - Writes to 'Verified Data' worksheet range A1:K{N}.
        - Re-creates table 'tbl_verified_data' with TableStyleMedium9.
        """
        if not contacts:
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

            # 1. Delete old table if exists
            try:
                tables_res = graph_request("GET", f"/workbook/worksheets/{sheet_name_encoded}/tables")
                for tbl in tables_res.get("value", []):
                    tname = tbl.get("name")
                    if tname in ["tbl_verified_data", "TableVerifiedData"]:
                        graph_request("DELETE", f"/workbook/tables/{tname}")
            except Exception as te:
                logger.debug(f"Table deletion notice: {te}")

            # 2. Clear range
            try:
                graph_request("POST", f"/workbook/worksheets/{sheet_name_encoded}/range(address='A1:Z200')/clear", {"applyTo": "All"})
            except Exception as ce:
                logger.debug(f"Range clear notice: {ce}")

            # 3. Prepare rows matrix (header + data)
            all_matrix = [VERIFIED_DATA_HEADERS]
            for c in contacts:
                all_matrix.append([
                    c["contact_type"],
                    c["conference_name"],
                    c["name"],
                    c["job_title"],
                    c["company_name"],
                    c["professional_email"],
                    c["email_status"],
                    c["personal_linkedin_url"],
                    c["outreach_status"],
                    c["source_url"],
                    c["collection_date"]
                ])

            end_row = len(all_matrix)
            range_addr = f"A1:K{end_row}"

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

            logger.info(f"✅ [VerifiedDataService] Successfully synced {len(contacts)} contacts to OneDrive 'tbl_verified_data'.")
            return {"status": "success", "count": len(contacts)}
        except Exception as e:
            logger.error(f"❌ [VerifiedDataService] Error syncing to OneDrive: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}

    def sync_all_verified_data(self) -> Dict[str, Any]:
        """
        Executes end-to-end sync of all verified contacts to both Local Excel and OneDrive.
        """
        contacts = self.get_all_verified_contacts()
        local_res = self.sync_to_local_excel(contacts)
        onedrive_res = self.sync_to_onedrive(contacts)

        return {
            "status": "success" if local_res.get("status") == "success" else "partial",
            "total_verified_contacts": len(contacts),
            "local_excel": local_res,
            "onedrive": onedrive_res
        }

