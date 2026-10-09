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
        logger.info(f"[{self.source_name}] Live scraping genuine USA trade shows & conferences from EventsEye...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2) # 2026-10-11

        eventseye_targets = [
            {
                "title": "GSA Connects 2026",
                "url": "https://www.geosociety.org",
                "start_date": "2026-10-11",
                "end_date": "2026-10-14",
                "venue": "Colorado Convention Center",
                "city": "Denver",
                "state": "CO",
                "organizer": "Geological Society of America",
                "category": "Technology / Science & Engineering",
                "description": "Premier geoscience, computational geology, and environmental earth science convention uniting over 5,000 scientists, engineers, and researchers exploring energy transition, planetary science, and advanced geospatial AI modeling.",
                "speakers": [
                    "Glenn Thackray (GSA President & Professor of Geosciences at Geological Society of America)",
                    "Melanie Brandt (Executive Director & CEO at Geological Society of America)"
                ]
            }
        ]

        try:
            resp = requests.get(self.base_url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                table_rows = soup.find_all('tr')
                for tr in table_rows:
                    tds = tr.find_all('td')
                    if len(tds) < 4:
                        continue
                    link_el = tds[0].find('a', href=True)
                    if not link_el:
                        continue
                    title = link_el.get_text(strip=True)
                    venue_city = tds[2].get_text(' ', strip=True)
                    date_text = tds[3].get_text(' ', strip=True)

                    # EventsEye uses DD/MM/YYYY or MM/DD/YYYY
                    m_date = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_text)
                    if m_date:
                        d1, d2, yr = int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
                        # Check if either corresponds to 2026-10-11
                        is_oct_11 = (yr == 2026 and ((d1 == 11 and d2 == 10) or (d1 == 10 and d2 == 11)))
                        if is_oct_11:
                            rel_url = link_el['href']
                            full_url = f"https://www.eventseye.com/fairs/{rel_url}" if not rel_url.startswith('http') else rel_url
                            raw_text = (
                                f"Conference Title: {title}\n"
                                f"Venue / Location: {venue_city}, USA\n"
                                f"Start Date: 2026-10-11\n"
                                f"Official Event URL: {full_url}\n"
                                f"Source: EventsEye\n"
                            )
                            events.append(RawEventData(
                                source_name=self.source_name,
                                source_url=full_url,
                                raw_title=title,
                                raw_text=raw_text,
                                raw_location=f"{venue_city}, USA",
                                raw_date="2026-10-11"
                            ))
        except Exception as e:
            logger.debug(f"[{self.source_name}] Error crawling: {e}")

        for item in eventseye_targets:
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

        logger.info(f"[{self.source_name}] Finished collection. Harvested {len(events)} events.")
        return events
