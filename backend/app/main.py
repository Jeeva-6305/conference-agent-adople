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
from .models import Conference
from .schemas import ConferenceResponse, DashboardStats
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

@app.on_event("startup")
def startup_event():
    init_db()
    start_scheduler()
    # Perform initial seed if empty
    db = next(get_db())
    if db.query(Conference).count() == 0:
        logger.info("Database is empty on boot. Triggering initial ingestion...")
        task_scrape_and_ingest()
        task_publish_2_days_before()

@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    count = db.query(Conference).count()
    return {
        "status": "healthy",
        "conferences_count": count,
        "excel_path": settings.EXCEL_OUTPUT_PATH,
        "excel_exists": os.path.exists(settings.EXCEL_OUTPUT_PATH)
    }

@app.get("/api/stats", response_model=DashboardStats)
def get_dashboard_stats(db: Session = Depends(get_db)):
    total = db.query(Conference).count()
    published = db.query(Conference).filter(Conference.is_published_to_excel == True).count()
    
    target_2_days = date.today() + timedelta(days=settings.REMINDER_DAYS_BEFORE)
    upcoming_2_days = db.query(Conference).filter(Conference.start_date == target_2_days).count()
    
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
def preview_excel():
    manager = ExcelManager()
    df = manager.read_excel_as_dataframe()
    # Replace NaN with empty string
    records = df.fillna("").to_dict(orient="records")
    return {
        "columns": list(df.columns),
        "total_rows": len(records),
        "rows": records
    }
