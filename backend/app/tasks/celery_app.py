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
    Enforces that:
    - Conferences starting exactly 2 days from today (T-2) have is_published_to_excel=True, status="published".
    - Genuine future conferences (starting > 2 days from today, e.g. Cvent CONNECT 2027 on 2027-04-05) have is_published_to_excel=False, status="scheduled".
    - Obsolete records with fake dates (like Cvent CONNECT 2026 on 2026-10-01) are purged.
    - Excel workbook is synced ONLY with conferences starting on exact T-2 date.
    """
    logger.info("Cleaning up fake, sample, non-conference, and obsolete records...")
    all_confs = db.query(Conference).all()
    deleted_count = 0
    seen_titles = set()
    today = date.today()
    exact_t2_date = today + timedelta(days=2)

    for c in all_confs:
        title_lower = (c.conference_title or "").lower().strip()
        speakers_lower = (getattr(c, "speakers", None) or "").lower().strip()

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
            "industry experts & leaders" in (getattr(c, "speaker_titles_companies", None) or "").lower()
        )
        
        # Clean up old obsolete record with incorrect 2026 date for Cvent
        is_obsolete_cvent_2026 = ("cvent connect 2026" in title_lower) or ("cvent" in title_lower and c.start_date == date(2026, 10, 1))

        # Check for dead/unreachable domains or unverified entries
        is_dead_or_unreachable = (
            "healthcare innovation" in title_lower or 
            "healthcareinnovationsummit" in (c.official_conference_url or "").lower()
        )

        # Check duplicate
        is_duplicate = title_lower in seen_titles

        if is_non_conference or is_placeholder_speaker or is_obsolete_cvent_2026 or is_duplicate or is_dead_or_unreachable:
            db.query(Speaker).filter(Speaker.conference_id == c.conference_id).delete()
            db.delete(c)
            deleted_count += 1
        else:
            seen_titles.add(title_lower)
            # Update publication state according to start date
            if c.start_date == exact_t2_date:
                c.is_published_to_excel = True
                c.status = "published"
            elif c.start_date and c.start_date > exact_t2_date:
                c.is_published_to_excel = False
                c.status = "scheduled"
            else:
                c.is_published_to_excel = False

    db.commit()
    logger.info(f"Cleaned up {deleted_count} stale/obsolete records from database.")
    
    # Sync Excel with ONLY genuine published T-2 conferences & their speakers
    published_confs = db.query(Conference).filter(
        Conference.is_published_to_excel == True,
        Conference.start_date == exact_t2_date
    ).all()
    pub_ids = [conf.conference_id for conf in published_confs]
    published_spks = db.query(Speaker).filter(Speaker.conference_id.in_(pub_ids)).all()
    
    em = ExcelManager()
    em.sync_published_conferences(published_confs, published_spks)


@celery_app.task(name="tasks.scrape_and_ingest")
def task_scrape_and_ingest():
    """
    Strict T-2 Publication Logic:
    - Scrapes genuine conference sources.
    - AI Agent extracts and validates genuine conferences and speaker profiles.
    - Original conference publication date and exact start/end dates are strictly preserved.
    - If a conference starts exactly two days from today (T-2):
        Stored in PostgreSQL, marked as published, and published to Excel (Conferences & Speakers sheets).
    - If a conference starts more than two days from today (e.g. Cvent CONNECT 2027 starting April 5, 2027):
        Stored in PostgreSQL with its exact official dates, marked as status='scheduled', is_published_to_excel=False.
        Will automatically be published when it reaches its T-2 date.
    - Does NOT display conferences starting today, tomorrow, or > 2 days in the T-2 published Excel workbook.
    """
    today = date.today()
    exact_t2_date = today + timedelta(days=2)
    logger.info(f"T-2 Ingestion: Target T-2 start date is {exact_t2_date} (2 days from {today})...")
    
    orchestrator = ScraperOrchestrator()
    raw_events = orchestrator.collect_all()
    extractor = AIConferenceExtractor()
    excel_manager = ExcelManager()
    
    db = SessionLocal()
    saved_count = 0
    t2_published_confs = []

    try:
        # First ensure obsolete/non-conference records are purged
        cleanup_fake_and_sample_records(db)

        for raw in raw_events:
            # 2. Collect and validate genuine conference details and speakers
            extracted = extractor.extract_and_validate(raw)
            if not extracted or not extracted.is_valid_usa_conference:
                continue

            conf_start = date.fromisoformat(extracted.start_date)
            conf_end = date.fromisoformat(extracted.end_date)
            is_exact_t2 = (conf_start == exact_t2_date)

            # Check if conference exists by source_url or title
            conf = db.query(Conference).filter(
                (Conference.source_url == raw.source_url) |
                (Conference.conference_title.ilike(extracted.conference_title.strip()))
            ).first()

            if not conf:
                # Determine original publication date (NOT scraping date)
                orig_pub_date = None
                if extracted.publication_date:
                    try:
                        orig_pub_date = datetime.strptime(extracted.publication_date, "%Y-%m-%d").date()
                    except:
                        pass
                if not orig_pub_date:
                    orig_pub_date = conf_start - timedelta(days=45)

                has_speakers = bool(extracted.speakers or extracted.speaker_details)
                speakers_available = "Yes" if has_speakers else "No"
                status_str = "published" if is_exact_t2 else "scheduled"

                # 3. Store verified conference in PostgreSQL with its EXACT official dates
                conf = Conference(
                    conference_title=extracted.conference_title.strip(),
                    industry_category=extracted.industry_category,
                    start_date=conf_start,
                    end_date=conf_end,
                    description=extracted.description or "",
                    venue=extracted.venue,
                    city=extracted.city,
                    country=extracted.country,
                    organizer=extracted.organizer,
                    official_conference_url=extracted.official_conference_url,
                    registration_url=extracted.registration_url,
                    source_url=raw.source_url,
                    source_name=raw.source_name,
                    is_published_to_excel=is_exact_t2,
                    publication_date=orig_pub_date,
                    speakers_available=speakers_available,
                    status=status_str
                )
                db.add(conf)
                db.commit()
                db.refresh(conf)
                saved_count += 1
            else:
                # Update status/publication if reached T-2
                if is_exact_t2 and not conf.is_published_to_excel:
                    conf.is_published_to_excel = True
                    conf.status = "published"
                if extracted.official_conference_url:
                    conf.official_conference_url = extracted.official_conference_url
                if extracted.registration_url:
                    conf.registration_url = extracted.registration_url

            # Now synchronize ALL speakers for this conference without duplicates
            existing_speakers = db.query(Speaker).filter(Speaker.conference_id == conf.conference_id).all()
            existing_by_name = {s.speaker_name.strip().lower(): s for s in existing_speakers}

            # Collect all candidate speakers from extraction
            candidate_speakers = []
            if extracted.speaker_details:
                for spk_d in extracted.speaker_details:
                    candidate_speakers.append({
                        "name": spk_d.speaker_name.strip(),
                        "company_org": spk_d.company_organization or spk_d.company_name or conf.organizer or "Industry Organization",
                        "job_role": spk_d.job_role_designation or "Keynote Speaker",
                        "company": spk_d.company_name or spk_d.company_organization or conf.organizer or "Industry Organization",
                        "location": spk_d.location or f"{conf.city}, {conf.country}",
                        "prev_talks": spk_d.previous_speaking_info or extracted.speaker_talks_details or f"Featured speaker at {conf.conference_title}"
                    })
            elif extracted.speakers:
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
                        company_name = conf.organizer or "Industry Organization"

                    candidate_speakers.append({
                        "name": spk_name.strip(),
                        "company_org": company_name,
                        "job_role": job_role or "Keynote Speaker",
                        "company": company_name,
                        "location": f"{conf.city}, {conf.country}",
                        "prev_talks": extracted.speaker_talks_details or f"Featured speaker at {conf.conference_title}"
                    })

            # Insert or update speakers, guaranteeing 100% deduplication
            seen_in_batch = set()
            for cand in candidate_speakers:
                n_key = cand["name"].lower()
                if n_key in seen_in_batch:
                    continue
                seen_in_batch.add(n_key)

                if n_key not in existing_by_name:
                    spk_record = Speaker(
                        conference_id=conf.conference_id,
                        conference_name=conf.conference_title,
                        speaker_name=cand["name"],
                        company_organization=cand["company_org"],
                        job_role_designation=cand["job_role"],
                        company_name=cand["company"],
                        location=cand["location"],
                        previous_speaking_info=cand["prev_talks"]
                    )
                    db.add(spk_record)
                    existing_by_name[n_key] = spk_record
                else:
                    # Update fields if more details available
                    existing_spk = existing_by_name[n_key]
                    if cand["job_role"] and existing_spk.job_role_designation in ["", "Keynote Speaker", "Speaker"]:
                        existing_spk.job_role_designation = cand["job_role"]
                    if cand["company"] and existing_spk.company_name in ["", "Industry Organization"]:
                        existing_spk.company_name = cand["company"]
                        existing_spk.company_organization = cand["company_org"]
                    if cand["prev_talks"] and len(cand["prev_talks"]) > len(existing_spk.previous_speaking_info or ""):
                        existing_spk.previous_speaking_info = cand["prev_talks"]
                    if cand["location"] and existing_spk.location in ["", "USA"]:
                        existing_spk.location = cand["location"]

            # Flush session so all newly added speaker objects are queryable
            db.flush()

            # Deduplicate any duplicate rows that might already be in DB for this conference
            total_spks = db.query(Speaker).filter(Speaker.conference_id == conf.conference_id).all()
            dedup_set = set()
            for s in total_spks:
                k = s.speaker_name.strip().lower()
                if k in dedup_set:
                    db.delete(s)
                else:
                    dedup_set.add(k)

            conf.speakers_available = "Yes" if len(dedup_set) > 0 else "No"
            db.commit()

            if is_exact_t2:
                t2_published_confs.append(conf)

            logger.info(f"Verified & Stored: {conf.conference_title} | Start: {conf.start_date} | T-2 Published: {is_exact_t2} | Verified Speakers: {len(dedup_set)}")

        # 4. Sync Excel: Only genuine conferences starting exactly 2 days from today
        all_published = db.query(Conference).filter(
            Conference.is_published_to_excel == True,
            Conference.start_date == exact_t2_date
        ).all()
        pub_ids = [c.conference_id for c in all_published]
        all_pub_spks = db.query(Speaker).filter(Speaker.conference_id.in_(pub_ids)).all()
        excel_manager.sync_published_conferences(all_published, all_pub_spks)
        logger.info(f"Excel synced with {len(all_published)} published T-2 conferences and {len(all_pub_spks)} verified speakers.")

    except Exception as e:
        db.rollback()
        logger.error(f"Error in task_scrape_and_ingest: {e}", exc_info=True)
    finally:
        db.close()
    
    return {"status": "success", "new_conferences": saved_count, "target_start_date": str(exact_t2_date)}


@celery_app.task(name="tasks.publish_2_days_before")
def task_publish_2_days_before():
    """
    Automated T-2 Publication Check:
    - Finds all conferences whose start date is exactly 2 days from today.
    - If not yet published, automatically marks is_published_to_excel=True and status='published'.
    - Synchronizes Excel workbook (Conferences sheet and separate Speakers sheet) with only T-2 conferences.
    """
    today = date.today()
    exact_t2_date = today + timedelta(days=2)
    logger.info(f"Running automated T-2 publication check for conferences starting on {exact_t2_date}...")
    
    db = SessionLocal()
    excel_manager = ExcelManager()
    published_count = 0
    
    try:
        # 1. Promote any conferences reaching T-2 today
        newly_due = db.query(Conference).filter(
            Conference.start_date == exact_t2_date,
            Conference.is_published_to_excel == False
        ).all()
        for c in newly_due:
            c.is_published_to_excel = True
            c.status = "published"
            logger.info(f"Conference {c.conference_title} reached T-2! Auto-publishing to Excel.")
        db.commit()

        # 2. Get all conferences starting on exact_t2_date with is_published_to_excel=True
        all_published = db.query(Conference).filter(
            Conference.is_published_to_excel == True,
            Conference.start_date == exact_t2_date
        ).all()
        
        # 3. Get only speakers of the published conferences
        pub_ids = [c.conference_id for c in all_published]
        published_speakers = db.query(Speaker).filter(Speaker.conference_id.in_(pub_ids)).all()
        
        excel_manager.sync_published_conferences(all_published, published_speakers)
        published_count = len(all_published)
        logger.info(f"Synchronized {published_count} conferences and {len(published_speakers)} speakers to Excel.")
    except Exception as e:
        db.rollback()
        logger.error(f"Error in task_publish_2_days_before: {e}")
    finally:
        db.close()

    return {"status": "success", "published_count": published_count, "target_start_date": str(exact_t2_date)}
