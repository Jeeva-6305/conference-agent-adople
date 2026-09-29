import os
import logging
from datetime import date, timedelta
from typing import List, Optional
from fastapi import FastAPI, Depends, Query, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db, init_db
from .models import Conference, Speaker
from .schemas import ConferenceResponse, SpeakerResponse, DashboardStats
from .storage.excel_manager import ExcelManager
from .tasks.celery_app import task_scrape_and_ingest, task_publish_2_days_before
from .tasks.scheduler import start_scheduler

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

from .tasks.celery_app import task_scrape_and_ingest, task_publish_2_days_before, cleanup_fake_and_sample_records

@app.on_event("startup")
def startup_event():
    init_db()
    start_scheduler()
    db = next(get_db())
    # Clean up any fake, sample, or duplicate records from previous runs
    cleanup_fake_and_sample_records(db)
    # If no genuine T-2 conferences are present, run ingestion cycle immediately
    if db.query(Conference).count() == 0:
        logger.info("Triggering genuine T-2 conference discovery & AI validation cycle...")
        task_scrape_and_ingest()

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
    
    return DashboardStats(
        total_conferences=total,
        published_to_excel=published,
        upcoming_2_days=upcoming_2_days,
        sources_active=6,
        last_scrape_time=None,
        excel_path=settings.EXCEL_OUTPUT_PATH
    )

@app.get("/api/conferences", response_model=List[ConferenceResponse])
def get_conferences(
    source: Optional[str] = Query(None, description="Filter by source (10times, luma, eventbrite, meetup, cvent, events_in_america)"),
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search by title, speaker, or city"),
    published_only: Optional[bool] = Query(False, description="Filter only conferences published to Excel"),
    db: Session = Depends(get_db)
):
    query = db.query(Conference)

    if source:
        query = query.filter(Conference.source_name.ilike(f"%{source}%"))
    if category:
        query = query.filter(Conference.industry_category.ilike(f"%{category}%"))
    if published_only:
        query = query.filter(Conference.is_published_to_excel == True)
    if search:
        search_filter = f"%{search}%"
        query = query.filter(
            (Conference.conference_title.ilike(search_filter)) |
            (Conference.speakers.ilike(search_filter)) |
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
    db: Session = Depends(get_db)
):
    """Fetch verified speaker profiles extracted from official sources."""
    query = db.query(Speaker)
    if conference_id:
        query = query.filter(Speaker.conference_id == conference_id)
    return query.order_by(Speaker.conference_name.asc(), Speaker.speaker_name.asc()).all()

@app.post("/api/trigger/scrape")
def trigger_scrape(background_tasks: BackgroundTasks):
    """Manually triggers immediate 24/7 web scraping & AI extraction cycle."""
    background_tasks.add_task(task_scrape_and_ingest)
    return {"message": "Scrape and AI ingestion cycle triggered across all 6 websites in background."}

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
    if sheet not in ["USA Conferences", "Speakers"]:
        sheet = "USA Conferences"
    try:
        df = manager.read_excel_as_dataframe(sheet_name=sheet)
        records = df.fillna("").to_dict(orient="records")
        return {
            "sheet": sheet,
            "sheets": ["USA Conferences", "Speakers"],
            "columns": list(df.columns),
            "total_rows": len(records),
            "rows": records
        }
    except Exception as e:
        logger.error(f"Error reading Excel sheet {sheet}: {e}")
        return {
            "sheet": sheet,
            "sheets": ["USA Conferences", "Speakers"],
            "columns": [],
            "total_rows": 0,
            "rows": []
        }
