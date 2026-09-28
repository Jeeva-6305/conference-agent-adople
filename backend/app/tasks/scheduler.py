import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from .celery_app import task_scrape_and_ingest, task_publish_2_days_before
from ..config import settings

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

def start_scheduler():
    if not scheduler.running:
        # Periodic 24/7 scraping across all 6 websites
        scheduler.add_job(
            task_scrape_and_ingest,
            trigger=IntervalTrigger(minutes=settings.SCRAPER_INTERVAL_MINUTES),
            id="continuous_scraper_job",
            name="24/7 Conference Ingestion",
            replace_existing=True
        )
        
        # Check and publish to Excel 2 days before conference (checks every hour or daily at midnight)
        scheduler.add_job(
            task_publish_2_days_before,
            trigger=CronTrigger(hour="0,6,12,18", minute=0),
            id="publish_2_days_before_job",
            name="2-Day Excel Publication Engine",
            replace_existing=True
        )
        
        scheduler.start()
        logger.info("24/7 Background Scheduler started successfully.")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Background Scheduler stopped.")
