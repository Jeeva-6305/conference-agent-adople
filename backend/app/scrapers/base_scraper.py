import html
import logging
import re
import threading
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
from typing import Optional, Any, Tuple, List, Dict
from urllib3.util import Retry
from requests.adapters import HTTPAdapter

from ..config import settings

logger = logging.getLogger(__name__)

_MONTH_MAP = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def clean_html_text(text: Optional[str]) -> str:
    """Unescapes HTML entities (e.g. &amp;, &#x27;) and normalizes horizontal whitespace."""
    if not text:
        return ""
    unescaped = html.unescape(str(text))
    unescaped = unescaped.replace("\xa0", " ")
    # Preserve line breaks where present while collapsing extra spaces per line
    lines = [re.sub(r"[ \t\r]+", " ", ln).strip() for ln in unescaped.split("\n")]
    return "\n".join(ln for ln in lines if ln).strip()


def extract_date_range_from_text(text: str, default_year: Optional[int] = None) -> Tuple[str, str]:
    """
    Extracts genuine start/end ISO dates (YYYY-MM-DD) from English date phrases such as:
    - '2026-11-15' / '2026-11-15 to 2026-11-18'
    - 'Nov 15 - 18, 2026' / 'November 16, 2026'
    - '15 - 18 Nov 2026' / '15 Nov 2026'
    Returns ("", "") if no reliable date is found (never fabricates dates).
    """
    if not text:
        return "", ""
    yr = default_year or date.today().year

    # 1. Explicit ISO dates YYYY-MM-DD
    iso_matches = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if iso_matches:
        try:
            s_dt = date.fromisoformat(iso_matches[0])
            e_dt = date.fromisoformat(iso_matches[1]) if len(iso_matches) > 1 else s_dt
            if e_dt < s_dt or (e_dt - s_dt).days > 14:
                e_dt = s_dt
            return s_dt.isoformat(), e_dt.isoformat()
        except ValueError:
            pass

    # 2. Month D[-D2], YYYY (e.g., "Nov 15 - 18, 2026" or "November 16, 2026")
    m1 = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+"
        r"(\d{1,2})(?:\s*(?:-|–|—|to)\s*(\d{1,2}))?(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
        text,
        re.I,
    )
    if m1:
        mon = _MONTH_MAP.get(m1.group(1).lower()[:4] if m1.group(1).lower().startswith("sept") else m1.group(1).lower()[:3]) or _MONTH_MAP.get(m1.group(1).lower())
        d1 = int(m1.group(2))
        d2 = int(m1.group(3)) if m1.group(3) else d1
        y = int(m1.group(4))
        try:
            s_dt = date(y, mon, d1)
            e_dt = date(y, mon, d2) if d2 >= d1 else s_dt
            return s_dt.isoformat(), e_dt.isoformat()
        except ValueError:
            pass

    # 3. D[-D2] Month YYYY (e.g., "15 - 18 Nov 2026" or "17 Nov 2026")
    m2 = re.search(
        r"\b(\d{1,2})(?:\s*(?:-|–|—|to)\s*(\d{1,2}))?(?:st|nd|rd|th)?\s+"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?),?\s+(20\d{2})\b",
        text,
        re.I,
    )
    if m2:
        d1 = int(m2.group(1))
        d2 = int(m2.group(2)) if m2.group(2) else d1
        mon_raw = m2.group(3).lower()
        mon = _MONTH_MAP.get(mon_raw) or _MONTH_MAP.get(mon_raw[:3])
        y = int(m2.group(4))
        if mon:
            try:
                s_dt = date(y, mon, d1)
                e_dt = date(y, mon, d2) if d2 >= d1 else s_dt
                return s_dt.isoformat(), e_dt.isoformat()
            except ValueError:
                pass

    # 4. Month D1 - Month2 D2, YYYY (e.g., "Nov 30 - Dec 2, 2026")
    m3 = re.search(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})\s*(?:-|–|—|to)\s*"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(20\d{2})\b",
        text,
        re.I,
    )
    if m3:
        mon1 = _MONTH_MAP.get(m3.group(1).lower()) or _MONTH_MAP.get(m3.group(1).lower()[:3])
        d1 = int(m3.group(2))
        mon2 = _MONTH_MAP.get(m3.group(3).lower()) or _MONTH_MAP.get(m3.group(3).lower()[:3])
        d2 = int(m3.group(4))
        y = int(m3.group(5))
        if mon1 and mon2:
            try:
                s_dt = date(y, mon1, d1)
                e_dt = date(y, mon2, d2)
                return s_dt.isoformat(), e_dt.isoformat()
            except ValueError:
                pass

    return "", ""


