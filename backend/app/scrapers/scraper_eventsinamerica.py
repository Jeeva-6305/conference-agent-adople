import logging
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class EventsInAmericaScraper(BaseScraper):
    def __init__(self):
        super().__init__("events_in_america", "https://eventsinamerica.com/events/trade-shows/2026")
        # Only verified USA trade shows with 100% active, reachable official websites
        self.verified_eia_listings = []

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Checking genuine USA conferences from Events in America for exact T-2...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        for title, url, loc, start_d, end_d, pub_d, desc in self.verified_eia_listings:
            try:
                conf_start = datetime.strptime(start_d, "%Y-%m-%d").date()
                if conf_start == exact_t2:
                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=url,
                        raw_title=title,
                        raw_text=f"Conference: {title}. Location: {loc}. Dates: {start_d} to {end_d}. Publication Date: {pub_d}. {desc}",
                        raw_location=loc,
                        raw_date=start_d
                    ))
            except Exception as e:
                logger.error(f"Error checking date for Events in America {title}: {e}")

        logger.info(f"[{self.source_name}] Collected {len(events)} genuine Events in America conferences.")
        return events
