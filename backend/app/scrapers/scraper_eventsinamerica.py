import logging
from datetime import date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class EventsInAmericaScraper(BaseScraper):
    def __init__(self):
        super().__init__("events_in_america", "https://eventsinamerica.com/trade-shows")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Checking Events in America live conferences...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        try:
            resp = self.fetch_page("https://eventsinamerica.com/trade-shows", timeout=10)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for card in soup.find_all(['div', 'article'], class_=lambda c: c and any(k in str(c).lower() for k in ['show', 'event', 'card', 'item'])):
                    link = card.find('a', href=True)
                    if not link:
                        continue
                    title = link.get_text(strip=True)
                    if not title or len(title) < 5:
                        continue
                    event_url = link['href']
                    if event_url and not event_url.startswith('http'):
                        event_url = f"https://eventsinamerica.com{event_url}"

                    events.append(RawEventData(
                        raw_title=title,
                        raw_text=f"Conference Title: {title}\nOfficial URL: {event_url}\nSource: Events in America\nCountry: USA",
                        source_url=event_url or self.base_url,
                        source_name=self.source_name
                    ))
            elif resp and resp.status_code in (403, 429):
                logger.warning(f"[{self.source_name}] Live endpoint restricted (HTTP {resp.status_code}, status: unverified_access_restricted). No events scraped.")
        except Exception as e:
            logger.warning(f"[{self.source_name}] Events in America live endpoint error: {e}")

        logger.info(f"[{self.source_name}] Harvested {len(events)} events from Events in America.")
        return events
