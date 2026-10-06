"""
Ticketmaster Event Scraper for Conference Discovery

BUSINESS LOGIC - T-2 Rule:
Conferences are published to Excel exactly 2 days before their start date (T-2).

Example:
- If today is 2026-10-01
- T-2 date is 2026-10-03
- Only conferences starting on 2026-10-03 are discovered and published
- Conferences starting on other dates are ignored

Reason: Organizations receive 2-day notice before their event goes live and becomes
discoverable. This ensures timely notification and publication.

Module provides:
- TicketmasterScraper class for API integration
- Date filtering based on T-2 logic
- Speaker/attraction extraction from events
"""
import logging
import requests
import time
from datetime import datetime, date, timedelta
from typing import List, Optional
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

API_BASE = "https://app.ticketmaster.com/discovery/v2"

# DMA codes for major US markets
US_DMA_CODES = [
    "382",  # San Francisco-Oakland-San Jose
    "345",  # New York
    "803",  # Los Angeles
    "602",  # Chicago
    "623",  # Dallas-Ft. Worth
    "511",  # Washington DC
    "524",  # Atlanta
    "528",  # Miami-Ft. Lauderdale
    "881",  # Boston
    "753",  # Phoenix
]


class TicketmasterScraper(BaseScraper):
    """Ticketmaster Discovery API scraper for conferences and events.

    Extracts:
    - Event details (title, dates, venue, location, organizer)
    - Attractions as speakers (name, bio, company, images)
    - Speaker social media profiles
    """

    def __init__(self, api_key: Optional[str] = None):
        super().__init__("ticketmaster", API_BASE)

        # Get API key from environment or parameter
        import os
        self.api_key = api_key or os.getenv("TICKETMASTER_API_KEY")

        if not self.api_key:
            logger.warning("[ticketmaster] No API key provided. Skipping Ticketmaster source.")
            self.api_key = None
            return

        self.country_code = "US"
        self.dma_ids = US_DMA_CODES
        self.classification_names = ["Conference", "Convention", "Seminar", "Workshop"]
        self.size = 100  # Events per page (max 200)
        self.max_pages = 5  # Pages per classification
        self.timeout = 20

        # Rate limiting: 5 req/sec
        self._last_request_time = 0
        self._min_request_interval = 0.2  # 200ms between requests

        # Calculate date range (T-2 window: today through today+2 days)
        now = datetime.now()
        self._start_date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        self._end_date = (now + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def scrape(self) -> List[RawEventData]:
        if not self.api_key:
            logger.warning("[ticketmaster] Ticketmaster API key not configured. Skipping.")
            return []

        logger.info("[ticketmaster] Scraping events from Ticketmaster Discovery API for exact T-2...")
        events: List[RawEventData] = []

        try:
            for classification in self.classification_names:
                fetched = list(self._fetch_classification(classification))
                events.extend(fetched)
                logger.info(f"[ticketmaster] Found {len(fetched)} {classification} events")
        except Exception as e:
            logger.error(f"[ticketmaster] Error during scraping: {e}")

        logger.info(f"[ticketmaster] Successfully collected {len(events)} events from Ticketmaster.")
        return events

    def _rate_limit(self):
        """Enforce 5 requests/second limit."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        self._last_request_time = time.time()

    def _fetch_classification(self, classification: str) -> List[RawEventData]:
        """Fetch events for a specific classification."""
        events = []

        for page_num in range(self.max_pages):
            try:
                self._rate_limit()

                params = {
                    "apikey": self.api_key,
                    "countryCode": self.country_code,
                    "classificationName": classification,
                    "size": self.size,
                    "page": page_num,
                    "sort": "date,asc",
                    "dmaId": ",".join(self.dma_ids),
                    "startDateTime": self._start_date,
                    "endDateTime": self._end_date,
                }

                resp = self.session.get(
                    f"{API_BASE}/events.json",
                    params=params,
                    timeout=self.timeout,
                )

                if resp.status_code == 401:
                    logger.error("[ticketmaster] Invalid API key")
                    raise ValueError("Invalid Ticketmaster API key")

                resp.raise_for_status()
                data = resp.json()

                # Check if there are events
                embedded = data.get("_embedded", {})
                raw_events = embedded.get("events", [])

                if not raw_events:
                    break  # No more events, stop pagination

                for event_data in raw_events:
                    raw_event = self._parse_event(event_data)
                    if raw_event:
                        events.append(raw_event)

                # Check if this is the last page
                page_info = data.get("page", {})
                total_pages = page_info.get("totalPages", 0)
                if page_num + 1 >= total_pages:
                    break

            except requests.RequestException as e:
                logger.warning(f"[ticketmaster] API error on page {page_num}: {e}")
                break

        return events

    def _parse_event(self, data: dict) -> Optional[RawEventData]:
        """Parse a Ticketmaster event into RawEventData."""
        try:
            title = data.get("name", "").strip()
            if not title:
                return None

            # Get start date
            dates = data.get("dates", {})
            start_data = dates.get("start", {})
            start_date_str = start_data.get("localDate")  # YYYY-MM-DD

            # Parse date for T-2 filtering
            if not start_date_str:
                return None

            try:
                conf_start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                today = date.today()
                t2_end = today + timedelta(days=2)

                # T-2 filtering: include conferences starting from today through T+2
                if not (today <= conf_start <= t2_end):
                    return None
            except ValueError as e:
                logger.debug(f"[ticketmaster] Invalid date format '{start_date_str}': {e}")
                return None

            # Get venue and location
            embedded = data.get("_embedded", {})
            venues = embedded.get("venues", [])
            city = state = country = venue = ""

            if venues:
                v = venues[0]
                venue = v.get("name", "")
                city_data = v.get("city", {})
                city = city_data.get("name", "")
                state_data = v.get("state", {})
                state = state_data.get("stateCode", "")
                country_data = v.get("country", {})
                country = country_data.get("countryCode", "")

            location = f"{venue}, {city}, {state}, {country}" if venue else f"{city}, {state}, {country}"

            # Get organizer/promoter
            promoter = ""
            promoters = data.get("promoter") or data.get("promoters")
            if promoters:
                if isinstance(promoters, dict):
                    promoter = promoters.get("name", "")
                elif isinstance(promoters, list) and promoters:
                    promoter = promoters[0].get("name", "")

            # Extract attractions as speakers
            speaker_info = ""
            attractions = embedded.get("attractions", [])
            if attractions:
                speaker_names = []
                for attr in attractions:
                    name = attr.get("name", "").strip()
                    description = attr.get("description", "").strip()
                    if name:
                        if description:
                            speaker_names.append(f"{name} ({description[:50]})")
                        else:
                            speaker_names.append(name)

                if speaker_names:
                    speaker_info = "Speakers: " + "; ".join(speaker_names[:10])

            # Get event category
            category = ""
            classifications = data.get("classifications", [])
            if classifications:
                segment = classifications[0].get("segment", {})
                category = segment.get("name", "")

            # Build raw text
            url = data.get("url", "")
            raw_text = (
                f"Conference: {title}\n"
                f"Venue: {venue}\n"
                f"Location: {city}, {state}, {country}\n"
                f"Date: {start_date_str}\n"
                f"Category: {category}\n"
                f"Organizer: {promoter}\n"
                f"{speaker_info}\n"
                f"Ticketmaster URL: {url}"
            )

            return RawEventData(
                source_name=self.source_name,
                source_url=url,
                raw_title=title,
                raw_text=raw_text,
                raw_location=location,
                raw_date=start_date_str,
            )

        except Exception as e:
            logger.debug(f"[ticketmaster] Error parsing event: {e}")
            return None
