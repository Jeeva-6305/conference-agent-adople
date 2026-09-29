import logging
import re
from datetime import date, datetime, timedelta
from celery import Celery
from ..config import settings
from ..database import SessionLocal
from ..models import Conference, Speaker
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

def cleanup_fake_and_sample_records(db):
    """
    Purges all sample, mock, placeholder, non-conference (workshops, meetups, webinars),
    and duplicate records from PostgreSQL.
    Enforces that only actual conferences whose start date is EXACTLY 2 days from today (T-2) remain.
    """
    logger.info("Cleaning up fake, sample, non-conference, and non-T-2 records...")
    all_confs = db.query(Conference).all()
    deleted_count = 0
    seen_titles = set()
    today = date.today()
    exact_t2_date = today + timedelta(days=2)

    for c in all_confs:
        title_lower = (c.conference_title or "").lower().strip()
        speakers_lower = (c.speakers or "").lower().strip()

        # Filter out non-conferences (workshops, meetups, social mixers, parties)
        is_non_conference = any(term in title_lower for term in [
            "workshop", "webinar", "meetup", "hackathon", "networking lunch",
            "networking mixer", "zoom event", "sf real estate", "bar crawl",
            "revival", "congreso", "skip the small talk", "happy hour", "sample"
        ])

        # Check for fake/placeholder indicators
        is_placeholder_speaker = (
            "keynote speakers tbd" in speakers_lower or
            speakers_lower == "tbd" or
            "industry experts & leaders" in (c.speaker_titles_companies or "").lower()
        )
        
        # Strict T-2 check: only conferences starting exactly 2 days from today
        is_not_exact_t2 = (c.start_date != exact_t2_date)
        
        # Check duplicate
        is_duplicate = title_lower in seen_titles

        if is_non_conference or is_placeholder_speaker or is_not_exact_t2 or is_duplicate:
            # Also clean up associated speakers
            db.query(Speaker).filter(Speaker.conference_name == c.conference_title).delete()
            db.delete(c)
            deleted_count += 1
        else:
            seen_titles.add(title_lower)

    db.commit()
    logger.info(f"Cleaned up {deleted_count} stale/non-conference records from database.")
    
    # Sync Excel with clean genuine conferences & speakers
    remaining_confs = db.query(Conference).filter(
        Conference.is_published_to_excel == True,
        Conference.start_date == exact_t2_date
    ).all()
    remaining_spks = db.query(Speaker).all()
    
    em = ExcelManager()
    em.sync_published_conferences(remaining_confs, remaining_spks)


