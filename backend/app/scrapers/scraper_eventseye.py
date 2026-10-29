import logging
import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

EVENTSEYE_USA_URL = "https://www.eventseye.com/fairs/c1_trade-shows_usa-united-states-of-america.html"

class EventsEyeScraper(BaseScraper):
    def __init__(self):
        super().__init__("eventseye", EVENTSEYE_USA_URL)

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Live scraping genuine USA trade shows & conferences from EventsEye...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        try:
            soup = self.fetch_soup(self.base_url, timeout=10)
            if not soup:
                logger.warning(f"[{self.source_name}] Failed to fetch EventsEye main directory")
                return events

            table_rows = soup.find_all('tr')
            candidate_rows = []

            for tr in table_rows:
                tds = tr.find_all('td')
                if len(tds) < 4:
                    continue
                link_el = tds[0].find('a', href=True)
                if not link_el:
                    continue
                title = link_el.get_text(strip=True)
                venue_city = tds[2].get_text(' ', strip=True)
                date_text = tds[3].get_text(' ', strip=True)

                # EventsEye uses MM/DD/YYYY or DD/MM/YYYY
                m_date = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', date_text)
                if not m_date:
                    continue

                d1, d2, yr = int(m_date.group(1)), int(m_date.group(2)), int(m_date.group(3))
                # Distinguish month vs day
                try:
                    if d1 <= 12 and d2 <= 31:
                        event_date = date(yr, d1, d2)
                    elif d2 <= 12 and d1 <= 31:
                        event_date = date(yr, d2, d1)
                    else:
                        continue
                except ValueError:
                    continue

                # Filter only future/upcoming events
                if event_date >= today:
                    rel_url = link_el['href']
                    full_url = f"https://www.eventseye.com/fairs/{rel_url}" if not rel_url.startswith('http') else rel_url
                    candidate_rows.append({
                        "title": title,
                        "venue_city": venue_city,
                        "date_str": event_date.isoformat(),
                        "url": full_url,
                        "is_t2": (event_date == exact_t2)
                    })

            # Prioritize exact T-2 candidates, then upcoming candidates
            candidate_rows.sort(key=lambda x: (not x["is_t2"], x["date_str"]))

            for item in candidate_rows[:15]:
                official_site = item["url"]
                desc = f"{item['title']} held in {item['venue_city']}, USA."
                organizer = "Industry Trade Organizer"

                try:
                    detail_soup = self.fetch_soup(item["url"], timeout=8)
                    if detail_soup:
                        # Find Official Web Site
                        for a_tag in detail_soup.find_all('a', href=True):
                            txt = a_tag.get_text(strip=True)
                            href = a_tag['href'].strip()
                            if "Official Web Site" in txt and href.startswith('http'):
                                official_site = href
                                break
                            elif "Web Site" in txt and href.startswith('http') and not any(ign in href for ign in ['eventseye', 'facebook', 'twitter', 'linkedin']):
                                official_site = href

                        body_txt = detail_soup.get_text('\n', strip=True)
                        if "Description" in body_txt:
                            d_idx = body_txt.find("Description")
                            desc = body_txt[d_idx:d_idx+600].replace("\n", " ")
                except Exception as d_err:
                    logger.debug(f"[{self.source_name}] Error parsing detail for {item['url']}: {d_err}")

                raw_text = (
                    f"Conference Title: {item['title']}\n"
                    f"Overview & Description: {desc}\n"
                    f"Venue: {item['venue_city']}\n"
                    f"Address: {item['venue_city']}, USA\n"
                    f"Organizer: {organizer}\n"
                    f"Official Event URL: {official_site}\n"
                    f"Registration URL: {item['url']}\n"
                    f"Start Date: {item['date_str']}\n"
                    f"End Date: {item['date_str']}\n"
                    f"Source: EventsEye\n"
                    f"Country: USA"
                )

                events.append(RawEventData(
                    source_name=self.source_name,
                    source_url=official_site,
                    raw_title=item["title"],
                    raw_text=raw_text,
                    raw_location=f"{item['venue_city']}, USA",
                    raw_date=item["date_str"]
                ))
                logger.info(f"[{self.source_name}] Harvested conference: {item['title']} ({item['date_str']}) in {item['venue_city']}")

        except Exception as e:
            logger.error(f"[{self.source_name}] Error crawling: {e}")

        logger.info(f"[{self.source_name}] Finished collection. Harvested {len(events)} events.")
        return events
