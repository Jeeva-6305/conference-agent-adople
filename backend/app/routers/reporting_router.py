"""
FastAPI Router & 24/7 Interactive Dashboard for the Automated Weekly Outreach & Conference Reporting System.

Strictly isolated under /reports and /api/reporting/* so existing routes and workflows remain untouched.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..reporting_models import WeeklyReportSnapshot
from ..services.reporting_exporter import generate_excel_report, generate_pdf_report
from ..services.reporting_service import (
    REPORTS_DIR,
    ReportingService,
    parse_week_id,
)

logger = logging.getLogger("reporting_router")

router = APIRouter(tags=["Automated Reporting"])


@router.get("/api/reporting/summary")
def get_reporting_summary(
    week_id: Optional[str] = Query(None, description="Optional WEEK-YYYY-MM-DD_YYYY-MM-DD filter or 'ALL'"),
    refresh: bool = Query(False, description="Force live Graph + DB + Excel refresh before returning"),
    db: Session = Depends(get_db),
):
    svc = ReportingService(db)
    if refresh:
        payload = svc.build_full_report_payload(refresh_graph=True)
    else:
        payload = svc.get_live_payload(max_cache_age_seconds=90)
    if week_id and week_id.upper() != "ALL":
        return svc.filter_payload_for_week(payload, week_id)
    return payload


@router.get("/api/reporting/weeks")
def get_reporting_weeks(db: Session = Depends(get_db)):
    svc = ReportingService(db)
    payload = svc.get_live_payload(max_cache_age_seconds=120)
    archives = svc.get_archive_list()
    latest_arch_by_wk: Dict[str, Dict[str, Any]] = {}
    for a in archives:
        if a["week_id"] not in latest_arch_by_wk:
            latest_arch_by_wk[a["week_id"]] = a

    weeks_out = []
    for wp in payload.get("weekly_performance", []):
        wk_id = wp["week_id"]
        arch = latest_arch_by_wk.get(wk_id, {})
        weeks_out.append({
            "week_id": wk_id,
            "week_start": wp["week_start"],
            "week_end": wp["week_end"],
            "is_completed_week": wp["is_completed_week"],
            "sent": wp["outreach"]["sent"],
            "delivered": wp["outreach"]["delivered"],
            "bounced": wp["outreach"]["bounced"],
            "replied": wp["outreach"]["replied"],
            "companies": wp["company_ranking_summary"]["total_companies"],
            "conferences": wp["conference_scraping_summary"]["total_conferences"],
            "contacts": wp["conference_scraping_summary"]["total_contacts"],
            "archived_version": arch.get("snapshot_version"),
            "is_sealed": arch.get("is_sealed", False),
            "download_xlsx": f"/api/reporting/download/{wk_id}?format=xlsx",
            "download_pdf": f"/api/reporting/download/{wk_id}?format=pdf",
        })

    return {
        "latest_week_id": payload.get("latest_week_id", ""),
        "generated_at": payload.get("generated_at", ""),
        "weeks": weeks_out,
    }


@router.get("/api/reporting/report/{week_id}")
def get_week_report(
    week_id: str,
    live: bool = Query(True, description="Return live data (true) or stored snapshot JSON (false)"),
    version: Optional[int] = Query(None, description="Specific immutable snapshot version"),
    db: Session = Depends(get_db),
):
    svc = ReportingService(db)
    svc.ensure_initialized()

    if version is not None or not live:
        q = db.query(WeeklyReportSnapshot).filter(WeeklyReportSnapshot.week_id == week_id)
        if version is not None:
            q = q.filter(WeeklyReportSnapshot.snapshot_version == version)
        snap = q.order_by(WeeklyReportSnapshot.snapshot_version.desc()).first()
        if not snap:
            raise HTTPException(status_code=404, detail=f"No archived snapshot found for {week_id}")
        data = json.loads(snap.report_payload_json or "{}")
        data["_snapshot_meta"] = snap.to_meta_dict()
        return data

    payload = svc.get_live_payload(max_cache_age_seconds=90)
    if week_id.upper() != "ALL" and week_id not in payload.get("weeks", []) and not parse_week_id(week_id):
        raise HTTPException(status_code=404, detail=f"Week '{week_id}' not found")
    return svc.filter_payload_for_week(payload, week_id)


@router.post("/api/reporting/refresh")
def trigger_reporting_refresh(
    sync_outlook: bool = Query(True, description="Sync Microsoft Graph SentItems & Inbox cache"),
    force_export: bool = Query(False, description="Force re-export of unsealed & latest documents"),
    db: Session = Depends(get_db),
):
    svc = ReportingService(db)
    result = svc.ensure_weekly_archives_and_refresh(
        refresh_graph=sync_outlook,
        force_export=force_export,
    )
    return result


@router.get("/api/reporting/archives")
def list_reporting_archives(db: Session = Depends(get_db)):
    svc = ReportingService(db)
    archives = svc.get_archive_list()
    for a in archives:
        wk = a["week_id"]
        ver = a["snapshot_version"]
        a["download_xlsx"] = f"/api/reporting/download/{wk}?format=xlsx&version={ver}"
        a["download_pdf"] = f"/api/reporting/download/{wk}?format=pdf&version={ver}"
    return {
        "total_snapshots": len(archives),
        "archives": archives,
        "latest_consolidated_xlsx": "/api/reporting/download/latest?format=xlsx",
        "latest_consolidated_pdf": "/api/reporting/download/latest?format=pdf",
    }


@router.get("/api/reporting/download/latest")
def download_latest_report(
    format: Literal["xlsx", "pdf"] = Query("xlsx"),
    week_id: Optional[str] = Query(None, description="Optional week_id scope; defaults to All Weeks consolidated"),
    sync: bool = Query(False, description="Sync live Graph before generating"),
    db: Session = Depends(get_db),
):
    svc = ReportingService(db)
    if sync:
        payload = svc.build_full_report_payload(refresh_graph=True)
    else:
        payload = svc.get_live_payload(max_cache_age_seconds=60)

    if week_id and week_id.upper() != "ALL":
        return download_week_report(week_id=week_id, format=format, version=None, db=db)

    ext = format.lower()
    out_file = REPORTS_DIR / f"Conference_Agent_Latest_Report.{ext}"
    if ext == "xlsx":
        generate_excel_report(payload, str(out_file), title_scope="Consolidated Weekly & Historical Report")
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        fname = "Adople_Conference_Agent_Latest_Report.xlsx"
    else:
        generate_pdf_report(payload, str(out_file), title_scope="Consolidated Weekly & Historical Report")
        media = "application/pdf"
        fname = "Adople_Conference_Agent_Latest_Report.pdf"

    return FileResponse(str(out_file), filename=fname, media_type=media)


@router.get("/api/reporting/download/{week_id}")
def download_week_report(
    week_id: str,
    format: Literal["xlsx", "pdf"] = Query("xlsx"),
    version: Optional[int] = Query(None, description="Optional snapshot version to download exact historical baseline"),
    db: Session = Depends(get_db),
):
    if week_id.lower() == "latest":
        return download_latest_report(format=format, week_id=None, sync=False, db=db)

    svc = ReportingService(db)
    svc.ensure_initialized()

    q = db.query(WeeklyReportSnapshot).filter(WeeklyReportSnapshot.week_id == week_id)
    if version is not None:
        q = q.filter(WeeklyReportSnapshot.snapshot_version == version)
    snap = q.order_by(WeeklyReportSnapshot.snapshot_version.desc()).first()

    ext = format.lower()
    media = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        if ext == "xlsx"
        else "application/pdf"
    )

    if snap:
        target_path = Path(snap.xlsx_path if ext == "xlsx" else snap.pdf_path)
        if target_path.exists():
            fname = target_path.name
            return FileResponse(str(target_path), filename=fname, media_type=media)

    # Fallback: generate dynamically for requested valid week without overwriting sealed files
    bounds = parse_week_id(week_id)
    if not bounds:
        raise HTTPException(status_code=404, detail=f"Invalid or unknown week_id: {week_id}")

    payload = svc.get_live_payload(max_cache_age_seconds=90)
    wk_payload = svc.filter_payload_for_week(payload, week_id)
    scope_lbl = f"Weekly Report: {bounds[0].isoformat()} to {bounds[1].isoformat()}"
    out_file = REPORTS_DIR / "cache" / f"Conference_Agent_Report_{week_id}.{ext}"
    if ext == "xlsx":
        generate_excel_report(wk_payload, str(out_file), title_scope=scope_lbl)
    else:
        generate_pdf_report(wk_payload, str(out_file), title_scope=scope_lbl)

    return FileResponse(
        str(out_file),
        filename=f"Adople_Conference_Agent_{week_id}.{ext}",
        media_type=media,
    )


# ==============================================================================
# 24/7 INTERACTIVE REPORTING DASHBOARD (/reports)
# ==============================================================================
_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Adople Conference Agent — 24/7 Automated Reporting</title>
<style>
  :root {
    --bg: #f1f5f9;
    --surface: #ffffff;
    --navy: #0f172a;
    --primary: #1e3a5f;
    --accent: #2563eb;
    --accent-soft: #dbeafe;
    --border: #e2e8f0;
    --text: #0f172a;
    --muted: #64748b;
    --green: #166534;
    --green-bg: #dcfce7;
    --red: #991b1b;
    --red-bg: #fee2e2;
    --amber: #92400e;
    --amber-bg: #fef3c7;
    --blue: #1e40af;
    --blue-bg: #dbeafe;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Inter, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.45;
  }
  header {
    background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 100%);
    color: #fff;
    padding: 18px 28px;
    border-bottom: 3px solid #3b82f6;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }
  .brand h1 {
    margin: 0;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .live-pill {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
    font-weight: 600;
    padding: 3px 9px;
    border-radius: 999px;
    background: rgba(34, 197, 94, 0.2);
    color: #86efac;
    border: 1px solid rgba(34, 197, 94, 0.4);
  }
  .live-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: #4ade80;
    box-shadow: 0 0 8px #4ade80;
  }
  .meta-line {
    font-size: 12px;
    color: #cbd5e1;
    margin-top: 4px;
  }
  .controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  select, input[type="text"], button, .btn-link {
    font-family: inherit;
    font-size: 13px;
    border-radius: 7px;
    padding: 8px 12px;
    border: 1px solid #cbd5e1;
  }
  select {
    background: #fff;
    color: var(--text);
    font-weight: 600;
    cursor: pointer;
  }
  .btn {
    cursor: pointer;
    font-weight: 600;
    border: none;
    display: inline-flex;
    align-items: center;
    gap: 6px;
    text-decoration: none;
    transition: opacity 0.15s ease, transform 0.1s ease;
  }
  .btn:hover { opacity: 0.92; }
  .btn:active { transform: translateY(1px); }
  .btn-refresh { background: #3b82f6; color: #fff; }
  .btn-excel { background: #16a34a; color: #fff; }
  .btn-pdf { background: #dc2626; color: #fff; }
  .btn-secondary { background: #e2e8f0; color: #0f172a; }
  .btn-sm { padding: 5px 10px; font-size: 12px; border-radius: 6px; }
  .container {
    max-width: 1460px;
    margin: 0 auto;
    padding: 20px 24px 48px;
  }
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(205px, 1fr));
    gap: 14px;
    margin-bottom: 18px;
  }
  .kpi-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 16px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }
  .kpi-label {
    font-size: 11.5px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
  }
  .kpi-value {
    font-size: 26px;
    font-weight: 800;
    color: var(--navy);
    margin: 4px 0 2px;
  }
  .kpi-sub {
    font-size: 12px;
    color: var(--muted);
  }
  .tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-bottom: 14px;
    border-bottom: 2px solid var(--border);
    padding-bottom: 8px;
  }
  .tab-btn {
    background: transparent;
    border: 1px solid transparent;
    color: var(--muted);
    font-weight: 600;
    padding: 8px 14px;
    border-radius: 7px;
    cursor: pointer;
  }
  .tab-btn:hover { background: #e2e8f0; color: var(--navy); }
  .tab-btn.active {
    background: var(--primary);
    color: #fff;
  }
  .panel { display: none; }
  .panel.active { display: block; }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 18px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }
  .card-header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
  }
  .card-title {
    margin: 0;
    font-size: 15.5px;
    font-weight: 700;
    color: var(--primary);
  }
  .filter-bar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-bottom: 12px;
    align-items: center;
  }
  .filter-bar input[type="text"] { min-width: 240px; }
  .table-wrap {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: 8px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12.7px;
  }
  th {
    background: #1e3a5f;
    color: #fff;
    font-weight: 600;
    text-align: left;
    padding: 9px 10px;
    white-space: nowrap;
  }
  th.num, td.num { text-align: right; font-variant-numeric: tabular-nums; }
  td {
    padding: 8px 10px;
    border-top: 1px solid var(--border);
    vertical-align: top;
  }
  tbody tr:nth-child(even) { background: #f8fafc; }
  tbody tr:hover { background: #eff6ff; }
  .badge {
    display: inline-block;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 999px;
    white-space: nowrap;
  }
  .badge-green { background: var(--green-bg); color: var(--green); }
  .badge-red { background: var(--red-bg); color: var(--red); }
  .badge-blue { background: var(--blue-bg); color: var(--blue); }
  .badge-amber { background: var(--amber-bg); color: var(--amber); }
  .badge-slate { background: #e2e8f0; color: #334155; }
  .small-muted { font-size: 11.5px; color: var(--muted); }
  .msg-snippet {
    max-width: 310px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .two-col {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
    gap: 16px;
  }
  .bar-track {
    width: 100%;
    height: 8px;
    background: #e2e8f0;
    border-radius: 999px;
    overflow: hidden;
    margin-top: 5px;
  }
  .bar-fill { height: 100%; border-radius: 999px; background: #2563eb; }
  .modal-backdrop {
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(15, 23, 42, 0.55);
    z-index: 1000;
    align-items: center;
    justify-content: center;
    padding: 20px;
  }
  .modal-backdrop.open { display: flex; }
  .modal {
    background: #fff;
    border-radius: 12px;
    max-width: 860px;
    width: 100%;
    max-height: 86vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    box-shadow: 0 20px 50px rgba(0,0,0,0.28);
  }
  .modal-head {
    background: var(--primary);
    color: #fff;
    padding: 14px 18px;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  .modal-head h3 { margin: 0; font-size: 15px; }
  .modal-close {
    background: rgba(255,255,255,0.18);
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 4px 10px;
    cursor: pointer;
    font-weight: 700;
  }
  .modal-body {
    padding: 18px;
    overflow-y: auto;
    font-size: 13px;
  }
  pre.email-pre {
    background: #f8fafc;
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    font-size: 12.2px;
    line-height: 1.5;
  }
</style>
</head>
<body>

<header>
  <div class="brand">
    <h1>
      Adople Conference Agent — Reporting Hub
      <span class="live-pill"><span class="live-dot"></span>24/7 AUTO-REPORTING</span>
    </h1>
    <div class="meta-line" id="metaLine">Loading verified telemetry...</div>
  </div>
  <div class="controls">
    <select id="weekSelector" title="Select Week Period">
      <option value="ALL">All Weeks Consolidated</option>
    </select>
    <button class="btn btn-refresh" id="btnRefresh" type="button">Sync Live Now</button>
    <a class="btn btn-excel" id="btnDownloadXlsx" href="/api/reporting/download/latest?format=xlsx">Download Excel</a>
    <a class="btn btn-pdf" id="btnDownloadPdf" href="/api/reporting/download/latest?format=pdf">Download PDF</a>
  </div>
</header>

<div class="container">
  <div class="kpi-grid" id="kpiGrid"></div>

  <div class="tabs" id="tabBar">
    <button class="tab-btn active" data-tab="weekly">Weekly Performance</button>
    <button class="tab-btn" data-tab="outreach">Email Outreach & Replies</button>
    <button class="tab-btn" data-tab="templates">Template Performance</button>
    <button class="tab-btn" data-tab="rankings">Company Rankings</button>
    <button class="tab-btn" data-tab="scraping">Conference Scraping</button>
    <button class="tab-btn" data-tab="archives">Historical Archives</button>
  </div>

  <!-- TAB 1: WEEKLY PERFORMANCE -->
  <section class="panel active" id="tab-weekly">
    <div class="two-col">
      <div class="card">
        <div class="card-header"><h2 class="card-title">Qualified vs Non-Qualified & Follow-Up Breakdown</h2></div>
        <div id="segmentGrid"></div>
      </div>
      <div class="card">
        <div class="card-header"><h2 class="card-title">General Follow-Up & Quality Guardrails</h2></div>
        <div id="followUpInfo"></div>
      </div>
    </div>
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Weekly Performance Report (Sunday–Saturday)</h2>
        <span class="small-muted">Exact reconciled figures across Outlook SentItems/Inbox, PostgreSQL, and Excel</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Week Period</th>
              <th>Status</th>
              <th class="num">Sent</th>
              <th class="num">Delivered</th>
              <th class="num">Bounced</th>
              <th class="num">Replied</th>
              <th class="num">Delivery %</th>
              <th class="num">Bounce %</th>
              <th class="num">Reply %</th>
              <th>Qualified (S/D/B/R)</th>
              <th>Non-Qualified (S/D/B/R)</th>
              <th>Follow-Up</th>
              <th class="num">Companies</th>
              <th class="num">Conferences</th>
            </tr>
          </thead>
          <tbody id="weeklyTbody"></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- TAB 2: EMAIL OUTREACH -->
  <section class="panel" id="tab-outreach">
    <div class="two-col">
      <div class="card">
        <div class="card-header"><h2 class="card-title">Bounced Emails & SMTP Diagnostic Reasons</h2></div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Recipient</th><th>Template / Tier</th><th>Bounce Reason (NDR)</th></tr>
            </thead>
            <tbody id="bouncesTbody"></tbody>
          </table>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><h2 class="card-title">Received Replies & Reply Details</h2></div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Recipient</th><th>Sentiment / Intent</th><th>Reply Details</th></tr>
            </thead>
            <tbody id="repliesTbody"></tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Complete Email Outreach Ledger</h2>
        <span class="small-muted" id="outreachCountLabel"></span>
      </div>
      <div class="filter-bar">
        <input type="text" id="outSearch" placeholder="Search recipient, email, company, conference..." />
        <select id="outStatusFilter">
          <option value="">All Statuses</option>
          <option value="Delivered">Delivered</option>
          <option value="Bounced">Bounced</option>
          <option value="Replied">Replied Only</option>
        </select>
        <select id="outTemplateFilter">
          <option value="">All Templates</option>
          <option value="Speakers">Speakers</option>
          <option value="Attendees">Attendees</option>
          <option value="Exhibitors">Exhibitors</option>
          <option value="General">General</option>
          <option value="Follow-Up">Follow-Up</option>
        </select>
        <select id="outTierFilter">
          <option value="">All Tiers</option>
          <option value="Qualified">Qualified</option>
          <option value="Non-Qualified">Non-Qualified</option>
        </select>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Sent Date</th>
              <th>Recipient</th>
              <th>Conference / Company</th>
              <th>Tier / ICP</th>
              <th>Template</th>
              <th>Delivery</th>
              <th>Reply</th>
              <th>Message Preview</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody id="outreachTbody"></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- TAB 3: TEMPLATE PERFORMANCE -->
  <section class="panel" id="tab-templates">
    <div class="card">
      <div class="card-header"><h2 class="card-title">Template Performance Overview</h2></div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Template Used</th>
              <th class="num">Sent</th>
              <th class="num">Unique Recipients</th>
              <th class="num">Delivered</th>
              <th class="num">Bounced</th>
              <th class="num">Replied</th>
              <th class="num">Delivery Rate %</th>
              <th class="num">Bounce Rate %</th>
              <th class="num">Reply Rate %</th>
              <th class="num">Pos</th>
              <th class="num">Neu</th>
              <th class="num">Neg</th>
            </tr>
          </thead>
          <tbody id="templatesTbody"></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- TAB 4: COMPANY RANKINGS -->
  <section class="panel" id="tab-rankings">
    <div class="card">
      <div class="card-header"><h2 class="card-title">Weekly Company Ranking Benchmarks & Inter-Week Changes</h2></div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Week Period</th>
              <th class="num">Total Companies</th>
              <th class="num">Qualified</th>
              <th class="num">Non-Qualified</th>
              <th class="num">Qual Rate %</th>
              <th class="num">Avg ICP Score</th>
              <th class="num">Avg Score Delta</th>
              <th>Top Ranked Company</th>
              <th class="num">Top Score</th>
              <th class="num">Returning / New</th>
            </tr>
          </thead>
          <tbody id="compBenchTbody"></tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Company Ranking Leaderboard</h2>
        <span class="small-muted" id="compCountLabel"></span>
      </div>
      <div class="filter-bar">
        <input type="text" id="compSearch" placeholder="Search company, domain, industry, conference..." />
        <select id="compTierFilter">
          <option value="">All Classifications</option>
          <option value="Qualified">Qualified</option>
          <option value="Non-Qualified">Non-Qualified</option>
        </select>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Week Period</th>
              <th class="num">Rank</th>
              <th>Rank Change</th>
              <th>Company</th>
              <th>Industry</th>
              <th>Headcount</th>
              <th class="num">ICP Score</th>
              <th>Qualification</th>
              <th>Classification</th>
              <th>Associated Conference</th>
            </tr>
          </thead>
          <tbody id="compTbody"></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- TAB 5: CONFERENCE SCRAPING -->
  <section class="panel" id="tab-scraping">
    <div class="card">
      <div class="card-header"><h2 class="card-title">Weekly Conference Scraping Summary</h2></div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Week Period</th>
              <th class="num">Conferences</th>
              <th class="num">Speakers</th>
              <th class="num">Attendees</th>
              <th class="num">Exhibitors</th>
              <th class="num">Total Contacts</th>
              <th class="num">Verified Emails</th>
              <th>Top Industries</th>
            </tr>
          </thead>
          <tbody id="scrapSumTbody"></tbody>
        </table>
      </div>
    </div>
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Conferences & Contact Associations</h2>
        <span class="small-muted" id="confCountLabel"></span>
      </div>
      <div class="filter-bar">
        <input type="text" id="confSearch" placeholder="Search conference, industry, city, website..." />
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Week</th>
              <th>Dates</th>
              <th>Conference Name</th>
              <th>Industry</th>
              <th>Location</th>
              <th>Website</th>
              <th class="num">Spk</th>
              <th class="num">Att</th>
              <th class="num">Exh</th>
              <th>Contacts</th>
            </tr>
          </thead>
          <tbody id="confTbody"></tbody>
        </table>
      </div>
    </div>
  </section>

  <!-- TAB 6: HISTORICAL ARCHIVES -->
  <section class="panel" id="tab-archives">
    <div class="card">
      <div class="card-header">
        <h2 class="card-title">Immutable Historical Weekly Report Archives</h2>
        <span class="small-muted">Completed past weekly reports are preserved verbatim without overwriting baselines</span>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Week Period</th>
              <th>Snapshot Version</th>
              <th>Lock Status</th>
              <th>Summary (Sent / Deliv / Reply | Cos | Confs)</th>
              <th>Generated At</th>
              <th>Downloads</th>
            </tr>
          </thead>
          <tbody id="archivesTbody"></tbody>
        </table>
      </div>
    </div>
  </section>
</div>

<!-- DETAIL MODAL -->
<div class="modal-backdrop" id="detailModal">
  <div class="modal">
    <div class="modal-head">
      <h3 id="modalTitle">Details</h3>
      <button class="modal-close" id="modalCloseBtn" type="button">Close</button>
    </div>
    <div class="modal-body" id="modalBody"></div>
  </div>
</div>

<script>
(function() {
  let CURRENT_PAYLOAD = null;
  let CURRENT_ARCHIVES = [];
  let FILTERED_OUTREACH = [];
  let FILTERED_CONFS = [];

  function esc(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function safeUrl(u) {
    const s = String(u || "").trim();
    if (/^https?:\/\//i.test(s)) return s;
    return "";
  }

  function openModal(title, htmlContent) {
    document.getElementById("modalTitle").textContent = title;
    document.getElementById("modalBody").innerHTML = htmlContent;
    document.getElementById("detailModal").classList.add("open");
  }

  document.getElementById("modalCloseBtn").addEventListener("click", () => {
    document.getElementById("detailModal").classList.remove("open");
  });
  document.getElementById("detailModal").addEventListener("click", (e) => {
    if (e.target.id === "detailModal") e.target.classList.remove("open");
  });

  // Tab switching
  document.getElementById("tabBar").addEventListener("click", (e) => {
    const btn = e.target.closest(".tab-btn");
    if (!btn) return;
    document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });

  function updateDownloadLinks(weekId) {
    const isAll = !weekId || weekId === "ALL";
    const xBtn = document.getElementById("btnDownloadXlsx");
    const pBtn = document.getElementById("btnDownloadPdf");
    if (isAll) {
      xBtn.href = "/api/reporting/download/latest?format=xlsx";
      pBtn.href = "/api/reporting/download/latest?format=pdf";
    } else {
      xBtn.href = "/api/reporting/download/" + encodeURIComponent(weekId) + "?format=xlsx";
      pBtn.href = "/api/reporting/download/" + encodeURIComponent(weekId) + "?format=pdf";
    }
  }

  function renderDashboard() {
    if (!CURRENT_PAYLOAD) return;
    const p = CURRENT_PAYLOAD;
    const exec = p.executive_summary || {};
    const out = exec.outreach || {};
    const qual = out.qualified || {};
    const nq = out.non_qualified || {};
    const fup = out.general_follow_up || {};
    const cr = exec.company_rankings || {};
    const cs = exec.conference_scraping || {};

    document.getElementById("metaLine").textContent =
      `Scope: ${p.scope || "All Weeks Consolidated"} | Mailbox: ${p.mailbox || ""} | Last Graph Sync: ${p.graph_synced_at || "Cached"} | Report Updated: ${p.generated_at || ""}`;

    // Populate week selector once preserving selection
    const sel = document.getElementById("weekSelector");
    const curVal = sel.value || "ALL";
    const opts = ['<option value="ALL">All Weeks Consolidated</option>'];
    (p.weeks || []).forEach(wk => {
      opts.push(`<option value="${esc(wk)}">${esc(wk)}</option>`);
    });
    sel.innerHTML = opts.join("");
    if (Array.from(sel.options).some(o => o.value === curVal)) sel.value = curVal;
    updateDownloadLinks(sel.value);

    // KPI Cards
    const kpis = [
      {
        label: "Prospect Emails Sent",
        val: out.sent || 0,
        sub: `${out.unique_recipients || 0} unique contacts (QA tests excl: ${exec.excluded_test_sends_count || 0})`
      },
      {
        label: "Delivery Rate",
        val: `${out.delivery_rate_pct || 0}%`,
        sub: `${out.delivered || 0} delivered / ${out.bounced || 0} bounced (${out.bounce_rate_pct || 0}%)`
      },
      {
        label: "Reply Rate",
        val: `${out.reply_rate_pct || 0}%`,
        sub: `${out.replied || 0} genuine replies (${out.reply_rate_of_delivered_pct || 0}% of delivered)`
      },
      {
        label: "Qualified vs Non-Qual",
        val: `${qual.sent || 0} / ${nq.sent || 0}`,
        sub: `Qual Deliv ${qual.delivery_rate_pct || 0}% | Non-Qual Deliv ${nq.delivery_rate_pct || 0}%`
      },
      {
        label: "Companies Ranked",
        val: cr.unique_companies || 0,
        sub: `Qualified: ${cr.qualified_entries || 0} | Non-Qual: ${cr.non_qualified_entries || 0}`
      },
      {
        label: "Conferences & Contacts",
        val: `${cs.total_conferences || 0} / ${cs.total_contacts || 0}`,
        sub: `Spk ${cs.total_speakers || 0} · Att ${cs.total_attendees || 0} · Exh ${cs.total_exhibitors || 0}`
      },
    ];
    document.getElementById("kpiGrid").innerHTML = kpis.map(k => `
      <div class="kpi-card">
        <div class="kpi-label">${esc(k.label)}</div>
        <div class="kpi-value">${esc(k.val)}</div>
        <div class="kpi-sub">${esc(k.sub)}</div>
      </div>
    `).join("");

    // Segment breakdown
    const segRows = [
      { name: "Qualified Leads Outreach (ICP >= 50)", d: qual, color: "#16a34a" },
      { name: "Non-Qualified Leads Outreach (ICP < 50)", d: nq, color: "#2563eb" },
      { name: "General Follow-Up Outreach", d: fup, color: "#9333ea" },
    ];
    document.getElementById("segmentGrid").innerHTML = segRows.map(s => `
      <div style="margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;font-size:13px;font-weight:600;">
          <span>${esc(s.name)}</span>
          <span>Sent ${s.d.sent || 0} · Deliv ${s.d.delivered || 0} (${s.d.delivery_rate_pct || 0}%) · Bounced ${s.d.bounced || 0} · Replied ${s.d.replied || 0} (${s.d.reply_rate_pct || 0}%)</span>
        </div>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.min(100, s.d.delivery_rate_pct || 0)}%;background:${s.color};"></div></div>
      </div>
    `).join("");

    document.getElementById("followUpInfo").innerHTML = `
      <div style="font-size:13px;line-height:1.65;">
        <div><strong>Automated Follow-Up Enabled:</strong> <span class="badge ${fup.follow_up_enabled ? 'badge-green' : 'badge-amber'}">${fup.follow_up_enabled ? 'ENABLED' : 'PAUSED (0 Sent)'}</span></div>
        <div><strong>Follow-Up Emails Sent:</strong> ${fup.sent || 0} | <strong>Follow-Up Replies:</strong> ${fup.replied || 0}</div>
        <div><strong>Delivered Prospects Awaiting Reply (Eligible for Follow-Up):</strong> ${fup.eligible_delivered_no_reply || 0}</div>
        <div class="small-muted" style="margin-top:6px;">All NDR bounces are separated strictly from genuine replies. Manual test sends (${exec.excluded_test_sends_count || 0}) are excluded from prospect KPIs.</div>
      </div>
    `;

    // Weekly performance table
    document.getElementById("weeklyTbody").innerHTML = (p.weekly_performance || []).map(w => {
      const wo = w.outreach || {};
      const wq = wo.qualified || {};
      const wn = wo.non_qualified || {};
      const wf = wo.general_follow_up || {};
      const wcr = w.company_ranking_summary || {};
      const wcs = w.conference_scraping_summary || {};
      return `
        <tr>
          <td><strong>${esc(w.week_start)} to ${esc(w.week_end)}</strong><div class="small-muted">${esc(w.week_id)}</div></td>
          <td><span class="badge ${w.is_completed_week ? 'badge-slate' : 'badge-blue'}">${w.is_completed_week ? 'Completed' : 'Active'}</span></td>
          <td class="num"><strong>${wo.sent || 0}</strong></td>
          <td class="num">${wo.delivered || 0}</td>
          <td class="num">${wo.bounced || 0}</td>
          <td class="num">${wo.replied || 0}</td>
          <td class="num">${wo.delivery_rate_pct || 0}%</td>
          <td class="num">${wo.bounce_rate_pct || 0}%</td>
          <td class="num">${wo.reply_rate_pct || 0}%</td>
          <td>${wq.sent||0} / ${wq.delivered||0} / ${wq.bounced||0} / ${wq.replied||0}</td>
          <td>${wn.sent||0} / ${wn.delivered||0} / ${wn.bounced||0} / ${wn.replied||0}</td>
          <td>Sent ${wf.sent||0} · Elig ${wf.eligible_delivered_no_reply||0}</td>
          <td class="num">${wcr.total_companies || 0}</td>
          <td class="num">${wcs.total_conferences || 0} <span class="small-muted">(${wcs.total_contacts || 0} cts)</span></td>
        </tr>
      `;
    }).join("") || `<tr><td colspan="14">No weekly data yet.</td></tr>`;

    // Bounces & Replies
    const bounces = (p.email_outreach || {}).bounces || [];
    document.getElementById("bouncesTbody").innerHTML = bounces.map(b => `
      <tr>
        <td><strong>${esc(b.recipient_name)}</strong><div class="small-muted">${esc(b.recipient_email)}</div><div class="small-muted">${esc(b.conference_name)}</div></td>
        <td><span class="badge badge-slate">${esc(b.template_used)}</span> <span class="badge badge-amber">${esc(b.lead_classification)}</span></td>
        <td><span class="badge badge-red">Bounced</span> <div style="margin-top:4px;font-size:12px;">${esc(b.bounce_reason)}</div></td>
      </tr>
    `).join("") || `<tr><td colspan="3" class="small-muted">Zero bounces recorded.</td></tr>`;

    const replies = (p.email_outreach || {}).replies || [];
    document.getElementById("repliesTbody").innerHTML = replies.map(r => `
      <tr>
        <td><strong>${esc(r.recipient_name)}</strong><div class="small-muted">${esc(r.recipient_email)}</div><div class="small-muted">${esc(r.reply_received_at)}</div></td>
        <td><span class="badge ${r.reply_sentiment === 'Negative' ? 'badge-red' : (r.reply_sentiment === 'Positive' ? 'badge-green' : 'badge-amber')}">${esc(r.reply_sentiment)}</span><div class="small-muted">${esc(r.reply_intent)}</div></td>
        <td><div style="font-size:12px;max-height:95px;overflow:auto;">${esc(r.reply_details)}</div></td>
      </tr>
    `).join("") || `<tr><td colspan="3" class="small-muted">Zero replies in selected scope.</td></tr>`;

    renderOutreachTable();

    // Templates
    document.getElementById("templatesTbody").innerHTML = (p.template_performance || []).map(t => `
      <tr>
        <td><strong>${esc(t.template_name)}</strong></td>
        <td class="num"><strong>${t.sent || 0}</strong></td>
        <td class="num">${t.unique_recipients || 0}</td>
        <td class="num">${t.delivered || 0}</td>
        <td class="num">${t.bounced || 0}</td>
        <td class="num">${t.replied || 0}</td>
        <td class="num">${t.delivery_rate_pct || 0}%</td>
        <td class="num">${t.bounce_rate_pct || 0}%</td>
        <td class="num">${t.reply_rate_pct || 0}%</td>
        <td class="num">${t.positive_replies || 0}</td>
        <td class="num">${t.neutral_replies || 0}</td>
        <td class="num">${t.negative_replies || 0}</td>
      </tr>
    `).join("");

    // Company Rankings
    const byWkComp = (p.company_rankings || {}).by_week || {};
    document.getElementById("compBenchTbody").innerHTML = Object.keys(byWkComp).sort().map(wk => {
      const b = byWkComp[wk];
      const dlt = b.avg_score_change_vs_prev == null ? "Baseline" : ((b.avg_score_change_vs_prev >= 0 ? "+" : "") + b.avg_score_change_vs_prev);
      return `
        <tr>
          <td><strong>${esc(b.week_period)}</strong></td>
          <td class="num">${b.total_companies}</td>
          <td class="num">${b.qualified_companies}</td>
          <td class="num">${b.non_qualified_companies}</td>
          <td class="num">${b.qualification_rate_pct}%</td>
          <td class="num">${b.avg_icp_score}</td>
          <td class="num">${esc(dlt)}</td>
          <td><strong>${esc(b.top_company)}</strong></td>
          <td class="num">${b.top_score}</td>
          <td class="num">${b.returning_companies_vs_prev} / ${b.new_companies_count}</td>
        </tr>
      `;
    }).join("") || `<tr><td colspan="10">No company benchmarks.</td></tr>`;
    renderCompanyTable();

    // Conference Scraping
    const byWkScrap = (p.conference_scraping || {}).by_week || {};
    document.getElementById("scrapSumTbody").innerHTML = Object.keys(byWkScrap).sort().map(wk => {
      const w = byWkScrap[wk];
      const ver = (w.verified_emails_speakers||0)+(w.verified_emails_attendees||0)+(w.verified_emails_exhibitors||0);
      const inds = (w.top_industries || []).slice(0,4).map(x => `${x.industry} (${x.count})`).join(", ");
      return `
        <tr>
          <td><strong>${esc(w.week_start)} to ${esc(w.week_end)}</strong></td>
          <td class="num">${w.total_conferences}</td>
          <td class="num">${w.total_speakers}</td>
          <td class="num">${w.total_attendees}</td>
          <td class="num">${w.total_exhibitors}</td>
          <td class="num"><strong>${w.total_contacts}</strong></td>
          <td class="num">${ver}</td>
          <td>${esc(inds)}</td>
        </tr>
      `;
    }).join("") || `<tr><td colspan="8">No conference summary.</td></tr>`;
    renderConfTable();
  }

  function renderOutreachTable() {
    if (!CURRENT_PAYLOAD) return;
    const q = (document.getElementById("outSearch").value || "").toLowerCase();
    const st = document.getElementById("outStatusFilter").value;
    const tm = document.getElementById("outTemplateFilter").value;
    const tr = document.getElementById("outTierFilter").value;
    const recs = (CURRENT_PAYLOAD.email_outreach || {}).records || [];
    FILTERED_OUTREACH = recs.filter(r => {
      if (q) {
        const hay = `${r.recipient_name} ${r.recipient_email} ${r.company_name} ${r.conference_name} ${r.subject}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (st === "Replied" && !r.replied) return false;
      if ((st === "Delivered" || st === "Bounced") && r.delivery_status !== st) return false;
      if (tm && r.template_used !== tm) return false;
      if (tr && r.lead_classification !== tr) return false;
      return true;
    });
    document.getElementById("outreachCountLabel").textContent = `Showing ${FILTERED_OUTREACH.length} of ${recs.length} emails`;
    document.getElementById("outreachTbody").innerHTML = FILTERED_OUTREACH.map((r, i) => `
      <tr>
        <td><div>${esc(r.sent_date)}</div><div class="small-muted">${esc((r.sent_at||"").slice(11,16))}</div></td>
        <td><strong>${esc(r.recipient_name)}</strong><div class="small-muted">${esc(r.recipient_email)}</div></td>
        <td><div>${esc(r.conference_name)}</div><div class="small-muted">${esc(r.company_name)} · ${esc(r.contact_role)}</div></td>
        <td><span class="badge ${r.lead_classification === 'Qualified' ? 'badge-green' : 'badge-amber'}">${esc(r.lead_classification)}</span><div class="small-muted">ICP ${r.icp_score != null ? r.icp_score : "—"}</div></td>
        <td><span class="badge badge-slate">${esc(r.template_used)}</span></td>
        <td><span class="badge ${r.delivery_status === 'Bounced' ? 'badge-red' : 'badge-green'}">${esc(r.delivery_status)}</span></td>
        <td>${r.replied ? `<span class="badge badge-blue">Replied (${esc(r.reply_sentiment)})</span>` : `<span class="small-muted">${esc(r.reply_status)}</span>`}</td>
        <td><div class="msg-snippet" title="${esc(r.subject)}">${esc(r.subject || r.message_sent)}</div></td>
        <td><button class="btn btn-secondary btn-sm btn-view-email" data-idx="${i}" type="button">Inspect</button></td>
      </tr>
    `).join("") || `<tr><td colspan="9">No matching outreach records.</td></tr>`;
  }

  document.getElementById("outreachTbody").addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-view-email");
    if (!btn) return;
    const r = FILTERED_OUTREACH[Number(btn.dataset.idx)];
    if (!r) return;
    let html = `
      <p><strong>Recipient:</strong> ${esc(r.recipient_name)} (&lt;${esc(r.recipient_email)}&gt;) · <strong>Role:</strong> ${esc(r.contact_role)}<br>
      <strong>Company:</strong> ${esc(r.company_name)} · <strong>Conference:</strong> ${esc(r.conference_name)}<br>
      <strong>Week:</strong> ${esc(r.week_id)} · <strong>Sent At:</strong> ${esc(r.sent_at)}<br>
      <strong>Tier / Score:</strong> ${esc(r.lead_classification)} (${r.icp_score != null ? r.icp_score : "—"}) · <strong>Template:</strong> ${esc(r.template_used)}<br>
      <strong>Delivery:</strong> ${esc(r.delivery_status)} · <strong>Reply Status:</strong> ${esc(r.reply_status)}</p>
    `;
    if (r.bounce_reason) {
      html += `<h4 style="color:#991b1b;margin:10px 0 4px;">SMTP Bounce Reason (NDR)</h4><pre class="email-pre">${esc(r.bounce_reason)}</pre>`;
    }
    if (r.reply_details) {
      html += `<h4 style="color:#1e40af;margin:10px 0 4px;">Received Reply (${esc(r.reply_sentiment)} / ${esc(r.reply_intent)} — ${esc(r.reply_received_at)})</h4><pre class="email-pre">${esc(r.reply_details)}</pre>`;
    }
    html += `<h4 style="margin:10px 0 4px;">Exact Message Sent</h4><pre class="email-pre">${esc(r.message_sent)}</pre>`;
    openModal(`Email Audit — ${r.recipient_name}`, html);
  });

  function renderCompanyTable() {
    if (!CURRENT_PAYLOAD) return;
    const q = (document.getElementById("compSearch").value || "").toLowerCase();
    const tr = document.getElementById("compTierFilter").value;
    const recs = (CURRENT_PAYLOAD.company_rankings || {}).records || [];
    const filtered = recs.filter(c => {
      if (q) {
        const hay = `${c.company_name} ${c.company_domain} ${c.primary_industry} ${c.associated_conference}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      if (tr && c.classification !== tr) return false;
      return true;
    });
    document.getElementById("compCountLabel").textContent = `Showing ${filtered.length} ranked entries`;
    document.getElementById("compTbody").innerHTML = filtered.map(c => {
      const site = safeUrl(c.official_website);
      return `
        <tr>
          <td><span class="small-muted">${esc(c.week_period)}</span></td>
          <td class="num"><strong>#${c.rank}</strong></td>
          <td><span class="badge badge-slate">${esc(c.rank_change_display)}</span></td>
          <td><strong>${esc(c.company_name)}</strong><div class="small-muted">${site ? `<a href="${esc(site)}" target="_blank" rel="noopener">${esc(c.company_domain || site)}</a>` : esc(c.company_domain)}</div></td>
          <td>${esc(c.primary_industry)}</td>
          <td>${esc(c.headcount_tier)}</td>
          <td class="num"><strong>${c.icp_score}</strong></td>
          <td>${esc(c.qualification_status)}</td>
          <td><span class="badge ${c.classification === 'Qualified' ? 'badge-green' : 'badge-amber'}">${esc(c.classification)}</span></td>
          <td>${esc(c.associated_conference)}</td>
        </tr>
      `;
    }).join("") || `<tr><td colspan="10">No companies matching filter.</td></tr>`;
  }

  function renderConfTable() {
    if (!CURRENT_PAYLOAD) return;
    const q = (document.getElementById("confSearch").value || "").toLowerCase();
    const confs = (CURRENT_PAYLOAD.conference_scraping || {}).conferences || [];
    FILTERED_CONFS = confs.filter(c => {
      if (!q) return true;
      const hay = `${c.conference_name} ${c.industry} ${c.location} ${c.official_website}`.toLowerCase();
      return hay.includes(q);
    });
    document.getElementById("confCountLabel").textContent = `Showing ${FILTERED_CONFS.length} conferences`;
    document.getElementById("confTbody").innerHTML = FILTERED_CONFS.map((c, idx) => {
      const url = safeUrl(c.official_website);
      return `
        <tr>
          <td><span class="small-muted">${esc(c.week_id.replace("WEEK-",""))}</span></td>
          <td>${esc(c.start_date)}${c.end_date && c.end_date !== c.start_date ? " → " + esc(c.end_date) : ""}</td>
          <td><strong>${esc(c.conference_name)}</strong><div class="small-muted">${esc(c.conference_id)}</div></td>
          <td>${esc(c.industry)}</td>
          <td>${esc(c.location)}</td>
          <td>${url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(url)}</a>` : esc(c.official_website)}</td>
          <td class="num">${c.speakers_count}</td>
          <td class="num">${c.attendees_count}</td>
          <td class="num">${c.exhibitors_count}</td>
          <td><button class="btn btn-secondary btn-sm btn-view-conf" data-idx="${idx}" type="button">Contacts (${c.speakers_count + c.attendees_count + c.exhibitors_count})</button></td>
        </tr>
      `;
    }).join("") || `<tr><td colspan="10">No conferences matching filter.</td></tr>`;
  }

  document.getElementById("confTbody").addEventListener("click", (e) => {
    const btn = e.target.closest(".btn-view-conf");
    if (!btn) return;
    const c = FILTERED_CONFS[Number(btn.dataset.idx)];
    if (!c) return;
    let html = `<p><strong>Conference:</strong> ${esc(c.conference_name)} (${esc(c.start_date)} to ${esc(c.end_date)})<br><strong>Industry:</strong> ${esc(c.industry)} · <strong>Location:</strong> ${esc(c.location)}</p>`;
    const renderList = (title, items, isExh) => {
      if (!items || !items.length) return `<p class="small-muted"><strong>${title}:</strong> None collected / not publicly listed</p>`;
      return `<h4>${title} (${items.length})</h4><ul>` + items.map(it => {
        if (isExh) {
          return `<li><strong>${esc(it.company_name)}</strong>${it.contact_person ? " — " + esc(it.contact_person) : ""}${it.email ? " (" + esc(it.email) + ")" : ""}${it.booth_number ? " · Booth " + esc(it.booth_number) : ""}</li>`;
        }
        return `<li><strong>${esc(it.name)}</strong>${it.job_title ? " — " + esc(it.job_title) : ""}${it.company ? " @ " + esc(it.company) : ""}${it.email ? " (" + esc(it.email) + ")" : ""}</li>`;
      }).join("") + `</ul>`;
    };
    html += renderList("Speakers", c.speakers, false);
    html += renderList("Attendees", c.attendees, false);
    html += renderList("Exhibitors", c.exhibitors, true);
    openModal(`Conference Contacts — ${c.conference_name}`, html);
  });

  function renderArchives() {
    document.getElementById("archivesTbody").innerHTML = (CURRENT_ARCHIVES || []).map(a => {
      const s = a.summary || {};
      const o = s.outreach || {};
      const cr = s.company_rankings || {};
      const cs = s.conference_scraping || {};
      return `
        <tr>
          <td><strong>${esc(a.week_start)} to ${esc(a.week_end)}</strong><div class="small-muted">${esc(a.week_id)}</div></td>
          <td>v${a.snapshot_version} ${a.is_baseline ? '<span class="badge badge-blue">Baseline</span>' : ''}</td>
          <td><span class="badge ${a.is_sealed ? 'badge-green' : 'badge-amber'}">${a.is_sealed ? 'Sealed Immutable' : 'Active Week'}</span></td>
          <td>Sent ${o.sent||0} / Deliv ${o.delivered||0} / Reply ${o.replied||0} · ${cr.total_ranked_entries||0} Cos · ${cs.total_conferences||0} Confs</td>
          <td>${esc((a.updated_at || a.generated_at || "").replace("T"," ").slice(0,19))} UTC</td>
          <td>
            <a class="btn btn-excel btn-sm" href="${esc(a.download_xlsx)}">Excel (${a.xlsx_size_kb} KB)</a>
            <a class="btn btn-pdf btn-sm" href="${esc(a.download_pdf)}">PDF (${a.pdf_size_kb} KB)</a>
          </td>
        </tr>
      `;
    }).join("") || `<tr><td colspan="6">No archived weekly snapshots yet. Click 'Sync Live Now' to initialize archives.</td></tr>`;
  }

  async function loadData(refresh = false) {
    const wk = document.getElementById("weekSelector").value || "ALL";
    const btn = document.getElementById("btnRefresh");
    btn.disabled = true;
    btn.textContent = refresh ? "Syncing..." : "Refreshing...";
    try {
      if (refresh) {
        await fetch("/api/reporting/refresh?sync_outlook=true", { method: "POST" });
      }
      const [sumRes, archRes] = await Promise.all([
        fetch("/api/reporting/summary?week_id=" + encodeURIComponent(wk)),
        fetch("/api/reporting/archives"),
      ]);
      CURRENT_PAYLOAD = await sumRes.json();
      const archData = await archRes.json();
      CURRENT_ARCHIVES = archData.archives || [];
      renderDashboard();
      renderArchives();
    } catch (err) {
      console.error("Failed loading report:", err);
      document.getElementById("metaLine").textContent = "Error loading report data: " + err.message;
    } finally {
      btn.disabled = false;
      btn.textContent = "Sync Live Now";
    }
  }

  document.getElementById("weekSelector").addEventListener("change", () => loadData(false));
  document.getElementById("btnRefresh").addEventListener("click", () => loadData(true));
  ["outSearch", "outStatusFilter", "outTemplateFilter", "outTierFilter"].forEach(id => {
    document.getElementById(id).addEventListener("input", renderOutreachTable);
    document.getElementById(id).addEventListener("change", renderOutreachTable);
  });
  ["compSearch", "compTierFilter"].forEach(id => {
    document.getElementById(id).addEventListener("input", renderCompanyTable);
    document.getElementById(id).addEventListener("change", renderCompanyTable);
  });
  document.getElementById("confSearch").addEventListener("input", renderConfTable);

  loadData(false);
  setInterval(() => loadData(false), 60000);
})();
</script>
</body>
</html>
"""


@router.get("/reports", response_class=HTMLResponse)
@router.get("/reports/", response_class=HTMLResponse)
@router.get("/api/reporting/dashboard", response_class=HTMLResponse)
def serve_reporting_dashboard():
    return HTMLResponse(content=_DASHBOARD_HTML)

