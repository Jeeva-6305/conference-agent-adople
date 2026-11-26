import logging
import re
from datetime import date, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper, clean_html_text, extract_date_range_from_text, extract_all_dates_from_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)


class GovEventsScraper(BaseScraper):
    def __init__(self):
        super().__init__("govevents", "https://www.govevents.com/")

    def scrape(self) -> List[RawEventData]:
        win_start, win_end = self.get_discovery_window()
        logger.info(f"[{self.source_name}] Harvesting government, public finance & civic technology conferences ({win_start}..{win_end})...")
        events: List[RawEventData] = []
        seen_urls = set()

        # 1. Honest direct HTTP check (no 403/CAPTCHA bypass)
        try:
            resp = self.fetch_page("https://www.govevents.com/", timeout=10)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for item in soup.find_all(['div', 'li'], class_=lambda c: c and any(k in str(c).lower() for k in ['event', 'item', 'listing'])):
                    link = item.find('a', href=True)
                    if not link:
                        continue
                    title = clean_html_text(link.get_text(strip=True))
                    if not title or len(title) < 5:
                        continue
                    event_url = link['href']
                    if event_url and not event_url.startswith('http'):
                        event_url = f"https://www.govevents.com{event_url}"
                    if any(b in event_url.lower() for b in ["/orgs/", "/find", "/calendar", "/speakers/"]):
                        continue
                    txt = clean_html_text(item.get_text(" ", strip=True))
                    s_iso, e_iso = extract_date_range_from_text(txt, default_year=win_start.year)
                    if s_iso and not self.is_date_in_window(s_iso, win_start, win_end):
                        continue
                    seen_urls.add(event_url.lower().rstrip('/'))
                    events.append(RawEventData(
                        raw_title=title,
                        raw_text=f"Conference Title: {title}\nOverview: {txt}\nOfficial URL: {event_url}\nStart Date: {s_iso}\nEnd Date: {e_iso or s_iso}\nSource: GovEvents\nCountry: USA",
                        source_url=event_url or self.base_url,
                        source_name=self.source_name,
                        raw_date=s_iso or None
                    ))
            elif resp and resp.status_code in (403, 429):
                logger.warning(f"[{self.source_name}] Live endpoint restricted (HTTP {resp.status_code}, status: unverified_access_restricted). Using sanctioned Tavily index search.")
        except Exception as e:
            logger.warning(f"[{self.source_name}] GovEvents crawl note: {e}")

        # 2. Sanctioned Tavily Search strictly over govevents.com/event/ pages for target week
        month_name = win_start.strftime("%B")
        mon_abbr = win_start.strftime("%b")
        day_phrases = " OR ".join(f'"{mon_abbr} {(win_start + timedelta(days=i)).day}"' for i in range((win_end - win_start).days + 1))
        full_day_phrases = " OR ".join(f'"{month_name} {(win_start + timedelta(days=i)).day}"' for i in range((win_end - win_start).days + 1))
        queries = [
            f'site:govevents.com/event ({day_phrases}) "{win_start.year}" (conference OR summit OR symposium OR forum)',
            f'site:govevents.com/event ({full_day_phrases}) "{win_start.year}" (conference OR summit OR symposium OR forum OR AI OR tech)',
            f'site:govevents.com/event "{mon_abbr}" "{win_start.year}" (AI OR cybersecurity OR health OR finance OR technology OR supply OR federal)',
        ]
        for q in queries:
            for r in self.tavily_search(q, max_results=10, include_raw_content=True):
                r_url = (r.get("url") or "").strip().split("?")[0]
                if not r_url or "/event/" not in r_url.lower():
                    continue
                if any(b in r_url.lower() for b in ["/orgs/", "/find", "/calendar", "/speakers/"]):
                    continue
                if r_url.lower().rstrip("/") in seen_urls:
                    continue

                r_title = clean_html_text(r.get("title") or "").split("|")[0].split(" - GovEvents")[0].strip()
                if not r_title or len(r_title) < 5 or "find government events" in r_title.lower():
                    continue

                raw_body = clean_html_text(r.get("raw_content") or r.get("content") or "")
                # Prefer matching date in window across full page content
                s_iso, e_iso = "", ""
                for cs, ce in extract_all_dates_from_text(f"{r_title} {raw_body}", default_year=win_start.year):
                    if self.is_date_in_window(cs, win_start, win_end):
                        s_iso, e_iso = cs, ce
                        break
                if not s_iso:
                    continue
                # Skip Virtual-only webinars on GovEvents
                if re.search(r"Event Type\s*[:\n]+\s*(?:Virtual|Online|Webinar)", raw_body, re.I) and "Onsite" not in raw_body:
                    continue

                seen_urls.add(r_url.lower().rstrip("/"))
                events.append(RawEventData(
                    raw_title=r_title,
                    raw_text=(
                        f"Conference Title: {r_title}\n"
                        f"Overview & Description: {raw_body[:4000]}\n"
                        f"Official Event URL: {r_url}\n"
                        f"Registration URL: {r_url}\n"
                        f"Start Date: {s_iso}\n"
                        f"End Date: {e_iso or s_iso}\n"
                        "Source: GovEvents (Tavily Search)\n"
                        "Country: USA"
                    ),
                    source_url=r_url,
                    source_name=self.source_name,
                    raw_location="USA",
                    raw_date=s_iso,
                ))

        logger.info(f"[{self.source_name}] Collection finished. Harvested {len(events)} events.")
        return events
