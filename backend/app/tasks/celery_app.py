import logging
from datetime import date, timedelta
from celery import Celery
from ..config import settings
from ..database import SessionLocal
from ..models import Conference
from ..scrapers.orchestrator import ScraperOrchestrator
from ..ai.extractor import AIConferenceExtractor
from ..storage.excel_manager import ExcelManager

logger = logging.getLogger(__name__)

celery_app = Celery(
    "conference_tasks",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task(name="tasks.scrape_and_ingest")
def task_scrape_and_ingest():
    """
    Continuous 24/7 ingestion:
    1. Scrapes real candidate conferences across the 6 websites.
    2. Passes each through the Gemini AI extraction & USA validation agent.
    3. Saves genuine verified conferences immediately into the database.
    """
    logger.info("Celery Task: Starting scrape and ingest cycle...")
    orchestrator = ScraperOrchestrator()
    raw_events = orchestrator.collect_all()
    extractor = AIConferenceExtractor()
    
    db = SessionLocal()
    saved_count = 0
    try:
        for raw in raw_events:
            # Check if source URL already processed
            existing = db.query(Conference).filter(Conference.source_url == raw.source_url).first()
            if existing:
                continue

            # Run AI extraction and validation
            extracted = extractor.extract_and_validate(raw)
            if not extracted:
                continue

            # Check if title already exists in DB
            title_exists = db.query(Conference).filter(Conference.conference_title == extracted.conference_title).first()
            if title_exists:
                continue

            conf = Conference(
                conference_title=extracted.conference_title,
                industry_category=extracted.industry_category,
                start_date=date.fromisoformat(extracted.start_date),
                end_date=date.fromisoformat(extracted.end_date),
                speakers=", ".join(extracted.speakers) if extracted.speakers else "Keynote Speakers TBD",
                speaker_titles_companies=", ".join(extracted.speaker_titles_companies) if extracted.speaker_titles_companies else "",
                venue=extracted.venue,
                city=extracted.city,
                country=extracted.country,
                organizer=extracted.organizer,
                official_conference_url=extracted.official_conference_url,
                registration_url=extracted.registration_url,
                source_url=raw.source_url,
                source_name=raw.source_name,
                is_published_to_excel=False,
                status="discovered"
            )
            db.add(conf)
            db.commit()  # Commit immediately per record
            saved_count += 1
            logger.info(f"Saved verified conference: {conf.conference_title} ({conf.city}, {conf.country})")

        logger.info(f"Ingested {saved_count} new conferences into database.")
    except Exception as e:
        db.rollback()
        logger.error(f"Error in task_scrape_and_ingest: {e}")
    finally:
        db.close()
    
    return {"status": "success", "new_conferences": saved_count}

@celery_app.task(name="tasks.publish_2_days_before")
def task_publish_2_days_before():
    """
    2-Day Publication Engine:
    Finds conferences where start_date is exactly 2 days from today,
    publishes their details into the Excel sheet, and marks them as published.
    """
    target_date = date.today() + timedelta(days=settings.REMINDER_DAYS_BEFORE)
    logger.info(f"Checking for conferences starting in 2 days on {target_date}...")
    
    db = SessionLocal()
    excel_manager = ExcelManager()
    published_count = 0
    
    try:
        due_conferences = db.query(Conference).filter(
            Conference.start_date == target_date,
            Conference.is_published_to_excel == False
        ).all()

        if due_conferences:
            # Publish to Excel
            excel_manager.publish_conferences(due_conferences)
            
            # Update status in Database
            for conf in due_conferences:
                conf.is_published_to_excel = True
                conf.publication_date = date.today()
                conf.status = "published"
            
            db.commit()
            published_count = len(due_conferences)
            logger.info(f"Published {published_count} conferences to Excel (2 days before event).")
    except Exception as e:
        db.rollback()
        logger.error(f"Error in task_publish_2_days_before: {e}")
    finally:
        db.close()

    return {"status": "success", "published_count": published_count, "target_date": str(target_date)}
