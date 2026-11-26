import logging
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
from datetime import datetime, date, timedelta
from typing import List, Optional, Tuple
from .base_scraper import BaseScraper, clean_html_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

ALLEVENTS_URLS = [
    ("https://allevents.in/united-states/conferences", "USA"),
    ("https://allevents.in/new-york/conferences", "New York, NY, USA"),
    ("https://allevents.in/san-francisco/conferences", "San Francisco, CA, USA"),
    ("https://allevents.in/chicago/conferences", "Chicago, IL, USA"),
    ("https://allevents.in/austin/conferences", "Austin, TX, USA"),
    ("https://allevents.in/boston/conferences", "Boston, MA, USA"),
    ("https://allevents.in/las-vegas/conferences", "Las Vegas, NV, USA"),
    ("https://allevents.in/dallas/conferences", "Dallas, TX, USA"),
    ("https://allevents.in/seattle/conferences", "Seattle, WA, USA"),
    ("https://allevents.in/atlanta/conferences", "Atlanta, GA, USA"),
    ("https://allevents.in/washington/conferences", "Washington, DC, USA"),
    ("https://allevents.in/los-angeles/conferences", "Los Angeles, CA, USA"),
    ("https://allevents.in/san-diego/conferences", "San Diego, CA, USA"),
    ("https://allevents.in/miami/conferences", "Miami, FL, USA"),
]

NON_CONFERENCE_KEYWORDS = [
    "workshop", "webinar", "happy hour", "bar crawl", "speed dating",
    "singles", "karaoke", "bootcamp", "mixer", "dinner", "party",
    "networking lunch", "social mixer", "class", "brunch", "walk",
    "comic con", "paleyfest", "talks with", "artform", "art show",
    "stage", "screening", "exhibition", "concert", "comedy",
    "festival", "wellness walk", "becky g", "almodovar", "koom",
    "yoga", "bridal", "wedding", "holiday boutique", "craft fair",
    "holy spirit", "revival", "church", "ministry", "faith",
    "fraternity", "sorority", "salsa", "bachata", "kizomba", "barista",
    "book company", "evening with", "tour", "career fair",
    "certification", "training", "town hall", "meet up", "meetup",
    "networking event", "tech social", "auto show", "beer", "wine",
]


