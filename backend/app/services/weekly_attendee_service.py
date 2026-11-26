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
from ..models import WeeklyConference, WeeklyAttendee, WeeklySpeaker
from ..scrapers.base_scraper import BaseScraper, clean_html_text
from ..scrapers.live_speaker_scraper import is_valid_speaker_name
from ..services.onedrive_excel_service import OneDriveExcelService, canonicalize_url, normalize_title
from ..storage.excel_manager import ExcelManager
from ..ai.extractor import (
    clean_and_resolve_speaker,
    discover_and_verify_linkedin_profile
)
from ..services.apollo_service import is_name_match, is_company_match

logger = logging.getLogger(__name__)

_AZURE_ATTENDEE_EXHAUSTED = False


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


def generate_weekly_attendee_id(conf_id: str, name: str) -> str:
    """Generates a stable Attendee ID."""
    norm = re.sub(r'[^a-zA-Z0-9]', '', name.lower())[:6].upper()
    return f"ATT-{conf_id}-{norm}-{uuid.uuid4().hex[:3].upper()}"


def _azure_extract_attendees_from_text(page_text: str, conf_title: str) -> List[Dict[str, str]]:
    """
    Uses Azure OpenAI (gpt-5.4-mini) to extract ONLY genuinely listed public attendees,
    delegates, or participants from explicitly published attendee/participant text.
    Strictly excludes speakers, panelists, hosts, sponsors, and exhibitors, and never fabricates details.
    """
    global _AZURE_ATTENDEE_EXHAUSTED
    if _AZURE_ATTENDEE_EXHAUSTED:
        return []
    api_key = getattr(settings, "AZURE_OPENAI_API_KEY", "") or ""
    base_url = getattr(settings, "AZURE_OPENAI_BASE_URL", "") or ""
    deployment = getattr(settings, "AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini") or "gpt-5.4-mini"
    if not api_key or not base_url or not page_text or len(page_text) < 100:
        return []

    if not re.search(r"\b(attendee|attendees|attending|participants|delegates|rsvp|going|registered guests)\b", page_text, re.I):
        return []

    snippet = page_text[:12000]
    prompt = (
        f"Extract ONLY genuine human attendees, registered delegates, or participants explicitly listed as attending '{conf_title}'.\n"
        f"CRITICAL RULES:\n"
        f"1. ONLY include people explicitly shown as attending/registered attendees/participants/delegates.\n"
        f"2. NEVER include speakers, keynote presenters, panelists, moderators, hosts, organizers, sponsors, or exhibitors.\n"
        f"3. NEVER invent names, job titles, companies, or LinkedIn URLs. Leave job_title, company_name, or linkedin_url as \"\" if not literally present in the text.\n"
        f"4. Return JSON with key 'attendees': list of objects with keys attendee_name, job_title, company_name, linkedin_url.\n\n"
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
                    {"role": "system", "content": "You extract strictly factual public attendee rosters from text. Return empty list when uncertain."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
            timeout=25,
        )
        if resp.status_code in (401, 402, 429):
            if resp.status_code in (401, 402):
                _AZURE_ATTENDEE_EXHAUSTED = True
            return []
        if resp.status_code != 200:
            return []

        raw_content = resp.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw_content)
        out: List[Dict[str, str]] = []
        for item in parsed.get("attendees", []) or []:
            if not isinstance(item, dict):
                continue
            name = clean_html_text(item.get("attendee_name") or "").strip()
            if not name or not is_valid_speaker_name(name):
                continue
            last_tok = re.sub(r"[^a-zA-Z]", "", name.split()[-1])
            if last_tok and last_tok.lower() not in snippet.lower():
                continue

            title = clean_html_text(item.get("job_title") or "").strip()
            comp = clean_html_text(item.get("company_name") or "").strip()
            if title.lower() in ("n/a", "tbd", "unknown", "attendee", "delegate", "participant", "conference delegate"):
                title = ""
            if comp.lower() in ("n/a", "tbd", "unknown", conf_title.lower()):
                comp = ""
            li = validate_personal_linkedin_url(item.get("linkedin_url") or "")
            if li and "/in/" not in snippet.lower():
                li = ""

            out.append({
                "name": name,
                "title": title,
                "company": comp,
                "linkedin_url": li,
            })
        return out
    except Exception as e:
        logger.debug(f"Azure attendee extraction notice for '{conf_title}': {e}")
        return []


