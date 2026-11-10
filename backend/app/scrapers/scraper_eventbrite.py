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

NON_CONFERENCE_KEYWORDS = [
    "workshop", "webinar", "happy hour", "bar crawl", "speed dating",
    "singles", "karaoke", "bootcamp", "mixer", "dinner", "party",
    "networking lunch", "social mixer", "class", "brunch", "walk",
    "comic con", "comedy", "stage", "festival", "screening", "talks with",
    "forest preserve", "zoo", "wildlife", "conservation symposium",
    "yoga", "pre-natal", "post-natal", "bridal", "wedding expo", "wedding show",
    "holiday boutique", "craft fair", "holy spirit", "revival", "reasonable faith",
    "church", "ministry", "fraternity", "sorority", "salsa", "bachata", "kizomba",
    "barista", "artist", "healing", "certification", "career fair", "pitch night",
    "poetry", "fashion", "concert", "gala", "fundraiser", "paint", "trivia",
    "nature summit", "tour",
]


def _norm_eb_title(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


class EventbriteScraper(BaseScraper):
    def __init__(self):
        super().__init__("eventbrite", "https://www.eventbrite.com/d/united-states/conferences/")

    def _fetch_detail(
        self,
        name: str,
        url: str,
        win_start: date,
        win_end: date,
    ) -> Optional[RawEventData]:
        try:
            resp = self.fetch_page(url, timeout=8)
            if not resp or resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, 'html.parser')
            event_data = None
            for s in soup.find_all('script', type='application/ld+json'):
                try:
                    d = json.loads(s.string or "")
                    if isinstance(d, dict) and d.get('@type') in ['BusinessEvent', 'Event']:
                        event_data = d
                        break
                except Exception:
                    pass

            if not event_data:
                return None

            title = clean_html_text(event_data.get('name', name))
            if any(k in title.lower() for k in NON_CONFERENCE_KEYWORDS):
                return None

            desc = clean_html_text(event_data.get('description', ''))
            start_iso = event_data.get('startDate', '')
            end_iso = event_data.get('endDate', '')

            start_date = start_iso[:10] if len(start_iso) >= 10 else ""
            end_date = end_iso[:10] if len(end_iso) >= 10 else start_date
            if not start_date or not self.is_date_in_window(start_date, win_start, win_end):
                return None

            loc = event_data.get('location', {})
            venue_name = clean_html_text(loc.get('name', '')) if isinstance(loc, dict) else ""
            addr = loc.get('address', {}) if isinstance(loc, dict) else {}
            city = clean_html_text(addr.get('addressLocality', '')) if isinstance(addr, dict) else ""
            state = clean_html_text(addr.get('addressRegion', '')) if isinstance(addr, dict) else ""
            country = clean_html_text(addr.get('addressCountry', 'USA')) if isinstance(addr, dict) else "USA"
            street = clean_html_text(addr.get('streetAddress', '')) if isinstance(addr, dict) else ""
            full_loc = f"{venue_name}, {street}, {city}, {state}, {country}".strip(', ')

            if country not in ['US', 'USA', 'United States'] and 'US' not in state:
                return None

            organizer_data = event_data.get('organizer', {})
            organizer_name = clean_html_text(organizer_data.get('name', '')) if isinstance(organizer_data, dict) else ""

            performers = event_data.get('performer', [])
            performer_names = []
            performer_details = []
            full_body_text = clean_html_text(soup.get_text('\n', strip=True))
            full_desc_and_body = f"{desc} {full_body_text}"
            if isinstance(performers, list):
                for p in performers:
                    if isinstance(p, dict):
                        p_name = clean_html_text(p.get('name', ''))
                        p_url = p.get('url', '')
                        if p_name and p_name.lower() not in title.lower():
                            performer_names.append(p_name)
                            m_rc = re.search(rf"\b{re.escape(p_name)}\s*\(([^()]+?)\)", full_desc_and_body)
                            if m_rc:
                                rc_str = m_rc.group(1).replace("\n", " ").strip()
                                performer_details.append(f"{p_name} ({rc_str})")
                            else:
                                m_comp = re.search(rf"\b{re.escape(p_name)}\s+(?:from|of|at)\s+([A-Z][A-Za-z0-9\.\s&]+?)(?:\s*[,–\.\n]|Career|Investing|Tickets|\Z)", full_desc_and_body)
                                if m_comp:
                                    c_name = m_comp.group(1).replace("\n", " ").strip()
                                    performer_details.append(f"{p_name} (Speaker at {c_name})")
                                elif p_url:
                                    performer_details.append(f"{p_name} ({p_url})")
                                else:
                                    performer_details.append(p_name)

            faq_text = ""
            for s in soup.find_all('script', type='application/ld+json'):
                try:
                    fd = json.loads(s.string or "")
                    if isinstance(fd, dict) and fd.get('@type') == 'FAQPage':
                        for q in fd.get('mainEntity', []):
                            q_name = clean_html_text(q.get('name', ''))
                            q_ans = clean_html_text(q.get('acceptedAnswer', {}).get('text', ''))
                            faq_text += f"\n{q_name}: {q_ans}"
                except Exception:
                    pass

            offers = event_data.get('offers', [])
            pub_date = ""
            if isinstance(offers, list) and len(offers) > 0:
                first_offer = offers[0]
                valid_from = first_offer.get('validFrom', '')
                if valid_from:
                    pub_date = valid_from[:10]

            speaker_section_text = ""
            for spk_marker in ["Featured Speakers", "Keynote Speakers", "Our Speakers", "Speakers"]:
                if spk_marker in full_body_text:
                    s_idx = full_body_text.find(spk_marker)
                    speaker_section_text = full_body_text[s_idx:s_idx + 2000]
                    break

            official_site_url = ""
            for a in soup.find_all('a', href=True):
                h_val = a['href'].strip()
                if h_val.startswith('http') and not any(ign in h_val.lower() for ign in [
                    'eventbrite.com', 'google.com', 'facebook.com', 'twitter.com', 'x.com',
                    'instagram.com', 'linkedin.com', 'youtube.com', 'apple.com', 'android.com',
                    'pinterest.com', 'tiktok.com', 'snapchat.com', 'vimeo.com', 'w3.org'
                ]):
                    official_site_url = h_val.rstrip('.,;)\"')
                    break

            primary_url = official_site_url if official_site_url else url

            raw_text_parts = [
                f"Conference Title: {title}",
                f"Overview & Description: {desc}",
                f"Venue: {venue_name}",
                f"Address: {street}, {city}, {state}, {country}",
                f"Organizer: {organizer_name}",
                f"Official Event URL: {primary_url}",
                f"Registration URL: {url}",
                f"Start Date: {start_date}",
                f"End Date: {end_date}",
            ]
            if pub_date:
                raw_text_parts.append(f"Publication / Announcement Date: {pub_date}")
            if performer_names:
                raw_text_parts.append(f"Featured Speakers / Keynotes: {', '.join(performer_details)}")
            if speaker_section_text:
                raw_text_parts.append(f"Agenda & Speakers Section:\n{speaker_section_text}")
            if faq_text:
                raw_text_parts.append(f"Conference Schedule & FAQ Details: {faq_text}")

            logger.info(f"[{self.source_name}] Harvested genuine conference: {title} ({start_date}) in {city}, {state}")
            return RawEventData(
                source_name=self.source_name,
                source_url=primary_url,
                raw_title=title,
                raw_text="\n".join(raw_text_parts),
                raw_location=full_loc,
                raw_date=start_date
            )
        except Exception as e:
            logger.debug(f"[{self.source_name}] Error parsing details for {url}: {e}")
            return None

    def scrape(self) -> List[RawEventData]:
        t_start = time.time()
        win_start, win_end = self.get_discovery_window()
        sun_str = win_start.isoformat()
        sat_str = win_end.isoformat()
        logger.info(f"[{self.source_name}] Live scraping genuine USA conferences from Eventbrite ({sun_str}..{sat_str})...")
        events: List[RawEventData] = []
        seen_urls = set()
        seen_titles = set()
        candidate_items: List[Tuple[str, str]] = []

        discovery_urls = [
            f"https://www.eventbrite.com/d/united-states/business--conferences/?start_date={sun_str}&end_date={sat_str}",
            f"https://www.eventbrite.com/d/united-states/business--conferences/?start_date={sun_str}&end_date={sat_str}&page=2",
            f"https://www.eventbrite.com/d/united-states/science-and-tech--conferences/?start_date={sun_str}&end_date={sat_str}",
            f"https://www.eventbrite.com/d/united-states/health--conferences/?start_date={sun_str}&end_date={sat_str}",
            f"https://www.eventbrite.com/d/united-states/conferences/?start_date={sun_str}&end_date={sat_str}",
            f"https://www.eventbrite.com/d/ny--new-york/conferences/?start_date={sun_str}&end_date={sat_str}",
            f"https://www.eventbrite.com/d/ca--san-francisco/conferences/?start_date={sun_str}&end_date={sat_str}",
            f"https://www.eventbrite.com/d/ma--boston/conferences/?start_date={sun_str}&end_date={sat_str}",
            f"https://www.eventbrite.com/d/il--chicago/conferences/?start_date={sun_str}&end_date={sat_str}",
            f"https://www.eventbrite.com/d/nv--las-vegas/conferences/?start_date={sun_str}&end_date={sat_str}",
            f"https://www.eventbrite.com/d/dc--washington/conferences/?start_date={sun_str}&end_date={sat_str}",
        ]

        # Step 1: Collect unique target-window candidate listings in bounded time
        for disc_url in discovery_urls:
            if time.time() - t_start > 30 or len(candidate_items) >= 48:
                break
            try:
                resp = self.fetch_page(disc_url, timeout=6)
                if not resp or resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                for s in soup.find_all('script', type='application/ld+json'):
                    try:
                        data = json.loads(s.string or "")
                        items = []
                        if isinstance(data, dict) and 'itemListElement' in data:
                            items = [el.get('item', {}) for el in data['itemListElement']]
                        elif isinstance(data, list):
                            items = data

                        for item in items:
                            if not isinstance(item, dict):
                                continue
                            url = (item.get('url') or '').split("?")[0].strip()
                            name = clean_html_text(item.get('name', ''))
                            item_start = (item.get('startDate') or '')[:10]
                            if not url or not name or url in seen_urls:
                                continue

                            name_lower = name.lower()
                            if any(k in name_lower for k in NON_CONFERENCE_KEYWORDS):
                                continue
                            t_key = _norm_eb_title(name)
                            if not t_key or t_key in seen_titles:
                                continue

                            if item_start and not self.is_date_in_window(item_start, win_start, win_end):
                                continue

                            seen_urls.add(url)
                            seen_titles.add(t_key)
                            candidate_items.append((name, url))
                            if len(candidate_items) >= 48:
                                break
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"[{self.source_name}] Error crawling {disc_url}: {e}")

        # Sanctioned Tavily supplement for Eventbrite USA conferences in target window
        month_name = win_start.strftime("%B")
        t_query = f'site:eventbrite.com/e ("conference" OR "summit" OR "symposium") "{month_name} {win_start.year}" (AI OR healthcare OR fintech OR "New York" OR "San Francisco" OR "Boston" OR "Chicago")'
        for r in self.tavily_search(t_query, max_results=8):
            r_url = (r.get("url") or "").split("?")[0].strip()
            r_title = clean_html_text(r.get("title") or "").split("Tickets")[0].strip()
            if not r_url or "/e/" not in r_url or r_url in seen_urls:
                continue
            if any(k in r_title.lower() for k in NON_CONFERENCE_KEYWORDS):
                continue
            t_key = _norm_eb_title(r_title)
            if not t_key or t_key in seen_titles:
                continue
            seen_urls.add(r_url)
            seen_titles.add(t_key)
            candidate_items.append((r_title, r_url))

        logger.info(f"[{self.source_name}] Found {len(candidate_items)} unique target-window candidate URLs. Fetching details concurrently...")

        # Step 2: Concurrent detail fetch bounded within 75s budget
        remaining = max(15.0, 75.0 - (time.time() - t_start))
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [pool.submit(self._fetch_detail, name, url, win_start, win_end) for name, url in candidate_items]
            try:
                for fut in as_completed(futs, timeout=remaining):
                    ev = fut.result()
                    if ev is not None:
                        events.append(ev)
            except Exception:
                pass

        logger.info(f"[{self.source_name}] Live collection finished in {round(time.time() - t_start, 1)}s. Harvested {len(events)} genuine conferences.")
        return events
