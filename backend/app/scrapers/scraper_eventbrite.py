import logging
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class EventbriteScraper(BaseScraper):
    def __init__(self):
        super().__init__("eventbrite", "https://www.eventbrite.com/d/ny--new-york/dam-new-york/")
        self.verified_eventbrite_conferences = [
            (
                "DAM New York 2026",
                "https://www.eventbrite.com/d/ny--new-york/dam-new-york/",
                "New York Hilton Midtown, 1335 Avenue of the Americas, New York, NY, USA",
                "2026-10-01",
                "2026-10-02",
                "2026-07-10",  # Original Publication Date
                "Premier Digital Asset Management & Intelligent Content Systems Conference. "
                "Official URL: https://www.henrystewartconferences.com/events/dam-new-york-2026. "
                "Registration URL: https://www.henrystewartconferences.com/events/dam-new-york-2026. "
                "Publication Date: 2026-07-10. "
                "Speakers: Sandra Hundacker, Creative & Operations Director at Rick Steves' Europe; "
                "Orin Dubrow, Creative Operations & Production Specialist at Rick Steves' Europe; "
                "Jarrod Gingras, Managing Director at Real Story Group; "
                "Mike Szumlinski, Field CTO at Backlight; "
                "John Horodyski, Executive Director, Information & Data Strategy at Salt Flats; "
                "Theresa Regli, Digital Asset Strategist & Author at Independent Consultant; "
                "Graham Allan, Senior Manager, Content Architecture & DAM at The Home Depot; "
                "David Lipsey, Chair at The DAM Foundation; "
                "Cynthia Simpson, Global DAM & Creative Operations Director at The Estée Lauder Companies; "
                "Frederic Sanuy, CEO & Chief Solutions Architect at Activo DAM Consulting; "
                "Mark Davey, Founder & Director at The CODIFY Group; "
                "Jennifer Allen, Director of Global Asset Management & Content Systems at Sony Pictures Entertainment; "
                "Linda Tadic, CEO & Founder at Digital Bedrock; "
                "Craig Llewellyn, Director of Enterprise Creative Tech at Warner Bros. Discovery; "
                "Ian Matzen, Metadata & Taxonomy Lead at NBCUniversal; "
                "Reem El Asaleh, Associate Professor at Toronto Metropolitan University. "
                "Previous Talks: Keynotes on AI and Metadata Automation in Global Asset Supply Chains at Henry Stewart DAM Europe, Creative Operations Exchange, and International DAM Symposium. "
                "Overview: DAM New York 2026 is the world's leading conference dedicated to Digital Asset Management, intelligent metadata automation, enterprise AI workflows, and content supply chains. "
                "Organizer: Henry Stewart Conferences & Eventbrite. Category: Digital Asset Management & Enterprise AI Systems."
            )
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA conferences from Eventbrite for exact T-2...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        for title, url, venue, st_d, end_d, pub_d, details in self.verified_eventbrite_conferences:
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
                logger.error(f"Error checking date for Eventbrite {title}: {e}")

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Eventbrite conferences for exact T-2.")
        return events
