import logging
import re
from datetime import date, timedelta
from typing import List, Set
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper, clean_html_text, extract_date_range_from_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

EVENTSEYE_USA_URL = "https://www.eventseye.com/fairs/c1_trade-shows_usa-united-states-of-america.html"


def _parse_eventseye_date(date_text: str, win_start: date, win_end: date) -> str:
    """
    Parses EventsEye MM/DD/YYYY (used on cd1_usa_{month} pages) or DD/MM/YYYY safely,
    preferring whichever interpretation falls in win_start..win_end month(s).
    """
    m_date = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_text)
    if not m_date:
        return ""
    d1, d2, yr = int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
    target_months = {win_start.month, win_end.month}

    # Try MM/DD/YYYY first if d1 matches target month (or standard US ordering)
    candidates = []
    if d1 in target_months and 1 <= d2 <= 31:
        candidates.append((yr, d1, d2))
    if d2 in target_months and 1 <= d1 <= 31:
        candidates.append((yr, d2, d1))
    # Generic fallback ordering: MM/DD then DD/MM
    if 1 <= d1 <= 12 and 1 <= d2 <= 31:
        candidates.append((yr, d1, d2))
    if 1 <= d2 <= 12 and 1 <= d1 <= 31:
        candidates.append((yr, d2, d1))

    for y, m, d in candidates:
        try:
            return date(y, m, d).isoformat()
        except ValueError:
            continue
    return ""


