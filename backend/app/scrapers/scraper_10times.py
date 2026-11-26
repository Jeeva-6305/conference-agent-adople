import logging
from datetime import date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper, clean_html_text, extract_date_range_from_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)


class TenTimesScraper(BaseScraper):
    def __init__(self):
        super().__init__("10times", "https://10times.com/usa")

    def scrape(self) -> List[RawEventData]:
        win_start, win_end = self.get_discovery_window()
        logger.info(f"[{self.source_name}] Checking 10times live conferences ({win_start}..{win_end})...")
        events: List[RawEventData] = []
        seen_urls = set()

        # 1. Honest direct HTTP check (no 403/CAPTCHA bypass)
        try:
            resp = self.fetch_page("https://10times.com/usa", timeout=10)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for row in soup.find_all(['tr', 'div'], class_=lambda c: c and any(k in str(c).lower() for k in ['event', 'row', 'listing'])):
                    title_elem = row.find(['a', 'h2', 'h3'], class_=lambda c: c and 'title' in str(c).lower()) or row.find('a', href=True)
                    if not title_elem:
                        continue
                    title = clean_html_text(title_elem.get_text(strip=True))
                    if not title or len(title) < 5 or any(b in title.lower() for b in ['login', 'sign up', 'contact', 'about us']):
                        continue
                    event_url = title_elem.get('href', '')
                    if event_url and not event_url.startswith('http'):
                        event_url = f"https://10times.com{event_url}"
                    row_txt = clean_html_text(row.get_text(" ", strip=True))
                    s_iso, e_iso = extract_date_range_from_text(row_txt, default_year=win_start.year)
                    if s_iso and not self.is_date_in_window(s_iso, win_start, win_end):
                        continue
                    seen_urls.add(event_url.lower().rstrip('/'))
                    events.append(RawEventData(
                        raw_title=title,
                        raw_text=f"Conference Title: {title}\nOverview: {row_txt}\nOfficial Event URL: {event_url}\nStart Date: {s_iso}\nEnd Date: {e_iso}\nSource: 10times\nCountry: USA",
                        source_url=event_url or self.base_url,
                        source_name=self.source_name,
                        raw_date=s_iso or None
                    ))
            elif resp and resp.status_code in (403, 429):
                logger.warning(f"[{self.source_name}] Live endpoint restricted (HTTP {resp.status_code}, status: unverified_access_restricted). Using sanctioned Tavily index search.")
        except Exception as e:
            logger.warning(f"[{self.source_name}] 10times live crawl notice: {e}")

        # 2. Sanctioned Tavily Search over 10times indexed USA conferences for the target week
        mon_abbr = win_start.strftime("%b")
        month_name = win_start.strftime("%B")
        day_terms = " OR ".join(f'"{mon_abbr} {(win_start + timedelta(days=i)).day}"' for i in range((win_end - win_start).days + 1))
        queries = [
            f'site:10times.com ({day_terms}) "{win_start.year}" ("United States" OR "USA") (conference OR summit OR expo)',
            f'site:10times.com "{month_name} {win_start.year}" ("United States" OR "USA") (AI OR Healthcare OR Medical OR Finance OR FinTech OR Cybersecurity)',
        ]
        for q in queries:
            for r in self.tavily_search(q, max_results=8):
                r_url = (r.get("url") or "").strip().split("?")[0]
                r_title = clean_html_text(r.get("title") or "").split("|")[0].strip()
                r_content = clean_html_text(r.get("content") or "")
                if not r_url or not r_title or len(r_title) < 5:
                    continue
                if r_url.rstrip("/").lower() in ("https://10times.com", "https://10times.com/usa") or r_url.lower().rstrip("/") in seen_urls:
                    continue
                combined = f"{r_title} {r_content}"
                s_iso, e_iso = extract_date_range_from_text(combined, default_year=win_start.year)
                if not s_iso or not self.is_date_in_window(s_iso, win_start, win_end):
                    continue
                seen_urls.add(r_url.lower().rstrip("/"))
                events.append(RawEventData(
                    raw_title=r_title,
                    raw_text=(
                        f"Conference Title: {r_title}\n"
                        f"Overview & Description: {r_content}\n"
                        f"Official Event URL: {r_url}\n"
                        f"Registration URL: {r_url}\n"
                        f"Start Date: {s_iso}\n"
                        f"End Date: {e_iso or s_iso}\n"
                        "Source: 10times (Tavily Search)\n"
                        "Country: USA"
                    ),
                    source_url=r_url,
                    source_name=self.source_name,
                    raw_location="USA",
                    raw_date=s_iso,
                ))

        logger.info(f"[{self.source_name}] Harvested {len(events)} events from 10times.")
        return events
