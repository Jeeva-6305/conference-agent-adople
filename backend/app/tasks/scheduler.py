import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from .celery_app import task_scrape_and_ingest, task_publish_2_days_before, task_send_conference_reminder_emails
from ..config import settings

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

# In-memory execution tracking for the automated hourly scraping service
scheduler_state: Dict[str, Any] = {
    "is_running": False,
    "interval_minutes": settings.SCRAPER_INTERVAL_MINUTES,
    "last_scrape_time": None,
    "next_scrape_time": None,
    "last_status": "Idle",
    "last_summary": None,
    "total_runs": 0,
    "last_error": None
}

def hourly_scrape_and_update_job():
    """
    Automated Hourly Job:
    Runs automatically once every hour (60 minutes).
    1. Scrapes conference and speaker details across verified websites.
    2. Runs AI extraction & deduplication on speakers and conferences.
    3. Updates PostgreSQL database with fresh conference & speaker records.
    4. Evaluates T-2 publication status.
    5. Updates and synchronizes the published Excel spreadsheet (both sheets).
    6. Sends separate individual email reminders for each matching conference.
    """
    now = datetime.now()
    scheduler_state["last_scrape_time"] = now
    scheduler_state["last_status"] = "Running"
    logger.info(f"⏰ [Hourly Automation] Starting scheduled scraping & data update at {now.strftime('%Y-%m-%d %H:%M:%S')}...")
    
    try:
        # Step 1: Scrape websites, extract speakers, and sync database & Excel
        res = task_scrape_and_ingest()
        
        # Step 2: Also run T-2 publication check to ensure scheduled conferences reaching T-2 are promoted
        pub_res = task_publish_2_days_before()

        # Step 3: Run reminder email delivery for any pending unnotified conferences
        email_res = task_send_conference_reminder_emails()
        
        scheduler_state["total_runs"] += 1
        scheduler_state["last_status"] = "Success"
        scheduler_state["last_error"] = None

        
        # Calculate next scheduled run
        job = scheduler.get_job("hourly_scraper_job")
        if job and job.next_run_time:
            scheduler_state["next_scrape_time"] = job.next_run_time
        else:
            scheduler_state["next_scrape_time"] = datetime.now() + timedelta(minutes=settings.SCRAPER_INTERVAL_MINUTES)
            
        summary = (
            f"Successfully scraped & updated data at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}. "
            f"Target T-2 Date: {res.get('target_start_date')}. Next run at {scheduler_state['next_scrape_time'].strftime('%Y-%m-%d %H:%M:%S')}."
        )
        scheduler_state["last_summary"] = summary
        logger.info(f"⏰ [Hourly Automation] Job finished. {summary}")
        
    except Exception as e:
        scheduler_state["last_status"] = f"Error: {e}"
        scheduler_state["last_error"] = str(e)
        logger.error(f"❌ [Hourly Automation] Error during scheduled scrape: {e}", exc_info=True)


def start_scheduler():
    """Starts the 24/7 background scheduler to run scraping automatically every hour."""
    if not scheduler.running:
        interval_minutes = settings.SCRAPER_INTERVAL_MINUTES or 60
        logger.info(f"Starting automated background scheduler (Interval: once every {interval_minutes} minutes)...")
        
        # 1. Automated scraping across all sources once every hour
        scheduler.add_job(
            hourly_scrape_and_update_job,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="hourly_scraper_job",
            name="Automated Hourly Conference & Speaker Scraping",
            replace_existing=True,
            next_run_time=datetime.now()  # Run immediately on start, then every 60 minutes
        )
        
        # 2. Safety publication check running every hour at the top of the hour (:00)
        scheduler.add_job(
            task_publish_2_days_before,
            trigger=CronTrigger(minute=0),
            id="publish_2_days_before_job",
            name="Hourly 2-Day Excel Publication Engine",
            replace_existing=True
        )
        
        scheduler.start()
        scheduler_state["is_running"] = True
        scheduler_state["interval_minutes"] = interval_minutes
        
        job = scheduler.get_job("hourly_scraper_job")
        if job and job.next_run_time:
            scheduler_state["next_scrape_time"] = job.next_run_time
            
        logger.info(f"✅ Automated Hourly Scheduler started successfully. Next execution scheduled at: {scheduler_state.get('next_scrape_time')}")


def stop_scheduler():
    """Stops the background scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        scheduler_state["is_running"] = False
        logger.info("Background Scheduler stopped.")


def get_scheduler_status() -> Dict[str, Any]:
    """Returns the live status, last execution time, and next scheduled run of the automated scraper."""
    job = scheduler.get_job("hourly_scraper_job") if scheduler.running else None
    next_time = job.next_run_time if job else scheduler_state.get("next_scrape_time")
    
    return {
        "is_running": scheduler.running,
        "interval_minutes": settings.SCRAPER_INTERVAL_MINUTES,
        "interval_display": f"Every {settings.SCRAPER_INTERVAL_MINUTES} minutes (1 hour)",
        "last_scrape_time": scheduler_state.get("last_scrape_time"),
        "next_scrape_time": next_time,
        "last_status": scheduler_state.get("last_status"),
        "last_summary": scheduler_state.get("last_summary"),
        "total_runs": scheduler_state.get("total_runs"),
        "last_error": scheduler_state.get("last_error")
    }

if __name__ == "__main__":
    import time
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    print("Starting standalone hourly scraper daemon. Press Ctrl+C to stop.")
    start_scheduler()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        stop_scheduler()
        print("Scheduler stopped.")