class EventsEyeScraper(BaseScraper):
    def __init__(self):
        super().__init__("eventseye", EVENTSEYE_USA_URL)

    def scrape(self) -> List[RawEventData]:
        win_start, win_end = self.get_discovery_window()
        logger.info(
            f"[{self.source_name}] Live scraping genuine USA trade shows & conferences "
            f"from EventsEye for {win_start}..{win_end}..."
        )
        events: List[RawEventData] = []
        today = date.today()

        # Build month directory pages dynamically (supports week spanning two months)
        target_months: List[str] = [win_start.strftime("%B").lower()]
        if win_end.month != win_start.month:
            target_months.append(win_end.strftime("%B").lower())

        pages_to_crawl: List[str] = []
        queued_pages: Set[str] = set()
        for mon_name in target_months:
            for suffix in [f"{mon_name}_0", f"{mon_name}_0_1", f"{mon_name}_0_2"]:
                u = f"https://www.eventseye.com/fairs/cd1_trade-shows_usa-united-states-of-america_{suffix}.html"
                if u not in queued_pages:
                    queued_pages.add(u)
                    pages_to_crawl.append(u)
        pages_to_crawl.append(self.base_url)

        candidate_rows = []
        seen_detail_urls: Set[str] = set()

        idx = 0
        while idx < len(pages_to_crawl):
            page_url = pages_to_crawl[idx]
            idx += 1
            try:
                soup = self.fetch_soup(page_url, timeout=12)
                if not soup:
                    continue

                # Discover additional pagination links for target months (year 0 / current year)
                for a in soup.find_all('a', href=True):
                    href = a['href'].strip()
                    if any(f"usa-united-states-of-america_{m}_0" in href.lower() for m in target_months):
                        next_u = href if href.startswith("http") else (f"https://www.eventseye.com{href}" if href.startswith("/") else f"https://www.eventseye.com/fairs/{href}")
                        if next_u not in queued_pages and len(pages_to_crawl) < 12:
                            queued_pages.add(next_u)
                            pages_to_crawl.append(next_u)

                for tr in soup.find_all('tr'):
                    tds = tr.find_all('td')
                    if len(tds) < 4:
                        continue
                    link_el = tds[0].find('a', href=True)
                    if not link_el:
                        continue
                    title_node = link_el.find(['b', 'strong']) or link_el
                    title = clean_html_text(title_node.get_text(" ", strip=True))
                    # Cell 0 may also include sector blurb after <a>; capture full cell text cleanly
                    sector_blurb = clean_html_text(tds[0].get_text(" ", strip=True))
                    if any(b in f"{title} {sector_blurb}".lower() for b in [
                        "bridal", "wedding", "holiday boutique", "art & craft", "craft fair",
                        "pool | spa | patio", "deck expo", "gift expo"
                    ]):
                        continue
                    venue_city = clean_html_text(tds[2].get_text(' ', strip=True))
                    date_text = clean_html_text(tds[3].get_text(' ', strip=True))

                    iso_str = _parse_eventseye_date(date_text, win_start, win_end)
                    if not iso_str:
                        continue
                    event_date = date.fromisoformat(iso_str)
                    if event_date < today or not (win_start <= event_date <= win_end):
                        continue

                    rel_url = link_el['href'].strip()
                    full_url = f"https://www.eventseye.com/fairs/{rel_url}" if not rel_url.startswith('http') else rel_url
                    if full_url in seen_detail_urls:
                        continue
                    seen_detail_urls.add(full_url)

                    # Compute end date if "N days" is printed in EventsEye cell
                    end_date = event_date
                    m_days = re.search(r'(\d+)\s+days?', date_text, re.I)
                    if m_days:
                        n_days = int(m_days.group(1))
                        if 1 < n_days <= 14:
                            end_date = event_date + timedelta(days=n_days - 1)

                    candidate_rows.append({
                        "title": title,
                        "sector_blurb": sector_blurb,
                        "venue_city": venue_city,
                        "date_str": event_date.isoformat(),
                        "end_date_str": end_date.isoformat(),
                        "url": full_url
                    })
            except Exception as e:
                logger.warning(f"[{self.source_name}] Error crawling {page_url}: {e}")

        candidate_rows.sort(key=lambda x: x["date_str"])
        logger.info(f"[{self.source_name}] Found {len(candidate_rows)} target-window USA trade shows before detail fetch.")

        for item in candidate_rows[:35]:
            official_site = item["url"]
            desc = item["sector_blurb"] or f"{item['title']} held in {item['venue_city']}, USA."
            organizer = ""
            industries_txt = ""

            try:
                detail_soup = self.fetch_soup(item["url"], timeout=8)
                if detail_soup:
                    for a_tag in detail_soup.find_all('a', href=True):
                        txt = a_tag.get_text(strip=True)
                        href = a_tag['href'].strip()
                        if "Official Web Site" in txt and href.startswith('http'):
                            official_site = href
                            break
                        elif "Web Site" in txt and href.startswith('http') and not any(ign in href for ign in ['eventseye', 'facebook', 'twitter', 'linkedin']):
                            official_site = href

                    body_txt = clean_html_text(detail_soup.get_text('\n', strip=True))
                    if "Description" in body_txt:
                        d_idx = body_txt.find("Description")
                        desc = body_txt[d_idx:d_idx + 800].replace("\n", " ")
                    m_sec = re.search(r"Industries\s*[:\n]+([^\n]{3,200})", body_txt, re.I)
                    if m_sec:
                        industries_txt = m_sec.group(1).strip()
                    m_org = re.search(r"Organizers?\s*[:\n]+([^\n]{2,120})", body_txt, re.I)
                    if m_org:
                        organizer = m_org.group(1).strip()
            except Exception as d_err:
                logger.debug(f"[{self.source_name}] Error parsing detail for {item['url']}: {d_err}")

            raw_parts = [
                f"Conference Title: {item['title']}",
                f"Overview & Description: {desc}",
                f"Venue: {item['venue_city']}",
                f"Address: {item['venue_city']}, USA",
                f"Official Event URL: {official_site}",
                f"Registration URL: {item['url']}",
                f"Start Date: {item['date_str']}",
                f"End Date: {item['end_date_str']}",
                "Source: EventsEye",
                "Country: USA",
            ]
            if organizer:
                raw_parts.append(f"Organizer: {organizer}")
            if industries_txt:
                raw_parts.append(f"Industries: {industries_txt}")

            events.append(RawEventData(
                source_name=self.source_name,
                source_url=official_site,
                raw_title=item["title"],
                raw_text="\n".join(raw_parts),
                raw_location=f"{item['venue_city']}, USA",
                raw_date=item["date_str"]
            ))
            logger.info(f"[{self.source_name}] Harvested conference: {item['title']} ({item['date_str']}) in {item['venue_city']}")

        # Sanctioned Tavily supplement if EventsEye direct pages yielded few target-week items
        if len(events) < 5:
            mon_name = win_start.strftime("%B")
            for r in self.tavily_search(f'site:eventseye.com/fairs "{mon_name} {win_start.year}" USA', max_results=6):
                r_url = (r.get("url") or "").strip()
                r_title = clean_html_text(r.get("title") or "").split("|")[0].split("-")[0].strip()
                r_content = clean_html_text(r.get("content") or "")
                if not r_url or not r_title or r_url in seen_detail_urls:
                    continue
                s_iso, e_iso = extract_date_range_from_text(f"{r_title} {r_content}", default_year=win_start.year)
                if not s_iso or not self.is_date_in_window(s_iso, win_start, win_end):
                    continue
                seen_detail_urls.add(r_url)
                events.append(RawEventData(
                    source_name=self.source_name,
                    source_url=r_url,
                    raw_title=r_title,
                    raw_text=(
                        f"Conference Title: {r_title}\n"
                        f"Overview & Description: {r_content}\n"
                        f"Official Event URL: {r_url}\n"
                        f"Start Date: {s_iso}\n"
                        f"End Date: {e_iso or s_iso}\n"
                        f"Source: EventsEye / Tavily\nCountry: USA"
                    ),
                    raw_location="USA",
                    raw_date=s_iso
                ))

        logger.info(f"[{self.source_name}] Finished collection. Harvested {len(events)} events.")
        return events
