import logging
from datetime import date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class GovEventsScraper(BaseScraper):
    def __init__(self):
        super().__init__("govevents", "https://www.govevents.com/")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Harvesting government, public finance & civic technology conferences...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        try:
            resp = self.fetch_page("https://www.govevents.com/", timeout=10)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for item in soup.find_all(['div', 'li'], class_=lambda c: c and any(k in str(c).lower() for k in ['event', 'item', 'listing'])):
                    link = item.find('a', href=True)
                    if not link:
                        continue
                    title = link.get_text(strip=True)
                    if not title or len(title) < 5:
                        continue
                    event_url = link['href']
                    if event_url and not event_url.startswith('http'):
                        event_url = f"https://www.govevents.com{event_url}"

                    events.append(RawEventData(
                        raw_title=title,
                        raw_text=f"Conference Title: {title}\nOfficial URL: {event_url}\nSource: GovEvents\nCountry: USA",
                        source_url=event_url or self.base_url,
                        source_name=self.source_name
                    ))
            elif resp and resp.status_code in (403, 429):
                logger.warning(f"[{self.source_name}] Live endpoint restricted (HTTP {resp.status_code}, status: unverified_access_restricted). No events scraped.")
        except Exception as e:
            logger.warning(f"[{self.source_name}] GovEvents crawl note: {e}")

        logger.info(f"[{self.source_name}] Collection finished. Harvested {len(events)} events.")
        return events
