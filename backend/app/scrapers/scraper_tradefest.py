import logging
import requests
from bs4 import BeautifulSoup
import json
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

TRADEFEST_VENUE_URLS = [
    "https://tradefest.io/en/selection/events-at-mandalay-bay-convention-center",
    "https://tradefest.io/en/selection/events-at-jacob-k-javits-convention-center",
    "https://tradefest.io/en/selection/events-at-orange-county-convention-center"
]

class TradefestScraper(BaseScraper):
    def __init__(self):
        super().__init__("tradefest", "https://tradefest.io/en/home")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping genuine USA trade shows & conferences from Tradefest...")
        events: List[RawEventData] = []
        seen_urls = set()
        event_paths = []

        # Step 1: Discover genuine event pages from US convention center showcases
        for venue_url in TRADEFEST_VENUE_URLS:
            try:
                resp = requests.get(venue_url, headers=HEADERS, timeout=12)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if '/en/event/' in href and href not in seen_urls:
                        seen_urls.add(href)
                        event_paths.append(href)

            except Exception as e:
                logger.error(f"[{self.source_name}] Error crawling {venue_url}: {e}")

        logger.info(f"[{self.source_name}] Found {len(event_paths)} live event URLs on Tradefest.")

        # Step 2: Fetch detailed event metadata via Schema.org JSON-LD
        for path in event_paths[:6]:
            full_url = f"https://tradefest.io{path}" if not path.startswith("http") else path
            try:
                resp = requests.get(full_url, headers=HEADERS, timeout=5)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                event_data = None

                for s in soup.find_all('script', type='application/ld+json'):
                    try:
                        d = json.loads(s.string)
                        if d.get('@type') == 'Event':
                            event_data = d
                            break
                    except Exception:
                        pass

                if not event_data:
                    continue

                name = event_data.get('name', '').strip()
                desc = event_data.get('description', '').strip()
                start_date = event_data.get('startDate', '')
                end_date = event_data.get('endDate', start_date)

                if not name or not start_date:
                    continue

                loc = event_data.get('location', {})
                venue_name = loc.get('name', '') if isinstance(loc, dict) else ''
                addr = loc.get('address', {}) if isinstance(loc, dict) else {}
                city = addr.get('addressLocality', '') if isinstance(addr, dict) else ''
                street = addr.get('streetAddress', '') if isinstance(addr, dict) else ''
                country = addr.get('addressCountry', 'USA') if isinstance(addr, dict) else 'USA'
                full_loc = f"{venue_name}, {street}, {city}, USA".strip(', ')

                s_date = start_date[:10]
                e_date = end_date[:10] if end_date else s_date

                raw_text = (
                    f"Conference Title: {name}\n"
                    f"Description: {desc}\n"
                    f"Venue: {venue_name}\n"
                    f"Location / Address: {full_loc}\n"
                    f"Start Date: {s_date}\n"
                    f"End Date: {e_date}\n"
                    f"Official URL: {full_url}\n"
                    f"Registration URL: {full_url}\n"
                    f"Source: Tradefest (tradefest.io)\n"
                    f"Country: USA"
                )

                events.append(RawEventData(
                    source_name=self.source_name,
                    source_url=full_url,
                    raw_title=name,
                    raw_text=raw_text,
                    raw_location=full_loc,
                    raw_date=s_date
                ))

                logger.info(f"[{self.source_name}] Harvested conference: {name} ({s_date}) at {venue_name}")

            except Exception as e:
                logger.error(f"[{self.source_name}] Error parsing {full_url}: {e}")

        logger.info(f"[{self.source_name}] Finished live scraping. Harvested {len(events)} events.")
        return events
