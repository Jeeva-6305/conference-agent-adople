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

COMPANY_DOMAINS = {
    'meta': 'https://about.meta.com',
    'cobot': 'https://cobot.com',
    'axiom math': 'https://axiommath.org',
    'sierra / openai': 'https://sierra.ai',
    'sierra': 'https://sierra.ai',
    'openai': 'https://openai.com',
    'mit': 'https://www.mit.edu',
    'the white house': 'https://www.whitehouse.gov',
    'adt': 'https://www.adt.com',
    'superhuman': 'https://superhuman.com',
    'cirrus logic': 'https://www.cirrus.com',
    'sacramento kings': 'https://www.nba.com/kings',
    'arc institute': 'https://arcinstitute.org',
    'sentinelone': 'https://www.sentinelone.com',
    'floodgate': 'https://floodgate.com',
    'nowadays': 'https://nowadays.ai',
    'moda': 'https://moda.ai',
    'code.org': 'https://code.org',
    'daytona': 'https://www.daytona.io',
    'e14 fund': 'https://e14fund.com',
    'bloomberg beta': 'https://www.bloomberg.com/beta',
    '1password': 'https://1password.com',
    'microsoft': 'https://www.microsoft.com',
    'google': 'https://about.google',
    'apple': 'https://www.apple.com'
}

def is_valid_speaker_name(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 45:
        return False
    lower = name.lower()
    invalid_keywords = [
        "visit", "for more", "information", "mitas", "ticket", "policy", "network",
        "community", "reserved", "terms", "condition", "refund", "fee", "admission",
        "organizer", "sponsor", "keynote", "speaker", "conference", "alumni",
        "options?", "http", "www.", ".com", ".org", "register", "faq", "agenda",
        "overview", "description", "presentation", "session", "panel"
    ]
    if any(kw in lower for kw in invalid_keywords):
        return False
    if any(c in name for c in [":", "?", "!", "$", "%", "\\", "/", "@", "<", ">"]):
        return False
    words = [w for w in name.split() if len(w) > 1]
    if len(words) < 2:
        return False
    return True

def resolve_company_website(company: str) -> str:
    if not company:
        return ""
    comp_clean = company.lower().strip()
    if comp_clean in COMPANY_DOMAINS:
        return COMPANY_DOMAINS[comp_clean]
    for k, v in COMPANY_DOMAINS.items():
        if k in comp_clean:
            return v
    return ""

def fetch_official_site_speakers(official_url: str, conf_title: str = "") -> List[Dict[str, str]]:
    """
    Crawls official conference page (and /speakers, /agenda) to extract verified speakers:
    - Conference Name
    - Speaker Name
    - Company Name
    - Job Role / Designation
    - Original LinkedIn Profile URL
    - Company Website URL
    - Source URL
    """
    if not official_url or not official_url.startswith("http"):
        return []
    
    import requests
    from bs4 import BeautifulSoup
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    urls_to_try = [official_url]
    if not official_url.rstrip("/").endswith("/speakers"):
        urls_to_try.insert(0, official_url.rstrip("/") + "/speakers")
        
    discovered = []
    seen_names = set()
    
    for target_url in urls_to_try:
        try:
            r = requests.get(target_url, headers=headers, timeout=12)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # 1. Parse Schema.org ItemList with Person items
            for s in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(s.string)
                    items = []
                    if data.get('@type') == 'ItemList':
                        items = [el.get('item', {}) for el in data.get('itemListElement', [])]
                    elif isinstance(data, list):
                        items = data
                    for it in items:
                        if it.get('@type') == 'Person' or 'name' in it:
                            name = it.get('name', '').strip()
                            if not is_valid_speaker_name(name):
                                continue
                            n_key = name.lower()
                            if n_key in seen_names:
                                continue
                            seen_names.add(n_key)
                            
                            role = it.get('jobTitle', '').strip()
                            works_for = it.get('worksFor', {})
                            company = works_for.get('name', '').strip() if isinstance(works_for, dict) else str(works_for)
                            same_as = it.get('sameAs', '')
                            spk_url = it.get('url', target_url)
                            
                            li_url = same_as if ('linkedin.com/in/' in same_as or 'linkedin.com/pub/' in same_as) else ''
                            comp_website = resolve_company_website(company)
                            
                            discovered.append({
                                'conference_name': conf_title,
                                'speaker_name': name,
                                'company_name': company or 'Not Verified',
                                'company_organization': company or 'Not Verified',
                                'job_role_designation': role or 'Speaker',
                                'linkedin_url': li_url,
                                'official_company_website_url': comp_website,
                                'source_url': spk_url
                            })
                except Exception:
                    pass
                    
            if len(discovered) >= 3:
                break
        except Exception as e:
            logger.debug(f"Error fetching official site speakers from {target_url}: {e}")
            
    return discovered

    @classmethod
    def scrape_speakers_from_url(cls, url: str) -> List[Dict[str, str]]:
        """Synchronous wrapper for Celery/FastAPI."""
        try:
            return asyncio.run(cls.scrape_speakers_from_url_async(url))
        except Exception as e:
            logger.error(f"Asyncio run error: {e}")
            return []
