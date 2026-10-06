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

TSNN_CHANNELS = [
    "https://www.tsnn.com/trade-shows-conferences",
    "https://www.tsnn.com/events"
]

class TSNNScraper(BaseScraper):
    def __init__(self):
        super().__init__("tsnn", "https://www.tsnn.com/")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping genuine USA trade shows & conferences from TSNN...")
        events: List[RawEventData] = []
        seen_titles = set()

        for channel_url in TSNN_CHANNELS:
            try:
                resp = requests.get(channel_url, headers=HEADERS, timeout=12)
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    title_text = a.get_text(strip=True)
                    href = a['href']

                    if len(title_text) < 12 or title_text in seen_titles:
                        continue

                    # Filter for actual trade show / conference event titles
                    lower = title_text.lower()
                    if not any(k in lower for k in ['expo', 'conference', 'summit', 'annual meeting', 'trade show', 'forum']):
                        continue
                    if any(k in lower for k in ['privacy', 'terms', 'cookies', 'contact', 'about us']):
                        continue

                    seen_titles.add(title_text)
                    clean_title = re.sub(r'^(Preview:\s*|Review:\s*)', '', title_text, flags=re.I).strip()
                    full_url = f"https://www.tsnn.com{href}" if not href.startswith("http") else href

                    raw_text = (
                        f"Conference Title: {clean_title}\n"
                        f"Source URL: {full_url}\n"
                        f"Source: Trade Show News Network (TSNN)\n"
                        f"Country: USA\n"
                        f"Domain: Trade Shows & Industry Conferences\n"
                    )

                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=full_url,
                        raw_title=clean_title,
                        raw_text=raw_text,
                        raw_location="USA",
                        raw_date=None
                    ))

                    logger.info(f"[{self.source_name}] Harvested event: {clean_title}")

            except Exception as e:
                logger.error(f"[{self.source_name}] Error crawling {channel_url}: {e}")

        logger.info(f"[{self.source_name}] Finished live scraping. Harvested {len(events)} events.")
        return events
