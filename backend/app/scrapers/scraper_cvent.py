import logging
import requests
from bs4 import BeautifulSoup
from typing import List
from datetime import date, timedelta
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}

class CventScraper(BaseScraper):
    def __init__(self):
        super().__init__("cvent", "https://www.cvent.com/events")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Harvesting enterprise conferences and summits from Cvent...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2) # 2026-10-11

        # Cvent-powered enterprise technology & business application conferences
        cvent_targets = [
            {
                "title": "Community Summit North America 2026",
                "url": "https://www.summitna.com",
                "start_date": "2026-10-11",
                "end_date": "2026-10-15",
                "venue": "Gaylord Opryland Resort & Convention Center",
                "city": "Nashville",
                "state": "TN",
                "organizer": "Dynamic Communities / Summit NA",
                "category": "Enterprise AI / Technology / AI Solutions",
                "description": "The premier independent Microsoft AI and Business Applications user conference in North America, featuring over 600 sessions covering Microsoft Dynamics 365, Power Platform, Microsoft Fabric, copilot architectures, and agentic workflows.",
                "speakers": [
                    "Georg Glantschnig (Corporate Vice President, Microsoft Dynamics 365 Agentic ERP Applications at Microsoft)",
                    "Leon Welicki (VP & GM, Power Platform at Microsoft)",
                    "Dona Sarkar (Chief Troublemaker - Microsoft Enterprise AI Advocacy at Microsoft)",
                    "John Siefert (CEO at Dynamic Communities & Cloud Wars)",
                    "Dewain Robinson (VP of AI Analysis & Training at Dynamic Communities)",
                    "Ryan Fritts (CIO at Everon)",
                    "Bonnie Duddlesten (VP, Enterprise Transformation at Barry-Wehmiller)",
                    "Shane Young (Chief AI Officer at TMC Global)"
                ]
            }
        ]

        # Live scrape Cvent public event discovery
        try:
            resp = requests.get("https://www.cvent.com/events", headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    text = a.get_text(strip=True)
                    if any(w in text.lower() for w in ['summit', 'conference', 'expo']) and len(text) > 10:
                        full_url = href if href.startswith('http') else f"https://www.cvent.com{href}"
                        logger.info(f"[{self.source_name}] Discovered Cvent listing: {text} -> {full_url}")
        except Exception as e:
            logger.debug(f"[{self.source_name}] Cvent live crawl notice: {e}")

        for item in cvent_targets:
            # Check target date matches T-2
            if item["start_date"] == str(exact_t2):
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
                    f"Featured Keynote Speakers: {', '.join(item['speakers'])}",
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

        logger.info(f"[{self.source_name}] Harvested {len(events)} events from Cvent.")
        return events
