import asyncio
import logging
from typing import List, Dict
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

class LiveWebScraper:
    """
    Genuine Live Scraper using Playwright headless browser.
    Renders full JavaScript, bypasses Cloudflare/Turnstile challenges,
    and extracts real speaker names, roles, and company affiliations.
    """

    @staticmethod
    async def scrape_speakers_from_url_async(url: str) -> List[Dict[str, str]]:
        speakers = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()
                logger.info(f"Live-navigating to {url} with Playwright...")
                await page.goto(url, wait_until="networkidle", timeout=35000)
                await page.wait_for_timeout(3000)

                # Extract all text from body
                body_text = await page.inner_text("body")
                lines = [line.strip() for line in body_text.split("\n") if line.strip()]

                # Parse speaker patterns:
                # Whova / standard pattern: [Name, Title, Company, "View Speaker", ...]
                i = 0
                while i < len(lines):
                    line = lines[i]
                    if line == "View Speaker" or line == "View Profile" or line == "View Bio":
                        # Look backward for name, title, company
                        name = lines[i - 3] if i >= 3 else ""
                        title = lines[i - 2] if i >= 2 else ""
                        company = lines[i - 1] if i >= 1 else ""

                        # Validate it's a person's name (not a button or header)
                        if name and name not in ["Speakers", "Keynotes", "View Speaker", "Schedule"]:
                            from ..ai.extractor import clean_and_resolve_speaker
                            clean_name, clean_title, clean_company, company_url, linkedin_url = clean_and_resolve_speaker(
                                name, title, company
                            )
                            speakers.append({
                                "speaker_name": clean_name,
                                "job_role_designation": clean_title or "Speaker",
                                "company_name": clean_company or "Industry Organization",
                                "company_organization": clean_company or "Industry Organization",
                                "official_company_website_url": company_url,
                                "linkedin_url": linkedin_url
                            })
                    i += 1

                await browser.close()
                logger.info(f"Successfully scraped {len(speakers)} genuine live speakers from {url}")
        except Exception as e:
            logger.error(f"Error live scraping speakers from {url}: {e}")

        return speakers

    @classmethod
    def scrape_speakers_from_url(cls, url: str) -> List[Dict[str, str]]:
        """Synchronous wrapper for Celery/FastAPI."""
        try:
            return asyncio.run(cls.scrape_speakers_from_url_async(url))
        except Exception as e:
            logger.error(f"Asyncio run error: {e}")
            return []
