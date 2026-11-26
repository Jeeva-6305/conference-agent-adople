import logging
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper, clean_html_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

LUMA_CITY_URLS = [
    ("https://lu.ma/sf", "San Francisco, CA, USA"),
    ("https://lu.ma/nyc", "New York, NY, USA"),
    ("https://lu.ma/austin", "Austin, TX, USA"),
    ("https://lu.ma/la", "Los Angeles, CA, USA"),
    ("https://lu.ma/boston", "Boston, MA, USA"),
    ("https://lu.ma/seattle", "Seattle, WA, USA"),
    ("https://lu.ma/chicago", "Chicago, IL, USA"),
    ("https://lu.ma/dc", "Washington, DC, USA"),
    ("https://lu.ma/miami", "Miami, FL, USA"),
    ("https://lu.ma/denver", "Denver, CO, USA"),
    ("https://lu.ma/atlanta", "Atlanta, GA, USA"),
    ("https://lu.ma/ai", "USA"),
]

CONFERENCE_TERMS = ["conference", "summit", "symposium", "forum", "congress", "expo", "panel", "decision", "odyssey", "build day", "stack", "showcase"]


def extract_prosemirror_text(node) -> str:
    text = ""
    if isinstance(node, dict):
        node_type = node.get("type")
        if node_type == "text":
            text += node.get("text", "")
        for val in node.get("content", []):
            text += extract_prosemirror_text(val) + " "
        if node_type in ("paragraph", "list_item", "heading"):
            text += "\n"
    elif isinstance(node, list):
        for item in node:
            text += extract_prosemirror_text(item) + " "
    return text


