import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
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

    def collect_all(self) -> List[RawEventData]:
        logger.info(f"Starting 24/7 conference collection across all {len(self.scrapers)} sources...")
        all_raw_events: List[RawEventData] = []
        
        with ThreadPoolExecutor(max_workers=len(self.scrapers)) as executor:
            future_to_scraper = {
                executor.submit(scraper.scrape): scraper.source_name
                for scraper in self.scrapers
            }
            for future in as_completed(future_to_scraper):
                name = future_to_scraper[future]
                try:
                    events = future.result()
                    logger.info(f"[{name}] Collected {len(events)} candidate events")
                    all_raw_events.extend(events[:25])
                except Exception as e:
                    logger.error(f"[{name}] Scraper error: {e}")

        logger.info(f"Collection complete: {len(all_raw_events)} raw events harvested across {len(self.scrapers)} sources.")
        return all_raw_events
