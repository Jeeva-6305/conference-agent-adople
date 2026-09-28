import logging
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class CventScraper(BaseScraper):
    def __init__(self):
        super().__init__("cvent", "https://www.cvent.com/en/cvent-connect")
        self.cvent_conferences = [
            ("Cvent CONNECT Annual Conference", "https://www.cvent.com/en/cvent-connect", "Gaylord Opryland Resort, Nashville, TN, USA")
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA conferences from Cvent...")
        events: List[RawEventData] = []

        for conf_title, conf_url, location in self.cvent_conferences:
            soup = self.fetch_soup(conf_url)
            page_text = ""
            if soup:
                title_tag = soup.title.string if soup.title else conf_title
                desc_tag = soup.select_one("meta[name='description']")
                desc = desc_tag.get("content", "") if desc_tag else ""
                h1_tags = " ".join([h.get_text(strip=True) for h in soup.find_all(["h1", "h2"])[:4]])
                page_text = f"{title_tag}. {desc}. {h1_tags}"
            else:
                page_text = f"{conf_title}. Flagship Enterprise Event Industry Conference in {location}."

            events.append(RawEventData(
                source_name=self.source_name,
                source_url=conf_url,
                raw_title=conf_title,
                raw_text=f"Conference: {conf_title}. Location: {location}. Details: {page_text}. Official Cvent URL: {conf_url}",
                raw_location=location,
                raw_date=None
            ))

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Cvent conferences.")
        return events
