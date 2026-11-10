
import logging
import re
import threading
import uuid
import time
import urllib.parse
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
import requests
from sqlalchemy.orm import Session
from bs4 import BeautifulSoup

from ..config import settings
from ..models import WeeklyConference, WeeklyExhibitor
from ..scrapers.base_scraper import BaseScraper, clean_html_text
from ..services.onedrive_excel_service import OneDriveExcelService
from ..storage.excel_manager import ExcelManager

logger = logging.getLogger(__name__)

_AZURE_EXHIBITOR_EXHAUSTED = False

_AGGREGATOR_DOMAINS = (
    "eventbrite.", "meetup.com", "lu.ma", "luma.com", "allevents.in",
    "10times.com", "tsnn.com", "tradefest.io", "eventseye.com",
    "eventsinamerica.com", "cvent.com", "govevents.com",
)

_EXHIBITOR_NOISE_PATTERNS = re.compile(
    r"^(become an exhibitor|exhibitor list|exhibitor directory|exhibitors|sponsors|partners|"
    r"view all|see all|learn more|register now|book a booth|request booth|exhibitor prospectus|"
    r"home|about|agenda|speakers|faq|contact us|privacy policy|terms|n/a|tbd|tba|none|unknown|"
    r"platinum sponsor|gold sponsor|silver sponsor|bronze sponsor|title sponsor|media partner)$",
    re.I,
)


def validate_company_linkedin_url(url: Optional[str]) -> str:
    """Enforces strictly company LinkedIn profile URLs (https://www.linkedin.com/company/...)."""
    if not url:
        return ""
    clean = str(url).strip()
    clean_lower = clean.lower()
    if any(blocked in clean_lower for blocked in ["/in/", "/feed/", "/jobs/", "/posts/"]):
        return ""
    if "linkedin.com/company/" in clean_lower:
        if not clean.startswith("http://") and not clean.startswith("https://"):
            clean = "https://" + clean
        return clean.split("?")[0].rstrip("/")
    return ""


def validate_personal_linkedin_url(url: Optional[str]) -> str:
    """Enforces strictly personal profile URLs (https://www.linkedin.com/in/...)."""
    if not url:
        return ""
    clean = str(url).strip()
    clean_lower = clean.lower()
    if any(blocked in clean_lower for blocked in ["/company/", "/school/", "/showcase/", "/feed/", "/jobs/", "/posts/"]):
        return ""
    if "linkedin.com/in/" in clean_lower:
        if not clean.startswith("http://") and not clean.startswith("https://"):
            clean = "https://" + clean
        return clean.split("?")[0].rstrip("/")
    return ""


def generate_weekly_exhibitor_id(conf_id: str, comp_name: str) -> str:
    """Generates a stable Exhibitor ID."""
    norm = re.sub(r'[^a-zA-Z0-9]', '', comp_name.lower())[:6].upper()
    return f"EXH-{conf_id}-{norm}-{uuid.uuid4().hex[:3].upper()}"


def _is_valid_exhibitor_name(name: str, conf_name: str = "") -> bool:
    if not name:
        return False
    clean = clean_html_text(name).strip("•|–- \t\n,")
    if len(clean) < 2 or len(clean) > 100:
        return False
    if _EXHIBITOR_NOISE_PATTERNS.match(clean):
        return False
    if conf_name and clean.lower() == conf_name.strip().lower():
        return False
    if re.search(r"(https?://|www\.|cookie|privacy policy|all rights reserved|register today|buy ticket)", clean, re.I):
        return False
    return True


