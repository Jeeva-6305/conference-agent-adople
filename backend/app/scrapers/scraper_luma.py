import logging
import requests
from bs4 import BeautifulSoup
import json
import re
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
}

LUMA_CITY_URLS = [
    ("https://lu.ma/sf", "San Francisco, CA, USA"),
    ("https://lu.ma/nyc", "New York, NY, USA"),
    ("https://lu.ma/austin", "Austin, TX, USA")
]

CONFERENCE_TERMS = ["conference", "summit", "symposium", "forum", "congress", "expo", "panel", "decision", "odyssey", "build day", "stack"]

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

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping genuine tech conferences from Luma...")
        events: List[RawEventData] = []
        seen_urls = set()

        for page_url, default_loc in LUMA_CITY_URLS:
            try:
                resp = requests.get(page_url, headers=HEADERS, timeout=12)
                if resp.status_code != 200:
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
                    if full_url in seen_urls:
                        continue

                    # Filter for conferences, summits, panels, tech events
                    name_lower = name.lower()
                    if not any(t in name_lower for t in CONFERENCE_TERMS):
                        continue

                    seen_urls.add(full_url)
                    start_date = start_at[:10] if len(start_at) >= 10 else ""
                    end_date = end_at[:10] if len(end_at) >= 10 else start_date

                    # Deep scrape individual event page for full description, speakers, and hosts
                    detailed_speakers_text = ""
                    detailed_desc = ""
                    attendee_count_str = ""

                    try:
                        ev_resp = requests.get(full_url, headers=HEADERS, timeout=10)
                        if ev_resp.status_code == 200:
                            ev_soup = BeautifulSoup(ev_resp.text, 'html.parser')
                            ev_script = ev_soup.find('script', id='__NEXT_DATA__')
                            if ev_script and ev_script.string:
                                ev_data = json.loads(ev_script.string)
                                pdata = ev_data.get('props', {}).get('pageProps', {}).get('initialData', {}).get('data', {})
                                
                                # Extract full prose description
                                desc_mirror = pdata.get('description_mirror', {})
                                detailed_desc = extract_prosemirror_text(desc_mirror).strip()

                                # Extract attendee/ticket count if available
                                g_count = pdata.get('guest_count') or 0
                                t_count = pdata.get('ticket_count') or 0
                                if g_count > 0 or t_count > 0:
                                    attendee_count_str = str(max(g_count, t_count))

                                # Extract hosts and featured guests
                                spk_lines = []
                                for h in pdata.get('hosts', []):
                                    h_name = h.get('name', '').strip()
                                    if not h_name:
                                        continue
                                    bio = h.get('bio_short', '').strip() if h.get('bio_short') else "Event Host & Organizer"
                                    lh = h.get('linkedin_handle', '')
                                    l_url = f"https://www.linkedin.com{lh}" if lh and lh.startswith('/') else (lh or "")
                                    spk_lines.append(f"- {h_name}, {bio} | LinkedIn: {l_url}")

                                for g in pdata.get('featured_guests', []):
                                    if isinstance(g, dict):
                                        g_name = g.get('name', '').strip()
                                        if not g_name:
                                            continue
                                        bio = g.get('bio_short', '').strip() if g.get('bio_short') else "Featured Guest"
                                        lh = g.get('linkedin_handle', '')
                                        l_url = f"https://www.linkedin.com{lh}" if lh and lh.startswith('/') else (lh or "")
                                        spk_lines.append(f"- {g_name}, {bio} | LinkedIn: {l_url}")

                                if spk_lines:
                                    detailed_speakers_text = "Hosts & Featured Guests:\n" + "\n".join(spk_lines)
                    except Exception as ev_err:
                        logger.debug(f"[{self.source_name}] Detailed fetch error for {full_url}: {ev_err}")

                    raw_text_parts = [
                        f"Conference Title: {name}",
                        f"Source: Luma Tech Discovery",
                        f"Official URL: {full_url}",
                        f"Registration URL: {full_url}",
                        f"Start Date: {start_date}",
                        f"End Date: {end_date}",
                        f"Location: {default_loc}"
                    ]
                    if detailed_desc:
                        raw_text_parts.append(f"Overview: {detailed_desc}")
                    if detailed_speakers_text:
                        raw_text_parts.append(detailed_speakers_text)
                    if attendee_count_str:
                        raw_text_parts.append(f"Registered Attendees: {attendee_count_str}")

                    raw_text = "\n".join(raw_text_parts)

                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=full_url,
                        raw_title=name,
                        raw_text=raw_text,
                        raw_location=default_loc,
                        raw_date=start_date
                    ))

                    logger.info(f"[{self.source_name}] Harvested genuine Luma conference: {name} ({start_date})")

            except Exception as e:
                logger.error(f"[{self.source_name}] Error crawling {page_url}: {e}")

        logger.info(f"[{self.source_name}] Live Luma collection finished. Total events: {len(events)}")
        return events
