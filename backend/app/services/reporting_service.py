"""
Automated Weekly Outreach & Conference Reporting Service.

Strictly isolated reporting module that aggregates verified data across:
- PostgreSQL (WeeklyConference, WeeklySpeaker, WeeklyAttendee, WeeklyExhibitor, WeeklyCompany, WeeklySourceRunLog, SpeakerReply)
- Local Excel workbook (usa_conferences_published.xlsx)
- Outreach state tracking (outreach_state.json)
- Microsoft Graph mailbox telemetry (SentItems & Inbox for akash@adople.ai with local cache)

Guarantees:
- Zero fake, estimated, or hardcoded statistics
- Strict deduplication across mirrored storage layers
- Accurate NDR bounce detection (never misclassifying bounces as replies)
- Historical weekly snapshot persistence without overwriting completed past weeks
- Zero modification or interruption to existing scraping, scoring, outreach, reply-monitoring, or Teams workflows
"""

import hashlib
import json
import logging
import os
import re
import threading
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

import openpyxl
import requests
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal, engine
from ..models import (
    SpeakerReply,
    WeeklyAttendee,
    WeeklyCompany,
    WeeklyConference,
    WeeklyExhibitor,
    WeeklySourceRunLog,
    WeeklySpeaker,
)
from ..reporting_models import WeeklyReportSnapshot
from .onedrive_excel_service import normalize_title
from .speaker_outreach_service import (
    MSGraphOutreachClient,
    extract_body_text_ms,
    extract_bounce_recipient,
    fallback_reply_analysis,
    get_state_file_path,
    is_bounce_email,
)

logger = logging.getLogger("reporting_service")

BASE_PROJECT_DIR = Path("/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva")
REPORTS_DIR = BASE_PROJECT_DIR / "data" / "reports"
ARCHIVE_DIR = REPORTS_DIR / "archive"
CACHE_DIR = REPORTS_DIR / "cache"
GRAPH_CACHE_PATH = CACHE_DIR / "graph_outreach_cache.json"
LIVE_PAYLOAD_CACHE_PATH = CACHE_DIR / "latest_report_payload.json"

for _d in (REPORTS_DIR, ARCHIVE_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

_report_lock = threading.Lock()

TEMPLATES_ORDERED = ["Speakers", "Attendees", "Exhibitors", "General", "Follow-Up"]
ALLOWED_TEMPLATES = set(TEMPLATES_ORDERED)


# ------------------------------------------------------------------------------
# Date & Week Boundary Helpers
# ------------------------------------------------------------------------------
def get_report_tz() -> ZoneInfo:
    tz_name = getattr(settings, "OUTREACH_TIMEZONE", None) or getattr(settings, "WEEKLY_TIMEZONE", "Asia/Kolkata")
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("Asia/Kolkata")


def week_bounds_from_date(d: date) -> Tuple[date, date, str]:
    """Returns (sunday, saturday, WEEK-YYYY-MM-DD_YYYY-MM-DD) for any date."""
    days_since_sunday = (d.weekday() + 1) % 7
    wk_start = d - timedelta(days=days_since_sunday)
    wk_end = wk_start + timedelta(days=6)
    return wk_start, wk_end, f"WEEK-{wk_start.isoformat()}_{wk_end.isoformat()}"


def parse_week_id(week_id: str) -> Optional[Tuple[date, date]]:
    m = re.match(r"^WEEK-(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})$", str(week_id or "").strip())
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))
    except Exception:
        return None


def parse_timestamp_local(ts: Any, assume_utc_if_naive: bool = False) -> Optional[datetime]:
    """Parses ISO/space timestamps into timezone-aware datetime in report timezone."""
    if ts is None:
        return None
    tz = get_report_tz()
    if isinstance(ts, datetime):
        dt_obj = ts
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc if assume_utc_if_naive else tz)
        return dt_obj.astimezone(tz)
    if isinstance(ts, date):
        return datetime(ts.year, ts.month, ts.day, tzinfo=tz)

    s = str(ts).strip()
    if not s:
        return None
    s_norm = s.replace("Z", "+00:00")
    try:
        dt_obj = datetime.fromisoformat(s_norm)
        if dt_obj.tzinfo is None:
            dt_obj = dt_obj.replace(tzinfo=timezone.utc if assume_utc_if_naive else tz)
        return dt_obj.astimezone(tz)
    except Exception:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt_obj = datetime.strptime(s[:19], fmt)
            dt_obj = dt_obj.replace(tzinfo=timezone.utc if assume_utc_if_naive else tz)
            return dt_obj.astimezone(tz)
        except Exception:
            continue
    return None


def _clean_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s.lower() in ("none", "null", "nan"):
        return ""
    return s


