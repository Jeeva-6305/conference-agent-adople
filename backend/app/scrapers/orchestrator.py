import concurrent.futures
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Any
from ..schemas import RawEventData
from .base_scraper import clean_html_text
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
        seen_global_keys = set()

        start_time = time.time()
        executor = ThreadPoolExecutor(max_workers=min(12, len(self.scrapers)))
        future_to_scraper = {
            executor.submit(scraper.scrape): scraper.source_name
            for scraper in self.scrapers
        }

        try:
            for future in concurrent.futures.as_completed(future_to_scraper, timeout=135):
                name = future_to_scraper[future]
                try:
                    events = future.result(timeout=5)
                    count = len(events)
                    self.source_telemetry[name] = {
                        "status": "success",
                        "discovered": count,
                        "error": None
                    }
                    logger.info(f"[{name}] Successfully collected {count} candidate events")
                    for ev in events:
                        dedup_key = (
                            clean_html_text(ev.raw_title).lower(),
                            (ev.raw_date or "")[:10],
                            (ev.source_name or ""),
                        )
                        if dedup_key in seen_global_keys:
                            continue
                        seen_global_keys.add(dedup_key)
                        all_raw_events.append(ev)
                except Exception as e:
                    self.source_telemetry[name] = {
                        "status": "error",
                        "discovered": 0,
                        "error": str(e)
                    }
                    logger.warning(f"[{name}] Scraper execution error: {e}")
        except concurrent.futures.TimeoutError:
            logger.warning("[Orchestrator] Overall 135s collection window reached; collecting completed sources.")
        finally:
            for future, name in future_to_scraper.items():
                if name not in self.source_telemetry:
                    self.source_telemetry[name] = {
                        "status": "timeout",
                        "discovered": 0,
                        "error": "Scraper execution exceeded overall 135s timeout"
                    }
                    logger.warning(f"[{name}] Scraper execution timed out (135s threshold)")
            executor.shutdown(wait=False, cancel_futures=True)

        elapsed = round(time.time() - start_time, 2)
        logger.info(f"Collection complete in {elapsed}s: {len(all_raw_events)} raw events harvested across {len(self.scrapers)} sources.")
        for name, data in self.source_telemetry.items():
            logger.info(f"  • Source [{name}]: status={data['status']}, discovered={data['discovered']}, err={data['error']}")

        return all_raw_events
