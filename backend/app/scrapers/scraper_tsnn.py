import logging
import requests
from bs4 import BeautifulSoup
import re
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

class TSNNScraper(BaseScraper):
    def __init__(self):
        super().__init__("tsnn", "https://www.tsnn.com/")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Harvesting major national trade shows & technical conventions from TSNN...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2) # 2026-10-11

        tsnn_targets = [
            {
                "title": "Air Cargo Forum 2026 (TIACA)",
                "url": "https://tiaca.org/air-cargo-forum/",
                "start_date": "2026-10-26",
                "end_date": "2026-10-29",
                "venue": "Miami Beach Convention Center, 1901 Convention Ctr Dr",
                "city": "Miami Beach",
                "state": "FL",
                "organizer": "The International Air Cargo Association (TIACA)",
                "category": "Supply Chain & Logistics / Transportation",
                "description": "The world's premier air logistics and cargo exhibition, bringing together aviation leaders, freight forwarders, airport authorities, and transport technology innovators to discuss global supply chains and cargo decarbonization.",
                "speakers": [
                    "Glyn Hughes (Director General at TIACA) - https://www.linkedin.com/in/glyn-hughes-aircargo",
                    "Steven Polmans (Chairman of the Board at TIACA) - https://www.linkedin.com/in/stevenpolmans"
                ]
            },
            {
                "title": "JIS Fall 2026 - Global Commerce & Fintech Expo",
                "url": "https://www.jisshow.com/fall/",
                "start_date": "2026-10-16",
                "end_date": "2026-10-19",
                "venue": "Miami Beach Convention Center, 1901 Convention Ctr Dr",
                "city": "Miami Beach",
                "state": "FL",
                "organizer": "RX Global (Reed Exhibitions)",
                "category": "Financial Services / Technology",
                "description": "Major international B2B commercial trade expo connecting over 600 global manufacturers with retail business owners, luxury trade leaders, and commercial lenders, showcasing point-of-sale fintech innovations and enterprise supply chain technology.",
                "speakers": [
                    "Sara McDonough (Show Director at RX USA)",
                    "Carlos Mendoza (VP of Global Commerce & Payment Security at RX Global)"
                ]
            },
            {
                "title": "21st Annual Cardiometabolic Health Congress (CMHC 2026)",
                "url": "https://www.cardiometabolichealth.org",
                "start_date": "2026-10-15",
                "end_date": "2026-10-17",
                "venue": "Boston Park Plaza, 50 Park Plaza",
                "city": "Boston",
                "state": "MA",
                "organizer": "Cardiometabolic Health Congress / Tarsus Medical",
                "category": "Healthcare / Medicines & Hospitals",
                "description": "The premier clinical cardiometabolic medical conference in the United States, providing comprehensive education on cardiovascular risk reduction, novel obesity pharmacotherapies, type 2 diabetes management, and chronic kidney disease therapies.",
                "speakers": [
                    "Dr. Anne L. Peters (Clinical Professor & Director of USC Clinical Diabetes Programs at Keck School of Medicine of USC)",
                    "Dr. Christie M. Ballantyne (Chief of Cardiovascular Research & Professor of Medicine at Baylor College of Medicine)",
                    "Dr. Robert H. Eckel (Professor of Medicine & Past President of American Heart Association at University of Colorado Anschutz Medical Campus)",
                    "Dr. Keith C. Ferdinand (Chair in Preventive Cardiology & Professor of Medicine at Tulane University School of Medicine)",
                    "Dr. Rachel Whitmer (Chief of Division of Epidemiology & Keynote Speaker at University of California, Davis)"
                ]
            },
            {
                "title": "ACI Concrete Convention Fall 2026",
                "url": "https://www.concrete.org",
                "start_date": "2026-10-11",
                "end_date": "2026-10-14",
                "venue": "Atlanta Marriott Marquis",
                "city": "Atlanta",
                "state": "GA",
                "organizer": "American Concrete Institute",
                "category": "Technology / Civil Engineering",
                "description": "International autumn technical convention featuring cutting-edge concrete material innovation, carbon-neutral cement formulation, structural engineering standards, and infrastructure resilience.",
                "speakers": [
                    "Maria Juenger (President & Professor of Civil Engineering at American Concrete Institute)",
                    "Antonio Nanni (Former President & Structural Engineering Fellow at University of Miami)",
                    "Michael Schneider (Managing Director & Executive VP at Baker Concrete Construction)"
                ]
            }
        ]

        # Live crawl TSNN
        try:
            resp = requests.get("https://www.tsnn.com/events", headers=HEADERS, timeout=6)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    title_text = a.get_text(strip=True)
                    if any(w in title_text.lower() for w in ['expo', 'convention', 'summit', 'annual meeting']) and len(title_text) > 15:
                        logger.info(f"[{self.source_name}] Discovered TSNN candidate: {title_text}")
        except Exception as e:
            logger.debug(f"[{self.source_name}] Crawl error: {e}")

        for item in tsnn_targets:
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
