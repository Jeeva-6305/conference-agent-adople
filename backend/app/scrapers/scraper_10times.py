import logging
from datetime import date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class TenTimesScraper(BaseScraper):
    def __init__(self):
        super().__init__("10times", "https://10times.com/usa")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Checking 10times live conferences...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        try:
            resp = self.fetch_page("https://10times.com/usa", timeout=10)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                # Parse live event rows from 10times listing table
                for row in soup.find_all(['tr', 'div'], class_=lambda c: c and any(k in str(c).lower() for k in ['event', 'row', 'listing'])):
                    title_elem = row.find(['a', 'h2', 'h3'], class_=lambda c: c and 'title' in str(c).lower()) or row.find('a', href=True)
                    if not title_elem:
                        continue
                    title = title_elem.get_text(strip=True)
                    if not title or len(title) < 5 or any(b in title.lower() for b in ['login', 'sign up', 'contact', 'about us']):
                        continue
                    event_url = title_elem.get('href', '')
                    if event_url and not event_url.startswith('http'):
                        event_url = f"https://10times.com{event_url}"

                    events.append(RawEventData(
                        raw_title=title,
                        raw_text=f"Conference Title: {title}\nOfficial Event URL: {event_url}\nSource: 10times\nCountry: USA",
                        source_url=event_url or self.base_url,
                        source_name=self.source_name
                    ))
            elif resp and resp.status_code in (403, 429):
                logger.warning(f"[{self.source_name}] Live endpoint restricted (HTTP {resp.status_code}, status: unverified_access_restricted). No events scraped.")
        except Exception as e:
            logger.warning(f"[{self.source_name}] 10times live crawl notice: {e}")

        logger.info(f"[{self.source_name}] Harvested {len(events)} events from 10times.")
        return events
