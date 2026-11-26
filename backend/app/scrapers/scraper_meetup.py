import logging
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper, clean_html_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

MEETUP_URLS = [
    ("https://www.meetup.com/find/?keywords=conference&location=us--ca--san-francisco", "San Francisco, CA, USA"),
    ("https://www.meetup.com/find/?keywords=conference&location=us--ny--new-york", "New York, NY, USA"),
    ("https://www.meetup.com/find/?keywords=conference&location=us--ma--boston", "Boston, MA, USA"),
    ("https://www.meetup.com/find/?keywords=conference&location=us--il--chicago", "Chicago, IL, USA"),
    ("https://www.meetup.com/find/?keywords=conference&location=us--tx--austin", "Austin, TX, USA"),
    ("https://www.meetup.com/find/?keywords=conference&location=us--wa--seattle", "Seattle, WA, USA"),
    ("https://www.meetup.com/find/?keywords=ai%20summit&location=us", "USA"),
    ("https://www.meetup.com/find/?keywords=summit&location=us", "USA"),
]

NON_CONFERENCE_KEYWORDS = [
    "happy hour", "bar crawl", "speed dating", "singles", "karaoke", "bootcamp",
    "dinner", "party", "social mixer", "class", "brunch", "walk", "comic con",
    "comedy", "festival", "screening", "game night", "board game", "pub crawl",
    "let's jam", "lets jam", "networking event", "tech social", "wordpress meetup",
    "fireside", "yoga", "church", "bridal", "faith", "cross-post",
]

CONFERENCE_TERMS = [
    "conference", "summit", "symposium", "forum", "congress", "expo", "annual meeting", "showcase"
]


