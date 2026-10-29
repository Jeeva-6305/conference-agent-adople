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

                            # Format dates to YYYY-MM-DD
                            s_date = start_date[:10] if len(start_date) >= 10 else ""
                            e_date = end_date[:10] if len(end_date) >= 10 else s_date

                            # Filter past events
                            today_str = str(date.today())
                            if s_date and s_date < today_str:
                                continue

                            if len(events) >= 20:
                                break

                            seen_urls.add(url)

                            loc = ev.get('location', {})
                            venue = loc.get('name', '') if isinstance(loc, dict) else ''
                            full_location = f"{venue}, {default_city}".strip(', ')

                            desc = ev.get('description', '')
                            organizer_name = ""
                            official_site_url = url
                            speaker_text = ""

                            # Deep scrape individual event page for complete description and real speakers
                            try:
                                ev_resp = requests.get(url, headers=HEADERS, timeout=6)
                                if ev_resp.status_code == 200:
                                    ev_soup = BeautifulSoup(ev_resp.text, 'html.parser')
                                    text_all = ev_soup.get_text('\n', strip=True)
                                    if "About the event" in text_all:
                                        idx = text_all.find("About the event")
                                        desc = text_all[idx:idx+2500]
                                    elif "About this Event" in text_all:
                                        idx = text_all.find("About this Event")
                                        desc = text_all[idx:idx+2500]
                                    
                                    # Extract organizer if available
                                    m_org = re.search(r"organized by\s+([^.\n]+)", text_all, re.I)
                                    if m_org:
                                        organizer_name = m_org.group(1).strip()

                                    # Extract speakers block if available
                                    for spk_marker in ["Featured Speakers", "Speakers", "Keynote Speakers"]:
                                        if spk_marker in text_all:
                                            spk_idx = text_all.find(spk_marker)
                                            speaker_text = text_all[spk_idx:spk_idx+1200]
                                            break

                                    # Check for external official conference URL
                                    for a_link in ev_soup.find_all('a', href=True):
                                        h = a_link['href'].strip()
                                        if h.startswith('http') and not any(ign in h.lower() for ign in ['allevents.in', 'google.com', 'facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com']):
                                            official_site_url = h.rstrip('.,;)\"')
                                            break

                            except Exception as ev_err:
                                logger.debug(f"Deep scrape error for {url}: {ev_err}")

                            raw_text_parts = [
                                f"Conference Title: {name}",
                                f"Overview: {desc}",
                                f"Venue / Location: {full_location}",
                                f"Start Date: {s_date}",
                                f"End Date: {e_date}",
                                f"Organizer: {organizer_name}",
                                f"Official Event URL: {official_site_url}",
                                f"Registration URL: {url}",
                                f"Source: All Events (allevents.in)",
                                f"Country: USA"
                            ]
                            if speaker_text:
                                raw_text_parts.append(f"Agenda & Speakers Section:\n{speaker_text}")

                            raw_text = "\n".join(raw_text_parts)

                            events.append(RawEventData(
                                source_name=self.source_name,
                                source_url=official_site_url,
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
