import logging
import requests
from bs4 import BeautifulSoup
from typing import Optional, Any
from urllib3.util import Retry
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

class BaseScraper:
    def __init__(self, source_name: str, base_url: str):
        self.source_name = source_name
        self.base_url = base_url
        self.session = requests.Session()
        
        # Bounded retries for temporary failures (connection resets, 502, 503, 504)
        retries = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def fetch_page(self, url: str, timeout: int = 12) -> Optional[requests.Response]:
        try:
            resp = self.session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp
            elif resp.status_code in (403, 429):
                logger.warning(f"[{self.source_name}] Access restricted (HTTP {resp.status_code}) on {url} (status: unverified_access_restricted)")
            else:
                logger.warning(f"[{self.source_name}] Failed to fetch {url} (Status: {resp.status_code})")
            return resp
        except Exception as e:
            logger.error(f"[{self.source_name}] Connection error on {url}: {e}")
            return None

    def fetch_soup(self, url: str, timeout: int = 12) -> Optional[BeautifulSoup]:
        try:
            resp = self.fetch_page(url, timeout=timeout)
            if resp and resp.status_code == 200:
                return BeautifulSoup(resp.text, "html.parser")
            return None
        except Exception as e:
            logger.error(f"[{self.source_name}] Soup parse error on {url}: {e}")
            return None

    def fetch_json(self, url: str, timeout: int = 12) -> Optional[Any]:
        try:
            resp = self.session.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code in (403, 429):
                logger.warning(f"[{self.source_name}] Access restricted (HTTP {resp.status_code}) on {url}")
            return None
        except Exception as e:
            logger.error(f"[{self.source_name}] JSON fetch error on {url}: {e}")
            return None

    def scrape(self):
        raise NotImplementedError
