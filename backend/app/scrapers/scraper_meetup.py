import logging
import json
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class MeetupScraper(BaseScraper):
    def __init__(self):
        super().__init__("meetup", "https://www.meetup.com/find/?keywords=conference&location=us--ca--san-francisco")
        self.us_locations = [
            "us--ca--san-francisco",
            "us--ny--new-york",
            "us--tx--austin",
            "us--il--chicago"
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA conferences from Meetup across US regions...")
        events: List[RawEventData] = []
        seen_urls = set()

        for loc_slug in self.us_locations:
            url = f"https://www.meetup.com/find/?keywords=conference&location={loc_slug}"
            soup = self.fetch_soup(url)
            if not soup:
                continue

            for script in soup.find_all("script", type="application/ld+json"):
                if not script.string:
                    continue
                try:
                    data = json.loads(script.string)
                    items = data if isinstance(data, list) else data.get("itemListElement", [])

                    for entry in items:
                        item = entry.get("item", entry) if isinstance(entry, dict) else {}
                        name = item.get("name")
                        event_url = item.get("url")
                        start_date = item.get("startDate")
                        loc = item.get("location", {})
                        addr = loc.get("address", {}) if isinstance(loc, dict) else {}
                        venue = loc.get("name", "Convention Venue") if isinstance(loc, dict) else "Convention Venue"
                        city = addr.get("addressLocality", "") if isinstance(addr, dict) else ""
                        state = addr.get("addressRegion", "") if isinstance(addr, dict) else ""
                        country = (addr.get("addressCountry") or "").lower() if isinstance(addr, dict) else ""

                        # Filter for conferences in the United States
                        if name and event_url and event_url not in seen_urls:
                            if country in ["us", "usa", "united states"] or "conference" in name.lower():
                                seen_urls.add(event_url)
                                events.append(RawEventData(
                                    source_name=self.source_name,
                                    source_url=event_url,
                                    raw_title=name,
                                    raw_text=f"Conference: {name}. Venue: {venue}. City: {city}, {state}, USA. Start Date: {start_date}. Meetup Event URL: {event_url}",
                                    raw_location=f"{city}, {state}, USA" if city else "USA",
                                    raw_date=str(start_date) if start_date else None
                                ))
                except Exception as e:
                    logger.debug(f"Meetup JSON-LD parse error: {e}")

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Meetup conferences.")
        return events
