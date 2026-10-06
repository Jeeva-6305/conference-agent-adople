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

EVENTSEYE_USA_URL = "https://www.eventseye.com/fairs/c1_trade-shows_usa-united-states-of-america.html"

class EventsEyeScraper(BaseScraper):
    def __init__(self):
        super().__init__("eventseye", EVENTSEYE_USA_URL)

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping genuine USA conferences & trade shows from EventsEye...")
        events: List[RawEventData] = []

        try:
            resp = requests.get(self.base_url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                logger.warning(f"[{self.source_name}] Received status {resp.status_code}")
                return events

            soup = BeautifulSoup(resp.text, 'html.parser')
            table_rows = soup.find_all('tr')

            for tr in table_rows:
                tds = tr.find_all('td')
                if len(tds) < 4:
                    continue

                title_td = tds[0]
                link_el = title_td.find('a', href=True)
                if not link_el:
                    continue

                title = link_el.get_text(strip=True)
                full_desc = title_td.get_text(' ', strip=True)
                rel_url = link_el['href']
                full_url = f"https://www.eventseye.com/fairs/{rel_url}" if not rel_url.startswith('http') else rel_url

                venue_city = tds[2].get_text(' ', strip=True)
                date_text = tds[3].get_text(' ', strip=True)

                # Parse date e.g. "10/08/2026 3 days" or "10/08/2026"
                m_date = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', date_text)
                if not m_date:
                    continue

                raw_start_date = m_date.group(1)
                try:
                    dt_start = datetime.strptime(raw_start_date, '%m/%d/%Y').date()
                    start_date_str = dt_start.isoformat()
                except Exception:
                    continue

                # Check duration in days
                duration_days = 1
                m_days = re.search(r'(\d+)\s+days?', date_text, re.I)
                if m_days:
                    try:
                        duration_days = int(m_days.group(1))
                    except ValueError:
                        duration_days = 1

                end_date_str = (dt_start + timedelta(days=max(0, duration_days - 1))).isoformat()

                raw_text = (
                    f"Conference Title: {title}\n"
                    f"Description: {full_desc}\n"
                    f"Location / Venue: {venue_city}, USA\n"
                    f"Start Date: {start_date_str}\n"
                    f"End Date: {end_date_str}\n"
                    f"Official Event Page: {full_url}\n"
                    f"Source: EventsEye Trade Show & Conference Directory\n"
                    f"Country: USA"
                )

                events.append(RawEventData(
                    source_name=self.source_name,
                    source_url=full_url,
                    raw_title=title,
                    raw_text=raw_text,
                    raw_location=f"{venue_city}, USA",
                    raw_date=start_date_str
                ))

                logger.info(f"[{self.source_name}] Harvested conference: {title} ({start_date_str}) in {venue_city}")

        except Exception as e:
            logger.error(f"[{self.source_name}] Error during live scraping: {e}")

        logger.info(f"[{self.source_name}] Finished live scraping. Harvested {len(events)} events.")
        return events