def _azure_extract_exhibitors_from_text(page_text: str, conf_title: str, source_url: str) -> List[Dict[str, str]]:
    """
    Uses Azure OpenAI (gpt-5.4-mini) to extract ONLY genuinely listed exhibitor / showcase companies
    from exhibitor directory or event page text. Verifies each company literally appears in text.
    """
    global _AZURE_EXHIBITOR_EXHAUSTED
    if _AZURE_EXHIBITOR_EXHAUSTED:
        return []
    api_key = getattr(settings, "AZURE_OPENAI_API_KEY", "") or ""
    base_url = getattr(settings, "AZURE_OPENAI_BASE_URL", "") or ""
    deployment = getattr(settings, "AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini") or "gpt-5.4-mini"
    if not api_key or not base_url or not page_text or len(page_text) < 120:
        return []

    if not re.search(r"\b(exhibitor|exhibitors|exhibiting|booth|pavilion|floorplan|floor plan|showcase|directory)\b", page_text, re.I):
        return []

    snippet = page_text[:13000]
    prompt = (
        f"Extract ONLY genuine exhibiting companies / vendors / showcase exhibitors explicitly listed for '{conf_title}'.\n"
        f"CRITICAL RULES:\n"
        f"1. ONLY include companies explicitly identified as exhibitors, exhibiting companies, booth holders, or expo showcase vendors whose names literally appear in TEXT.\n"
        f"2. NEVER include the conference organizer itself, venue hotels, cities, speaker names (unless company), generic sponsor tier labels ('Gold Sponsor'), or placeholders ('N/A', 'TBD', 'Not Publicly Available').\n"
        f"3. NEVER invent websites, emails, LinkedIn URLs, contacts, booth numbers, or descriptions. Leave any field not stated in TEXT as \"\".\n"
        f"4. Return JSON with key 'exhibitors': list of objects with keys company_name, booth_number, category_industry, company_description, company_website, contact_person, contact_designation, professional_email.\n\n"
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
                    {"role": "system", "content": "You extract strictly factual exhibitor directories from webpage text. Never fabricate."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=25,
        )
        if resp.status_code in (401, 402, 429):
            if resp.status_code in (401, 402):
                _AZURE_EXHIBITOR_EXHAUSTED = True
            return []
        if resp.status_code != 200:
            return []

        raw_content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw_content)
        out: List[Dict[str, str]] = []
        for item in parsed.get("exhibitors", []) or []:
            if not isinstance(item, dict):
                continue
            comp = clean_html_text(item.get("company_name") or "").strip()
            if not _is_valid_exhibitor_name(comp, conf_title):
                continue
            # Ensure company name token appears literally in snippet
            tokens = [t for t in re.findall(r"[a-zA-Z0-9]{3,}", comp)]
            if tokens and not any(t.lower() in snippet.lower() for t in tokens):
                continue

            website = clean_html_text(item.get("company_website") or "").strip()
            if website and any(dom in website.lower() for dom in _AGGREGATOR_DOMAINS):
                website = ""
            email = clean_html_text(item.get("professional_email") or "").strip()
            if email and ("@" not in email or email.lower() not in snippet.lower()):
                email = ""

            out.append({
                "company_name": comp[:120],
                "company_website": website[:250],
                "category_industry": clean_html_text(item.get("category_industry") or "")[:120],
                "company_description": clean_html_text(item.get("company_description") or "")[:300],
                "booth_number": clean_html_text(item.get("booth_number") or "")[:60],
                "contact_person": clean_html_text(item.get("contact_person") or "")[:100],
                "contact_designation": clean_html_text(item.get("contact_designation") or "")[:100],
                "professional_email": email[:120],
                "company_linkedin_url": validate_company_linkedin_url(item.get("company_linkedin_url") or ""),
                "contact_person_linkedin_url": validate_personal_linkedin_url(item.get("contact_person_linkedin_url") or ""),
                "source_url": source_url,
            })
        return out
    except Exception as e:
        logger.debug(f"Azure exhibitor extraction notice for '{conf_title}': {e}")
        return []


