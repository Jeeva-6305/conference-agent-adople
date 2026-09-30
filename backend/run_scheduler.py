import sys
import time
import logging
from pathlib import Path

# Add backend directory to sys.path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from app.tasks.scheduler import start_scheduler, stop_scheduler, get_scheduler_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("hourly_scheduler_daemon")

if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("🚀 USA Conference & Speaker Hourly Scraping Daemon")
    logger.info("Scrapes websites & updates PostgreSQL and Excel once every hour.")
    logger.info("=" * 70)
    
    start_scheduler()
    
    try:
        while True:
            time.sleep(30)
            status = get_scheduler_status()
            logger.info(
                f"[Heartbeat] Status: {status['last_status']} | "
                f"Runs: {status['total_runs']} | "
                f"Last Scrape: {status['last_scrape_time']} | "
                f"Next Scrape: {status['next_scrape_time']}"
            )
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopping hourly scheduler daemon...")
        stop_scheduler()
        logger.info("Daemon gracefully stopped.")
