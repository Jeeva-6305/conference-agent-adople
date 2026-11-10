import asyncio
import html
import json
import logging
import re
import urllib.parse
from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup

from ..config import settings

logger = logging.getLogger(__name__)

# Optional Playwright integration
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

_AZURE_SPEAKER_EXHAUSTED = False


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
                            if clean_name:
                                speakers.append({
                                    "speaker_name": clean_name,
                                    "job_role_designation": clean_title or "",
                                    "company_name": clean_company or "",
                                    "company_organization": clean_company or "",
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


def _is_valid_name_token(part: str, allow_initial: bool = False) -> bool:
    """Validates a single person name component, supporting hyphens, apostrophes, CamelCase (McDonald), and initials."""
    if not part:
        return False
    # Allow single-letter middle initial like "C" or "C."
    stripped = part.rstrip(".")
    if len(stripped) == 1:
        return allow_initial and stripped.isupper()

    # Split hyphenated or apostrophe parts (e.g. O'Brien, Jean-Luc)
    sub_parts = re.split(r"[-'\u2019]", stripped)
    for sp in sub_parts:
        if not sp:
            continue
        if len(sp) == 1:
            # e.g. "O" in "O'Brien"
            if not sp.isupper():
                return False
            continue
        if not sp[0].isupper():
            return False
        if not any(c.islower() for c in sp):
            return False
        # Reject mixed noise where more than 2 uppercase letters appear in one short sub-part
        if sum(1 for c in sp if c.isupper()) > 2:
            return False
    return True


def is_valid_speaker_name(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 55:
        return False
    name = html.unescape(name).strip().strip(",- \t\n|•·")
    # Strip prefixes & suffixes for validation
    clean = re.sub(
        r"^(?:Dr\.?|Doctor|Prof\.?|Professor|Mr\.?|Ms\.?|Mrs\.?|Rev\.?|Hon\.?|Rep\.?|Sen\.?|Gen\.?)\s+",
        "",
        name,
        flags=re.I,
    ).strip()
    clean = re.sub(
        r"(?:,\s*|\s+)(?:M\.?D\.?|Ph\.?D\.?|J\.?D\.?|MBA|M\.B\.A\.|MPH|RN|FACS|FACC|CISO|CISSP|Esq\.?|Jr\.?|Sr\.?|III|II|IV)+\.?$",
        "",
        clean,
        flags=re.I,
    ).strip().strip(",")

    if not clean or len(clean) < 3 or len(clean) > 45:
        return False
    if re.search(r"\d", clean):
        return False
    for c in [":", "?", "!", "$", "%", "/", "@", "<", ">", "|", "&", "+", "*", "~", "^", "(", ")", "[", "]", "{", "}"]:
        if c in clean:
            return False

    lower = clean.lower()

    # Substring checks ONLY for unmistakable non-person / URL / UI markers
    substring_junk = [
        "http", "www.", ".com", ".org", ".io", ".ai", ".net", ".edu",
        "click here", "sign up", "sign in", "learn more", "read more",
        "see all", "view all", "buy ticket", "get ticket", "register now",
        "featured speaker", "keynote speaker", "meet the speaker", "our speaker",
        "about the event", "event detail", "to reserve your seat", "free h",
        "things to do", "use eventbrite", "plan event", "event blog", "how it works",
        "not publicly available", "coming soon", "to be announced",
        "meetup pro", "google play", "app store", "download on", "terms of", "privacy policy",
        "artificial intelligence", "deep learning", "machine learning", "natural language",
        "convention center", "medical center", "marriott", "hyatt", "hilton", "sheraton",
    ]
    if any(kw in lower for kw in substring_junk):
        return False

    # Whole-word checks for job titles, event vocabulary, and cities
    invalid_words = {
        "visit", "information", "ticket", "tickets", "policy", "network", "community",
        "reserved", "terms", "condition", "conditions", "refund", "fee", "admission",
        "organizer", "organizers", "sponsor", "sponsors", "sponsorship", "keynote",
        "speaker", "speakers", "conference", "summit", "symposium", "expo", "forum",
        "congress", "convention", "alumni", "register", "registration", "faq", "agenda",
        "overview", "description", "presentation", "session", "sessions", "panel",
        "panelist", "panelists", "moderator", "moderators", "hosts", "breakout",
        "tracks", "series", "events", "founder", "co-founder", "ceo", "cto", "cfo",
        "cio", "ciso", "coo", "president", "partner", "director", "manager",
        "principal", "professor", "associate", "analyst", "lead", "engineering",
        "observability", "reliability", "infrastructure", "operational", "excellence",
        "maintenance", "automation", "integrations", "tooling", "architecture",
        "attendee", "attendees", "pass", "passes", "prospectus", "request", "awards",
        "streaming", "settings", "cookie", "cookies", "privacy", "apache", "kafka",
        "flink", "iceberg", "technology", "technologies", "software", "hardware",
        "platform", "platforms", "solution", "solutions", "system", "systems", "cloud",
        "devops", "kubernetes", "linux", "python", "golang", "ruby", "rust", "react",
        "cybersecurity", "security", "threat", "vulnerability", "management", "strategy",
        "roadmap", "showcase", "exhibit", "exhibitor", "exhibitors", "booth", "track",
        "reception", "breakfast", "lunch", "dinner", "cocktail", "vip", "schedule",
        "avenue", "boulevard", "suite", "floor", "united", "states", "usa", "uk",
        "masterclass", "workshop", "webinar", "bootcamp", "tbd", "tba", "placeholder",
        "n/a", "none", "unknown", "what", "when", "where", "why", "how", "more",
    }
    raw_words = clean.split()
    if len(raw_words) < 2 or len(raw_words) > 4:
        return False

    alpha_words = [re.sub(r"[^A-Za-z'\-\u2019\.]", "", w) for w in raw_words]
    alpha_words = [w for w in alpha_words if w]
    if len(alpha_words) < 2 or len(alpha_words) > 4:
        return False

    non_initial_count = sum(1 for w in alpha_words if len(w.rstrip(".")) > 1)
    if non_initial_count < 2:
        return False

    # First & last word must not be single-letter initials
    if len(alpha_words[0].rstrip(".")) < 2 or len(alpha_words[-1].rstrip(".")) < 2:
        return False

    for idx, w in enumerate(alpha_words):
        w_clean = w.rstrip(".").lower()
        if w_clean in invalid_words:
            return False
        is_mid = 0 < idx < len(alpha_words) - 1
        if not _is_valid_name_token(w, allow_initial=is_mid):
            return False

    return True


def resolve_company_website(company: str) -> str:
    if not company:
        return ""
    comp_clean = company.lower().strip()
    if comp_clean in COMPANY_DOMAINS:
        return COMPANY_DOMAINS[comp_clean]
    for k, v in COMPANY_DOMAINS.items():
        if re.search(rf"\b{re.escape(k)}\b", comp_clean):
            return v
    return ""


def _azure_extract_speakers_from_text(page_text: str, conf_title: str, source_url: str) -> List[Dict[str, str]]:
    """
    Uses Azure OpenAI (gpt-5.4-mini) to extract ONLY genuinely listed speakers from official event HTML text.
    Strictly forbidden from inventing names, roles, companies, or LinkedIn URLs.
    """
    global _AZURE_SPEAKER_EXHAUSTED
    if _AZURE_SPEAKER_EXHAUSTED:
        return []
    api_key = getattr(settings, "AZURE_OPENAI_API_KEY", "") or ""
    base_url = getattr(settings, "AZURE_OPENAI_BASE_URL", "") or ""
    deployment = getattr(settings, "AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini") or "gpt-5.4-mini"
    if not api_key or not base_url or not page_text or len(page_text) < 120:
        return []

    # Check if text contains at least some speaker/program cues to avoid unnecessary LLM calls on empty promo pages
    if not re.search(r"\b(speaker|speakers|keynote|faculty|presenter|panelist|moderator|host|chair|agenda|session|program|featured)\b", page_text, re.I):
        return []

    snippet = page_text[:14000]
    prompt = (
        f"Extract ONLY the real human speakers, keynote presenters, faculty, or panelists explicitly listed in the event text below for '{conf_title}'.\n"
        f"CRITICAL RULES:\n"
        f"1. ONLY include people whose full names literally appear in the provided text.\n"
        f"2. NEVER invent, guess, or use conference names, sponsors, or placeholders ('Keynote Speaker', 'Industry Organization', 'TBD').\n"
        f"3. Leave job_role_designation, company_name, or linkedin_url as empty string \"\" if not explicitly stated in the text.\n"
        f"4. Return JSON object with key 'speakers': list of objects with keys speaker_name, job_role_designation, company_name, linkedin_url.\n\n"
        f"TEXT:\n{snippet}"
    )

    try:
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        resp = requests.post(
            endpoint,
            headers={
                "api-key": api_key,
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": deployment,
                "messages": [
                    {"role": "system", "content": "You extract strictly factual speaker rosters from webpage text. Never fabricate."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=25,
        )
        if resp.status_code in (401, 402, 429):
            logger.warning(f"Azure OpenAI speaker extractor limit/auth notice (HTTP {resp.status_code}).")
            if resp.status_code in (401, 402):
                _AZURE_SPEAKER_EXHAUSTED = True
            return []
        if resp.status_code != 200:
            return []

        raw_content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw_content)
        out: List[Dict[str, str]] = []
        for item in parsed.get("speakers", []) or []:
            if not isinstance(item, dict):
                continue
            name = html.unescape((item.get("speaker_name") or "").strip())
            if not name or not is_valid_speaker_name(name):
                continue
            # Double check name actually appears in snippet text
            last_tok = re.sub(r"[^a-zA-Z]", "", name.split()[-1])
            if last_tok and last_tok.lower() not in snippet.lower():
                continue

            role = html.unescape((item.get("job_role_designation") or "").strip())
            comp = html.unescape((item.get("company_name") or "").strip())
            if role.lower() in ("speaker", "keynote speaker", "n/a", "tbd", "unknown"):
                role = ""
            if comp.lower() in ("industry organization", "n/a", "tbd", "unknown", conf_title.lower()):
                comp = ""
            li = (item.get("linkedin_url") or "").strip()
            if "linkedin.com/in/" not in li.lower():
                li = ""
            elif li and li.lower() not in page_text.lower() and "/in/" not in page_text.lower():
                li = ""

            out.append({
                "conference_name": conf_title,
                "speaker_name": name,
                "company_name": comp,
                "company_organization": comp,
                "job_role_designation": role,
                "linkedin_url": li,
                "official_company_website_url": resolve_company_website(comp),
                "source_url": source_url,
            })
        return out
    except Exception as e:
        logger.debug(f"Azure speaker extraction note for '{conf_title}': {e}")
        return []


def _parse_role_and_company(raw_desc: str, conf_title: str = "") -> tuple:
    """Splits combined 'Title at Company' / 'Title, Company' cleanly without inventing defaults."""
    if not raw_desc:
        return "", ""
    desc = html.unescape(raw_desc).strip().strip("•|–-,").strip()
    if not desc or desc.lower() in ("tbd", "tba", "n/a", "none"):
        return "", ""

    role, comp = "", ""
    if " at " in desc:
        role, comp = [p.strip() for p in desc.split(" at ", 1)]
    elif "@" in desc:
        role, comp = [p.strip() for p in desc.split("@", 1)]
    elif " | " in desc:
        role, comp = [p.strip() for p in desc.split(" | ", 1)]
    elif " - " in desc:
        role, comp = [p.strip() for p in desc.split(" - ", 1)]
    elif " – " in desc:
        role, comp = [p.strip() for p in desc.split(" – ", 1)]
    elif "," in desc:
        role, comp = [p.strip() for p in desc.split(",", 1)]
    else:
        role = desc

    if role.lower() in ("speaker", "keynote speaker", "n/a", "tbd", "industry organization"):
        role = ""
    if comp.lower() in ("industry organization", "n/a", "tbd", conf_title.lower()):
        comp = ""
    return role[:100], comp[:100]


def fetch_official_site_speakers(official_url: str, conf_title: str = "") -> List[Dict[str, str]]:
    """
    Crawls official conference page + discovered speaker/faculty/agenda links (and standard subpaths)
    to extract ALL genuine speakers with zero fabricated roles/companies/placeholders.
    """
    if not official_url or not official_url.startswith("http"):
        return []

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    }

    parsed_root = urllib.parse.urlparse(official_url)
    base = f"{parsed_root.scheme}://{parsed_root.netloc}"
    trimmed = official_url.rstrip("/")

    urls_to_try: List[str] = [official_url]
    seen_urls = {official_url.rstrip("/")}

    def _queue_url(u: str):
        clean_u = u.split("#")[0].rstrip("/")
        if clean_u and clean_u not in seen_urls and len(urls_to_try) < 9:
            seen_urls.add(clean_u)
            urls_to_try.append(u.split("#")[0])

    # Queue common official subpages (skip path guessing on aggregator roots like eventbrite/meetup/luma)
    is_aggregator = any(dom in parsed_root.netloc.lower() for dom in ["eventbrite.", "meetup.com", "lu.ma", "luma.com", "allevents.in", "10times.com"])
    if not is_aggregator:
        for path in ["/speakers", "/faculty", "/agenda", "/program", "/schedule", "/presenters", "/lineup"]:
            _queue_url(trimmed + path)
            if trimmed != base:
                _queue_url(base + path)

    discovered: List[Dict[str, str]] = []
    seen_names: Dict[str, int] = {}

    def _add_or_merge(rec: Dict[str, str]):
        s_name = (rec.get("speaker_name") or "").strip()
        if not s_name or not is_valid_speaker_name(s_name):
            return
        n_key = s_name.lower()
        if n_key in seen_names:
            idx = seen_names[n_key]
            existing = discovered[idx]
            if not existing["job_role_designation"] and rec.get("job_role_designation"):
                existing["job_role_designation"] = rec["job_role_designation"]
            if not existing["company_name"] and rec.get("company_name"):
                existing["company_name"] = rec["company_name"]
                existing["company_organization"] = rec["company_name"]
                existing["official_company_website_url"] = rec.get("official_company_website_url") or resolve_company_website(rec["company_name"])
            if not existing["linkedin_url"] and rec.get("linkedin_url"):
                existing["linkedin_url"] = rec["linkedin_url"]
            return
        seen_names[n_key] = len(discovered)
        discovered.append(rec)

    combined_relevant_text: List[str] = []

    idx_url = 0
    while idx_url < len(urls_to_try) and idx_url < 9:
        target_url = urls_to_try[idx_url]
        idx_url += 1
        try:
            r = requests.get(target_url, headers=headers, timeout=9)
            if r.status_code != 200 or not r.text:
                continue
            soup = BeautifulSoup(r.text, 'html.parser')

            # Discover same-domain links from homepage/nav pointing to speaker/faculty/program pages
            if idx_url == 1 and not is_aggregator:
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    txt = (a.get_text(" ", strip=True) or "").lower()
                    href_l = href.lower()
                    if any(k in href_l or k in txt for k in ["speaker", "faculty", "presenter", "keynote", "agenda", "program", "schedule", "lineup", "panelist"]):
                        abs_u = urllib.parse.urljoin(target_url, href)
                        p_u = urllib.parse.urlparse(abs_u)
                        if p_u.netloc == parsed_root.netloc and not abs_u.lower().endswith((".pdf", ".jpg", ".png", ".css", ".js")):
                            _queue_url(abs_u)

            # 1. Parse Schema.org JSON-LD (@graph supported)
            for s in soup.find_all('script', type='application/ld+json'):
                try:
                    raw_js = s.string or s.get_text() or ""
                    if not raw_js.strip():
                        continue
                    data = json.loads(raw_js)
                    nodes = data if isinstance(data, list) else (data.get("@graph", [data]) if isinstance(data, dict) else [])
                    items = []
                    for node in nodes:
                        if not isinstance(node, dict):
                            continue
                        ntype = node.get("@type")
                        if ntype == "Person":
                            items.append(node)
                        elif ntype == "ItemList":
                            for el in node.get("itemListElement", []):
                                items.append(el.get("item", el) if isinstance(el, dict) else {})
                        elif ntype in ["Event", "BusinessEvent", "EducationEvent", "SocialEvent"]:
                            perf = node.get("performer") or node.get("performers") or []
                            if isinstance(perf, dict):
                                items.append(perf)
                            elif isinstance(perf, list):
                                items.extend(perf)

                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        name = html.unescape((it.get('name') or '').strip())
                        if not is_valid_speaker_name(name):
                            continue
                        role = html.unescape((it.get('jobTitle') or '').strip())
                        works_for = it.get('worksFor') or {}
                        company = works_for.get('name', '').strip() if isinstance(works_for, dict) else (str(works_for).strip() if works_for else '')
                        if company.lower() in ('none', '{}', 'n/a', 'unknown', 'industry organization'):
                            company = ''
                        same_as = it.get('sameAs', '')
                        if isinstance(same_as, list):
                            same_as = next((u for u in same_as if isinstance(u, str) and 'linkedin.com/in/' in u.lower()), '')
                        li_url = same_as if (isinstance(same_as, str) and 'linkedin.com/in/' in same_as.lower()) else ''
                        comp_website = resolve_company_website(company)
                        if role.lower() in ('speaker', 'keynote speaker'):
                            role = ''

                        _add_or_merge({
                            'conference_name': conf_title,
                            'speaker_name': name,
                            'company_name': company,
                            'company_organization': company,
                            'job_role_designation': role,
                            'linkedin_url': li_url,
                            'official_company_website_url': comp_website,
                            'source_url': it.get('url') or target_url
                        })
                except Exception:
                    pass

            # 2. Parse HTML speaker cards / containers with optional nearby personal LinkedIn links
            for card in soup.find_all(["div", "li", "article", "section"], class_=re.compile(r"(speaker|faculty|presenter|keynote|panelist|team|card)", re.I)):
                card_links = [a.get("href", "") for a in card.find_all("a", href=True) if "linkedin.com/in/" in a.get("href", "").lower()]
                card_li = card_links[0].split("?")[0].rstrip("/") if card_links else ""
                heading = card.find(["h2", "h3", "h4", "h5", "strong"])
                if not heading:
                    continue
                cand_name = html.unescape(heading.get_text(" ", strip=True))
                if not is_valid_speaker_name(cand_name):
                    continue
                lines = [html.unescape(ln.strip()) for ln in card.get_text("\n", strip=True).split("\n") if ln.strip()]
                desc_parts = [ln for ln in lines if ln.lower() != cand_name.lower() and len(ln) <= 120]
                role_str, comp_str = "", ""
                if len(desc_parts) >= 2 and len(desc_parts[0]) <= 70 and len(desc_parts[1]) <= 70 and " at " not in desc_parts[0] and "," not in desc_parts[0]:
                    role_str = desc_parts[0]
                    comp_str = desc_parts[1]
                elif desc_parts:
                    role_str, comp_str = _parse_role_and_company(desc_parts[0], conf_title)
                _add_or_merge({
                    'conference_name': conf_title,
                    'speaker_name': cand_name,
                    'company_name': comp_str,
                    'company_organization': comp_str,
                    'job_role_designation': role_str,
                    'linkedin_url': card_li,
                    'official_company_website_url': resolve_company_website(comp_str),
                    'source_url': target_url
                })

            # 3. Parse plain text "Featured Speakers / Keynote Speakers / Faculty" sections
            text_all = html.unescape(soup.get_text('\n', strip=True))
            if any(k in target_url.lower() for k in ["speaker", "faculty", "agenda", "program", "schedule"]) or len(combined_relevant_text) < 2:
                combined_relevant_text.append(f"[PAGE: {target_url}]\n{text_all[:7000]}")

            for marker in ["Featured Speakers", "Keynote Speakers", "Our Speakers", "Speakers & Presenters", "Course Faculty", "Program Committee"]:
                m_idx = text_all.lower().find(marker.lower())
                if m_idx != -1:
                    block = text_all[m_idx + len(marker):m_idx + len(marker) + 4000]
                    lines = [l.strip() for l in block.split("\n") if l.strip()]
                    j = 0
                    while j < len(lines):
                        line = lines[j].strip().strip(",- \t\n•·")
                        if is_valid_speaker_name(line):
                            role_line = lines[j + 1].strip() if j + 1 < len(lines) else ""
                            comp_line = lines[j + 2].strip() if j + 2 < len(lines) else ""
                            job_role, comp_name, adv = "", "", 1
                            if role_line and not is_valid_speaker_name(role_line) and len(role_line) < 100:
                                job_role, comp_name = _parse_role_and_company(role_line, conf_title)
                                adv = 2
                                if not comp_name and comp_line and not is_valid_speaker_name(comp_line) and len(comp_line) < 70 and not any(bad in comp_line.lower() for bad in ["view ", "read ", "learn ", "bio", "session"]):
                                    comp_name = comp_line
                                    adv = 3
                            _add_or_merge({
                                'conference_name': conf_title,
                                'speaker_name': line,
                                'company_name': comp_name,
                                'company_organization': comp_name,
                                'job_role_designation': job_role,
                                'linkedin_url': '',
                                'official_company_website_url': resolve_company_website(comp_name),
                                'source_url': target_url
                            })
                            j += adv
                            continue
                        j += 1
        except Exception as e:
            logger.debug(f"Error fetching official site speakers from {target_url}: {e}")

    # 4. If DOM/JSON-LD yielded fewer than 3 speakers and we have rich speaker/faculty page text, use Azure OpenAI strictly over text
    if len(discovered) < 3 and combined_relevant_text:
        ai_speakers = _azure_extract_speakers_from_text("\n\n".join(combined_relevant_text), conf_title, official_url)
        for spk in ai_speakers:
            _add_or_merge(spk)

    return discovered

