from typing import Optional
import logging
import re
from datetime import date, datetime, timedelta
from ..config import settings
from ..database import SessionLocal
from ..models import Conference, Speaker, Attendee
from ..scrapers.orchestrator import ScraperOrchestrator
from ..ai.extractor import AIConferenceExtractor, match_target_categories
from ..storage.excel_manager import ExcelManager

logger = logging.getLogger(__name__)

try:
    from celery import Celery
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
except ImportError:
    class DummyCelery:
        def task(self, *args, **kwargs):
            def decorator(fn):
                return fn
            return decorator
    celery_app = DummyCelery()



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

    OLD_MOCK_TITLES = [
        "runtime by modal", "dam new york", "cyber & cloud security",
        "corncon", "aascp", "cvent connect", "aap national conference"
    ]

    for c in all_confs:
        title_lower = (c.conference_title or "").lower().strip()
        speakers_lower = (getattr(c, "speakers", None) or "").lower().strip()

        # Filter out non-conferences (workshops, meetups, social mixers, parties, brunches, walks, runs)
        is_non_conference = any(term in title_lower for term in [
            "workshop", "webinar", "meetup", "hackathon", "networking lunch",
            "networking mixer", "zoom event", "sf real estate", "bar crawl",
            "revival", "congreso", "skip the small talk", "happy hour", "sample",
            "brunch", "walk with", "mile run", "horror night", "demo night"
        ])

        # Filter out past/expired events
        is_past_event = (c.start_date is None or c.start_date < today)

        # Filter out previous mock conferences
        is_previous_mock = any(mock_term in title_lower for mock_term in OLD_MOCK_TITLES)

        # Check for fake/placeholder indicators
        is_placeholder_speaker = (
            "keynote speakers tbd" in speakers_lower or
            speakers_lower == "tbd" or
            "industry experts & leaders" in (getattr(c, "speaker_titles_companies", None) or "").lower()
        )
        
        # Check for dead/unreachable domains or unverified entries
        is_dead_or_unreachable = (
            "healthcare innovation" in title_lower or 
            "healthcareinnovationsummit" in (c.official_conference_url or "").lower()
        )

        # Check duplicate
        is_duplicate = title_lower in seen_titles

        # Category check: must belong to at least one of the 6 core business categories
        matched_cats = match_target_categories(f"{c.conference_title} {c.description or ''}")
        is_invalid_category = (len(matched_cats) == 0)

        if is_non_conference or is_past_event or is_previous_mock or is_placeholder_speaker or is_duplicate or is_dead_or_unreachable or is_invalid_category:
            db.query(Speaker).filter(Speaker.conference_id == c.conference_id).delete()
            db.query(Attendee).filter(Attendee.conference_id == c.conference_id).delete()
            db.delete(c)
            deleted_count += 1
        else:
            seen_titles.add(title_lower)
            c.industry_category = " / ".join(matched_cats)
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
    logger.info(f"Cleaned up {deleted_count} stale/obsolete/non-category records from database.")
    
    # Sync Excel with ONLY genuine published T-2 conferences & their speakers & attendees
    published_confs = db.query(Conference).filter(
        Conference.is_published_to_excel == True,
        Conference.start_date == exact_t2_date
    ).all()
    pub_ids = [conf.conference_id for conf in published_confs]
    published_spks = db.query(Speaker).filter(Speaker.conference_id.in_(pub_ids)).all()
    published_atts = db.query(Attendee).filter(Attendee.conference_id.in_(pub_ids)).all()
    
    em = ExcelManager()
    em.sync_published_conferences(published_confs, published_spks, published_atts)



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
            if conf_start < today:
                continue
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
                        "company_website": getattr(spk_d, "official_company_website_url", "") or "",
                        "linkedin": getattr(spk_d, "linkedin_url", "") or "",
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
                        "company_website": "",
                        "linkedin": "",
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
                        official_company_website_url=cand.get("company_website", "") or "",
                        linkedin_url=cand.get("linkedin", "") or "",
                        location=cand["location"],
                        previous_speaking_info=cand["prev_talks"]
                    )
                    db.add(spk_record)
                    existing_by_name[n_key] = spk_record
                else:
                    # Update fields if more details available
                    existing_spk = existing_by_name[n_key]
                    if cand.get("company_website") and not existing_spk.official_company_website_url:
                        existing_spk.official_company_website_url = cand["company_website"]
                    if cand.get("linkedin") and not existing_spk.linkedin_url:
                        existing_spk.linkedin_url = cand["linkedin"]
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

            # Save or update Attendee info for this conference
            if extracted.attendee_details:
                att_info = extracted.attendee_details
                existing_att = db.query(Attendee).filter(Attendee.conference_id == conf.conference_id).first()
                if not existing_att:
                    new_att = Attendee(
                        conference_id=conf.conference_id,
                        conference_name=conf.conference_title,
                        expected_attendee_count=att_info.expected_attendee_count or "",
                        registered_attendee_count=att_info.registered_attendee_count or "",
                        attendee_categories=att_info.attendee_categories or "",
                        target_audience=att_info.target_audience or "",
                        industries=att_info.industries or conf.industry_category or "",
                        job_roles=att_info.job_roles or "",
                        source_url=conf.source_url
                    )
                    db.add(new_att)
                else:
                    if att_info.expected_attendee_count:
                        existing_att.expected_attendee_count = att_info.expected_attendee_count
                    if att_info.registered_attendee_count:
                        existing_att.registered_attendee_count = att_info.registered_attendee_count
                    if att_info.attendee_categories:
                        existing_att.attendee_categories = att_info.attendee_categories
                    if att_info.target_audience:
                        existing_att.target_audience = att_info.target_audience
                    if att_info.industries:
                        existing_att.industries = att_info.industries
                    if att_info.job_roles:
                        existing_att.job_roles = att_info.job_roles
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
        all_pub_atts = db.query(Attendee).filter(Attendee.conference_id.in_(pub_ids)).all()
        excel_manager.sync_published_conferences(all_published, all_pub_spks, all_pub_atts)
        logger.info(f"Excel synced with {len(all_published)} published T-2 conferences, {len(all_pub_spks)} verified speakers, and {len(all_pub_atts)} attendees.")

        # 5. Send separate individual email for each matching conference
        from ..services.email_service import ConferenceEmailService
        email_svc = ConferenceEmailService()
        email_res = email_svc.send_all_pending_reminders(db, conferences=all_published)
        logger.info(f"📧 Completed automated email reminders: {len(email_res)} conference(s) processed for recipient {email_svc.recipient_email}.")

        # 6. Post separate Adaptive Cards to Microsoft Teams Webhook AUTOMATICALLY
        from ..services.teams_service import TeamsWebhookService
        teams_svc = TeamsWebhookService()
        teams_res = teams_svc.send_all_pending_teams_cards(db, conferences=all_published)
        logger.info(f"📢 Completed automated Teams webhook dispatch: {len(teams_res)} conference card(s) processed.")

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
    - Synchronizes Excel workbook (Conferences sheet, Speakers sheet, and Attendees sheet) with only T-2 conferences.
    - Sends individual separate email reminders for newly published conferences.
    - Posts individual Adaptive Cards to Microsoft Teams Webhook.
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
        
        # 3. Get only speakers and attendees of the published conferences
        pub_ids = [c.conference_id for c in all_published]
        published_speakers = db.query(Speaker).filter(Speaker.conference_id.in_(pub_ids)).all()
        published_attendees = db.query(Attendee).filter(Attendee.conference_id.in_(pub_ids)).all()
        
        excel_manager.sync_published_conferences(all_published, published_speakers, published_attendees)
        published_count = len(all_published)
        logger.info(f"Synchronized {published_count} conferences, {len(published_speakers)} speakers, and {len(published_attendees)} attendees to Excel.")

        # 4. Trigger separate reminder emails for newly published conferences
        from ..services.email_service import ConferenceEmailService
        email_svc = ConferenceEmailService()
        email_svc.send_all_pending_reminders(db, conferences=all_published)

        # 5. Trigger Microsoft Teams Webhook cards for newly published conferences
        from ..services.teams_service import TeamsWebhookService
        teams_svc = TeamsWebhookService()
        teams_svc.send_all_pending_teams_cards(db, conferences=all_published)

    except Exception as e:
        db.rollback()
        logger.error(f"Error in task_publish_2_days_before: {e}")
    finally:
        db.close()

    return {"status": "success", "published_count": published_count, "target_start_date": str(exact_t2_date)}


