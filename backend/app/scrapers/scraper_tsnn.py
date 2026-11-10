import logging
import re
from datetime import date, datetime, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper, clean_html_text, extract_date_range_from_text
from ..schemas import RawEventData

logger = logging.getLogger(__name__)


class TSNNScraper(BaseScraper):
    def __init__(self):
        super().__init__("tsnn", "https://thetradeshowcalendar.com/tsnn/index.php")

    def scrape(self) -> List[RawEventData]:
        win_start, win_end = self.get_discovery_window()
        logger.info(
            f"[{self.source_name}] Harvesting major national trade shows & technical conventions "
            f"from TSNN for {win_start}..{win_end}..."
        )
        events: List[RawEventData] = []
        seen_titles = set()
        seen_urls = set()
        today = date.today()

        # 1. Live crawl TSNN official tradeshow calendar feed (vRpP=200 covers full upcoming window)
        try:
            resp = self.fetch_page("https://thetradeshowcalendar.com/tsnn/index.php?vCtry=United+States&vRpP=200", timeout=15)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for tr in soup.find_all('tr'):
                    tds = tr.find_all('td')
                    if len(tds) >= 4:
                        a = tds[1].find('a')
                        if not a or not a.get('href'):
                            continue
                        title = clean_html_text(a.get_text(strip=True))
                        link = a['href'].strip()
                        if link.startswith('//'):
                            link = 'https:' + link
                        elif not link.startswith('http'):
                            continue

                        dates_text = tds[2].get_text(separator=' ', strip=True)
                        loc = clean_html_text(tds[3].get_text(separator=' ', strip=True))
                        m_dates = re.findall(r'([A-Z]{3})/(\d{1,2})/(\d{4})', dates_text)
                        if not m_dates:
                            continue

                        start_m, start_d, start_y = m_dates[0]
                        try:
                            start_dt = datetime.strptime(f"{start_m} {start_d} {start_y}", "%b %d %Y").date()
                            end_dt = start_dt
                            if len(m_dates) > 1:
                                end_m, end_d, end_y = m_dates[1]
                                end_dt = datetime.strptime(f"{end_m} {end_d} {end_y}", "%b %d %Y").date()

                            if start_dt < today:
                                continue

                            if not (win_start <= start_dt <= win_end):
                                continue

                            t_norm = title.lower().strip()
                            if t_norm in seen_titles:
                                continue
                            seen_titles.add(t_norm)
                            seen_urls.add(link.lower().rstrip('/'))

                            # Enrich description & metadata from official landing page if accessible
                            overview_extra = ""
                            try:
                                ev_soup = self.fetch_soup(link, timeout=8)
                                if ev_soup:
                                    meta_desc = ev_soup.find('meta', attrs={'name': 'description'}) or ev_soup.find('meta', attrs={'property': 'og:description'})
                                    if meta_desc and meta_desc.get('content'):
                                        overview_extra = clean_html_text(meta_desc['content'])
                                    else:
                                        body_p = " ".join(p.get_text(' ', strip=True) for p in ev_soup.find_all(['h1', 'h2', 'p'])[:6])
                                        overview_extra = clean_html_text(body_p)[:800]
                            except Exception:
                                pass

                            overview_text = (
                                overview_extra
                                or f"National trade show and industry conference featured on the official TSNN Trade Show Calendar in {loc}."
                            )
                            raw_text = "\n".join([
                                f"Conference Title: {title}",
                                f"Overview & Description: {overview_text}",
                                f"Venue: {loc}",
                                f"Address: {loc}",
                                f"Official Event URL: {link}",
                                f"Registration URL: {link}",
                                f"Start Date: {start_dt.isoformat()}",
                                f"End Date: {end_dt.isoformat()}",
                                "Source: TSNN Trade Show Calendar",
                                "Country: USA"
                            ])
                            events.append(RawEventData(
                                source_name=self.source_name,
                                source_url=link,
                                raw_title=title,
                                raw_text=raw_text,
                                raw_location=loc,
                                raw_date=start_dt.isoformat()
                            ))
                            logger.info(f"[{self.source_name}] Ingested live TSNN conference: {title} ({start_dt})")
                        except Exception as parse_err:
                            logger.debug(f"[{self.source_name}] Error parsing TSNN date {dates_text}: {parse_err}")
            else:
                status_code = resp.status_code if resp else "timeout"
                logger.warning(f"[{self.source_name}] Live TSNN calendar returned status {status_code}")
        except Exception as e:
            logger.warning(f"[{self.source_name}] TSNN live crawl error: {e}")

        # 2. Sanctioned Tavily supplement for TSNN listings missed by single feed page
        month_name = win_start.strftime("%B")
        t_query = f'(site:tsnn.com OR site:thetradeshowcalendar.com) "{month_name} {win_start.year}" (conference OR summit OR expo) ("United States" OR "USA")'
        for r in self.tavily_search(t_query, max_results=6):
            r_url = (r.get("url") or "").strip()
            r_title = clean_html_text(r.get("title") or "").split("|")[0].strip()
            r_content = clean_html_text(r.get("content") or "")
            if not r_url or not r_title or r_url.lower().rstrip('/') in seen_urls:
                continue
            s_iso, e_iso = extract_date_range_from_text(f"{r_title} {r_content}", default_year=win_start.year)
            if s_iso and not self.is_date_in_window(s_iso, win_start, win_end):
                continue
            if not s_iso:
                continue
            seen_urls.add(r_url.lower().rstrip('/'))
            seen_titles.add(r_title.lower())
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
                    f"Source: TSNN / Tavily\nCountry: USA"
                ),
                raw_location="USA",
                raw_date=s_iso
            ))

        logger.info(f"[{self.source_name}] Collection finished. Harvested {len(events)} events.")
        return events