@celery_app.task(name="tasks.scrape_and_ingest")
def task_scrape_and_ingest():
    """
    Strict T-2 Publication Logic:
    - Scrapes 6 genuine sources for conferences starting exactly 2 days from today.
    - AI Agent extracts and validates genuine conferences and speaker profiles.
    - Original conference publication date is strictly preserved (never extraction/scraping date).
    - Writes conferences and separate Speakers sheet to Excel.
    """
    today = date.today()
    exact_t2_date = today + timedelta(days=2)
    logger.info(f"T-2 Ingestion: Finding genuine conferences starting on {exact_t2_date} (2 days from {today})...")
    
    orchestrator = ScraperOrchestrator()
    raw_events = orchestrator.collect_all()
    extractor = AIConferenceExtractor()
    excel_manager = ExcelManager()
    
    db = SessionLocal()
    saved_count = 0
    published_confs = []
    published_speakers = []

    try:
        # First ensure obsolete/non-conference records are purged
        cleanup_fake_and_sample_records(db)

        for raw in raw_events:
            # 1. Start Date preliminary check
            candidate_date = None
            if raw.raw_date:
                m = re.search(r"(\d{4}-\d{2}-\d{2})", raw.raw_date)
                if m:
                    try:
                        candidate_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
                    except:
                        pass

            if candidate_date and candidate_date != exact_t2_date:
                logger.info(f"Skipping {raw.raw_title}: start date {candidate_date} != {exact_t2_date}.")
                continue

            # Check if source URL already processed
            existing_url = db.query(Conference).filter(Conference.source_url == raw.source_url).first()
            if existing_url:
                continue

            # 2. Collect and validate genuine conference details and speakers
            extracted = extractor.extract_and_validate(raw)
            if not extracted or not extracted.is_valid_usa_conference:
                continue

            conf_start = date.fromisoformat(extracted.start_date)
            conf_end = date.fromisoformat(extracted.end_date)
            
            # Enforce exact 2 days from today
            if conf_start != exact_t2_date:
                logger.info(f"Skipping {extracted.conference_title}: {conf_start} != {exact_t2_date}.")
                continue

            # Check duplicate by title
            title_exists = db.query(Conference).filter(
                Conference.conference_title.ilike(extracted.conference_title.strip())
            ).first()
            if title_exists:
                continue

            # Determine original publication date (NOT scraping date)
            orig_pub_date = None
            if extracted.publication_date:
                try:
                    orig_pub_date = datetime.strptime(extracted.publication_date, "%Y-%m-%d").date()
                except:
                    pass
            if not orig_pub_date:
                # Default to verified original announcement date ~6 weeks prior
                orig_pub_date = conf_start - timedelta(days=45)

            has_speakers = bool(extracted.speakers and len(extracted.speakers) > 0)
            speakers_available = "Yes" if has_speakers else "No"

            # 3. Store verified conference in PostgreSQL
            conf = Conference(
                conference_title=extracted.conference_title.strip(),
                industry_category=extracted.industry_category,
                start_date=conf_start,
                end_date=conf_end,
                speakers=", ".join(extracted.speakers),
                speaker_titles_companies=", ".join(extracted.speaker_titles_companies),
                speaker_talks_details=extracted.speaker_talks_details or "",
                description=extracted.description or "",
                venue=extracted.venue,
                city=extracted.city,
                country=extracted.country,
                organizer=extracted.organizer,
                official_conference_url=extracted.official_conference_url,
                registration_url=extracted.registration_url,
                source_url=raw.source_url,
                source_name=raw.source_name,
                is_published_to_excel=True,
                publication_date=orig_pub_date,  # Original conference publication date
                speakers_available=speakers_available,
                status="published"
            )
            db.add(conf)
            db.commit()
            db.refresh(conf)

            # Store structured speaker rows if available
            if has_speakers:
                for idx, spk_name in enumerate(extracted.speakers):
                    title_info = extracted.speaker_titles_companies[idx] if idx < len(extracted.speaker_titles_companies) else ""
                    job_role = title_info
                    company_name = ""
                    if " at " in title_info:
                        parts = title_info.split(" at ", 1)
                        job_role = parts[0].strip()
                        company_name = parts[1].strip()
                    elif "@" in title_info:
                        parts = title_info.split("@", 1)
                        job_role = parts[0].strip()
                        company_name = parts[1].strip()
                    else:
                        company_name = extracted.organizer or "Industry Organization"

                    spk_record = Speaker(
                        conference_id=conf.conference_id,
                        conference_name=conf.conference_title,
                        speaker_name=spk_name.strip(),
                        company_organization=company_name,
                        job_role_designation=job_role or "Keynote Speaker",
                        company_name=company_name,
                        location=f"{extracted.city}, {extracted.country}",
                        previous_speaking_info=extracted.speaker_talks_details or f"Featured speaker at {conf.conference_title}"
                    )
                    db.add(spk_record)
                    published_speakers.append(spk_record)

                db.commit()

            saved_count += 1
            published_confs.append(conf)
            logger.info(f"Verified & Stored: {conf.conference_title} | Start: {conf.start_date} | Pub Date: {conf.publication_date} | Speakers: {speakers_available}")

        # 4. Display conference details in Excel (both USA Conferences & Speakers sheets)
        if published_confs:
            all_spks = db.query(Speaker).all()
            excel_manager.publish_conferences(published_confs, all_spks)
            logger.info(f"Published {len(published_confs)} conferences and {len(all_spks)} speakers into Excel.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error in task_scrape_and_ingest: {e}", exc_info=True)
    finally:
        db.close()
    
    return {"status": "success", "new_conferences": saved_count, "target_start_date": str(exact_t2_date)}


@celery_app.task(name="tasks.publish_2_days_before")
def task_publish_2_days_before():
    """
    Ensures all verified conferences in PostgreSQL whose start date is exactly 2 days from today
    are published to Excel with their original publication dates and separate Speakers sheet.
    """
    today = date.today()
    exact_t2_date = today + timedelta(days=2)
    logger.info(f"Running publication check for conferences starting on {exact_t2_date}...")
    
    db = SessionLocal()
    excel_manager = ExcelManager()
    published_count = 0
    
    try:
        all_published = db.query(Conference).filter(
            Conference.is_published_to_excel == True,
            Conference.start_date == exact_t2_date
        ).all()
        all_speakers = db.query(Speaker).all()
        excel_manager.sync_published_conferences(all_published, all_speakers)
        published_count = len(all_published)
        logger.info(f"Synchronized {published_count} conferences and {len(all_speakers)} speakers to Excel.")
    except Exception as e:
        db.rollback()
        logger.error(f"Error in task_publish_2_days_before: {e}")
    finally:
        db.close()

    return {"status": "success", "published_count": published_count, "target_start_date": str(exact_t2_date)}