class WeeklyExhibitorService:
    """
    Dedicated Weekly Conference Exhibitor Collection & Sync Service:
    - Live-crawls official conference websites, exhibitor directories, floorplans, and partner/expo pages,
      supplemented by sanctioned Tavily discovery when directories are external.
    - Never relies on hardcoded exhibitor lists or placeholder rows ('Not Publicly Available').
    - Never fabricates company websites, emails, LinkedIn URLs, or contacts.
    - Stores genuine exhibitors in PostgreSQL, Local Excel ('weekly_exhibitors'), and OneDrive ('weekly_exhibitors' table).
    - Preserves all existing historical rows and outreach tracking columns untouched.
    """

    def __init__(self, db: Session):
        self.db = db
        self.onedrive_svc = OneDriveExcelService()
        self.excel_mgr = ExcelManager()
        self._thread_local = threading.local()
        self.session = self._get_session()

    def _get_session(self) -> requests.Session:
        s = getattr(self._thread_local, "session", None)
        if s is None:
            s = requests.Session()
            s.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            })
            self._thread_local.session = s
        return s

    def _extract_exhibitors_from_html(self, html_text: str, page_url: str, conf_name: str) -> List[Dict[str, str]]:
        """Extracts genuine exhibitor entries from HTML tables, cards, MapYourShow/a2z blocks, or grounded Azure text."""
        soup = BeautifulSoup(html_text, "html.parser")
        found: List[Dict[str, str]] = []
        seen_comps = set()

        def _add(rec: Dict[str, str]):
            comp = clean_html_text(rec.get("company_name") or "").strip()
            if not _is_valid_exhibitor_name(comp, conf_name):
                return
            key = comp.lower()
            if key in seen_comps:
                return
            seen_comps.add(key)
            found.append({
                "company_name": comp,
                "company_website": rec.get("company_website", "") or "",
                "category_industry": rec.get("category_industry", "") or "",
                "company_description": rec.get("company_description", "") or "",
                "booth_number": rec.get("booth_number", "") or "",
                "contact_person": rec.get("contact_person", "") or "",
                "contact_designation": rec.get("contact_designation", "") or "",
                "professional_email": rec.get("professional_email", "") or "",
                "company_linkedin_url": validate_company_linkedin_url(rec.get("company_linkedin_url", "")),
                "contact_person_linkedin_url": validate_personal_linkedin_url(rec.get("contact_person_linkedin_url", "")),
                "source_url": rec.get("source_url") or page_url,
            })

        parsed_page = urllib.parse.urlparse(page_url)

        # 1. Explicit exhibitor HTML tables
        for tbl in soup.find_all("table"):
            t_ctx = tbl.get_text(" ", strip=True).lower()
            if any(k in t_ctx for k in ["exhibitor", "booth", "company", "organization", "pavilion"]):
                rows = tbl.find_all("tr")
                hdrs = [clean_html_text(th.get_text(" ", strip=True)).lower() for th in (rows[0].find_all(["th", "td"]) if rows else [])]
                if not any(h in " ".join(hdrs) for h in ["exhibitor", "company", "organization", "booth", "vendor"]):
                    continue
                for tr in rows[1:]:
                    cols = [clean_html_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
                    if not cols:
                        continue
                    comp_val = cols[0]
                    booth_val = ""
                    cat_val = ""
                    for idx_c, h in enumerate(hdrs):
                        if idx_c < len(cols):
                            if "booth" in h:
                                booth_val = cols[idx_c]
                            elif any(x in h for x in ["category", "industry", "sector", "track"]):
                                cat_val = cols[idx_c]
                            elif any(x in h for x in ["company", "exhibitor", "organization"]) and cols[idx_c]:
                                comp_val = cols[idx_c]
                    ext_site = ""
                    li_comp = ""
                    for a in tr.find_all("a", href=True):
                        href = a["href"].strip()
                        if "linkedin.com/company/" in href.lower():
                            li_comp = href
                        elif href.startswith("http") and urllib.parse.urlparse(href).netloc != parsed_page.netloc and not any(d in href.lower() for d in _AGGREGATOR_DOMAINS):
                            if not ext_site:
                                ext_site = href
                    _add({
                        "company_name": comp_val,
                        "company_website": ext_site,
                        "category_industry": cat_val,
                        "booth_number": booth_val,
                        "company_linkedin_url": li_comp,
                        "source_url": page_url,
                    })

        # 2. Structured exhibitor cards / directory tiles (MapYourShow, Cadmium, custom React/WP grids)
        for container in soup.find_all(["section", "div", "ul"], class_=re.compile(r"\b(exhibitor|exhibitors|booth|floorplan|expo|vendor|showcase|directory)\b", re.I)):
            c_cls = " ".join(container.get("class", [])).lower()
            if any(bad in c_cls for bad in ["nav", "menu", "header", "footer", "button"]):
                continue
            cards = container.find_all(["div", "li", "article"], class_=re.compile(r"(card|item|exhibitor|tile|company|vendor|logo|row)", re.I))
            if not cards:
                cards = container.find_all("li", recursive=False)
            for card in cards[:120]:
                heading = card.find(["h2", "h3", "h4", "h5", "strong", "a"])
                cand_comp = clean_html_text(heading.get_text(" ", strip=True)) if heading else ""
                if not cand_comp:
                    img = card.find("img", alt=True)
                    if img:
                        cand_comp = clean_html_text(img.get("alt") or "")
                        cand_comp = re.sub(r"\s*logo\s*$", "", cand_comp, flags=re.I).strip()
                if not _is_valid_exhibitor_name(cand_comp, conf_name):
                    continue
                card_txt = clean_html_text(card.get_text("\n", strip=True))
                booth_m = re.search(r"\b(Booth\s*#?\s*[A-Z0-9\-]+)\b", card_txt, re.I)
                ext_site, li_comp = "", ""
                for a in card.find_all("a", href=True):
                    href = a["href"].strip()
                    if "linkedin.com/company/" in href.lower():
                        li_comp = href
                    elif href.startswith("http") and urllib.parse.urlparse(href).netloc != parsed_page.netloc and not any(d in href.lower() for d in _AGGREGATOR_DOMAINS):
                        if "linkedin.com" not in href.lower() and not ext_site:
                            ext_site = href
                _add({
                    "company_name": cand_comp,
                    "company_website": ext_site,
                    "booth_number": booth_m.group(1) if booth_m else "",
                    "company_linkedin_url": li_comp,
                    "source_url": page_url,
                })

        # 3. Grounded Azure OpenAI extraction when on an exhibitor/expo/floorplan/sponsors page and DOM didn't return structured cards
        is_exh_page = any(k in page_url.lower() for k in ["exhibitor", "floorplan", "mapyourshow", "a2z", "cadmium", "expo", "directory", "showcase"])
        if len(found) < 2 and is_exh_page:
            text_all = clean_html_text(soup.get_text("\n", strip=True))
            for rec in _azure_extract_exhibitors_from_text(text_all, conf_name, page_url):
                _add(rec)

        return found

    def discover_live_exhibitors_for_conference(
        self,
        conf: WeeklyConference,
        tavily_helper: Optional[BaseScraper] = None,
    ) -> Tuple[bool, List[Dict[str, str]]]:
        """
        Live-discovers genuine exhibitors for a weekly conference by:
        1. Crawling official_event_url + source_url and discovering exhibitor/floorplan/expo/partner links.
        2. Probing standard official exhibitor subpaths on non-aggregator domains.
        3. Using sanctioned Tavily search when direct pages yield 0 exhibitors.
        Returns (has_exhibitors, exhibitor_records).
        """
        conf_name = clean_html_text(conf.conference_name or "").strip()
        seed_urls = []
        for u in [conf.official_event_url, conf.source_url]:
            if u and u.startswith("http") and u not in seed_urls:
                seed_urls.append(u)

        urls_to_try: List[str] = list(seed_urls)
        seen_urls = {u.rstrip("/") for u in seed_urls}

        def _queue(u: str):
            cu = u.split("#")[0].rstrip("/")
            if cu and cu not in seen_urls and len(urls_to_try) < 10:
                seen_urls.add(cu)
                urls_to_try.append(u.split("#")[0])

        for u in seed_urls:
            p = urllib.parse.urlparse(u)
            if not any(dom in p.netloc.lower() for dom in _AGGREGATOR_DOMAINS):
                trimmed = u.rstrip("/")
                base = f"{p.scheme}://{p.netloc}"
                for path in ["/exhibitors", "/exhibitor-list", "/exhibitor-directory", "/exhibitors-list", "/floorplan", "/expo", "/sponsors", "/partners"]:
                    _queue(trimmed + path)
                    if trimmed != base:
                        _queue(base + path)

        all_found: List[Dict[str, str]] = []
        seen_comp_names = set()

        def _merge(recs: List[Dict[str, str]]):
            for rec in recs:
                c = (rec.get("company_name") or "").strip()
                k = c.lower()
                if c and k not in seen_comp_names:
                    seen_comp_names.add(k)
                    all_found.append(rec)

        idx = 0
        while idx < len(urls_to_try) and idx < 10:
            target = urls_to_try[idx]
            idx += 1
            try:
                resp = self._get_session().get(target, timeout=8)
                if resp.status_code != 200 or not resp.text:
                    continue

                # Discover internal or external exhibitor directory links (e.g. mapyourshow, a2z, /exhibitors)
                if idx <= len(seed_urls):
                    soup_nav = BeautifulSoup(resp.text, "html.parser")
                    for a in soup_nav.find_all("a", href=True):
                        href = a["href"].strip()
                        txt = (a.get_text(" ", strip=True) or "").lower()
                        href_l = href.lower()
                        if any(k in href_l or k in txt for k in ["exhibitor", "floorplan", "floor-plan", "mapyourshow", "a2z", "cadmium", "directory", "showcase", "expo-hall"]):
                            abs_u = urllib.parse.urljoin(target, href)
                            if abs_u.startswith("http") and not abs_u.lower().endswith((".pdf", ".jpg", ".png")):
                                _queue(abs_u)

                recs = self._extract_exhibitors_from_html(resp.text, target, conf_name)
                _merge(recs)
                if len(all_found) >= 15:
                    break
            except Exception as e:
                logger.debug(f"Exhibitor crawl notice on {target}: {e}")

        # Supplement with sanctioned Tavily search if direct crawl found 0 exhibitors
        if not all_found and tavily_helper and getattr(settings, "TAVILY_API_KEY", ""):
            try:
                t_results = tavily_helper.tavily_search(
                    f'"{conf_name}" 2026 ("exhibitor list" OR "exhibitor directory" OR "exhibitors" OR "floorplan" OR "mapyourshow")',
                    max_results=5,
                )
                snippet_blocks: List[str] = []
                for tr in t_results:
                    r_url = tr.get("url", "")
                    r_title = tr.get("title", "")
                    if r_url and any(k in (r_url + " " + r_title).lower() for k in ["exhibitor", "floorplan", "mapyourshow", "directory", "a2z", "cadmium", "expo", "partner", "sponsor"]):
                        try:
                            resp = self._get_session().get(r_url, timeout=8)
                            if resp.status_code == 200 and resp.text:
                                _merge(self._extract_exhibitors_from_html(resp.text, r_url, conf_name))
                        except Exception:
                            pass
                    r_txt = clean_html_text(f"{r_title}\n{tr.get('content', '')}")
                    if r_txt:
                        snippet_blocks.append(f"[{r_url}]\n{r_txt}")
                if not all_found and snippet_blocks:
                    _merge(
                        _azure_extract_exhibitors_from_text(
                            "\n\n".join(snippet_blocks),
                            conf_name,
                            conf.official_event_url or conf.source_url or "",
                        )
                    )
            except Exception as te:
                logger.debug(f"Tavily exhibitor discovery notice for '{conf_name}': {te}")

        return (len(all_found) > 0), all_found

    def collect_weekly_exhibitors(
        self,
        conference_id: Optional[str] = None,
        run_id: Optional[str] = None,
        force: bool = False,
        sync_verified: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes live exhibitor collection for weekly conferences:
        1. Queries target WeeklyConference records in the active run / target Sunday-Saturday range.
        2. Removes any legacy placeholder rows ('Not Publicly Available') within target conferences.
        3. Live-crawls official websites/directories + sanctioned Tavily search for genuine exhibitors.
        4. Stores ONLY genuine public exhibitors (inserts 0 rows when no exhibitor directory exists).
        5. Syncs to PostgreSQL, Local Excel ('weekly_exhibitors'), OneDrive ('weekly_exhibitors' table), and Verified Data.
        """
        start_time = time.time()
        logger.info("🚀 [Exhibitor Collection] Starting weekly conference exhibitor collection...")

        query = self.db.query(WeeklyConference)
        if conference_id:
            query = query.filter(WeeklyConference.conference_id == conference_id)
        elif run_id:
            parsed_range = None
            m_run = re.match(r"^WEEK-(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$", str(run_id).strip())
            if m_run:
                try:
                    parsed_range = (date.fromisoformat(m_run.group(1)), date.fromisoformat(m_run.group(2)))
                except ValueError:
                    parsed_range = None
            if parsed_range is None:
                from .weekly_service import calculate_weekly_target_range
                t_sun, t_sat, _ = calculate_weekly_target_range()
                parsed_range = (t_sun, t_sat)
            t_sun, t_sat = parsed_range
            query = query.filter(
                (WeeklyConference.weekly_run_id == run_id) |
                ((WeeklyConference.start_date >= t_sun) & (WeeklyConference.start_date <= t_sat))
            )

        target_confs = query.order_by(WeeklyConference.start_date.asc()).all()
        target_conf_ids = [c.conference_id for c in target_confs]
        logger.info(f"Checking {len(target_confs)} weekly conferences for live exhibitor directories...")

        # Remove stale 'Not Publicly Available' placeholders for target conferences
        if target_conf_ids:
            self.db.query(WeeklyExhibitor).filter(
                WeeklyExhibitor.conference_id.in_(target_conf_ids),
                WeeklyExhibitor.company_name == "Not Publicly Available"
            ).delete(synchronize_session=False)
            self.db.flush()

        # Existing exhibitors map in DB
        existing_db_exhs = self.db.query(WeeklyExhibitor).all()
        existing_exh_keys = {
            (exh.conference_name.strip().lower(), exh.company_name.strip().lower())
            for exh in existing_db_exhs
        }

        collected_records: List[WeeklyExhibitor] = []
        confs_with_exhibitors = 0
        confs_no_exhibitors = 0
        today = date.today()
        tavily_helper = BaseScraper("weekly_exhibitor_discovery", "")
        confs_needing_exh = []
        retained_conf_ids = set()
        for conf in target_confs:
            conf_name_chk = clean_html_text(conf.conference_name).strip()
            has_real_existing = any(
                k[0] == conf_name_chk.lower() and k[1] != "not publicly available"
                for k in existing_exh_keys
            )
            if has_real_existing and not force:
                logger.info(f"Retaining already collected genuine exhibitors for '{conf_name_chk}'.")
                confs_with_exhibitors += 1
                retained_conf_ids.add(conf.conference_id)
            else:
                confs_needing_exh.append(conf)

        exh_discovered_map: Dict[str, Tuple[bool, List[Dict[str, str]]]] = {}
        if confs_needing_exh:
            def _discover_one_exh(c_obj):
                return c_obj.conference_id, self.discover_live_exhibitors_for_conference(c_obj, tavily_helper=tavily_helper)

            with ThreadPoolExecutor(max_workers=6) as pool:
                futs = [pool.submit(_discover_one_exh, c) for c in confs_needing_exh]
                for fut in futs:
                    try:
                        cid_r, (hx, rex) = fut.result(timeout=45)
                        exh_discovered_map[cid_r] = (hx, rex)
                    except Exception:
                        pass

        for conf in confs_needing_exh:
            conf_name = clean_html_text(conf.conference_name).strip()
            conf_date = conf.start_date
            c_run_id = conf.weekly_run_id or run_id or "WEEKLY-EXHIBITOR-RUN"
            event_url = conf.official_event_url or conf.source_url or ""

            has_exhibitors, raw_exhibitors = exh_discovered_map.get(conf.conference_id, (False, []))

            if has_exhibitors and raw_exhibitors:
                added_for_conf = 0
                for raw in raw_exhibitors:
                    comp_name = clean_html_text(raw.get("company_name") or "").strip()
                    if not _is_valid_exhibitor_name(comp_name, conf_name):
                        continue

                    dup_key = (conf_name.lower(), comp_name.lower())
                    if dup_key in existing_exh_keys:
                        continue
                    existing_exh_keys.add(dup_key)

                    comp_li = validate_company_linkedin_url(raw.get("company_linkedin_url", ""))
                    person_li = validate_personal_linkedin_url(raw.get("contact_person_linkedin_url", ""))
                    raw_email = clean_html_text(raw.get("professional_email", "") or "").strip()

                    exh_id = generate_weekly_exhibitor_id(conf.conference_id, comp_name)
                    exh_record = WeeklyExhibitor(
                        exhibitor_id=exh_id,
                        conference_id=conf.conference_id,
                        conference_name=conf_name,
                        conference_date=conf_date,
                        company_name=comp_name,
                        company_website=raw.get("company_website", "") or "",
                        category_industry=raw.get("category_industry", "") or "",
                        company_description=raw.get("company_description", "") or "",
                        booth_number=raw.get("booth_number", "") or "",
                        contact_person=raw.get("contact_person", "") or "",
                        contact_designation=raw.get("contact_designation", "") or "",
                        professional_email=raw_email,
                        email_status="Needs Review" if raw_email else "Not Found",
                        company_linkedin_url=comp_li,
                        contact_person_linkedin_url=person_li,
                        source_url=raw.get("source_url") or event_url,
                        availability_status="Available",
                        weekly_run_id=c_run_id,
                        collection_date=today,
                        created_at=datetime.utcnow()
                    )
                    self.db.add(exh_record)
                    collected_records.append(exh_record)
                    added_for_conf += 1

                if added_for_conf > 0:
                    confs_with_exhibitors += 1
                else:
                    confs_no_exhibitors += 1
            else:
                confs_no_exhibitors += 1
                logger.info(f"ℹ️ No public exhibitor directory published for '{conf_name}'; inserting 0 placeholder rows.")

        # Commit to PostgreSQL
        self.db.commit()

        # Sync non-placeholder exhibitors to Local Excel ('weekly_exhibitors' worksheet)
        all_current_exhs = self.db.query(WeeklyExhibitor).filter(
            WeeklyExhibitor.company_name != "Not Publicly Available"
        ).order_by(
            WeeklyExhibitor.conference_date.asc(),
            WeeklyExhibitor.conference_name.asc()
        ).all()

        local_sync_res = {}
        try:
            local_sync_res = self.excel_mgr.sync_weekly_exhibitors_to_excel(all_current_exhs, replace_all=True)
            logger.info(f"✅ Local Excel weekly_exhibitors sync result: {local_sync_res}")
        except Exception as e:
            logger.warning(f"⚠️ Local Excel weekly_exhibitors sync notice: {e}")

        # Sync to OneDrive Excel ('weekly_exhibitors' table)
        onedrive_sync_res = {}
        try:
            onedrive_sync_res = self.onedrive_svc.sync_weekly_exhibitors(
                exhibitors=collected_records,
                run_id=run_id
            )
            logger.info(f"✅ OneDrive Excel weekly_exhibitors sync result: {onedrive_sync_res}")
        except Exception as e:
            logger.warning(f"⚠️ OneDrive Excel weekly_exhibitors sync notice: {e}")

        # Automated Sync to Verified Data Sheet
        if sync_verified:
            try:
                from .verified_data_service import VerifiedDataService
                VerifiedDataService(self.db).sync_all_verified_data()
                logger.info("✅ [Exhibitor Collection] Synchronized eligible verified exhibitors to 'Verified Data' sheet.")
            except Exception as ve:
                logger.warning(f"⚠️ [Exhibitor Collection] Notice syncing to Verified Data: {ve}")

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            f"🎉 [Exhibitor Collection] Completed: {len(target_confs)} conferences checked in {elapsed}s | "
            f"{len(collected_records)} genuine exhibitor records added (Conferences with Exhibitors: {confs_with_exhibitors}, "
            f"None publicly listed: {confs_no_exhibitors})."
        )

        return {
            "status": "success",
            "total_conferences_checked": len(target_confs),
            "conferences_with_exhibitors": confs_with_exhibitors,
            "conferences_not_publicly_available": confs_no_exhibitors,
            "total_records_created": len(collected_records),
            "local_excel_sync": local_sync_res,
            "onedrive_sync": onedrive_sync_res,
            "duration_seconds": elapsed
        }

