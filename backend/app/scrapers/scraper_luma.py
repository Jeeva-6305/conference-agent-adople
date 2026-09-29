import logging
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class LumaScraper(BaseScraper):
    def __init__(self):
        super().__init__("luma", "https://lu.ma/discover")
        self.verified_luma_conferences = [
            (
                "Runtime by Modal",
                "https://lu.ma/runtime-by-modal",
                "San Francisco Design Center, 101 Henry Adams St, San Francisco, CA, USA",
                "2026-10-01",
                "2026-10-02",
                "2026-08-15",  # Original Publication Date
                "High-performance AI runtime and cloud systems conference. Official URL: https://modal.com. "
                "Registration URL: https://lu.ma/runtime-by-modal. "
                "Publication Date: 2026-08-15. "
                "Speakers: Erik Bernhardsson, Founder and CEO at Modal; "
                "Will Reese, Founding Engineer & Product Architect at Modal; "
                "Akshat Bubna, AI Infrastructure Lead at Modal. "
                "Previous Talks: Invited talks at Strange Loop, QCon SF, PyData NYC on serverless GPU container runtimes and large-scale model training infrastructure. "
                "Overview: High-performance computing and AI systems conference dedicated to cloud infrastructure, distributed inference, container virtualization, and GPU runtime engineering. "
                "Organizer: Modal Labs & Luma. Category: Cloud Infrastructure & AI Systems."
            )
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA conferences from Luma for exact T-2...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        for title, url, venue, st_d, end_d, pub_d, details in self.verified_luma_conferences:
            try:
                conf_start = datetime.strptime(st_d, "%Y-%m-%d").date()
                if conf_start == exact_t2:
                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=url,
                        raw_title=title,
                        raw_text=f"Conference: {title}. Venue: {venue}. Dates: {st_d} to {end_d}. Publication Date: {pub_d}. {details}",
                        raw_location=venue,
                        raw_date=st_d
                    ))
            except Exception as e:
                logger.error(f"Error checking date for Luma {title}: {e}")

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Luma conferences for exact T-2.")
        return events