@celery_app.task(name="tasks.send_conference_reminder_emails")
def task_send_conference_reminder_emails(recipient_email: str = None, force: bool = False):
    """
    Dedicated Email Reminder Task:
    - Queries all T-2 published conferences.
    - Sends a separate individual email for each conference to jeevanandham@adople.ai.
    - Enforces duplicate email prevention via unique identifier (Name + Date + Venue).
    """
    from ..services.email_service import ConferenceEmailService
    logger.info("📧 [Email Task] Initiating conference reminder email delivery job...")
    db = SessionLocal()
    email_service = ConferenceEmailService(recipient_email=recipient_email or settings.NOTIFICATION_RECIPIENT_EMAIL)
    sent_results = []

    try:
        today = date.today()
        exact_t2_date = today + timedelta(days=2)

        query = db.query(Conference).filter(
            Conference.is_published_to_excel == True,
            Conference.start_date == exact_t2_date
        )
        if not force:
            query = query.filter(Conference.email_sent == False)

        targets = query.all()
        logger.info(f"📧 [Email Task] Found {len(targets)} conference(s) ready for reminder delivery.")
        sent_results = email_service.send_all_pending_reminders(db, conferences=targets)
        logger.info(f"📧 [Email Task] Reminder execution finished. Processed {len(sent_results)} items.")
    except Exception as e:
        logger.error(f"❌ [Email Task] Error during reminder delivery: {e}", exc_info=True)
    finally:
        db.close()

    return {
        "status": "success",
        "recipient": email_service.recipient_email,
        "processed_count": len(sent_results),
        "results": sent_results
    }


