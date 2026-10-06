import logging
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime, date, timedelta
from typing import List, Optional
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}

DISCOVERY_URLS = [
    'https://www.eventbrite.com/d/united-states/conferences/',
    'https://www.eventbrite.com/d/united-states/business--conferences/',
    'https://www.eventbrite.com/d/united-states/science-and-tech--conferences/',
    'https://www.eventbrite.com/d/united-states/health--conferences/'
]

NON_CONFERENCE_KEYWORDS = [
    "workshop", "webinar", "happy hour", "bar crawl", "speed dating",
    "singles", "karaoke", "bootcamp", "mixer", "dinner", "party",
    "networking lunch", "social mixer", "class", "brunch"
]

class EventbriteScraper(BaseScraper):
    def __init__(self):
        super().__init__("eventbrite", "https://www.eventbrite.com/d/united-states/conferences/")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping genuine USA conferences from Eventbrite...")
        events: List[RawEventData] = []
        seen_urls = set()
        candidate_items = []

        # Step 1: Collect live candidate conference listings
        for disc_url in DISCOVERY_URLS:
            try:
                resp = requests.get(disc_url, headers=HEADERS, timeout=12)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                scripts = soup.find_all('script', type='application/ld+json')
                for s in scripts:
                    try:
                        data = json.loads(s.string)
                        items = []
                        if isinstance(data, dict) and 'itemListElement' in data:
                            items = [el.get('item', {}) for el in data['itemListElement']]
                        elif isinstance(data, list):
                            items = data

                        for item in items:
                            url = item.get('url')
                            name = item.get('name', '')
                            if not url or url in seen_urls:
                                continue
                            
                            # Filter out non-conferences
                            name_lower = name.lower()
                            if any(k in name_lower for k in NON_CONFERENCE_KEYWORDS):
                                continue

                            seen_urls.add(url)
                            candidate_items.append((name, url))
                    except Exception:
                        pass
            except Exception as e:
                logger.error(f"[{self.source_name}] Error crawling {disc_url}: {e}")

        logger.info(f"[{self.source_name}] Found {len(candidate_items)} live candidate conference URLs. Fetching details...")

        # Step 2: Fetch detailed event pages and extract structured metadata
        for name, url in candidate_items:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                event_data = None

                for s in soup.find_all('script', type='application/ld+json'):
                    try:
                        d = json.loads(s.string)
                        if d.get('@type') in ['BusinessEvent', 'Event']:
                            event_data = d
                            break
                    except Exception:
                        pass

                if not event_data:
                    continue

                title = event_data.get('name', name).strip()
                desc = event_data.get('description', '').strip()
                start_iso = event_data.get('startDate', '')
                end_iso = event_data.get('endDate', '')

                # Parse dates to YYYY-MM-DD
                start_date = start_iso[:10] if len(start_iso) >= 10 else ""
                end_date = end_iso[:10] if len(end_iso) >= 10 else start_date

                # Location details
                loc = event_data.get('location', {})
                venue_name = loc.get('name', '')
                addr = loc.get('address', {})
                city = addr.get('addressLocality', '')
                state = addr.get('addressRegion', '')
                country = addr.get('addressCountry', 'USA')
                street = addr.get('streetAddress', '')
                full_loc = f"{venue_name}, {street}, {city}, {state}, {country}".strip(', ')

                # Verify event is in USA
                if country not in ['US', 'USA', 'United States'] and 'US' not in state:
                    continue

                # Organizer
                organizer_data = event_data.get('organizer', {})
                organizer_name = organizer_data.get('name', '') if isinstance(organizer_data, dict) else ""
                organizer_url = organizer_data.get('url', '') if isinstance(organizer_data, dict) else ""

                # Performers / Speakers
                performers = event_data.get('performer', [])
                performer_names = []
                performer_details = []
                if isinstance(performers, list):
                    for p in performers:
                        if isinstance(p, dict):
                            p_name = p.get('name', '').strip()
                            p_url = p.get('url', '')
                            if p_name and p_name.lower() not in title.lower():
                                performer_names.append(p_name)
                                if p_url:
                                    performer_details.append(f"{p_name} ({p_url})")
                                else:
                                    performer_details.append(p_name)

                # FAQ / Agenda / Description details
                faq_text = ""
                for s in soup.find_all('script', type='application/ld+json'):
                    try:
                        fd = json.loads(s.string)
                        if fd.get('@type') == 'FAQPage':
                            for q in fd.get('mainEntity', []):
                                q_name = q.get('name', '')
                                q_ans = q.get('acceptedAnswer', {}).get('text', '')
                                faq_text += f"\n{q_name}: {q_ans}"
                    except Exception:
                        pass

                # Ticket / Registration URL
                offers = event_data.get('offers', [])
                reg_url = url
                pub_date = ""
                if isinstance(offers, list) and len(offers) > 0:
                    first_offer = offers[0]
                    reg_url = first_offer.get('url', url)
                    valid_from = first_offer.get('validFrom', '')
                    if valid_from:
                        pub_date = valid_from[:10]

                # Compose rich raw text for AI Agent verification
                raw_text_parts = [
                    f"Conference Title: {title}",
                    f"Overview & Description: {desc}",
                    f"Venue: {venue_name}",
                    f"Address: {street}, {city}, {state}, {country}",
                    f"Organizer: {organizer_name}",
                    f"Official Event URL: {url}",
                    f"Registration URL: {reg_url}",
                    f"Start Date: {start_date}",
                    f"End Date: {end_date}",
                ]
                if pub_date:
                    raw_text_parts.append(f"Publication / Announcement Date: {pub_date}")
                if performer_names:
                    raw_text_parts.append(f"Featured Speakers / Keynotes: {', '.join(performer_details)}")
                if faq_text:
                    raw_text_parts.append(f"Conference Schedule & FAQ Details: {faq_text}")

                raw_text = "\n".join(raw_text_parts)

                events.append(RawEventData(
                    source_name=self.source_name,
                    source_url=url,
                    raw_title=title,
                    raw_text=raw_text,
                    raw_location=full_loc,
                    raw_date=start_date
                ))

                logger.info(f"[{self.source_name}] Harvested genuine conference: {title} ({start_date}) in {city}, {state}")

            except Exception as e:
                logger.error(f"[{self.source_name}] Error parsing details for {url}: {e}")

        logger.info(f"[{self.source_name}] Live collection finished. Harvested {len(events)} genuine conferences.")
        return events
