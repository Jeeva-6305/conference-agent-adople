import logging
import json
import re
from datetime import datetime, date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

MEETUP_URLS = [
    ("https://www.meetup.com/find/?keywords=conference&location=us--ca--san-francisco", "San Francisco, CA, USA"),
    ("https://www.meetup.com/find/?keywords=conference&location=us--ny--new-york", "New York, NY, USA"),
    ("https://www.meetup.com/find/?keywords=summit&location=us", "USA")
]

NON_CONFERENCE_KEYWORDS = [
    "happy hour", "bar crawl", "speed dating", "singles", "karaoke", "bootcamp",
    "dinner", "party", "social mixer", "class", "brunch", "walk", "comic con",
    "comedy", "festival", "screening", "game night", "board game", "pub crawl"
]

CONFERENCE_TERMS = [
    "conference", "summit", "symposium", "forum", "congress", "expo", "annual meeting"
]

class MeetupScraper(BaseScraper):
    def __init__(self):
        super().__init__("meetup", "https://www.meetup.com/find/?keywords=conference&location=us--ca--san-francisco")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scanning Meetup for genuine USA conferences...")
        events: List[RawEventData] = []
        seen_urls = set()

        for page_url, default_loc in MEETUP_URLS:
            try:
                soup = self.fetch_soup(page_url, timeout=10)
                if not soup:
                    continue

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

                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            name = item.get('name', '').strip()
                            url = item.get('url', '').strip()
                            start_at = item.get('startDate', '')
                            end_at = item.get('endDate', start_at)
                            desc = item.get('description', '')

                            if not name or not url or url in seen_urls:
                                continue

                            name_lower = name.lower()
                            if any(bad in name_lower for bad in NON_CONFERENCE_KEYWORDS):
                                continue

                            # Must contain a conference indicator or have conference in description
                            if not any(t in name_lower for t in CONFERENCE_TERMS) and not any(t in desc.lower() for t in CONFERENCE_TERMS):
                                continue

                            seen_urls.add(url)
                            start_date = start_at[:10] if len(start_at) >= 10 else ""
                            end_date = end_at[:10] if len(end_at) >= 10 else start_date

                            loc = item.get('location', {})
                            venue = loc.get('name', '') if isinstance(loc, dict) else ''
                            full_loc = f"{venue}, {default_loc}".strip(', ')

                            raw_text = (
                                f"Conference Title: {name}\n"
                                f"Overview & Description: {desc}\n"
                                f"Venue: {venue}\n"
                                f"Address: {full_loc}\n"
                                f"Official Event URL: {url}\n"
                                f"Registration URL: {url}\n"
                                f"Start Date: {start_date}\n"
                                f"End Date: {end_date}\n"
                                f"Source: Meetup Conferences\n"
                                f"Country: USA"
                            )

                            events.append(RawEventData(
                                source_name=self.source_name,
                                source_url=url,
                                raw_title=name,
                                raw_text=raw_text,
                                raw_location=full_loc,
                                raw_date=start_date
                            ))
                            logger.info(f"[{self.source_name}] Harvested conference: {name} ({start_date})")

                    except Exception as err:
                        logger.debug(f"[{self.source_name}] JSON-LD parse error: {err}")

            except Exception as e:
                logger.error(f"[{self.source_name}] Error crawling {page_url}: {e}")

        logger.info(f"[{self.source_name}] Harvested {len(events)} genuine conferences from Meetup.")
        return events
