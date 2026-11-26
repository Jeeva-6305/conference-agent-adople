import logging
import json
import re
from datetime import date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper, clean_html_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)


class TradefestScraper(BaseScraper):
    def __init__(self):
        super().__init__("tradefest", "https://tradefest.io/en")

    def scrape(self) -> List[RawEventData]:
        win_start, win_end = self.get_discovery_window()
        logger.info(f"[{self.source_name}] Harvesting USA conventions & trade summits from Tradefest ({win_start}..{win_end})...")
        events: List[RawEventData] = []
        seen_urls = set()
        candidate_paths = []

        # 1. Crawl Tradefest entry pages
        for page_url in ["https://tradefest.io/en", "https://tradefest.io/en/search?countries=US"]:
            try:
                soup = self.fetch_soup(page_url, timeout=12)
                if not soup:
                    continue
                for a in soup.find_all('a', href=True):
                    href = a['href'].split("?")[0].strip()
                    if '/en/event/' in href:
                        full_u = href if href.startswith("http") else f"https://tradefest.io{href}"
                        if full_u not in seen_urls:
                            seen_urls.add(full_u)
                            candidate_paths.append(full_u)
            except Exception as e:
                logger.debug(f"[{self.source_name}] Page crawl note for {page_url}: {e}")

        # 2. Sanctioned Tavily search specifically for target month/year USA Tradefest events
        month_name = win_start.strftime("%B")
        t_query = f'site:tradefest.io/en/event "{month_name} {win_start.year}" ("United States" OR "USA" OR "Las Vegas" OR "New York" OR "Chicago" OR "Boston" OR "San Francisco")'
        for r in self.tavily_search(t_query, max_results=10):
            r_url = (r.get("url") or "").split("?")[0].strip()
            if r_url and "/en/event/" in r_url and r_url not in seen_urls:
                seen_urls.add(r_url)
                candidate_paths.insert(0, r_url)

        logger.info(f"[{self.source_name}] Discovered {len(candidate_paths)} candidate event URLs. Fetching details...")

        for full_url in candidate_paths[:45]:
            try:
                ev_soup = self.fetch_soup(full_url, timeout=8)
                if not ev_soup:
                    continue

                event_data = None
                for s in ev_soup.find_all('script', type='application/ld+json'):
                    try:
                        d = json.loads(s.string or "")
                        if isinstance(d, dict) and d.get('@type') in ['Event', 'BusinessEvent']:
                            event_data = d
                            break
                    except Exception:
                        pass

                if not event_data:
                    continue

                title = clean_html_text(event_data.get('name', ''))
                start_date_raw = event_data.get('startDate', '')
                end_date_raw = event_data.get('endDate', start_date_raw)
                start_date = start_date_raw[:10] if len(start_date_raw) >= 10 else ""
                end_date = end_date_raw[:10] if len(end_date_raw) >= 10 else start_date

                if not start_date or not self.is_date_in_window(start_date, win_start, win_end):
                    continue

                loc = event_data.get('location', {})
                if not isinstance(loc, dict):
                    loc = {}
                addr = loc.get('address', {})
                if isinstance(addr, dict):
                    country = clean_html_text(addr.get('addressCountry', 'USA'))
                    city = clean_html_text(addr.get('addressLocality', ''))
                    street = clean_html_text(addr.get('streetAddress', ''))
                else:
                    country = 'USA'
                    city = ''
                    street = ''

                venue = clean_html_text(loc.get('name', ''))
                if country not in ['US', 'USA', 'United States', 'US of A']:
                    continue

                desc = clean_html_text(event_data.get('description', f"{title} convention in {city}, USA."))
                full_loc = f"{venue}, {street}, {city}, USA".strip(', ')

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
                    "Source: Tradefest\n"
                    "Country: USA"
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

        logger.info(f"[{self.source_name}] Finished collection. Harvested {len(events)} events.")
        return events
