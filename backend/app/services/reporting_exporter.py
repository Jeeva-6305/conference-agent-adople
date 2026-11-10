"""
Document Exporters (Excel & PDF) for the Automated Weekly Outreach & Conference Reporting System.

Generates publication-ready, audit-accurate multi-sheet Excel workbooks (.xlsx)
and Landscape Executive PDF reports (.pdf) directly from verified payload dictionaries.
All writes use atomic temporary files before replacement.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List
from xml.sax.saxutils import escape as xml_escape

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger("reporting_exporter")

# Strip ASCII control characters invalid in XML/Excel except \t, \n, \r
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _safe_str(val: Any, max_len: int = 0) -> str:
    if val is None:
        return ""
    s = _CTRL_RE.sub("", str(val)).strip()
    if max_len > 0 and len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _excel_str(val: Any) -> str:
    """Sanitizes string for openpyxl (max 32,767 chars)."""
    return _safe_str(val, max_len=32000)


def _pdf_p(val: Any, style: ParagraphStyle, max_len: int = 0) -> Paragraph:
    """Safely XML-escapes text and preserves line breaks for ReportLab Paragraph."""
    txt = xml_escape(_safe_str(val, max_len=max_len))
    txt = txt.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")
    if not txt:
        txt = "—"
    return Paragraph(txt, style)


# ==============================================================================
# EXCEL (.xlsx) EXPORTER
# ==============================================================================
def generate_excel_report(
    payload: Dict[str, Any],
    output_path: str,
    title_scope: str = "Weekly Report",
) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()

    # Palette & Styles
    navy_fill = PatternFill("solid", fgColor="1E3A5F")
    subhdr_fill = PatternFill("solid", fgColor="2B547E")
    section_fill = PatternFill("solid", fgColor="EBF1F8")
    zebra_fill = PatternFill("solid", fgColor="F8FAFC")
    green_fill = PatternFill("solid", fgColor="DCFCE7")
    red_fill = PatternFill("solid", fgColor="FEE2E2")
    blue_fill = PatternFill("solid", fgColor="DBEAFE")
    amber_fill = PatternFill("solid", fgColor="FEF3C7")
    gray_fill = PatternFill("solid", fgColor="F1F5F9")

    title_font = Font(name="Calibri", size=14, bold=True, color="FFFFFF")
    hdr_font = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
    sec_font = Font(name="Calibri", size=11, bold=True, color="1E3A5F")
    bold_font = Font(name="Calibri", size=10, bold=True, color="0F172A")
    body_font = Font(name="Calibri", size=10, color="1E293B")
    green_font = Font(name="Calibri", size=10, bold=True, color="166534")
    red_font = Font(name="Calibri", size=10, bold=True, color="991B1B")
    blue_font = Font(name="Calibri", size=10, bold=True, color="1E40AF")

    thin_side = Side(style="thin", color="CBD5E1")
    grid_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

    align_left = Alignment(horizontal="left", vertical="top", wrap_text=True)
    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_right = Alignment(horizontal="right", vertical="center", wrap_text=True)

    def _style_banner(ws, text: str, col_span: int):
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=col_span)
        c = ws.cell(row=1, column=1, value=_excel_str(text))
        c.fill = navy_fill
        c.font = title_font
        c.alignment = Alignment(horizontal="left", vertical="center")
        ws.row_dimensions[1].height = 28

    def _style_section_title(ws, row_idx: int, text: str, col_span: int):
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=col_span)
        c = ws.cell(row=row_idx, column=1, value=_excel_str(text))
        c.fill = section_fill
        c.font = sec_font
        c.alignment = Alignment(horizontal="left", vertical="center")
        for col in range(1, col_span + 1):
            ws.cell(row=row_idx, column=col).border = grid_border
        ws.row_dimensions[row_idx].height = 22

    def _write_table_headers(ws, row_idx: int, headers: List[str]):
        for c_idx, h in enumerate(headers, 1):
            cell = ws.cell(row=row_idx, column=c_idx, value=_excel_str(h))
            cell.fill = subhdr_fill
            cell.font = hdr_font
            cell.alignment = align_center
            cell.border = grid_border
        ws.row_dimensions[row_idx].height = 26

    def _set_col_widths(ws, widths: Dict[int, float]):
        for idx, w in widths.items():
            ws.column_dimensions[get_column_letter(idx)].width = w

    exec_sum = payload.get("executive_summary", {})
    out_sum = exec_sum.get("outreach", {})
    qual_sum = out_sum.get("qualified", {})
    nq_sum = out_sum.get("non_qualified", {})
    fup_sum = out_sum.get("general_follow_up", {})
    comp_tot = exec_sum.get("company_rankings", {})
    scrap_tot = exec_sum.get("conference_scraping", {})

    # --------------------------------------------------------------------------
    # SHEET 1: Executive Summary
    # --------------------------------------------------------------------------
    ws1 = wb.active
    ws1.title = "Executive Summary"
    ws1.views.sheetView[0].showGridLines = True

    _style_banner(ws1, f"Adople Conference Agent — {title_scope}", 9)
    meta_rows = [
        ("Report Scope", title_scope, "Generated At", payload.get("generated_at", "")),
        ("Mailbox Monitored", payload.get("mailbox", ""), "Graph Last Synced", payload.get("graph_synced_at", "")),
        ("Timezone", payload.get("timezone", "Asia/Kolkata"), "Weeks Covered", ", ".join(payload.get("weeks", []))),
        ("Excluded Manual QA Tests", exec_sum.get("excluded_test_sends_count", 0), "Source Integrity", "100% Real PostgreSQL, Excel & Outlook Graph Data"),
    ]
    r_ptr = 2
    for mr in meta_rows:
        ws1.cell(row=r_ptr, column=1, value=mr[0]).font = bold_font
        ws1.cell(row=r_ptr, column=2, value=_excel_str(mr[1])).font = body_font
        ws1.cell(row=r_ptr, column=4, value=mr[2]).font = bold_font
        ws1.cell(row=r_ptr, column=5, value=_excel_str(mr[3])).font = body_font
        for col in range(1, 10):
            ws1.cell(row=r_ptr, column=col).border = grid_border
            ws1.cell(row=r_ptr, column=col).alignment = align_left
        ws1.row_dimensions[r_ptr].height = 20
        r_ptr += 1

    r_ptr += 1
    _style_section_title(ws1, r_ptr, "1. Overall Email Outreach & Qualification Breakdown", 9)
    r_ptr += 1
    _write_table_headers(
        ws1,
        r_ptr,
        [
            "Segment",
            "Emails Sent",
            "Delivered",
            "Bounced",
            "Replies Received",
            "Delivery Rate (%)",
            "Bounce Rate (%)",
            "Reply Rate % (of Sent)",
            "Reply Rate % (of Delivered)",
        ],
    )
    r_ptr += 1

    seg_rows = [
        ("All Prospect Outreach", out_sum),
        ("Qualified Leads (ICP >= 50)", qual_sum),
        ("Non-Qualified Leads (ICP < 50)", nq_sum),
        ("General Follow-Up Outreach", fup_sum),
    ]
    for s_idx, (seg_label, s_data) in enumerate(seg_rows):
        vals = [
            seg_label,
            s_data.get("sent", 0),
            s_data.get("delivered", 0),
            s_data.get("bounced", 0),
            s_data.get("replied", 0),
            s_data.get("delivery_rate_pct", 0.0),
            s_data.get("bounce_rate_pct", 0.0),
            s_data.get("reply_rate_pct", 0.0),
            s_data.get("reply_rate_of_delivered_pct", 0.0),
        ]
        for c_i, val in enumerate(vals, 1):
            cell = ws1.cell(row=r_ptr, column=c_i, value=val)
            cell.border = grid_border
            cell.font = bold_font if s_idx == 0 or c_i == 1 else body_font
            cell.fill = gray_fill if s_idx == 0 else (zebra_fill if s_idx % 2 == 1 else PatternFill(fill_type=None))
            cell.alignment = align_left if c_i == 1 else align_right
            if c_i >= 6:
                cell.number_format = "0.00"
        ws1.row_dimensions[r_ptr].height = 20
        r_ptr += 1

    # Follow-Up telemetry note
    ws1.cell(row=r_ptr, column=1, value="Follow-Up Readiness Note").font = bold_font
    ws1.merge_cells(start_row=r_ptr, start_column=2, end_row=r_ptr, end_column=9)
    ws1.cell(
        row=r_ptr,
        column=2,
        value=(
            f"FOLLOW_UP_ENABLED={fup_sum.get('follow_up_enabled', False)} | "
            f"Follow-Ups Sent={fup_sum.get('sent', 0)} | "
            f"Delivered Prospects Awaiting Reply (Follow-Up Eligible)={fup_sum.get('eligible_delivered_no_reply', 0)}"
        ),
    ).font = body_font
    for col in range(1, 10):
        ws1.cell(row=r_ptr, column=col).border = grid_border
    ws1.row_dimensions[r_ptr].height = 20
    r_ptr += 2

    _style_section_title(ws1, r_ptr, "2. Template Performance Summary", 9)
    r_ptr += 1
    _write_table_headers(
        ws1,
        r_ptr,
        [
            "Template Used",
            "Sent",
            "Delivered",
            "Bounced",
            "Replied",
            "Delivery Rate (%)",
            "Bounce Rate (%)",
            "Reply Rate (%)",
            "Sentiment (Pos / Neu / Neg)",
        ],
    )
    r_ptr += 1
    for t_idx, tm in enumerate(payload.get("template_performance", [])):
        sent_cnt = tm.get("sent", 0)
        sent_summary = f"{tm.get('positive_replies', 0)} / {tm.get('neutral_replies', 0)} / {tm.get('negative_replies', 0)}"
        vals = [
            tm.get("template_name", ""),
            sent_cnt,
            tm.get("delivered", 0),
            tm.get("bounced", 0),
            tm.get("replied", 0),
            tm.get("delivery_rate_pct", 0.0),
            tm.get("bounce_rate_pct", 0.0),
            tm.get("reply_rate_pct", 0.0),
            sent_summary,
        ]
        for c_i, val in enumerate(vals, 1):
            cell = ws1.cell(row=r_ptr, column=c_i, value=val)
            cell.border = grid_border
            cell.font = bold_font if c_i == 1 else body_font
            cell.fill = zebra_fill if t_idx % 2 == 1 else PatternFill(fill_type=None)
            cell.alignment = align_left if c_i in (1, 9) else align_right
            if 6 <= c_i <= 8:
                cell.number_format = "0.00"
        ws1.row_dimensions[r_ptr].height = 20
        r_ptr += 1

    r_ptr += 1
    _style_section_title(ws1, r_ptr, "3. Company Rankings & Conference Scraping Totals", 9)
    r_ptr += 1
    overview_pairs = [
        ("Companies Ranked (Unique)", comp_tot.get("unique_companies", 0), "Total Ranked Entries", comp_tot.get("total_ranked_entries", 0)),
        ("Qualified Companies", comp_tot.get("qualified_entries", 0), "Non-Qualified Companies", comp_tot.get("non_qualified_entries", 0)),
        ("Total Conferences Collected", scrap_tot.get("total_conferences", 0), "Total Genuine Contacts", scrap_tot.get("total_contacts", 0)),
        ("Speakers Collected", scrap_tot.get("total_speakers", 0), "Verified Contact Emails", scrap_tot.get("total_verified_emails", 0)),
        ("Attendees Collected", scrap_tot.get("total_attendees", 0), "Exhibitors Collected", scrap_tot.get("total_exhibitors", 0)),
    ]
    for idx_p, op in enumerate(overview_pairs):
        ws1.cell(row=r_ptr, column=1, value=op[0]).font = bold_font
        ws1.cell(row=r_ptr, column=2, value=op[1]).font = body_font
        ws1.cell(row=r_ptr, column=4, value=op[2]).font = bold_font
        ws1.cell(row=r_ptr, column=5, value=op[3]).font = body_font
        for col in range(1, 10):
            ws1.cell(row=r_ptr, column=col).border = grid_border
            ws1.cell(row=r_ptr, column=col).fill = zebra_fill if idx_p % 2 == 1 else PatternFill(fill_type=None)
        ws1.row_dimensions[r_ptr].height = 20
        r_ptr += 1

    _set_col_widths(ws1, {1: 30, 2: 18, 3: 14, 4: 26, 5: 24, 6: 18, 7: 16, 8: 20, 9: 26})

    # --------------------------------------------------------------------------
    # SHEET 2: Weekly Performance
    # --------------------------------------------------------------------------
    ws2 = wb.create_sheet("Weekly Performance")
    _style_banner(ws2, f"Weekly Performance Report — {title_scope}", 28)
    wk_headers = [
        "Week ID", "Week Start", "Week End", "Week Status",
        "Sent", "Delivered", "Bounced", "Replied", "Delivery %", "Bounce %", "Reply %",
        "Qual Sent", "Qual Deliv", "Qual Bounced", "Qual Replied", "Qual Deliv %", "Qual Reply %",
        "Non-Qual Sent", "Non-Qual Deliv", "Non-Qual Bounced", "Non-Qual Replied", "Non-Qual Deliv %", "Non-Qual Reply %",
        "Follow-Up Sent", "Follow-Up Replied", "Follow-Up Eligible",
        "Companies Ranked", "Conferences Scraped",
    ]
    _write_table_headers(ws2, 2, wk_headers)
    ws2.freeze_panes = "B3"

    r_ptr = 3
    for idx, wp in enumerate(payload.get("weekly_performance", [])):
        wo = wp.get("outreach", {})
        wq = wo.get("qualified", {})
        wn = wo.get("non_qualified", {})
        wf = wo.get("general_follow_up", {})
        wcr = wp.get("company_ranking_summary", {})
        wcs = wp.get("conference_scraping_summary", {})
        vals = [
            wp.get("week_id", ""),
            wp.get("week_start", ""),
            wp.get("week_end", ""),
            "Completed" if wp.get("is_completed_week") else "Active / Upcoming",
            wo.get("sent", 0),
            wo.get("delivered", 0),
            wo.get("bounced", 0),
            wo.get("replied", 0),
            wo.get("delivery_rate_pct", 0.0),
            wo.get("bounce_rate_pct", 0.0),
            wo.get("reply_rate_pct", 0.0),
            wq.get("sent", 0),
            wq.get("delivered", 0),
            wq.get("bounced", 0),
            wq.get("replied", 0),
            wq.get("delivery_rate_pct", 0.0),
            wq.get("reply_rate_pct", 0.0),
            wn.get("sent", 0),
            wn.get("delivered", 0),
            wn.get("bounced", 0),
            wn.get("replied", 0),
            wn.get("delivery_rate_pct", 0.0),
            wn.get("reply_rate_pct", 0.0),
            wf.get("sent", 0),
            wf.get("replied", 0),
            wf.get("eligible_delivered_no_reply", 0),
            wcr.get("total_companies", 0),
            wcs.get("total_conferences", 0),
        ]
        for c_i, val in enumerate(vals, 1):
            cell = ws2.cell(row=r_ptr, column=c_i, value=val)
            cell.border = grid_border
            cell.font = bold_font if c_i == 1 else body_font
            cell.fill = zebra_fill if idx % 2 == 1 else PatternFill(fill_type=None)
            cell.alignment = align_left if c_i <= 4 else align_right
            if c_i in (9, 10, 11, 16, 17, 22, 23):
                cell.number_format = "0.00"
        ws2.row_dimensions[r_ptr].height = 22
        r_ptr += 1

    _set_col_widths(ws2, {1: 26, 2: 12, 3: 12, 4: 16, **{i: 13 for i in range(5, 29)}})

    # --------------------------------------------------------------------------
    # SHEET 3: Email Outreach
    # --------------------------------------------------------------------------
    ws3 = wb.create_sheet("Email Outreach")
    _style_banner(ws3, f"Detailed Email Outreach Report — {title_scope}", 21)
    out_headers = [
        "Week ID", "Sent At", "Recipient Name", "Recipient Email", "Job Title", "Company",
        "Contact Role", "Conference Name", "Target Conference Week", "Lead Classification",
        "ICP Score", "Template Used", "Delivery Status", "Bounce Reason", "Reply Status",
        "Reply Sentiment", "Reply Intent", "Reply Received At", "Reply Details",
        "Email Subject", "Email Message Sent",
    ]
    _write_table_headers(ws3, 2, out_headers)
    ws3.freeze_panes = "E3"

    r_ptr = 3
    for idx, rec in enumerate(payload.get("email_outreach", {}).get("records", [])):
        vals = [
            rec.get("week_id", ""),
            rec.get("sent_at", ""),
            _excel_str(rec.get("recipient_name", "")),
            _excel_str(rec.get("recipient_email", "")),
            _excel_str(rec.get("job_title", "")),
            _excel_str(rec.get("company_name", "")),
            _excel_str(rec.get("contact_role", "")),
            _excel_str(rec.get("conference_name", "")),
            _excel_str(rec.get("target_conference_week", "")),
            _excel_str(rec.get("lead_classification", "")),
            rec.get("icp_score") if rec.get("icp_score") is not None else "",
            _excel_str(rec.get("template_used", "")),
            _excel_str(rec.get("delivery_status", "")),
            _excel_str(rec.get("bounce_reason", "")),
            _excel_str(rec.get("reply_status", "")),
            _excel_str(rec.get("reply_sentiment", "")),
            _excel_str(rec.get("reply_intent", "")),
            _excel_str(rec.get("reply_received_at", "")),
            _excel_str(rec.get("reply_details", "")),
            _excel_str(rec.get("subject", "")),
            _excel_str(rec.get("message_sent", "")),
        ]
        for c_i, val in enumerate(vals, 1):
            cell = ws3.cell(row=r_ptr, column=c_i, value=val)
            cell.border = grid_border
            cell.font = body_font
            cell.alignment = align_right if c_i == 11 else align_left
            if c_i == 13:
                if val == "Bounced":
                    cell.fill = red_fill
                    cell.font = red_font
                elif val == "Delivered":
                    cell.fill = green_fill
                    cell.font = green_font
            elif c_i == 15:
                if val == "Replied":
                    cell.fill = blue_fill
                    cell.font = blue_font
                elif val == "Bounced":
                    cell.fill = red_fill
                    cell.font = red_font
            elif c_i == 16 and val:
                if val.lower() == "positive":
                    cell.fill = green_fill
                elif val.lower() == "negative":
                    cell.fill = red_fill
                else:
                    cell.fill = amber_fill
            elif idx % 2 == 1:
                cell.fill = zebra_fill
        ws3.row_dimensions[r_ptr].height = 42
        r_ptr += 1

    _set_col_widths(
        ws3,
        {
            1: 24, 2: 20, 3: 22, 4: 28, 5: 24, 6: 22,
            7: 13, 8: 28, 9: 24, 10: 16, 11: 11, 12: 14,
            13: 14, 14: 38, 15: 13, 16: 14, 17: 16, 18: 20,
            19: 44, 20: 36, 21: 60,
        },
    )

    # --------------------------------------------------------------------------
    # SHEET 4: Template Performance
    # --------------------------------------------------------------------------
    ws4 = wb.create_sheet("Template Performance")
    _style_banner(ws4, f"Email Template Performance — {title_scope}", 12)
    _style_section_title(ws4, 2, "Overall Template Performance", 12)
    tmpl_headers = [
        "Week Scope", "Template Used", "Emails Sent", "Unique Recipients", "Delivered", "Bounced",
        "Replies Received", "Delivery Rate (%)", "Bounce Rate (%)", "Reply Rate (%)",
        "Positive Replies", "Neutral / Negative Replies",
    ]
    _write_table_headers(ws4, 3, tmpl_headers)
    r_ptr = 4
    for idx, tm in enumerate(payload.get("template_performance", [])):
        vals = [
            title_scope,
            tm.get("template_name", ""),
            tm.get("sent", 0),
            tm.get("unique_recipients", 0),
            tm.get("delivered", 0),
            tm.get("bounced", 0),
            tm.get("replied", 0),
            tm.get("delivery_rate_pct", 0.0),
            tm.get("bounce_rate_pct", 0.0),
            tm.get("reply_rate_pct", 0.0),
            tm.get("positive_replies", 0),
            f"{tm.get('neutral_replies', 0)} / {tm.get('negative_replies', 0)}",
        ]
        for c_i, val in enumerate(vals, 1):
            cell = ws4.cell(row=r_ptr, column=c_i, value=val)
            cell.border = grid_border
            cell.font = bold_font if c_i == 2 else body_font
            cell.fill = zebra_fill if idx % 2 == 1 else PatternFill(fill_type=None)
            cell.alignment = align_left if c_i in (1, 2, 12) else align_right
            if 8 <= c_i <= 10:
                cell.number_format = "0.00"
        ws4.row_dimensions[r_ptr].height = 20
        r_ptr += 1

    r_ptr += 1
    _style_section_title(ws4, r_ptr, "Per-Week Template Breakdown", 12)
    r_ptr += 1
    _write_table_headers(ws4, r_ptr, tmpl_headers)
    r_ptr += 1
    for wp in payload.get("weekly_performance", []):
        wk_id = wp.get("week_id", "")
        for tm in wp.get("template_performance", []):
            if tm.get("sent", 0) == 0 and len(payload.get("weekly_performance", [])) > 1:
                continue
            vals = [
                wk_id,
                tm.get("template_name", ""),
                tm.get("sent", 0),
                tm.get("unique_recipients", 0),
                tm.get("delivered", 0),
                tm.get("bounced", 0),
                tm.get("replied", 0),
                tm.get("delivery_rate_pct", 0.0),
                tm.get("bounce_rate_pct", 0.0),
                tm.get("reply_rate_pct", 0.0),
                tm.get("positive_replies", 0),
                f"{tm.get('neutral_replies', 0)} / {tm.get('negative_replies', 0)}",
            ]
            for c_i, val in enumerate(vals, 1):
                cell = ws4.cell(row=r_ptr, column=c_i, value=val)
                cell.border = grid_border
                cell.font = body_font
                cell.alignment = align_left if c_i in (1, 2, 12) else align_right
                if 8 <= c_i <= 10:
                    cell.number_format = "0.00"
            ws4.row_dimensions[r_ptr].height = 20
            r_ptr += 1

    _set_col_widths(ws4, {1: 28, 2: 18, 3: 13, 4: 16, 5: 12, 6: 12, 7: 16, 8: 16, 9: 15, 10: 15, 11: 15, 12: 22})

    # --------------------------------------------------------------------------
    # SHEET 5: Company Rankings
    # --------------------------------------------------------------------------
    ws5 = wb.create_sheet("Company Rankings")
    _style_banner(ws5, f"Company Ranking Report — {title_scope}", 15)
    _style_section_title(ws5, 2, "Weekly Ranking Benchmarks & Week-over-Week Comparison", 15)
    bench_headers = [
        "Week ID", "Week Period", "Total Companies", "Qualified", "Non-Qualified",
        "Qualification Rate (%)", "Avg ICP Score", "Avg Score Delta", "Top 10 Avg Score",
        "Top Company", "Top Score", "Returning Cos", "New Cos", "HIGH_MATCH", "MODERATE",
    ]
    _write_table_headers(ws5, 3, bench_headers)
    r_ptr = 4
    by_wk_comp = payload.get("company_rankings", {}).get("by_week", {})
    for idx, wk_id in enumerate(sorted(by_wk_comp.keys())):
        wb_info = by_wk_comp[wk_id]
        vals = [
            wk_id,
            wb_info.get("week_period", ""),
            wb_info.get("total_companies", 0),
            wb_info.get("qualified_companies", 0),
            wb_info.get("non_qualified_companies", 0),
            wb_info.get("qualification_rate_pct", 0.0),
            wb_info.get("avg_icp_score", 0.0),
            wb_info.get("avg_score_change_vs_prev") if wb_info.get("avg_score_change_vs_prev") is not None else "—",
            wb_info.get("top_10_avg_score", 0.0),
            _excel_str(wb_info.get("top_company", "")),
            wb_info.get("top_score", 0.0),
            wb_info.get("returning_companies_vs_prev", 0),
            wb_info.get("new_companies_count", 0),
            wb_info.get("high_match_count", 0),
            wb_info.get("moderate_count", 0),
        ]
        for c_i, val in enumerate(vals, 1):
            cell = ws5.cell(row=r_ptr, column=c_i, value=val)
            cell.border = grid_border
            cell.font = bold_font if c_i in (1, 10) else body_font
            cell.fill = zebra_fill if idx % 2 == 1 else PatternFill(fill_type=None)
            cell.alignment = align_left if c_i in (1, 2, 10) else align_right
        ws5.row_dimensions[r_ptr].height = 21
        r_ptr += 1

    r_ptr += 1
    _style_section_title(ws5, r_ptr, "Weekly Company Ranking Leaderboard", 15)
    r_ptr += 1
    comp_headers = [
        "Week ID", "Week Period", "Weekly Rank", "Previous Rank", "Rank Change",
        "Company Name", "Domain", "Primary Industry", "Headcount Tier",
        "ICP Score", "Score Change", "Qualification Status", "Classification",
        "Associated Conference", "Official Website",
    ]
    _write_table_headers(ws5, r_ptr, comp_headers)
    r_ptr += 1

    for idx, comp in enumerate(payload.get("company_rankings", {}).get("records", [])):
        vals = [
            comp.get("week_id", ""),
            comp.get("week_period", ""),
            comp.get("rank", 0),
            comp.get("previous_rank") if comp.get("previous_rank") is not None else "—",
            comp.get("rank_change_display", "New"),
            _excel_str(comp.get("company_name", "")),
            _excel_str(comp.get("company_domain", "")),
            _excel_str(comp.get("primary_industry", "")),
            _excel_str(comp.get("headcount_tier", "")),
            comp.get("icp_score", 0.0),
            comp.get("score_change") if comp.get("score_change") is not None else "—",
            comp.get("qualification_status", ""),
            comp.get("classification", ""),
            _excel_str(comp.get("associated_conference", "")),
            _excel_str(comp.get("official_website", "")),
        ]
        for c_i, val in enumerate(vals, 1):
            cell = ws5.cell(row=r_ptr, column=c_i, value=val)
            cell.border = grid_border
            cell.font = body_font
            cell.alignment = align_right if c_i in (3, 4, 10, 11) else align_left
            if c_i == 13:
                cell.fill = green_fill if val == "Qualified" else amber_fill
                cell.font = green_font if val == "Qualified" else red_font
            elif idx % 2 == 1:
                cell.fill = zebra_fill
        ws5.row_dimensions[r_ptr].height = 20
        r_ptr += 1

    _set_col_widths(
        ws5,
        {1: 24, 2: 24, 3: 13, 4: 13, 5: 14, 6: 28, 7: 22, 8: 24, 9: 16, 10: 12, 11: 12, 12: 18, 13: 15, 14: 34, 15: 32},
    )

    # --------------------------------------------------------------------------
    # SHEET 6: Conference Scraping
    # --------------------------------------------------------------------------
    ws6 = wb.create_sheet("Conference Scraping")
    _style_banner(ws6, f"Weekly Conference Scraping Report — {title_scope}", 16)
    _style_section_title(ws6, 2, "Weekly Data Collection Summary", 16)
    scrap_sum_headers = [
        "Week ID", "Week Start", "Week End", "Total Conferences", "Confs w/ Speakers",
        "Confs w/ Attendees", "Confs w/ Exhibitors", "Total Speakers", "Total Attendees",
        "Total Exhibitors", "Total Contacts", "Verified Speaker Emails",
        "Verified Attendee Emails", "Verified Exhibitor Emails", "Top Industries", "Notes",
    ]
    _write_table_headers(ws6, 3, scrap_sum_headers)
    r_ptr = 4
    by_wk_scrap = payload.get("conference_scraping", {}).get("by_week", {})
    for idx, wk_id in enumerate(sorted(by_wk_scrap.keys())):
        ws_info = by_wk_scrap[wk_id]
        inds = ", ".join(f"{x['industry']} ({x['count']})" for x in ws_info.get("top_industries", [])[:5])
        vals = [
            wk_id,
            ws_info.get("week_start", ""),
            ws_info.get("week_end", ""),
            ws_info.get("total_conferences", 0),
            ws_info.get("conferences_with_speakers", 0),
            ws_info.get("conferences_with_attendees", 0),
            ws_info.get("conferences_with_exhibitors", 0),
            ws_info.get("total_speakers", 0),
            ws_info.get("total_attendees", 0),
            ws_info.get("total_exhibitors", 0),
            ws_info.get("total_contacts", 0),
            ws_info.get("verified_emails_speakers", 0),
            ws_info.get("verified_emails_attendees", 0),
            ws_info.get("verified_emails_exhibitors", 0),
            _excel_str(inds),
            "Deduplicated across PG + Excel",
        ]
        for c_i, val in enumerate(vals, 1):
            cell = ws6.cell(row=r_ptr, column=c_i, value=val)
            cell.border = grid_border
            cell.font = bold_font if c_i == 1 else body_font
            cell.fill = zebra_fill if idx % 2 == 1 else PatternFill(fill_type=None)
            cell.alignment = align_left if c_i in (1, 2, 3, 15, 16) else align_right
        ws6.row_dimensions[r_ptr].height = 24
        r_ptr += 1

    r_ptr += 1
    _style_section_title(ws6, r_ptr, "Collected Conferences & Contact Associations", 16)
    r_ptr += 1
    conf_headers = [
        "Week ID", "Conference ID", "Conference Name", "Industry", "Start Date", "End Date",
        "Location", "Official Website", "Link Status", "Speakers", "Attendees", "Exhibitors",
        "Verified Emails", "Associated Speakers Preview", "Associated Attendees / Exhibitors Preview", "Source Name",
    ]
    _write_table_headers(ws6, r_ptr, conf_headers)
    r_ptr += 1

    for idx, c in enumerate(payload.get("conference_scraping", {}).get("conferences", [])):
        sp_prev = "; ".join(f"{s['name']} ({s['company']})" if s.get("company") else s["name"] for s in c.get("speakers", [])[:8])
        ae_parts = []
        if c.get("attendees"):
            ae_parts.append("Att: " + "; ".join(a["name"] for a in c["attendees"][:5]))
        if c.get("exhibitors"):
            ae_parts.append("Exh: " + "; ".join(e["company_name"] for e in c["exhibitors"][:6]))
        ae_prev = " | ".join(ae_parts)

        vals = [
            c.get("week_id", ""),
            c.get("conference_id", ""),
            _excel_str(c.get("conference_name", "")),
            _excel_str(c.get("industry", "")),
            c.get("start_date", ""),
            c.get("end_date", ""),
            _excel_str(c.get("location", "")),
            _excel_str(c.get("official_website", "")),
            _excel_str(c.get("link_status", "")),
            c.get("speakers_count", 0),
            c.get("attendees_count", 0),
            c.get("exhibitors_count", 0),
            c.get("verified_emails_count", 0),
            _excel_str(sp_prev),
            _excel_str(ae_prev),
            _excel_str(c.get("source_name", "")),
        ]
        for c_i, val in enumerate(vals, 1):
            cell = ws6.cell(row=r_ptr, column=c_i, value=val)
            cell.border = grid_border
            cell.font = body_font
            cell.fill = zebra_fill if idx % 2 == 1 else PatternFill(fill_type=None)
            cell.alignment = align_right if 10 <= c_i <= 13 else align_left
        ws6.row_dimensions[r_ptr].height = 34
        r_ptr += 1

    _set_col_widths(
        ws6,
        {1: 24, 2: 24, 3: 34, 4: 24, 5: 12, 6: 12, 7: 22, 8: 36, 9: 13, 10: 10, 11: 11, 12: 11, 13: 14, 14: 44, 15: 44, 16: 22},
    )

    # --------------------------------------------------------------------------
    # SHEET 7: Scraped Contacts (Full Conference Associations)
    # --------------------------------------------------------------------------
    ws7 = wb.create_sheet("Scraped Contacts")
    _style_banner(ws7, f"All Collected Speakers, Attendees & Exhibitors — {title_scope}", 9)
    ct_headers = [
        "Week ID", "Conference ID", "Conference Name", "Contact Type",
        "Full Name / Exhibitor", "Job Title", "Company", "Verified Email", "LinkedIn / Website / Booth",
    ]
    _write_table_headers(ws7, 2, ct_headers)
    ws7.freeze_panes = "A3"
    r_ptr = 3
    row_idx = 0
    for c in payload.get("conference_scraping", {}).get("conferences", []):
        wk_id = c.get("week_id", "")
        cid = c.get("conference_id", "")
        cname = c.get("conference_name", "")
        for s in c.get("speakers", []):
            vals = [wk_id, cid, cname, "Speaker", s.get("name", ""), s.get("job_title", ""), s.get("company", ""), s.get("email", ""), s.get("linkedin", "")]
            for c_i, val in enumerate(vals, 1):
                cell = ws7.cell(row=r_ptr, column=c_i, value=_excel_str(val))
                cell.border = grid_border
                cell.font = body_font
                cell.alignment = align_left
                if row_idx % 2 == 1:
                    cell.fill = zebra_fill
            ws7.row_dimensions[r_ptr].height = 20
            r_ptr += 1
            row_idx += 1
        for a in c.get("attendees", []):
            vals = [wk_id, cid, cname, "Attendee", a.get("name", ""), a.get("job_title", ""), a.get("company", ""), a.get("email", ""), a.get("linkedin", "")]
            for c_i, val in enumerate(vals, 1):
                cell = ws7.cell(row=r_ptr, column=c_i, value=_excel_str(val))
                cell.border = grid_border
                cell.font = body_font
                cell.alignment = align_left
                if row_idx % 2 == 1:
                    cell.fill = zebra_fill
            ws7.row_dimensions[r_ptr].height = 20
            r_ptr += 1
            row_idx += 1
        for e in c.get("exhibitors", []):
            extra = e.get("website", "")
            if e.get("booth_number"):
                extra = f"Booth {e['booth_number']} | {extra}".strip(" |")
            vals = [wk_id, cid, cname, "Exhibitor", e.get("contact_person") or e.get("company_name", ""), e.get("job_title", ""), e.get("company_name", ""), e.get("email", ""), extra]
            for c_i, val in enumerate(vals, 1):
                cell = ws7.cell(row=r_ptr, column=c_i, value=_excel_str(val))
                cell.border = grid_border
                cell.font = body_font
                cell.alignment = align_left
                if row_idx % 2 == 1:
                    cell.fill = zebra_fill
            ws7.row_dimensions[r_ptr].height = 20
            r_ptr += 1
            row_idx += 1

    _set_col_widths(ws7, {1: 24, 2: 24, 3: 34, 4: 13, 5: 26, 6: 26, 7: 26, 8: 30, 9: 38})

    tmp_path = f"{output_path}.tmp"
    wb.save(tmp_path)
    os.replace(tmp_path, output_path)
    return output_path


# ==============================================================================
# PDF (.pdf) EXPORTER (Landscape Letter via ReportLab Platypus)
# ==============================================================================
def generate_pdf_report(
    payload: Dict[str, Any],
    output_path: str,
    title_scope: str = "Weekly Report",
) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    tmp_path = f"{output_path}.tmp"

    page_size = landscape(letter)  # 792 x 612 pt
    margin = 28
    usable_w = page_size[0] - (2 * margin)  # 736 pt

    base_styles = getSampleStyleSheet()
    s_title = ParagraphStyle(
        "RptTitle",
        parent=base_styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=16,
        leading=20,
        textColor=colors.HexColor("#0F172A"),
        spaceAfter=4,
    )
    s_subtitle = ParagraphStyle(
        "RptSub",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#475569"),
        spaceAfter=8,
    )
    s_sec = ParagraphStyle(
        "RptSec",
        parent=base_styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#1E3A5F"),
        spaceBefore=10,
        spaceAfter=5,
    )
    s_subsec = ParagraphStyle(
        "RptSubSec",
        parent=base_styles["Heading3"],
        fontName="Helvetica-Bold",
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#334155"),
        spaceBefore=8,
        spaceAfter=4,
    )
    s_note = ParagraphStyle(
        "RptNote",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#475569"),
        spaceAfter=6,
    )
    s_th = ParagraphStyle(
        "RptTH",
        parent=base_styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=7.5,
        leading=9.5,
        textColor=colors.white,
        alignment=TA_LEFT,
    )
    s_th_r = ParagraphStyle("RptTHR", parent=s_th, alignment=TA_RIGHT)
    s_td = ParagraphStyle(
        "RptTD",
        parent=base_styles["Normal"],
        fontName="Helvetica",
        fontSize=7.3,
        leading=9.5,
        textColor=colors.HexColor("#1E293B"),
        alignment=TA_LEFT,
    )
    s_td_b = ParagraphStyle("RptTDB", parent=s_td, fontName="Helvetica-Bold")
    s_td_r = ParagraphStyle("RptTDR", parent=s_td, alignment=TA_RIGHT)

    def _base_table_style(header_bg: str = "#1E3A5F") -> List[Any]:
        return [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]

    def _draw_footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748B"))
        canvas.drawString(
            margin,
            15,
            f"Adople Conference Agent Automated Reporting System | Generated {payload.get('generated_at', '')} | Mailbox: {payload.get('mailbox', '')}",
        )
        canvas.drawRightString(page_size[0] - margin, 15, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        tmp_path,
        pagesize=page_size,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=margin,
        bottomMargin=30,
        title=f"Adople Conference Agent - {title_scope}",
    )

    exec_sum = payload.get("executive_summary", {})
    out_sum = exec_sum.get("outreach", {})
    qual_sum = out_sum.get("qualified", {})
    nq_sum = out_sum.get("non_qualified", {})
    fup_sum = out_sum.get("general_follow_up", {})
    comp_tot = exec_sum.get("company_rankings", {})
    scrap_tot = exec_sum.get("conference_scraping", {})

    story: List[Any] = []

    # Title Header
    story.append(Paragraph(xml_escape(f"Adople Conference Agent — {title_scope}"), s_title))
    story.append(
        Paragraph(
            xml_escape(
                f"Generated: {payload.get('generated_at', '')} | Mailbox: {payload.get('mailbox', '')} | "
                f"Graph Last Sync: {payload.get('graph_synced_at', '')} | Source: Verified PostgreSQL, Excel & Outlook Records"
            ),
            s_subtitle,
        )
    )
    story.append(HRFlowable(width="100%", thickness=1.2, color=colors.HexColor("#1E3A5F"), spaceAfter=8))

    # Executive Summary Cards Table
    kpi_data = [
        [
            _pdf_p("Total Prospect Emails Sent", s_th),
            _pdf_p("Delivered (Rate)", s_th),
            _pdf_p("Bounced (Rate)", s_th),
            _pdf_p("Replies Received (Rate)", s_th),
            _pdf_p("Companies Ranked", s_th),
            _pdf_p("Conferences & Contacts", s_th),
        ],
        [
            _pdf_p(str(out_sum.get("sent", 0)), s_td_b),
            _pdf_p(f"{out_sum.get('delivered', 0)} ({out_sum.get('delivery_rate_pct', 0.0)}%)", s_td_b),
            _pdf_p(f"{out_sum.get('bounced', 0)} ({out_sum.get('bounce_rate_pct', 0.0)}%)", s_td_b),
            _pdf_p(f"{out_sum.get('replied', 0)} ({out_sum.get('reply_rate_pct', 0.0)}%)", s_td_b),
            _pdf_p(
                f"{comp_tot.get('unique_companies', 0)} unique\n({comp_tot.get('qualified_entries', 0)} Qual / {comp_tot.get('non_qualified_entries', 0)} Non-Qual)",
                s_td_b,
            ),
            _pdf_p(
                f"{scrap_tot.get('total_conferences', 0)} Confs | {scrap_tot.get('total_contacts', 0)} Contacts\n"
                f"(Spk {scrap_tot.get('total_speakers', 0)} / Att {scrap_tot.get('total_attendees', 0)} / Exh {scrap_tot.get('total_exhibitors', 0)})",
                s_td_b,
            ),
        ],
    ]
    kpi_tbl = Table(kpi_data, colWidths=[108, 118, 112, 128, 130, 140], repeatRows=1)
    kpi_tbl.setStyle(TableStyle(_base_table_style("#1E3A5F")))
    story.append(kpi_tbl)
    story.append(Spacer(1, 8))

    # Segment Breakdown + Follow-up
    story.append(Paragraph("Outreach Segmentation: Qualified, Non-Qualified & Follow-Up", s_subsec))
    seg_tbl_data = [
        [
            _pdf_p("Segment", s_th),
            _pdf_p("Sent", s_th_r),
            _pdf_p("Delivered", s_th_r),
            _pdf_p("Bounced", s_th_r),
            _pdf_p("Replied", s_th_r),
            _pdf_p("Delivery %", s_th_r),
            _pdf_p("Bounce %", s_th_r),
            _pdf_p("Reply % (Sent)", s_th_r),
            _pdf_p("Notes", s_th),
        ],
        [
            _pdf_p("All Prospect Outreach", s_td_b),
            _pdf_p(out_sum.get("sent", 0), s_td_r),
            _pdf_p(out_sum.get("delivered", 0), s_td_r),
            _pdf_p(out_sum.get("bounced", 0), s_td_r),
            _pdf_p(out_sum.get("replied", 0), s_td_r),
            _pdf_p(f"{out_sum.get('delivery_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{out_sum.get('bounce_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{out_sum.get('reply_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"Excludes {exec_sum.get('excluded_test_sends_count', 0)} manual QA test email(s)", s_td),
        ],
        [
            _pdf_p("Qualified Leads (ICP >= 50)", s_td_b),
            _pdf_p(qual_sum.get("sent", 0), s_td_r),
            _pdf_p(qual_sum.get("delivered", 0), s_td_r),
            _pdf_p(qual_sum.get("bounced", 0), s_td_r),
            _pdf_p(qual_sum.get("replied", 0), s_td_r),
            _pdf_p(f"{qual_sum.get('delivery_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{qual_sum.get('bounce_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{qual_sum.get('reply_rate_pct', 0.0)}%", s_td_r),
            _pdf_p("Dispatched from Qualified Leads pipeline", s_td),
        ],
        [
            _pdf_p("Non-Qualified Leads (ICP < 50)", s_td_b),
            _pdf_p(nq_sum.get("sent", 0), s_td_r),
            _pdf_p(nq_sum.get("delivered", 0), s_td_r),
            _pdf_p(nq_sum.get("bounced", 0), s_td_r),
            _pdf_p(nq_sum.get("replied", 0), s_td_r),
            _pdf_p(f"{nq_sum.get('delivery_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{nq_sum.get('bounce_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{nq_sum.get('reply_rate_pct', 0.0)}%", s_td_r),
            _pdf_p("Dispatched from Non-Qualified campaign", s_td),
        ],
        [
            _pdf_p("General Follow-Up Outreach", s_td_b),
            _pdf_p(fup_sum.get("sent", 0), s_td_r),
            _pdf_p(fup_sum.get("delivered", 0), s_td_r),
            _pdf_p(fup_sum.get("bounced", 0), s_td_r),
            _pdf_p(fup_sum.get("replied", 0), s_td_r),
            _pdf_p(f"{fup_sum.get('delivery_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{fup_sum.get('bounce_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{fup_sum.get('reply_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(
                f"Enabled={fup_sum.get('follow_up_enabled', False)}; Eligible awaiting reply={fup_sum.get('eligible_delivered_no_reply', 0)}",
                s_td,
            ),
        ],
    ]
    seg_tbl = Table(seg_tbl_data, colWidths=[142, 42, 52, 48, 48, 54, 52, 68, 230], repeatRows=1)
    seg_tbl.setStyle(TableStyle(_base_table_style("#2B547E")))
    story.append(seg_tbl)
    story.append(Spacer(1, 8))

    # Weekly Performance Table
    story.append(Paragraph("Section 2 — Weekly Performance Summary", s_sec))
    wk_rows = [
        [
            _pdf_p("Week Period (Sun–Sat)", s_th),
            _pdf_p("Status", s_th),
            _pdf_p("Sent", s_th_r),
            _pdf_p("Deliv", s_th_r),
            _pdf_p("Bounce", s_th_r),
            _pdf_p("Reply", s_th_r),
            _pdf_p("Deliv %", s_th_r),
            _pdf_p("Qual (S/D/B/R)", s_th),
            _pdf_p("Non-Qual (S/D/B/R)", s_th),
            _pdf_p("F/Up (S/R)", s_th),
            _pdf_p("Cos Ranked", s_th_r),
            _pdf_p("Confs / Contacts", s_th),
        ]
    ]
    for wp in payload.get("weekly_performance", []):
        wo = wp.get("outreach", {})
        wq = wo.get("qualified", {})
        wn = wo.get("non_qualified", {})
        wf = wo.get("general_follow_up", {})
        wcr = wp.get("company_ranking_summary", {})
        wcs = wp.get("conference_scraping_summary", {})
        wk_rows.append([
            _pdf_p(f"{wp.get('week_start', '')} to {wp.get('week_end', '')}", s_td_b),
            _pdf_p("Closed" if wp.get("is_completed_week") else "Active", s_td),
            _pdf_p(wo.get("sent", 0), s_td_r),
            _pdf_p(wo.get("delivered", 0), s_td_r),
            _pdf_p(wo.get("bounced", 0), s_td_r),
            _pdf_p(wo.get("replied", 0), s_td_r),
            _pdf_p(f"{wo.get('delivery_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{wq.get('sent',0)}/{wq.get('delivered',0)}/{wq.get('bounced',0)}/{wq.get('replied',0)}", s_td),
            _pdf_p(f"{wn.get('sent',0)}/{wn.get('delivered',0)}/{wn.get('bounced',0)}/{wn.get('replied',0)}", s_td),
            _pdf_p(f"{wf.get('sent',0)}/{wf.get('replied',0)} (Elig {wf.get('eligible_delivered_no_reply',0)})", s_td),
            _pdf_p(wcr.get("total_companies", 0), s_td_r),
            _pdf_p(f"{wcs.get('total_conferences', 0)} confs / {wcs.get('total_contacts', 0)} cts", s_td),
        ])
    wk_tbl = Table(wk_rows, colWidths=[110, 42, 34, 34, 38, 34, 42, 74, 82, 76, 52, 118], repeatRows=1)
    wk_tbl.setStyle(TableStyle(_base_table_style("#1E3A5F")))
    story.append(wk_tbl)
    story.append(Spacer(1, 8))

    # Section 5: Template Performance
    story.append(Paragraph("Section 5 — Email Template Performance", s_sec))
    tmpl_rows = [
        [
            _pdf_p("Template Name", s_th),
            _pdf_p("Emails Sent", s_th_r),
            _pdf_p("Unique Recipients", s_th_r),
            _pdf_p("Delivered", s_th_r),
            _pdf_p("Bounced", s_th_r),
            _pdf_p("Replied", s_th_r),
            _pdf_p("Delivery %", s_th_r),
            _pdf_p("Bounce %", s_th_r),
            _pdf_p("Reply %", s_th_r),
            _pdf_p("Replies (Pos / Neu / Neg)", s_th),
        ]
    ]
    for tm in payload.get("template_performance", []):
        tmpl_rows.append([
            _pdf_p(tm.get("template_name", ""), s_td_b),
            _pdf_p(tm.get("sent", 0), s_td_r),
            _pdf_p(tm.get("unique_recipients", 0), s_td_r),
            _pdf_p(tm.get("delivered", 0), s_td_r),
            _pdf_p(tm.get("bounced", 0), s_td_r),
            _pdf_p(tm.get("replied", 0), s_td_r),
            _pdf_p(f"{tm.get('delivery_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{tm.get('bounce_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{tm.get('reply_rate_pct', 0.0)}%", s_td_r),
            _pdf_p(f"{tm.get('positive_replies',0)} / {tm.get('neutral_replies',0)} / {tm.get('negative_replies',0)}", s_td),
        ])
    tmpl_tbl = Table(tmpl_rows, colWidths=[96, 62, 74, 58, 56, 56, 64, 62, 62, 146], repeatRows=1)
    tmpl_tbl.setStyle(TableStyle(_base_table_style("#2B547E")))
    story.append(tmpl_tbl)

    # --------------------------------------------------------------------------
    # Section 1: Email Outreach Details (Bounces, Replies & Full Ledger)
    # --------------------------------------------------------------------------
    outreach_recs = payload.get("email_outreach", {}).get("records", [])
    bounces = payload.get("email_outreach", {}).get("bounces", [])
    replies = payload.get("email_outreach", {}).get("replies", [])

    if outreach_recs or bounces or replies:
        story.append(PageBreak())
        story.append(Paragraph("Section 1 — Email Outreach Report", s_sec))

    if bounces:
        story.append(Paragraph(f"Bounced Emails & SMTP Diagnostic Reasons ({len(bounces)})", s_subsec))
        b_rows = [
            [
                _pdf_p("Recipient", s_th),
                _pdf_p("Company / Conference", s_th),
                _pdf_p("Tier / Template", s_th),
                _pdf_p("Sent At", s_th),
                _pdf_p("Bounce Reason (SMTP NDR)", s_th),
            ]
        ]
        for b in bounces:
            b_rows.append([
                _pdf_p(f"{b.get('recipient_name', '')}\n{b.get('recipient_email', '')}", s_td_b),
                _pdf_p(f"{b.get('company_name', '')}\n{b.get('conference_name', '')}", s_td),
                _pdf_p(f"{b.get('lead_classification', '')} | {b.get('template_used', '')}", s_td),
                _pdf_p(b.get("sent_at", "")[:16], s_td),
                _pdf_p(b.get("bounce_reason", ""), s_td, max_len=360),
            ])
        b_tbl = Table(b_rows, colWidths=[145, 140, 100, 75, 276], repeatRows=1)
        b_tbl.setStyle(TableStyle(_base_table_style("#991B1B")))
        story.append(b_tbl)
        story.append(Spacer(1, 8))

    if replies:
        story.append(Paragraph(f"Received Replies & Details ({len(replies)})", s_subsec))
        r_rows = [
            [
                _pdf_p("Recipient", s_th),
                _pdf_p("Conference / Tier", s_th),
                _pdf_p("Sentiment / Intent", s_th),
                _pdf_p("Received At", s_th),
                _pdf_p("Reply Details", s_th),
            ]
        ]
        for rep in replies:
            r_rows.append([
                _pdf_p(f"{rep.get('recipient_name', '')}\n{rep.get('recipient_email', '')}", s_td_b),
                _pdf_p(f"{rep.get('conference_name', '')}\n{rep.get('lead_classification', '')} | {rep.get('template_used', '')}", s_td),
                _pdf_p(f"{rep.get('reply_sentiment', '')} / {rep.get('reply_intent', '')}", s_td_b),
                _pdf_p(rep.get("reply_received_at", "")[:19], s_td),
                _pdf_p(rep.get("reply_details", ""), s_td, max_len=500),
            ])
        r_tbl = Table(r_rows, colWidths=[140, 140, 95, 85, 276], repeatRows=1)
        r_tbl.setStyle(TableStyle(_base_table_style("#1E40AF")))
        story.append(r_tbl)
        story.append(Spacer(1, 8))

    if outreach_recs:
        story.append(Paragraph(f"Complete Sent Email Ledger ({len(outreach_recs)} Dispatched Emails)", s_subsec))
        o_rows = [
            [
                _pdf_p("Sent At / Week", s_th),
                _pdf_p("Recipient Name & Email", s_th),
                _pdf_p("Conference & Tier", s_th),
                _pdf_p("Template", s_th),
                _pdf_p("Status", s_th),
                _pdf_p("Subject & Message Sent", s_th),
            ]
        ]
        for rec in outreach_recs:
            st_txt = rec.get("delivery_status", "")
            if rec.get("replied"):
                st_txt += f"\nReplied ({rec.get('reply_sentiment', '')})"
            msg_preview = _safe_str(rec.get("message_sent", ""), max_len=240)
            o_rows.append([
                _pdf_p(f"{rec.get('sent_date', '')}\n{rec.get('week_id', '').replace('WEEK-', '')}", s_td),
                _pdf_p(f"{rec.get('recipient_name', '')}\n{rec.get('recipient_email', '')}", s_td_b),
                _pdf_p(f"{rec.get('conference_name', '')}\n{rec.get('lead_classification', '')} (ICP {rec.get('icp_score') or '—'})", s_td),
                _pdf_p(rec.get("template_used", ""), s_td),
                _pdf_p(st_txt, s_td_b),
                _pdf_p(msg_preview, s_td),
            ])
        o_tbl = Table(o_rows, colWidths=[76, 134, 134, 58, 72, 262], repeatRows=1)
        o_tbl.setStyle(TableStyle(_base_table_style("#1E3A5F")))
        story.append(o_tbl)

    # --------------------------------------------------------------------------
    # Section 3: Company Ranking Report
    # --------------------------------------------------------------------------
    by_wk_comp = payload.get("company_rankings", {}).get("by_week", {})
    if by_wk_comp:
        story.append(PageBreak())
        story.append(Paragraph("Section 3 — Company Ranking Report", s_sec))
        story.append(Paragraph("Weekly Company Ranking Benchmarks & Inter-Week Changes", s_subsec))
        b_comp_rows = [
            [
                _pdf_p("Week Period", s_th),
                _pdf_p("Companies", s_th_r),
                _pdf_p("Qualified", s_th_r),
                _pdf_p("Non-Qual", s_th_r),
                _pdf_p("Qual Rate", s_th_r),
                _pdf_p("Avg ICP", s_th_r),
                _pdf_p("Avg Change", s_th_r),
                _pdf_p("Top 10 Avg", s_th_r),
                _pdf_p("Top Ranked Company (Score)", s_th),
                _pdf_p("Returning / New", s_th),
            ]
        ]
        for wk_id in sorted(by_wk_comp.keys()):
            wb_info = by_wk_comp[wk_id]
            avg_chg = wb_info.get("avg_score_change_vs_prev")
            chg_txt = f"{avg_chg:+.2f}" if isinstance(avg_chg, (int, float)) else "Baseline"
            b_comp_rows.append([
                _pdf_p(wb_info.get("week_period", wk_id), s_td_b),
                _pdf_p(wb_info.get("total_companies", 0), s_td_r),
                _pdf_p(wb_info.get("qualified_companies", 0), s_td_r),
                _pdf_p(wb_info.get("non_qualified_companies", 0), s_td_r),
                _pdf_p(f"{wb_info.get('qualification_rate_pct', 0.0)}%", s_td_r),
                _pdf_p(wb_info.get("avg_icp_score", 0.0), s_td_r),
                _pdf_p(chg_txt, s_td_r),
                _pdf_p(wb_info.get("top_10_avg_score", 0.0), s_td_r),
                _pdf_p(f"{wb_info.get('top_company', '')} ({wb_info.get('top_score', 0.0)})", s_td),
                _pdf_p(f"{wb_info.get('returning_companies_vs_prev', 0)} / {wb_info.get('new_companies_count', 0)}", s_td),
            ])
        bc_tbl = Table(b_comp_rows, colWidths=[116, 48, 48, 48, 52, 48, 54, 54, 194, 74], repeatRows=1)
        bc_tbl.setStyle(TableStyle(_base_table_style("#1E3A5F")))
        story.append(bc_tbl)
        story.append(Spacer(1, 8))

        for wk_id in sorted(by_wk_comp.keys()):
            wb_info = by_wk_comp[wk_id]
            comps = wb_info.get("companies", [])
            story.append(
                Paragraph(
                    xml_escape(
                        f"Week Period: {wb_info.get('week_period', wk_id)} — {len(comps)} Companies Ranked "
                        f"(Qualified: {wb_info.get('qualified_companies', 0)} | Non-Qualified: {wb_info.get('non_qualified_companies', 0)})"
                    ),
                    s_subsec,
                )
            )
            c_rows = [
                [
                    _pdf_p("Rank", s_th_r),
                    _pdf_p("Chg", s_th),
                    _pdf_p("Company Name", s_th),
                    _pdf_p("Industry", s_th),
                    _pdf_p("Size", s_th),
                    _pdf_p("ICP Score", s_th_r),
                    _pdf_p("Classification", s_th),
                    _pdf_p("Status", s_th),
                    _pdf_p("Associated Conference", s_th),
                ]
            ]
            for c in comps:
                c_rows.append([
                    _pdf_p(c.get("rank", 0), s_td_r),
                    _pdf_p(c.get("rank_change_display", "New"), s_td),
                    _pdf_p(c.get("company_name", ""), s_td_b),
                    _pdf_p(c.get("primary_industry", ""), s_td),
                    _pdf_p(c.get("headcount_tier", ""), s_td),
                    _pdf_p(c.get("icp_score", 0.0), s_td_r),
                    _pdf_p(c.get("classification", ""), s_td_b),
                    _pdf_p(c.get("qualification_status", ""), s_td),
                    _pdf_p(c.get("associated_conference", ""), s_td),
                ])
            c_tbl = Table(c_rows, colWidths=[30, 44, 152, 112, 68, 48, 68, 68, 146], repeatRows=1)
            c_tbl.setStyle(TableStyle(_base_table_style("#2B547E")))
            story.append(c_tbl)
            story.append(Spacer(1, 8))

    # --------------------------------------------------------------------------
    # Section 4: Conference Scraping Report
    # --------------------------------------------------------------------------
    by_wk_scrap = payload.get("conference_scraping", {}).get("by_week", {})
    if by_wk_scrap:
        story.append(PageBreak())
        story.append(Paragraph("Section 4 — Conference Scraping Report", s_sec))
        story.append(Paragraph("Weekly Conference & Contact Collection Summary", s_subsec))
        sc_sum_rows = [
            [
                _pdf_p("Week Period", s_th),
                _pdf_p("Conferences", s_th_r),
                _pdf_p("Speakers", s_th_r),
                _pdf_p("Attendees", s_th_r),
                _pdf_p("Exhibitors", s_th_r),
                _pdf_p("Total Contacts", s_th_r),
                _pdf_p("Verified Emails", s_th_r),
                _pdf_p("Top Industries Collected", s_th),
            ]
        ]
        for wk_id in sorted(by_wk_scrap.keys()):
            wsi = by_wk_scrap[wk_id]
            ver_em = (
                wsi.get("verified_emails_speakers", 0)
                + wsi.get("verified_emails_attendees", 0)
                + wsi.get("verified_emails_exhibitors", 0)
            )
            inds = ", ".join(f"{x['industry']} ({x['count']})" for x in wsi.get("top_industries", [])[:4])
            sc_sum_rows.append([
                _pdf_p(f"{wsi.get('week_start', '')} to {wsi.get('week_end', '')}", s_td_b),
                _pdf_p(wsi.get("total_conferences", 0), s_td_r),
                _pdf_p(wsi.get("total_speakers", 0), s_td_r),
                _pdf_p(wsi.get("total_attendees", 0), s_td_r),
                _pdf_p(wsi.get("total_exhibitors", 0), s_td_r),
                _pdf_p(wsi.get("total_contacts", 0), s_td_r),
                _pdf_p(ver_em, s_td_r),
                _pdf_p(inds, s_td),
            ])
        sc_sum_tbl = Table(sc_sum_rows, colWidths=[116, 56, 52, 54, 54, 62, 62, 280], repeatRows=1)
        sc_sum_tbl.setStyle(TableStyle(_base_table_style("#1E3A5F")))
        story.append(sc_sum_tbl)
        story.append(Spacer(1, 8))

        for wk_id in sorted(by_wk_scrap.keys()):
            wsi = by_wk_scrap[wk_id]
            confs = wsi.get("conferences", [])
            story.append(
                Paragraph(
                    xml_escape(
                        f"Conferences for {wsi.get('week_start', '')} to {wsi.get('week_end', '')} "
                        f"({len(confs)} Conferences | {wsi.get('total_speakers', 0)} Speakers | "
                        f"{wsi.get('total_attendees', 0)} Attendees | {wsi.get('total_exhibitors', 0)} Exhibitors)"
                    ),
                    s_subsec,
                )
            )
            cf_rows = [
                [
                    _pdf_p("Date", s_th),
                    _pdf_p("Conference Name", s_th),
                    _pdf_p("Industry", s_th),
                    _pdf_p("Official Website", s_th),
                    _pdf_p("Spk/Att/Exh", s_th),
                    _pdf_p("Associated Contacts / Exhibitors", s_th),
                ]
            ]
            for c in confs:
                assoc_parts = []
                if c.get("speakers"):
                    assoc_parts.append("Speakers: " + ", ".join(s["name"] for s in c["speakers"][:5]))
                if c.get("attendees"):
                    assoc_parts.append("Attendees: " + ", ".join(a["name"] for a in c["attendees"][:4]))
                if c.get("exhibitors"):
                    assoc_parts.append("Exhibitors: " + ", ".join(e["company_name"] for e in c["exhibitors"][:4]))
                assoc_txt = " | ".join(assoc_parts) or "No public contact details listed"
                dt_txt = c.get("start_date", "")
                if c.get("end_date") and c.get("end_date") != dt_txt:
                    dt_txt = f"{dt_txt}\n→ {c['end_date']}"
                cf_rows.append([
                    _pdf_p(dt_txt, s_td),
                    _pdf_p(f"{c.get('conference_name', '')}\n({c.get('location', '')})", s_td_b),
                    _pdf_p(c.get("industry", ""), s_td),
                    _pdf_p(c.get("official_website", ""), s_td),
                    _pdf_p(f"{c.get('speakers_count', 0)} / {c.get('attendees_count', 0)} / {c.get('exhibitors_count', 0)}", s_td),
                    _pdf_p(assoc_txt, s_td),
                ])
            cf_tbl = Table(cf_rows, colWidths=[64, 152, 98, 152, 58, 212], repeatRows=1)
            cf_tbl.setStyle(TableStyle(_base_table_style("#2B547E")))
            story.append(cf_tbl)
            story.append(Spacer(1, 8))

    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    os.replace(tmp_path, output_path)
    return output_path

