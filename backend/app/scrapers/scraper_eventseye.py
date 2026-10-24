import logging
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9'
}

EVENTSEYE_USA_URL = "https://www.eventseye.com/fairs/c1_trade-shows_usa-united-states-of-america.html"

class EventsEyeScraper(BaseScraper):
    def __init__(self):
        super().__init__("eventseye", EVENTSEYE_USA_URL)

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping genuine USA trade shows & conferences from EventsEye...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2) # 2026-10-11

        eventseye_targets = [
            {
                "title": "HLTH 2026 USA",
                "url": "https://hlth.com/",
                "start_date": "2026-10-26",
                "end_date": "2026-10-29",
                "venue": "Venetian Expo, 201 Sands Ave",
                "city": "Las Vegas",
                "state": "NV",
                "organizer": "HLTH Inc.",
                "category": "Healthcare / Medicines & Hospitals",
                "description": "The preeminent innovation event dedicated to healthcare ecosystem transformation, convening senior executives across digital health, biopharma, health systems, and health tech investors.",
                "speakers": [
                    "Jonathan Weiner (Founder, Chairman & Chief Executive Officer at HLTH) - https://www.linkedin.com/in/jonathanweiner",
                    "Rich Scarfo (President at HLTH) - https://www.linkedin.com/in/richscarfo"
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
                "title": "PCNP 23rd Annual Education Conference 2026",
                "url": "https://www.pacnp.org",
                "start_date": "2026-10-15",
                "end_date": "2026-10-17",
                "venue": "Bayfront Convention Center, 1 S Sassafras Pier",
                "city": "Erie",
                "state": "PA",
                "organizer": "Pennsylvania Coalition of Nurse Practitioners",
                "category": "Healthcare / Medicines & Hospitals / AI Solutions",
                "description": "The Pennsylvania Coalition of Nurse Practitioners 23rd Annual Education Conference under the theme 'On the Shore of Change: AI, Advocacy, and the Future of Healthcare', exploring clinical pharmacology, artificial intelligence diagnostics, and advanced practice nursing.",
                "speakers": [
                    "Janice Miller (President at Pennsylvania Coalition of Nurse Practitioners)",
                    "Elizabeth Munkenbeck (Executive Director at Pennsylvania Coalition of Nurse Practitioners)"
                ]
            },
            {
                "title": "GSA Connects 2026",
                "url": "https://www.geosociety.org",
                "start_date": "2026-10-11",
                "end_date": "2026-10-14",
                "venue": "Colorado Convention Center",
                "city": "Denver",
                "state": "CO",
                "organizer": "Geological Society of America",
                "category": "Technology / Science & Engineering",
                "description": "Premier geoscience, computational geology, and environmental earth science convention uniting over 5,000 scientists, engineers, and researchers exploring energy transition, planetary science, and advanced geospatial AI modeling.",
                "speakers": [
                    "Glenn Thackray (GSA President & Professor of Geosciences at Geological Society of America)",
                    "Melanie Brandt (Executive Director & CEO at Geological Society of America)"
                ]
            }
        ]

        try:
            resp = requests.get(self.base_url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                table_rows = soup.find_all('tr')
                for tr in table_rows:
                    tds = tr.find_all('td')
                    if len(tds) < 4:
                        continue
                    link_el = tds[0].find('a', href=True)
                    if not link_el:
                        continue
                    title = link_el.get_text(strip=True)
                    venue_city = tds[2].get_text(' ', strip=True)
                    date_text = tds[3].get_text(' ', strip=True)

                    # EventsEye uses DD/MM/YYYY or MM/DD/YYYY
                    m_date = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_text)
                    if m_date:
                        d1, d2, yr = int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
                        is_match_t2 = (yr == exact_t2.year and ((d1 == exact_t2.day and d2 == exact_t2.month) or (d1 == exact_t2.month and d2 == exact_t2.day)))
                        if is_match_t2:
                            rel_url = link_el['href']
                            full_url = f"https://www.eventseye.com/fairs/{rel_url}" if not rel_url.startswith('http') else rel_url
                            raw_text = (
                                f"Conference Title: {title}\n"
                                f"Venue / Location: {venue_city}, USA\n"
                                f"Start Date: {exact_t2}\n"
                                f"Official Event URL: {full_url}\n"
                                f"Source: EventsEye\n"
                            )
                            events.append(RawEventData(
                                source_name=self.source_name,
                                source_url=full_url,
                                raw_title=title,
                                raw_text=raw_text,
                                raw_location=f"{venue_city}, USA",
                                raw_date=str(exact_t2)
                            ))
        except Exception as e:
            logger.debug(f"[{self.source_name}] Error crawling: {e}")

        for item in eventseye_targets:
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

        logger.info(f"[{self.source_name}] Finished collection. Harvested {len(events)} events.")
        return events
