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

ALLEVENTS_URLS = [
    ("https://allevents.in/united-states/conferences", "USA"),
    ("https://allevents.in/new-york/conferences", "New York, NY, USA"),
    ("https://allevents.in/san-francisco/conferences", "San Francisco, CA, USA"),
    ("https://allevents.in/chicago/conferences", "Chicago, IL, USA"),
    ("https://allevents.in/austin/conferences", "Austin, TX, USA")
]

NON_CONFERENCE_KEYWORDS = [
    "workshop", "webinar", "happy hour", "bar crawl", "speed dating",
    "singles", "karaoke", "bootcamp", "mixer", "dinner", "party",
    "networking lunch", "social mixer", "class", "brunch", "walk",
    "comic con", "paleyfest", "talks with", "artform", "art show",
    "stage", "screening", "exhibition", "concert", "comedy", "showcase",
    "festival", "wellness walk", "becky g", "almodovar", "koom"
]

class AllEventsScraper(BaseScraper):
    def __init__(self):
        super().__init__("allevents", "https://allevents.in/united-states/conferences")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping genuine USA conferences from AllEvents...")
        events: List[RawEventData] = []
        seen_urls = set()

        for page_url, default_city in ALLEVENTS_URLS:
            try:
                resp = requests.get(page_url, headers=HEADERS, timeout=12)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                scripts = soup.find_all('script', type='application/ld+json')

                for s in scripts:
                    try:
                        data = json.loads(s.string)
                        items = []
                        if isinstance(data, list):
                            items = data
                        elif isinstance(data, dict):
                            if 'itemListElement' in data:
                                items = [el.get('item', {}) for el in data['itemListElement']]
                            elif data.get('@type') in ['Event', 'BusinessEvent']:
                                items = [data]

                        for ev in items:
                            name = ev.get('name', '').strip()
                            url = ev.get('url', '').strip()
                            start_date = ev.get('startDate', '')
                            end_date = ev.get('endDate', start_date)

                            if not name or not url or url in seen_urls:
                                continue

                            # Filter non-conferences
                            name_lower = name.lower()
                            if any(k in name_lower for k in NON_CONFERENCE_KEYWORDS):
                                continue

                            seen_urls.add(url)

                            # Format dates to YYYY-MM-DD
                            s_date = start_date[:10] if len(start_date) >= 10 else ""
                            e_date = end_date[:10] if len(end_date) >= 10 else s_date

                            loc = ev.get('location', {})
                            venue = loc.get('name', '') if isinstance(loc, dict) else ''
                            full_location = f"{venue}, {default_city}".strip(', ')

                            desc = ev.get('description', '')
                            organizer_name = ""

                            # Deep scrape individual event page for complete description and real speakers
                            try:
                                ev_resp = requests.get(url, headers=HEADERS, timeout=10)
                                if ev_resp.status_code == 200:
                                    ev_soup = BeautifulSoup(ev_resp.text, 'html.parser')
                                    text_all = ev_soup.get_text('\n', strip=True)
                                    if "About the event" in text_all:
                                        idx = text_all.find("About the event")
                                        desc = text_all[idx:idx+3500]
                                    elif "About this Event" in text_all:
                                        idx = text_all.find("About this Event")
                                        desc = text_all[idx:idx+3500]
                                    
                                    # Extract organizer if available
                                    m_org = re.search(r"organized by\s+([^.\n]+)", text_all, re.I)
                                    if m_org:
                                        organizer_name = m_org.group(1).strip()
                            except Exception as ev_err:
                                logger.debug(f"Deep scrape error for {url}: {ev_err}")

                            raw_text = (
                                f"Conference Title: {name}\n"
                                f"Overview: {desc}\n"
                                f"Venue / Location: {full_location}\n"
                                f"Start Date: {s_date}\n"
                                f"End Date: {e_date}\n"
                                f"Organizer: {organizer_name}\n"
                                f"Official Event URL: {url}\n"
                                f"Registration URL: {url}\n"
                                f"Source: All Events (allevents.in)\n"
                                f"Country: USA"
                            )

                            events.append(RawEventData(
                                source_name=self.source_name,
                                source_url=url,
                                raw_title=name,
                                raw_text=raw_text,
                                raw_location=full_location,
                                raw_date=s_date
                            ))

                            logger.info(f"[{self.source_name}] Harvested conference: {name} ({s_date}) in {full_location}")

                    except Exception:
                        pass

            except Exception as e:
                logger.error(f"[{self.source_name}] Error crawling {page_url}: {e}")

        logger.info(f"[{self.source_name}] Finished live scraping. Harvested {len(events)} events.")
        return events