class WeeklyAttendeeService:
    """
    Dedicated Weekly Conference Attendee Collection & Sync Service:
    - Checks official conference websites, attendee pages, and registration platforms.
    - Collects genuine attendee lists published by organizers where publicly accessible.
    - Strictly avoids treating speakers, sponsors, exhibitors, or hosts as attendees.
    - Never fabricates names, emails, LinkedIn URLs, companies, job titles, or placeholder rows.
    - Stores genuine records exclusively in the dedicated 'weekly_attendees' worksheet and 'tbl_weekly_attendees' table.
    - Preserves all existing conferences, speakers, historical rows, and outreach columns untouched.
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

    def _parse_attendees_from_html(self, html_text: str, page_url: str, conf_name: str = "") -> List[Dict[str, str]]:
        """Parses Meetup, Luma, and HTML attendee containers without fabricating missing fields."""
        soup = BeautifulSoup(html_text, "html.parser")
        candidates: List[Dict[str, str]] = []
        seen_names = set()

        def _add_candidate(name: str, title: str = "", company: str = "", linkedin_url: str = "", source_url: str = ""):
            c_name = clean_html_text(name).strip()
            if not c_name or not is_valid_speaker_name(c_name):
                return
            key = c_name.lower()
            if key in seen_names:
                return
            seen_names.add(key)
            c_title = clean_html_text(title).strip()
            c_comp = clean_html_text(company).strip()
            if c_title.lower() in ("n/a", "tbd", "none", "unknown", "attendee", "delegate", "participant", "speaker", "keynote speaker"):
                c_title = ""
            if c_comp.lower() in ("n/a", "tbd", "none", "unknown", conf_name.lower() if conf_name else ""):
                c_comp = ""
            candidates.append({
                "name": c_name,
                "title": c_title,
                "company": c_comp,
                "linkedin_url": validate_personal_linkedin_url(linkedin_url),
                "source_url": source_url or page_url,
            })

        # 1. Check Meetup.com RSVP attendance (__NEXT_DATA__ / __APOLLO_STATE__)
        if "meetup.com" in page_url.lower():
            script = soup.find("script", id="__NEXT_DATA__")
            if script and script.string:
                try:
                    data = json.loads(script.string)
                    page_props = data.get("props", {}).get("pageProps", {})
                    apollo = page_props.get("__APOLLO_STATE__", {})
                    event = page_props.get("event", {})
                    host_ids = {str(h.get("id")) for h in event.get("eventHosts", []) if isinstance(h, dict)}
                    for k, v in apollo.items():
                        if (k.startswith("Member:") or k.startswith("User:")) and isinstance(v, dict):
                            m_id = str(v.get("id", ""))
                            raw_name = (v.get("name") or "").strip()
                            if raw_name and m_id not in host_ids:
                                name_clean = " ".join(part.capitalize() for part in raw_name.split())
                                _add_candidate(name_clean, source_url=page_url)
                except Exception as me:
                    logger.debug(f"Meetup attendee parse notice for {page_url}: {me}")

        # 2. Check Luma guests (__NEXT_DATA__)
        if "lu.ma" in page_url.lower() or "luma.com" in page_url.lower():
            script = soup.find("script", id="__NEXT_DATA__")
            if script and script.string:
                try:
                    data = json.loads(script.string)
                    guests = data.get("props", {}).get("pageProps", {}).get("initialData", {}).get("guests", [])
                    for g in guests:
                        u = g.get("user", {}) if isinstance(g, dict) else {}
                        name = (u.get("name") or "").strip()
                        li_raw = (u.get("linkedin_handle") or "").strip()
                        if li_raw and "linkedin.com/" not in li_raw.lower():
                            li_raw = f"https://www.linkedin.com/in/{li_raw.lstrip('/')}"
                        _add_candidate(
                            name=name,
                            title=u.get("title", "") or "",
                            company=u.get("company", "") or "",
                            linkedin_url=li_raw,
                            source_url=page_url,
                        )
                except Exception as le:
                    logger.debug(f"Luma guest parse notice for {page_url}: {le}")

        # 3. Check HTML tables / cards / lists explicitly labeled as attendee / participant / delegate rosters
        if not candidates:
            for container in soup.find_all(["section", "div", "table", "ul"], class_=re.compile(r"\b(attendee|attendees|participant|participants|delegate|delegates|guest-list|roster)\b", re.I)):
                c_text = container.get_text(" ", strip=True).lower()
                if any(bad in c_text for bad in ["speaker", "keynote", "sponsor", "exhibitor", "committee", "agenda", "faculty"]):
                    continue

                if container.name == "table":
                    for row in container.find_all("tr"):
                        cols = [clean_html_text(td.get_text(" ", strip=True)) for td in row.find_all(["td", "th"])]
                        if len(cols) >= 2 and cols[0] and cols[0].lower() not in ("name", "attendee", "attendee name", "participant"):
                            li_a = row.find("a", href=re.compile(r"linkedin\.com/in/", re.I))
                            _add_candidate(
                                name=cols[0],
                                title=cols[1] if len(cols) > 2 else "",
                                company=cols[2] if len(cols) > 2 else cols[1],
                                linkedin_url=li_a["href"] if li_a and li_a.has_attr("href") else "",
                                source_url=page_url,
                            )
                else:
                    items = container.find_all(["li", "div", "article"], recursive=False)
                    if not items:
                        items = container.find_all(["li", "div", "article"], class_=re.compile(r"(card|item|member|row|attendee|participant)", re.I))
                    for item in items[:80]:
                        heading = item.find(["h2", "h3", "h4", "h5", "strong", "span", "p"])
                        cand_name = clean_html_text(heading.get_text(" ", strip=True)) if heading else ""
                        if not is_valid_speaker_name(cand_name):
                            continue
                        li_a = item.find("a", href=re.compile(r"linkedin\.com/in/", re.I))
                        lines = [clean_html_text(ln) for ln in item.get_text("\n", strip=True).split("\n") if ln.strip()]
                        desc = [ln for ln in lines if ln.lower() != cand_name.lower() and len(ln) <= 90]
                        _add_candidate(
                            name=cand_name,
                            title=desc[0] if len(desc) >= 1 else "",
                            company=desc[1] if len(desc) >= 2 else "",
                            linkedin_url=li_a["href"] if li_a and li_a.has_attr("href") else "",
                            source_url=page_url,
                        )

        # 4. If URL itself is an attendee/participant/delegate page and DOM yielded 0, use Azure OpenAI strictly over text
        if not candidates and any(k in page_url.lower() for k in ["attendee", "participant", "delegate", "who-attends", "whos-attending"]):
            text_all = clean_html_text(soup.get_text("\n", strip=True))
            for ai_att in _azure_extract_attendees_from_text(text_all, conf_name):
                _add_candidate(
                    name=ai_att["name"],
                    title=ai_att.get("title", ""),
                    company=ai_att.get("company", ""),
                    linkedin_url=ai_att.get("linkedin_url", ""),
                    source_url=page_url,
                )

        return candidates

    def check_public_attendee_list(self, url: str, conf_name: str = "") -> Tuple[bool, List[Dict[str, str]]]:
        """
        Inspects an official event URL and its attendee/participant/delegate subpages for publicly published attendee rosters.
        Returns (is_available, attendee_records).
        """
        if not url or not url.startswith("http"):
            return False, []

        parsed_root = urllib.parse.urlparse(url)
        base = f"{parsed_root.scheme}://{parsed_root.netloc}"
        trimmed = url.rstrip("/")
        is_aggregator = any(dom in parsed_root.netloc.lower() for dom in ["eventbrite.", "meetup.com", "lu.ma", "luma.com", "allevents.in", "10times.com", "tsnn.com", "tradefest.io", "eventseye.com", "eventsinamerica.com", "cvent.com", "govevents.com"])

        urls_to_check: List[str] = [url]
        seen_urls = {trimmed}

        def _queue(u: str):
            cu = u.split("#")[0].rstrip("/")
            if cu and cu not in seen_urls and len(urls_to_check) < 6:
                seen_urls.add(cu)
                urls_to_check.append(u.split("#")[0])

        if not is_aggregator:
            for sub in ["/attendees", "/attendee-list", "/participants", "/delegates", "/who-is-attending", "/who-attends"]:
                _queue(trimmed + sub)

        idx = 0
        while idx < len(urls_to_check) and idx < 6:
            target = urls_to_check[idx]
            idx += 1
            try:
                resp = self._get_session().get(target, timeout=8)
                if resp.status_code != 200 or not resp.text:
                    continue

                if idx == 1 and not is_aggregator:
                    soup_nav = BeautifulSoup(resp.text, "html.parser")
                    for a in soup_nav.find_all("a", href=True):
                        href = a["href"].strip()
                        txt = (a.get_text(" ", strip=True) or "").lower()
                        href_l = href.lower()
                        if any(k in href_l or k in txt for k in ["attendee", "participant", "delegate", "who-attends", "who-is-attending", "whos-going"]):
                            abs_u = urllib.parse.urljoin(target, href)
                            if urllib.parse.urlparse(abs_u).netloc == parsed_root.netloc and not abs_u.lower().endswith((".pdf", ".jpg", ".png")):
                                _queue(abs_u)

                atts = self._parse_attendees_from_html(resp.text, target, conf_name=conf_name)
                if atts:
                    return True, atts
            except Exception as e:
                logger.debug(f"Public attendee check notice for {target}: {e}")

        return False, []

    def collect_weekly_attendees(
        self,
        conference_id: Optional[str] = None,
        run_id: Optional[str] = None,
        force: bool = False,
        sync_verified: bool = True,
    ) -> Dict[str, Any]:
        """
        Executes attendee collection for weekly conferences:
        1. Queries target WeeklyConference records in the active run / target Sunday-Saturday range.
        2. Removes any legacy placeholder rows ('Not Publicly Available') within the target conferences.
        3. Checks each conference for genuine public attendees across official pages, subpages, and sanctioned Tavily search.
        4. Strictly excludes speakers/hosts/exhibitors and never fabricates missing titles/companies/LinkedIn URLs.
        5. Stores ONLY genuine attendees (inserts 0 rows when no public attendee list exists).
        """
        start_time = time.time()
        logger.info("🚀 [Attendee Collection] Starting weekly conference attendee collection...")

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
        logger.info(f"Checking {len(target_confs)} weekly conferences for public attendee lists...")

        # Remove any stale 'Not Publicly Available' placeholders for target conferences
        if target_conf_ids:
            self.db.query(WeeklyAttendee).filter(
                WeeklyAttendee.conference_id.in_(target_conf_ids),
                WeeklyAttendee.attendee_name == "Not Publicly Available"
            ).delete(synchronize_session=False)
            self.db.flush()

        # Preload speakers per conference to avoid counting speakers as attendees
        speakers_by_conf: Dict[str, set] = {}
        if target_conf_ids:
            for spk in self.db.query(WeeklySpeaker).filter(WeeklySpeaker.conference_id.in_(target_conf_ids)).all():
                speakers_by_conf.setdefault(spk.conference_id, set()).add((spk.speaker_name or "").strip().lower())

        # Existing attendees map in DB to avoid duplicate entries
        existing_db_atts = self.db.query(WeeklyAttendee).all()
        existing_att_keys = {
            (att.conference_name.strip().lower(), att.attendee_name.strip().lower())
            for att in existing_db_atts
        }
        existing_att_cid_keys = {
            (att.conference_id.strip().lower(), att.attendee_name.strip().lower())
            for att in existing_db_atts
            if att.conference_id
        }

        collected_records: List[WeeklyAttendee] = []
        confs_with_public_attendees = 0
        confs_no_public_attendees = 0
        today = date.today()
        tavily_helper = BaseScraper("weekly_attendee_discovery", "")

        def _discover_conf_attendees(c_id: str, c_name: str, off_u: str, src_u: str) -> Tuple[str, bool, List[Dict[str, str]], str]:
            urls_to_check = []
            if src_u and any(x in src_u.lower() for x in ["meetup.com", "lu.ma", "luma.com"]):
                urls_to_check.append(src_u)
            if off_u and off_u not in urls_to_check:
                urls_to_check.append(off_u)
            if src_u and src_u not in urls_to_check:
                urls_to_check.append(src_u)

            has_pub = False
            raw_atts: List[Dict[str, str]] = []
            ev_url = off_u or src_u or ""

            for u in urls_to_check:
                h_pub, r_atts = self.check_public_attendee_list(u, conf_name=c_name)
                if h_pub and r_atts:
                    has_pub = True
                    raw_atts = r_atts
                    ev_url = u
                    break

            if (not has_pub or not raw_atts) and getattr(settings, "TAVILY_API_KEY", ""):
                try:
                    t_results = tavily_helper.tavily_search(
                        f'"{c_name}" 2026 ("attendee list" OR "who attends" OR "who is attending" OR "participants" OR "delegates")',
                        max_results=4,
                    )
                    snippet_blocks: List[str] = []
                    for tr in t_results:
                        r_url = tr.get("url", "")
                        if r_url and any(k in r_url.lower() for k in ["attendee", "participant", "delegate", "who-attends", "whos-attending", "lu.ma", "luma.com", "meetup.com"]):
                            h_pub, r_atts = self.check_public_attendee_list(r_url, conf_name=c_name)
                            if h_pub and r_atts:
                                has_pub = True
                                raw_atts = r_atts
                                ev_url = r_url
                                break
                        r_txt = clean_html_text(f"{tr.get('title', '')}\n{tr.get('content', '')}")
                        if r_txt:
                            snippet_blocks.append(f"[{r_url}]\n{r_txt}")
                    if (not has_pub or not raw_atts) and snippet_blocks:
                        ai_atts = _azure_extract_attendees_from_text("\n\n".join(snippet_blocks), c_name)
                        if ai_atts:
                            has_pub = True
                            raw_atts = ai_atts
                except Exception as te:
                    logger.debug(f"Tavily attendee discovery notice for '{c_name}': {te}")
            return c_id, has_pub, raw_atts, ev_url

        discovered_map: Dict[str, Tuple[bool, List[Dict[str, str]], str]] = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futs = [
                pool.submit(
                    _discover_conf_attendees,
                    c.conference_id,
                    clean_html_text(c.conference_name).strip(),
                    c.official_event_url or "",
                    c.source_url or "",
                )
                for c in target_confs
            ]
            for fut in futs:
                try:
                    cid_r, hp, ratts, evu = fut.result(timeout=45)
                    discovered_map[cid_r] = (hp, ratts, evu)
                except Exception:
                    pass

        for conf in target_confs:
            conf_name = clean_html_text(conf.conference_name).strip()
            conf_date = conf.start_date
            c_run_id = conf.weekly_run_id or run_id or "WEEKLY-ATTENDEE-RUN"
            conf_speakers = speakers_by_conf.get(conf.conference_id, set())

            has_public_list, raw_attendees, event_url = discovered_map.get(
                conf.conference_id,
                (False, [], conf.official_event_url or conf.source_url or ""),
            )

            if has_public_list and raw_attendees:
                valid_conf_added = 0
                for raw in raw_attendees:
                    att_name = clean_html_text(raw.get("name") or "").strip()
                    if not att_name or not is_valid_speaker_name(att_name):
                        continue
                    if att_name.lower() in conf_speakers:
                        continue

                    att_title = clean_html_text(raw.get("title") or "").strip()
                    att_company = clean_html_text(raw.get("company") or "").strip()
                    if att_title.lower() in ("n/a", "tbd", "none", "unknown", "conference delegate"):
                        att_title = ""
                    if att_company.lower() in ("n/a", "tbd", "none", "unknown", conf_name.lower()):
                        att_company = ""

                    dup_key = (conf_name.lower(), att_name.lower())
                    cid_dup_key = (conf.conference_id.lower(), att_name.lower())
                    if dup_key in existing_att_keys or cid_dup_key in existing_att_cid_keys:
                        continue
                    existing_att_keys.add(dup_key)
                    existing_att_cid_keys.add(cid_dup_key)

                    raw_li = raw.get("linkedin_url") or ""
                    li_url = validate_personal_linkedin_url(raw_li)
                    if not li_url and att_company:
                        try:
                            li_url = validate_personal_linkedin_url(
                                discover_and_verify_linkedin_profile(att_name, att_company, att_title, conf.city)
                            )
                        except Exception:
                            li_url = ""
                    li_status = "verified" if li_url else "not_found"

                    att_id = generate_weekly_attendee_id(conf.conference_id, att_name)
                    att_record = WeeklyAttendee(
                        attendee_id=att_id,
                        conference_id=conf.conference_id,
                        conference_name=conf_name,
                        conference_date=conf_date,
                        attendee_name=att_name,
                        job_title=att_title,
                        company_name=att_company,
                        professional_email="",
                        email_status="Not Found",
                        personal_linkedin_url=li_url,
                        linkedin_status=li_status,
                        source_url=raw.get("source_url") or event_url,
                        availability_status="Available",
                        weekly_run_id=c_run_id,
                        collection_date=today,
                        created_at=datetime.utcnow()
                    )
                    self.db.add(att_record)
                    collected_records.append(att_record)
                    valid_conf_added += 1

                if valid_conf_added > 0:
                    confs_with_public_attendees += 1
                else:
                    confs_no_public_attendees += 1
            else:
                confs_no_public_attendees += 1
                logger.info(f"ℹ️ No genuine public attendee roster available for '{conf_name}'; inserting 0 placeholder rows.")

        # Commit to PostgreSQL
        self.db.commit()

        # Sync non-placeholder attendees to Local Excel ('weekly_attendees' worksheet)
        all_current_atts = self.db.query(WeeklyAttendee).filter(
            WeeklyAttendee.attendee_name != "Not Publicly Available"
        ).order_by(WeeklyAttendee.conference_date.asc(), WeeklyAttendee.conference_name.asc()).all()
        local_sync_res = {}
        try:
            local_sync_res = self.excel_mgr.sync_weekly_attendees_to_excel(all_current_atts, replace_all=True)
            logger.info(f"✅ Local Excel weekly_attendees sync result: {local_sync_res}")
        except Exception as e:
            logger.warning(f"⚠️ Local Excel weekly_attendees sync notice: {e}")

        # Sync to OneDrive Excel ('tbl_weekly_attendees' table on 'weekly_attendees' worksheet)
        onedrive_sync_res = {}
        try:
            onedrive_sync_res = self.onedrive_svc.sync_weekly_attendees(
                attendees=collected_records,
                run_id=run_id
            )
            logger.info(f"✅ OneDrive Excel weekly_attendees sync result: {onedrive_sync_res}")
        except Exception as e:
            logger.warning(f"⚠️ OneDrive Excel weekly_attendees sync notice: {e}")

        # Automated Sync to Verified Data Sheet
        if sync_verified:
            try:
                from .verified_data_service import VerifiedDataService
                VerifiedDataService(self.db).sync_all_verified_data()
                logger.info("✅ [Attendee Collection] Synchronized eligible verified attendees to 'Verified Data' sheet.")
            except Exception as ve:
                logger.warning(f"⚠️ [Attendee Collection] Notice syncing to Verified Data: {ve}")

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            f"🎉 [Attendee Collection] Completed: {len(target_confs)} conferences checked in {elapsed}s | "
            f"{len(collected_records)} genuine attendee records added (Conferences with public attendees: {confs_with_public_attendees}, "
            f"None publicly listed: {confs_no_public_attendees})."
        )

        return {
            "status": "success",
            "total_conferences_checked": len(target_confs),
            "conferences_with_public_attendees": confs_with_public_attendees,
            "conferences_not_publicly_available": confs_no_public_attendees,
            "total_records_created": len(collected_records),
            "local_excel_sync": local_sync_res,
            "onedrive_sync": onedrive_sync_res,
            "duration_seconds": elapsed
        }
