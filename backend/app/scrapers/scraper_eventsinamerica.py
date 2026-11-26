import logging
import re
from datetime import date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper, clean_html_text, extract_date_range_from_text, extract_all_dates_from_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)


class EventsInAmericaScraper(BaseScraper):
    def __init__(self):
        super().__init__("events_in_america", "https://eventsinamerica.com/trade-shows")

    def scrape(self) -> List[RawEventData]:
        win_start, win_end = self.get_discovery_window()
        logger.info(f"[{self.source_name}] Checking Events in America live conferences ({win_start}..{win_end})...")
        events: List[RawEventData] = []
        seen_urls = set()

        # 1. Honest direct HTTP check (no 403/CAPTCHA bypass)
        try:
            resp = self.fetch_page("https://eventsinamerica.com/trade-shows", timeout=8)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for card in soup.find_all(['div', 'article'], class_=lambda c: c and any(k in str(c).lower() for k in ['show', 'event', 'card', 'item'])):
                    link = card.find('a', href=True)
                    if not link:
                        continue
                    title = clean_html_text(link.get_text(strip=True))
                    if not title or len(title) < 5:
                        continue
                    event_url = link['href']
                    if event_url and not event_url.startswith('http'):
                        event_url = f"https://eventsinamerica.com{event_url}"
                    txt = clean_html_text(card.get_text(" ", strip=True))
                    s_iso, e_iso = extract_date_range_from_text(txt, default_year=win_start.year)
                    if s_iso and not self.is_date_in_window(s_iso, win_start, win_end):
                        continue
                    seen_urls.add(event_url.lower().rstrip('/'))
                    events.append(RawEventData(
                        raw_title=title,
                        raw_text=f"Conference Title: {title}\nOverview: {txt}\nOfficial URL: {event_url}\nStart Date: {s_iso}\nEnd Date: {e_iso or s_iso}\nSource: Events in America\nCountry: USA",
                        source_url=event_url or self.base_url,
                        source_name=self.source_name,
                        raw_date=s_iso or None
                    ))
            elif resp and resp.status_code in (403, 429):
                logger.warning(f"[{self.source_name}] Live endpoint restricted (HTTP {resp.status_code}, status: unverified_access_restricted). Using sanctioned Tavily index search.")
        except Exception as e:
            logger.warning(f"[{self.source_name}] Events in America live endpoint error: {e}")

        # 2. Sanctioned Tavily Advanced Search over eventsinamerica.com individual show/conference pages
        mon_abbr = win_start.strftime("%b")
        month_name = win_start.strftime("%B")
        day_terms = " OR ".join(
            f'"{mon_abbr} {(win_start + timedelta(days=i)).day}"'
            for i in range((win_end - win_start).days + 1)
        )
        queries = [
            f'site:eventsinamerica.com ({day_terms}) "{win_start.year}"',
            f'site:eventsinamerica.com/events-conference OR site:eventsinamerica.com/events-trade-shows "{month_name} {win_start.year}" (healthcare OR medical OR finance OR technology OR supply OR conference)',
        ]
        for q in queries:
            for r in self.tavily_search(q, max_results=10, search_depth="advanced"):
                r_url = (r.get("url") or "").strip().split("?")[0]
                if not r_url:
                    continue
                r_u_low = r_url.lower().rstrip("/")
                if r_u_low in seen_urls:
                    continue
                # Accept only specific event detail pages, never category index or top-trade-shows lists
                if not any(seg in r_u_low for seg in ["/events-trade-shows/", "/events-conference/", "/events/"]):
                    continue
                if "/category/" in r_u_low or "/top-trade-shows" in r_u_low:
                    continue

                r_title = clean_html_text(r.get("title") or "").split("|")[0].split(" - Events in America")[0].strip()
                r_content = clean_html_text(r.get("content") or "")
                if not r_title or len(r_title) < 5:
                    continue

                # Check all dates in snippet (because Future & Past Event Dates tables list 2028/2027 before 2026)
                s_iso, e_iso = "", ""
                for cs, ce in extract_all_dates_from_text(f"{r_title} {r_content}", default_year=win_start.year):
                    if self.is_date_in_window(cs, win_start, win_end):
                        s_iso, e_iso = cs, ce
                        break
                if not s_iso:
                    continue

                seen_urls.add(r_u_low)
                events.append(RawEventData(
                    raw_title=r_title,
                    raw_text=(
                        f"Conference Title: {r_title}\n"
                        f"Overview & Description: {r_content}\n"
                        f"Official Event URL: {r_url}\n"
                        f"Registration URL: {r_url}\n"
                        f"Start Date: {s_iso}\n"
                        f"End Date: {e_iso or s_iso}\n"
                        "Source: Events in America (Tavily Search)\n"
                        "Country: USA"
                    ),
                    source_url=r_url,
                    source_name=self.source_name,
                    raw_location="USA",
                    raw_date=s_iso,
                ))

        logger.info(f"[{self.source_name}] Harvested {len(events)} events from Events in America.")
        return events