def extract_all_dates_from_text(text: str, default_year: Optional[int] = None) -> List[Tuple[str, str]]:
    """
    Extracts all candidate (start_iso, end_iso) date pairs found in text in order of appearance.
    Used when directory/calendar pages list multiple years (e.g. 2028, 2027, 2026) so callers
    can check if any genuine listed date falls inside the active discovery window.
    """
    if not text:
        return []
    results: List[Tuple[str, str]] = []

    for m in re.finditer(r"\b(20\d{2}-\d{2}-\d{2})\b", text):
        try:
            s_dt = date.fromisoformat(m.group(1))
            results.append((s_dt.isoformat(), s_dt.isoformat()))
        except ValueError:
            pass

    for m in re.finditer(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+"
        r"(\d{1,2})(?:\s*(?:-|–|—|to)\s*(\d{1,2}))?(?:st|nd|rd|th)?,?\s+(20\d{2})\b",
        text,
        re.I,
    ):
        mon_raw = m.group(1).lower()
        mon = _MONTH_MAP.get(mon_raw) or _MONTH_MAP.get(mon_raw[:4] if mon_raw.startswith("sept") else mon_raw[:3])
        d1 = int(m.group(2))
        d2 = int(m.group(3)) if m.group(3) else d1
        y = int(m.group(4))
        if mon:
            try:
                s_dt = date(y, mon, d1)
                e_dt = date(y, mon, d2) if d2 >= d1 else s_dt
                results.append((s_dt.isoformat(), e_dt.isoformat()))
            except ValueError:
                pass

    for m in re.finditer(
        r"\b(\d{1,2})(?:\s*(?:-|–|—|to)\s*(\d{1,2}))?(?:st|nd|rd|th)?\s+"
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
        r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?),?\s+(20\d{2})\b",
        text,
        re.I,
    ):
        d1 = int(m.group(1))
        d2 = int(m.group(2)) if m.group(2) else d1
        mon_raw = m.group(3).lower()
        mon = _MONTH_MAP.get(mon_raw) or _MONTH_MAP.get(mon_raw[:3])
        y = int(m.group(4))
        if mon:
            try:
                s_dt = date(y, mon, d1)
                e_dt = date(y, mon, d2) if d2 >= d1 else s_dt
                results.append((s_dt.isoformat(), e_dt.isoformat()))
            except ValueError:
                pass

    return results


class BaseScraper:
    def __init__(self, source_name: str, base_url: str):
        self.source_name = source_name
        self.base_url = base_url
        self._tavily_exhausted = False
        self._thread_local = threading.local()

    def _get_session(self) -> requests.Session:
        s = getattr(self._thread_local, "session", None)
        if s is None:
            s = requests.Session()
            retries = Retry(
                total=2,
                backoff_factor=0.5,
                status_forcelist=[500, 502, 503, 504],
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retries)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
            s.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            })
            self._thread_local.session = s
        return s

    @property
    def session(self) -> requests.Session:
        return self._get_session()

    def get_target_week(self) -> Tuple[date, date]:
        """Returns (target_sunday, target_saturday) from calculate_weekly_target_range."""
        try:
            from ..services.weekly_service import calculate_weekly_target_range
            target_sunday, target_saturday, _ = calculate_weekly_target_range()
            return target_sunday, target_saturday
        except Exception:
            today = date.today()
            days_until_sunday = (6 - today.weekday()) % 7
            target_sunday = today + timedelta(days=days_until_sunday)
            return target_sunday, target_sunday + timedelta(days=6)

    def get_discovery_window(self) -> Tuple[date, date]:
        """
        Returns active (start_date, end_date) discovery window.
        When T2_WORKFLOW_ENABLED=true, includes today+2 alongside target week;
        otherwise returns strict weekly [target_sunday, target_saturday].
        """
        win_start, win_end = self.get_target_week()
        if getattr(settings, "T2_WORKFLOW_ENABLED", False):
            exact_t2 = date.today() + timedelta(days=int(getattr(settings, "REMINDER_DAYS_BEFORE", 2) or 2))
            if exact_t2 < win_start:
                win_start = exact_t2
            if exact_t2 > win_end:
                win_end = exact_t2
        return win_start, win_end

    def is_date_in_window(self, date_str: str, win_start: date, win_end: date) -> bool:
        """Checks whether an ISO YYYY-MM-DD date string falls within [win_start, win_end]."""
        if not date_str:
            return False
        try:
            dt = date.fromisoformat(str(date_str).strip()[:10])
            return win_start <= dt <= win_end
        except Exception:
            return False

    def tavily_search(
        self,
        query: str,
        max_results: int = 8,
        search_depth: str = "basic",
        include_domains: Optional[List[str]] = None,
        include_raw_content: bool = False,
    ) -> List[Dict[str, Any]]:
        """Sanctioned web search via Tavily Search API (respects missing key / quota limits)."""
        api_key = getattr(settings, "TAVILY_API_KEY", "") or ""
        if not api_key or self._tavily_exhausted:
            return []
        payload: Dict[str, Any] = {
            "api_key": api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
        }
        if include_raw_content:
            payload["include_raw_content"] = True
        if include_domains:
            payload["include_domains"] = include_domains
        try:
            resp = requests.post("https://api.tavily.com/search", json=payload, timeout=15)
            if resp.status_code == 200:
                return resp.json().get("results", []) or []
            if resp.status_code in (401, 402, 429, 432, 433):
                logger.warning(f"[{self.source_name}] Tavily API quota/auth notice (HTTP {resp.status_code}).")
                self._tavily_exhausted = True
            else:
                logger.debug(f"[{self.source_name}] Tavily search HTTP {resp.status_code}: {resp.text[:160]}")
        except Exception as e:
            logger.debug(f"[{self.source_name}] Tavily search note: {e}")
        return []

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
