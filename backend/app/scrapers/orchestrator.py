import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any
from ..schemas import RawEventData
from .scraper_10times import TenTimesScraper
from .scraper_luma import LumaScraper
from .scraper_eventbrite import EventbriteScraper
from .scraper_meetup import MeetupScraper
from .scraper_cvent import CventScraper
from .scraper_eventsinamerica import EventsInAmericaScraper
from .scraper_eventseye import EventsEyeScraper
from .scraper_tsnn import TSNNScraper
from .scraper_tradefest import TradefestScraper
from .scraper_govevents import GovEventsScraper
from .scraper_allevents import AllEventsScraper

logger = logging.getLogger(__name__)

class ScraperOrchestrator:
    def __init__(self):
        self.scrapers = [
            TenTimesScraper(),
            LumaScraper(),
            EventbriteScraper(),
            MeetupScraper(),
            CventScraper(),
            EventsInAmericaScraper(),
            EventsEyeScraper(),
            TSNNScraper(),
            TradefestScraper(),
            GovEventsScraper(),
            AllEventsScraper()
        ]
        self.source_telemetry: Dict[str, Dict[str, Any]] = {}

    def collect_all(self) -> List[RawEventData]:
        logger.info(f"Starting conference collection across all {len(self.scrapers)} sources...")
        all_raw_events: List[RawEventData] = []
        self.source_telemetry = {}
        
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=min(12, len(self.scrapers))) as executor:
            future_to_scraper = {
                executor.submit(scraper.scrape): scraper.source_name
                for scraper in self.scrapers
            }
            for future in as_completed(future_to_scraper):
                name = future_to_scraper[future]
                try:
                    events = future.result(timeout=45)
                    count = len(events)
                    self.source_telemetry[name] = {
                        "status": "success",
                        "discovered": count,
                        "error": None
                    }
                    logger.info(f"[{name}] Successfully collected {count} candidate events")
                    all_raw_events.extend(events[:30])
                except TimeoutError:
                    self.source_telemetry[name] = {
                        "status": "timeout",
                        "discovered": 0,
                        "error": "Scraper execution exceeded 45s timeout"
                    }
                    logger.warning(f"[{name}] Scraper execution timed out (45s threshold)")
                except Exception as e:
                    self.source_telemetry[name] = {
                        "status": "error",
                        "discovered": 0,
                        "error": str(e)
                    }
                    logger.warning(f"[{name}] Scraper execution error: {e}")

        elapsed = round(time.time() - start_time, 2)
        logger.info(f"Collection complete in {elapsed}s: {len(all_raw_events)} raw events harvested across {len(self.scrapers)} sources.")
        for name, data in self.source_telemetry.items():
            logger.info(f"  • Source [{name}]: status={data['status']}, discovered={data['discovered']}, err={data['error']}")
            
        return all_raw_events
