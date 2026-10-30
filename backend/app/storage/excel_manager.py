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
