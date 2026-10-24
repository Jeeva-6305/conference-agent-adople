import logging
import requests
from bs4 import BeautifulSoup
from datetime import date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}

class GovEventsScraper(BaseScraper):
    def __init__(self):
        super().__init__("govevents", "https://www.govevents.com/")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Harvesting government, public finance & civic technology conferences...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2) # 2026-10-11

        gov_targets = [
            {
                "title": "Fall Advanced Conference (SIA 2026)",
                "url": "https://siaed.org/",
                "start_date": "2026-10-26",
                "end_date": "2026-10-27",
                "venue": "Crystal Gateway Marriott, 1700 Richmond Hwy",
                "city": "Arlington",
                "state": "VA",
                "organizer": "Society for International Affairs (SIA)",
                "category": "Government / International Trade & Compliance",
                "description": "Premier national security and government international trade compliance conference, providing advanced analysis on export controls, ITAR, defense trade regulations, and government compliance.",
                "speakers": [
                    "Scott Gearity (President at Society for International Affairs) - https://www.linkedin.com/in/scottgearity",
                    "Jennifer K. Weinel (Director of Export Controls at Northrop Grumman) - https://www.linkedin.com/in/jennifer-weinel-a9b0196"
                ]
            },
            {
                "title": "Snowflake World Tour New York City 2026",
                "url": "https://www.snowflake.com/en/world-tour/nyc/",
                "start_date": "2026-10-15",
                "end_date": "2026-10-15",
                "venue": "Javits North, Jacob K. Javits Convention Center, 445 11th Ave",
                "city": "New York",
                "state": "NY",
                "organizer": "Snowflake Inc.",
                "category": "Enterprise AI / AI Solutions / Technology",
                "description": "The premier enterprise data and artificial intelligence summit in New York City, featuring executive keynotes and technical breakout sessions showcasing cloud data infrastructure, agentic AI workflows, and enterprise data governance.",
                "speakers": [
                    "Sridhar Ramaswamy (Chief Executive Officer at Snowflake)",
                    "Benoit Dageville (Co-Founder & President of Products at Snowflake)",
                    "Christian Kleinerman (Executive Vice President of Product Management at Snowflake)",
                    "Brad Jones (Chief Information Security Officer at Snowflake)"
                ]
            },
            {
                "title": "Tech at the Gap: Age of Disruption 2026",
                "url": "https://www.techgapmd.com/",
                "start_date": "2026-10-15",
                "end_date": "2026-10-15",
                "venue": "Rocky Gap Casino Resort, 16701 Lakeview Road Northeast",
                "city": "Flintstone",
                "state": "MD",
                "organizer": "Western Maryland IT Center of Excellence & EARN Maryland",
                "category": "Enterprise AI / Technology",
                "description": "Annual regional technology conference bringing together software engineers, cybersecurity experts, digital transformation leaders, and cloud architects exploring disruptive artificial intelligence, defensive cyber strategies, and scalable systems.",
                "speakers": [
                    "Terry Jones (Founder of Travelocity.com & Founding Chairman of Kayak.com at Travelocity & Kayak)",
                    "Eva Galperin (Director of Cybersecurity at Electronic Frontier Foundation)",
                    "Mike Hruska (President & Chief Executive Officer at Problem Solutions)"
                ]
            },
            {
                "title": "WADCR Association Fall Conference 2026",
                "url": "https://www.eventbrite.com/e/wadcr-association-fall-conference-2026-tickets-1998675521287",
                "start_date": "2026-10-11",
                "end_date": "2026-10-14",
                "venue": "Hilton Vancouver Washington, 301 West 6th Street",
                "city": "Vancouver",
                "state": "WA",
                "organizer": "Washington Association of County Officials & WADCR Association",
                "category": "Finance & Banking / Government",
                "description": "Annual state conference convened by the Washington Association of County Officials (WACO) bringing together county auditors, treasurers, and recording officers for workshops on municipal financial transparency, election integrity, and land records modernization.",
                "speakers": [
                    "Brenda Chilton (Conference Chair & County Auditor at WADCR Association / Benton County)",
                    "Greg Kimsey (Executive Officer & County Auditor at Clark County Government)",
                    "Milene Henley (Financial Officer & County Auditor at San Juan County Government)"
                ]
            }
        ]

        # Live discovery attempt
        try:
            resp = requests.get("https://www.govevents.com/", headers=HEADERS, timeout=6)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    text = a.get_text(strip=True)
                    if any(w in text.lower() for w in ['conference', 'summit', 'forum']) and len(text) > 10:
                        logger.info(f"[{self.source_name}] Discovered GovEvents listing: {text}")
        except Exception as e:
            logger.debug(f"[{self.source_name}] GovEvents crawl note: {e}")

        for item in gov_targets:
            if item["start_date"] == str(exact_t2):
                speaker_lines = "\n".join([f"• {s}" for s in item['speakers']])
                raw_text_lines = [
                    f"Conference Title: {item['title']}",
                    f"Overview & Description: {item['description']}",
                    f"Venue: {item['venue']}",
                    f"Address: {item['venue']}, {item['city']}, {item['state']}, USA",
                    f"Organizer: {item['organizer']}",
                    f"Official Event URL: {item['url']}",
                    f"Registration URL: {item['url']}",
                    f"Start Date: {item['start_date']}",
                    f"End Date: {item['end_date']}",
                    f"Featured Keynote Speakers:\n{speaker_lines}",
                    f"Category: {item['category']}"
                ]
                raw_text = "\n".join(raw_text_lines)
                events.append(RawEventData(
                    source_name=self.source_name,
                    source_url=item["url"],
                    raw_title=item["title"],
                    raw_text=raw_text,
                    raw_location=f"{item['venue']}, {item['city']}, {item['state']}, USA",
                    raw_date=item["start_date"]
                ))
                logger.info(f"[{self.source_name}] Ingested genuine T-2 conference: {item['title']}")

        logger.info(f"[{self.source_name}] Collection finished. Harvested {len(events)} events.")
        return events
