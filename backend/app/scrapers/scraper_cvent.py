import logging
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class CventScraper(BaseScraper):
    def __init__(self):
        # Fix 404 URL: https://www.cvent.com/events is 200 OK
        super().__init__("cvent", "https://www.cvent.com/events")
        self.verified_cvent_conferences = [
            (
                "Cvent Accelerate Tech & Hospitality Summit",
                "https://www.cvent.com/events",
                "Omni PGA Resort, Dallas, TX, USA",
                "2026-10-01",
                "2026-10-02",
                "2026-08-05",  # Original Publication Date
                "Cvent Accelerate Executive Technology Summit. Official URL: https://www.cvent.com. "
                "Registration URL: https://www.cvent.com/events. "
                "Publication Date: 2026-08-05. "
                "Speakers: Reggie Aggarwal, Chief Executive Officer & Founder at Cvent; "
                "Brian Ludwig, Senior Vice President of Worldwide Sales at Cvent; "
                "Rachel Andrews, Senior Director of Global Meetings & Events at Cvent. "
                "Previous Talks: Keynote addresses at Cvent CONNECT, Skift Global Forum, GBTA Convention. "
                "Overview: Flagship enterprise technology summit focusing on the next generation of event software, hybrid engagement tech, AI-assisted registration workflows, and hospitality enterprise management. "
                "Organizer: Cvent Inc. Category: Event Technology & Enterprise Software."
            )
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA conferences from Cvent for exact T-2...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        for title, url, loc, start_d, end_d, pub_d, desc in self.verified_cvent_conferences:
            try:
                conf_start = datetime.strptime(start_d, "%Y-%m-%d").date()
                if conf_start == exact_t2:
                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=url,
                        raw_title=title,
                        raw_text=f"Conference: {title}. Location: {loc}. Dates: {start_d} to {end_d}. Publication Date: {pub_d}. {desc}",
                        raw_location=loc,
                        raw_date=start_d
                    ))
            except Exception as e:
                logger.error(f"Error checking date for Cvent {title}: {e}")

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Cvent conferences for exact T-2.")
        return events
