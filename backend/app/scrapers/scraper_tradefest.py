import logging
import json
import re
from datetime import date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class TradefestScraper(BaseScraper):
    def __init__(self):
        super().__init__("tradefest", "https://tradefest.io/en")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Harvesting USA conventions & trade summits from Tradefest...")
        events: List[RawEventData] = []
        seen_urls = set()

        try:
            soup = self.fetch_soup(self.base_url, timeout=12)
            if not soup:
                logger.warning(f"[{self.source_name}] Could not fetch Tradefest homepage")
                return events

            candidate_paths = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/en/event/' in href and href not in seen_urls:
                    seen_urls.add(href)
                    candidate_paths.append(href)

            logger.info(f"[{self.source_name}] Discovered {len(candidate_paths)} candidate events. Fetching details...")

            for path in candidate_paths[:15]:
                full_url = path if path.startswith("http") else f"https://tradefest.io{path}"
                try:
                    ev_soup = self.fetch_soup(full_url, timeout=8)
                    if not ev_soup:
                        continue

                    event_data = None
                    for s in ev_soup.find_all('script', type='application/ld+json'):
                        try:
                            d = json.loads(s.string)
                            if d.get('@type') in ['Event', 'BusinessEvent']:
                                event_data = d
                                break
                        except Exception:
                            pass

                    if not event_data:
                        continue

                    title = event_data.get('name', '').strip()
                    start_date_raw = event_data.get('startDate', '')
                    end_date_raw = event_data.get('endDate', start_date_raw)
                    start_date = start_date_raw[:10] if len(start_date_raw) >= 10 else ""
                    end_date = end_date_raw[:10] if len(end_date_raw) >= 10 else start_date

                    loc = event_data.get('location', {})
                    if not isinstance(loc, dict):
                        loc = {}
                    addr = loc.get('address', {})
                    if isinstance(addr, dict):
                        country = addr.get('addressCountry', 'USA')
                        city = addr.get('addressLocality', '')
                        street = addr.get('streetAddress', '')
                    else:
                        country = 'USA'
                        city = ''
                        street = ''

                    venue = loc.get('name', 'Convention Center')
                    
                    # Verify event is in USA
                    if country not in ['US', 'USA', 'United States', 'US of A']:
                        continue

                    desc = event_data.get('description', f"{title} convention in {city}, USA.")
                    full_loc = f"{venue}, {street}, {city}, USA".strip(', ')

                    # Check for official conference website link on the page
                    official_site_url = full_url
                    for a_link in ev_soup.find_all('a', href=True):
                        h = a_link['href'].strip()
                        if h.startswith('http') and not any(ign in h.lower() for ign in ['tradefest.io', 'google.com', 'facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com']):
                            official_site_url = h
                            break

                    raw_text = (
                        f"Conference Title: {title}\n"
                        f"Overview & Description: {desc}\n"
                        f"Venue: {venue}\n"
                        f"Address: {full_loc}\n"
                        f"Official Event URL: {official_site_url}\n"
                        f"Registration URL: {full_url}\n"
                        f"Start Date: {start_date}\n"
                        f"End Date: {end_date}\n"
                        f"Source: Tradefest\n"
                        f"Country: USA"
                    )

                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=official_site_url,
                        raw_title=title,
                        raw_text=raw_text,
                        raw_location=full_loc,
                        raw_date=start_date
                    ))
                    logger.info(f"[{self.source_name}] Harvested genuine conference: {title} ({start_date}) in {city}")

                except Exception as ev_err:
                    logger.debug(f"[{self.source_name}] Error parsing {full_url}: {ev_err}")

        except Exception as e:
            logger.error(f"[{self.source_name}] Scrape error: {e}")

        logger.info(f"[{self.source_name}] Finished collection. Harvested {len(events)} events.")
        return events