def _norm_mu_title(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


class MeetupScraper(BaseScraper):
    def __init__(self):
        super().__init__("meetup", "https://www.meetup.com/find/?keywords=conference&location=us--ca--san-francisco")

    def _fetch_detail(
        self,
        url: str,
        name: str,
        start_at: str,
        end_at: str,
        desc: str,
        default_loc: str,
        venue: str,
        win_start: date,
        win_end: date,
    ) -> Optional[RawEventData]:
        url = url.strip()
        name = clean_html_text(name)
        desc = clean_html_text(desc)
        if not name or not url:
            return None

        start_date = start_at[:10] if len(start_at) >= 10 else ""
        end_date = end_at[:10] if len(end_at) >= 10 else start_date
        full_loc = clean_html_text(f"{venue}, {default_loc}".strip(', '))
        deep_desc = desc
        official_site_url = url
        speakers_block = ""

        try:
            m_resp = self.fetch_page(url, timeout=7)
            if m_resp and m_resp.status_code == 200:
                m_soup = BeautifulSoup(m_resp.text, 'html.parser')
                if not start_date:
                    for ld in m_soup.find_all('script', type='application/ld+json'):
                        try:
                            ld_d = json.loads(ld.string or "")
                            if isinstance(ld_d, dict) and ld_d.get("startDate"):
                                start_date = str(ld_d["startDate"])[:10]
                                end_date = str(ld_d.get("endDate") or start_date)[:10]
                        except Exception:
                            pass
                if start_date and not self.is_date_in_window(start_date, win_start, win_end):
                    return None
                body_el = m_soup.find('div', class_='break-words') or m_soup.find('section')
                if body_el:
                    deep_desc = clean_html_text(body_el.get_text('\n', strip=True))
                for marker in ["Featured Speakers", "Speakers", "Keynote Speakers", "Agenda"]:
                    if marker in deep_desc:
                        idx = deep_desc.find(marker)
                        speakers_block = deep_desc[idx:idx + 1500]
                        break
                for a_el in m_soup.find_all('a', href=True):
                    h_el = a_el['href'].strip()
                    if h_el.startswith('http') and not any(ign in h_el.lower() for ign in [
                        'meetup.com', 'google.com', 'facebook.com', 'twitter.com', 'x.com',
                        'instagram.com', 'linkedin.com', 'youtube.com', 'apple.com', 'pinterest.com', 'meetu.ps'
                    ]):
                        official_site_url = h_el.rstrip('.,;)\"')
                        break
        except Exception:
            pass

        if not start_date or not self.is_date_in_window(start_date, win_start, win_end):
            return None

        raw_parts = [
            f"Conference Title: {name}",
            f"Overview & Description: {deep_desc}",
            f"Venue: {venue}",
            f"Address: {full_loc}",
            f"Official Event URL: {official_site_url}",
            f"Registration URL: {url}",
            f"Start Date: {start_date}",
            f"End Date: {end_date}",
            "Source: Meetup Conferences",
            "Country: USA",
        ]
        if speakers_block:
            raw_parts.append(speakers_block)

        logger.info(f"[{self.source_name}] Harvested conference: {name} ({start_date})")
        return RawEventData(
            source_name=self.source_name,
            source_url=official_site_url or url,
            raw_title=name,
            raw_text="\n".join(raw_parts),
            raw_location=full_loc,
            raw_date=start_date
        )

    def scrape(self) -> List[RawEventData]:
        t_start = time.time()
        win_start, win_end = self.get_discovery_window()
        logger.info(f"[{self.source_name}] Scanning Meetup for genuine USA conferences ({win_start}..{win_end})...")
        events: List[RawEventData] = []
        seen_urls = set()
        seen_titles = set()
        candidates: List[Tuple[str, str, str, str, str, str, str]] = []

        for page_url, default_loc in MEETUP_URLS:
            if time.time() - t_start > 35 or len(candidates) >= 30:
                break
            try:
                soup = self.fetch_soup(page_url, timeout=8)
                if not soup:
                    continue

                scripts = soup.find_all('script', type='application/ld+json')
                for s in scripts:
                    try:
                        data = json.loads(s.string or "")
                        items = []
                        if isinstance(data, list):
                            items = data
                        elif isinstance(data, dict):
                            if 'itemListElement' in data:
                                items = [el.get('item', {}) for el in data['itemListElement']]
                            elif data.get('@type') in ['Event', 'BusinessEvent']:
                                items = [data]

                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            u = (item.get('url') or '').strip()
                            nm = clean_html_text(item.get('name', ''))
                            ds = clean_html_text(item.get('description', ''))
                            if not u or not nm or u in seen_urls:
                                continue
                            nm_l = nm.lower()
                            if any(bad in nm_l for bad in NON_CONFERENCE_KEYWORDS):
                                continue
                            if not any(t in nm_l for t in CONFERENCE_TERMS) and not any(t in ds.lower() for t in CONFERENCE_TERMS):
                                continue
                            t_key = _norm_mu_title(nm)
                            if not t_key or t_key in seen_titles:
                                continue
                            s_at = item.get('startDate', '')
                            if s_at and len(s_at) >= 10 and not self.is_date_in_window(s_at[:10], win_start, win_end):
                                continue

                            loc = item.get('location', {})
                            venue = loc.get('name', '') if isinstance(loc, dict) else ''
                            addr = loc.get('address', {}) if isinstance(loc, dict) else {}
                            city = addr.get('addressLocality', '') if isinstance(addr, dict) else ''
                            state = addr.get('addressRegion', '') if isinstance(addr, dict) else ''
                            loc_str = f"{city}, {state}, USA".strip(', ') if (city or state) else default_loc

                            seen_urls.add(u)
                            seen_titles.add(t_key)
                            candidates.append((u, nm, s_at, item.get('endDate', s_at), ds, loc_str, venue))
                            if len(candidates) >= 30:
                                break
                    except Exception as err:
                        logger.debug(f"[{self.source_name}] JSON-LD parse error: {err}")
            except Exception as e:
                logger.debug(f"[{self.source_name}] Error crawling {page_url}: {e}")

        # Sanctioned Tavily supplement for Meetup events in target month/year
        month_name = win_start.strftime("%B")
        t_query = f'site:meetup.com/events ("conference" OR "summit" OR "showcase") "{month_name} {win_start.year}" (AI OR healthcare OR fintech OR tech)'
        for r in self.tavily_search(t_query, max_results=6):
            r_url = (r.get("url") or "").strip()
            r_title = clean_html_text((r.get("title") or "").split("|")[0].strip())
            if not r_url or "/events/" not in r_url or r_url in seen_urls or not r_title:
                continue
            if any(bad in r_title.lower() for bad in NON_CONFERENCE_KEYWORDS):
                continue
            t_key = _norm_mu_title(r_title)
            if not t_key or t_key in seen_titles:
                continue
            seen_urls.add(r_url)
            seen_titles.add(t_key)
            candidates.append((r_url, r_title, "", "", r.get("content", ""), "USA", ""))

        logger.info(f"[{self.source_name}] Discovered {len(candidates)} unique candidates. Fetching details concurrently...")
        remaining = max(15.0, 65.0 - (time.time() - t_start))
        with ThreadPoolExecutor(max_workers=5) as pool:
            futs = [
                pool.submit(self._fetch_detail, u, nm, sa, ea, ds, dloc, ven, win_start, win_end)
                for (u, nm, sa, ea, ds, dloc, ven) in candidates
            ]
            try:
                for fut in as_completed(futs, timeout=remaining):
                    ev = fut.result()
                    if ev is not None:
                        events.append(ev)
            except Exception:
                pass

        logger.info(f"[{self.source_name}] Harvested {len(events)} genuine conferences from Meetup in {round(time.time() - t_start, 1)}s.")
        return events
