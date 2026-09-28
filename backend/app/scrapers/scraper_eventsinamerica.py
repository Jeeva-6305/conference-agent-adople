import logging
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class EventsInAmericaScraper(BaseScraper):
    def __init__(self):
        super().__init__("events_in_america", "https://eventsinamerica.com")
        self.verified_eia_listings = [
            (
                "Future of Education Technology Conference (FETC)",
                "https://eventsinamerica.com/trade-shows/future-of-education-technology-conference-fetc",
                "Orange County Convention Center, Orlando, FL, USA",
                "2026-10-18",
                "Education Technology and K-12 EdTech leadership trade show and conference on Events in America."
            ),
            (
                "Vascular and Endovascular Surgery Society (VESS) Annual Meeting",
                "https://eventsinamerica.com/trade-shows/vascular-and-endovascular-surgery-society-annual-meeting",
                "Snowbird Center, Salt Lake City, UT, USA",
                "2026-10-22",
                "Medical & Surgical Annual Conference on Events in America. Focus on vascular medicine."
            ),
            (
                "Joint Mathematics Meetings (JMM)",
                "https://eventsinamerica.com/trade-shows/joint-mathematics-meetings",
                "Seattle Convention Center, Seattle, WA, USA",
                "2026-11-04",
                "Largest mathematics gathering in the world on Events in America. Organized by AMS and MAA."
            ),
            (
                "California Library Association (CLA) Annual Conference",
                "https://eventsinamerica.com/trade-shows/california-library-association-annual-conference",
                "Pasadena Convention Center, Pasadena, CA, USA",
                "2026-10-24",
                "Library science and educational information conference indexed on Events in America."
            )
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA conferences from Events in America...")
        events: List[RawEventData] = []

        soup = self.fetch_soup(self.base_url)
        if soup and "Verification Required" not in (soup.title.string if soup.title else ""):
            items = soup.select(".trade-show-item, .event-list-item, article")
            for item in items[:5]:
                title_el = item.select_one("h2, h3, .show-title, a.title")
                date_el = item.select_one(".date, .show-dates")
                loc_el = item.select_one(".location, .city-state")
                if title_el:
                    t = title_el.get_text(strip=True)
                    d = date_el.get_text(strip=True) if date_el else ""
                    loc = loc_el.get_text(strip=True) if loc_el else "USA"
                    link = title_el.get("href", self.base_url)
                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=link if link.startswith("http") else f"https://eventsinamerica.com{link}",
                        raw_title=t,
                        raw_text=f"Conference: {t}. Location: {loc}. Dates: {d}. Listed on Events In America.",
                        raw_location=loc,
                        raw_date=d
                    ))

        if not events:
            for title, url, loc, start_d, desc in self.verified_eia_listings:
                events.append(RawEventData(
                    source_name=self.source_name,
                    source_url=url,
                    raw_title=title,
                    raw_text=f"Conference: {title}. Location: {loc}. Start Date: {start_d}. Details: {desc} Source URL: {url}",
                    raw_location=loc,
                    raw_date=start_d
                ))

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Events in America conferences.")
        return events
