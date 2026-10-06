import os
import logging
from datetime import date, timedelta
from typing import List, Optional
from fastapi import FastAPI, Depends, Query, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db, init_db
from .models import Conference, Speaker, Attendee, EmailNotification, TeamsNotification
from .schemas import ConferenceResponse, SpeakerResponse, AttendeeResponse, DashboardStats
from .storage.excel_manager import ExcelManager
from .tasks.celery_app import (
    task_scrape_and_ingest,
    task_publish_2_days_before,
    cleanup_fake_and_sample_records,
    task_sync_to_google_sheets,
    task_migrate_db_to_google_sheets,
    task_send_conference_reminder_emails,
    task_send_teams_cards
)

from .tasks.scheduler import start_scheduler, stop_scheduler, get_scheduler_status



logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("main")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="24/7 AI-Powered USA Conference Discovery, Validation & 2-Day Excel Publication Engine"
)

# CORS configuration for Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    init_db()
    start_scheduler()
    db = next(get_db())
    # Clean up any fake, sample, or duplicate records from previous runs
    cleanup_fake_and_sample_records(db)
    # If no genuine T-2 conferences are present, run ingestion cycle in background
    if db.query(Conference).count() == 0:
        logger.info("Triggering genuine T-2 conference discovery & AI validation cycle in background...")
        import threading
        threading.Thread(target=task_scrape_and_ingest, daemon=True).start()

@app.on_event("shutdown")
def shutdown_event():
    stop_scheduler()

@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    count = db.query(Conference).count()
    return {
        "status": "healthy",
        "conferences_count": count,
        "database": "PostgreSQL",
        "excel_path": settings.EXCEL_OUTPUT_PATH,
        "excel_exists": os.path.exists(settings.EXCEL_OUTPUT_PATH)
    }

@app.get("/api/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    total = db.query(Conference).count()
    published = db.query(Conference).filter(Conference.is_published_to_excel == True).count()
    
    today = date.today()
    exact_2_days = today + timedelta(days=2)
    upcoming_2_days = db.query(Conference).filter(
        Conference.start_date == exact_2_days
    ).count()
    
    sched = get_scheduler_status()
    
    return DashboardStats(
        total_conferences=total,
        published_to_excel=published,
        upcoming_2_days=upcoming_2_days,
        sources_active=11,
        last_scrape_time=sched.get("last_scrape_time"),
        next_scrape_time=sched.get("next_scrape_time"),
        scheduler_interval=sched.get("interval_display", "Every 1 hour"),
        excel_path=settings.EXCEL_OUTPUT_PATH
    )

@app.get("/api/scheduler/status")
def get_scheduler_telemetry():
    """Live telemetry of the automated 1-hour scraping background job."""
    return get_scheduler_status()

@app.get("/api/conferences", response_model=List[ConferenceResponse])
def get_conferences(
    source: Optional[str] = Query(None, description="Filter by source (10times, luma, eventbrite, meetup, cvent, events_in_america)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search by title, speaker, or city"),
    published_only: Optional[bool] = Query(False, description="Filter only conferences published to Excel"),
    status: Optional[str] = Query(None, description="Filter by status (published, scheduled)"),
    db: Session = Depends(get_db)
):
    query = db.query(Conference)

    if source:
        query = query.filter(Conference.source_name.ilike(f"%{source}%"))
    if category:
        query = query.filter(Conference.industry_category.ilike(f"%{category}%"))
    if published_only:
        query = query.filter(Conference.is_published_to_excel == True)
    if status:
        query = query.filter(Conference.status == status)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Conference.conference_title.ilike(search_filter)) |
            (Conference.city.ilike(search_filter)) |
            (Conference.venue.ilike(search_filter))
        )

    return query.order_by(Conference.start_date.asc()).all()

@app.get("/api/conferences/{identifier}", response_model=ConferenceResponse)
def get_conference_detail(identifier: str, db: Session = Depends(get_db)):
    """Fetch complete verified details for a specific conference."""
    conf = None
    if identifier.isdigit():
        conf = db.query(Conference).filter(Conference.id == int(identifier)).first()
    if not conf:
        conf = db.query(Conference).filter(Conference.conference_id == identifier).first()
    if not conf:
        raise HTTPException(status_code=404, detail="Conference not found")
    return conf

