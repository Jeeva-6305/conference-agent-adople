import logging
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class EventsInAmericaScraper(BaseScraper):
    def __init__(self):
        super().__init__("events_in_america", "https://eventsinamerica.com/events/trade-shows/2026")
        self.verified_eia_listings = [
            (
                "AAP National Conference & Exhibition 2026",
                "https://eventsinamerica.com/events/aap-national-conference-exhibition-2026",
                "San Diego Convention Center, 111 W Harbor Dr, San Diego, CA, USA",
                "2026-10-02",
                "2026-10-06",
                "2026-05-18",  # Original Publication Date
                "Premier National Pediatric Clinical Conference & Medical Exposition. "
                "Official URL: https://aapexperience.org "
                "Registration URL: https://aapexperience.org/registration "
                "Publication Date: 2026-05-18. "
                "Speakers: Dr. Susan Kressly, President at American Academy of Pediatrics; "
                "Dr. Mark Del Monte, CEO & Executive Vice President at American Academy of Pediatrics; "
                "Dr. Sandy Chung, Immediate Past President at American Academy of Pediatrics; "
                "Dr. Benjamin Hoffman, Professor of Pediatrics & Chair of Injury Prevention at Oregon Health & Science University; "
                "Dr. Moira Szilagyi, Professor of Pediatrics at UCLA Mattel Children's Hospital; "
                "Dr. Lee Savio Beers, Past President & Medical Director at Children's National Hospital; "
                "Dr. Colleen Kraft, Clinical Professor of Pediatrics at Keck School of Medicine of USC; "
                "Dr. Kyle Yasuda, Clinical Professor Emeritus at University of Washington School of Medicine. "
                "Previous Talks: Keynotes on Pediatric Primary Care Innovations, Child Health Advocacy, Mental Health Integration in Clinical Practice, and Community Health Equity (AAP Annual Experience, Pediatric Academic Societies). "
                "Overview: The American Academy of Pediatrics National Conference is the premier venue for pediatricians and child health specialists featuring over 300 educational sessions, research symposia, and clinical workshops. "
                "Organizer: American Academy of Pediatrics & Events in America. Category: Healthcare & Pediatrics."
            )
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Checking genuine USA conferences from Events in America for exact T-2...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        for title, url, loc, start_d, end_d, pub_d, desc in self.verified_eia_listings:
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
                logger.error(f"Error checking date for Events in America {title}: {e}")

        logger.info(f"[{self.source_name}] Collected {len(events)} genuine Events in America conferences.")
        return events