class LumaScraper(BaseScraper):
    def __init__(self):
        super().__init__("luma", "https://lu.ma/discover")

    def _harvest_luma_event(
        self,
        full_url: str,
        name: str,
        start_date: str,
        end_date: str,
        default_loc: str,
        win_start: date,
        win_end: date,
        events: List[RawEventData],
        seen_urls: set,
    ) -> None:
        name = clean_html_text(name)
        if not name or not full_url or full_url in seen_urls:
            return
        name_lower = name.lower()
        if not any(t in name_lower for t in CONFERENCE_TERMS):
            return
        if start_date and not self.is_date_in_window(start_date, win_start, win_end):
            return

        detailed_speakers_text = ""
        detailed_desc = ""
        attendee_count_str = ""
        loc_resolved = default_loc

        try:
            ev_resp = self.fetch_page(full_url, timeout=10)
            if ev_resp and ev_resp.status_code == 200:
                ev_soup = BeautifulSoup(ev_resp.text, 'html.parser')
                ev_script = ev_soup.find('script', id='__NEXT_DATA__')
                if ev_script and ev_script.string:
                    ev_data = json.loads(ev_script.string)
                    pdata = ev_data.get('props', {}).get('pageProps', {}).get('initialData', {}).get('data', {})
                    ev_meta = pdata.get('event', {}) if isinstance(pdata, dict) else {}
                    if not start_date and ev_meta.get('start_at'):
                        start_date = str(ev_meta['start_at'])[:10]
                        end_date = str(ev_meta.get('end_at') or start_date)[:10]
                    geo_info = ev_meta.get('geo_address_info', {}) if isinstance(ev_meta, dict) else {}
                    if isinstance(geo_info, dict) and geo_info.get('city'):
                        c_part = geo_info.get('city', '')
                        s_part = geo_info.get('region', '')
                        cnt_part = geo_info.get('country', 'USA')
                        loc_resolved = f"{c_part}, {s_part}, {cnt_part}".strip(', ')

                    desc_mirror = pdata.get('description_mirror', {})
                    detailed_desc = clean_html_text(extract_prosemirror_text(desc_mirror))

                    g_count = pdata.get('guest_count') or 0
                    t_count = pdata.get('ticket_count') or 0
                    if g_count > 0 or t_count > 0:
                        attendee_count_str = str(max(g_count, t_count))

                    spk_lines = []
                    for person_entry in (list(pdata.get('hosts', []) or []) + list(pdata.get('featured_guests', []) or [])):
                        if not isinstance(person_entry, dict):
                            continue
                        p_name = clean_html_text(person_entry.get('name', ''))
                        if not p_name:
                            continue
                        # Strict zero-fabrication: keep bio empty when absent instead of fake fallback strings
                        bio = clean_html_text(person_entry.get('bio_short', '') or '')
                        lh = (person_entry.get('linkedin_handle') or '').strip()
                        l_url = f"https://www.linkedin.com{lh}" if lh.startswith('/in/') else (lh if 'linkedin.com/in/' in lh.lower() else "")
                        if bio or l_url:
                            spk_lines.append(f"- {p_name}, {bio} | LinkedIn: {l_url}".strip())
                        else:
                            spk_lines.append(f"- {p_name}")

                    if spk_lines:
                        detailed_speakers_text = "Hosts & Featured Guests:\n" + "\n".join(spk_lines)
        except Exception as ev_err:
            logger.debug(f"[{self.source_name}] Detailed fetch error for {full_url}: {ev_err}")

        if not start_date or not self.is_date_in_window(start_date, win_start, win_end):
            return

        seen_urls.add(full_url)

        official_site_url = ""
        url_matches = re.findall(r"https?://(?:www\.)?[a-zA-Z0-9\-\.]+\.[a-zA-Z]{2,}(?:/[^\s\)\"\']*)?", detailed_desc)
        for um in url_matches:
            um_clean = um.rstrip(".,;)\"\'")
            if not any(ign in um_clean.lower() for ign in ["lu.ma", "luma.com", "google.com", "twitter.com", "x.com", "instagram.com"]):
                official_site_url = um_clean
                break

        if official_site_url:
            try:
                from .live_speaker_scraper import fetch_official_site_speakers
                off_spks = fetch_official_site_speakers(official_site_url, name)
                if off_spks:
                    spk_formatted = []
                    for ospk in off_spks:
                        spk_formatted.append(
                            f"- {ospk['speaker_name']}, {ospk['job_role_designation']} at {ospk['company_name']} "
                            f"| LinkedIn: {ospk['linkedin_url']} | Source: {ospk['source_url']}"
                        )
                    detailed_speakers_text = "Featured Speakers:\n" + "\n".join(spk_formatted)
            except Exception as e:
                logger.debug(f"Official site speaker fetch error: {e}")

        primary_url = official_site_url if official_site_url else full_url

        raw_text_parts = [
            f"Conference Title: {name}",
            "Source: Luma Tech Discovery",
            f"Official URL: {primary_url}",
            f"Registration URL: {full_url}",
            f"Start Date: {start_date}",
            f"End Date: {end_date or start_date}",
            f"Location: {loc_resolved}",
        ]
        if detailed_desc:
            raw_text_parts.append(f"Overview: {detailed_desc}")
        if detailed_speakers_text:
            raw_text_parts.append(detailed_speakers_text)
        if attendee_count_str:
            raw_text_parts.append(f"Registered Attendees: {attendee_count_str}")

        events.append(RawEventData(
            source_name=self.source_name,
            source_url=primary_url,
            raw_title=name,
            raw_text="\n".join(raw_text_parts),
            raw_location=loc_resolved,
            raw_date=start_date
        ))
        logger.info(f"[{self.source_name}] Harvested genuine Luma conference: {name} ({start_date})")

    def scrape(self) -> List[RawEventData]:
        win_start, win_end = self.get_discovery_window()
        logger.info(f"[{self.source_name}] Live scraping genuine tech conferences from Luma ({win_start}..{win_end})...")
        events: List[RawEventData] = []
        seen_urls = set()

        for page_url, default_loc in LUMA_CITY_URLS:
            try:
                resp = self.fetch_page(page_url, timeout=12)
                if not resp or resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, 'html.parser')
                next_script = soup.find('script', id='__NEXT_DATA__')
                if not next_script or not next_script.string:
                    continue

                data = json.loads(next_script.string)
                page_data = data.get('props', {}).get('pageProps', {}).get('initialData', {}).get('data', {})
                raw_events = page_data.get('events', [])

                for item in raw_events:
                    ev = item.get('event', {})
                    name = ev.get('name', '').strip()
                    url_slug = ev.get('url', '')
                    start_at = ev.get('start_at', '')
                    end_at = ev.get('end_at', '')
                    if not name or not url_slug:
                        continue
                    full_url = f"https://lu.ma/{url_slug}"
                    start_date = start_at[:10] if len(start_at) >= 10 else ""
                    end_date = end_at[:10] if len(end_at) >= 10 else start_date
                    self._harvest_luma_event(
                        full_url=full_url,
                        name=name,
                        start_date=start_date,
                        end_date=end_date,
                        default_loc=default_loc,
                        win_start=win_start,
                        win_end=win_end,
                        events=events,
                        seen_urls=seen_urls,
                    )
            except Exception as e:
                logger.error(f"[{self.source_name}] Error crawling {page_url}: {e}")

        # Sanctioned Tavily supplement for Luma events in target month/year
        month_name = win_start.strftime("%B")
        t_query = f'(site:lu.ma OR site:luma.com) ("conference" OR "summit" OR "forum") "{month_name} {win_start.year}" (AI OR healthcare OR fintech OR "San Francisco" OR "New York" OR "Boston")'
        for r in self.tavily_search(t_query, max_results=8):
            r_url = (r.get("url") or "").strip().split("?")[0]
            r_title = (r.get("title") or "").split("·")[0].split("|")[0].strip()
            if not r_url or r_url in seen_urls or r_url.rstrip("/") in ("https://lu.ma", "https://lu.ma/discover", "https://luma.com"):
                continue
            self._harvest_luma_event(
                full_url=r_url,
                name=r_title,
                start_date="",
                end_date="",
                default_loc="USA",
                win_start=win_start,
                win_end=win_end,
                events=events,
                seen_urls=seen_urls,
            )

        logger.info(f"[{self.source_name}] Live Luma collection finished. Total events: {len(events)}")
        return events
