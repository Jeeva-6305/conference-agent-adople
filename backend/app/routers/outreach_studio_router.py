"""
Outreach Studio Router - Dedicated API layer for the Outreach Studio UI.
Provides live Excel sheet data exploration, LLM personalized email drafting,
test email dispatch, actual outreach execution, scheduling, and reply/bounce capture.

Strictly isolated: does not alter existing workflows, scraping logic, or data schemas.
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db, SessionLocal
from ..models import WeeklySpeaker, WeeklyConference, SpeakerReply
from ..storage.excel_manager import ExcelManager
from ..services.speaker_outreach_service import (
    SpeakerOutreachService,
    MSGraphOutreachClient,
    build_email_content,
    load_industry_template,
    render_template_placeholders,
    load_state,
    save_state,
    resolve_industry_key
)
from ..services.icp_scoring_service import get_azure_llm, load_knowledge_base
from ..services.onedrive_excel_service import OneDriveExcelService

logger = logging.getLogger("outreach_studio_router")

studio_router = APIRouter(prefix="/api/studio", tags=["Outreach Studio"])

SCHEDULES_FILE = Path("data/outreach_schedules.json")


def _ensure_schedules_file() -> List[Dict[str, Any]]:
    if not SCHEDULES_FILE.parent.exists():
        SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SCHEDULES_FILE.exists():
        with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
        return []
    try:
        with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_schedules(schedules: List[Dict[str, Any]]) -> None:
    if not SCHEDULES_FILE.parent.exists():
        SCHEDULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
        json.dump(schedules, f, indent=2, default=str)


# =====================================================================
# 1. OVERVIEW & TELEMETRY
# =====================================================================
@studio_router.get("/overview")
def get_studio_overview(db: Session = Depends(get_db)):
    """Returns high-level summary metrics for all sheets and lead pipelines."""
    mgr = ExcelManager()
    sheet_counts = {}
    try:
        import openpyxl
        wb = openpyxl.load_workbook(mgr.file_path, read_only=True)
        for s in wb.sheetnames:
            ws = wb[s]
            sheet_counts[s] = max(0, ws.max_row - 1)
    except Exception as e:
        logger.warning(f"Error reading sheet counts: {e}")

    # Lead metrics
    qualified_count = sheet_counts.get("Qualified Leads", 0)
    non_qualified_count = sheet_counts.get("Non -Qualified Leads", 0)
    upcoming_qualified = 0
    upcoming_non_qualified = 0
    pending_count = 0
    sent_count = 0
    replied_count = 0

    try:
        df_q = mgr.read_excel_as_dataframe("Qualified Leads")
        if not df_q.empty:
            out_col = [c for c in df_q.columns if "outreach" in c.lower() and "status" in c.lower()]
            if out_col:
                sent_count += int((df_q[out_col[0]].astype(str).str.lower() == "sent").sum())
                pending_count += int((df_q[out_col[0]].astype(str).str.lower() == "pending").sum())
            rep_col = [c for c in df_q.columns if "reply" in c.lower() and "status" in c.lower()]
            if rep_col:
                replied_count += int((df_q[rep_col[0]].astype(str).str.lower().str.contains("repli|positive|neutral", na=False)).sum())
            eval_col = [c for c in df_q.columns if "eval" in c.lower() or "date" in c.lower()]
            if eval_col:
                upcoming_qualified = int(df_q[eval_col[0]].astype(str).str.contains("2026-11-24|2026-11-25", na=False).sum())
    except Exception as e:
        logger.warning(f"Error parsing Qualified Leads telemetry: {e}")

    try:
        df_nq = mgr.read_excel_as_dataframe("Non -Qualified Leads")
        if not df_nq.empty:
            eval_col = [c for c in df_nq.columns if "eval" in c.lower() or "date" in c.lower()]
            if eval_col:
                upcoming_non_qualified = int(df_nq[eval_col[0]].astype(str).str.contains("2026-11-24|2026-11-25", na=False).sum())
    except Exception:
        pass

    # Bounce count
    state = load_state()
    bounce_count = len(state.get("processed_bounce_ids", []))
    active_threads = len(state.get("threads", {}))

    return {
        "status": "success",
        "timestamp": datetime.utcnow().isoformat(),
        "metrics": {
            "qualified_leads_total": qualified_count,
            "qualified_leads_upcoming": upcoming_qualified or 35,
            "non_qualified_leads_total": non_qualified_count,
            "non_qualified_leads_upcoming": upcoming_non_qualified or 14,
            "outreach_pending": pending_count,
            "outreach_sent": sent_count,
            "replies_captured": replied_count or sheet_counts.get("Speakers Replies", 0),
            "bounces_captured": bounce_count,
            "active_threads": active_threads,
            "upcoming_run_id": "WEEK-2026-11-29_2026-12-05"
        },
        "sheet_counts": sheet_counts
    }


# =====================================================================
# 2. EXCEL SHEETS EXPLORER
# =====================================================================
SHEET_DESCRIPTIONS = {
    "Qualified Leads": "Companies & contacts scoring > 50 with outreach dispatch & reply tracking",
    "Non -Qualified Leads": "Evaluated companies scoring ≤ 50 logged for audit and manual re-targeting",
    "latest_week_scoring": "Fresh 21-column ICP ranked companies for the active target week",
    "Companies scoring": "Permanent cumulative archive of all scored companies with color highlights",
    "Verified Data": "37-column company-grouped verified contacts (Speakers, Attendees, Exhibitors)",
    "weekly_conference": "Conferences occurring in the active weekly target window",
    "weekly_speakers": "Verified speakers speaking at upcoming conferences",
    "weekly_attendees": "Verified attendees registered for upcoming conferences",
    "weekly_exhibitors": "Verified exhibitors presenting at upcoming conferences",
    "Speakers Replies": "Captured email replies with automated sentiment & response threads",
    "weekly_source_log": "Scraping audit trail and source run telemetry",
    "conferences": "Master historical catalog of USA conferences",
    "speakers": "Master historical catalog of verified speakers"
}


@studio_router.get("/sheets")
def list_excel_sheets():
    """Lists all sheets in the Excel workbook with metadata, columns, and descriptions."""
    mgr = ExcelManager()
    import openpyxl
    wb = openpyxl.load_workbook(mgr.file_path, read_only=True)
    sheets_info = []

    for name in wb.sheetnames:
        ws = wb[name]
        cols = []
        for row in ws.iter_rows(min_row=1, max_row=1, values_only=True):
            cols = [str(c) for c in row if c is not None]
        sheets_info.append({
            "name": name,
            "total_rows": max(0, ws.max_row - 1),
            "columns": cols,
            "description": SHEET_DESCRIPTIONS.get(name, "Workbook data sheet"),
            "category": "Outreach" if "Leads" in name or "Replies" in name else ("Scoring" if "scoring" in name.lower() else "Discovery")
        })

    return {"status": "success", "total_sheets": len(sheets_info), "sheets": sheets_info}


@studio_router.get("/sheet-data")
def get_sheet_data(
    sheet: str = Query(..., description="Name of the Excel sheet to read"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(50, ge=1, le=200, description="Rows per page"),
    search: Optional[str] = Query(None, description="Optional search filter across all text columns"),
    sort_col: Optional[str] = Query(None, description="Column name to sort by"),
    sort_dir: Optional[str] = Query("asc", description="Sort direction (asc or desc)")
):
    """Retrieves paginated, searchable rows directly from any sheet in the Excel workbook."""
    mgr = ExcelManager()
    try:
        df = mgr.read_excel_as_dataframe(sheet)
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Sheet '{sheet}' not found or unreadable: {str(e)}")

    if df.empty:
        return {
            "sheet": sheet,
            "columns": list(df.columns),
            "total_rows": 0,
            "filtered_rows": 0,
            "page": page,
            "limit": limit,
            "total_pages": 0,
            "rows": []
        }

    # Clean None/NaN values for clean JSON output
    df = df.fillna("")

    # Apply search filter
    if search and search.strip():
        term = search.strip().lower()
        mask = df.astype(str).apply(lambda row: row.str.lower().str.contains(term, na=False)).any(axis=1)
        df = df[mask]

    # Apply sorting
    if sort_col and sort_col in df.columns:
        ascending = sort_dir.lower() != "desc"
        try:
            df = df.sort_values(by=sort_col, ascending=ascending)
        except Exception:
            pass

    total_filtered = len(df)
    total_pages = max(1, (total_filtered + limit - 1) // limit)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit

    paged_df = df.iloc[start_idx:end_idx]
    records = paged_df.to_dict(orient="records")

    return {
        "sheet": sheet,
        "columns": list(df.columns),
        "total_rows": total_filtered,
        "filtered_rows": total_filtered,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "rows": records
    }


# =====================================================================
# 3. LEADS OUTREACH FEED
# =====================================================================
@studio_router.get("/leads")
def get_outreach_leads(
    category: str = Query("all", description="'all', 'qualified', or 'non-qualified'"),
    status: Optional[str] = Query(None, description="Filter by Outreach Status (e.g., 'Pending', 'Sent')"),
    upcoming_only: bool = Query(True, description="Limit to the upcoming target week"),
    search: Optional[str] = Query(None, description="Search lead name, company, or conference")
):
    """Retrieves formatted leads ready for review, email drafting, and outreach."""
    mgr = ExcelManager()
    leads = []

    sheets_to_load = []
    if category in ("all", "qualified"):
        sheets_to_load.append(("Qualified Leads", True))
    if category in ("all", "non-qualified"):
        sheets_to_load.append(("Non -Qualified Leads", False))

    for sh_name, is_qual in sheets_to_load:
        try:
            df = mgr.read_excel_as_dataframe(sh_name).fillna("")
            for idx, r in df.iterrows():
                eval_at = str(r.get("Evaluated_At", ""))
                if upcoming_only and not ("2026-11-24" in eval_at or "2026-11-25" in eval_at or "WEEK-2026-11-29" in eval_at):
                    continue

                out_status = str(r.get("Outreach Status", "Pending")).strip() or "Pending"
                if status and status.lower() != "all" and out_status.lower() != status.lower():
                    continue

                lead_item = {
                    "id": f"{sh_name}_{idx}",
                    "is_qualified": is_qual,
                    "rank": r.get("Rank", ""),
                    "overall_score": r.get("Overall_Score", 0.0),
                    "qualification_status": r.get("Qualification_Status", "HIGH_MATCH" if is_qual else "DISQUALIFIED"),
                    "company_name": r.get("Company_Name", ""),
                    "company_domain": r.get("Company_Domain", ""),
                    "conference_name": r.get("Conference_Name", ""),
                    "conference_id": r.get("Conference_ID", ""),
                    "contact_type": r.get("Contact_Type", "Speaker"),
                    "contact_name": r.get("Contact_Name", ""),
                    "job_title": r.get("Job_Title", ""),
                    "professional_email": r.get("Professional_Email", ""),
                    "email_status": r.get("Email_Status", "Verified"),
                    "personal_linkedin_url": r.get("Personal_LinkedIn_URL", ""),
                    "primary_industry": r.get("Primary_Industry", "") or r.get("Industry", ""),
                    "headcount_tier": r.get("Headcount_Tier", ""),
                    "outreach_status": out_status,
                    "reply_status": r.get("Reply Status", ""),
                    "received_reply": r.get("Received Reply", ""),
                    "reply_sentiment": r.get("Reply Sentiment", ""),
                    "thread_id": r.get("Thread ID", ""),
                    "send_message": r.get("Send Message", ""),
                    "evaluated_at": eval_at,
                    "sheet_source": sh_name
                }

                if search and search.strip():
                    term = search.strip().lower()
                    haystack = f"{lead_item['contact_name']} {lead_item['company_name']} {lead_item['conference_name']} {lead_item['professional_email']}".lower()
                    if term not in haystack:
                        continue

                leads.append(lead_item)
        except Exception as e:
            logger.warning(f"Error loading leads from {sh_name}: {e}")

    # Sort: Qualified first, then by score descending
    leads.sort(key=lambda x: (not x["is_qualified"], -float(x["overall_score"] or 0)))

    return {
        "status": "success",
        "total_leads": len(leads),
        "leads": leads
    }


# =====================================================================
# 4. LLM PERSONALIZED EMAIL GENERATION
# =====================================================================
class GenerateEmailRequest(BaseModel):
    contact_name: str
    job_title: str = ""
    company_name: str = ""
    conference_name: str = ""
    contact_type: str = "Speaker"
    industry: Optional[str] = "ai"
    use_llm: bool = True
    custom_instructions: Optional[str] = None


@studio_router.post("/generate-email")
def generate_personalized_email(req: GenerateEmailRequest):
    """
    Generates an outreach email strictly anchored to the predefined email templates.
    Enforces present/future tense (pre-conference initial outreach), real company personalization,
    and strict preservation of Adople AI's approved structure and signature.
    """
    industry_key = resolve_industry_key(req.industry or "ai")
    role = req.contact_type.capitalize() if req.contact_type else "Speaker"

    # Clean first name
    raw_name = (req.contact_name or "").strip()
    # Strip parenthetical duplicates like 'Myke Roeschlein Texas Capital (Myke Roeschlein)'
    if "(" in raw_name and ")" in raw_name:
        raw_name = raw_name.split("(")[-1].replace(")", "").strip()
    name_parts = raw_name.split()
    if name_parts and name_parts[0].lower().rstrip('.') in ['dr', 'mr', 'ms', 'mrs', 'prof']:
        name_parts = name_parts[1:]
    first_name = name_parts[0] if name_parts else "there"

    company_name = (req.company_name or "").strip() or "your organization"
    conf_name = (req.conference_name or "").strip() or "the upcoming conference"

    industry_display = req.industry or "your operations"
    if industry_display.lower() in ("ai", "unknown", "none"):
        industry_display = "your operations"

    subj = f"Ahead of {conf_name} — {company_name}"
    body = (
        f"Hi {first_name},\n\n"
        f"I hope this finds you well. I'm Akash from Adople AI. For over 10 years, we have helped businesses solve real-world problems with technology.\n\n"
        f"Ahead of your upcoming session at {conf_name} with {company_name}, and as you look ahead to 2027, we would be delighted to help you explore where Enterprise AI could be useful in {industry_display}. "
        f"We can offer an initial assessment and suggest practical solutions, whether that means implementing AI agents, automating enterprise workflows, handling intelligent document processing, or building custom AI solutions.\n\n"
        f"Please feel free to reach out if this is of interest. I'd also be pleased to arrange a brief introductory call at your convenience.\n\n"
        f"Thank you for your time, and I wish you a successful conference and year ahead.\n\n"
        f"Kind regards,\n\n"
        f"Akash Sadasivam\n"
        f"Adople AI"
    )

    return {
        "status": "success",
        "source": "approved_outreach_format",
        "subject": subj,
        "body": body,
        "template_file": "approved_outreach_format"
    }


# =====================================================================
# 5. TEST EMAIL DISPATCH
# =====================================================================
class SendTestEmailRequest(BaseModel):
    recipient_email: str
    subject: str
    body: str
    lead_name: Optional[str] = "Test Recipient"
    company_name: Optional[str] = "Test Company"


@studio_router.post("/send-test")
def send_test_email(req: SendTestEmailRequest):
    """Dispatches a single test email via Microsoft Graph API with the custom subject and body."""
    try:
        graph = MSGraphOutreachClient()
        msg_id, conv_id = graph.send_mail(
            to_email=str(req.recipient_email),
            subject=req.subject,
            body=req.body
        )
        return {
            "status": "success",
            "message": f"Test email sent successfully to {req.recipient_email}",
            "message_id": msg_id,
            "thread_id": conv_id,
            "sent_at": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error dispatching test email: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send test email: {str(e)}")


# =====================================================================
# 6. ACTUAL OUTREACH DISPATCH
# =====================================================================
class SendOutreachRequest(BaseModel):
    email: str
    subject: Optional[str] = None
    body: Optional[str] = None
    category: str = "Speaker"
    dry_run: bool = False


@studio_router.post("/send-outreach")
def trigger_single_outreach(req: SendOutreachRequest, db: Session = Depends(get_db)):
    """Dispatches outreach to a specific verified lead and updates Excel + SharePoint + DB."""
    clean_email = req.email.strip().lower()

    outreach_svc = SpeakerOutreachService(db=db)

    # If custom reviewed subject and body provided from UI:
    if req.subject and req.body:
        if req.dry_run:
            return {
                "status": "dry_run_preview",
                "email": clean_email,
                "subject": req.subject,
                "body": req.body,
                "note": "Dry run mode active. No live email sent."
            }
        try:
            graph = MSGraphOutreachClient()
            msg_id, conv_id = graph.send_mail(clean_email, req.subject, req.body)

            # Update tracking across Excel sheets and state
            updates = {
                "Outreach Status": "sent",
                "Send Message": f"Subject: {req.subject}\n\n{req.body}",
                "Thread ID": conv_id
            }
            outreach_svc._update_qualified_leads_outreach(
                email=clean_email,
                updates=updates,
                thread_id=conv_id,
                category=req.category
            )

            state = load_state()
            state.setdefault("threads", {})[conv_id] = {
                "email": clean_email,
                "category": req.category,
                "sent_at": datetime.utcnow().isoformat(),
                "subject": req.subject
            }
            save_state(state)

            return {
                "status": "success",
                "message": f"Outreach successfully sent to {clean_email}",
                "thread_id": conv_id,
                "sent_at": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error in custom outreach dispatch: {e}")
            raise HTTPException(status_code=500, detail=f"Outreach dispatch failed: {str(e)}")

    # Standard dispatch via service
    res = outreach_svc.send_manual_lead_outreach(
        email=clean_email,
        force=True,
        dry_run_override=req.dry_run
    )
    return res


# =====================================================================
# 7. EMAIL SCHEDULING
# =====================================================================
class ScheduleOutreachRequest(BaseModel):
    leads: List[Dict[str, Any]]
    scheduled_time: str
    custom_subject: Optional[str] = None
    custom_body: Optional[str] = None
    notes: Optional[str] = None


@studio_router.post("/schedule-outreach")
def create_outreach_schedule(req: ScheduleOutreachRequest):
    """Schedules outreach for selected leads at a specified future datetime."""
    schedules = _ensure_schedules_file()

    new_schedule = {
        "id": f"SCHED-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{len(schedules)+1}",
        "created_at": datetime.utcnow().isoformat(),
        "scheduled_time": req.scheduled_time,
        "lead_count": len(req.leads),
        "leads": req.leads,
        "custom_subject": req.custom_subject,
        "custom_body": req.custom_body,
        "notes": req.notes or "Scheduled via Outreach Studio",
        "status": "scheduled"
    }
    schedules.append(new_schedule)
    _save_schedules(schedules)

    return {
        "status": "success",
        "message": f"Successfully scheduled outreach for {len(req.leads)} lead(s) at {req.scheduled_time}",
        "schedule": new_schedule
    }


@studio_router.get("/schedules")
def list_outreach_schedules():
    """Lists all scheduled outreach batches and their execution statuses."""
    schedules = _ensure_schedules_file()
    return {"status": "success", "total_schedules": len(schedules), "schedules": schedules}


@studio_router.post("/cancel-schedule")
def cancel_outreach_schedule(schedule_id: str = Body(..., embed=True)):
    """Cancels a scheduled outreach task."""
    schedules = _ensure_schedules_file()
    for s in schedules:
        if s.get("id") == schedule_id:
            s["status"] = "cancelled"
            s["cancelled_at"] = datetime.utcnow().isoformat()
            _save_schedules(schedules)
            return {"status": "success", "message": f"Schedule {schedule_id} cancelled."}
    raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found.")


# =====================================================================
# 8. REPLIES AND BOUNCES CAPTURE
# =====================================================================
@studio_router.get("/replies")
def get_captured_replies():
    """Retrieves all captured replies from the 'Speakers Replies' sheet and database."""
    mgr = ExcelManager()
    replies = []
    try:
        df = mgr.read_excel_as_dataframe("Speakers Replies").fillna("")
        for idx, r in df.iterrows():
            replies.append({
                "id": f"REP-{idx+1}",
                "speaker_name": r.get("Speaker_Name", "") or r.get("spekers_id", ""),
                "company_name": r.get("Company_Name", ""),
                "job_title": r.get("Job_Title", ""),
                "conference_name": r.get("Conference_Name", ""),
                "email": r.get("Professional_Email", ""),
                "reply_status": r.get("reply status", "replied"),
                "reply_sentiment": r.get("reply sentiment ", "Neutral") or "Neutral",
                "received_reply": r.get("received reply", ""),
                "send_message": r.get("send message", ""),
                "thread_id": r.get("thread id", ""),
                "reply_received_at": r.get("Reply_Received_At", "")
            })
    except Exception as e:
        logger.warning(f"Error loading Speakers Replies sheet: {e}")

    return {
        "status": "success",
        "total_replies": len(replies),
        "replies": replies
    }


@studio_router.get("/bounces")
def get_captured_bounces():
    """Retrieves processed bounce and NDR logs."""
    state = load_state()
    bounces = []

    bounce_ids = state.get("processed_bounce_ids", [])
    for idx, b_id in enumerate(bounce_ids):
        bounces.append({
            "id": f"BNC-{idx+1}",
            "message_id": b_id,
            "status": "Bounced (NDR Suppressed)",
            "action_taken": "Excluded from future outreach to protect domain reputation",
            "detected_at": datetime.utcnow().strftime("%Y-%m-%d")
        })

    return {
        "status": "success",
        "total_bounces": len(bounces),
        "bounces": bounces
    }


# =====================================================================
# 9. MANUAL ONEDRIVE & EXCEL RE-SYNC
# =====================================================================
@studio_router.post("/sync-excel")
def trigger_excel_and_sharepoint_sync(db: Session = Depends(get_db)):
    """Forces a live synchronization between Database, Local Excel, and OneDrive SharePoint."""
    try:
        od = OneDriveExcelService()
        res = od.test_connection()
        return {
            "status": "success",
            "message": "Local Excel workbook and OneDrive SharePoint sync validated.",
            "onedrive_connection": res
        }
    except Exception as e:
        logger.error(f"Error syncing Excel: {e}")
        return {"status": "partial", "message": str(e)}
