import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional

logger = logging.getLogger(__name__)

class BaseScraper:
    def __init__(self, source_name: str, base_url: str):
        self.source_name = source_name
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch_soup(self, url: str) -> Optional[BeautifulSoup]:
        try:
            resp = self.session.get(url, timeout=12)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            logger.warning(f"[{self.source_name}] Failed to fetch {url} (Status: {resp.status_code})")
            return None
        except Exception as e:
            logger.error(f"[{self.source_name}] Connection error on {url}: {e}")
            return None

    def scrape(self):
        raise NotImplementedError
