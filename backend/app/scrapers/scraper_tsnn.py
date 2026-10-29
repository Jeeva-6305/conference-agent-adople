import logging
import re
from datetime import date, datetime, timedelta
from typing import List
from bs4 import BeautifulSoup
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class TSNNScraper(BaseScraper):
    def __init__(self):
        super().__init__("tsnn", "https://thetradeshowcalendar.com/tsnn/index.php")

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Harvesting major national trade shows & technical conventions from TSNN...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        # Live crawl TSNN official tradeshow calendar feed
        try:
            resp = self.fetch_page("https://thetradeshowcalendar.com/tsnn/index.php?vCtry=United+States&vRpP=50", timeout=12)
            if resp and resp.status_code == 200:
                soup = BeautifulSoup(resp.text, 'html.parser')
                seen_titles = set()
                for tr in soup.find_all('tr'):
                    tds = tr.find_all('td')
                    if len(tds) >= 4:
                        a = tds[1].find('a')
                        if not a or not a.get('href'):
                            continue
                        title = a.get_text(strip=True)
                        link = a['href'].strip()
                        if link.startswith('//'):
                            link = 'https:' + link
                        elif not link.startswith('http'):
                            continue

                        dates_text = tds[2].get_text(separator=' ', strip=True)
                        loc = tds[3].get_text(separator=' ', strip=True)
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

                            # Dynamic date filtering: prioritize exact T-2, also ingest near-term scheduled events
                            if start_dt == exact_t2 or (start_dt >= exact_t2 and start_dt <= exact_t2 + timedelta(days=14)):
                                t_norm = title.lower().strip()
                                if t_norm in seen_titles:
                                    continue
                                seen_titles.add(t_norm)

                                raw_text = "\n".join([
                                    f"Conference Title: {title}",
                                    f"Overview & Description: Major national trade exhibition and conference featured on the official TSNN Trade Show Calendar in {loc}.",
                                    f"Venue: {loc}",
                                    f"Address: {loc}",
                                    f"Official Event URL: {link}",
                                    f"Registration URL: {link}",
                                    f"Start Date: {start_dt.isoformat()}",
                                    f"End Date: {end_dt.isoformat()}",
                                    f"Category: Technology / Enterprise / Trade Show"
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

        logger.info(f"[{self.source_name}] Collection finished. Harvested {len(events)} events.")
        return events
