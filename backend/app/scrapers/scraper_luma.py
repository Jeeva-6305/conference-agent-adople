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
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

LUMA_CITY_URLS = [
    ("https://lu.ma/sf", "San Francisco, CA, USA"),
    ("https://lu.ma/nyc", "New York, NY, USA"),
    ("https://lu.ma/austin", "Austin, TX, USA")
]

CONFERENCE_TERMS = ["conference", "summit", "symposium", "forum", "congress", "expo", "con", "day"]

class LumaScraper(BaseScraper):
    def __init__(self):
        super().__init__("luma", "https://lu.ma/discover")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping genuine tech conferences from Luma...")
        events: List[RawEventData] = []
        seen_urls = set()

        for page_url, default_loc in LUMA_CITY_URLS:
            try:
                resp = requests.get(page_url, headers=HEADERS, timeout=12)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                next_script = soup.find('script', id='__NEXT_DATA__')
                if not next_script or not next_script.string:
                    continue

                data = json.loads(next_script.string)
                page_data = data.get('props', {}).get('pageProps', {}).get('initialData', {}).get('data', {})
                raw_events = page_data.get('events', [])

                for item in raw_events:
                    ev = item.get('event', {})
                    name = ev.get('name', '').strip()
                    url_slug = ev.get('url', '')
                    start_at = ev.get('start_at', '')
                    end_at = ev.get('end_at', '')

                    if not name or not url_slug:
                        continue

                    full_url = f"https://lu.ma/{url_slug}"
                    if full_url in seen_urls:
                        continue

                    # Filter for conferences, summits, and symposiums
                    name_lower = name.lower()
                    if not any(t in name_lower for t in CONFERENCE_TERMS):
                        continue

                    seen_urls.add(full_url)
                    start_date = start_at[:10] if len(start_at) >= 10 else ""
                    end_date = end_at[:10] if len(end_at) >= 10 else start_date

                    raw_text = (
                        f"Conference Title: {name}\n"
                        f"Source: Luma Tech Discovery\n"
                        f"Official URL: {full_url}\n"
                        f"Registration URL: {full_url}\n"
                        f"Start Date: {start_date}\n"
                        f"End Date: {end_date}\n"
                        f"Location: {default_loc}"
                    )

                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=full_url,
                        raw_title=name,
                        raw_text=raw_text,
                        raw_location=default_loc,
                        raw_date=start_date
                    ))

                    logger.info(f"[{self.source_name}] Harvested genuine Luma conference: {name} ({start_date})")

            except Exception as e:
                logger.error(f"[{self.source_name}] Error crawling {page_url}: {e}")

        logger.info(f"[{self.source_name}] Live Luma collection finished. Total events: {len(events)}")
        return events
