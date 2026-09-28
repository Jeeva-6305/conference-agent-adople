import logging
import os
from datetime import date
from typing import List
import pandas as pd
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from ..config import settings
from ..models import Conference

logger = logging.getLogger(__name__)

EXCEL_COLUMNS = [
    "Conference ID",
    "Conference Title",
    "Industry / Category",
    "Conference Start Date",
    "Conference End Date",
    "Speakers",
    "Speaker Titles / Companies",
    "Venue",
    "City",
    "Country",
    "Organizer",
    "Official Conference URL",
    "Registration URL",
    "Source URL",
    "Publication Date"
]

class ExcelManager:
    def __init__(self, file_path: str = settings.EXCEL_OUTPUT_PATH):
        self.file_path = file_path
        self._ensure_file_exists()

    def _ensure_file_exists(self):
        if not os.path.exists(self.file_path):
            wb = Workbook()
            ws = wb.active
            ws.title = "USA Conferences"
            
            # Header styling
            header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
            header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)

            ws.append(EXCEL_COLUMNS)
            ws.row_dimensions[1].height = 28

            for col_idx, col_name in enumerate(EXCEL_COLUMNS, 1):
                cell = ws.cell(row=1, column=col_idx)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = align_center

            self._auto_fit_columns(ws)
            wb.save(self.file_path)
            logger.info(f"Initialized blank Excel sheet with schema at {self.file_path}")

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

    def publish_conferences(self, conferences: List[Conference]) -> int:
        """
        Appends newly due conferences (published 2 days before event) into the Excel file.
        Returns the number of conferences added.
        """
        if not conferences:
            return 0

        self._ensure_file_exists()
        wb = load_workbook(self.file_path)
        ws = wb.active

        # Collect existing IDs to avoid duplicates
        existing_ids = set()
        for row in ws.iter_rows(min_row=2, max_col=1, values_only=True):
            if row[0]:
                existing_ids.add(str(row[0]).strip())

        added_count = 0
        today_str = date.today().isoformat()

        for conf in conferences:
            if conf.conference_id in existing_ids:
                continue

            row_data = [
                conf.conference_id,
                conf.conference_title,
                conf.industry_category,
                conf.start_date.isoformat() if conf.start_date else "",
                conf.end_date.isoformat() if conf.end_date else "",
                conf.speakers,
                conf.speaker_titles_companies,
                conf.venue,
                conf.city,
                conf.country,
                conf.organizer,
                conf.official_conference_url,
                conf.registration_url,
                conf.source_url,
                today_str  # Publication Date (2 days before conference)
            ]
            ws.append(row_data)
            added_count += 1
            existing_ids.add(conf.conference_id)

        if added_count > 0:
            self._auto_fit_columns(ws)
            wb.save(self.file_path)
            logger.info(f"Published {added_count} conferences to Excel at {self.file_path}")

        return added_count

    def read_excel_as_dataframe(self) -> pd.DataFrame:
        self._ensure_file_exists()
        return pd.read_excel(self.file_path)
