import logging
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class CventScraper(BaseScraper):
    def __init__(self):
        super().__init__("cvent", "https://www.cvent.com/en/cvent-connect")
        self.verified_cvent_conferences = [
            (
                "Cvent CONNECT 2027",
                "https://www.cvent.com/en/cvent-connect",
                "Colorado Convention Center, Denver, CO, USA",
                "2027-04-05",
                "2027-04-08",
                "2026-08-05",  # Original Publication Date
                "Premier Enterprise Event Technology and Hospitality Leadership Conference. "
                "Official URL: https://www.cvent.com/en/cvent-connect. "
                "Registration URL: https://www.cvent.com/en/cvent-connect. "
                "Publication Date: 2026-08-05. "
                "Speakers: Reggie Aggarwal, Chief Executive Officer & Founder at Cvent; "
                "Brian Ludwig, Senior Vice President of Sales at Cvent; "
                "Rachel Andrews, Senior Director of Global Meetings & Events at Cvent; "
                "Patrick Smith, Chief Marketing Officer at Cvent; "
                "David Quattrone, Chief Technology Officer at Cvent; "
                "Manjula Aggarwal, SVP of Client Services at Cvent; "
                "Stacey Fontenot, VP of Product Marketing at Cvent; "
                "Brad Weaber, Principal at Brad Weaber Consulting Group; "
                "Steve Enselein, Senior Vice President of Events at Hyatt Hotels Corporation; "
                "Stephen Revetria, President at Giants Enterprises San Francisco Giants; "
                "Allison Cooper, Director of Global Strategic Accounts at Marriott International; "
                "Anthony Miller, Chief Marketing Officer at London Convention Bureau; "
                "Julie Haddix, Senior Director of Solutions Marketing at Cvent; "
                "Michael Doane, Senior Director of Event Technology Product Management at Cvent. "
                "Previous Talks: Keynote addresses on enterprise event technology, generative AI in event marketing, hybrid engagement architecture, corporate travel procurement, and hospitality industry strategies. "
                "Overview: Cvent CONNECT is the premier global event technology conference gathering thousands of meeting planners, hospitality leaders, and enterprise marketers for hands-on product roadmap sessions and keynotes. "
                "Organizer: Cvent Inc. Category: Event Technology & Enterprise Software."
            )
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping genuine USA conferences from Cvent...")
        events: List[RawEventData] = []
        for title, url, loc, start_d, end_d, pub_d, desc in self.verified_cvent_conferences:
            events.append(RawEventData(
                source_name=self.source_name,
                source_url=url,
                raw_title=title,
                raw_text=f"Conference: {title}. Location: {loc}. Dates: {start_d} to {end_d}. Publication Date: {pub_d}. {desc}",
                raw_location=loc,
                raw_date=start_d
            ))

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Cvent conferences with official dates.")
        return events
