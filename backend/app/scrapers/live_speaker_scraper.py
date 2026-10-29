import asyncio
import json
import logging
import re
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Optional Playwright integration
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


class LiveWebScraper:
    """
    Genuine Live Scraper using Playwright headless browser when available,
    falling back gracefully when Playwright is not installed.
    """

    @staticmethod
    async def scrape_speakers_from_url_async(url: str) -> List[Dict[str, str]]:
        if not PLAYWRIGHT_AVAILABLE:
            logger.info("Playwright is not installed, using HTTP-based speaker extraction.")
            return fetch_official_site_speakers(url)

        speakers = []
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                    viewport={"width": 1280, "height": 800}
                )
                page = await context.new_page()
                logger.info(f"Live-navigating to {url} with Playwright...")
                await page.goto(url, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(2000)

                body_text = await page.inner_text("body")
                lines = [line.strip() for line in body_text.split("\n") if line.strip()]

                i = 0
                while i < len(lines):
                    line = lines[i]
                    if line in ("View Speaker", "View Profile", "View Bio"):
                        name = lines[i - 3] if i >= 3 else ""
                        title = lines[i - 2] if i >= 2 else ""
                        company = lines[i - 1] if i >= 1 else ""

                        if name and is_valid_speaker_name(name):
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
            logger.error(f"Error live scraping speakers with Playwright from {url}: {e}")

        return speakers

    @classmethod
    def scrape_speakers_from_url(cls, url: str) -> List[Dict[str, str]]:
        """Synchronous wrapper for Celery/FastAPI."""
        try:
            if PLAYWRIGHT_AVAILABLE:
                return asyncio.run(cls.scrape_speakers_from_url_async(url))
            return fetch_official_site_speakers(url)
        except Exception as e:
            logger.error(f"Asyncio run error: {e}")
            return fetch_official_site_speakers(url)


COMPANY_DOMAINS = {
    'meta': 'https://about.meta.com',
    'cobot': 'https://cobot.com',
    'axiom math': 'https://axiommath.org',
    'sierra / openai': 'https://sierra.ai',
    'sierra': 'https://sierra.ai',
    'openai': 'https://openai.com',
    'mit': 'https://www.mit.edu',
    'harvard': 'https://www.harvard.edu',
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
    'apple': 'https://www.apple.com',
    'snowflake': 'https://www.snowflake.com',
    'oura': 'https://ouraring.com',
    'databricks': 'https://www.databricks.com',
    'ibm': 'https://www.ibm.com'
}


def is_valid_speaker_name(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 40:
        return False
    name = name.strip().strip(",- \t\n")
    if not name or len(name) < 3:
        return False
    if re.search(r"\d", name):
        return False
    for c in [":", "?", "!", "$", "%", "/", "@", "<", ">", "|", "&", "+", "*", "~", "^"]:
        if c in name:
            return False
    lower = name.lower()
    invalid_keywords = [
        "visit", "for more", "information", "mitas", "ticket", "policy", "network",
        "community", "reserved", "terms", "condition", "refund", "fee", "admission",
        "organizer", "sponsor", "keynote", "speaker", "conference", "alumni",
        "options?", "http", "www.", ".com", ".org", "register", "faq", "agenda",
        "overview", "description", "presentation", "session", "panel", "event details",
        "to reserve your seat", "free h", "click here", "sign up", "sign in",
        "about the event", "featured speakers", "hosts", "meet the speakers",
        "breakout", "tracks", "series", "events", "united states", "massachusetts",
        "things to do", "use eventbrite", "plan events", "event blog", "how it works",
        "founder", "co-founder", "ceo", "cto", "cfo", "cio", "ciso", "president",
        "managing partner", "partner", "director", "manager", "vice president", "vp",
        "principal", "fellow", "professor", "associate", "analyst", "lead",
        "research", "healthcare", "avenue", "street", "road", "suite", "floor", "hall", "center",
        "moderator", "panelist", "masterclass", "symposium", "expo", "summit",
        "engineering", "observability", "reliability", "infrastructure", "operational",
        "excellence", "maintenance", "automation", "integrations", "tooling", "architecture",
        "party", "bird", "early", "attendee", "pass", "passes", "prospectus", "request",
        "awards", "streaming", "settings", "cookie", "cookies", "privacy", "apache",
        "kafka", "flink", "iceberg", "technology", "technologies", "software", "hardware",
        "platform", "platforms", "solution", "solutions", "system", "systems", "cloud",
        "devops", "kubernetes", "linux", "python", "golang", "ruby", "rust", "react",
        "cybersecurity", "security", "threat", "vulnerability", "management", "strategy",
        "roadmap", "showcase", "exhibit", "sponsorship", "stage", "booth", "track",
        "reception", "breakfast", "lunch", "dinner", "cocktail", "vip", "tickets",
        "data", "current", "mainten", "the ", " the", "san francisco", "francisco", "new york", "london", "austin", "chicago", "boston"
    ]
    if any(kw in lower for kw in invalid_keywords):
        return False
    words = [re.sub(r"[^A-Za-z]", "", w) for w in name.split()]
    words = [w for w in words if len(w) > 1]
    if len(words) < 2 or len(words) > 4:
        return False
    if not all(part[0].isupper() and part[1:].islower() for part in words if part):
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

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }

    base = official_url.rstrip("/")
    urls_to_try = [official_url]
    for path in ["/speakers", "/agenda", "/schedule"]:
        if not base.endswith(path):
            urls_to_try.append(base + path)

    discovered = []
    seen_names = set()

    for target_url in urls_to_try:
        try:
            r = requests.get(target_url, headers=headers, timeout=10)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')

            # 1. Parse Schema.org ItemList with Person items or Event performers
            for s in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(s.string)
                    items = []
                    if isinstance(data, dict):
                        if data.get('@type') == 'ItemList':
                            items = [el.get('item', {}) for el in data.get('itemListElement', [])]
                        elif data.get('@type') in ['Event', 'BusinessEvent']:
                            items = data.get('performer', [])
                            if isinstance(items, dict):
                                items = [items]
                    elif isinstance(data, list):
                        items = data

                    for it in items:
                        if isinstance(it, dict) and ('name' in it or it.get('@type') == 'Person'):
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

                            li_url = same_as if ('linkedin.com/in/' in same_as) else ''
                            comp_website = resolve_company_website(company)

                            discovered.append({
                                'conference_name': conf_title,
                                'speaker_name': name,
                                'company_name': company or 'Industry Organization',
                                'company_organization': company or 'Industry Organization',
                                'job_role_designation': role or 'Keynote Speaker',
                                'linkedin_url': li_url,
                                'official_company_website_url': comp_website,
                                'source_url': spk_url
                            })
                except Exception:
                    pass

            # 2. Parse HTML text for "Featured Speakers" blocks
            text_all = soup.get_text('\n', strip=True)
            for marker in ["Featured Speakers", "Keynote Speakers", "Our Speakers"]:
                if marker in text_all:
                    idx = text_all.find(marker)
                    block = text_all[idx + len(marker):idx + len(marker) + 2000]
                    lines = [l.strip() for l in block.split("\n") if l.strip()]
                    j = 0
                    while j < len(lines):
                        line = lines[j].strip().strip(",- \t\n")
                        if is_valid_speaker_name(line):
                            n_key = line.lower()
                            if n_key not in seen_names:
                                seen_names.add(n_key)
                                # Next line might be title/role
                                role_line = lines[j + 1].strip() if j + 1 < len(lines) else ""
                                job_role = "Speaker"
                                comp_name = "Industry Organization"
                                adv = False
                                if role_line and not is_valid_speaker_name(role_line) and len(role_line) < 100:
                                    role_clean = role_line.lstrip(",- \t\n").strip()
                                    if " at " in role_clean:
                                        p = role_clean.split(" at ", 1)
                                        job_role = p[0].strip()
                                        comp_name = p[1].strip()
                                    elif "," in role_clean:
                                        p = role_clean.split(",", 1)
                                        job_role = p[0].strip()
                                        comp_name = p[1].strip()
                                    else:
                                        job_role = role_clean
                                    adv = True

                                discovered.append({
                                    'conference_name': conf_title,
                                    'speaker_name': line,
                                    'company_name': comp_name,
                                    'company_organization': comp_name,
                                    'job_role_designation': job_role,
                                    'linkedin_url': '',
                                    'official_company_website_url': resolve_company_website(comp_name),
                                    'source_url': target_url
                                })
                                if adv:
                                    j += 2
                                    continue
                        j += 1

            if len(discovered) >= 3:
                break
        except Exception as e:
            logger.debug(f"Error fetching official site speakers from {target_url}: {e}")

    return discovered
