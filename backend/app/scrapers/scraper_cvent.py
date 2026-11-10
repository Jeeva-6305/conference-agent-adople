import logging
from datetime import date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper, clean_html_text, extract_date_range_from_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)


class CventScraper(BaseScraper):
    def __init__(self):
        super().__init__("cvent", "https://www.cvent.com/events")

    def scrape(self) -> List[RawEventData]:
        win_start, win_end = self.get_discovery_window()
        logger.info(f"[{self.source_name}] Harvesting enterprise conferences and summits from Cvent ({win_start}..{win_end})...")
        events: List[RawEventData] = []
        seen_urls = set()

        try:
            resp = self.fetch_page("https://www.cvent.com/events", timeout=10)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for item in soup.find_all(['div', 'article'], class_=lambda c: c and any(k in str(c).lower() for k in ['event', 'card', 'item'])):
                    link = item.find('a', href=True)
                    if not link:
                        continue
                    title = clean_html_text(link.get_text(strip=True))
                    if not title or len(title) < 5:
                        continue
                    event_url = link['href']
                    if event_url and not event_url.startswith('http'):
                        event_url = f"https://www.cvent.com{event_url}"
                    txt = clean_html_text(item.get_text(" ", strip=True))
                    s_iso, e_iso = extract_date_range_from_text(txt, default_year=win_start.year)
                    if not s_iso or not self.is_date_in_window(s_iso, win_start, win_end):
                        continue
                    seen_urls.add(event_url.lower().rstrip('/'))
                    events.append(RawEventData(
                        raw_title=title,
                        raw_text=f"Conference Title: {title}\nOverview: {txt}\nOfficial URL: {event_url}\nStart Date: {s_iso}\nEnd Date: {e_iso or s_iso}\nSource: Cvent\nCountry: USA",
                        source_url=event_url or self.base_url,
                        source_name=self.source_name,
                        raw_date=s_iso
                    ))
            elif resp and resp.status_code in (403, 429):
                logger.warning(f"[{self.source_name}] Live endpoint restricted (HTTP {resp.status_code}, status: unverified_access_restricted).")
        except Exception as e:
            logger.warning(f"[{self.source_name}] Cvent crawl error: {e}")

        # Sanctioned Tavily Search over Cvent event portals & listings for target week
        month_name = win_start.strftime("%B")
        mon_abbr = win_start.strftime("%b")
        queries = [
            f'(site:cvent.com OR site:web.cvent.com) ("{month_name}" OR "{mon_abbr}") "{win_start.year}" (conference OR summit OR symposium) ("United States" OR "USA" OR "Las Vegas" OR "New York" OR "Chicago" OR "Orlando")',
            f'site:cvent.com/events "{month_name} {win_start.year}" (AI OR healthcare OR finance OR technology)',
        ]
        for q in queries:
            for r in self.tavily_search(q, max_results=8):
                r_url = (r.get("url") or "").strip().split("?")[0]
                r_title = clean_html_text(r.get("title") or "").split("|")[0].strip()
                r_content = clean_html_text(r.get("content") or "")
                if not r_url or not r_title or len(r_title) < 5:
                    continue
                if r_url.lower().rstrip("/") in ("https://www.cvent.com/events", "https://www.cvent.com") or r_url.lower().rstrip("/") in seen_urls:
                    continue
                s_iso, e_iso = extract_date_range_from_text(f"{r_title} {r_content}", default_year=win_start.year)
                if not s_iso or not self.is_date_in_window(s_iso, win_start, win_end):
                    continue
                seen_urls.add(r_url.lower().rstrip("/"))

                # Optionally enrich speakers if Cvent event page returns HTTP 200
                extra_txt = r_content
                try:
                    ev_resp = self.fetch_page(r_url, timeout=8)
                    if ev_resp and ev_resp.status_code == 200:
                        ev_soup = BeautifulSoup(ev_resp.text, 'html.parser')
                        body_txt = clean_html_text(ev_soup.get_text("\n", strip=True))[:2500]
                        if len(body_txt) > len(extra_txt):
                            extra_txt = body_txt
                except Exception:
                    pass

                events.append(RawEventData(
                    raw_title=r_title,
                    raw_text=(
                        f"Conference Title: {r_title}\n"
                        f"Overview & Description: {extra_txt}\n"
                        f"Official Event URL: {r_url}\n"
                        f"Registration URL: {r_url}\n"
                        f"Start Date: {s_iso}\n"
                        f"End Date: {e_iso or s_iso}\n"
                        "Source: Cvent (Tavily Search)\n"
                        "Country: USA"
                    ),
                    source_url=r_url,
                    source_name=self.source_name,
                    raw_location="USA",
                    raw_date=s_iso,
                ))

        logger.info(f"[{self.source_name}] Harvested {len(events)} events from Cvent.")
        return events