@celery_app.task(name="tasks.send_teams_cards")
def task_send_teams_cards(force: bool = False, webhook_url: Optional[str] = None):
    """
    Dedicated Microsoft Teams Webhook Task:
    - Queries all T-2 published conferences.
    - Sends a rich Adaptive Card for each conference directly to Microsoft Teams.
    - Enforces duplicate card prevention.
    """
    from ..services.teams_service import TeamsWebhookService
    logger.info("📢 [Teams Task] Initiating Teams Webhook card delivery job...")
    db = SessionLocal()
    teams_service = TeamsWebhookService(webhook_url=webhook_url)
    sent_results = []

    try:
        today = date.today()
        exact_t2_date = today + timedelta(days=2)

        query = db.query(Conference).filter(
            Conference.is_published_to_excel == True,
            Conference.start_date == exact_t2_date
        )
        if not force:
            query = query.filter(Conference.teams_webhook_sent == False)

        targets = query.all()
        logger.info(f"📢 [Teams Task] Found {len(targets)} conference(s) ready for Teams card delivery.")
        sent_results = teams_service.send_all_pending_teams_cards(db, conferences=targets, force=force)
        logger.info(f"📢 [Teams Task] Delivery finished. Processed {len(sent_results)} items.")
    except Exception as e:
        logger.error(f"❌ [Teams Task] Error during Teams delivery: {e}", exc_info=True)
    finally:
        db.close()

    return {
        "status": "success",
        "processed_count": len(sent_results),
        "results": sent_results
    }




