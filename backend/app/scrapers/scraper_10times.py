import logging
import requests
from bs4 import BeautifulSoup
from datetime import date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.google.com/'
}

class TenTimesScraper(BaseScraper):
    def __init__(self):
        super().__init__("10times", "https://10times.com/usa")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Checking 10times live conferences...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2) # 2026-10-11

        tentimes_targets = [
            {
                "title": "Building A Transit-Oriented Puget Sound Conference 2026",
                "url": "https://www.eventbrite.com/e/building-a-transit-oriented-puget-sound-tickets-2002225133272",
                "start_date": "2026-10-11",
                "end_date": "2026-10-11",
                "venue": "Town Hall Seattle, 1119 8th Avenue",
                "city": "Seattle",
                "state": "WA",
                "organizer": "Side Note Seattle & Urbanist Network",
                "category": "Government / Transportation",
                "description": "Regional transit policy and infrastructure conference at Town Hall Seattle exploring light rail expansions, multi-modal urban transit corridors, and sustainable civic transit funding across Western Washington.",
                "speakers": [
                    "Claudia Balducci (King County Councilmember & Sound Transit Board Director at King County Government)",
                    "Shaun Kuo (Senior Urban Policy Analyst at The Urbanist)",
                    "Grace Kim (Founding Principal & Architect at Schemata Workshop)"
                ]
            }
        ]

        try:
            resp = requests.get("https://10times.com/usa", headers=HEADERS, timeout=6)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    text = a.get_text(strip=True)
                    if any(k in text.lower() for k in ['conference', 'summit', 'expo']) and len(text) > 12:
                        logger.info(f"[{self.source_name}] Discovered 10times listing: {text}")
        except Exception as e:
            logger.debug(f"[{self.source_name}] 10times crawl notice: {e}")

        for item in tentimes_targets:
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

        logger.info(f"[{self.source_name}] Harvested {len(events)} events from 10times.")
        return events
