import logging
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}

GOVEVENTS_URLS = [
    "https://govevents.in/trainings-calander/",
    "https://govevents.in/courses-online-learning/",
    "https://govevents.in/workshop/"
]

class GovEventsScraper(BaseScraper):
    def __init__(self):
        super().__init__("govevents", "https://govevents.in/")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping government & productivity conferences from GovEvents...")
        events: List[RawEventData] = []
        seen_titles = set()

        for page_url in GOVEVENTS_URLS:
            try:
                resp = requests.get(page_url, headers=HEADERS, timeout=12)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                headings = soup.find_all(['h2', 'h3', 'h4', 'article'])

                for h in headings:
                    title = h.get_text(strip=True)
                    if len(title) < 15 or title in seen_titles:
                        continue

                    # Filter irrelevant menu items
                    lower = title.lower()
                    if any(term in lower for term in ['menu', 'privacy', 'contact', 'skip to', 'navigation', 'search']):
                        continue

                    seen_titles.add(title)
                    link = page_url
                    a_tag = h.find('a', href=True)
                    if a_tag:
                        href = a_tag['href']
                        link = href if href.startswith('http') else f"https://govevents.in{href}"

                    raw_text = (
                        f"Conference / Training Title: {title}\n"
                        f"Organizer: GovEvents\n"
                        f"Official URL: {link}\n"
                        f"Source: GovEvents (govevents.in)\n"
                        f"Country: USA\n"
                    )

                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=link,
                        raw_title=title,
                        raw_text=raw_text,
                        raw_location="USA",
                        raw_date=None
                    ))

                    logger.info(f"[{self.source_name}] Harvested event: {title}")

            except Exception as e:
                logger.error(f"[{self.source_name}] Error crawling {page_url}: {e}")

        logger.info(f"[{self.source_name}] Finished live scraping. Harvested {len(events)} events.")
        return events