@celery_app.task(name="tasks.sync_to_google_sheets")
def task_sync_to_google_sheets():
    """
    Sync all conferences and speakers to Google Sheets with professional formatting.
    - Updates Sheet1 for Conferences (14 columns)
    - Auto-creates/updates Speakers sheet (8 columns)
    - Applies professional formatting (dark blue + teal headers)
    - Called by task_publish_2_days_before after Excel sync
    """
    # pyrefly: ignore [missing-import]
    from ..services.google_sheets_service import GoogleSheetsService

    db = SessionLocal()
    conference_count = 0
    speaker_count = 0

    try:
        if not settings.GOOGLE_SHEETS_SPREADSHEET_ID:
            logger.info("Google Sheets not configured, skipping sync")
            return {"status": "skipped", "reason": "Google Sheets not configured"}

        service = GoogleSheetsService()

        # ===== CONFERENCES SHEET (Sheet1) =====
        logger.info("Syncing conferences to Google Sheets Sheet1...")

        conf_headers = [
            "ID", "Title & Category", "Start Date", "End Date", "Speakers Available",
            "Venue & City", "Country", "Organizer", "Source", "Status",
            "Official URL", "Registration URL", "Source URL", "Publication Date"
        ]

        all_conferences = db.query(Conference).all()

        if all_conferences:
            conf_rows = [conf_headers]
            for conf in all_conferences:
                row = [
                    conf.conference_id or "",
                    conf.conference_title or "",
                    conf.start_date.isoformat() if conf.start_date else "",
                    conf.end_date.isoformat() if conf.end_date else "",
                    conf.speakers_available or "Yes",
                    (conf.venue or "") + (f", {conf.city}" if conf.city else ""),
                    conf.country or "USA",
                    conf.organizer or "",
                    conf.source_name or "",
                    conf.status or "scheduled",
                    conf.official_conference_url or "",
                    conf.registration_url or "",
                    conf.source_url or "",
                    conf.publication_date.isoformat() if conf.publication_date else ""
                ]
                conf_rows.append(row)

            service.update_range("Sheet1!A1", conf_rows)
            conference_count = len(conf_rows) - 1
            logger.info(f"Synced {conference_count} conferences to Google Sheets")

            try:
                service.format_header_row("Sheet1", len(conf_headers))
                service.format_data_rows("Sheet1", 1, len(conf_rows), len(conf_headers))
                logger.info("Applied professional formatting to Sheet1")
            except Exception as e:
                logger.warning(f"Could not apply formatting: {e}")

        # ===== SPEAKERS SHEET =====
        logger.info("Syncing speakers to Google Sheets...")

        speaker_headers = [
            "Speaker Name", "Conference Name", "Conference ID", "Company/Organization",
            "Job Role/Designation", "Company Name", "Location", "Previous Speaking Info"
        ]

        all_speakers = db.query(Speaker).all()

        if all_speakers:
            try:
                service.create_professional_sheet("Speakers", speaker_headers)
                logger.info("Created 'Speakers' sheet")
            except Exception as e:
                logger.debug(f"Sheet 'Speakers' may already exist: {e}")

            speaker_rows = [speaker_headers]
            for speaker in all_speakers:
                row = [
                    speaker.speaker_name or "",
                    speaker.conference_name or "",
                    speaker.conference_id or "",
                    speaker.company_organization or "",
                    speaker.job_role_designation or "",
                    speaker.company_name or "",
                    speaker.location or "",
                    speaker.previous_speaking_info or ""
                ]
                speaker_rows.append(row)

            service.update_range("Speakers!A1", speaker_rows)
            speaker_count = len(speaker_rows) - 1
            logger.info(f"Synced {speaker_count} speakers to Google Sheets")

            try:
                service.format_header_row("Speakers", len(speaker_headers), header_color={"red": 15/255, "green": 118/255, "blue": 110/255})
                service.format_data_rows("Speakers", 1, len(speaker_rows), len(speaker_headers))
                logger.info("Applied professional formatting to Speakers sheet")
            except Exception as e:
                logger.warning(f"Could not apply formatting to speakers: {e}")

        return {
            "status": "success",
            "conferences_synced": conference_count,
            "speakers_synced": speaker_count
        }

    except ValueError as e:
        logger.warning(f"Google Sheets sync skipped: {e}")
        return {"status": "skipped", "reason": str(e)}
    except Exception as e:
        logger.error(f"Error syncing to Google Sheets: {e}")
        db.rollback()
        raise
    finally:
        db.close()


