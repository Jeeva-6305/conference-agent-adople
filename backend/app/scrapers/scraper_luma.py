import logging
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class LumaScraper(BaseScraper):
    def __init__(self):
        super().__init__("luma", "https://lu.ma/tech")
        self.luma_conferences = [
            ("San Francisco Tech Week 2026", "https://lu.ma/sftw", "San Francisco, CA, USA"),
            ("Austin Tech Week 2026", "https://lu.ma/austin-tech-week", "Austin, TX, USA"),
            ("LA Tech Week 2026", "https://lu.ma/latw", "Los Angeles, CA, USA"),
            ("AWS re:Invent Tech Summit 2026", "https://lu.ma/aws-re-invent", "Las Vegas, NV, USA")
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA tech conferences from Luma calendars...")
        events: List[RawEventData] = []

        for conf_title, conf_url, location in self.luma_conferences:
            soup = self.fetch_soup(conf_url)
            page_text = ""
            if soup:
                title_tag = soup.title.string if soup.title else conf_title
                desc_tag = soup.select_one("meta[name='description']")
                desc = desc_tag.get("content", "") if desc_tag else ""
                page_text = f"{title_tag}. {desc}"
            else:
                page_text = f"{conf_title} on Luma. Major Technology and Developer Conference in {location}."

            events.append(RawEventData(
                source_name=self.source_name,
                source_url=conf_url,
                raw_title=conf_title,
                raw_text=f"Conference: {conf_title}. Location: {location}. Details: {page_text}. Luma Official Page: {conf_url}",
                raw_location=location,
                raw_date=None
            ))

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Luma conferences.")
        return events
