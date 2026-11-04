import base64
import datetime as dt
import html
import json
import logging
import os
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
import requests
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import SessionLocal
from ..models import WeeklySpeaker
from .onedrive_excel_service import OneDriveExcelService

logger = logging.getLogger("speaker_outreach")

# Safety locks for concurrent threads
state_lock = threading.Lock()
outreach_lock = threading.Lock()

# Persistent in-memory cache to guarantee zero duplicate Teams notifications across threads
PROCESSED_REPLY_IDS_GLOBAL = set()

REPLY_INTENTS = {
    "INTERESTED", "MEETING_REQUESTED", "OUT_OF_OFFICE", "REFERRAL",
    "NOT_INTERESTED", "UNSUBSCRIBE", "OTHER", "BOUNCE"
}


def now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def get_first_name(raw_name: str) -> str:
    """Extract clean first name, ignoring honorifics and professional titles."""
    if not raw_name:
        return "there"
    clean = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', raw_name.strip(), flags=re.I).strip()
    clean = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV|CPA)[\s.]*$', '', clean, flags=re.I).strip()
    words = clean.split()
    return words[0] if words else "there"


class SafeDict(dict):
    def __missing__(self, key):
        clean_key = str(key).strip().lower().replace(" ", "_").replace("-", "_")
        if clean_key in self:
            return self[clean_key]
        if clean_key in ("company", "company_name"):
            return self.get("company_name", "") or self.get("company", "")
        if clean_key in ("first_name", "speaker_name", "name"):
            return self.get("first_name", "") or self.get("speaker_name", "")
        if clean_key in ("conference", "conference_name"):
            return self.get("conference_name", "")
        return ""


