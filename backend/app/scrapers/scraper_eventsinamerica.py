import logging
import requests
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class EventsInAmericaScraper(BaseScraper):
    def __init__(self):
        super().__init__("events_in_america", "https://eventsinamerica.com/trade-shows")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Checking Events in America live conferences...")
        events: List[RawEventData] = []
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            resp = requests.get("https://eventsinamerica.com/trade-shows", headers=headers, timeout=10)
            if resp.status_code == 200:
                pass
        except Exception as e:
            logger.warning(f"[{self.source_name}] Events in America live endpoint error: {e}")

        logger.info(f"[{self.source_name}] Harvested {len(events)} events from Events in America.")
        return events
