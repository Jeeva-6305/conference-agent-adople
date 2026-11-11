import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any, Set
import pandas as pd
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

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

        existing_wconf_rows: Dict[str, int] = {}
        for r_idx in range(2, ws_wconf.max_row + 1):
            c_id_cell = str(ws_wconf.cell(row=r_idx, column=1).value or "").strip().lower()
            c_name_cell = str(ws_wconf.cell(row=r_idx, column=2).value or "").strip().lower()
            if c_id_cell and c_id_cell not in existing_wconf_rows:
                existing_wconf_rows[c_id_cell] = r_idx
            if c_name_cell and c_name_cell not in existing_wconf_rows:
                existing_wconf_rows[c_name_cell] = r_idx

        added_confs = 0
        for c in conferences:
            c_id = (c.conference_id or "").strip().lower()
            c_name = (c.conference_name or "").strip().lower()
            match_row = existing_wconf_rows.get(c_id) or existing_wconf_rows.get(c_name)
            if match_row:
                # Update speaker_status, last_checked_at, and backfill empty metadata in-place
                if (c.speaker_status or "").strip().lower() == "yes":
                    ws_wconf.cell(row=match_row, column=13).value = "Yes"
                if c.last_checked_at:
                    ws_wconf.cell(row=match_row, column=14).value = c.last_checked_at.isoformat()
                if not str(ws_wconf.cell(row=match_row, column=5).value or "").strip() and c.city:
                    ws_wconf.cell(row=match_row, column=5).value = c.city
                if not str(ws_wconf.cell(row=match_row, column=6).value or "").strip() and c.state:
                    ws_wconf.cell(row=match_row, column=6).value = c.state
                if not str(ws_wconf.cell(row=match_row, column=8).value or "").strip() and c.industry:
                    ws_wconf.cell(row=match_row, column=8).value = c.industry
                if not str(ws_wconf.cell(row=match_row, column=9).value or "").strip() and c.official_event_url:
                    ws_wconf.cell(row=match_row, column=9).value = c.official_event_url
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
            new_row_idx = ws_wconf.max_row
            if c_id:
                existing_wconf_rows[c_id] = new_row_idx
            if c_name:
                existing_wconf_rows[c_name] = new_row_idx
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

        existing_wspk_rows: Dict[tuple, int] = {}
        for r_idx in range(2, ws_wspk.max_row + 1):
            cid_val = str(ws_wspk.cell(row=r_idx, column=2).value or "").strip().lower()
            sname_val = str(ws_wspk.cell(row=r_idx, column=4).value or "").strip().lower()
            if cid_val and sname_val and (cid_val, sname_val) not in existing_wspk_rows:
                existing_wspk_rows[(cid_val, sname_val)] = r_idx

        added_spks = 0
        for s in speakers:
            spk_key = ((s.conference_id or "").strip().lower(), (s.speaker_name or "").strip().lower())
            match_spk_row = existing_wspk_rows.get(spk_key)
            if match_spk_row:
                # Backfill empty speaker enrichment/profile fields without overwriting outreach columns (cols 15+)
                if not str(ws_wspk.cell(row=match_spk_row, column=5).value or "").strip() and s.job_title:
                    ws_wspk.cell(row=match_spk_row, column=5).value = s.job_title
                if not str(ws_wspk.cell(row=match_spk_row, column=6).value or "").strip() and s.company_name:
                    ws_wspk.cell(row=match_spk_row, column=6).value = s.company_name
                if not str(ws_wspk.cell(row=match_spk_row, column=7).value or "").strip() and s.personal_linkedin_url:
                    ws_wspk.cell(row=match_spk_row, column=7).value = s.personal_linkedin_url
                if s.linkedin_status and str(ws_wspk.cell(row=match_spk_row, column=8).value or "").strip().lower() != "verified":
                    ws_wspk.cell(row=match_spk_row, column=8).value = s.linkedin_status
                if not str(ws_wspk.cell(row=match_spk_row, column=9).value or "").strip() and s.professional_email:
                    ws_wspk.cell(row=match_spk_row, column=9).value = s.professional_email
                if not str(ws_wspk.cell(row=match_spk_row, column=10).value or "").strip() and s.email_source_url:
                    ws_wspk.cell(row=match_spk_row, column=10).value = s.email_source_url
                if (s.verification_status or "").strip().lower() == "verified":
                    ws_wspk.cell(row=match_spk_row, column=12).value = "verified"
                if s.last_checked_at:
                    ws_wspk.cell(row=match_spk_row, column=13).value = s.last_checked_at.isoformat()
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
            existing_wspk_rows[spk_key] = ws_wspk.max_row
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
        last_checked_at: Optional[str] = None,
        job_title: Optional[str] = None,
        company_name: Optional[str] = None,
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
                if job_title and not str(ws.cell(row=row_idx, column=5).value or "").strip():
                    ws.cell(row=row_idx, column=5).value = job_title
                if company_name and not str(ws.cell(row=row_idx, column=6).value or "").strip():
                    ws.cell(row=row_idx, column=6).value = company_name
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
        Preserves all 16 columns (including cols 11-16 outreach/reply tracking) and historical real records.
        """
        if not attendees and not replace_all:
            return {"status": "skipped", "inserted_count": 0}

        self._ensure_file_exists()
        wb = load_workbook(self.file_path)

        sheet_name = "weekly_attendees"
        cols = [
            "Conference Name", "Conference Date", "Attendee Name", "Job Title", "Company",
            "Professional Email", "LinkedIn URL", "Source URL", "Collection Date", "Email Status",
            "outreach status", "reply status", "reply sentiment", "received reply", "send message", "thread id"
        ]

        cached_outreach_by_key: Dict[tuple, List[Any]] = {}
        cached_outreach_by_email: Dict[str, List[Any]] = {}
        cached_real_rows: List[List[Any]] = []
        existing_headers: List[str] = list(cols)

        if sheet_name in wb.sheetnames:
            ws_old = wb[sheet_name]
            old_rows = list(ws_old.iter_rows(values_only=True))
            if old_rows:
                raw_hdr = [str(h or "") for h in old_rows[0]]
                if len(raw_hdr) >= 16:
                    existing_headers = raw_hdr[:16]
                for r in old_rows[1:]:
                    if not r or not any(r):
                        continue
                    r_list = list(r)
                    while len(r_list) < len(existing_headers):
                        r_list.append("")
                    c_name = str(r_list[0] or "").strip()
                    a_name = str(r_list[2] or "").strip()
                    if not c_name or not a_name or a_name.lower() == "not publicly available":
                        continue
                    tail = list(r_list[10:16])
                    while len(tail) < 6:
                        tail.append("")
                    cached_outreach_by_key[(c_name.lower(), a_name.lower())] = tail
                    em_v = str(r_list[5] or "").strip().lower()
                    if em_v and "@" in em_v:
                        cached_outreach_by_email[em_v] = tail
                    cached_real_rows.append(r_list[:len(existing_headers)])
            if replace_all:
                wb.remove(ws_old)
                ws = wb.create_sheet(sheet_name)
                ws.append(existing_headers)
                self._apply_header_styles(ws)
            else:
                ws = ws_old
        else:
            ws = wb.create_sheet(sheet_name)
            ws.append(existing_headers)
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
            if not conf_name.strip() or not att_name.strip() or att_name.strip().lower() == "not publicly available":
                skipped_count += 1
                continue
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

            prof_email = (att.professional_email if hasattr(att, "professional_email") else att.get("professional_email", "")) or ""
            outreach_tail = (
                cached_outreach_by_key.get(key)
                or (cached_outreach_by_email.get(prof_email.strip().lower()) if prof_email else None)
                or ["", "", "", "", "", ""]
            )

            row_vals = [
                conf_name,
                conf_date,
                att_name,
                (att.job_title if hasattr(att, "job_title") else att.get("job_title", "")) or "",
                (att.company_name if hasattr(att, "company_name") else att.get("company_name", "")) or "",
                prof_email,
                (att.personal_linkedin_url if hasattr(att, "personal_linkedin_url") else att.get("personal_linkedin_url", "")) or "",
                (att.source_url if hasattr(att, "source_url") else att.get("source_url", "")) or "",
                coll_date,
                (att.email_status if hasattr(att, "email_status") else att.get("email_status", "Not Found")) or "Not Found"
            ] + list(outreach_tail[:6])
            ws.append(row_vals)
            existing_keys.add(key)
            added_count += 1

        if replace_all and cached_real_rows:
            for hist_row in cached_real_rows:
                h_key = (str(hist_row[0] or "").strip().lower(), str(hist_row[2] or "").strip().lower())
                if h_key not in existing_keys:
                    ws.append(hist_row)
                    existing_keys.add(h_key)
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
        Preserves all 21 columns (including cols 16-21 outreach/reply tracking) and historical real records.
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
            "LinkedIn Company URL", "Contact Person LinkedIn URL", "Source URL", "Collection Date", "Email Status",
            "outreach status", "reply status", "reply sentiment", "received reply", "send message", "thread id"
        ]

        cached_outreach_by_key: Dict[tuple, List[Any]] = {}
        cached_outreach_by_email: Dict[str, List[Any]] = {}
        cached_real_rows: List[List[Any]] = []
        existing_headers: List[str] = list(cols)

        if sheet_name in wb.sheetnames:
            ws_old = wb[sheet_name]
            old_rows = list(ws_old.iter_rows(values_only=True))
            if old_rows:
                raw_hdr = [str(h or "") for h in old_rows[0]]
                if len(raw_hdr) >= 21:
                    existing_headers = raw_hdr[:21]
                for r in old_rows[1:]:
                    if not r or not any(r):
                        continue
                    r_list = list(r)
                    while len(r_list) < len(existing_headers):
                        r_list.append("")
                    c_name = str(r_list[0] or "").strip()
                    comp_n = str(r_list[2] or "").strip()
                    if not c_name or not comp_n or comp_n.lower() == "not publicly available":
                        continue
                    tail = list(r_list[15:21])
                    while len(tail) < 6:
                        tail.append("")
                    cached_outreach_by_key[(c_name.lower(), comp_n.lower())] = tail
                    em_v = str(r_list[9] or "").strip().lower()
                    if em_v and "@" in em_v:
                        cached_outreach_by_email[em_v] = tail
                    cached_real_rows.append(r_list[:len(existing_headers)])
            if replace_all:
                wb.remove(ws_old)
                ws = wb.create_sheet(sheet_name)
                ws.append(existing_headers)
                self._apply_header_styles(ws)
            else:
                ws = ws_old
        else:
            ws = wb.create_sheet(sheet_name)
            ws.append(existing_headers)
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
            if not conf_name.strip() or not comp_name.strip() or comp_name.strip().lower() == "not publicly available":
                skipped_count += 1
                continue
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

            prof_email = (exh.professional_email if hasattr(exh, "professional_email") else exh.get("professional_email", "")) or ""
            outreach_tail = (
                cached_outreach_by_key.get(key)
                or (cached_outreach_by_email.get(prof_email.strip().lower()) if prof_email else None)
                or ["", "", "", "", "", ""]
            )

            row_vals = [
                conf_name,
                conf_date,
                comp_name,
                (exh.company_website if hasattr(exh, "company_website") else exh.get("company_website", "")) or "",
                (exh.category_industry if hasattr(exh, "category_industry") else exh.get("category_industry", "")) or "",
                (exh.company_description if hasattr(exh, "company_description") else exh.get("company_description", "")) or "",
                (exh.booth_number if hasattr(exh, "booth_number") else exh.get("booth_number", "")) or "",
                (exh.contact_person if hasattr(exh, "contact_person") else exh.get("contact_person", "")) or "",
                (exh.contact_designation if hasattr(exh, "contact_designation") else exh.get("contact_designation", "")) or "",
                prof_email,
                (exh.company_linkedin_url if hasattr(exh, "company_linkedin_url") else exh.get("company_linkedin_url", "")) or "",
                (exh.contact_person_linkedin_url if hasattr(exh, "contact_person_linkedin_url") else exh.get("contact_person_linkedin_url", "")) or "",
                (exh.source_url if hasattr(exh, "source_url") else exh.get("source_url", "")) or "",
                coll_date,
                (exh.email_status if hasattr(exh, "email_status") else exh.get("email_status", "Not Found")) or "Not Found"
            ] + list(outreach_tail[:6])
            ws.append(row_vals)
            existing_keys.add(key)
            added_count += 1

        if replace_all and cached_real_rows:
            for hist_row in cached_real_rows:
                h_key = (str(hist_row[0] or "").strip().lower(), str(hist_row[2] or "").strip().lower())
                if h_key not in existing_keys:
                    ws.append(hist_row)
                    existing_keys.add(h_key)
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

    @staticmethod
    def _union_merge_lead_rows(
        existing_rows: List[List[Any]],
        incoming_rows: List[List[Any]],
        headers: List[str],
        default_status: str = "Pending",
    ) -> List[List[Any]]:
        """
        Union-merges existing historical lead rows with newly scored incoming rows
        using lowercase Professional_Email (or Company+Contact+Conference fallback),
        preserving outreach tracking states with precedence replied > bounced > sent > sending > failed > pending.
        Keeps existing contacted rows at top, existing unsent rows next, and always appends
        newly collected rows strictly below existing records, reassigning Rank 1..N.
        """
        cur_h_map = {h.lower().replace(" ", "").replace("_", ""): idx for idx, h in enumerate(headers)}
        em_col = cur_h_map.get("professionalemail", 10)
        comp_col = cur_h_map.get("companyname", 3)
        name_col = cur_h_map.get("contactname", 8)
        conf_col = cur_h_map.get("conferencename", 5)
        score_col = cur_h_map.get("overallscore", 1)
        out_ind_col = cur_h_map.get("industry")
        eval_col = cur_h_map.get("evaluatedat", 16)
        ost_col = cur_h_map.get("outreachstatus", 17)
        rep_col = cur_h_map.get("replystatus", 18)
        rec_col = cur_h_map.get("receivedreply", 19)
        sent_col = cur_h_map.get("replysentiment", 20)
        th_col = cur_h_map.get("threadid", 21)
        snd_col = cur_h_map.get("sendmessage", 22)
        valid_industries = {
            "healthcare": "Healthcare",
            "ai": "AI",
            "finance": "Finance",
            "medical": "Medical",
        }

        precedence = {
            "replied": 5,
            "bounced": 4,
            "do_not_contact": 4,
            "sent": 3,
            "sending": 2,
            "failed": 1,
            "pending": 0,
            "disqualified": 0,
            "": -1,
        }
        contacted_states = {"replied", "bounced", "do_not_contact", "sent", "sending", "failed"}

        def _normalize_row(row_vals: List[Any]) -> List[Any]:
            padded = ["" if v is None else v for v in list(row_vals)]
            while len(padded) < len(headers):
                padded.append("")
            padded = padded[:len(headers)]
            ev_v = padded[eval_col]
            if isinstance(ev_v, (int, float)) and not isinstance(ev_v, bool) and 40000 < float(ev_v) < 60000:
                padded[eval_col] = (datetime(1899, 12, 30) + timedelta(days=float(ev_v))).strftime("%Y-%m-%d %H:%M:%S")
            return padded

        def _row_key(row_vals: List[Any]) -> str:
            em = str(row_vals[em_col] or "").strip().lower()
            if em and "@" in em:
                return f"em:{em}"
            comp = str(row_vals[comp_col] or "").strip().lower()
            name = str(row_vals[name_col] or "").strip().lower()
            conf = str(row_vals[conf_col] or "").strip().lower()
            return f"alt:{comp}|{name}|{conf}"

        merged_map: Dict[str, List[Any]] = {}
        existing_order_keys: List[str] = []
        existing_keys_set: Set[str] = set()
        new_incoming_keys: List[str] = []

        for r in existing_rows:
            padded = _normalize_row(r)
            if not any(padded[1:]):
                continue
            k = _row_key(padded)
            if not k or k == "alt:||":
                continue
            if k not in merged_map:
                merged_map[k] = padded
                existing_order_keys.append(k)
                existing_keys_set.add(k)

        for r in incoming_rows:
            padded = _normalize_row(r)
            if not any(padded[1:]):
                continue
            k = _row_key(padded)
            if not k or k == "alt:||":
                continue

            if k not in merged_map:
                if not str(padded[ost_col] or "").strip():
                    padded[ost_col] = default_status
                merged_map[k] = padded
                new_incoming_keys.append(k)
            elif k in existing_keys_set:
                prev = merged_map[k]
                prev_st = str(prev[ost_col] or "").strip()
                new_st = str(padded[ost_col] or "").strip()

                for idx in range(len(headers)):
                    if idx in (ost_col, rep_col, rec_col, sent_col, th_col, snd_col):
                        continue
                    if (padded[idx] is None or str(padded[idx]).strip() == "") and prev[idx] not in (None, ""):
                        padded[idx] = prev[idx]

                # Preserve historical Evaluated_At on already-contacted leads
                if prev_st.lower() in contacted_states and str(prev[eval_col] or "").strip():
                    padded[eval_col] = prev[eval_col]

                # Preserve previously curated valid Industry categorization
                if out_ind_col is not None:
                    prev_ind = valid_industries.get(str(prev[out_ind_col] or "").strip().lower(), "")
                    if prev_ind:
                        padded[out_ind_col] = prev_ind

                if precedence.get(prev_st.lower(), 0) >= precedence.get(new_st.lower(), 0):
                    if prev_st:
                        padded[ost_col] = prev_st
                if not padded[ost_col]:
                    padded[ost_col] = default_status

                for track_idx in (rep_col, rec_col, sent_col, th_col, snd_col):
                    if str(prev[track_idx] or "").strip() and not str(padded[track_idx] or "").strip():
                        padded[track_idx] = prev[track_idx]

                merged_map[k] = ["" if v is None else v for v in padded]

        def _score_val(row_vals: List[Any]) -> float:
            try:
                return float(row_vals[score_col] or 0.0)
            except (ValueError, TypeError):
                return 0.0

        existing_contacted = [
            merged_map[k] for k in existing_order_keys
            if str(merged_map[k][ost_col] or "").strip().lower() in contacted_states
        ]
        existing_unsent = [
            merged_map[k] for k in existing_order_keys
            if str(merged_map[k][ost_col] or "").strip().lower() not in contacted_states
        ]
        new_incoming_rows = [merged_map[k] for k in new_incoming_keys]
        new_incoming_rows.sort(
            key=lambda row_vals: (-_score_val(row_vals), str(row_vals[comp_col] or "").lower())
        )

        merged_list = existing_contacted + existing_unsent + new_incoming_rows
        for rank_idx, row_vals in enumerate(merged_list, 1):
            row_vals[0] = rank_idx
        return merged_list

    @staticmethod
    def _write_formatted_leads_table_sheet(
        ws,
        headers: List[str],
        rows: List[List[Any]],
        table_name: str,
    ) -> None:
        """
        Writes a structured, styled Excel table (`tbl_qualified_leads` / `tbl_non_qualified_leads`)
        preserving exact header styling, zebra striping, column alignments, widths, borders,
        number formats ('0', '0.0', '@' on Evaluated_At), frozen header row, and TableStyleMedium2.
        """
        thin_side = Side(style="thin", color="CBD5E1")
        cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

        hdr_fill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
        hdr_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        hdr_align = Alignment(horizontal="center", vertical="center")

        even_fill = PatternFill(start_color="FFFFFF", end_color="FFFFFF", fill_type="solid")
        odd_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
        data_font = Font(name="Calibri", size=10, color="0F172A")

        center_headers = {
            "rank", "overallscore", "qualificationstatus", "conferenceid",
            "contacttype", "emailstatus", "industry", "headcounttier",
            "evaluatedat", "outreachstatus", "replystatus", "replysentiment",
        }
        col_widths_by_norm = {
            "rank": 10.0,
            "overallscore": 16.5,
            "qualificationstatus": 23.0,
            "companyname": 30.0,
            "companydomain": 24.0,
            "conferencename": 38.0,
            "conferenceid": 24.0,
            "contacttype": 16.0,
            "contactname": 24.0,
            "jobtitle": 30.0,
            "professionalemail": 34.0,
            "emailstatus": 16.0,
            "personallinkedinurl": 36.0,
            "primaryindustry": 28.0,
            "industry": 16.0,
            "headcounttier": 22.0,
            "evaluatedat": 22.0,
            "outreachstatus": 18.0,
            "replystatus": 17.0,
            "receivedreply": 38.0,
            "replysentiment": 18.0,
            "threadid": 32.0,
            "sendmessage": 48.0,
        }

        ws.row_dimensions[1].height = 30.0
        norm_headers = [
            str(h or "").strip().lower().replace(" ", "").replace("_", "")
            for h in headers
        ]

        for col_idx, (h, nh) in enumerate(zip(headers, norm_headers), 1):
            cell = ws.cell(row=1, column=col_idx, value=h)
            cell.font = hdr_font
            cell.fill = hdr_fill
            cell.alignment = hdr_align
            cell.border = cell_border
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = col_widths_by_norm.get(nh, 20.0)

        for row_idx, padded in enumerate(rows, 2):
            ws.row_dimensions[row_idx].height = 22.0
            row_fill = even_fill if row_idx % 2 == 0 else odd_fill
            for col_idx, (val, nh) in enumerate(zip(padded[:len(headers)], norm_headers), 1):
                clean_val = "" if val is None else val
                cell = ws.cell(row=row_idx, column=col_idx, value=clean_val)
                cell.fill = row_fill
                cell.font = data_font
                cell.border = cell_border
                cell.alignment = Alignment(
                    horizontal="center" if nh in center_headers else "left",
                    vertical="center",
                )
                if nh == "rank":
                    cell.number_format = "0"
                elif nh == "overallscore":
                    cell.number_format = "0.0"
                elif nh == "evaluatedat":
                    cell.number_format = "@"

        ws.freeze_panes = "A2"
        last_col = get_column_letter(max(1, len(headers)))
        last_row = max(2, len(rows) + 1)
        tbl = Table(displayName=table_name, ref=f"A1:{last_col}{last_row}")
        tbl.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        ws.add_table(tbl)

    def sync_qualified_leads_to_excel(self, qualified_rows: List[List[Any]], headers: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Synchronizes qualified leads (score > 50) with 6 outreach tracking columns to 'Qualified Leads' worksheet in Local Excel.
        Union-merges incoming rows with existing historical rows and preserves all outreach tracking states.
        """
        self._ensure_file_exists()
        wb = load_workbook(self.file_path)
        sheet_name = getattr(settings, "QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME", "Qualified Leads")
        table_name = getattr(settings, "QUALIFIED_LEADS_EXCEL_TABLE_NAME", "tbl_qualified_leads")

        if headers is None:
            headers = [
                "Rank", "Overall_Score", "Qualification_Status", "Company_Name",
                "Company_Domain", "Conference_Name", "Conference_ID", "Contact_Type",
                "Contact_Name", "Job_Title", "Professional_Email", "Email_Status",
                "Personal_LinkedIn_URL", "Primary_Industry", "Industry", "Headcount_Tier",
                "Evaluated_At", "Outreach Status", "Reply Status", "Received Reply",
                "Reply Sentiment", "Thread ID", "Send Message"
            ]

        existing_rows_aligned: List[List[Any]] = []
        old_idx = None
        if sheet_name in wb.sheetnames:
            old_idx = wb.sheetnames.index(sheet_name)
            ws_exist = wb[sheet_name]
            h_row = [str(cell.value or "").strip().lower().replace(" ", "").replace("_", "").replace("replay", "reply") for cell in ws_exist[1]]
            h_map = {name: idx for idx, name in enumerate(h_row)}
            cur_norm_headers = [h.lower().replace(" ", "").replace("_", "") for h in headers]

            for r in range(2, ws_exist.max_row + 1):
                raw_vals = [ws_exist.cell(row=r, column=c).value for c in range(1, ws_exist.max_column + 1)]
                if not any(raw_vals):
                    continue
                aligned = []
                for nh in cur_norm_headers:
                    src_idx = h_map.get(nh)
                    if src_idx is None and nh == "professionalemail":
                        src_idx = h_map.get("email")
                    elif src_idx is None and nh == "contactname":
                        src_idx = h_map.get("name")
                    elif src_idx is None and nh == "replysentiment":
                        src_idx = h_map.get("sentiment")
                    val = raw_vals[src_idx] if src_idx is not None and src_idx < len(raw_vals) else ""
                    aligned.append("" if val is None else val)
                existing_rows_aligned.append(aligned)
            del wb[sheet_name]

        merged_rows = self._union_merge_lead_rows(existing_rows_aligned, qualified_rows, headers, default_status="Pending")

        ws = wb.create_sheet(title=sheet_name, index=old_idx)
        self._write_formatted_leads_table_sheet(ws, headers, merged_rows, table_name=table_name)

        self._safe_save(wb)
        logger.info(f"✅ Local Excel: Successfully union-synced {len(merged_rows)} qualified leads ({len(qualified_rows)} incoming) to '{sheet_name}'.")
        return {"status": "success", "count": len(merged_rows)}

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
        Union-merges incoming rows with existing historical rows and preserves all outreach tracking states.
        """
        self._ensure_file_exists()
        wb = load_workbook(self.file_path)
        sheet_name = getattr(settings, "NON_QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME", "Non -Qualified Leads")
        table_name = getattr(settings, "NON_QUALIFIED_LEADS_EXCEL_TABLE_NAME", "tbl_non_qualified_leads")

        if headers is None:
            headers = [
                "Rank", "Overall_Score", "Qualification_Status", "Company_Name",
                "Company_Domain", "Conference_Name", "Conference_ID", "Contact_Type",
                "Contact_Name", "Job_Title", "Professional_Email", "Email_Status",
                "Personal_LinkedIn_URL", "Primary_Industry", "Industry", "Headcount_Tier",
                "Evaluated_At", "Outreach Status", "Reply Status", "Received Reply",
                "Reply Sentiment", "Thread ID", "Send Message"
            ]

        existing_rows_aligned: List[List[Any]] = []
        target_ws_name = None
        old_idx = None
        for s in [sheet_name, "Non -Qualified Leads", "Non-Qualified Leads", "Disqualified Leads"]:
            if s in wb.sheetnames:
                target_ws_name = s
                old_idx = wb.sheetnames.index(s)
                break

        if target_ws_name and target_ws_name in wb.sheetnames:
            ws_exist = wb[target_ws_name]
            h_row = [str(cell.value or "").strip().lower().replace(" ", "").replace("_", "").replace("replay", "reply") for cell in ws_exist[1]]
            h_map = {name: idx for idx, name in enumerate(h_row)}
            cur_norm_headers = [h.lower().replace(" ", "").replace("_", "") for h in headers]

            for r in range(2, ws_exist.max_row + 1):
                raw_vals = [ws_exist.cell(row=r, column=c).value for c in range(1, ws_exist.max_column + 1)]
                if not any(raw_vals):
                    continue
                aligned = []
                for nh in cur_norm_headers:
                    src_idx = h_map.get(nh)
                    if src_idx is None and nh == "professionalemail":
                        src_idx = h_map.get("email")
                    elif src_idx is None and nh == "contactname":
                        src_idx = h_map.get("name")
                    elif src_idx is None and nh == "replysentiment":
                        src_idx = h_map.get("sentiment")
                    val = raw_vals[src_idx] if src_idx is not None and src_idx < len(raw_vals) else ""
                    aligned.append("" if val is None else val)
                existing_rows_aligned.append(aligned)
            del wb[target_ws_name]

        merged_rows = self._union_merge_lead_rows(existing_rows_aligned, non_qualified_rows, headers, default_status="Disqualified")

        ws = wb.create_sheet(title=sheet_name, index=old_idx)
        self._write_formatted_leads_table_sheet(ws, headers, merged_rows, table_name=table_name)

        self._safe_save(wb)
        logger.info(f"✅ Local Excel: Successfully union-synced {len(merged_rows)} non-qualified leads ({len(non_qualified_rows)} incoming) to '{sheet_name}'.")
        return {"status": "success", "count": len(merged_rows)}

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
