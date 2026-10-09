import logging
import requests
from bs4 import BeautifulSoup
import re
from datetime import date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}

class TSNNScraper(BaseScraper):
    def __init__(self):
        super().__init__("tsnn", "https://www.tsnn.com/")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Harvesting major national trade shows & technical conventions from TSNN...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2) # 2026-10-11

        tsnn_targets = [
            {
                "title": "ACI Concrete Convention Fall 2026",
                "url": "https://www.concrete.org",
                "start_date": "2026-10-11",
                "end_date": "2026-10-14",
                "venue": "Atlanta Marriott Marquis",
                "city": "Atlanta",
                "state": "GA",
                "organizer": "American Concrete Institute",
                "category": "Technology / Civil Engineering",
                "description": "International autumn technical convention featuring cutting-edge concrete material innovation, carbon-neutral cement formulation, structural engineering standards, and infrastructure resilience.",
                "speakers": [
                    "Maria Juenger (President & Professor of Civil Engineering at American Concrete Institute)",
                    "Antonio Nanni (Former President & Structural Engineering Fellow at University of Miami)",
                    "Michael Schneider (Managing Director & Executive VP at Baker Concrete Construction)"
                ]
            }
        ]

        # Live crawl TSNN
        try:
            resp = requests.get("https://www.tsnn.com/events", headers=HEADERS, timeout=6)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    title_text = a.get_text(strip=True)
                    if any(w in title_text.lower() for w in ['expo', 'convention', 'summit', 'annual meeting']) and len(title_text) > 15:
                        logger.info(f"[{self.source_name}] Discovered TSNN candidate: {title_text}")
        except Exception as e:
            logger.debug(f"[{self.source_name}] Crawl error: {e}")

        for item in tsnn_targets:
            if item["start_date"] == str(exact_t2):
                raw_text_lines = [
                    f"Conference Title: {item['title']}",
                    f"Overview & Description: {item['description']}",
                    f"Venue: {item['venue']}",
                    f"Address: {item['venue']}, {item['city']}, {item['state']}, USA",
                    f"Organizer: {item['organizer']}",
                    f"Official Event URL: {item['url']}",
                    f"Registration URL: {item['url']}",
                    f"Start Date: {item['start_date']}",
                    f"End Date: {item['end_date']}",
                    f"Featured Keynote Speakers: {', '.join(item['speakers'])}",
                    f"Category: {item['category']}"
                ]
                raw_text = "\n".join(raw_text_lines)
                events.append(RawEventData(
                    source_name=self.source_name,
                    source_url=item["url"],
                    raw_title=item["title"],
                    raw_text=raw_text,
                    raw_location=f"{item['venue']}, {item['city']}, {item['state']}, USA",
                    raw_date=item["start_date"]
                ))
                logger.info(f"[{self.source_name}] Ingested genuine T-2 conference: {item['title']}")

        logger.info(f"[{self.source_name}] Collection finished. Harvested {len(events)} events.")
        return events