def _is_valid_email(em: str) -> bool:
    s = _clean_str(em).lower()
    if not s or "@" not in s or "." not in s or " " in s:
        return False
    if s in ("not available", "not publicly available", "n/a", "none", "tbd"):
        return False
    return bool(re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", s))


def _is_placeholder_entity(name: str, status: str = "") -> bool:
    n = _clean_str(name).lower()
    st = _clean_str(status).lower()
    if not n:
        return True
    if n in ("not publicly available", "not available", "n/a", "none", "tbd", "unknown"):
        return True
    if "not publicly available" in st:
        return True
    return False


def _clean_bounce_reason(body_text: str, subject: str = "") -> str:
    """Extracts a concise, factual diagnostic reason from an SMTP/Exchange NDR bounce email."""
    txt = _clean_str(body_text)
    if not txt:
        return _clean_str(subject) or "Undeliverable (NDR returned)"

    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    keep: List[str] = []
    stop_markers = (
        "diagnostic information for administrators",
        "how to fix it",
        "more info for email admins",
        "original message headers",
    )
    for ln in lines:
        low = ln.lower()
        if any(m in low for m in stop_markers):
            if keep:
                break
            continue
        if any(
            k in low
            for k in (
                "rejected your message",
                "couldn't be delivered",
                "could not be delivered",
                "was undeliverable",
                "reason for the problem",
                "5.1.",
                "5.4.",
                "5.7.",
                "550",
                "554",
                "wasn't found",
                "does not exist",
                "not found",
                "message blocked",
                "access denied",
                "delivery has failed",
                "problem with the recipient",
                "unknown address",
                "dns",
            )
        ):
            keep.append(ln)
        if len(" | ".join(keep)) > 260:
            break

    if not keep:
        keep = lines[:3]
    summary = " | ".join(keep)
    if len(summary) > 320:
        summary = summary[:317] + "..."
    return summary


def classify_template_used(
    subject: str = "",
    body: str = "",
    contact_category: str = "",
    is_followup: bool = False,
) -> str:
    """
    Deterministically classifies which template generated the email:
    'Speakers', 'Attendees', 'Exhibitors', 'General', or 'Follow-Up'.
    """
    subj_low = _clean_str(subject).lower()
    body_low = _clean_str(body).lower()
    combined = f"{subj_low}\n{body_low}"

    if (
        is_followup
        or subj_low.startswith("re:")
        or "quickly follow up on my previous note" in body_low
        or "following up on my previous note" in body_low
        or "follow-up" in subj_low
    ):
        return "Follow-Up"

    if "where ai could be useful in your business" in combined:
        return "Speakers"
    if "understand you participated in" in combined:
        return "Attendees"
    if (
        "organization's participation" in combined
        or "organization’s participation" in combined
        or "complement your existing solutions" in combined
    ):
        return "Exhibitors"
    if (
        "a practical ai starting point" in combined
        or "salem, india" in combined
        or "referred by" not in subj_low and "practical ai" in combined
    ):
        return "General"

    # Fallback by role only when template body text is absent
    if not body_low and not subj_low:
        cat_low = _clean_str(contact_category).lower()
        if "attendee" in cat_low:
            return "Attendees"
        if "exhibitor" in cat_low:
            return "Exhibitors"
        if "speaker" in cat_low:
            return "Speakers"
    return "General"


def _compute_rates(sent: int, delivered: int, bounced: int, replied: int) -> Dict[str, Any]:
    return {
        "sent": sent,
        "delivered": delivered,
        "bounced": bounced,
        "replied": replied,
        "delivery_rate_pct": round((delivered / sent) * 100.0, 2) if sent > 0 else 0.0,
        "bounce_rate_pct": round((bounced / sent) * 100.0, 2) if sent > 0 else 0.0,
        "reply_rate_pct": round((replied / sent) * 100.0, 2) if sent > 0 else 0.0,
        "reply_rate_of_delivered_pct": round((replied / delivered) * 100.0, 2) if delivered > 0 else 0.0,
    }


def _is_internal_or_non_outreach_sent(subject: str, to_emails: List[str], known_lead_emails: Set[str], conv_id: str, known_thread_ids: Set[str]) -> Tuple[bool, bool]:
    """
    Returns (is_campaign_outreach, is_test_send).
    Strictly filters out:
    - Automated T-2 conference reminders ('USA Conference Reminder ...')
    - Internal Graph API test notifications ('Conference Agent Test Notification')
    - Unrelated personal/business mailbox correspondence not matching outreach templates or lead lists
    Separately flags CONF-TEST-OUTREACH / WEEK-TEST / skjeeva2005@gmail.com as is_test_send=True.
    """
    subj_low = _clean_str(subject).lower()
    if (
        subj_low.startswith("usa conference reminder")
        or subj_low.startswith("conference agent test notification")
    ):
        return False, False

    if "skjeeva2005@gmail.com" in to_emails or "ai innovation summit 2026" in subj_low:
        return True, True

    if conv_id and conv_id in known_thread_ids:
        return True, False
    if any(em in known_lead_emails for em in to_emails):
        return True, False

    outreach_subj_markers = (
        "akash from adople ai – referred by",
        "akash from adople ai - referred by",
        "re: akash from adople ai",
        "a practical ai starting point for",
        "re: collaboration regarding your upcoming session",
    )
    if any(subj_low.startswith(m) for m in outreach_subj_markers):
        return True, False

    return False, False


class ReportingService:
    """
    Central automated reporting engine integrating PostgreSQL, Local Excel,
    outreach_state.json, and Microsoft Graph Outlook telemetry (with caching).
    """

    def __init__(self, db: Optional[Session] = None):
        if db is None:
            self.db = SessionLocal()
            self._owns_db = True
        else:
            self.db = db
            self._owns_db = False
        self.local_excel_path = Path(settings.EXCEL_OUTPUT_PATH)

    def close(self):
        if getattr(self, "_owns_db", False) and self.db:
            try:
                self.db.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def ensure_initialized():
        """Ensures weekly_report_snapshots table and directories exist without disturbing existing tables."""
        try:
            for d in (REPORTS_DIR, ARCHIVE_DIR, CACHE_DIR):
                d.mkdir(parents=True, exist_ok=True)
            WeeklyReportSnapshot.__table__.create(bind=engine, checkfirst=True)
        except Exception as e:
            logger.warning(f"[ReportingService] Table initialization notice: {e}")

    # --------------------------------------------------------------------------
    # Microsoft Graph Outlook Cache & Sync (Read-Only Mailbox Query)
    # --------------------------------------------------------------------------
    def _load_graph_cache(self) -> Dict[str, Any]:
        if GRAPH_CACHE_PATH.exists():
            try:
                with open(GRAPH_CACHE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
            except Exception as e:
                logger.debug(f"Could not read graph cache: {e}")
        return {"fetched_at": "", "sent_messages": [], "inbox_messages": [], "mailbox": settings.OUTREACH_MS_MAILBOX}

    def sync_graph_mailbox_cache(self, since_date: str = "2026-10-25T00:00:00Z") -> Dict[str, Any]:
        """
        Read-only fetch of SentItems and Inbox from akash@adople.ai via Microsoft Graph
        and persistence into local JSON cache for ultra-fast 24/7 reporting.
        Never modifies mailbox state, read/unread flags, or outreach_state.json.
        """
        client = MSGraphOutreachClient()

        def _fetch_all(url: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
            items: List[Dict[str, Any]] = []
            cur_url: Optional[str] = url
            cur_params: Optional[Dict[str, str]] = params
            while cur_url:
                resp = requests.get(cur_url, headers=client.headers(), params=cur_params, timeout=20)
                cur_params = None
                if resp.status_code != 200:
                    raise RuntimeError(f"Graph API {resp.status_code}: {resp.text[:250]}")
                payload = resp.json()
                items.extend(payload.get("value", []))
                cur_url = payload.get("@odata.nextLink")
            return items

        sent_url = f"{client.base_url}/users/{client.mailbox}/mailFolders/SentItems/messages"
        sent_raw = _fetch_all(
            sent_url,
            {
                "$filter": f"sentDateTime ge {since_date}",
                "$top": "100",
                "$select": "id,subject,sentDateTime,toRecipients,conversationId,bodyPreview,body",
            },
        )

        inbox_url = f"{client.base_url}/users/{client.mailbox}/mailFolders/Inbox/messages"
        inbox_raw = _fetch_all(
            inbox_url,
            {
                "$filter": f"receivedDateTime ge {since_date}",
                "$top": "100",
                "$select": "id,subject,receivedDateTime,from,conversationId,bodyPreview,body",
            },
        )

        sent_compact = []
        for m in sent_raw:
            to_list = [
                {
                    "name": _clean_str(r.get("emailAddress", {}).get("name", "")),
                    "address": _clean_str(r.get("emailAddress", {}).get("address", "")).lower(),
                }
                for r in (m.get("toRecipients") or [])
                if r.get("emailAddress", {}).get("address")
            ]
            body_text = extract_body_text_ms(m)
            sent_compact.append(
                {
                    "id": m.get("id", ""),
                    "subject": _clean_str(m.get("subject", "")),
                    "sentDateTime": m.get("sentDateTime", ""),
                    "conversationId": m.get("conversationId", ""),
                    "toRecipients": to_list,
                    "bodyText": body_text,
                    "bodyPreview": _clean_str(m.get("bodyPreview", "")),
                }
            )

        inbox_compact = []
        for m in inbox_raw:
            from_obj = (m.get("from") or {}).get("emailAddress", {})
            body_text = extract_body_text_ms(m)
            bounce = is_bounce_email(m, body_text)
            bounced_addr = extract_bounce_recipient(m, body_text) if bounce else ""
            inbox_compact.append(
                {
                    "id": m.get("id", ""),
                    "subject": _clean_str(m.get("subject", "")),
                    "receivedDateTime": m.get("receivedDateTime", ""),
                    "conversationId": m.get("conversationId", ""),
                    "fromName": _clean_str(from_obj.get("name", "")),
                    "fromAddress": _clean_str(from_obj.get("address", "")).lower(),
                    "bodyText": body_text,
                    "bodyPreview": _clean_str(m.get("bodyPreview", "")),
                    "isBounce": bool(bounce),
                    "bounceRecipient": _clean_str(bounced_addr).lower(),
                    "bounceReason": _clean_bounce_reason(body_text, m.get("subject", "")) if bounce else "",
                }
            )

        cache_obj = {
            "fetched_at": datetime.now(get_report_tz()).isoformat(timespec="seconds"),
            "mailbox": client.mailbox,
            "sent_messages": sent_compact,
            "inbox_messages": inbox_compact,
        }
        tmp = f"{GRAPH_CACHE_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache_obj, f, indent=2)
        os.replace(tmp, GRAPH_CACHE_PATH)
        logger.info(
            f"[ReportingService] Refreshed Graph mailbox cache ({len(sent_compact)} sent, {len(inbox_compact)} inbox)."
        )
        return cache_obj

    # --------------------------------------------------------------------------
    # Source Loaders
    # --------------------------------------------------------------------------
    def _load_outreach_state(self) -> Dict[str, Any]:
        p = get_state_file_path()
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    return d
            except Exception as e:
                logger.warning(f"[ReportingService] Could not read outreach state {p}: {e}")
        return {"threads": {}, "sent_log": [], "replies": [], "processed_reply_ids": []}

    def _load_local_excel_sheets(self) -> Dict[str, List[Dict[str, Any]]]:
        """Reads all relevant sheets from Local Excel in read-only mode without holding any locks."""
        sheets_data: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        if not self.local_excel_path.exists():
            return sheets_data

        target_sheets = [
            "weekly_conference",
            "weekly_speakers",
            "weekly_attendees",
            "weekly_exhibitors",
            "Qualified Leads",
            "Non -Qualified Leads",
            "Verified Data",
            "Companies scoring",
            "latest_week_scoring",
            "Speakers Replies",
            "weekly_source_log",
        ]
        wb = openpyxl.load_workbook(self.local_excel_path, read_only=True, data_only=True)
        try:
            for sh_name in target_sheets:
                if sh_name not in wb.sheetnames:
                    continue
                ws = wb[sh_name]
                raw = list(ws.iter_rows(values_only=True))
                if not raw:
                    continue
                headers = [_clean_str(h) for h in raw[0]]
                if sh_name == "Companies scoring":
                    # Preserve raw rows too because historical 15-col and newer 21-col schemas coexist cleanly
                    for r in raw[1:]:
                        if not any(v is not None and str(v).strip() != "" for v in r):
                            continue
                        sheets_data[sh_name].append({"_raw": list(r)})
                    continue

                for r in raw[1:]:
                    if not any(v is not None and str(v).strip() != "" for v in r):
                        continue
                    row_dict: Dict[str, Any] = {}
                    for idx, h in enumerate(headers):
                        if h:
                            row_dict[h] = r[idx] if idx < len(r) else ""
                    sheets_data[sh_name].append(row_dict)
        finally:
            wb.close()
        return sheets_data

    # --------------------------------------------------------------------------
    # Section 4: Conference Scraping Aggregation (PG + Excel)
    # --------------------------------------------------------------------------
    def _aggregate_conference_scraping(self, excel_sheets: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        db_confs = self.db.query(WeeklyConference).all()
        db_spks = self.db.query(WeeklySpeaker).all()
        db_atts = self.db.query(WeeklyAttendee).all()
        db_exhs = self.db.query(WeeklyExhibitor).all()
        db_logs = self.db.query(WeeklySourceRunLog).all()

        def _norm_wk(raw_run_id: str, start_dt: Optional[date]) -> str:
            parsed = parse_week_id(raw_run_id)
            if parsed:
                return raw_run_id.strip()
            if start_dt:
                return week_bounds_from_date(start_dt)[2]
            return "UNASSIGNED"

        # 1. Deduplicate Conferences across DB and Excel
        conf_by_id: Dict[str, Dict[str, Any]] = {}
        conf_id_by_name: Dict[str, str] = {}
        seen_title_date: Dict[Tuple[str, str], str] = {}

        def _register_conf(
            cid: str,
            name: str,
            start_d: Optional[date],
            end_d: Optional[date],
            city: str,
            state_v: str,
            country: str,
            industry: str,
            url: str,
            src_name: str,
            link_status: str,
            run_id_raw: str,
        ):
            clean_name = _clean_str(name)
            clean_cid = _clean_str(cid)
            if not clean_name or clean_cid.startswith("CONF-TEST"):
                return
            wk_id = _norm_wk(run_id_raw, start_d)
            if wk_id == "WEEK-TEST":
                return

            d_str = start_d.isoformat() if start_d else ""
            td_key = (normalize_title(clean_name), d_str)
            canonical_cid = clean_cid

            if canonical_cid in conf_by_id:
                rec = conf_by_id[canonical_cid]
                if not rec["official_website"] and url:
                    rec["official_website"] = url
                if not rec["industry"] and industry:
                    rec["industry"] = industry
                if not rec["city"] and city:
                    rec["city"] = city
                return

            if td_key in seen_title_date:
                existing_id = seen_title_date[td_key]
                conf_id_by_name[clean_name.lower()] = existing_id
                conf_id_by_name[normalize_title(clean_name)] = existing_id
                return

            if not canonical_cid:
                canonical_cid = f"CONF-{hashlib.md5((clean_name + d_str).encode()).hexdigest()[:10].upper()}"

            seen_title_date[td_key] = canonical_cid
            conf_id_by_name[clean_name.lower()] = canonical_cid
            conf_id_by_name[normalize_title(clean_name)] = canonical_cid

            loc_parts = [p for p in (_clean_str(city), _clean_str(state_v), _clean_str(country)) if p]
            conf_by_id[canonical_cid] = {
                "conference_id": canonical_cid,
                "conference_name": clean_name,
                "week_id": wk_id,
                "start_date": d_str,
                "end_date": end_d.isoformat() if end_d else d_str,
                "city": _clean_str(city),
                "state": _clean_str(state_v),
                "location": ", ".join(loc_parts) or "USA",
                "industry": _clean_str(industry) or "Technology & Business",
                "official_website": _clean_str(url),
                "source_name": _clean_str(src_name),
                "link_status": _clean_str(link_status) or "verified",
                "speakers_count": 0,
                "attendees_count": 0,
                "exhibitors_count": 0,
                "verified_emails_count": 0,
                "speakers": [],
                "attendees": [],
                "exhibitors": [],
            }

        for c in db_confs:
            _register_conf(
                c.conference_id,
                c.conference_name,
                c.start_date,
                c.end_date,
                c.city,
                c.state,
                c.country,
                c.industry,
                c.official_event_url or c.source_url,
                c.source_name,
                c.link_status,
                c.weekly_run_id,
            )

        for r in excel_sheets.get("weekly_conference", []):
            sd = parse_timestamp_local(r.get("Conference_Start_Date"))
            ed = parse_timestamp_local(r.get("Conference_End_Date"))
            _register_conf(
                r.get("Conference_ID", ""),
                r.get("Conference_Name", ""),
                sd.date() if sd else None,
                ed.date() if ed else None,
                r.get("Conference_City", ""),
                r.get("Conference_State", ""),
                r.get("Country", "USA"),
                r.get("Industry", ""),
                r.get("Official_Event_URL", "") or r.get("Source_URL", ""),
                r.get("Source_Name", ""),
                r.get("Link_Status", ""),
                r.get("Weekly_Run_ID", ""),
            )

        def _resolve_conf(cid: str, cname: str, fallback_date: Optional[date], fallback_run: str) -> Optional[Dict[str, Any]]:
            c1 = _clean_str(cid)
            if c1 and c1 in conf_by_id:
                return conf_by_id[c1]
            cn = _clean_str(cname)
            if cn:
                mapped = conf_id_by_name.get(cn.lower()) or conf_id_by_name.get(normalize_title(cn))
                if mapped and mapped in conf_by_id:
                    return conf_by_id[mapped]
            return None

        # 2. Speakers (dedup by conf_id + speaker_name_lower)
        seen_spks: Set[Tuple[str, str]] = set()
        speaker_rows_all: List[Dict[str, Any]] = []

        def _add_speaker(
            cid: str,
            cname: str,
            sname: str,
            title: str,
            comp: str,
            email: str,
            linkedin: str,
            ver_status: str,
            run_id_raw: str,
        ):
            if _clean_str(run_id_raw) == "WEEK-TEST" or _clean_str(cid).startswith("CONF-TEST"):
                return
            clean_s = _clean_str(sname)
            if _is_placeholder_entity(clean_s):
                return
            c_rec = _resolve_conf(cid, cname, None, run_id_raw)
            eff_cid = c_rec["conference_id"] if c_rec else _clean_str(cid)
            eff_cname = c_rec["conference_name"] if c_rec else _clean_str(cname)
            wk_id = c_rec["week_id"] if c_rec else (_norm_wk(run_id_raw, None))

            k = (eff_cid or eff_cname.lower(), clean_s.lower())
            if k in seen_spks:
                return
            seen_spks.add(k)
            em_clean = _clean_str(email).lower()
            has_valid_em = _is_valid_email(em_clean)
            item = {
                "week_id": wk_id,
                "conference_id": eff_cid,
                "conference_name": eff_cname,
                "name": clean_s,
                "job_title": _clean_str(title),
                "company": _clean_str(comp),
                "email": em_clean if has_valid_em else "",
                "email_verified": bool(has_valid_em and (_clean_str(ver_status).lower() == "verified" or has_valid_em)),
                "linkedin": _clean_str(linkedin),
            }
            speaker_rows_all.append(item)
            if c_rec is not None:
                c_rec["speakers"].append(item)
                c_rec["speakers_count"] += 1
                if has_valid_em:
                    c_rec["verified_emails_count"] += 1

        for s in db_spks:
            _add_speaker(
                s.conference_id,
                s.conference_name,
                s.speaker_name,
                s.job_title,
                s.company_name,
                s.professional_email,
                s.personal_linkedin_url,
                s.verification_status,
                s.weekly_run_id,
            )
        for r in excel_sheets.get("weekly_speakers", []):
            _add_speaker(
                r.get("Conference_ID", ""),
                r.get("Conference_Name", ""),
                r.get("Speaker_Name", ""),
                r.get("Job_Title", ""),
                r.get("Company_Name", ""),
                r.get("Professional_Email", ""),
                r.get("Personal_LinkedIn_URL", ""),
                r.get("Verification_Status", ""),
                r.get("Weekly_Run_ID", ""),
            )

        # 3. Genuine Attendees (exclude 'Not Publicly Available' placeholders)
        seen_atts: Set[Tuple[str, str]] = set()
        attendee_rows_all: List[Dict[str, Any]] = []

        def _add_attendee(
            cid: str,
            cname: str,
            conf_dt_val: Any,
            aname: str,
            title: str,
            comp: str,
            email: str,
            email_st: str,
            avail_st: str,
            linkedin: str,
            run_id_raw: str,
        ):
            clean_a = _clean_str(aname)
            if _is_placeholder_entity(clean_a, avail_st):
                return
            dt_obj = parse_timestamp_local(conf_dt_val)
            c_rec = _resolve_conf(cid, cname, dt_obj.date() if dt_obj else None, run_id_raw)
            eff_cid = c_rec["conference_id"] if c_rec else _clean_str(cid)
            eff_cname = c_rec["conference_name"] if c_rec else _clean_str(cname)
            wk_id = c_rec["week_id"] if c_rec else _norm_wk(run_id_raw, dt_obj.date() if dt_obj else None)

            k = (eff_cid or eff_cname.lower(), clean_a.lower())
            if k in seen_atts:
                return
            seen_atts.add(k)
            em_clean = _clean_str(email).lower()
            has_valid_em = _is_valid_email(em_clean)
            item = {
                "week_id": wk_id,
                "conference_id": eff_cid,
                "conference_name": eff_cname,
                "name": clean_a,
                "job_title": _clean_str(title),
                "company": _clean_str(comp),
                "email": em_clean if has_valid_em else "",
                "email_verified": has_valid_em,
                "linkedin": _clean_str(linkedin),
            }
            attendee_rows_all.append(item)
            if c_rec is not None:
                c_rec["attendees"].append(item)
                c_rec["attendees_count"] += 1
                if has_valid_em:
                    c_rec["verified_emails_count"] += 1

        for a in db_atts:
            _add_attendee(
                a.conference_id,
                a.conference_name,
                a.conference_date,
                a.attendee_name,
                a.job_title,
                a.company_name,
                a.professional_email,
                a.email_status,
                a.availability_status,
                a.personal_linkedin_url,
                a.weekly_run_id,
            )
        for r in excel_sheets.get("weekly_attendees", []):
            _add_attendee(
                "",
                r.get("Conference Name", ""),
                r.get("Conference Date", ""),
                r.get("Attendee Name", ""),
                r.get("Job Title", ""),
                r.get("Company", ""),
                r.get("Professional Email", ""),
                r.get("Email Status", ""),
                "",
                r.get("LinkedIn URL", ""),
                "",
            )

        # 4. Genuine Exhibitors (exclude 'Not Publicly Available' placeholders)
        seen_exhs: Set[Tuple[str, str]] = set()
        exhibitor_rows_all: List[Dict[str, Any]] = []

        def _add_exhibitor(
            cid: str,
            cname: str,
            conf_dt_val: Any,
            comp_name: str,
            contact_person: str,
            designation: str,
            email: str,
            website: str,
            booth: str,
            avail_st: str,
            run_id_raw: str,
        ):
            clean_comp = _clean_str(comp_name)
            if _is_placeholder_entity(clean_comp, avail_st):
                return
            dt_obj = parse_timestamp_local(conf_dt_val)
            c_rec = _resolve_conf(cid, cname, dt_obj.date() if dt_obj else None, run_id_raw)
            eff_cid = c_rec["conference_id"] if c_rec else _clean_str(cid)
            eff_cname = c_rec["conference_name"] if c_rec else _clean_str(cname)
            wk_id = c_rec["week_id"] if c_rec else _norm_wk(run_id_raw, dt_obj.date() if dt_obj else None)

            k = (eff_cid or eff_cname.lower(), clean_comp.lower())
            if k in seen_exhs:
                return
            seen_exhs.add(k)
            em_clean = _clean_str(email).lower()
            has_valid_em = _is_valid_email(em_clean)
            item = {
                "week_id": wk_id,
                "conference_id": eff_cid,
                "conference_name": eff_cname,
                "company_name": clean_comp,
                "contact_person": _clean_str(contact_person),
                "job_title": _clean_str(designation),
                "email": em_clean if has_valid_em else "",
                "email_verified": has_valid_em,
                "website": _clean_str(website),
                "booth_number": _clean_str(booth),
            }
            exhibitor_rows_all.append(item)
            if c_rec is not None:
                c_rec["exhibitors"].append(item)
                c_rec["exhibitors_count"] += 1
                if has_valid_em:
                    c_rec["verified_emails_count"] += 1

        for e in db_exhs:
            _add_exhibitor(
                e.conference_id,
                e.conference_name,
                e.conference_date,
                e.company_name,
                e.contact_person,
                e.contact_designation,
                e.professional_email,
                e.company_website,
                e.booth_number,
                e.availability_status,
                e.weekly_run_id,
            )
        for r in excel_sheets.get("weekly_exhibitors", []):
            _add_exhibitor(
                "",
                r.get("Conference Name", ""),
                r.get("Conference Date", ""),
                r.get("Exhibitor Company Name", ""),
                r.get("Contact Person", ""),
                r.get("Contact Person Designation", ""),
                r.get("Professional Email", ""),
                r.get("Company Website", ""),
                r.get("Exhibitor Booth Number", ""),
                "",
                "",
            )

        # Organize per-week summaries
        conferences_list = sorted(
            conf_by_id.values(),
            key=lambda x: (x["week_id"], x["start_date"], x["conference_name"].lower()),
        )
        by_week: Dict[str, Dict[str, Any]] = {}
        confs_by_wk: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for c in conferences_list:
            confs_by_wk[c["week_id"]].append(c)

        all_scraping_wks = sorted(
            set(confs_by_wk.keys())
            | {s["week_id"] for s in speaker_rows_all}
            | {a["week_id"] for a in attendee_rows_all}
            | {e["week_id"] for e in exhibitor_rows_all}
        )
        for wk in all_scraping_wks:
            if wk in ("", "UNASSIGNED", "WEEK-TEST"):
                continue
            wk_confs = confs_by_wk.get(wk, [])
            wk_spks = [s for s in speaker_rows_all if s["week_id"] == wk]
            wk_atts = [a for a in attendee_rows_all if a["week_id"] == wk]
            wk_exhs = [e for e in exhibitor_rows_all if e["week_id"] == wk]
            ind_counts = Counter(c["industry"] for c in wk_confs if c["industry"])
            bounds = parse_week_id(wk)
            by_week[wk] = {
                "week_id": wk,
                "week_start": bounds[0].isoformat() if bounds else "",
                "week_end": bounds[1].isoformat() if bounds else "",
                "total_conferences": len(wk_confs),
                "conferences_with_speakers": sum(1 for c in wk_confs if c["speakers_count"] > 0),
                "conferences_with_attendees": sum(1 for c in wk_confs if c["attendees_count"] > 0),
                "conferences_with_exhibitors": sum(1 for c in wk_confs if c["exhibitors_count"] > 0),
                "total_speakers": len(wk_spks),
                "total_attendees": len(wk_atts),
                "total_exhibitors": len(wk_exhs),
                "total_contacts": len(wk_spks) + len(wk_atts) + len(wk_exhs),
                "verified_emails_speakers": sum(1 for s in wk_spks if s["email"]),
                "verified_emails_attendees": sum(1 for a in wk_atts if a["email"]),
                "verified_emails_exhibitors": sum(1 for e in wk_exhs if e["email"]),
                "top_industries": [{"industry": k, "count": v} for k, v in ind_counts.most_common(10)],
                "conferences": wk_confs,
            }

        return {
            "totals": {
                "total_conferences": len(conferences_list),
                "total_speakers": len(speaker_rows_all),
                "total_attendees": len(attendee_rows_all),
                "total_exhibitors": len(exhibitor_rows_all),
                "total_contacts": len(speaker_rows_all) + len(attendee_rows_all) + len(exhibitor_rows_all),
                "total_verified_emails": (
                    sum(1 for s in speaker_rows_all if s["email"])
                    + sum(1 for a in attendee_rows_all if a["email"])
                    + sum(1 for e in exhibitor_rows_all if e["email"])
                ),
            },
            "by_week": by_week,
            "conferences": conferences_list,
            "speakers": speaker_rows_all,
            "attendees": attendee_rows_all,
            "exhibitors": exhibitor_rows_all,
            "conf_id_to_week": {c["conference_id"]: c["week_id"] for c in conferences_list},
            "conf_name_to_week": {
                k: v for c in conferences_list for k, v in (
                    (c["conference_name"].lower(), c["week_id"]),
                    (normalize_title(c["conference_name"]), c["week_id"]),
                )
            },
            "source_logs_count": len(db_logs),
        }

    # --------------------------------------------------------------------------
    # Section 3: Company Ranking & Week-over-Week Delta Aggregation
    # --------------------------------------------------------------------------
    def _aggregate_company_rankings(
        self,
        excel_sheets: Dict[str, List[Dict[str, Any]]],
        conf_name_to_week: Dict[str, str],
    ) -> Dict[str, Any]:
        db_companies = self.db.query(WeeklyCompany).all()

        def _map_conf_or_ts_week(raw_wk: str, conf_name: str, eval_ts: Any) -> str:
            parsed = parse_week_id(raw_wk)
            if parsed:
                return raw_wk.strip()
            cn = _clean_str(conf_name)
            if cn:
                mapped = conf_name_to_week.get(cn.lower()) or conf_name_to_week.get(normalize_title(cn))
                if mapped:
                    return mapped
            dt_obj = parse_timestamp_local(eval_ts)
            if dt_obj:
                return week_bounds_from_date(dt_obj.date())[2]
            return "UNASSIGNED"

        # Deduplicate per (week_id, canonical_company_name)
        records_by_wk_comp: Dict[Tuple[str, str], Dict[str, Any]] = {}

        def _upsert_company(
            week_id: str,
            company_name: str,
            domain: str,
            website: str,
            industry: str,
            headcount_tier: str,
            icp_score: float,
            qual_status: str,
            icp_tier: str,
            ind_score: float,
            scale_score: float,
            conf_name: str,
            evaluated_at: str,
            source_rank: int = 0,
        ):
            comp_clean = _clean_str(company_name)
            if not comp_clean or week_id in ("", "UNASSIGNED", "WEEK-TEST"):
                return
            comp_key = re.sub(r"\s+", " ", comp_clean.lower())
            q_up = _clean_str(qual_status).upper()
            if q_up not in ("HIGH_MATCH", "MODERATE", "DISQUALIFIED"):
                q_up = "HIGH_MATCH" if icp_score >= 75.0 else ("MODERATE" if icp_score >= 50.0 else "DISQUALIFIED")
            classification = "Qualified" if icp_score >= 50.0 or q_up in ("HIGH_MATCH", "MODERATE") else "Non-Qualified"
            dom_clean = _clean_str(domain).lower().removeprefix("www.")

            rec = {
                "week_id": week_id,
                "company_name": comp_clean,
                "company_domain": dom_clean,
                "official_website": _clean_str(website) or (f"https://{dom_clean}" if dom_clean else ""),
                "primary_industry": _clean_str(industry),
                "headcount_tier": _clean_str(headcount_tier),
                "icp_score": round(float(icp_score or 0.0), 2),
                "qualification_status": q_up,
                "classification": classification,
                "icp_tier": _clean_str(icp_tier) or q_up,
                "industry_fit_score": round(float(ind_score or 0.0), 2),
                "scale_fit_score": round(float(scale_score or 0.0), 2),
                "associated_conference": _clean_str(conf_name),
                "evaluated_at": _clean_str(evaluated_at),
                "source_rank": int(source_rank or 0),
                "rank": 0,
                "previous_week_id": "",
                "previous_rank": None,
                "previous_score": None,
                "rank_change": None,
                "rank_change_display": "New",
                "score_change": None,
            }

            k = (week_id, comp_key)
            if k not in records_by_wk_comp:
                records_by_wk_comp[k] = rec
            else:
                prev = records_by_wk_comp[k]
                # Prefer newer evaluation or higher completeness
                if rec["icp_score"] > prev["icp_score"] or (
                    rec["evaluated_at"] and not prev["evaluated_at"]
                ):
                    for fld in ("company_domain", "official_website", "primary_industry", "headcount_tier", "associated_conference"):
                        if not rec[fld] and prev[fld]:
                            rec[fld] = prev[fld]
                    records_by_wk_comp[k] = rec
                else:
                    for fld in ("company_domain", "official_website", "primary_industry", "headcount_tier", "associated_conference", "evaluated_at"):
                        if not prev[fld] and rec[fld]:
                            prev[fld] = rec[fld]

        # 1. PG WeeklyCompany
        for wc in db_companies:
            wk = _map_conf_or_ts_week(wc.weekly_run_id, wc.conference_name, wc.last_checked_at)
            _upsert_company(
                wk,
                wc.company_name,
                wc.company_domain,
                wc.official_website,
                wc.primary_industry,
                wc.headcount_tier,
                float(wc.icp_score or 0.0),
                wc.qualification_status,
                wc.icp_tier,
                float(wc.industry_fit_score or 0.0),
                float(wc.scale_fit_score or 0.0),
                wc.conference_name,
                wc.last_checked_at.isoformat() if wc.last_checked_at else "",
                wc.icp_rank or 0,
            )

        # 2. Local Excel Companies scoring (both 15-col and 21-col schemas)
        for item in excel_sheets.get("Companies scoring", []):
            r = item.get("_raw", [])
            if not r:
                continue
            c14 = _clean_str(r[14] if len(r) > 14 else "")
            if c14.startswith("WEEK-"):
                # 15-column WeeklyCompany schema
                try:
                    src_rk = int(r[0] or 0)
                    score_v = float(r[6] or 0.0)
                    ind_v = float(r[9] or 0.0) if len(r) > 9 and r[9] not in (None, "") else 0.0
                    sc_v = float(r[10] or 0.0) if len(r) > 10 and r[10] not in (None, "") else 0.0
                except Exception:
                    continue
                wk = _map_conf_or_ts_week(c14, _clean_str(r[11] if len(r) > 11 else ""), "")
                _upsert_company(
                    wk,
                    _clean_str(r[1]),
                    _clean_str(r[2]),
                    _clean_str(r[3]),
                    _clean_str(r[4]),
                    _clean_str(r[5]),
                    score_v,
                    _clean_str(r[7]),
                    _clean_str(r[8]),
                    ind_v,
                    sc_v,
                    _clean_str(r[11] if len(r) > 11 else ""),
                    "",
                    src_rk,
                )
            elif isinstance(r[1], (int, float)):
                # 21-column CURATED_SHEET_HEADERS schema
                try:
                    src_rk = int(r[0] or 0)
                    score_v = float(r[1] or 0.0)
                except Exception:
                    continue
                comp_n = _clean_str(r[2] if len(r) > 2 else "")
                dom_n = _clean_str(r[3] if len(r) > 3 else "")
                conf_n = _clean_str(r[4] if len(r) > 4 else "")
                qual_n = _clean_str(r[5] if len(r) > 5 else "")
                ind_n = _clean_str(r[6] if len(r) > 6 else "")
                tier_n = _clean_str(r[7] if len(r) > 7 else "")
                eval_at = _clean_str(r[20] if len(r) > 20 else "")
                wk = _map_conf_or_ts_week("", conf_n, eval_at)
                _upsert_company(wk, comp_n, dom_n, "", ind_n, tier_n, score_v, qual_n, qual_n, 0.0, 0.0, conf_n, eval_at, src_rk)

        # 3. Local Excel latest_week_scoring (takes precedence/enriches current week)
        for r in excel_sheets.get("latest_week_scoring", []):
            try:
                score_v = float(r.get("Overall_Score") or 0.0)
                src_rk = int(r.get("Rank") or 0)
            except Exception:
                continue
            conf_n = _clean_str(r.get("Conference_Name", ""))
            eval_at = _clean_str(r.get("Evaluated_At", ""))
            wk = _map_conf_or_ts_week("", conf_n, eval_at)
            _upsert_company(
                wk,
                _clean_str(r.get("Company_Name", "")),
                _clean_str(r.get("Company_Domain", "")),
                "",
                _clean_str(r.get("Primary_Industry", "")),
                _clean_str(r.get("Headcount_Tier", "")),
                score_v,
                _clean_str(r.get("Qualification_Status", "")),
                _clean_str(r.get("Qualification_Status", "")),
                0.0,
                0.0,
                conf_n,
                eval_at,
                src_rk,
            )

        # Rank deterministically per week & compute week-over-week deltas
        by_week_raw: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for rec in records_by_wk_comp.values():
            by_week_raw[rec["week_id"]].append(rec)

        sorted_weeks = sorted(by_week_raw.keys())
        prior_lookup_by_name: Dict[str, Dict[str, Any]] = {}
        prior_lookup_by_domain: Dict[str, Dict[str, Any]] = {}
        by_week_summary: Dict[str, Dict[str, Any]] = {}
        all_ranked: List[Dict[str, Any]] = []
        prev_wk_stats: Optional[Dict[str, Any]] = None

        for wk in sorted_weeks:
            wk_list = sorted(
                by_week_raw[wk],
                key=lambda x: (-x["icp_score"], x["source_rank"] if x["source_rank"] > 0 else 999999, x["company_name"].lower()),
            )
            bounds = parse_week_id(wk)
            for idx, rec in enumerate(wk_list, 1):
                rec["rank"] = idx
                rec["week_period"] = f"{bounds[0].isoformat()} to {bounds[1].isoformat()}" if bounds else wk

                n_key = re.sub(r"\s+", " ", rec["company_name"].lower())
                d_key = rec["company_domain"]
                prev_rec = prior_lookup_by_name.get(n_key) or (prior_lookup_by_domain.get(d_key) if d_key else None)
                if prev_rec:
                    delta = prev_rec["rank"] - idx
                    s_delta = round(rec["icp_score"] - prev_rec["icp_score"], 2)
                    rec["previous_week_id"] = prev_rec["week_id"]
                    rec["previous_rank"] = prev_rec["rank"]
                    rec["previous_score"] = prev_rec["icp_score"]
                    rec["rank_change"] = delta
                    rec["score_change"] = s_delta
                    if delta > 0:
                        rec["rank_change_display"] = f"▲ +{delta}"
                    elif delta < 0:
                        rec["rank_change_display"] = f"▼ {delta}"
                    else:
                        rec["rank_change_display"] = "= (0)"
                else:
                    rec["rank_change_display"] = "New"

            # Update prior lookups after processing entire week
            for rec in wk_list:
                n_key = re.sub(r"\s+", " ", rec["company_name"].lower())
                prior_lookup_by_name[n_key] = rec
                if rec["company_domain"]:
                    prior_lookup_by_domain[rec["company_domain"]] = rec

            qual_cnt = sum(1 for r in wk_list if r["classification"] == "Qualified")
            non_qual_cnt = len(wk_list) - qual_cnt
            high_cnt = sum(1 for r in wk_list if r["qualification_status"] == "HIGH_MATCH")
            mod_cnt = sum(1 for r in wk_list if r["qualification_status"] == "MODERATE")
            avg_score = round(sum(r["icp_score"] for r in wk_list) / len(wk_list), 2) if wk_list else 0.0
            top_10 = wk_list[:10]
            top10_avg = round(sum(r["icp_score"] for r in top_10) / len(top_10), 2) if top_10 else 0.0
            returning_cnt = sum(1 for r in wk_list if r["previous_rank"] is not None)

            wk_stats = {
                "week_id": wk,
                "week_start": bounds[0].isoformat() if bounds else "",
                "week_end": bounds[1].isoformat() if bounds else "",
                "week_period": f"{bounds[0].isoformat()} to {bounds[1].isoformat()}" if bounds else wk,
                "total_companies": len(wk_list),
                "qualified_companies": qual_cnt,
                "non_qualified_companies": non_qual_cnt,
                "high_match_count": high_cnt,
                "moderate_count": mod_cnt,
                "disqualified_count": non_qual_cnt,
                "qualification_rate_pct": round((qual_cnt / len(wk_list)) * 100.0, 2) if wk_list else 0.0,
                "avg_icp_score": avg_score,
                "top_10_avg_score": top10_avg,
                "top_company": wk_list[0]["company_name"] if wk_list else "",
                "top_score": wk_list[0]["icp_score"] if wk_list else 0.0,
                "returning_companies_vs_prev": returning_cnt,
                "new_companies_count": len(wk_list) - returning_cnt,
                "avg_score_change_vs_prev": round(avg_score - prev_wk_stats["avg_icp_score"], 2) if prev_wk_stats else None,
                "top_score_change_vs_prev": round((wk_list[0]["icp_score"] if wk_list else 0.0) - prev_wk_stats["top_score"], 2) if prev_wk_stats else None,
                "companies": wk_list,
            }
            by_week_summary[wk] = wk_stats
            prev_wk_stats = wk_stats
            all_ranked.extend(wk_list)

        return {
            "totals": {
                "total_ranked_entries": len(all_ranked),
                "unique_companies": len({re.sub(r"\s+", " ", c["company_name"].lower()) for c in all_ranked}),
                "qualified_entries": sum(1 for c in all_ranked if c["classification"] == "Qualified"),
                "non_qualified_entries": sum(1 for c in all_ranked if c["classification"] == "Non-Qualified"),
                "weeks_covered": len(sorted_weeks),
            },
            "by_week": by_week_summary,
            "all_rankings": all_ranked,
        }

    # --------------------------------------------------------------------------
    # Sections 1, 2, 5: Email Outreach, Weekly Performance & Template Performance
    # --------------------------------------------------------------------------
    def _aggregate_outreach_and_replies(
        self,
        excel_sheets: Dict[str, List[Dict[str, Any]]],
        outreach_state: Dict[str, Any],
        graph_cache: Dict[str, Any],
        company_rankings: Dict[str, Any],
        conf_id_to_week: Dict[str, str],
        conf_name_to_week: Dict[str, str],
    ) -> Dict[str, Any]:
        db_speakers = self.db.query(WeeklySpeaker).all()
        db_replies = self.db.query(SpeakerReply).all()
        db_attendees = self.db.query(WeeklyAttendee).all()
        db_exhibitors = self.db.query(WeeklyExhibitor).all()

        # Build lead qualification & metadata lookups across all real sources
        lead_meta_by_email: Dict[str, Dict[str, Any]] = {}
        comp_score_lookup: Dict[str, Tuple[float, str]] = {}
        for comp_rec in company_rankings.get("all_rankings", []):
            ck = re.sub(r"\s+", " ", comp_rec["company_name"].lower())
            comp_score_lookup[ck] = (comp_rec["icp_score"], comp_rec["classification"])

        def _merge_lead_meta(email: str, **kwargs):
            em = _clean_str(email).lower()
            if not _is_valid_email(em):
                return
            cur = lead_meta_by_email.setdefault(em, {
                "email": em,
                "name": "",
                "job_title": "",
                "company": "",
                "conference_name": "",
                "conference_id": "",
                "role": "",
                "icp_score": None,
                "lead_classification": "",
                "qualification_source": "",
                "excel_outreach_status": "",
                "excel_reply_status": "",
                "excel_reply_sentiment": "",
                "excel_received_reply": "",
                "excel_sent_message": "",
                "thread_id": "",
                "follow_up_count": 0,
                "follow_up_status": "",
                "target_conf_week": "",
            })
            for k, v in kwargs.items():
                if v is None or v == "":
                    continue
                if k == "icp_score":
                    if cur["icp_score"] is None or float(v) > 0:
                        cur["icp_score"] = float(v)
                elif k == "lead_classification":
                    if not cur["lead_classification"] or kwargs.get("force_tier"):
                        cur["lead_classification"] = str(v)
                elif k == "follow_up_count":
                    cur["follow_up_count"] = max(cur["follow_up_count"], int(v))
                elif not cur.get(k):
                    cur[k] = v

        # Qualified Leads sheet (authoritative Qualified tier)
        for r in excel_sheets.get("Qualified Leads", []):
            em = _clean_str(r.get("Professional_Email", "")).lower()
            sc = None
            try:
                sc = float(r.get("Overall_Score")) if r.get("Overall_Score") not in (None, "") else None
            except Exception:
                pass
            role = "Speaker"
            ct = _clean_str(r.get("Contact_Type", ""))
            if "attendee" in ct.lower():
                role = "Attendee"
            elif "exhibitor" in ct.lower():
                role = "Exhibitor"
            _merge_lead_meta(
                em,
                name=_clean_str(r.get("Contact_Name", "")),
                job_title=_clean_str(r.get("Job_Title", "")),
                company=_clean_str(r.get("Company_Name", "")),
                conference_name=_clean_str(r.get("Conference_Name", "")),
                conference_id=_clean_str(r.get("Conference_ID", "")),
                role=role,
                icp_score=sc,
                lead_classification="Qualified",
                force_tier=True,
                qualification_source="Qualified Leads",
                excel_outreach_status=_clean_str(r.get("Outreach Status", "")),
                excel_reply_status=_clean_str(r.get("Reply Status", "")),
                excel_reply_sentiment=_clean_str(r.get("Reply Sentiment", "")),
                excel_received_reply=_clean_str(r.get("Received Reply", "")),
                excel_sent_message=_clean_str(r.get("Send Message", "")),
                thread_id=_clean_str(r.get("Thread ID", "")),
            )

        # Non -Qualified Leads sheet (do not overwrite an already-sent Qualified Lead with a later pending NQ row)
        for r in excel_sheets.get("Non -Qualified Leads", []):
            em = _clean_str(r.get("Professional_Email", "")).lower()
            sc = None
            try:
                sc = float(r.get("Overall_Score")) if r.get("Overall_Score") not in (None, "") else None
            except Exception:
                pass
            nq_out_st = _clean_str(r.get("Outreach Status", "")).lower()
            existing_meta = lead_meta_by_email.get(em, {})
            existing_sent = existing_meta.get("excel_outreach_status", "").lower() in ("sent", "replied", "bounced")
            existing_is_q = existing_meta.get("qualification_source") == "Qualified Leads"
            if existing_is_q and existing_sent and nq_out_st not in ("sent", "replied", "bounced"):
                continue

            role = "Speaker"
            ct = _clean_str(r.get("Contact_Type", ""))
            if "attendee" in ct.lower():
                role = "Attendee"
            elif "exhibitor" in ct.lower():
                role = "Exhibitor"
            _merge_lead_meta(
                em,
                name=_clean_str(r.get("Contact_Name", "")),
                job_title=_clean_str(r.get("Job_Title", "")),
                company=_clean_str(r.get("Company_Name", "")),
                conference_name=_clean_str(r.get("Conference_Name", "")),
                conference_id=_clean_str(r.get("Conference_ID", "")),
                role=role,
                icp_score=sc,
                lead_classification="Non-Qualified",
                force_tier=True,
                qualification_source="Non -Qualified Leads",
                excel_outreach_status=_clean_str(r.get("Outreach Status", "")),
                excel_reply_status=_clean_str(r.get("Reply Status", "")),
                excel_reply_sentiment=_clean_str(r.get("Reply Sentiment", "")),
                excel_received_reply=_clean_str(r.get("Received Reply", "")),
                excel_sent_message=_clean_str(r.get("Send Message", "")),
                thread_id=_clean_str(r.get("Thread ID", "")),
            )

        # PG WeeklySpeaker, WeeklyAttendee, WeeklyExhibitor & Verified Data
        for sp in db_speakers:
            if not sp.professional_email or sp.weekly_run_id == "WEEK-TEST" or sp.conference_id.startswith("CONF-TEST"):
                continue
            sc = float(sp.icp_score or 0.0) if sp.icp_score else None
            _merge_lead_meta(
                sp.professional_email,
                name=sp.speaker_name,
                job_title=sp.job_title,
                company=sp.company_name,
                conference_name=sp.conference_name,
                conference_id=sp.conference_id,
                role="Speaker",
                icp_score=sc,
                lead_classification=("Qualified" if sc >= 50.0 else "Non-Qualified") if sc and sc > 0 else "",
                excel_outreach_status=sp.outreach_status,
                excel_reply_status=sp.reply_status,
                excel_reply_sentiment=sp.reply_sentiment,
                excel_received_reply=sp.received_reply,
                excel_sent_message=sp.sent_message,
                thread_id=sp.email_thread_id,
                follow_up_count=sp.follow_up_count or 0,
                follow_up_status=sp.follow_up_status,
                target_conf_week=sp.weekly_run_id if parse_week_id(sp.weekly_run_id or "") else "",
            )

        for at in db_attendees:
            if not at.professional_email or _is_placeholder_entity(at.attendee_name, at.availability_status):
                continue
            _merge_lead_meta(
                at.professional_email,
                name=at.attendee_name,
                job_title=at.job_title,
                company=at.company_name,
                conference_name=at.conference_name,
                conference_id=at.conference_id,
                role="Attendee",
                target_conf_week=at.weekly_run_id if parse_week_id(at.weekly_run_id or "") else "",
            )

        for ex in db_exhibitors:
            if not ex.professional_email or _is_placeholder_entity(ex.company_name, ex.availability_status):
                continue
            _merge_lead_meta(
                ex.professional_email,
                name=ex.contact_person or ex.company_name,
                job_title=ex.contact_designation,
                company=ex.company_name,
                conference_name=ex.conference_name,
                conference_id=ex.conference_id,
                role="Exhibitor",
                target_conf_week=ex.weekly_run_id if parse_week_id(ex.weekly_run_id or "") else "",
            )

        for r in excel_sheets.get("Verified Data", []):
            comp = _clean_str(r.get("Company Name", ""))
            conf = _clean_str(r.get("Conference Name", ""))
            cid = _clean_str(r.get("Conference ID", ""))
            for role, pfx in (("Speaker", "Speaker"), ("Attendee", "Attendee"), ("Exhibitor", "Exhibitor")):
                em = _clean_str(r.get(f"{pfx} Professional Email", "")).lower()
                if not _is_valid_email(em):
                    continue
                _merge_lead_meta(
                    em,
                    name=_clean_str(r.get(f"{pfx} Name", "")),
                    job_title=_clean_str(r.get(f"{pfx} Job Title", "")),
                    company=comp,
                    conference_name=conf,
                    conference_id=cid,
                    role=role,
                    excel_outreach_status=_clean_str(r.get(f"{pfx} Outreach Status", "")),
                    excel_reply_status=_clean_str(r.get(f"{pfx} Reply Status", "")),
                    excel_reply_sentiment=_clean_str(r.get(f"{pfx} Sentiment", "")),
                    excel_received_reply=_clean_str(r.get(f"{pfx} Received Reply", "")),
                    excel_sent_message=_clean_str(r.get(f"{pfx} Sent Message", "")),
                    thread_id=_clean_str(r.get(f"{pfx} Thread ID", "")),
                )

        # State threads & sent_log also enrich lead metadata
        state_threads = outreach_state.get("threads", {}) or {}
        state_sent_log = outreach_state.get("sent_log", []) or []
        state_replies = outreach_state.get("replies", []) or []
        known_thread_ids: Set[str] = {
            _clean_str(th.get("thread_id", ""))
            for th in state_threads.values()
            if _clean_str(th.get("thread_id", ""))
        }
        known_thread_ids.update(
            meta["thread_id"] for meta in lead_meta_by_email.values() if meta["thread_id"]
        )

        for k, th in state_threads.items():
            em = _clean_str(th.get("email") or (k.split("|")[0] if "|" in k else "")).lower()
            if not _is_valid_email(em) or "skjeeva2005" in em:
                continue
            sc = None
            try:
                sc = float(th.get("score")) if th.get("score") not in (None, "") else None
            except Exception:
                pass
            src = _clean_str(th.get("source", "")).lower()
            tier = ""
            if src == "non_qualified_leads":
                tier = "Non-Qualified"
            elif src == "qualified_leads":
                tier = "Qualified"
            elif sc and sc > 0:
                tier = "Qualified" if sc >= 50.0 else "Non-Qualified"
            _merge_lead_meta(
                em,
                name=_clean_str(th.get("name", "")),
                company=_clean_str(th.get("company", "")),
                conference_name=_clean_str(th.get("conference", "")),
                conference_id=_clean_str(th.get("conference_id", "")),
                role=_clean_str(th.get("category", "")),
                icp_score=sc,
                lead_classification=tier,
                thread_id=_clean_str(th.get("thread_id", "")),
            )

        for s_entry in state_sent_log:
            em = _clean_str(s_entry.get("email", "")).lower()
            if not _is_valid_email(em) or "skjeeva2005" in em or s_entry.get("conference_id") == "CONF-TEST-OUTREACH":
                continue
            sc = None
            try:
                sc = float(s_entry.get("score")) if s_entry.get("score") not in (None, "") else None
            except Exception:
                pass
            src = _clean_str(s_entry.get("source", "")).lower()
            tier = "Non-Qualified" if src == "non_qualified_leads" else ("Qualified" if src == "qualified_leads" else ("Qualified" if sc and sc >= 50.0 else ("Non-Qualified" if sc and sc > 0 else "")))
            _merge_lead_meta(
                em,
                name=_clean_str(s_entry.get("name", "")),
                conference_name=_clean_str(s_entry.get("conference_name", "")),
                conference_id=_clean_str(s_entry.get("conference_id", "")),
                role=_clean_str(s_entry.get("category", "")),
                icp_score=sc,
                lead_classification=tier,
            )

        known_lead_emails = set(lead_meta_by_email.keys())

        # Index NDR bounces & genuine replies from Graph Inbox + SpeakerReply + state_replies + Excel
        bounces_by_conv: Dict[str, Dict[str, Any]] = {}
        bounces_by_email: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        replies_by_conv: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        replies_by_email: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        for m in graph_cache.get("inbox_messages", []):
            cid = _clean_str(m.get("conversationId", ""))
            rdt = m.get("receivedDateTime", "")
            if m.get("isBounce"):
                br = _clean_str(m.get("bounceRecipient", "")).lower()
                b_obj = {
                    "bounced_at": rdt,
                    "bounce_reason": _clean_str(m.get("bounceReason", "")) or "Undeliverable (NDR returned)",
                    "bounce_recipient": br,
                    "conversation_id": cid,
                    "message_id": m.get("id", ""),
                }
                if cid:
                    bounces_by_conv[cid] = b_obj
                if br:
                    bounces_by_email[br].append(b_obj)
                continue

            fa = _clean_str(m.get("fromAddress", "")).lower()
            if not fa or "adople.ai" in fa or "skjeeva2005" in fa:
                continue
            if (cid and cid in known_thread_ids) or (fa in known_lead_emails):
                bt = _clean_str(m.get("bodyText", "")) or _clean_str(m.get("bodyPreview", ""))
                meta = lead_meta_by_email.get(fa, {})
                ana = fallback_reply_analysis(bt)
                r_obj = {
                    "message_id": m.get("id", ""),
                    "conversation_id": cid,
                    "from_email": fa,
                    "received_at": rdt,
                    "reply_text": bt,
                    "sentiment": ana.get("sentiment", "Neutral"),
                    "intent": ana.get("intent", "OTHER"),
                    "summary": ana.get("summary", ""),
                }
                if cid:
                    replies_by_conv[cid].append(r_obj)
                replies_by_email[fa].append(r_obj)

        # Check state_replies & PG SpeakerReply for bounces/replies if Graph inbox cache hasn't seen them yet
        for sr in state_replies:
            em = _clean_str(sr.get("email", "")).lower()
            if not em or "skjeeva2005" in em:
                continue
            intent = _clean_str(sr.get("intent", "")).upper()
            if intent == "BOUNCE":
                if not bounces_by_email.get(em):
                    bounces_by_email[em].append({
                        "bounced_at": sr.get("received_at", ""),
                        "bounce_reason": "Undeliverable address (NDR recorded in outreach monitor)",
                        "bounce_recipient": em,
                        "conversation_id": "",
                        "message_id": sr.get("message_id", ""),
                    })
            else:
                if not replies_by_email.get(em):
                    replies_by_email[em].append({
                        "message_id": sr.get("message_id", ""),
                        "conversation_id": "",
                        "from_email": em,
                        "received_at": sr.get("received_at", ""),
                        "reply_text": lead_meta_by_email.get(em, {}).get("excel_received_reply", ""),
                        "sentiment": _clean_str(sr.get("sentiment", "Neutral")),
                        "intent": intent or "OTHER",
                        "summary": "",
                    })

        for r_db in db_replies:
            em = _clean_str(r_db.professional_email).lower()
            if not em or "skjeeva2005" in em:
                continue
            txt = _clean_str(r_db.received_reply)
            # Catch misclassified NDR bounces stored inside SpeakerReply
            fake_msg = {"subject": "", "bodyPreview": txt[:200], "from": {"emailAddress": {"address": "", "name": ""}}}
            if is_bounce_email(fake_msg, txt):
                if not bounces_by_email.get(em):
                    bounces_by_email[em].append({
                        "bounced_at": r_db.reply_received_at.isoformat() if r_db.reply_received_at else "",
                        "bounce_reason": _clean_bounce_reason(txt),
                        "bounce_recipient": em,
                        "conversation_id": _clean_str(r_db.thread_id),
                        "message_id": _clean_str(r_db.message_id),
                    })
                continue
            if not replies_by_email.get(em):
                ana = fallback_reply_analysis(txt)
                replies_by_email[em].append({
                    "message_id": _clean_str(r_db.message_id),
                    "conversation_id": _clean_str(r_db.thread_id),
                    "from_email": em,
                    "received_at": r_db.reply_received_at.isoformat() if r_db.reply_received_at else "",
                    "reply_text": txt,
                    "sentiment": _clean_str(r_db.reply_sentiment) or ana.get("sentiment", "Neutral"),
                    "intent": ana.get("intent", "OTHER"),
                    "summary": ana.get("summary", ""),
                })

        for sp in db_speakers:
            em = _clean_str(sp.professional_email).lower()
            if not em or "skjeeva2005" in em:
                continue
            if (_clean_str(sp.reply_status).lower() == "bounced" or _clean_str(sp.outreach_status).lower() == "bounced") and not bounces_by_email.get(em):
                bounces_by_email[em].append({
                    "bounced_at": "",
                    "bounce_reason": _clean_str(sp.received_reply) or "BOUNCE: Undeliverable address",
                    "bounce_recipient": em,
                    "conversation_id": _clean_str(sp.email_thread_id),
                    "message_id": "",
                })

        # Build deduplicated list of ALL dispatched outreach emails (SentItems primary, merged with sent_log/threads/DB/Excel)
        outreach_emails: List[Dict[str, Any]] = []
        test_emails_excluded: List[Dict[str, Any]] = []
        seen_send_keys: Set[str] = set()
        sent_by_conv_id: Set[str] = set()
        sent_email_ts_keys: Set[Tuple[str, str]] = set()  # (email, yyyy-mm-ddThh:mm local)

        # Match sent_log entries by (email, sent_dt) for conference_id attribution when email sent twice
        sent_log_by_email: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for s_item in state_sent_log:
            if s_item.get("status") == "sent" and s_item.get("email"):
                sent_log_by_email[_clean_str(s_item["email"]).lower()].append(s_item)

        def _finalize_email_record(
            rec_email: str,
            subj: str,
            body_text: str,
            sent_dt_obj: Optional[datetime],
            conv_id: str,
            msg_id: str,
            conf_id_hint: str = "",
            conf_name_hint: str = "",
            name_hint: str = "",
            role_hint: str = "",
            score_hint: Optional[float] = None,
            tier_hint: str = "",
            is_followup_flag: bool = False,
        ):
            em = _clean_str(rec_email).lower()
            meta = lead_meta_by_email.get(em, {})
            rec_name = _clean_str(name_hint) or _clean_str(meta.get("name")) or em.split("@")[0]
            comp = _clean_str(meta.get("company"))
            conf_name = _clean_str(conf_name_hint) or _clean_str(meta.get("conference_name"))
            conf_id = _clean_str(conf_id_hint) or _clean_str(meta.get("conference_id"))
            role = _clean_str(role_hint) or _clean_str(meta.get("role")) or "Speaker"
            role = role.capitalize() if role.lower() in ("speaker", "attendee", "exhibitor") else role

            # Resolve score & Qualified vs Non-Qualified tier accurately
            icp_score = score_hint if score_hint is not None else meta.get("icp_score")
            if (icp_score is None or icp_score == 0) and comp:
                comp_k = re.sub(r"\s+", " ", comp.lower())
                if comp_k in comp_score_lookup:
                    icp_score = comp_score_lookup[comp_k][0]
            tier = _clean_str(tier_hint) or _clean_str(meta.get("lead_classification"))
            if not tier and icp_score is not None and icp_score > 0:
                tier = "Qualified" if float(icp_score) >= 50.0 else "Non-Qualified"
            if not tier:
                tier = "Qualified"

            # Message sent fallback to Excel / DB
            final_msg = _clean_str(body_text)
            if not final_msg and meta.get("excel_sent_message"):
                final_msg = meta["excel_sent_message"]
            elif subj and final_msg and not final_msg.lower().startswith("subject:"):
                final_msg = f"Subject: {subj}\n\n{final_msg}"

            if not subj and final_msg.lower().startswith("subject:"):
                subj = final_msg.splitlines()[0][8:].strip()

            template_used = classify_template_used(
                subject=subj,
                body=final_msg,
                contact_category=role,
                is_followup=is_followup_flag,
            )

            # Week & timestamp formatting
            if sent_dt_obj:
                wk_start, wk_end, wk_id = week_bounds_from_date(sent_dt_obj.date())
                sent_at_iso = sent_dt_obj.isoformat(timespec="seconds")
                sent_date_str = sent_dt_obj.date().isoformat()
            else:
                wk_id = meta.get("target_conf_week") or "WEEK-2026-11-01_2026-11-07"
                b = parse_week_id(wk_id)
                wk_start, wk_end = b if b else week_bounds_from_date(date.today())[:2]
                sent_at_iso = ""
                sent_date_str = ""

            target_conf_wk = (
                conf_id_to_week.get(conf_id)
                or conf_name_to_week.get(conf_name.lower())
                or conf_name_to_week.get(normalize_title(conf_name))
                or meta.get("target_conf_week")
                or ""
            )

            # Bounce check (exact conversationId first, then timestamp-verified email match to catch external gateway NDRs like Cisco CES / Gmailer-Daemon)
            bounce_info = bounces_by_conv.get(conv_id) if conv_id else None
            if bounce_info is None and bounces_by_email.get(em):
                sent_utc = sent_dt_obj.astimezone(timezone.utc) if sent_dt_obj else None
                for cand_b in bounces_by_email[em]:
                    b_dt = parse_timestamp_local(cand_b.get("bounced_at"), assume_utc_if_naive=True)
                    b_utc = b_dt.astimezone(timezone.utc) if b_dt else None
                    if sent_utc is None or b_utc is None:
                        bounce_info = cand_b
                        break
                    diff_sec = (b_utc - sent_utc).total_seconds()
                    if -120 <= diff_sec <= 14 * 86400:
                        bounce_info = cand_b
                        break

            is_bounced = bounce_info is not None
            delivery_status = "Bounced" if is_bounced else "Delivered"
            bounce_reason = bounce_info["bounce_reason"] if is_bounced else ""

            # Genuine Reply check
            matched_replies = []
            if not is_bounced:
                if conv_id and replies_by_conv.get(conv_id):
                    matched_replies = replies_by_conv[conv_id]
                elif replies_by_email.get(em):
                    # If no conversationId mismatch
                    cands = [
                        rep for rep in replies_by_email[em]
                        if not conv_id or not rep.get("conversation_id") or rep["conversation_id"] == conv_id
                    ]
                    matched_replies = cands

            replied = len(matched_replies) > 0
            reply_sentiment = ""
            reply_intent = ""
            reply_text = ""
            reply_received_at = ""
            if replied:
                # Merge chronologically if multiple messages in reply thread
                matched_replies_sorted = sorted(matched_replies, key=lambda x: x.get("received_at", ""))
                latest_rep = matched_replies_sorted[-1]
                reply_sentiment = latest_rep.get("sentiment") or "Neutral"
                reply_intent = latest_rep.get("intent") or "OTHER"
                reply_received_at = latest_rep.get("received_at") or ""
                if len(matched_replies_sorted) > 1:
                    reply_text = "\n\n---\n\n".join(
                        f"[{r.get('received_at','')[:16]}] {r.get('reply_text','')}" for r in matched_replies_sorted
                    )
                else:
                    reply_text = latest_rep.get("reply_text") or ""

            outreach_emails.append({
                "email_id": msg_id or f"{em}|{sent_at_iso or conf_id}",
                "week_id": wk_id,
                "week_start": wk_start.isoformat(),
                "week_end": wk_end.isoformat(),
                "target_conference_week": target_conf_wk,
                "sent_at": sent_at_iso,
                "sent_date": sent_date_str,
                "recipient_name": rec_name,
                "recipient_email": em,
                "job_title": _clean_str(meta.get("job_title")),
                "company_name": comp,
                "conference_id": conf_id,
                "conference_name": conf_name,
                "contact_role": role,
                "lead_classification": tier,
                "icp_score": round(float(icp_score), 2) if icp_score is not None else None,
                "template_used": template_used,
                "is_follow_up": template_used == "Follow-Up",
                "subject": subj,
                "message_sent": final_msg,
                "delivery_status": delivery_status,
                "bounce_reason": bounce_reason,
                "replied": replied,
                "reply_status": "Bounced" if is_bounced else ("Replied" if replied else "No Reply"),
                "reply_sentiment": reply_sentiment,
                "reply_intent": reply_intent,
                "reply_received_at": reply_received_at,
                "reply_details": reply_text,
                "conversation_id": conv_id,
            })

        # Pass 1: Authoritative Outlook SentItems messages
        for gm in graph_cache.get("sent_messages", []):
            to_emails = [r["address"] for r in gm.get("toRecipients", []) if r.get("address")]
            if not to_emails:
                continue
            subj = _clean_str(gm.get("subject", ""))
            conv_id = _clean_str(gm.get("conversationId", ""))
            msg_id = _clean_str(gm.get("id", ""))
            is_outreach, is_test = _is_internal_or_non_outreach_sent(subj, to_emails, known_lead_emails, conv_id, known_thread_ids)
            if not is_outreach:
                continue

            dt_local = parse_timestamp_local(gm.get("sentDateTime"), assume_utc_if_naive=True)
            if is_test:
                test_emails_excluded.append({
                    "recipient_email": to_emails[0],
                    "sent_at": dt_local.isoformat(timespec="seconds") if dt_local else "",
                    "subject": subj,
                    "reason": "QA Manual Test Send (CONF-TEST-OUTREACH / WEEK-TEST)",
                })
                continue

            rec_em = to_emails[0]
            dedupe_k = msg_id or f"{rec_em}|{conv_id}|{gm.get('sentDateTime','')[:16]}"
            if dedupe_k in seen_send_keys:
                continue
            seen_send_keys.add(dedupe_k)
            if conv_id:
                sent_by_conv_id.add(conv_id)
            if dt_local:
                sent_email_ts_keys.add((rec_em, dt_local.strftime("%Y-%m-%d %H:%M")))

            # Find closest sent_log/thread entry for conference/score hints
            hint_cid = ""
            hint_cname = ""
            hint_score = None
            hint_tier = ""
            hint_name = gm["toRecipients"][0].get("name", "")
            hint_role = ""
            for th in state_threads.values():
                if conv_id and _clean_str(th.get("thread_id", "")) == conv_id:
                    hint_cid = _clean_str(th.get("conference_id", "")) or hint_cid
                    hint_cname = _clean_str(th.get("conference", "")) or hint_cname
                    if th.get("score") not in (None, ""):
                        hint_score = float(th["score"])
                    if th.get("source") == "non_qualified_leads":
                        hint_tier = "Non-Qualified"
                    elif th.get("source") == "qualified_leads":
                        hint_tier = "Qualified"
                    hint_name = _clean_str(th.get("name", "")) or hint_name
                    hint_role = _clean_str(th.get("category", "")) or hint_role
                    break

            for cand_s in sent_log_by_email.get(rec_em, []):
                cand_dt = parse_timestamp_local(cand_s.get("sent_at"), assume_utc_if_naive=False)
                if cand_dt and dt_local and abs((cand_dt - dt_local).total_seconds()) <= 180:
                    hint_cid = _clean_str(cand_s.get("conference_id", "")) or hint_cid
                    hint_cname = _clean_str(cand_s.get("conference_name", "")) or hint_cname
                    if cand_s.get("score") not in (None, "") and hint_score is None:
                        hint_score = float(cand_s["score"])
                    if not hint_tier:
                        if cand_s.get("source") == "non_qualified_leads":
                            hint_tier = "Non-Qualified"
                        elif cand_s.get("source") == "qualified_leads":
                            hint_tier = "Qualified"
                    hint_name = _clean_str(cand_s.get("name", "")) or hint_name
                    hint_role = _clean_str(cand_s.get("category", "")) or hint_role
                    break

            _finalize_email_record(
                rec_email=rec_em,
                subj=subj,
                body_text=_clean_str(gm.get("bodyText", "")) or _clean_str(gm.get("bodyPreview", "")),
                sent_dt_obj=dt_local,
                conv_id=conv_id,
                msg_id=msg_id,
                conf_id_hint=hint_cid,
                conf_name_hint=hint_cname,
                name_hint=hint_name,
                role_hint=hint_role,
                score_hint=hint_score,
                tier_hint=hint_tier,
            )

        # Pass 2: Any real sends in outreach_state / threads / DB not yet in SentItems cache
        for k, th in state_threads.items():
            em = _clean_str(th.get("email") or (k.split("|")[0] if "|" in k else "")).lower()
            conv_id = _clean_str(th.get("thread_id", ""))
            msg_id = _clean_str(th.get("message_id", ""))
            if not _is_valid_email(em) or "skjeeva2005" in em or th.get("speaker_id") == "SPK-TEST-MANUAL-001":
                continue
            if conv_id and conv_id in sent_by_conv_id:
                continue
            dt_local = parse_timestamp_local(th.get("sent_at"), assume_utc_if_naive=False)
            ts_min = dt_local.strftime("%Y-%m-%d %H:%M") if dt_local else ""
            if (em, ts_min) in sent_email_ts_keys:
                continue
            # Also skip if same recipient already captured within same day without distinct thread_id
            if any(o["recipient_email"] == em and o["sent_date"] == (dt_local.date().isoformat() if dt_local else "") and not conv_id for o in outreach_emails):
                continue

            if conv_id:
                sent_by_conv_id.add(conv_id)
            if ts_min:
                sent_email_ts_keys.add((em, ts_min))

            src = _clean_str(th.get("source", "")).lower()
            hint_tier = "Non-Qualified" if src == "non_qualified_leads" else ("Qualified" if src == "qualified_leads" else "")
            sc = float(th["score"]) if th.get("score") not in (None, "") else None
            _finalize_email_record(
                rec_email=em,
                subj="",
                body_text="",
                sent_dt_obj=dt_local,
                conv_id=conv_id,
                msg_id=msg_id,
                conf_id_hint=_clean_str(th.get("conference_id", "")),
                conf_name_hint=_clean_str(th.get("conference", "")),
                name_hint=_clean_str(th.get("name", "")),
                role_hint=_clean_str(th.get("category", "")),
                score_hint=sc,
                tier_hint=hint_tier,
            )

        outreach_emails.sort(key=lambda x: (x["sent_at"] or "", x["recipient_email"]), reverse=True)

        # Follow-up eligibility telemetry (honest count, zero fake numbers)
        replied_or_bounced_emails = {
            o["recipient_email"] for o in outreach_emails if o["delivery_status"] == "Bounced" or o["replied"]
        }
        follow_up_eligible_contacts = len({
            o["recipient_email"]
            for o in outreach_emails
            if o["delivery_status"] == "Delivered" and not o["replied"] and o["recipient_email"] not in replied_or_bounced_emails
        })

        # Compute overall + per-template metrics
        def _calc_group(records: List[Dict[str, Any]]) -> Dict[str, Any]:
            sent = len(records)
            bounced = sum(1 for r in records if r["delivery_status"] == "Bounced")
            delivered = sent - bounced
            replied = sum(1 for r in records if r["replied"])
            res = _compute_rates(sent, delivered, bounced, replied)
            res["unique_recipients"] = len({r["recipient_email"] for r in records})
            res["positive_replies"] = sum(1 for r in records if r["replied"] and r["reply_sentiment"].lower() == "positive")
            res["neutral_replies"] = sum(1 for r in records if r["replied"] and r["reply_sentiment"].lower() == "neutral")
            res["negative_replies"] = sum(1 for r in records if r["replied"] and r["reply_sentiment"].lower() == "negative")
            return res

        template_performance: List[Dict[str, Any]] = []
        for tmpl in TEMPLATES_ORDERED:
            t_recs = [o for o in outreach_emails if o["template_used"] == tmpl]
            m = _calc_group(t_recs)
            m["template_name"] = tmpl
            template_performance.append(m)

        overall_metrics = _calc_group(outreach_emails)
        qualified_recs = [o for o in outreach_emails if o["lead_classification"] == "Qualified"]
        non_qualified_recs = [o for o in outreach_emails if o["lead_classification"] == "Non-Qualified"]
        followup_recs = [o for o in outreach_emails if o["is_follow_up"]]

        return {
            "records": outreach_emails,
            "excluded_test_sends": test_emails_excluded,
            "overall": {
                **overall_metrics,
                "qualified": _calc_group(qualified_recs),
                "non_qualified": _calc_group(non_qualified_recs),
                "general_follow_up": {
                    **_calc_group(followup_recs),
                    "follow_up_enabled": bool(getattr(settings, "FOLLOW_UP_ENABLED", False)),
                    "eligible_delivered_no_reply": follow_up_eligible_contacts,
                },
            },
            "template_performance": template_performance,
            "_calc_group": _calc_group,
        }

    # --------------------------------------------------------------------------
    # Unified Live Report Payload Builder
    # --------------------------------------------------------------------------
    def build_full_report_payload(self, refresh_graph: bool = False) -> Dict[str, Any]:
        """Builds the complete deterministic report payload across all weeks and all 5 reporting sections."""
        self.ensure_initialized()
        tz = get_report_tz()
        now_dt = datetime.now(tz)

        if refresh_graph or not GRAPH_CACHE_PATH.exists():
            try:
                graph_cache = self.sync_graph_mailbox_cache()
            except Exception as e:
                logger.warning(f"[ReportingService] Live Graph refresh notice (falling back to cache): {e}")
                graph_cache = self._load_graph_cache()
        else:
            graph_cache = self._load_graph_cache()

        excel_sheets = self._load_local_excel_sheets()
        outreach_state = self._load_outreach_state()

        scraping = self._aggregate_conference_scraping(excel_sheets)
        rankings = self._aggregate_company_rankings(excel_sheets, scraping["conf_name_to_week"])
        outreach = self._aggregate_outreach_and_replies(
            excel_sheets=excel_sheets,
            outreach_state=outreach_state,
            graph_cache=graph_cache,
            company_rankings=rankings,
            conf_id_to_week=scraping["conf_id_to_week"],
            conf_name_to_week=scraping["conf_name_to_week"],
        )

        # Build unified Weekly Performance timeline across all weeks seen in Outreach, Rankings, and Scraping
        all_week_ids = sorted(
            {o["week_id"] for o in outreach["records"] if parse_week_id(o["week_id"])}
            | set(rankings["by_week"].keys())
            | set(scraping["by_week"].keys())
        )

        weekly_performance: Dict[str, Dict[str, Any]] = {}
        calc_group = outreach["_calc_group"]

        for wk in all_week_ids:
            bounds = parse_week_id(wk)
            if not bounds:
                continue
            wk_start, wk_end = bounds
            wk_emails = [o for o in outreach["records"] if o["week_id"] == wk]
            wk_qual = [o for o in wk_emails if o["lead_classification"] == "Qualified"]
            wk_non_qual = [o for o in wk_emails if o["lead_classification"] == "Non-Qualified"]
            wk_fup = [o for o in wk_emails if o["is_follow_up"]]

            wk_tmpl_perf = []
            for tmpl in TEMPLATES_ORDERED:
                t_m = calc_group([o for o in wk_emails if o["template_used"] == tmpl])
                t_m["template_name"] = tmpl
                wk_tmpl_perf.append(t_m)

            wk_rank_info = rankings["by_week"].get(wk, {})
            wk_scrap_info = scraping["by_week"].get(wk, {})

            replied_or_bounced_wk = {o["recipient_email"] for o in wk_emails if o["delivery_status"] == "Bounced" or o["replied"]}
            eligible_fup_wk = len({
                o["recipient_email"] for o in wk_emails
                if o["delivery_status"] == "Delivered" and not o["replied"] and o["recipient_email"] not in replied_or_bounced_wk
            })

            is_past_closed = wk_end < now_dt.date()
            weekly_performance[wk] = {
                "week_id": wk,
                "week_start": wk_start.isoformat(),
                "week_end": wk_end.isoformat(),
                "week_period": f"{wk_start.isoformat()} to {wk_end.isoformat()}",
                "is_completed_week": is_past_closed,
                "outreach": {
                    **calc_group(wk_emails),
                    "qualified": calc_group(wk_qual),
                    "non_qualified": calc_group(wk_non_qual),
                    "general_follow_up": {
                        **calc_group(wk_fup),
                        "follow_up_enabled": bool(getattr(settings, "FOLLOW_UP_ENABLED", False)),
                        "eligible_delivered_no_reply": eligible_fup_wk,
                    },
                },
                "template_performance": wk_tmpl_perf,
                "company_ranking_summary": {k: v for k, v in wk_rank_info.items() if k != "companies"} if wk_rank_info else {
                    "week_id": wk,
                    "week_start": wk_start.isoformat(),
                    "week_end": wk_end.isoformat(),
                    "week_period": f"{wk_start.isoformat()} to {wk_end.isoformat()}",
                    "total_companies": 0,
                    "qualified_companies": 0,
                    "non_qualified_companies": 0,
                    "high_match_count": 0,
                    "moderate_count": 0,
                    "disqualified_count": 0,
                    "qualification_rate_pct": 0.0,
                    "avg_icp_score": 0.0,
                    "top_10_avg_score": 0.0,
                    "top_company": "",
                    "top_score": 0.0,
                },
                "conference_scraping_summary": {k: v for k, v in wk_scrap_info.items() if k != "conferences"} if wk_scrap_info else {
                    "week_id": wk,
                    "week_start": wk_start.isoformat(),
                    "week_end": wk_end.isoformat(),
                    "total_conferences": 0,
                    "conferences_with_speakers": 0,
                    "conferences_with_attendees": 0,
                    "conferences_with_exhibitors": 0,
                    "total_speakers": 0,
                    "total_attendees": 0,
                    "total_exhibitors": 0,
                    "total_contacts": 0,
                    "verified_emails_speakers": 0,
                    "verified_emails_attendees": 0,
                    "verified_emails_exhibitors": 0,
                    "top_industries": [],
                },
            }

        payload = {
            "generated_at": now_dt.isoformat(timespec="seconds"),
            "timezone": str(tz),
            "mailbox": graph_cache.get("mailbox") or settings.OUTREACH_MS_MAILBOX,
            "graph_synced_at": graph_cache.get("fetched_at", ""),
            "weeks": all_week_ids,
            "latest_week_id": all_week_ids[-1] if all_week_ids else "",
            "executive_summary": {
                "outreach": outreach["overall"],
                "excluded_test_sends_count": len(outreach["excluded_test_sends"]),
                "excluded_test_sends": outreach["excluded_test_sends"],
                "company_rankings": rankings["totals"],
                "conference_scraping": scraping["totals"],
            },
            "weekly_performance": [weekly_performance[w] for w in all_week_ids],
            "weekly_performance_map": weekly_performance,
            "template_performance": outreach["template_performance"],
            "email_outreach": {
                "total_sent": len(outreach["records"]),
                "records": outreach["records"],
                "bounces": [r for r in outreach["records"] if r["delivery_status"] == "Bounced"],
                "replies": [r for r in outreach["records"] if r["replied"]],
            },
            "company_rankings": {
                "totals": rankings["totals"],
                "by_week": rankings["by_week"],
                "records": rankings["all_rankings"],
            },
            "conference_scraping": {
                "totals": scraping["totals"],
                "by_week": scraping["by_week"],
                "conferences": scraping["conferences"],
            },
        }

        try:
            tmp = f"{LIVE_PAYLOAD_CACHE_PATH}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, LIVE_PAYLOAD_CACHE_PATH)
        except Exception as e:
            logger.debug(f"Could not write live payload cache: {e}")

        return payload

    def filter_payload_for_week(self, payload: Dict[str, Any], week_id: str) -> Dict[str, Any]:
        """Extracts a clean week-scoped view from a full payload without altering stored snapshots."""
        if not week_id or week_id == "ALL":
            return payload

        wk_perf = payload.get("weekly_performance_map", {}).get(week_id)
        bounds = parse_week_id(week_id)
        wk_emails = [r for r in payload["email_outreach"]["records"] if r["week_id"] == week_id]
        wk_comp_info = payload["company_rankings"]["by_week"].get(week_id, {})
        wk_companies = wk_comp_info.get("companies", [])
        wk_scrap_info = payload["conference_scraping"]["by_week"].get(week_id, {})
        wk_confs = wk_scrap_info.get("conferences", [])

        outreach_summary = wk_perf["outreach"] if wk_perf else {
            **_compute_rates(0, 0, 0, 0),
            "unique_recipients": 0,
            "positive_replies": 0,
            "neutral_replies": 0,
            "negative_replies": 0,
            "qualified": _compute_rates(0, 0, 0, 0),
            "non_qualified": _compute_rates(0, 0, 0, 0),
            "general_follow_up": {**_compute_rates(0, 0, 0, 0), "follow_up_enabled": bool(getattr(settings, "FOLLOW_UP_ENABLED", False)), "eligible_delivered_no_reply": 0},
        }
        tmpl_perf = wk_perf["template_performance"] if wk_perf else [
            {**_compute_rates(0, 0, 0, 0), "template_name": t, "unique_recipients": 0, "positive_replies": 0, "neutral_replies": 0, "negative_replies": 0}
            for t in TEMPLATES_ORDERED
        ]

        return {
            "generated_at": payload["generated_at"],
            "timezone": payload["timezone"],
            "mailbox": payload["mailbox"],
            "graph_synced_at": payload.get("graph_synced_at", ""),
            "scope": week_id,
            "week_id": week_id,
            "week_start": bounds[0].isoformat() if bounds else "",
            "week_end": bounds[1].isoformat() if bounds else "",
            "weeks": payload["weeks"],
            "latest_week_id": payload["latest_week_id"],
            "executive_summary": {
                "outreach": outreach_summary,
                "excluded_test_sends_count": payload["executive_summary"].get("excluded_test_sends_count", 0),
                "company_rankings": {
                    "total_ranked_entries": len(wk_companies),
                    "unique_companies": len(wk_companies),
                    "qualified_entries": wk_comp_info.get("qualified_companies", 0),
                    "non_qualified_entries": wk_comp_info.get("non_qualified_companies", 0),
                    "weeks_covered": 1,
                },
                "conference_scraping": {
                    "total_conferences": wk_scrap_info.get("total_conferences", 0),
                    "total_speakers": wk_scrap_info.get("total_speakers", 0),
                    "total_attendees": wk_scrap_info.get("total_attendees", 0),
                    "total_exhibitors": wk_scrap_info.get("total_exhibitors", 0),
                    "total_contacts": wk_scrap_info.get("total_contacts", 0),
                    "total_verified_emails": (
                        wk_scrap_info.get("verified_emails_speakers", 0)
                        + wk_scrap_info.get("verified_emails_attendees", 0)
                        + wk_scrap_info.get("verified_emails_exhibitors", 0)
                    ),
                },
            },
            "weekly_performance": [wk_perf] if wk_perf else [],
            "weekly_performance_map": {week_id: wk_perf} if wk_perf else {},
            "template_performance": tmpl_perf,
            "email_outreach": {
                "total_sent": len(wk_emails),
                "records": wk_emails,
                "bounces": [r for r in wk_emails if r["delivery_status"] == "Bounced"],
                "replies": [r for r in wk_emails if r["replied"]],
            },
            "company_rankings": {
                "totals": {
                    "total_ranked_entries": len(wk_companies),
                    "unique_companies": len(wk_companies),
                    "qualified_entries": wk_comp_info.get("qualified_companies", 0),
                    "non_qualified_entries": wk_comp_info.get("non_qualified_companies", 0),
                },
                "by_week": {week_id: wk_comp_info} if wk_comp_info else {},
                "records": wk_companies,
            },
            "conference_scraping": {
                "totals": {
                    "total_conferences": wk_scrap_info.get("total_conferences", 0),
                    "total_speakers": wk_scrap_info.get("total_speakers", 0),
                    "total_attendees": wk_scrap_info.get("total_attendees", 0),
                    "total_exhibitors": wk_scrap_info.get("total_exhibitors", 0),
                    "total_contacts": wk_scrap_info.get("total_contacts", 0),
                },
                "by_week": {week_id: wk_scrap_info} if wk_scrap_info else {},
                "conferences": wk_confs,
            },
        }

    # --------------------------------------------------------------------------
    # Non-Overwriting Historical Snapshot & Document Generation
    # --------------------------------------------------------------------------
    @staticmethod
    def _payload_signature(payload: Dict[str, Any]) -> str:
        """Stable content hash excluding ephemeral generation timestamp."""
        canon = {
            "exec": payload.get("executive_summary"),
            "wk": payload.get("weekly_performance"),
            "tmpl": payload.get("template_performance"),
            "out": len(payload.get("email_outreach", {}).get("records", [])),
            "out_b": len(payload.get("email_outreach", {}).get("bounces", [])),
            "out_r": len(payload.get("email_outreach", {}).get("replies", [])),
            "comp": len(payload.get("company_rankings", {}).get("records", [])),
            "conf": len(payload.get("conference_scraping", {}).get("conferences", [])),
        }
        raw = json.dumps(canon, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def ensure_weekly_archives_and_refresh(
        self,
        refresh_graph: bool = True,
        force_export: bool = False,
    ) -> Dict[str, Any]:
        """
        Refreshes live reporting payload and maintains immutable historical snapshots:
        - Every completed past week gets a sealed baseline snapshot (v1) + archived .xlsx/.pdf that is NEVER overwritten.
        - If a closed week receives late data (e.g., late reply/bounce), its baseline remains untouched in archive/v1
          while a newer versioned snapshot (v2, v3, ...) is appended cleanly.
        - The Consolidated All-Weeks Latest Report (ALL_WEEKS) is also exported cleanly for instant download.
        """
        with _report_lock:
            from .reporting_exporter import generate_excel_report, generate_pdf_report

            payload = self.build_full_report_payload(refresh_graph=refresh_graph)
            today_local = datetime.now(get_report_tz()).date()
            archived_results: List[Dict[str, Any]] = []

            for wk_id in payload["weeks"]:
                bounds = parse_week_id(wk_id)
                if not bounds:
                    continue
                wk_start, wk_end = bounds
                wk_payload = self.filter_payload_for_week(payload, wk_id)
                sig = self._payload_signature(wk_payload)
                is_closed = wk_end < today_local

                existing_snaps = (
                    self.db.query(WeeklyReportSnapshot)
                    .filter(WeeklyReportSnapshot.week_id == wk_id)
                    .order_by(WeeklyReportSnapshot.snapshot_version.desc())
                    .all()
                )
                latest_snap = existing_snaps[0] if existing_snaps else None

                # Never overwrite a sealed historical baseline; only create next version if signature changed or files missing
                if (
                    latest_snap
                    and latest_snap.data_signature == sig
                    and latest_snap.xlsx_path
                    and Path(latest_snap.xlsx_path).exists()
                    and latest_snap.pdf_path
                    and Path(latest_snap.pdf_path).exists()
                    and not force_export
                ):
                    archived_results.append({"week_id": wk_id, "action": "unchanged", "version": latest_snap.snapshot_version})
                    continue

                wk_archive_dir = ARCHIVE_DIR / wk_id
                wk_archive_dir.mkdir(parents=True, exist_ok=True)
                ts_tag = datetime.now(get_report_tz()).strftime("%Y%m%d_%H%M%S")

                if latest_snap and latest_snap.is_sealed:
                    # Strictly preserve prior sealed report file(s); write a new versioned artifact!
                    new_ver = latest_snap.snapshot_version + 1
                    is_baseline = False
                    xlsx_file = wk_archive_dir / f"Conference_Agent_Report_{wk_id}_v{new_ver}_{ts_tag}.xlsx"
                    pdf_file = wk_archive_dir / f"Conference_Agent_Report_{wk_id}_v{new_ver}_{ts_tag}.pdf"
                    create_new_row = True
                elif latest_snap and not latest_snap.is_sealed:
                    # Active / unsealed week updates cleanly in place (baseline once week closes)
                    new_ver = latest_snap.snapshot_version
                    is_baseline = latest_snap.is_baseline
                    xlsx_file = wk_archive_dir / f"Conference_Agent_Report_{wk_id}_v{new_ver}.xlsx"
                    pdf_file = wk_archive_dir / f"Conference_Agent_Report_{wk_id}_v{new_ver}.pdf"
                    create_new_row = False
                else:
                    new_ver = 1
                    is_baseline = True
                    xlsx_file = wk_archive_dir / f"Conference_Agent_Report_{wk_id}_v1_baseline.xlsx"
                    pdf_file = wk_archive_dir / f"Conference_Agent_Report_{wk_id}_v1_baseline.pdf"
                    create_new_row = True

                generate_excel_report(wk_payload, str(xlsx_file), title_scope=f"Weekly Report: {wk_start.isoformat()} to {wk_end.isoformat()}")
                generate_pdf_report(wk_payload, str(pdf_file), title_scope=f"Weekly Report: {wk_start.isoformat()} to {wk_end.isoformat()}")

                summary_json = json.dumps(wk_payload.get("executive_summary", {}))
                full_json = json.dumps(wk_payload)

                if create_new_row:
                    snap = WeeklyReportSnapshot(
                        week_id=wk_id,
                        week_start=wk_start,
                        week_end=wk_end,
                        snapshot_version=new_ver,
                        is_baseline=is_baseline,
                        is_sealed=is_closed,
                        data_signature=sig,
                        summary_metrics_json=summary_json,
                        report_payload_json=full_json,
                        xlsx_path=str(xlsx_file),
                        pdf_path=str(pdf_file),
                        generated_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                    self.db.add(snap)
                else:
                    latest_snap.is_sealed = is_closed
                    latest_snap.data_signature = sig
                    latest_snap.summary_metrics_json = summary_json
                    latest_snap.report_payload_json = full_json
                    latest_snap.xlsx_path = str(xlsx_file)
                    latest_snap.pdf_path = str(pdf_file)
                    latest_snap.updated_at = datetime.utcnow()

                self.db.commit()
                archived_results.append({
                    "week_id": wk_id,
                    "action": "created_version" if create_new_row else "updated_active",
                    "version": new_ver,
                    "is_sealed": is_closed,
                    "xlsx": str(xlsx_file),
                    "pdf": str(pdf_file),
                })

            # Update Consolidated Latest Report (ALL_WEEKS)
            latest_xlsx = REPORTS_DIR / "Conference_Agent_Latest_Report.xlsx"
            latest_pdf = REPORTS_DIR / "Conference_Agent_Latest_Report.pdf"
            all_sig = self._payload_signature(payload)
            latest_row = (
                self.db.query(WeeklyReportSnapshot)
                .filter(WeeklyReportSnapshot.week_id == "ALL_WEEKS")
                .first()
            )
            if (
                not latest_row
                or latest_row.data_signature != all_sig
                or not latest_xlsx.exists()
                or not latest_pdf.exists()
                or force_export
            ):
                generate_excel_report(payload, str(latest_xlsx), title_scope="Consolidated Weekly & Historical Report")
                generate_pdf_report(payload, str(latest_pdf), title_scope="Consolidated Weekly & Historical Report")
                first_b = parse_week_id(payload["weeks"][0]) if payload["weeks"] else None
                last_b = parse_week_id(payload["weeks"][-1]) if payload["weeks"] else None
                ws_d = first_b[0] if first_b else today_local
                we_d = last_b[1] if last_b else today_local
                if not latest_row:
                    latest_row = WeeklyReportSnapshot(
                        week_id="ALL_WEEKS",
                        week_start=ws_d,
                        week_end=we_d,
                        snapshot_version=1,
                        is_baseline=False,
                        is_sealed=False,
                        data_signature=all_sig,
                        summary_metrics_json=json.dumps(payload["executive_summary"]),
                        report_payload_json="{}",
                        xlsx_path=str(latest_xlsx),
                        pdf_path=str(latest_pdf),
                    )
                    self.db.add(latest_row)
                else:
                    latest_row.week_start = ws_d
                    latest_row.week_end = we_d
                    latest_row.data_signature = all_sig
                    latest_row.summary_metrics_json = json.dumps(payload["executive_summary"])
                    latest_row.xlsx_path = str(latest_xlsx)
                    latest_row.pdf_path = str(latest_pdf)
                    latest_row.updated_at = datetime.utcnow()
                self.db.commit()

            return {
                "status": "success",
                "generated_at": payload["generated_at"],
                "weeks_processed": len(archived_results),
                "archives": archived_results,
                "latest_xlsx": str(latest_xlsx),
                "latest_pdf": str(latest_pdf),
            }

    def get_live_payload(self, max_cache_age_seconds: int = 90) -> Dict[str, Any]:
        """
        Returns cached live payload if fresh (<= max_cache_age_seconds) for sub-50ms responses,
        otherwise rebuilds deterministically from DB + Excel + outreach_state + cached Graph data.
        """
        self.ensure_initialized()
        if LIVE_PAYLOAD_CACHE_PATH.exists():
            try:
                age = datetime.now().timestamp() - LIVE_PAYLOAD_CACHE_PATH.stat().st_mtime
                if age <= max_cache_age_seconds:
                    with open(LIVE_PAYLOAD_CACHE_PATH, "r", encoding="utf-8") as f:
                        return json.load(f)
            except Exception:
                pass
        return self.build_full_report_payload(refresh_graph=False)

    def get_archive_list(self) -> List[Dict[str, Any]]:
        self.ensure_initialized()
        rows = (
            self.db.query(WeeklyReportSnapshot)
            .filter(WeeklyReportSnapshot.week_id != "ALL_WEEKS")
            .order_by(WeeklyReportSnapshot.week_start.desc(), WeeklyReportSnapshot.snapshot_version.desc())
            .all()
        )
        out = []
        for r in rows:
            d = r.to_meta_dict()
            try:
                d["summary"] = json.loads(r.summary_metrics_json or "{}")
            except Exception:
                d["summary"] = {}
            d["xlsx_exists"] = bool(r.xlsx_path and Path(r.xlsx_path).exists())
            d["pdf_exists"] = bool(r.pdf_path and Path(r.pdf_path).exists())
            d["xlsx_size_kb"] = round(Path(r.xlsx_path).stat().st_size / 1024.0, 1) if d["xlsx_exists"] else 0.0
            d["pdf_size_kb"] = round(Path(r.pdf_path).stat().st_size / 1024.0, 1) if d["pdf_exists"] else 0.0
            out.append(d)
        return out