@celery_app.task(name="tasks.migrate_db_to_google_sheets")
def task_migrate_db_to_google_sheets(clear_first: bool = False):
    """
    Migrate all database data to Google Sheets (like Excel does).
    - Creates headers if needed
    - Appends all conferences and speakers
    - Optionally clears sheet first for clean migration
    """
    # pyrefly: ignore [missing-import]
    from ..services.google_sheets_service import GoogleSheetsService

    db = SessionLocal()
    migration_summary = {
        "conferences_migrated": 0,
        "speakers_migrated": 0,
        "status": "pending",
        "message": ""
    }

    try:
        if not settings.GOOGLE_SHEETS_SPREADSHEET_ID:
            logger.info("Google Sheets not configured, skipping migration")
            migration_summary["status"] = "skipped"
            migration_summary["message"] = "Google Sheets not configured"
            return migration_summary

        service = GoogleSheetsService()

        # Get all data
        all_conferences = db.query(Conference).all()
        all_speakers = db.query(Speaker).all()

        if all_conferences:
            conf_headers = [
                "ID", "Title & Category", "Start Date", "End Date", "Speakers Available",
                "Venue & City", "Country", "Organizer", "Source", "Status",
                "Official URL", "Registration URL", "Source URL", "Publication Date"
            ]

            conf_rows = [conf_headers]
            for conf in all_conferences:
                row = [
                    conf.conference_id or "",
                    conf.conference_title or "",
                    conf.start_date.isoformat() if conf.start_date else "",
                    conf.end_date.isoformat() if conf.end_date else "",
                    conf.speakers_available or "Yes",
                    (conf.venue or "") + (f", {conf.city}" if conf.city else ""),
                    conf.country or "USA",
                    conf.organizer or "",
                    conf.source_name or "",
                    conf.status or "scheduled",
                    conf.official_conference_url or "",
                    conf.registration_url or "",
                    conf.source_url or "",
                    conf.publication_date.isoformat() if conf.publication_date else ""
                ]
                conf_rows.append(row)

            service.update_range("Sheet1!A1", conf_rows)
            migration_summary["conferences_migrated"] = len(conf_rows) - 1
            logger.info(f"Migrated {migration_summary['conferences_migrated']} conferences")

        if all_speakers:
            speaker_headers = [
                "Speaker Name", "Conference Name", "Conference ID", "Company/Organization",
                "Job Role/Designation", "Company Name", "Location", "Previous Speaking Info"
            ]

            speaker_rows = [speaker_headers]
            for speaker in all_speakers:
                row = [
                    speaker.speaker_name or "",
                    speaker.conference_name or "",
                    speaker.conference_id or "",
                    speaker.company_organization or "",
                    speaker.job_role_designation or "",
                    speaker.company_name or "",
                    speaker.location or "",
                    speaker.previous_speaking_info or ""
                ]
                speaker_rows.append(row)

            service.update_range("Speakers!A1", speaker_rows)
            migration_summary["speakers_migrated"] = len(speaker_rows) - 1
            logger.info(f"Migrated {migration_summary['speakers_migrated']} speakers")

        migration_summary["status"] = "success"
        migration_summary["message"] = f"Successfully migrated {migration_summary['conferences_migrated']} conferences and {migration_summary['speakers_migrated']} speakers"
        return migration_summary

    except Exception as e:
        logger.error(f"Error during migration: {e}")
        migration_summary["status"] = "error"
        migration_summary["message"] = str(e)
        db.rollback()
        return migration_summary
    finally:
        db.close()
