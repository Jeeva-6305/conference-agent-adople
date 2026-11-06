import logging
import os
import re
from datetime import date
from typing import List, Optional, Dict, Any
import pandas as pd
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from ..config import settings
from ..models import Conference, Speaker, Attendee, WeeklyConference, WeeklySpeaker, WeeklySourceRunLog

logger = logging.getLogger(__name__)

EXCEL_COLUMNS = [
    "Conference ID",
    "Conference Title",
    "Industry / Category",
    "Conference Start Date",
    "Conference End Date",
    "Speakers Available",
    "Venue",
    "City",
    "Country",
    "Organizer",
    "Official Conference URL",
    "Registration URL",
    "Source URL",
    "Publication Date"
]

SPEAKER_COLUMNS = [
    "Conference Name",
    "Speaker Name",
    "Company Name",
    "Job Role / Designation",
    "Original LinkedIn Profile URL",
    "Company Website URL",
    "Source URL"
]

ATTENDEE_COLUMNS = [
    "Conference ID",
    "Conference Name",
    "Expected Attendee Count",
    "Registered Attendee Count",
    "Attendee / Participant Categories",
    "Target Audience",
    "Industries",
    "Job Roles / Professions Represented",
    "Source URL"
]

class ExcelManager:
    def __init__(self, file_path: str = settings.EXCEL_OUTPUT_PATH):
        self.file_path = file_path
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.file_path):
            self.reset_excel()

    def reset_excel(self):
        """Creates or resets the Excel file with three styled sheets: USA Conferences, Speakers, and Attendees."""
        wb = Workbook()
        
        # 1. Main Sheet: USA Conferences
        ws_conf = wb.active
        ws_conf.title = "USA Conferences"
        
        conf_header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        conf_header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)

        ws_conf.append(EXCEL_COLUMNS)
        ws_conf.row_dimensions[1].height = 28

        for col_idx, col_name in enumerate(EXCEL_COLUMNS, 1):
            cell = ws_conf.cell(row=1, column=col_idx)
            cell.fill = conf_header_fill
            cell.font = conf_header_font
            cell.alignment = align_center

        self._auto_fit_columns(ws_conf)

        # 2. Second Sheet: Speakers
        ws_spk = wb.create_sheet(title="Speakers")
        spk_header_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
        spk_header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

        ws_spk.append(SPEAKER_COLUMNS)
        ws_spk.row_dimensions[1].height = 28

        for col_idx, col_name in enumerate(SPEAKER_COLUMNS, 1):
            cell = ws_spk.cell(row=1, column=col_idx)
            cell.fill = spk_header_fill
            cell.font = spk_header_font
            cell.alignment = align_center

        self._auto_fit_columns(ws_spk)

        # 3. Third Sheet: Attendees
        ws_att = wb.create_sheet(title="Attendees")
        att_header_fill = PatternFill(start_color="4338CA", end_color="4338CA", fill_type="solid")
        att_header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")

        ws_att.append(ATTENDEE_COLUMNS)
        ws_att.row_dimensions[1].height = 28

        for col_idx, col_name in enumerate(ATTENDEE_COLUMNS, 1):
            cell = ws_att.cell(row=1, column=col_idx)
            cell.fill = att_header_fill
            cell.font = att_header_font
            cell.alignment = align_center

        self._auto_fit_columns(ws_att)

        self._safe_save(wb)
        logger.info(f"Initialized blank Excel workbook with 'USA Conferences', 'Speakers', and 'Attendees' sheets at {self.file_path}")


    def _safe_save(self, wb) -> bool:
        try:
            wb.save(self.file_path)
            return True
        except PermissionError:
            logger.warning(f"File {self.file_path} is locked by an external application (like Excel). Retrying...")
            import time
            for _ in range(3):
                time.sleep(0.5)
                try:
                    wb.save(self.file_path)
                    return True
                except PermissionError:
                    pass
            logger.warning(f"Could not overwrite {self.file_path} because it is currently locked in Excel.")
            return False

    def _auto_fit_columns(self, ws):
        thin_border = Border(
            left=Side(style='thin', color='E2E8F0'),
            right=Side(style='thin', color='E2E8F0'),
            top=Side(style='thin', color='E2E8F0'),
            bottom=Side(style='thin', color='E2E8F0')
        )
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 14)
            for cell in col:
                if cell.row > 1:
                    cell.border = thin_border
                    cell.alignment = Alignment(vertical="center")

    def _apply_header_styles(self, ws, color="1E3A8A"):
        header_fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[1].height = 28
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = align_center

    def sync_published_conferences(
        self,
        conferences: List[Conference],
        speakers: Optional[List[Speaker]] = None,
        attendees: Optional[List[Attendee]] = None
    ) -> int:
        """
        Synchronizes the Excel workbook by appending newly published verified conferences,
        their associated speakers, and attendee profiles without wiping historical records.
        """
        return self.publish_conferences(conferences, speakers, attendees)

    def publish_conferences(
        self,
        conferences: List[Conference],
        speakers: Optional[List[Speaker]] = None,
        attendees: Optional[List[Attendee]] = None
    ) -> int:
        """
        Appends newly due conferences into the 'USA Conferences' sheet,
        their detailed speaker profiles into the 'Speakers' sheet,
        and attendee profiles into the 'Attendees' sheet.
        """
        if not conferences:
            return 0

        self._ensure_file_exists()
        wb = load_workbook(self.file_path)
        
        if "USA Conferences" not in wb.sheetnames:
            ws_conf = wb.active
            ws_conf.title = "USA Conferences"
        else:
            ws_conf = wb["USA Conferences"]

        if "Speakers" not in wb.sheetnames:
            ws_spk = wb.create_sheet(title="Speakers")
            ws_spk.append(SPEAKER_COLUMNS)
        else:
            ws_spk = wb["Speakers"]

        if "Attendees" not in wb.sheetnames:
            ws_att = wb.create_sheet(title="Attendees")
            ws_att.append(ATTENDEE_COLUMNS)
        else:
            ws_att = wb["Attendees"]

        # Collect existing conference IDs and titles
        existing_ids = set()
        existing_titles = set()
        for row in ws_conf.iter_rows(min_row=2, max_col=2, values_only=True):
            if row[0]:
                existing_ids.add(str(row[0]).strip())
            if len(row) > 1 and row[1]:
                existing_titles.add(str(row[1]).strip().lower())

        # Collect existing speakers (speaker_name, conf_title)
        existing_speakers = set()
        for row in ws_spk.iter_rows(min_row=2, max_col=2, values_only=True):
            if row[0] and len(row) > 1 and row[1]:
                existing_speakers.add((str(row[0]).strip().lower(), str(row[1]).strip().lower()))

        # Collect existing attendees (conference_id)
        existing_attendees = set()
        for row in ws_att.iter_rows(min_row=2, max_col=2, values_only=True):
            if row[0]:
                existing_attendees.add(str(row[0]).strip())

        added_conf_count = 0
        added_spk_count = 0
        added_att_count = 0
        updated_count = 0

        for conf in conferences:
            title_clean = conf.conference_title.strip().lower()
            if conf.conference_id in existing_ids or title_clean in existing_titles:
                # If speakers now exist for an existing conference, update Speakers Available column in sheet
                if conf.speakers_available and conf.speakers_available.strip().lower() in ["yes", "true", "1"]:
                    for row in ws_conf.iter_rows(min_row=2):
                        if (row[0].value and str(row[0].value).strip() == conf.conference_id) or \
                           (len(row) > 1 and row[1].value and str(row[1].value).strip().lower() == title_clean):
                            if len(row) > 5 and row[5].value != "Yes":
                                row[5].value = "Yes"
                                updated_count += 1
                            break
                continue

            # Determine whether speakers/auditors are available (Yes/No)
            speakers_available_str = "Yes" if (conf.speakers_available and conf.speakers_available.strip().lower() in ["yes", "true", "1"]) else "No"
            
            # Publication Date: MUST be the original conference publication date
            pub_date_str = conf.publication_date.isoformat() if conf.publication_date else ""

            row_data = [
                conf.conference_id,
                conf.conference_title,
                conf.industry_category,
                conf.start_date.isoformat() if conf.start_date else "",
                conf.end_date.isoformat() if conf.end_date else "",
                speakers_available_str,
                conf.venue,
                conf.city,
                conf.country,
                conf.organizer,
                conf.official_conference_url,
                conf.registration_url,
                conf.source_url,
                pub_date_str
            ]
            ws_conf.append(row_data)
            added_conf_count += 1
            existing_ids.add(conf.conference_id)
            existing_titles.add(title_clean)

        # Write explicit Speaker models into the Speakers sheet
        if speakers:
            for spk in speakers:
                key = (spk.conference_name.strip().lower(), spk.speaker_name.strip().lower())
                if key not in existing_speakers:
                    ws_spk.append([
                        spk.conference_name,
                        spk.speaker_name,
                        spk.company_name or spk.company_organization or "Not Verified",
                        spk.job_role_designation or "Not Verified",
                        getattr(spk, "linkedin_url", "") or "",
                        getattr(spk, "official_company_website_url", "") or "",
                        getattr(spk, "source_url", "") or ""
                    ])
                    existing_speakers.add(key)
                    added_spk_count += 1
                else:
                    # Update existing speaker row if more details (e.g. LinkedIn URL) become available
                    for row in ws_spk.iter_rows(min_row=2, max_col=7):
                        if (row[0].value and str(row[0].value).strip().lower() == key[0] and
                            row[1].value and str(row[1].value).strip().lower() == key[1]):
                            clean_li = getattr(spk, "linkedin_url", "") or ""
                            if clean_li and not row[4].value:
                                row[4].value = clean_li
                                updated_count += 1
                            comp_url = getattr(spk, "official_company_website_url", "") or ""
                            if comp_url and not row[5].value:
                                row[5].value = comp_url
                                updated_count += 1
                            if spk.company_name and (not row[2].value or row[2].value in ["", "Not Verified", "Industry Organization"]):
                                row[2].value = spk.company_name
                                updated_count += 1
                            if spk.job_role_designation and (not row[3].value or row[3].value in ["", "Not Verified", "Speaker", "Keynote Speaker"]):
                                row[3].value = spk.job_role_designation
                                updated_count += 1
                            break

        # Write Attendee models into the Attendees sheet
        if attendees:
            for att in attendees:
                if att.conference_id not in existing_attendees:
                    ws_att.append([
                        att.conference_id,
                        att.conference_name,
                        att.expected_attendee_count or "",
                        att.registered_attendee_count or "",
                        att.attendee_categories or "",
                        att.target_audience or "",
                        att.industries or "",
                        att.job_roles or "",
                        att.source_url or ""
                    ])
                    existing_attendees.add(att.conference_id)
                    added_att_count += 1

        if added_conf_count > 0 or added_spk_count > 0 or added_att_count > 0 or updated_count > 0:
            self._auto_fit_columns(ws_conf)
            self._auto_fit_columns(ws_spk)
            self._auto_fit_columns(ws_att)
            self._safe_save(wb)
            logger.info(
                f"Published {added_conf_count} conferences, {added_spk_count} speakers, "
                f"{added_att_count} attendee records, and updated {updated_count} fields in Excel at {self.file_path}"
            )

        return added_conf_count

    def sync_weekly_to_excel(
        self,
        conferences: List[WeeklyConference],
        speakers: List[WeeklySpeaker],
        logs: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Appends weekly conferences, speakers, and source logs to the local Excel workbook.
        Ensures sheets: 'weekly_conference', 'weekly_speakers', 'weekly_source_log'.
        Never deletes or overwrites existing rows.
        """
        self._ensure_file_exists()
        wb = load_workbook(self.file_path)

        # 1. Weekly Conferences sheet
        if "weekly_conference" not in wb.sheetnames:
            ws_wconf = wb.create_sheet("weekly_conference")
            wconf_cols = [
                "Conference_ID", "Conference_Name", "Conference_Start_Date", "Conference_End_Date",
                "Conference_City", "Conference_State", "Country", "Industry", "Official_Event_URL",
                "Source_Name", "Source_URL", "Link_Status", "Speaker_Status", "Last_Checked_At", "Weekly_Run_ID"
            ]
            ws_wconf.append(wconf_cols)
            self._apply_header_styles(ws_wconf)
        else:
            ws_wconf = wb["weekly_conference"]

        existing_wconfs = set()
        for row in ws_wconf.iter_rows(min_row=2, max_col=3, values_only=True):
            if row[0]:
                existing_wconfs.add(str(row[0]).strip().lower())
            if len(row) > 1 and row[1]:
                existing_wconfs.add(str(row[1]).strip().lower())

        added_confs = 0
        for c in conferences:
            c_id = (c.conference_id or "").strip().lower()
            c_name = (c.conference_name or "").strip().lower()
            if c_id in existing_wconfs or c_name in existing_wconfs:
                continue
            ws_wconf.append([
                c.conference_id,
                c.conference_name,
                c.start_date.isoformat() if c.start_date else "",
                c.end_date.isoformat() if c.end_date else "",
                c.city or "",
                c.state or "",
                c.country or "USA",
                c.industry or "",
                c.official_event_url or "",
                c.source_name or "",
                c.source_url or "",
                c.link_status or "verified",
                c.speaker_status or "No",
                c.last_checked_at.isoformat() if c.last_checked_at else "",
                c.weekly_run_id or ""
            ])
            existing_wconfs.add(c_id)
            existing_wconfs.add(c_name)
            added_confs += 1

        # 2. Weekly Speakers sheet
        if "weekly_speakers" not in wb.sheetnames:
            ws_wspk = wb.create_sheet("weekly_speakers")
            wspk_cols = [
                "Speaker_ID", "Conference_ID", "Conference_Name", "Speaker_Name", "Job_Title",
                "Company_Name", "Personal_LinkedIn_URL", "LinkedIn_Status", "Professional_Email",
                "Email_Source_URL", "Speaker_Source_URL", "Verification_Status", "Last_Checked_At", "Weekly_Run_ID"
            ]
            ws_wspk.append(wspk_cols)
            self._apply_header_styles(ws_wspk)
        else:
            ws_wspk = wb["weekly_speakers"]

        existing_wspks = set()
        for row in ws_wspk.iter_rows(min_row=2, max_col=4, values_only=True):
            if len(row) >= 4 and row[1] and row[3]:
                existing_wspks.add((str(row[1]).strip().lower(), str(row[3]).strip().lower()))

        added_spks = 0
        for s in speakers:
            spk_key = ((s.conference_id or "").strip().lower(), (s.speaker_name or "").strip().lower())
            if spk_key in existing_wspks:
                continue
            ws_wspk.append([
                s.speaker_id,
                s.conference_id,
                s.conference_name,
                s.speaker_name,
                s.job_title or "",
                s.company_name or "",
                s.personal_linkedin_url or "",
                s.linkedin_status or "needs_review",
                s.professional_email or "",
                s.email_source_url or "",
                s.speaker_source_url or "",
                s.verification_status or "needs_review",
                s.last_checked_at.isoformat() if s.last_checked_at else "",
                s.weekly_run_id or ""
            ])
            existing_wspks.add(spk_key)
            added_spks += 1

        # 3. Weekly Source Run Log sheet
        if logs:
            if "weekly_source_log" not in wb.sheetnames:
                ws_wlog = wb.create_sheet("weekly_source_log")
                wlog_cols = [
                    "Run_ID", "Run_Date", "Source_Name", "Source_Status", "Pages_Checked",
                    "Conferences_Found", "Conferences_Accepted", "Speakers_Found", "Error_Details", "Duration_Seconds"
                ]
                ws_wlog.append(wlog_cols)
                self._apply_header_styles(ws_wlog)
            else:
                ws_wlog = wb["weekly_source_log"]

            for l in logs:
                ws_wlog.append([
                    l.get("run_id", ""),
                    str(l.get("run_date", "")),
                    l.get("source_name", ""),
                    l.get("source_status", "success"),
                    int(l.get("pages_checked", 1)),
                    int(l.get("conferences_found", 0)),
                    int(l.get("conferences_accepted", 0)),
                    int(l.get("speakers_found", 0)),
                    str(l.get("error_details", "") or ""),
                    round(float(l.get("duration_seconds", 0.0)), 2)
                ])

        self._auto_fit_columns(ws_wconf)
        self._auto_fit_columns(ws_wspk)
        if "weekly_source_log" in wb.sheetnames:
            self._auto_fit_columns(wb["weekly_source_log"])
        self._safe_save(wb)

        logger.info(f"Local Excel weekly sync complete: {added_confs} conferences and {added_spks} speakers appended.")
        return {
            "status": "success",
            "added_conferences": added_confs,
            "added_speakers": added_spks
        }

    def update_weekly_speaker_enrichment(
        self,
        speaker_id: str,
        conference_id: str,
        speaker_name: str,
        personal_linkedin_url: Optional[str] = None,
        linkedin_status: Optional[str] = None,
        professional_email: Optional[str] = None,
        email_source_url: Optional[str] = None,
        verification_status: Optional[str] = None,
        last_checked_at: Optional[str] = None
    ) -> bool:
        """
        Updates an existing speaker row in-place on the local 'weekly_speakers' sheet.
        Preserves all other row data and columns.
        """
        if not os.path.exists(self.file_path):
            return False
        wb = load_workbook(self.file_path)
        if "weekly_speakers" not in wb.sheetnames:
            return False
        ws = wb["weekly_speakers"]

        updated = False
        target_sid = (speaker_id or "").strip().lower()
        target_cid = (conference_id or "").strip().lower()
        target_name = (speaker_name or "").strip().lower()

        for row_idx in range(2, ws.max_row + 1):
            sid_val = str(ws.cell(row=row_idx, column=1).value or "").strip().lower()
            cid_val = str(ws.cell(row=row_idx, column=2).value or "").strip().lower()
            name_val = str(ws.cell(row=row_idx, column=4).value or "").strip().lower()

            match = False
            if target_sid and sid_val and target_sid == sid_val:
                match = True
            elif target_cid and target_name and cid_val == target_cid and name_val == target_name:
                match = True

            if match:
                if personal_linkedin_url:
                    ws.cell(row=row_idx, column=7).value = personal_linkedin_url
                if linkedin_status:
                    ws.cell(row=row_idx, column=8).value = linkedin_status
                if professional_email:
                    ws.cell(row=row_idx, column=9).value = professional_email
                if email_source_url:
                    ws.cell(row=row_idx, column=10).value = email_source_url
                if verification_status:
                    ws.cell(row=row_idx, column=12).value = verification_status
                if last_checked_at:
                    ws.cell(row=row_idx, column=13).value = last_checked_at
                updated = True
                break

        if updated:
            self._safe_save(wb)
        return updated

    def sync_weekly_attendees_to_excel(
        self,
        attendees: List[Any],
        replace_all: bool = False
    ) -> Dict[str, Any]:
        """
        Appends or refreshes weekly attendees to the 'weekly_attendees' sheet in the local Excel workbook.
        Headers: Conference Name, Conference Date, Attendee Name, Job Title, Company,
                 Professional Email, LinkedIn URL, Source URL, Collection Date.
        Never overwrites or disturbs existing conference, speaker, or source log records.
        """
        if not attendees and not replace_all:
            return {"status": "skipped", "inserted_count": 0}

        self._ensure_file_exists()
        wb = load_workbook(self.file_path)

        sheet_name = "weekly_attendees"
        cols = [
            "Conference Name", "Conference Date", "Attendee Name", "Job Title", "Company",
            "Professional Email", "LinkedIn URL", "Source URL", "Collection Date", "Email Status"
        ]

        if sheet_name not in wb.sheetnames:
            ws = wb.create_sheet(sheet_name)
            ws.append(cols)
            self._apply_header_styles(ws)
        else:
            ws = wb[sheet_name]
            if replace_all:
                wb.remove(ws)
                ws = wb.create_sheet(sheet_name)
                ws.append(cols)
                self._apply_header_styles(ws)

        existing_keys = set()
        for row in ws.iter_rows(min_row=2, max_col=3, values_only=True):
            if row and row[0] and len(row) >= 3 and row[2]:
                existing_keys.add((str(row[0]).strip().lower(), str(row[2]).strip().lower()))

        added_count = 0
        skipped_count = 0
        from datetime import date as _dt_date

        for att in attendees:
            conf_name = (att.conference_name if hasattr(att, "conference_name") else att.get("conference_name", "")) or ""
            att_name = (att.attendee_name if hasattr(att, "attendee_name") else att.get("attendee_name", "")) or ""
            key = (conf_name.strip().lower(), att_name.strip().lower())
            if key in existing_keys:
                skipped_count += 1
                continue

            conf_date = ""
            if hasattr(att, "conference_date") and att.conference_date:
                conf_date = att.conference_date.isoformat() if hasattr(att.conference_date, "isoformat") else str(att.conference_date)
            elif isinstance(att, dict) and att.get("conference_date"):
                conf_date = str(att["conference_date"])

            coll_date = ""
            if hasattr(att, "collection_date") and att.collection_date:
                coll_date = att.collection_date.isoformat() if hasattr(att.collection_date, "isoformat") else str(att.collection_date)
            elif isinstance(att, dict) and att.get("collection_date"):
                coll_date = str(att["collection_date"])
            else:
                coll_date = _dt_date.today().isoformat()

            ws.append([
                conf_name,
                conf_date,
                att_name,
                (att.job_title if hasattr(att, "job_title") else att.get("job_title", "")) or "",
                (att.company_name if hasattr(att, "company_name") else att.get("company_name", "")) or "",
                (att.professional_email if hasattr(att, "professional_email") else att.get("professional_email", "")) or "",
                (att.personal_linkedin_url if hasattr(att, "personal_linkedin_url") else att.get("personal_linkedin_url", "")) or "",
                (att.source_url if hasattr(att, "source_url") else att.get("source_url", "")) or "",
                coll_date,
                (att.email_status if hasattr(att, "email_status") else att.get("email_status", "Not Found")) or "Not Found"
            ])
            existing_keys.add(key)
            added_count += 1

        self._safe_save(wb)
        logger.info(f"✅ Local Excel weekly_attendees sync: {added_count} appended, {skipped_count} skipped/duplicate.")
        return {"status": "success", "inserted_count": added_count, "skipped_count": skipped_count}

    def sync_weekly_exhibitors_to_excel(
        self,
        exhibitors: List[Any],
        replace_all: bool = False
    ) -> Dict[str, Any]:
        """
        Appends or refreshes weekly exhibitors in the 'weekly_exhibitors' sheet in the local Excel workbook.
        Headers: Conference Name, Conference Date, Exhibitor Company Name, Company Website,
                 Exhibitor Category / Industry, Company Description, Exhibitor Booth Number,
                 Contact Person, Contact Person Designation, Professional Email,
                 LinkedIn Company URL, Contact Person LinkedIn URL, Source URL, Collection Date.
        Never overwrites or disturbs existing conference, speaker, or attendee records.
        """
        if not exhibitors and not replace_all:
            return {"status": "skipped", "inserted_count": 0}

        self._ensure_file_exists()
        wb = load_workbook(self.file_path)

        sheet_name = "weekly_exhibitors"
        cols = [
            "Conference Name", "Conference Date", "Exhibitor Company Name", "Company Website",
            "Exhibitor Category / Industry", "Company Description", "Exhibitor Booth Number",
            "Contact Person", "Contact Person Designation", "Professional Email",
            "LinkedIn Company URL", "Contact Person LinkedIn URL", "Source URL", "Collection Date", "Email Status"
        ]

        if sheet_name not in wb.sheetnames:
            ws = wb.create_sheet(sheet_name)
            ws.append(cols)
            self._apply_header_styles(ws)
        else:
            ws = wb[sheet_name]
            if replace_all:
                wb.remove(ws)
                ws = wb.create_sheet(sheet_name)
                ws.append(cols)
                self._apply_header_styles(ws)

        existing_keys = set()
        for row in ws.iter_rows(min_row=2, max_col=3, values_only=True):
            if row and row[0] and len(row) >= 3 and row[2]:
                existing_keys.add((str(row[0]).strip().lower(), str(row[2]).strip().lower()))

        added_count = 0
        skipped_count = 0
        from datetime import date as _dt_date

        for exh in exhibitors:
            conf_name = (exh.conference_name if hasattr(exh, "conference_name") else exh.get("conference_name", "")) or ""
            comp_name = (exh.company_name if hasattr(exh, "company_name") else exh.get("company_name", "")) or ""
            key = (conf_name.strip().lower(), comp_name.strip().lower())
            if key in existing_keys:
                skipped_count += 1
                continue

            conf_date = ""
            if hasattr(exh, "conference_date") and exh.conference_date:
                conf_date = exh.conference_date.isoformat() if hasattr(exh.conference_date, "isoformat") else str(exh.conference_date)
            elif isinstance(exh, dict) and exh.get("conference_date"):
                conf_date = str(exh["conference_date"])

            coll_date = ""
            if hasattr(exh, "collection_date") and exh.collection_date:
                coll_date = exh.collection_date.isoformat() if hasattr(exh.collection_date, "isoformat") else str(exh.collection_date)
            elif isinstance(exh, dict) and exh.get("collection_date"):
                coll_date = str(exh["collection_date"])
            else:
                coll_date = _dt_date.today().isoformat()

            ws.append([
                conf_name,
                conf_date,
                comp_name,
                (exh.company_website if hasattr(exh, "company_website") else exh.get("company_website", "")) or "",
                (exh.category_industry if hasattr(exh, "category_industry") else exh.get("category_industry", "")) or "",
                (exh.company_description if hasattr(exh, "company_description") else exh.get("company_description", "")) or "",
                (exh.booth_number if hasattr(exh, "booth_number") else exh.get("booth_number", "")) or "",
                (exh.contact_person if hasattr(exh, "contact_person") else exh.get("contact_person", "")) or "",
                (exh.contact_designation if hasattr(exh, "contact_designation") else exh.get("contact_designation", "")) or "",
                (exh.professional_email if hasattr(exh, "professional_email") else exh.get("professional_email", "")) or "",
                (exh.company_linkedin_url if hasattr(exh, "company_linkedin_url") else exh.get("company_linkedin_url", "")) or "",
                (exh.contact_person_linkedin_url if hasattr(exh, "contact_person_linkedin_url") else exh.get("contact_person_linkedin_url", "")) or "",
                (exh.source_url if hasattr(exh, "source_url") else exh.get("source_url", "")) or "",
                coll_date,
                (exh.email_status if hasattr(exh, "email_status") else exh.get("email_status", "Not Found")) or "Not Found"
            ])
            existing_keys.add(key)
            added_count += 1

        self._safe_save(wb)
        logger.info(f"✅ Local Excel weekly_exhibitors sync: {added_count} appended, {skipped_count} skipped/duplicate.")
        return {"status": "success", "inserted_count": added_count, "skipped_count": skipped_count}

    def sync_verified_data_to_excel(self, contacts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Synchronizes verified contacts (speakers, attendees, exhibitors with verified email)
        to the 'Verified Data' sheet in local Excel.
        """
        from ..services.verified_data_service import VerifiedDataService
        from ..database import SessionLocal
        db = SessionLocal()
        try:
            svc = VerifiedDataService(db)
            return svc.sync_to_local_excel(contacts)
        finally:
            db.close()

    def update_verified_data_row_in_excel(
        self,
        email: str,
        updates: Dict[str, Any],
        thread_id: Optional[str] = None,
        category: Optional[str] = None
    ) -> bool:
        """
        Updates an existing contact row in Local Excel 'Verified Data' worksheet by email or thread_id
        across Speaker, Attendee, and Exhibitor column sets.
        """
        self._ensure_file_exists()
        wb = load_workbook(self.file_path)
        if "Verified Data" not in wb.sheetnames:
            return False
        ws = wb["Verified Data"]
        rows = list(ws.iter_rows(values_only=True))
        if not rows or len(rows) < 2:
            return False
        headers = [str(h).strip().lower().replace(" ", "").replace("_", "").replace("/", "") for h in rows[0]]
        header_map = {name: idx + 1 for idx, name in enumerate(headers)}

        clean_email = (email or "").strip().lower()
        clean_thread = (thread_id or "").strip()

        target_row_idx = None
        detected_category = category

        cat_checks = [
            ("Speaker", header_map.get("speakerprofessionalemail"), header_map.get("speakerthreadid")),
            ("Attendee", header_map.get("attendeeprofessionalemail"), header_map.get("attendeethreadid")),
            ("Exhibitor", header_map.get("exhibitorprofessionalemail"), header_map.get("exhibitorthreadid")),
            ("Speaker", header_map.get("professionalemail"), header_map.get("threadid"))
        ]

        for r_idx in range(2, ws.max_row + 1):
            for cat, em_col, th_col in cat_checks:
                if em_col:
                    cell_em = str(ws.cell(row=r_idx, column=em_col).value or "").strip().lower()
                    if clean_email and cell_em == clean_email:
                        target_row_idx = r_idx
                        detected_category = detected_category or cat
                        break
                if th_col:
                    cell_th = str(ws.cell(row=r_idx, column=th_col).value or "").strip()
                    if clean_thread and cell_th == clean_thread:
                        target_row_idx = r_idx
                        detected_category = detected_category or cat
                        break
            if target_row_idx:
                break

        if not target_row_idx:
            return False

        detected_category = detected_category or "Speaker"

        for field, val in updates.items():
            f_clean = field.strip()
            f_key = f_clean.lower().replace(" ", "").replace("_", "").replace("/", "")
            col_num = header_map.get(f_key)

            if col_num is None:
                cat_field = f"{detected_category} {f_clean}"
                f_key_cat = cat_field.lower().replace(" ", "").replace("_", "").replace("/", "")
                col_num = header_map.get(f_key_cat)

            if col_num is None and "replay" in f_key:
                f_key_alt = f_key.replace("replay", "reply")
                col_num = header_map.get(f_key_alt) or header_map.get(f"{detected_category.lower()}{f_key_alt}")

            if col_num is not None:
                ws.cell(row=target_row_idx, column=col_num).value = val

        self._safe_save(wb)
        return True

    def append_speaker_reply_to_excel(self, row_values: List[Any]) -> Dict[str, Any]:
        """
        Appends a separate speaker reply record to the 'Speakers Replies' worksheet in local Excel.
        Preserves 'weekly_speakers' completely untouched.
        """
        self._ensure_file_exists()
        wb = load_workbook(self.file_path)

        sheet_name = "Speakers Replies"
        headers = [
            "spekers_id", "Conference_ID", "Conference_Name", "Speaker_Name", "Job_Title",
            "Company_Name", "Personal_LinkedIn_URL", "LinkedIn_Status", "Professional_Email",
            "Email_Source_URL", "Speaker_Source_URL", "Verification_Status", "Last_Checked_At",
            "Weekly_Run_ID", "outreach status", "reply status", "reply sentiment",
            "received reply", "send message", "thread id", "Reply_Received_At", "Message_ID"
        ]

        if sheet_name not in wb.sheetnames:
            ws = wb.create_sheet(sheet_name)
            ws.append(headers)
            self._apply_header_styles(ws)
        else:
            ws = wb[sheet_name]

        msg_id = str(row_values[21] or "").strip() if len(row_values) > 21 else ""
        if msg_id:
            for r in range(2, ws.max_row + 1):
                existing_mid = str(ws.cell(row=r, column=22).value or "").strip()
                if existing_mid == msg_id:
                    logger.info(f"Local Excel '{sheet_name}': Message ID '{msg_id}' already exists. Skipping duplicate.")
                    wb.close()
                    return {"status": "skipped", "reason": "duplicate_message_id"}

        padded_row = list(row_values)
        while len(padded_row) < len(headers):
            padded_row.append("")
        ws.append(padded_row[:len(headers)])
        self._safe_save(wb)
        logger.info(f"✅ Local Excel: Appended reply record for '{row_values[3]}' to '{sheet_name}'.")
        return {"status": "success", "inserted": 1}


    def read_excel_as_dataframe(self, sheet_name: str = "USA Conferences") -> pd.DataFrame:
        self._ensure_file_exists()
        return pd.read_excel(self.file_path, sheet_name=sheet_name)

    def read_all_sheets(self):
        self._ensure_file_exists()
        xls = pd.ExcelFile(self.file_path)
        result = {}
        for s in xls.sheet_names:
            result[s] = pd.read_excel(xls, sheet_name=s).fillna("").to_dict(orient="records")
        return result

    def sync_qualified_leads_to_excel(self, qualified_rows: List[List[Any]], headers: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Synchronizes qualified leads (score > 50) with 6 outreach tracking columns to 'Qualified Leads' worksheet in Local Excel.
        Preserves existing outreach tracking states across syncs.
        """
        self._ensure_file_exists()
        wb = load_workbook(self.file_path)
        sheet_name = getattr(settings, "QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME", "Qualified Leads")

        from openpyxl.styles import PatternFill, Font, Alignment

        if headers is None:
            headers = [
                "Rank", "Overall_Score", "Qualification_Status", "Company_Name",
                "Company_Domain", "Conference_Name", "Conference_ID", "Contact_Type",
                "Contact_Name", "Job_Title", "Professional_Email", "Email_Status",
                "Personal_LinkedIn_URL", "Primary_Industry", "Headcount_Tier",
                "Evaluated_At", "Outreach Status", "Reply Status", "Received Reply",
                "Reply Sentiment", "Thread ID", "Send Message"
            ]

        # Read existing outreach history if sheet exists to avoid overwriting sent/replied statuses
        existing_history: Dict[str, Dict[str, Any]] = {}
        if sheet_name in wb.sheetnames:
            ws_exist = wb[sheet_name]
            h_row = [str(cell.value or "").strip().lower().replace(" ", "").replace("_", "") for cell in ws_exist[1]]
            h_map = {name: idx for idx, name in enumerate(h_row)}
            em_idx = h_map.get("professionalemail") or h_map.get("email")
            ost_idx = h_map.get("outreachstatus")
            rep_idx = h_map.get("replystatus") or h_map.get("replaystatus")
            rec_idx = h_map.get("receivedreply") or h_map.get("receivedreplay")
            sent_idx = h_map.get("replysentiment") or h_map.get("sentiment")
            th_idx = h_map.get("threadid")
            snd_idx = h_map.get("sendmessage")

            if em_idx is not None:
                for r in range(2, ws_exist.max_row + 1):
                    em_val = str(ws_exist.cell(row=r, column=em_idx + 1).value or "").strip().lower()
                    if em_val and "@" in em_val:
                        existing_history[em_val] = {
                            "outreach_status": ws_exist.cell(row=r, column=ost_idx + 1).value if ost_idx is not None else "",
                            "reply_status": ws_exist.cell(row=r, column=rep_idx + 1).value if rep_idx is not None else "",
                            "received_reply": ws_exist.cell(row=r, column=rec_idx + 1).value if rec_idx is not None else "",
                            "reply_sentiment": ws_exist.cell(row=r, column=sent_idx + 1).value if sent_idx is not None else "",
                            "thread_id": ws_exist.cell(row=r, column=th_idx + 1).value if th_idx is not None else "",
                            "send_message": ws_exist.cell(row=r, column=snd_idx + 1).value if snd_idx is not None else ""
                        }
            del wb[sheet_name]

        ws = wb.create_sheet(title=sheet_name)
        # Write Header
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = Font(name="Calibri", size=11, bold=True, color="1B365D")
            cell.fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center")

        # Map header indices
        cur_h_map = {h.lower().replace(" ", "").replace("_", ""): idx for idx, h in enumerate(headers)}
        em_col_idx = cur_h_map.get("professionalemail", 10)
        ost_col_idx = cur_h_map.get("outreachstatus", 16)
        rep_col_idx = cur_h_map.get("replystatus", 17)
        rec_col_idx = cur_h_map.get("receivedreply", 18)
        sent_col_idx = cur_h_map.get("replysentiment", 19)
        th_col_idx = cur_h_map.get("threadid", 20)
        snd_col_idx = cur_h_map.get("sendmessage", 21)

        for row_idx, row_data in enumerate(qualified_rows, 2):
            padded = list(row_data)
            while len(padded) < len(headers):
                padded.append("")

            # Restore existing outreach data if previously tracked
            email_val = str(padded[em_col_idx] or "").strip().lower()
            if email_val in existing_history:
                hist = existing_history[email_val]
                if hist.get("outreach_status"):
                    padded[ost_col_idx] = hist["outreach_status"]
                if hist.get("reply_status"):
                    padded[rep_col_idx] = hist["reply_status"]
                if hist.get("received_reply"):
                    padded[rec_col_idx] = hist["received_reply"]
                if hist.get("reply_sentiment"):
                    padded[sent_col_idx] = hist["reply_sentiment"]
                if hist.get("thread_id"):
                    padded[th_col_idx] = hist["thread_id"]
                if hist.get("send_message"):
                    padded[snd_col_idx] = hist["send_message"]

            qual_val = str(padded[2] or "").upper()
            score_val = float(padded[1] or 0)
            fill_color = "D9EAD3" if (qual_val == "HIGH_MATCH" or score_val >= 75.0) else "FFF2CC"
            row_fill = PatternFill(start_color=fill_color, end_color=fill_color, fill_type="solid")

            for col_idx, val in enumerate(padded[:len(headers)], 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.fill = row_fill
                cell.font = Font(name="Calibri", size=10)

        self._safe_save(wb)
        logger.info(f"✅ Local Excel: Successfully synced {len(qualified_rows)} leads to '{sheet_name}'.")
        return {"status": "success", "count": len(qualified_rows)}

    def update_qualified_leads_row_in_excel(
        self,
        email: str,
        updates: Dict[str, Any],
        thread_id: Optional[str] = None
    ) -> bool:
        """
        Updates an existing contact row in Local Excel 'Qualified Leads' worksheet.
        """
        self._ensure_file_exists()
        wb = load_workbook(self.file_path)
        sheet_name = getattr(settings, "QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME", "Qualified Leads")
        if sheet_name not in wb.sheetnames:
            return False
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows or len(rows) < 2:
            return False

        headers = [str(h).strip().lower().replace(" ", "").replace("_", "").replace("/", "") for h in rows[0]]
        header_map = {name: idx + 1 for idx, name in enumerate(headers)}

        clean_email = (email or "").strip().lower()
        clean_thread = (thread_id or "").strip()

        target_row_idx = None
        em_col = header_map.get("professionalemail") or header_map.get("email")
        th_col = header_map.get("threadid")

        for r_idx in range(2, ws.max_row + 1):
            if em_col:
                c_em = str(ws.cell(row=r_idx, column=em_col).value or "").strip().lower()
                if clean_email and c_em == clean_email:
                    target_row_idx = r_idx
                    break
            if th_col:
                c_th = str(ws.cell(row=r_idx, column=th_col).value or "").strip()
                if clean_thread and c_th == clean_thread:
                    target_row_idx = r_idx
                    break

        if not target_row_idx:
            return False

        for field, val in updates.items():
            f_clean = field.strip()
            f_key = f_clean.lower().replace(" ", "").replace("_", "").replace("/", "")
            col_idx = header_map.get(f_key)
            if col_idx is None and "replay" in f_key:
                col_idx = header_map.get(f_key.replace("replay", "reply"))
            if col_idx:
                ws.cell(row=target_row_idx, column=col_idx, value=val)

        self._safe_save(wb)
        return True

    def sync_non_qualified_leads_to_excel(self, non_qualified_rows: List[List[Any]], headers: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Synchronizes non-qualified leads (score < 50) with 6 outreach tracking columns to 'Non -Qualified Leads' worksheet in Local Excel.
        Preserves existing outreach tracking states across syncs.
        """
        self._ensure_file_exists()
        wb = load_workbook(self.file_path)
        sheet_name = getattr(settings, "NON_QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME", "Non -Qualified Leads")

        from openpyxl.styles import PatternFill, Font, Alignment

        if headers is None:
            headers = [
                "Rank", "Overall_Score", "Qualification_Status", "Company_Name",
                "Company_Domain", "Conference_Name", "Conference_ID", "Contact_Type",
                "Contact_Name", "Job_Title", "Professional_Email", "Email_Status",
                "Personal_LinkedIn_URL", "Primary_Industry", "Headcount_Tier",
                "Evaluated_At", "Outreach Status", "Reply Status", "Received Reply",
                "Reply Sentiment", "Thread ID", "Send Message"
            ]

        existing_history: Dict[str, Dict[str, Any]] = {}
        target_ws_name = None
        for s in [sheet_name, "Non -Qualified Leads", "Non-Qualified Leads", "Disqualified Leads"]:
            if s in wb.sheetnames:
                target_ws_name = s
                break

        if target_ws_name and target_ws_name in wb.sheetnames:
            ws_exist = wb[target_ws_name]
            h_row = [str(cell.value or "").strip().lower().replace(" ", "").replace("_", "") for cell in ws_exist[1]]
            h_map = {name: idx for idx, name in enumerate(h_row)}
            em_idx = h_map.get("professionalemail") or h_map.get("email")
            ost_idx = h_map.get("outreachstatus")
            rep_idx = h_map.get("replystatus") or h_map.get("replaystatus")
            rec_idx = h_map.get("receivedreply") or h_map.get("receivedreplay")
            sent_idx = h_map.get("replysentiment") or h_map.get("sentiment")
            th_idx = h_map.get("threadid")
            snd_idx = h_map.get("sendmessage")

            if em_idx is not None:
                for r in range(2, ws_exist.max_row + 1):
                    em_val = str(ws_exist.cell(row=r, column=em_idx + 1).value or "").strip().lower()
                    if em_val and "@" in em_val:
                        existing_history[em_val] = {
                            "outreach_status": ws_exist.cell(row=r, column=ost_idx + 1).value if ost_idx is not None else "",
                            "reply_status": ws_exist.cell(row=r, column=rep_idx + 1).value if rep_idx is not None else "",
                            "received_reply": ws_exist.cell(row=r, column=rec_idx + 1).value if rec_idx is not None else "",
                            "reply_sentiment": ws_exist.cell(row=r, column=sent_idx + 1).value if sent_idx is not None else "",
                            "thread_id": ws_exist.cell(row=r, column=th_idx + 1).value if th_idx is not None else "",
                            "send_message": ws_exist.cell(row=r, column=snd_idx + 1).value if snd_idx is not None else ""
                        }
            del wb[target_ws_name]

        ws = wb.create_sheet(title=sheet_name)
        # Write Header
        for col_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = Font(name="Calibri", size=11, bold=True, color="5B2C05")
            cell.fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center")

        cur_h_map = {h.lower().replace(" ", "").replace("_", ""): idx for idx, h in enumerate(headers)}
        em_col_idx = cur_h_map.get("professionalemail", 10)
        ost_col_idx = cur_h_map.get("outreachstatus", 16)
        rep_col_idx = cur_h_map.get("replystatus", 17)
        rec_col_idx = cur_h_map.get("receivedreply", 18)
        sent_col_idx = cur_h_map.get("replysentiment", 19)
        th_col_idx = cur_h_map.get("threadid", 20)
        snd_col_idx = cur_h_map.get("sendmessage", 21)

        row_fill = PatternFill(start_color="FCE5CD", end_color="FCE5CD", fill_type="solid")

        for row_idx, row_data in enumerate(non_qualified_rows, 2):
            padded = list(row_data)
            while len(padded) < len(headers):
                padded.append("")

            email_val = str(padded[em_col_idx] or "").strip().lower()
            if email_val in existing_history:
                hist = existing_history[email_val]
                if hist.get("outreach_status"):
                    padded[ost_col_idx] = hist["outreach_status"]
                if hist.get("reply_status"):
                    padded[rep_col_idx] = hist["reply_status"]
                if hist.get("received_reply"):
                    padded[rec_col_idx] = hist["received_reply"]
                if hist.get("reply_sentiment"):
                    padded[sent_col_idx] = hist["reply_sentiment"]
                if hist.get("thread_id"):
                    padded[th_col_idx] = hist["thread_id"]
                if hist.get("send_message"):
                    padded[snd_col_idx] = hist["send_message"]

            for col_idx, val in enumerate(padded[:len(headers)], 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.fill = row_fill
                cell.font = Font(name="Calibri", size=10)

        self._safe_save(wb)
        logger.info(f"✅ Local Excel: Successfully synced {len(non_qualified_rows)} leads to '{sheet_name}'.")
        return {"status": "success", "count": len(non_qualified_rows)}

    def update_non_qualified_leads_row_in_excel(
        self,
        email: str,
        updates: Dict[str, Any],
        thread_id: Optional[str] = None
    ) -> bool:
        """
        Updates an existing contact row in Local Excel 'Non -Qualified Leads' worksheet.
        """
        self._ensure_file_exists()
        wb = load_workbook(self.file_path)
        sheet_name = getattr(settings, "NON_QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME", "Non -Qualified Leads")
        target_ws_name = None
        for s in [sheet_name, "Non -Qualified Leads", "Non-Qualified Leads", "Disqualified Leads"]:
            if s in wb.sheetnames:
                target_ws_name = s
                break

        if not target_ws_name:
            return False

        ws = wb[target_ws_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows or len(rows) < 2:
            return False

        headers = [str(h).strip().lower().replace(" ", "").replace("_", "").replace("/", "") for h in rows[0]]
        header_map = {name: idx + 1 for idx, name in enumerate(headers)}

        clean_email = (email or "").strip().lower()
        clean_thread = (thread_id or "").strip()

        target_row_idx = None
        em_col = header_map.get("professionalemail") or header_map.get("email")
        th_col = header_map.get("threadid")

        for r_idx in range(2, ws.max_row + 1):
            if em_col:
                c_em = str(ws.cell(row=r_idx, column=em_col).value or "").strip().lower()
                if clean_email and c_em == clean_email:
                    target_row_idx = r_idx
                    break
            if th_col:
                c_th = str(ws.cell(row=r_idx, column=th_col).value or "").strip()
                if clean_thread and c_th == clean_thread:
                    target_row_idx = r_idx
                    break

        if not target_row_idx:
            return False

        for field, val in updates.items():
            f_clean = field.strip()
            f_key = f_clean.lower().replace(" ", "").replace("_", "").replace("/", "")
            col_idx = header_map.get(f_key)
            if col_idx is None and "replay" in f_key:
                col_idx = header_map.get(f_key.replace("replay", "reply"))
            if col_idx:
                ws.cell(row=target_row_idx, column=col_idx, value=val)

        self._safe_save(wb)
        return True
