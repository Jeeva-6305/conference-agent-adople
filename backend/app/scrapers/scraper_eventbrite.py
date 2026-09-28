import logging
import json
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class EventbriteScraper(BaseScraper):
    def __init__(self):
        super().__init__("eventbrite", "https://www.eventbrite.com/d/united-states/conferences/")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA conferences from Eventbrite...")
        events: List[RawEventData] = []
        soup = self.fetch_soup(self.base_url)
        
        if not soup:
            return events

        # Parse genuine conferences from JSON-LD schema
        for script in soup.find_all("script", type="application/ld+json"):
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else data.get("itemListElement", [])
                
                for entry in items:
                    item = entry.get("item", entry) if isinstance(entry, dict) else {}
                    name = item.get("name")
                    url = item.get("url")
                    start_date = item.get("startDate")
                    loc = item.get("location", {})
                    addr = loc.get("address", {}) if isinstance(loc, dict) else {}
                    venue = loc.get("name", "Convention Center") if isinstance(loc, dict) else "Convention Center"
                    city = addr.get("addressLocality", "") if isinstance(addr, dict) else ""
                    state = addr.get("addressRegion", "") if isinstance(addr, dict) else ""
                    country = (addr.get("addressCountry") or "").upper() if isinstance(addr, dict) else ""

                    # Must be a real event in the US
                    if name and url and country in ["US", "USA", "UNITED STATES"]:
                        events.append(RawEventData(
                            source_name=self.source_name,
                            source_url=url,
                            raw_title=name,
                            raw_text=f"Conference Name: {name}. Venue: {venue}. City: {city}, {state}, USA. Start Date: {start_date}. Eventbrite Ticket Page: {url}",
                            raw_location=f"{city}, {state}, USA" if city else "USA",
                            raw_date=str(start_date) if start_date else None
                        ))
            except Exception as e:
                logger.debug(f"JSON-LD parse error: {e}")

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Eventbrite conferences.")
        return events