# ==============================================================================
# Microsoft Graph API Client for Outreach & Mailbox Polling
# (Using dedicated OUTREACH_MS_* credentials for akash@adople.ai)
# ==============================================================================
class MSGraphOutreachClient:
    def __init__(self):
        self.tenant_id = settings.OUTREACH_MS_TENANT_ID or os.getenv("OUTREACH_MS_TENANT_ID", "")
        self.client_id = settings.OUTREACH_MS_CLIENT_ID or os.getenv("OUTREACH_MS_CLIENT_ID", "")
        self.client_secret = settings.OUTREACH_MS_CLIENT_SECRET or os.getenv("OUTREACH_MS_CLIENT_SECRET", "")
        self.mailbox = settings.OUTREACH_MS_MAILBOX or os.getenv("OUTREACH_MS_MAILBOX", "akash@adople.ai")
        self.base_url = "https://graph.microsoft.com/v1.0"
        self._token: Optional[str] = None
        self._token_expires_at: float = 0

    def get_token(self) -> str:
        """Acquires a valid OAuth2 Bearer token with caching."""
        if self._token and time.time() < (self._token_expires_at - 60):
            return self._token

        if not self.tenant_id or not self.client_id or not self.client_secret:
            raise ValueError("Microsoft Graph outreach credentials (OUTREACH_MS_*) are not configured in .env")

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        resp = requests.post(token_url, data=payload, timeout=12)
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 3600)
        return self._token

    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json"
        }

    def send_mail(self, to_email: str, subject: str, body: str, content_type: str = "Text") -> Tuple[str, str]:
        """
        1. Creates message in akash@adople.ai to get message ID and conversationId.
        2. Sends the message immediately.
        Returns: (message_id, conversation_id)
        """
        create_url = f"{self.base_url}/users/{self.mailbox}/messages"
        payload = {
            "subject": subject,
            "body": {
                "contentType": content_type,
                "content": body
            },
            "toRecipients": [
                {"emailAddress": {"address": to_email}}
            ]
        }
        r = requests.post(create_url, headers=self.headers(), json=payload, timeout=15)
        r.raise_for_status()
        msg_data = r.json()
        msg_id = msg_data.get("id", "")
        conversation_id = msg_data.get("conversationId", "")

        # Dispatch the message
        send_url = f"{self.base_url}/users/{self.mailbox}/messages/{msg_id}/send"
        r_send = requests.post(send_url, headers=self.headers(), timeout=15)
        if r_send.status_code >= 400:
            err_msg = r_send.text
            try:
                err_msg = r_send.json().get("error", {}).get("message") or r_send.text
            except Exception:
                pass
            raise RuntimeError(f"Microsoft Graph API send failed ({r_send.status_code}): {err_msg}")

        return msg_id, conversation_id

    def get_conversation_messages(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Fetches all sent and received messages in a specific conversation thread."""
        if not conversation_id:
            return []
        # Note: Do not append &$orderby with conversationId filter as Microsoft Exchange throws InefficientFilter (HTTP 400).
        # We fetch messages and sort them locally in Python.
        url = f"{self.base_url}/users/{self.mailbox}/messages?$filter=conversationId eq '{conversation_id}'"
        r = requests.get(url, headers=self.headers(), timeout=15)
        if r.status_code == 200:
            msgs = r.json().get("value", [])
            msgs.sort(key=lambda m: m.get("receivedDateTime") or m.get("createdDateTime") or "")
            return msgs
        logger.warning(f"Failed to fetch conversation messages ({r.status_code}): {r.text}")
        return []

    def get_inbox_messages(self, top: int = 50) -> List[Dict[str, Any]]:
        """Queries recent messages from the Inbox."""
        url = f"{self.base_url}/users/{self.mailbox}/mailFolders/Inbox/messages?$top={top}&$orderby=receivedDateTime desc"
        r = requests.get(url, headers=self.headers(), timeout=15)
        if r.status_code == 200:
            return r.json().get("value", [])
        return []


# ==============================================================================
# Gemini AI Sentiment & Intent Classification Agent
# ==============================================================================
class GeminiOutreachAgent:
    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "")
        self.model = getattr(settings, "OUTREACH_GEMINI_MODEL", "gemini-3.8-flash") or "gemini-3.8-flash"
        self.use_gemini = getattr(settings, "OUTREACH_USE_GEMINI", True)
        self.client = None
        if self.use_gemini and self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"[Gemini Agent] Init notice: {e}. Rule fallback enabled.")

    def analyze_reply(self, reply_text: str, name: str = "", company: str = "", conf: str = "") -> Dict[str, Any]:
        """Analyzes incoming reply text. Uses Gemini if available, else rule-based fallback."""
        if not reply_text or not reply_text.strip():
            return fallback_reply_analysis(reply_text)

        if self.client:
            try:
                from google.genai import types
                prompt = f"""
You classify a reply from a conference speaker to our short outreach email.
Our email only said hello / nice to connect around {conf}.
Speaker: {name} ({company}).
Reply text:
\"\"\"
{reply_text[:2000]}
\"\"\"
Choose exactly one "intent":
- INTERESTED: positive, open to chatting or connecting (including short affirmations or typos like "yes", "sure", "interested", "yes intrested", "sounds good").
- MEETING_REQUESTED: asks for a call, meeting time, or shares/asks for a calendar link.
- OUT_OF_OFFICE: automated away message or temporary absence.
- REFERRAL: points us to someone else.
- NOT_INTERESTED: polite decline or not relevant.
- UNSUBSCRIBE: asks to stop emailing / be removed.
- OTHER: only if truly unclear or unrelated.

Note on sentiment: Any expression of interest or willingness to connect (even brief replies like "Yes intrested" or "Sure") MUST be classified as "Positive".

Return ONLY valid JSON with exactly these keys:
{{"intent": "<one of the above>", "sentiment": "Positive" | "Neutral" | "Negative", "summary": "<one short sentence>"}}
"""
                config = types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
                resp = self.client.models.generate_content(model=self.model, contents=prompt, config=config)
                data = json.loads(resp.text.strip())
                intent = str(data.get("intent", "OTHER")).upper().strip()
                sentiment = str(data.get("sentiment", "Neutral")).capitalize().strip()
                if sentiment not in ("Positive", "Neutral", "Negative"):
                    sentiment = "Neutral"
                return {
                    "intent": intent if intent in REPLY_INTENTS else "OTHER",
                    "sentiment": sentiment,
                    "summary": str(data.get("summary", "")).strip() or reply_text[:140]
                }
            except Exception as e:
                logger.debug(f"[Gemini Agent] AI analysis fallback: {e}")

        return fallback_reply_analysis(reply_text)


def fallback_reply_analysis(reply_text: str) -> Dict[str, Any]:
    """Reliable rule-based intent and sentiment classifier."""
    lower = (reply_text or "").lower()
    ooo = ["out of the office", "out of office", "auto-reply", "away from my desk", "on leave", "vacation"]
    unsub = ["unsubscribe", "remove me", "stop emailing", "take me off"]
    decline = ["not interested", "no thank you", "no thanks", "pass at this time", "not right now"]
    meeting = [
        "calendly", "calendar", "schedule a time", "book a call", "meet with you", "send a link",
        "love to chat", "what time", "available", "let me know when", "jump on a call", "grab coffee",
        "how to reach", "reach you", "contact you", "your number", "your email"
    ]
    positive = [
        "interested", "intrested", "intrest", "sounds interesting", "happy to chat", "let's connect", "open to",
        "sounds good", "happy to discuss", "fine lets connect", "fine let's connect", "yes intrested", "yes", "sure",
        "pleasure to meet", "nice to meet", "nice to connect", "good to connect", "likewise", "count me in"
    ]
    referral = ["reach out to", "looping in", "cc'ing", "contact my colleague", "better person to talk"]

    if any(k in lower for k in ooo):
        intent, sentiment = "OUT_OF_OFFICE", "Neutral"
    elif any(k in lower for k in unsub):
        intent, sentiment = "UNSUBSCRIBE", "Negative"
    elif any(k in lower for k in decline):
        intent, sentiment = "NOT_INTERESTED", "Negative"
    elif any(k in lower for k in meeting):
        intent, sentiment = "MEETING_REQUESTED", "Positive"
    elif any(k in lower for k in referral):
        intent, sentiment = "REFERRAL", "Positive"
    elif any(k in lower for k in positive):
        intent, sentiment = "INTERESTED", "Positive"
    else:
        intent, sentiment = "OTHER", "Neutral"

    return {
        "intent": intent,
        "sentiment": sentiment,
        "summary": (reply_text or "")[:140].strip().replace("\n", " ")
    }


# ==============================================================================
# Helper Functions: State, Template, Transcript
# ==============================================================================
def clean_html(html_text: str) -> str:
    text = re.sub(r"<(script|style).*?</\1>", "", html_text, flags=re.I | re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p>", "\n\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return "\n".join(l.strip() for l in text.splitlines() if l.strip())


def extract_body_text_ms(msg: Dict[str, Any]) -> str:
    """Extracts clean text body from Microsoft Graph message object."""
    body_obj = msg.get("body", {})
    content = body_obj.get("content", "")
    c_type = body_obj.get("contentType", "").lower()
    if c_type == "html" or "<p>" in content or "<br>" in content:
        raw = clean_html(content)
    else:
        raw = content or msg.get("bodyPreview", "")

    # Strip quoted historical replies
    for pat in [r"\nOn .+?wrote:", r"\n[-]+ Original Message [-]+", r"\n_{10,}", r"\nFrom: .+?\nSent: .+?"]:
        parts = re.split(pat, raw, flags=re.I)
        if parts and parts[0].strip():
            raw = parts[0].strip()

    return raw.strip()


def get_state_file_path() -> str:
    configured = getattr(settings, "OUTREACH_STATE_FILE", "outreach_state.json")
    if os.path.isabs(configured):
        return configured
    return "/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/outreach_state.json"


def load_state() -> Dict[str, Any]:
    state_file = get_state_file_path()
    with state_lock:
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        data = json.loads(content)
                        PROCESSED_REPLY_IDS_GLOBAL.update(data.get("processed_reply_ids", []))
                        return data
            except Exception as e:
                logger.warning(f"Could not read {state_file}: {e}")
        return {"threads": {}, "sent_log": [], "processed_reply_ids": list(PROCESSED_REPLY_IDS_GLOBAL)}


def save_state(state: Dict[str, Any]):
    state_file = get_state_file_path()
    with state_lock:
        try:
            # Read latest from disk to avoid wiping out concurrent entries
            current_on_disk = {}
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        current_on_disk = json.loads(f.read().strip() or "{}")
                except Exception:
                    pass

            # Merge processed_reply_ids
            pids = set(current_on_disk.get("processed_reply_ids", []))
            pids.update(state.get("processed_reply_ids", []))
            pids.update(PROCESSED_REPLY_IDS_GLOBAL)
            state["processed_reply_ids"] = list(pids)
            PROCESSED_REPLY_IDS_GLOBAL.update(pids)

            # Merge threads
            merged_threads = current_on_disk.get("threads", {})
            merged_threads.update(state.get("threads", {}))
            state["threads"] = merged_threads

            tmp_file = f"{state_file}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_file, state_file)
        except Exception as e:
            logger.warning(f"Could not save {state_file}: {e}")


def mark_reply_processed(msg_id: str):
    """Atomically commits a message ID to in-memory set and disk immediately."""
    if not msg_id:
        return
    PROCESSED_REPLY_IDS_GLOBAL.add(msg_id)
    state_file = get_state_file_path()
    with state_lock:
        current = {"threads": {}, "sent_log": [], "processed_reply_ids": []}
        if os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    current = json.loads(f.read().strip() or "{}")
            except Exception:
                pass
        pids = set(current.get("processed_reply_ids", []))
        pids.add(msg_id)
        pids.update(PROCESSED_REPLY_IDS_GLOBAL)
        current["processed_reply_ids"] = list(pids)
        try:
            tmp_file = f"{state_file}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(current, f, indent=2)
            os.replace(tmp_file, state_file)
        except Exception as e:
            logger.warning(f"Could not atomically mark reply processed: {e}")


def get_sent_today(state: Dict[str, Any]) -> int:
    today = dt.date.today().isoformat()
    return sum(
        1 for item in state.get("sent_log", [])
        if str(item.get("sent_at", "")).startswith(today) and item.get("status") == "sent"
    )


def load_template(template_path: Optional[str] = None) -> Tuple[str, str]:
    """Loads Subject and Body from template file."""
    path = template_path or getattr(settings, "OUTREACH_TEMPLATE_FILE", "template.txt")
    candidates = [
        path,
        "template.txt",
        "backend/app/templates/template.txt",
        "/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/template.txt"
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    lines = content.splitlines()
                    subject = "A practical AI starting point for {company_name}’s operations"
                    body_start = 0
                    if lines and lines[0].lower().startswith("subject:"):
                        subject = lines[0].split(":", 1)[1].strip()
                        body_start = 1
                    body = "\n".join(lines[body_start:]).strip()
                    return subject, body
            except Exception as e:
                logger.debug(f"Could not read {p}: {e}")

     

def build_email_content(speaker_name: str, job_title: str, company: str, conf_name: str) -> Tuple[str, str]:
    subj_tmpl, body_tmpl = load_template()
    first_name = get_first_name(speaker_name)
    sender = getattr(settings, "OUTREACH_SENDER_NAME", "Akash")
    sender_comp = getattr(settings, "OUTREACH_COMPANY", "Adople AI")

    ctx = SafeDict({
        "first_name": first_name,
        "speaker_name": speaker_name or "there",
        "job_title": job_title or "Speaker",
        "company": company or "your organization",
        "company_name": company or "your organization",
        "conference_name": conf_name or "the conference",
        "sender": sender,
        "sender_company": sender_comp
    })
    return subj_tmpl.format_map(ctx), body_tmpl.format_map(ctx)


def build_conversation_transcript_ms(messages: List[Dict[str, Any]], my_email: str, speaker_name: str) -> str:
    """
    Builds chronological transcript containing ONLY the speaker's received replies.
    Our sent message is excluded from here because it is stored separately in the 'send message' column.
    """
    blocks = []
    for msg in messages:
        from_obj = msg.get("from", {}).get("emailAddress", {})
        sender_email = from_obj.get("address", "").lower()
        sender_name = from_obj.get("name", "")
        dt_str = msg.get("receivedDateTime", "")[:16].replace("T", " ")

        is_from_us = (sender_email == my_email.lower()) or ("adople.ai" in sender_email)
        if is_from_us:
            # Exclude our sent outreach emails; only record the speaker's incoming replies
            continue

        label = speaker_name or sender_name or sender_email
        body = extract_body_text_ms(msg)
        blocks.append(f"[{dt_str}] {label}:\n{body}")

    divider = "\n\n" + ("-" * 50) + "\n\n"
    transcript = divider.join(blocks)
    if len(transcript) > 40000:
        transcript = "[...earlier messages truncated...]\n\n" + transcript[-38000:]
    return transcript


# ==============================================================================
# Microsoft Teams Notification Dispatcher
# ==============================================================================
def send_teams_reply_notification(speaker_name: str, email: str, conf_name: str, intent: str, sentiment: str, reply_text: str):
    """Sends an inbound Teams card when EMAIL_TEAMS_CARD_ENABLED is true."""
    enabled = getattr(settings, "EMAIL_TEAMS_CARD_ENABLED", True)
    if not enabled:
        logger.info("Teams reply card is disabled (EMAIL_TEAMS_CARD_ENABLED=false).")
        return

    webhook_url = getattr(settings, "TEAMS_WEBHOOK_URL", "") or os.getenv("TEAMS_REPLY_WEBHOOK_URL", "")
    if not webhook_url:
        logger.warning("TEAMS_WEBHOOK_URL is not configured.")
        return

    badge_color = "Good" if sentiment.upper() == "POSITIVE" else ("Attention" if sentiment.upper() == "NEGATIVE" else "Default")

    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "Container",
                "style": "emphasis",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": f"📬 Weekly Speaker Email Reply: {intent.title()}",
                        "weight": "Bolder",
                        "size": "Large",
                        "color": badge_color
                    },
                    {
                        "type": "TextBlock",
                        "text": f"Captured from {speaker_name} ({email}) at {now_iso()[:16]}",
                        "isSubtle": True,
                        "spacing": "None"
                    }
                ]
            },
            {
                "type": "Container",
                "spacing": "Medium",
                "items": [
                    {
                        "type": "FactSet",
                        "facts": [
                            {"title": "Speaker:", "value": speaker_name or "-"},
                            {"title": "Email:", "value": email or "-"},
                            {"title": "Conference:", "value": conf_name or "-"},
                            {"title": "Sentiment:", "value": sentiment or "Neutral"},
                            {"title": "Intent:", "value": intent or "OTHER"},
                            {"title": "Captured At:", "value": now_iso()[:16]}
                        ]
                    }
                ]
            },
            {
                "type": "Container",
                "spacing": "Medium",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": "💬 Reply Content:",
                        "weight": "Bolder",
                        "size": "Medium"
                    },
                    {
                        "type": "TextBlock",
                        "text": reply_text[:1000] if reply_text else "(No body text)",
                        "wrap": True
                    }
                ]
            }
        ]
    }

    try:
        r = requests.post(webhook_url, json=card, headers={"Content-Type": "application/json"}, timeout=15)
        logger.info(f"Teams reply card response: {r.status_code}")
    except Exception as e:
        logger.warning(f"Failed to post Teams reply card: {e}")


# ==============================================================================
# Main Speaker Outreach Service
# ==============================================================================
class SpeakerOutreachService:
    def __init__(self, db: Optional[Session] = None):
        if db is None:
            self.db = SessionLocal()
            self._owns_db = True
        else:
            self.db = db
            self._owns_db = False
        self.graph = MSGraphOutreachClient()
        self.gemini = GeminiOutreachAgent()
        self.onedrive = OneDriveExcelService()
        from ..storage.excel_manager import ExcelManager
        self.excel_mgr = ExcelManager()
        self.local_excel_path = Path("/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/data/excel/usa_conferences_published.xlsx")

    def close(self):
        """Closes database session if owned by this service instance."""
        if getattr(self, "_owns_db", False) and self.db:
            try:
                self.db.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def send_test_outreach_email(
        self,
        recipient_email: str,
        speaker_name: str = "Test Speaker",
        company_name: str = "Adople Test Co",
        conference_name: str = "AI Innovation Summit 2026",
        conference_id: str = "CONF-TEST-OUTREACH"
    ) -> Dict[str, Any]:
        """
        Sends a single test outreach email to a specified personal email address:
        - Renders email strictly using template.txt.
        - Ensures an isolated test record in PostgreSQL and local/OneDrive Excel exists.
        - Dispatches via Microsoft Graph API (akash@adople.ai).
        - Tracks the conversation thread in outreach_state.json for reply monitoring.
        - Leaves ALL other real conference speakers completely untouched.
        """
        recipient_email = recipient_email.strip().lower()
        if "@" not in recipient_email or "." not in recipient_email or recipient_email.count("@") != 1:
            raise ValueError(f"Invalid recipient email address: '{recipient_email}'. An email must contain exactly one '@' (e.g. 'skjeeva2005@gmail.com').")

        subject, body = build_email_content(
            speaker_name=speaker_name,
            job_title="Keynote Speaker",
            company=company_name,
            conf_name=conference_name
        )

        logger.info(f"🧪 [Manual Test] Dispatching test outreach email to {recipient_email}...")

        # 1. Ensure test record in PostgreSQL
        test_speaker = self.db.query(WeeklySpeaker).filter(
            WeeklySpeaker.speaker_id == "SPK-TEST-MANUAL-001"
        ).first()

        if not test_speaker:
            test_speaker = WeeklySpeaker(
                speaker_id="SPK-TEST-MANUAL-001",
                conference_id=conference_id,
                conference_name=conference_name,
                speaker_name=speaker_name,
                job_title="Keynote Speaker",
                company_name=company_name,
                professional_email=recipient_email,
                verification_status="verified",
                weekly_run_id="WEEK-TEST"
            )
            self.db.add(test_speaker)
        else:
            test_speaker.professional_email = recipient_email
            test_speaker.speaker_name = speaker_name
            test_speaker.company_name = company_name
            test_speaker.conference_name = conference_name
            test_speaker.outreach_status = None
            test_speaker.reply_status = None
            test_speaker.reply_sentiment = None
            test_speaker.received_reply = None

        self.db.commit()

        # 2. Ensure row exists in OneDrive tbl_weekly_speakers for tracking
        try:
            existing_map = self.onedrive.get_existing_weekly_speaker_rows_map()
            t_cid = conference_id.strip().lower()
            t_name = speaker_name.strip().lower()
            t_email = recipient_email.strip().lower()
            
            row_exists = False
            for (k_cid, k_name), (_, cur_vals) in existing_map.items():
                r_email = str(cur_vals[8] if len(cur_vals) > 8 else "").strip().lower()
                if (k_cid.strip().lower() == t_cid and k_name.strip().lower() == t_name) or (t_email and r_email == t_email):
                    row_exists = True
                    break

            if not row_exists:
                drive_id = self.onedrive.resolve_drive_id()
                item_id = self.onedrive.resolve_item_id()
                # tbl_weekly_speakers has exactly 20 columns
                test_row = [
                    "SPK-TEST-MANUAL-001",
                    conference_id,
                    conference_name,
                    speaker_name,
                    "Keynote Speaker",
                    company_name,
                    "",
                    "not_found",
                    recipient_email,
                    "manual_test",
                    "",
                    "verified",
                    now_iso(),
                    "WEEK-TEST",
                    "", "", "", "", "", ""
                ]
                self.onedrive._api_request(
                    "POST",
                    f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.onedrive.weekly_spk_tbl_name}/rows",
                    body={"values": [test_row]}
                )
                logger.info("Added test row (20 columns) into OneDrive tbl_weekly_speakers.")
        except Exception as e:
            logger.warning(f"Notice ensuring test row in OneDrive: {e}")
            logger.warning(f"Notice ensuring test row in OneDrive: {e}")

        # 3. Dispatch email via Microsoft Graph API
        msg_id, conversation_id = self.graph.send_mail(recipient_email, subject, body)

        # 4. Update test speaker in DB
        test_speaker.outreach_status = "sent"
        test_speaker.sent_message = f"Subject: {subject}\n\n{body}"
        test_speaker.email_thread_id = conversation_id
        test_speaker.email_sent_at = datetime.utcnow()
        self.db.commit()

        # 5. Record thread in outreach_state.json
        state = load_state()
        dedupe_key = f"{recipient_email}|{conference_id.lower()}"
        state.setdefault("sent_log", []).append({
            "email": recipient_email,
            "conference_id": conference_id,
            "sent_at": now_iso(),
            "status": "sent"
        })
        state.setdefault("threads", {})[dedupe_key] = {
            "thread_id": conversation_id,
            "message_id": msg_id,
            "speaker_id": test_speaker.speaker_id,
            "sent_at": now_iso()
        }
        save_state(state)

        # 6. Update OneDrive and Local Excel with 'sent' status
        self._update_onedrive_speaker_row(test_speaker)

        return {
            "status": "sent",
            "recipient": recipient_email,
            "speaker_name": speaker_name,
            "message_id": msg_id,
            "conversation_id": conversation_id,
            "subject": subject,
            "body": body,
            "instructions": (
                f"Test email sent successfully to {recipient_email}. "
                "Open your inbox, reply to the email, and then run a reply poll or wait 60 seconds "
                "to see the reply captured, sentiment analyzed, and OneDrive Excel updated."
            )
        }

    def get_status(self) -> Dict[str, Any]:
        """Returns live telemetry of the outreach engine, safety status, and database counts."""
        state = load_state()
        sent_today = get_sent_today(state)
        
        allowed_status = getattr(settings, "OUTREACH_ALLOWED_EMAIL_STATUS", "verified").lower()
        if allowed_status in ("all", "*", "any"):
            verified_speakers = self.db.query(WeeklySpeaker).filter(
                WeeklySpeaker.professional_email != "",
                WeeklySpeaker.professional_email.isnot(None),
                WeeklySpeaker.speaker_id != "SPK-TEST-MANUAL-001"
            ).count()
        else:
            allowed_list = [s.strip().lower() for s in allowed_status.split(",") if s.strip()]
            verified_speakers = self.db.query(WeeklySpeaker).filter(
                WeeklySpeaker.professional_email != "",
                WeeklySpeaker.professional_email.isnot(None),
                func.lower(WeeklySpeaker.verification_status).in_(allowed_list),
                WeeklySpeaker.speaker_id != "SPK-TEST-MANUAL-001"
            ).count()

        sent_speakers = self.db.query(WeeklySpeaker).filter(
            WeeklySpeaker.outreach_status == "sent"
        ).count()

        replied_speakers = self.db.query(WeeklySpeaker).filter(
            WeeklySpeaker.reply_status == "replied"
        ).count()

        return {
            "mailbox": getattr(settings, "OUTREACH_MS_MAILBOX", "akash@adople.ai"),
            "campaign_active": getattr(settings, "OUTREACH_ACTIVE", False),
            "dry_run": getattr(settings, "OUTREACH_DRY_RUN", True),
            "teams_card_notifications": getattr(settings, "EMAIL_TEAMS_CARD_ENABLED", True),
            "gemini_model": getattr(settings, "OUTREACH_GEMINI_MODEL", "gemini-3.8-flash"),
            "scheduled_send_time": getattr(settings, "OUTREACH_SEND_TIME", "19:00"),
            "timezone": getattr(settings, "OUTREACH_TIMEZONE", "Asia/Kolkata"),
            "reply_watch_interval_minutes": getattr(settings, "OUTREACH_WATCH_INTERVAL_MINUTES", 1),
            "verified_speakers_eligible": verified_speakers,
            "emails_sent_count": sent_speakers,
            "replies_captured_count": replied_speakers,
            "emails_sent_today": sent_today,
            "daily_cap": getattr(settings, "OUTREACH_DAILY_CAP", 0),
            "active_monitored_threads": len(state.get("threads", {}))
        }

    def run_outreach_send_pass(self, force: bool = False) -> Dict[str, Any]:
        """
        Executes the scheduled email outreach pass:
        - Filters speakers with valid, verified email addresses.
        - Skips already sent, unverified, or duplicate speakers.
        - Pre-marks 'sending' before dispatch.
        - Dispatches email via Microsoft Graph (akash@adople.ai).
        - Enforces DRY_RUN safety check (no real emails sent if DRY_RUN=True).
        - Syncs status to OneDrive Excel and PostgreSQL.
        """
        with outreach_lock:
            dry_run = getattr(settings, "OUTREACH_DRY_RUN", True)
            active = getattr(settings, "OUTREACH_ACTIVE", False)
            if not force and not active and not dry_run:
                logger.info("Outreach is not active (OUTREACH_ACTIVE=false). Pass skipped.")
                return {"status": "inactive", "message": "Outreach inactive awaiting template approval."}

            logger.info(f"🚀 Starting Outreach Send Pass (DRY_RUN={dry_run})...")
            state = load_state()
            sent_today = get_sent_today(state)
            daily_cap = getattr(settings, "OUTREACH_DAILY_CAP", 0)

            # Query eligible speakers with non-empty emails
            allowed_status = getattr(settings, "OUTREACH_ALLOWED_EMAIL_STATUS", "verified").lower()
            if allowed_status in ("all", "*", "any"):
                speakers = self.db.query(WeeklySpeaker).filter(
                    WeeklySpeaker.professional_email != "",
                    WeeklySpeaker.professional_email.isnot(None),
                    WeeklySpeaker.speaker_id != "SPK-TEST-MANUAL-001"
                ).all()
            else:
                allowed_list = [s.strip().lower() for s in allowed_status.split(",") if s.strip()]
                speakers = self.db.query(WeeklySpeaker).filter(
                    WeeklySpeaker.professional_email != "",
                    WeeklySpeaker.professional_email.isnot(None),
                    func.lower(WeeklySpeaker.verification_status).in_(allowed_list),
                    WeeklySpeaker.speaker_id != "SPK-TEST-MANUAL-001"
                ).all()

            sent_count = 0
            skipped_count = 0
            preview_list = []

            for spk in speakers:
                email = (spk.professional_email or "").strip().lower()
                if "@" not in email or "." not in email:
                    skipped_count += 1
                    continue

                # Check if already sent or processing
                current_st = (spk.outreach_status or "").lower()
                if current_st in ("sent", "sending", "do_not_contact", "failed"):
                    skipped_count += 1
                    continue

                if daily_cap > 0 and sent_today >= daily_cap:
                    logger.info(f"Daily cap ({daily_cap}) reached.")
                    break

                subject, body = build_email_content(
                    speaker_name=spk.speaker_name,
                    job_title=spk.job_title,
                    company=spk.company_name,
                    conf_name=spk.conference_name
                )
                full_message = f"Subject: {subject}\n\n{body}"

                if dry_run:
                    # Safe Dry-Run preview only
                    preview_list.append({
                        "speaker": spk.speaker_name,
                        "email": email,
                        "conference": spk.conference_name,
                        "subject": subject,
                        "body_preview": body[:120]
                    })
                    sent_count += 1
                    sent_today += 1
                    logger.info(f"[DRY RUN PREVIEW] Would send to: {spk.speaker_name} <{email}>")
                    continue

                # Live Sending Logic
                try:
                    # Pre-send lock in DB
                    spk.outreach_status = "sending"
                    spk.sent_message = full_message
                    self.db.commit()

                    msg_id, conversation_id = self.graph.send_mail(email, subject, body)

                    spk.outreach_status = "sent"
                    spk.email_thread_id = conversation_id
                    spk.email_sent_at = datetime.utcnow()
                    self.db.commit()

                    # Record in state
                    dedupe_key = f"{email}|{spk.conference_id.lower()}"
                    fresh_state = load_state()
                    fresh_state.setdefault("sent_log", []).append({
                        "email": email,
                        "conference_id": spk.conference_id,
                        "sent_at": now_iso(),
                        "status": "sent"
                    })
                    fresh_state.setdefault("threads", {})[dedupe_key] = {
                        "thread_id": conversation_id,
                        "message_id": msg_id,
                        "speaker_id": spk.speaker_id,
                        "sent_at": now_iso()
                    }
                    save_state(fresh_state)

                    # Sync to OneDrive Excel in-place
                    self._update_onedrive_speaker_row(spk)

                    sent_count += 1
                    sent_today += 1
                    logger.info(f"✅ Dispatched email to: {spk.speaker_name} <{email}>")

                    # Jitter delay
                    delay = random.randint(getattr(settings, "OUTREACH_DELAY_MIN", 60), getattr(settings, "OUTREACH_DELAY_MAX", 120))
                    time.sleep(delay)

                except Exception as e:
                    logger.error(f"❌ Failed to send to {email}: {e}")
                    spk.outreach_status = "failed"
                    self.db.commit()

            return {
                "status": "completed",
                "dry_run": dry_run,
                "sent_count": sent_count,
                "skipped_count": skipped_count,
                "previews": preview_list
            }

    def poll_replies(self) -> Dict[str, Any]:
        """
        Polls mailbox akash@adople.ai for new incoming replies:
        - Runs 24/7 every 60s without interrupting existing workflows.
        - Identifies whether incoming messages belong to our reached-out speakers.
        - Captures full back-and-forth transcript into 'Received Reply'.
        - Performs Gemini sentiment & intent analysis.
        - Updates OneDrive Excel, Local Excel, and PostgreSQL database.
        - Sends Microsoft Teams Adaptive Card if EMAIL_TEAMS_CARD_ENABLED=true.
        """
        state = load_state()
        threads = state.get("threads", {})
        processed_ids = set(state.get("processed_reply_ids", []))
        new_replies_count = 0
        bounces_count = 0

        # Query all speakers who were emailed (supports initial and all subsequent replies)
        sent_speakers = self.db.query(WeeklySpeaker).filter(
            (WeeklySpeaker.outreach_status.in_(["sent", "replied"])) | (WeeklySpeaker.email_thread_id.isnot(None))
        ).all()

        speaker_by_thread = {s.email_thread_id: s for s in sent_speakers if s.email_thread_id}
        speaker_by_email = {(s.professional_email or "").strip().lower(): s for s in sent_speakers if s.professional_email}

        # Query recent inbox messages
        try:
            inbox_messages = self.graph.get_inbox_messages(top=30)
        except Exception as e:
            logger.warning(f"Error querying inbox messages: {e}")
            return {"status": "error", "error": str(e)}

        for msg in inbox_messages:
            msg_id = msg.get("id")
            if not msg_id or msg_id in processed_ids or msg_id in PROCESSED_REPLY_IDS_GLOBAL:
                continue

            conv_id = msg.get("conversationId", "")
            from_addr = msg.get("from", {}).get("emailAddress", {}).get("address", "").strip().lower()

            target_speaker = speaker_by_thread.get(conv_id) or speaker_by_email.get(from_addr)
            if not target_speaker:
                # Unrelated email - ignore safely
                continue

            # IMMEDIATELY claim this message ID in memory and disk before any processing begins
            processed_ids.add(msg_id)
            mark_reply_processed(msg_id)

            # This is a verified reply from a target speaker
            logger.info(f"📬 Incoming reply detected from {target_speaker.speaker_name} <{from_addr}>!")
            body_text = extract_body_text_ms(msg)

            # Check bounce
            is_bounce = any(b in from_addr for b in ["mailer-daemon", "postmaster"]) or "delivery status" in msg.get("subject", "").lower()

            # Fetch full conversation thread to build transcript
            thread_msgs = self.graph.get_conversation_messages(conv_id) if conv_id else [msg]
            transcript = build_conversation_transcript_ms(thread_msgs, self.graph.mailbox, target_speaker.speaker_name)

            sentiment = "Negative" if is_bounce else "Neutral"
            intent = "BOUNCE" if is_bounce else "OTHER"

            if is_bounce:
                bounces_count += 1
            else:
                analysis = self.gemini.analyze_reply(
                    body_text,
                    name=target_speaker.speaker_name,
                    company=target_speaker.company_name,
                    conf=target_speaker.conference_name
                )
                intent = analysis.get("intent", "OTHER")
                sentiment = analysis.get("sentiment", "Neutral")
                new_replies_count += 1

                # Teams notification
                send_teams_reply_notification(
                    speaker_name=target_speaker.speaker_name,
                    email=from_addr,
                    conf_name=target_speaker.conference_name,
                    intent=intent,
                    sentiment=sentiment,
                    reply_text=body_text
                )

            # 1. Existing Weekly Speakers workflow: continues working exactly as before
            target_speaker.reply_status = "bounced" if is_bounce else "replied"
            target_speaker.reply_sentiment = sentiment
            target_speaker.received_reply = transcript
            self.db.commit()
            self._update_onedrive_speaker_row(target_speaker)

            # 2. In addition, store a copy of the speaker's complete row only when they reply in 'Speakers Replies'
            if getattr(settings, "SPEAKER_REPLIES_ENABLED", True):
                received_at_str = msg.get("receivedDateTime") or datetime.utcnow().isoformat()
                last_checked_str = target_speaker.last_checked_at.isoformat() if target_speaker.last_checked_at else datetime.utcnow().isoformat()

                reply_row = [
                    target_speaker.speaker_id or "",             # 1. spekers_id (Reference to original speaker)
                    target_speaker.conference_id or "",          # 2. Conference_ID
                    target_speaker.conference_name or "",        # 3. Conference_Name
                    target_speaker.speaker_name or "",           # 4. Speaker_Name
                    target_speaker.job_title or "",              # 5. Job_Title
                    target_speaker.company_name or "",           # 6. Company_Name
                    target_speaker.personal_linkedin_url or "",  # 7. Personal_LinkedIn_URL
                    target_speaker.linkedin_status or "",        # 8. LinkedIn_Status
                    target_speaker.professional_email or from_addr, # 9. Professional_Email
                    target_speaker.email_source_url or "",       # 10. Email_Source_URL
                    target_speaker.speaker_source_url or "",     # 11. Speaker_Source_URL
                    target_speaker.verification_status or "",    # 12. Verification_Status
                    last_checked_str,                            # 13. Last_Checked_At
                    target_speaker.weekly_run_id or "",          # 14. Weekly_Run_ID
                    target_speaker.outreach_status or "sent",    # 15. outreach status 
                    "bounced" if is_bounce else "replied",       # 16. reply status
                    sentiment,                                   # 17. reply sentiment 
                    body_text if not is_bounce else "BOUNCE",    # 18. received reply
                    target_speaker.sent_message or "",           # 19. send message
                    conv_id or "",                               # 20. thread id (Outlook Conversation ID)
                    received_at_str,                             # 21. Reply_Received_At
                    msg_id                                       # 22. Message_ID
                ]

                # 1. Append to OneDrive 'tbl_speakers_replies'
                try:
                    self.onedrive.append_speaker_reply(reply_row)
                except Exception as e:
                    logger.error(f"Error appending reply to OneDrive tbl_speakers_replies: {e}", exc_info=True)

                # 2. Append to Local Excel 'Speakers Replies'
                try:
                    self.excel_mgr.append_speaker_reply_to_excel(reply_row)
                except Exception as e:
                    logger.error(f"Error appending reply to Local Excel 'Speakers Replies': {e}", exc_info=True)

                # 3. Store in PostgreSQL speaker_replies table
                try:
                    from ..models import SpeakerReply
                    parsed_dt = None
                    try:
                        parsed_dt = datetime.fromisoformat(received_at_str.replace("Z", "+00:00"))
                    except Exception:
                        parsed_dt = datetime.utcnow()

                    reply_rec = SpeakerReply(
                        speaker_id=target_speaker.speaker_id or "",
                        conference_id=target_speaker.conference_id or "",
                        conference_name=target_speaker.conference_name or "",
                        speaker_name=target_speaker.speaker_name or "",
                        job_title=target_speaker.job_title or "",
                        company_name=target_speaker.company_name or "",
                        personal_linkedin_url=target_speaker.personal_linkedin_url or "",
                        linkedin_status=target_speaker.linkedin_status or "",
                        professional_email=target_speaker.professional_email or from_addr,
                        email_source_url=target_speaker.email_source_url or "",
                        speaker_source_url=target_speaker.speaker_source_url or "",
                        verification_status=target_speaker.verification_status or "",
                        last_checked_at=target_speaker.last_checked_at or datetime.utcnow(),
                        weekly_run_id=target_speaker.weekly_run_id or "",
                        outreach_status=target_speaker.outreach_status or "sent",
                        reply_status="bounced" if is_bounce else "replied",
                        reply_sentiment=sentiment,
                        received_reply=body_text if not is_bounce else "BOUNCE",
                        sent_message=target_speaker.sent_message or "",
                        thread_id=conv_id or "",
                        reply_received_at=parsed_dt,
                        message_id=msg_id,
                        original_speaker_id=target_speaker.speaker_id or ""
                    )
                    self.db.add(reply_rec)
                    self.db.commit()
                except Exception as e:
                    self.db.rollback()
                    logger.warning(f"Notice: PostgreSQL speaker_replies record commit: {e}")

                logger.info(f"✅ Stored reply copy for '{target_speaker.speaker_name}' into 'Speakers Replies' (Weekly Speakers also updated as usual).")

            # Ensure persisted in state & deduplication set
            mark_reply_processed(msg_id)

        return {
            "status": "success",
            "new_replies": new_replies_count,
            "bounces": bounces_count,
            "scanned_messages": len(inbox_messages)
        }

    def _update_onedrive_speaker_row(self, speaker: WeeklySpeaker):
        """Updates the speaker row in OneDrive Excel (tbl_weekly_speakers) and Local Excel."""
        try:
            # 1. Update OneDrive
            existing_map = self.onedrive.get_existing_weekly_speaker_rows_map()
            target_cid = str(speaker.conference_id or "").strip().lower()
            target_name = str(speaker.speaker_name or "").strip().lower()
            target_email = str(speaker.professional_email or "").strip().lower()

            target_row_info = None
            for (k_cid, k_name), (row_idx, cur_vals) in existing_map.items():
                row_email = str(cur_vals[8] if len(cur_vals) > 8 else "").strip().lower()
                if (k_cid.strip().lower() == target_cid and k_name.strip().lower() == target_name) or (target_email and row_email == target_email):
                    target_row_info = (row_idx, cur_vals)
                    break

            if target_row_info:
                row_idx, cur_vals = target_row_info
                new_vals = list(cur_vals)
                while len(new_vals) < 20:
                    new_vals.append("")

                new_vals[14] = speaker.outreach_status or ""
                new_vals[15] = speaker.reply_status or ""
                new_vals[16] = speaker.reply_sentiment or ""
                new_vals[17] = speaker.received_reply or ""
                new_vals[18] = speaker.sent_message or ""
                new_vals[19] = speaker.email_thread_id or ""

                self.onedrive.update_weekly_speaker_row(row_idx, new_vals)
                logger.info(f"✅ OneDrive tbl_weekly_speakers row {row_idx} updated for {speaker.speaker_name}.")
            else:
                logger.warning(f"Speaker {speaker.speaker_name} not found in OneDrive tbl_weekly_speakers rows map.")

            # 2. Update Local Excel
            if self.local_excel_path.exists():
                wb = openpyxl.load_workbook(self.local_excel_path)
                ws = wb["weekly_speakers"]
                # Ensure headers exist
                if ws.max_column < 20:
                    headers = ["outreach status", "reply status", "reply sentiment", "received reply", "send message", "thread id"]
                    for c_idx, h in enumerate(headers, start=15):
                        ws.cell(row=1, column=c_idx, value=h)

                for r in range(2, ws.max_row + 1):
                    cid = str(ws.cell(row=r, column=2).value or "").strip().lower()
                    sname = str(ws.cell(row=r, column=4).value or "").strip().lower()
                    semail = str(ws.cell(row=r, column=9).value or "").strip().lower()
                    if (cid == target_cid and sname == target_name) or (target_email and semail == target_email):
                        ws.cell(row=r, column=15, value=speaker.outreach_status or "")
                        ws.cell(row=r, column=16, value=speaker.reply_status or "")
                        ws.cell(row=r, column=17, value=speaker.reply_sentiment or "")
                        ws.cell(row=r, column=18, value=speaker.received_reply or "")
                        ws.cell(row=r, column=19, value=speaker.sent_message or "")
                        ws.cell(row=r, column=20, value=speaker.email_thread_id or "")
                        break
                wb.save(self.local_excel_path)
        except Exception as e:
            logger.warning(f"Notice while updating Excel rows: {e}")