def _norm_ae_title(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


class AllEventsScraper(BaseScraper):
    def __init__(self):
        super().__init__("allevents", "https://allevents.in/united-states/conferences")

    def _fetch_single_detail(
        self,
        url: str,
        name: str,
        s_date: str,
        e_date: str,
        full_location: str,
        desc: str,
        win_start: date,
        win_end: date,
    ) -> Optional[RawEventData]:
        name = clean_html_text(name)
        desc = clean_html_text(desc)
        if not name or not url:
            return None
        if any(k in name.lower() for k in NON_CONFERENCE_KEYWORDS):
            return None
        if s_date and not self.is_date_in_window(s_date, win_start, win_end):
            return None

        organizer_name = ""
        official_site_url = url
        speaker_text = ""

        try:
            ev_resp = self.fetch_page(url, timeout=7)
            if ev_resp and ev_resp.status_code == 200:
                ev_soup = BeautifulSoup(ev_resp.text, 'html.parser')
                if not s_date:
                    for ld in ev_soup.find_all('script', type='application/ld+json'):
                        try:
                            ld_d = json.loads(ld.string or "")
                            if isinstance(ld_d, dict) and ld_d.get('startDate'):
                                s_date = str(ld_d['startDate'])[:10]
                                e_date = str(ld_d.get('endDate') or s_date)[:10]
                        except Exception:
                            pass
                if not s_date or not self.is_date_in_window(s_date, win_start, win_end):
                    return None
                text_all = clean_html_text(ev_soup.get_text('\n', strip=True))
                if "About the event" in text_all:
                    idx = text_all.find("About the event")
                    desc = text_all[idx:idx + 2500]
                elif "About this Event" in text_all:
                    idx = text_all.find("About this Event")
                    desc = text_all[idx:idx + 2500]

                m_org = re.search(r"organized by\s+([^.\n]+)", text_all, re.I)
                if m_org:
                    organizer_name = m_org.group(1).strip()

                for spk_marker in ["Featured Speakers", "Speakers", "Keynote Speakers"]:
                    if spk_marker in text_all:
                        spk_idx = text_all.find(spk_marker)
                        speaker_text = text_all[spk_idx:spk_idx + 1500]
                        break

                for a_link in ev_soup.find_all('a', href=True):
                    h = a_link['href'].strip()
                    if h.startswith('http') and not any(ign in h.lower() for ign in [
                        'allevents.in', 'google.com', 'facebook.com', 'twitter.com', 'x.com',
                        'linkedin.com', 'instagram.com', 'apple.com', 'itunes.apple',
                        'play.google', 'apps.apple', 'youtube.com', 'pinterest.com',
                        'tiktok.com', 'snapchat.com', 'vimeo.com', 'reddit.com'
                    ]):
                        official_site_url = h.rstrip('.,;)\"')
                        break
        except Exception as ev_err:
            logger.debug(f"Deep scrape error for {url}: {ev_err}")

        if not s_date or not self.is_date_in_window(s_date, win_start, win_end):
            return None

        raw_text_parts = [
            f"Conference Title: {name}",
            f"Overview: {desc}",
            f"Venue / Location: {full_location}",
            f"Start Date: {s_date}",
            f"End Date: {e_date or s_date}",
            f"Organizer: {organizer_name}",
            f"Official Event URL: {official_site_url or url}",
            f"Registration URL: {url}",
            "Source: All Events (allevents.in)",
            "Country: USA",
        ]
        if speaker_text:
            raw_text_parts.append(f"Agenda & Speakers Section:\n{speaker_text}")

        logger.info(f"[{self.source_name}] Harvested conference: {name} ({s_date}) in {full_location}")
        return RawEventData(
            source_name=self.source_name,
            source_url=official_site_url or url,
            raw_title=name,
            raw_text="\n".join(raw_text_parts),
            raw_location=full_location,
            raw_date=s_date
        )

    def scrape(self) -> List[RawEventData]:
        t_start = time.time()
        win_start, win_end = self.get_discovery_window()
        logger.info(f"[{self.source_name}] Live scraping genuine USA conferences from AllEvents ({win_start}..{win_end})...")
        events: List[RawEventData] = []
        seen_urls = set()
        seen_titles = set()
        candidates: List[Tuple[str, str, str, str, str, str]] = []

        for page_url, default_city in ALLEVENTS_URLS:
            if time.time() - t_start > 35 or len(candidates) >= 42:
                break
            try:
                resp = self.fetch_page(page_url, timeout=8)
                if not resp or resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                for s in soup.find_all('script', type='application/ld+json'):
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

                        for ev in items:
                            if not isinstance(ev, dict):
                                continue
                            name = clean_html_text(ev.get('name', '').strip())
                            url = (ev.get('url') or '').strip()
                            if not name or not url or url in seen_urls:
                                continue
                            if any(k in name.lower() for k in NON_CONFERENCE_KEYWORDS):
                                continue
                            t_key = _norm_ae_title(name)
                            if not t_key or t_key in seen_titles:
                                continue

                            start_date = ev.get('startDate', '')
                            end_date = ev.get('endDate', start_date)
                            s_date = start_date[:10] if len(start_date) >= 10 else ""
                            e_date = end_date[:10] if len(end_date) >= 10 else s_date
                            if s_date and not self.is_date_in_window(s_date, win_start, win_end):
                                continue

                            loc = ev.get('location', {})
                            venue = loc.get('name', '') if isinstance(loc, dict) else ''
                            addr = loc.get('address', {}) if isinstance(loc, dict) else {}
                            city_v = addr.get('addressLocality', '') if isinstance(addr, dict) else ''
                            state_v = addr.get('addressRegion', '') if isinstance(addr, dict) else ''
                            loc_label = f"{city_v}, {state_v}, USA".strip(', ') if (city_v or state_v) else default_city
                            full_location = f"{venue}, {loc_label}".strip(', ')

                            seen_urls.add(url)
                            seen_titles.add(t_key)
                            candidates.append((url, name, s_date, e_date, full_location, ev.get('description', '')))
                            if len(candidates) >= 42:
                                break
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"[{self.source_name}] Error crawling {page_url}: {e}")

        # Sanctioned Tavily supplement for AllEvents USA conferences in target month/year
        month_name = win_start.strftime("%B")
        t_query = f'site:allevents.in ("conference" OR "summit" OR "symposium") "{month_name} {win_start.year}" (USA OR "New York" OR "Chicago" OR "Boston" OR "San Francisco" OR "Las Vegas")'
        for r in self.tavily_search(t_query, max_results=6):
            r_url = (r.get("url") or "").strip()
            r_title = clean_html_text((r.get("title") or "").split("|")[0].strip())
            if not r_url or not r_title or r_url in seen_urls or r_url.rstrip("/").endswith("/conferences"):
                continue
            if any(k in r_title.lower() for k in NON_CONFERENCE_KEYWORDS):
                continue
            t_key = _norm_ae_title(r_title)
            if not t_key or t_key in seen_titles:
                continue
            seen_urls.add(r_url)
            seen_titles.add(t_key)
            candidates.append((r_url, r_title, "", "", "USA", r.get("content", "")))

        logger.info(f"[{self.source_name}] Discovered {len(candidates)} unique candidates. Fetching details concurrently...")
        remaining = max(15.0, 75.0 - (time.time() - t_start))
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [
                pool.submit(self._fetch_single_detail, u, nm, sd, ed, fl, ds, win_start, win_end)
                for (u, nm, sd, ed, fl, ds) in candidates
            ]
            try:
                for fut in as_completed(futs, timeout=remaining):
                    ev = fut.result()
                    if ev is not None:
                        events.append(ev)
            except Exception:
                pass

        logger.info(f"[{self.source_name}] Finished live scraping in {round(time.time() - t_start, 1)}s. Harvested {len(events)} events.")
        return events
