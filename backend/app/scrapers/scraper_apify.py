import os
import logging
import requests
import time
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from ..schemas import RawEventData

logger = logging.getLogger(__name__)


class ApifyScraperBase:
    """Base class for Apify actor integration."""

    def __init__(self, actor_id: str, source_name: str):
        self.api_key = os.getenv("APIFY_API_KEY")
        self.actor_id = actor_id
        self.source_name = source_name
        self.api_url = "https://api.apify.com/v2"

        if not self.api_key:
            logger.warning(f"[{source_name}] Apify API key not configured")

    def run_actor(self, input_data: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
        """Run an Apify actor and get results."""
        if not self.api_key:
            logger.warning(f"[{self.source_name}] Skipping - API key not configured")
            return None

        try:
            url = f"{self.api_url}/acts/{self.actor_id}/runs"
            headers = {"Authorization": f"Bearer {self.api_key}"}

            logger.info(f"[{self.source_name}] Starting Apify actor {self.actor_id}...")

            response = requests.post(
                url,
                headers=headers,
                json={"content": input_data},
                timeout=60
            )

            if response.status_code != 201:
                logger.error(f"[{self.source_name}] Actor run failed: {response.status_code} - {response.text}")
                return None

            run_data = response.json()
            run_id = run_data.get("data", {}).get("id")

            if not run_id:
                logger.error(f"[{self.source_name}] No run ID in response")
                return None

            logger.info(f"[{self.source_name}] Actor run {run_id} started, polling for results...")

            return self._wait_for_results(run_id)

        except Exception as e:
            logger.error(f"[{self.source_name}] Error running actor: {e}")
            return None

    def _wait_for_results(self, run_id: str, max_wait: int = 300) -> Optional[List[Dict[str, Any]]]:
        """Wait for actor to complete and get results."""
        url = f"{self.api_url}/acts/{self.actor_id}/runs/{run_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        start_time = time.time()

        while time.time() - start_time < max_wait:
            try:
                response = requests.get(url, headers=headers, timeout=10)
                data = response.json()
                status = data.get("data", {}).get("status")

                if status == "SUCCEEDED":
                    logger.info(f"[{self.source_name}] Actor completed successfully")
                    dataset_id = data.get("data", {}).get("defaultDatasetId")
                    return self._get_dataset_results(dataset_id)
                elif status == "FAILED":
                    logger.error(f"[{self.source_name}] Actor failed")
                    return None

                time.sleep(2)

            except Exception as e:
                logger.error(f"[{self.source_name}] Error polling actor: {e}")
                return None

        logger.warning(f"[{self.source_name}] Actor timeout after {max_wait}s")
        return None

    def _get_dataset_results(self, dataset_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get results from Apify dataset."""
        try:
            url = f"{self.api_url}/datasets/{dataset_id}/items"
            headers = {"Authorization": f"Bearer {self.api_key}"}

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                results = response.json()
                if isinstance(results, list):
                    logger.info(f"[{self.source_name}] Retrieved {len(results)} items from dataset")
                    return results
                else:
                    logger.warning(f"[{self.source_name}] Unexpected response format: {type(results)}")
                    return None
            else:
                logger.error(f"[{self.source_name}] Failed to get dataset: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"[{self.source_name}] Error getting dataset: {e}")
            return None


class SmartEventApifyScraper(ApifyScraperBase):
    """Scrape multiple event platforms using Apify Smart Event Scraper."""

    SMART_EVENT_ACTOR_ID = "TlT1NfTkQs2qfjzz4"

    def __init__(self):
        super().__init__(self.SMART_EVENT_ACTOR_ID, "apify_smart_events")

    def scrape(self) -> List[RawEventData]:
        """Scrape EventBrite, Meetup, AllEvents, EventsEye, ConferenceAlerts conferences in T-2 window."""
        if not self.api_key:
            return []

        today = date.today()
        t_plus_2 = today + timedelta(days=2)

        input_data = {
            "keywords": "conference",
            "locations": "United States",
            "eventType": "all",
            "minDate": today.strftime("%Y-%m-%d"),
            "maxDate": t_plus_2.strftime("%Y-%m-%d"),
            "platforms": ["eventbrite", "allevents", "eventseye"],
            "minResults": 10,
            "maxResults": 100,
        }

        logger.info(f"[{self.source_name}] Filtering Smart Events for T-2 window ({today} to {t_plus_2})...")

        results = self.run_actor(input_data)

        if not results:
            return []

        events = []
        for item in results:
            try:
                raw_event = self._parse_smart_event_item(item)
                if raw_event:
                    events.append(raw_event)
            except Exception as e:
                logger.debug(f"[{self.source_name}] Error parsing item: {e}")

        logger.info(f"[{self.source_name}] Scraped {len(events)} conferences")
        return events

    def _parse_smart_event_item(self, item: Dict[str, Any]) -> Optional[RawEventData]:
        """Parse Smart Event Scraper item into RawEventData."""
        try:
            title = item.get("title") or item.get("name") or item.get("eventName", "")
            title = title.strip()
            if not title:
                return None

            url = item.get("url") or item.get("link") or item.get("eventUrl", "") or ""
            location = item.get("location") or item.get("city") or item.get("venue", "") or ""
            date_str = item.get("date") or item.get("startDate") or item.get("start_date", "") or ""
            description = item.get("description") or ""

            return RawEventData(
                source_name=self.source_name,
                source_url=url,
                raw_title=title,
                raw_text=f"{title}. Location: {location}. {description}",
                raw_location=location,
                raw_date=date_str,
            )
        except Exception as e:
            logger.debug(f"[{self.source_name}] Parse error: {e}")
            return None


class LumaApifyScraper(ApifyScraperBase):
    """Scrape Luma using Apify actor."""

    LUMA_ACTOR_ID = "u2AYuJNICFRQIJT4s"

    def __init__(self):
        super().__init__(self.LUMA_ACTOR_ID, "apify_luma")

    def scrape(self) -> List[RawEventData]:
        """Scrape Luma tech conferences in T+2 window to reduce API costs."""
        if not self.api_key:
            return []

        today = date.today()
        t_plus_2 = today + timedelta(days=2)

        input_data = {
            "searchQuery": "conference",
            "maxResults": 50,
            "useProxy": True,
            "startDate": str(today),
            "endDate": str(t_plus_2),
        }

        logger.info(f"[{self.source_name}] Filtering Luma conferences for T+2 window ({today} to {t_plus_2}) to reduce API cost...")
        results = self.run_actor(input_data)

        if not results:
            logger.info(f"[{self.source_name}] No conferences found in T+2 window")
            return []

        events = []
        for item in results:
            try:
                raw_event = self._parse_luma_item(item)
                if raw_event:
                    events.append(raw_event)
            except Exception as e:
                logger.debug(f"[{self.source_name}] Error parsing item: {e}")

        logger.info(f"[{self.source_name}] Scraped {len(events)} conferences in T+2 window (reduced from 30-day window)")
        return events

    def _parse_luma_item(self, item: Dict[str, Any]) -> Optional[RawEventData]:
        """Parse Luma item into RawEventData."""
        try:
            title = item.get("title") or item.get("name", "")
            title = title.strip()
            if not title:
                return None

            url = item.get("url") or item.get("link", "") or ""
            location = item.get("location") or item.get("city", "") or ""
            date_str = item.get("eventDate") or item.get("date", "") or item.get("startDate", "") or ""
            description = item.get("description") or ""

            return RawEventData(
                source_name=self.source_name,
                source_url=url,
                raw_title=title,
                raw_text=f"{title}. Location: {location}. {description}",
                raw_location=location,
                raw_date=date_str,
            )
        except Exception as e:
            logger.debug(f"[{self.source_name}] Parse error: {e}")
            return None