@app.get("/api/speakers", response_model=List[SpeakerResponse])
def get_speakers(
    conference_id: Optional[str] = Query(None, description="Filter speakers by Conference ID"),
    published_only: Optional[bool] = Query(False, description="Filter speakers of published conferences"),
    db: Session = Depends(get_db)
):
    """Fetch verified speaker profiles extracted from official sources."""
    query = db.query(Speaker)
    if conference_id:
        query = query.filter(Speaker.conference_id == conference_id)
    elif published_only:
        today = date.today()
        exact_t2 = today + timedelta(days=2)
        pub_confs = db.query(Conference).filter(Conference.is_published_to_excel == True, Conference.start_date == exact_t2).all()
        pub_ids = [c.conference_id for c in pub_confs]
        query = query.filter(Speaker.conference_id.in_(pub_ids))
    return query.order_by(Speaker.conference_name.asc(), Speaker.speaker_name.asc()).all()

@app.get("/api/attendees", response_model=List[AttendeeResponse])
def get_attendees(
    conference_id: Optional[str] = Query(None, description="Filter attendees by Conference ID"),
    published_only: Optional[bool] = Query(False, description="Filter attendees of published conferences"),
    db: Session = Depends(get_db)
):
    """Fetch attendee and participant profile details."""
    query = db.query(Attendee)
    if conference_id:
        query = query.filter(Attendee.conference_id == conference_id)
    elif published_only:
        today = date.today()
        exact_t2 = today + timedelta(days=2)
        pub_confs = db.query(Conference).filter(Conference.is_published_to_excel == True, Conference.start_date == exact_t2).all()
        pub_ids = [c.conference_id for c in pub_confs]
        query = query.filter(Attendee.conference_id.in_(pub_ids))
    return query.order_by(Attendee.conference_name.asc()).all()

@app.post("/api/trigger/scrape")
def trigger_scrape(background_tasks: BackgroundTasks):
    """Manually triggers immediate 24/7 web scraping & AI extraction cycle."""
    background_tasks.add_task(task_scrape_and_ingest)
    return {"message": "Scrape and AI ingestion cycle triggered across all configured websites in background."}

@app.post("/api/trigger/publish")
def trigger_publish():
    """Manually triggers the 2-day Excel publication check."""
    result = task_publish_2_days_before()
    return result

