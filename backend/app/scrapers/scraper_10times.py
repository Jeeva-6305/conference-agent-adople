import logging
import requests
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class TenTimesScraper(BaseScraper):
    def __init__(self):
        super().__init__("10times", "https://10times.com/usa")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Checking 10times live conferences...")
        events: List[RawEventData] = []
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            resp = requests.get("https://10times.com/usa", headers=headers, timeout=10)
            if resp.status_code == 200:
                pass
        except Exception as e:
            logger.warning(f"[{self.source_name}] 10times live endpoint error: {e}")

        logger.info(f"[{self.source_name}] Harvested {len(events)} events from 10times.")
        return events