@app.get("/api/excel/download")
def download_excel():
    excel_path = settings.EXCEL_OUTPUT_PATH
    if not os.path.exists(excel_path):
        raise HTTPException(status_code=404, detail="Excel file has not been generated yet.")
    return FileResponse(
        excel_path,
        filename="usa_conferences_published.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.get("/api/excel/preview")
def preview_excel(sheet: Optional[str] = Query("USA Conferences")):
    manager = ExcelManager()
    valid_sheets = ["USA Conferences", "Speakers", "Attendees"]
    if sheet not in valid_sheets:
        sheet = "USA Conferences"
    try:
        df = manager.read_excel_as_dataframe(sheet_name=sheet)
        records = df.fillna("").to_dict(orient="records")
        return {
            "sheet": sheet,
            "sheets": valid_sheets,
            "columns": list(df.columns),
            "total_rows": len(records),
            "rows": records
        }
    except Exception as e:
        logger.error(f"Error reading Excel sheet {sheet}: {e}")
        return {
            "sheet": sheet,
            "sheets": valid_sheets,
            "columns": [],
            "total_rows": 0,
            "rows": []
        }



@app.post("/api/trigger/google-sheets-sync")
def trigger_google_sheets_sync(background_tasks: BackgroundTasks):
    """Manually trigger Google Sheets sync for all conferences and speakers."""
    logger.info("Manual Google Sheets sync triggered")
    background_tasks.add_task(task_sync_to_google_sheets)
    return {
        "status": "sync_initiated",
        "message": "Google Sheets sync started in background",
        "endpoint": "/api/trigger/google-sheets-sync"
    }


@app.post("/api/trigger/google-sheets-migrate")
def trigger_google_sheets_migrate(background_tasks: BackgroundTasks, clear_first: bool = False):
    """Migrate entire database to Google Sheets (full migration)."""
    logger.info(f"Manual Google Sheets migration triggered (clear_first={clear_first})")
    background_tasks.add_task(task_migrate_db_to_google_sheets, clear_first=clear_first)
    return {
        "status": "migration_initiated",
        "message": "Google Sheets migration started in background",
        "endpoint": "/api/trigger/google-sheets-migrate"
    }


# =========================================================================
# EMAIL NOTIFICATION ENDPOINTS
# Recipient: jeevanandham@adople.ai
# Rule: Separate individual email for each matching conference
# =========================================================================

@app.post("/api/notifications/send-reminders")
def send_reminder_emails(
    recipient: Optional[str] = Query(None, description="Recipient email (defaults to jeevanandham@adople.ai)"),
    force: bool = Query(False, description="Resend even if already notified"),
    background_tasks: BackgroundTasks = None
):
    """
    Sends a separate individual email notification for each conference matching filtering criteria.
    - Destination: jeevanandham@adople.ai
    - Each conference has its own separate email (no bundling).
    - Prevents duplicate emails across scraping cycles and application restarts.
    """
    target_recipient = recipient or settings.NOTIFICATION_RECIPIENT_EMAIL
    logger.info(f"Triggering automated separate conference reminders for recipient: {target_recipient} (force={force})")
    result = task_send_conference_reminder_emails(recipient_email=target_recipient, force=force)
    return result


@app.get("/api/notifications/history")
def get_notification_history(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Returns persistent audit log of all sent conference reminder emails."""
    items = db.query(EmailNotification).order_by(EmailNotification.sent_at.desc()).limit(limit).all()
    return {
        "total_records": len(items),
        "recipient": settings.NOTIFICATION_RECIPIENT_EMAIL,
        "notifications": [item.to_dict() for item in items]
    }


@app.get("/api/notifications/preview/{conference_id}")
def preview_notification_email(
    conference_id: str,
    db: Session = Depends(get_db)
):
    """Renders live HTML preview of the conference reminder email layout."""
    from .services.email_service import ConferenceEmailService

    conf = db.query(Conference).filter(Conference.conference_id == conference_id).first()
    if not conf:
        raise HTTPException(status_code=404, detail=f"Conference '{conference_id}' not found.")

    speakers = db.query(Speaker).filter(Speaker.conference_id == conf.conference_id).all()
    attendee = db.query(Attendee).filter(Attendee.conference_id == conf.conference_id).first()

    service = ConferenceEmailService()
    html_content = service.build_html_body(conf, speakers, attendee)
    return HTMLResponse(content=html_content)


# =========================================================================
# MICROSOFT TEAMS WEBHOOK ENDPOINTS
# Power Automate Workflow Direct Integration
# Post card in a chat or channel -> Adaptive Card = triggerBody()
# =========================================================================

@app.post("/api/notifications/teams-webhook/send")
def trigger_teams_webhook(
    force: bool = Query(False, description="Resend cards even if already marked sent"),
    webhook_url: Optional[str] = Query(None, description="Custom Webhook URL override")
):
    """
    Sends Adaptive Cards for all matching published conferences to the Microsoft Teams Webhook.
    """
    logger.info(f"Triggering Teams webhook cards dispatch (force={force})...")
    result = task_send_teams_cards(force=force, webhook_url=webhook_url)
    return result


@app.get("/api/notifications/teams-webhook/history")
def get_teams_webhook_history(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Returns persistent audit log of all sent Microsoft Teams cards."""
    items = db.query(TeamsNotification).order_by(TeamsNotification.sent_at.desc()).limit(limit).all()
    return {
        "total_records": len(items),
        "webhook_url": settings.TEAMS_WEBHOOK_URL,
        "notifications": [item.to_dict() for item in items]
    }


@app.get("/api/notifications/teams-webhook/preview/{conference_id}")
def preview_teams_adaptive_card(
    conference_id: str,
    db: Session = Depends(get_db)
):
    """Returns the exact Adaptive Card JSON payload rendered for Microsoft Teams."""
    from .services.teams_service import TeamsWebhookService

    conf = db.query(Conference).filter(Conference.conference_id == conference_id).first()
    if not conf:
        raise HTTPException(status_code=404, detail=f"Conference '{conference_id}' not found.")

    speakers = db.query(Speaker).filter(Speaker.conference_id == conf.conference_id).all()
    attendee = db.query(Attendee).filter(Attendee.conference_id == conf.conference_id).first()

    service = TeamsWebhookService()
    card = service.build_adaptive_card(conf, speakers, attendee)
    return card


