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
        if clean_key in ("first_name", "name"):
            return self.get("first_name", "") or self.get("name", "")
        if clean_key in ("speaker_name", "attendee_name", "exhibitor_name", "full_name"):
            return self.get("full_name", "") or self.get("speaker_name", "") or self.get("name", "")
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


def is_bounce_email(msg: Dict[str, Any], body_text: str = "") -> bool:
    """
    Comprehensive NDR (Non-Delivery Report) and bounce detection:
    - Detects Microsoft 365 Exchange automated NDRs (e.g. Microsoftexchange...<hash>@domain)
    - Detects standard MTA bounce senders (mailer-daemon, postmaster, noreply, etc.)
    - Detects NDR / bounce subjects ('Undeliverable:', 'Delivery has failed', 'Delivery Status Notification', etc.)
    - Detects NDR body signatures and standard RFC failure codes (550, 554, etc.)
    """
    from_obj = msg.get("from", {}).get("emailAddress", {})
    from_addr = str(from_obj.get("address", "")).strip().lower()
    from_name = str(from_obj.get("name", "")).strip().lower()
    subject = str(msg.get("subject", "")).strip().lower()
    body_preview = str(msg.get("bodyPreview", "")).strip().lower()
    combined_body = f"{body_preview} {body_text.lower()}"

    # 1. Sender name / address checks
    bounce_sender_keywords = [
        "mailer-daemon", "postmaster", "microsoftexchange", "microsoft exchange",
        "system-administrator", "system administrator", "mail delivery",
        "mail delivery system", "mail delivery subsystem", "daemon"
    ]
    if any(k in from_addr for k in bounce_sender_keywords):
        return True
    if any(k in from_name for k in ["microsoft outlook", "mail delivery system", "mail delivery subsystem", "postmaster", "system administrator"]):
        return True

    # 2. Subject checks
    bounce_subject_keywords = [
        "undeliverable", "delivery status notification", "delivery has failed",
        "failure notice", "mail delivery failed", "returned mail",
        "undelivered mail", "message not delivered", "failure delivery",
        "delivery failure", "could not be delivered"
    ]
    if any(k in subject for k in bounce_subject_keywords):
        return True

    # 3. Body text / preview checks
    bounce_body_keywords = [
        "delivery has failed to these recipients",
        "your message couldn't be delivered",
        "your message could not be delivered",
        "domain name system (dns) reported that the recipient's domain does not exist",
        "recipient's email address was not found",
        "recipient address rejected",
        "the email account that you tried to reach does not exist",
        "user unknown", "mailbox unavailable", "550 5.1.1", "554 5.4.4",
        "550 5.4.1", "550 5.7.1", "remote server returned",
        "diagnostic information for administrators", "generating server:",
        "rejected your message to the following email addresses"
    ]
    if any(k in combined_body for k in bounce_body_keywords):
        return True

    return False


def extract_bounce_recipient(msg: Dict[str, Any], body_text: str = "") -> Optional[str]:
    """Extracts the intended recipient's email from an NDR/bounce message body."""
    combined = f"{msg.get('bodyPreview', '')} {body_text}"
    candidates = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', combined)
    for c in candidates:
        c_clean = c.strip().strip("<>():;,.").lower()
        if not c_clean.endswith("adople.ai") and "exchange" not in c_clean and "outlook" not in c_clean:
            return c_clean
    return None


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


def normalize_category(category: Optional[str]) -> str:
    """Normalizes category/contact_type string to 'speaker', 'attendee', or 'exhibitor'."""
    clean = str(category or "").strip().lower()
    if "attendee" in clean:
        return "attendee"
    if "exhibitor" in clean:
        return "exhibitor"
    return "speaker"


def parse_template_content(content: str) -> Dict[str, Tuple[str, str]]:
    """
    Parses multi-section template content into role-specific templates.
    Expected sections in template.txt:
        Speakers templates :
        Sub : ...
        Hi {Name}, ...

        Attendees Templates :
        Sub : ...
        Hi {Name}, ...

        Exhibitors Template :
        Sub : ...
        Hi {Name}, ...
    """
    section_pattern = re.compile(
        r'(?im)^\s*(?:\[|\b)?(speaker|attendee|exhibitor)s?\s*(?:template|templates)?\s*(?:\])?\s*:\s*$'
    )
    matches = list(section_pattern.finditer(content))
    templates: Dict[str, Tuple[str, str]] = {}

    def extract_subj_and_body(block: str) -> Tuple[str, str]:
        # Strip trailing horizontal divider lines like --- or ===
        block = re.sub(r'[\r\n]+\s*[-=]{3,}\s*$', '', block).strip()
        lines = block.splitlines()
        subj = ""
        body_lines = []
        in_body = False
        for line in lines:
            sub_m = re.match(r'(?i)^\s*(?:sub|subject)\s*:\s*(.+)$', line)
            if sub_m and not in_body and not subj:
                subj = sub_m.group(1).strip()
            elif not in_body and not line.strip():
                continue
            else:
                in_body = True
                body_lines.append(line)
        body = "\n".join(body_lines).strip()
        if not subj:
            subj = "Akash from Adople AI – Referred by {Conference Name}"
        return subj, body

    if not matches:
        # Fallback for single-template files
        subj, body = extract_subj_and_body(content)
        templates["default"] = (subj, body)
        templates["speaker"] = (subj, body)
        templates["attendee"] = (subj, body)
        templates["exhibitor"] = (subj, body)
        return templates

    for i, match in enumerate(matches):
        role_raw = match.group(1).lower()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        block = content[start:end].strip()
        subj, body = extract_subj_and_body(block)
        templates[role_raw] = (subj, body)

    if "speaker" in templates:
        templates["default"] = templates["speaker"]
    elif templates:
        templates["default"] = next(iter(templates.values()))

    return templates


def load_templates(template_path: Optional[str] = None) -> Dict[str, Tuple[str, str]]:
    """Loads all role-specific templates from template.txt."""
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
                    templates = parse_template_content(content)
                    if templates:
                        return templates
            except Exception as e:
                logger.debug(f"Could not read template from {p}: {e}")

    # Fallback template
    fallback = (
        "Akash from Adople AI – Referred by {Conference Name}",
        "Hi {Name},\n\nI hope this finds you well. I'm Akash from Adople AI. For over 10 years, we have helped businesses solve real-world problems with technology."
    )
    return {
        "speaker": fallback,
        "attendee": fallback,
        "exhibitor": fallback,
        "default": fallback
    }


def load_template(template_path: Optional[str] = None, category: str = "Speaker") -> Tuple[str, str]:
    """Loads Subject and Body for a specific category (Speaker, Attendee, or Exhibitor)."""
    templates = load_templates(template_path)
    role = normalize_category(category)
    return templates.get(role) or templates.get("default", ("Akash from Adople AI – Referred by {Conference Name}", "Hi {Name},"))


def build_email_content(
    speaker_name: str,
    job_title: str,
    company: str,
    conf_name: str,
    pitch_hook: str = "",
    category: str = "Speaker",
    template_path: Optional[str] = None
) -> Tuple[str, str]:
    subj_tmpl, body_tmpl = load_template(template_path=template_path, category=category)
    first_name = get_first_name(speaker_name)
    sender = getattr(settings, "OUTREACH_SENDER_NAME", "Akash")
    sender_comp = getattr(settings, "OUTREACH_COMPANY", "Adople AI")

    ctx = SafeDict({
        "first_name": first_name,
        "name": first_name,
        "full_name": speaker_name or "there",
        "speaker_name": speaker_name or "there",
        "job_title": job_title or "Professional",
        "company": company or "your organization",
        "company_name": company or "your organization",
        "conference_name": conf_name or "the conference",
        "pitch_hook": pitch_hook or "",
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
def send_teams_reply_notification(speaker_name: str, email: str, conf_name: str, intent: str, sentiment: str, reply_text: str, contact_type: str = "Weekly Speaker"):
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
                        "text": f"📬 {contact_type} Email Reply: {intent.title()}",
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
                            {"title": f"{contact_type}:", "value": speaker_name or "-"},
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
        conference_id: str = "CONF-TEST-OUTREACH",
        category: str = "Speaker"
    ) -> Dict[str, Any]:
        """
        Sends a single test outreach email to a specified personal email address:
        - Renders email strictly using the role-specific pitch in template.txt.
        - Ensures an isolated test record in PostgreSQL and local/OneDrive Excel exists.
        - Dispatches via Microsoft Graph API (akash@adople.ai).
        - Tracks the conversation thread in outreach_state.json for reply monitoring.
        - Leaves ALL other real conference contacts completely untouched.
        """
        recipient_email = recipient_email.strip().lower()
        if "@" not in recipient_email or "." not in recipient_email or recipient_email.count("@") != 1:
            raise ValueError(f"Invalid recipient email address: '{recipient_email}'. An email must contain exactly one '@' (e.g. 'skjeeva2005@gmail.com').")

        subject, body = build_email_content(
            speaker_name=speaker_name,
            job_title="Keynote Speaker" if "speaker" in category.lower() else "Professional",
            company=company_name,
            conf_name=conference_name,
            category=category
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

        # Qualified Leads telemetry (score > 50)
        qualified_leads = self._load_qualified_leads()
        if qualified_leads:
            contacts_total = len(qualified_leads)
            contacts_pending = sum(1 for l in qualified_leads if str(l.get("outreach_status") or "").strip().lower() in ["pending", ""])
            contacts_sent = sum(1 for l in qualified_leads if str(l.get("outreach_status") or "").strip().lower() in ["sent", "sending"])
            contacts_replied = sum(1 for l in qualified_leads if str(l.get("outreach_status") or "").strip().lower() == "replied")
            outreach_source_name = "Qualified Leads sheet (score > 50)"
        else:
            # Fallback to Verified Data leads
            verified_leads = self._load_verified_data_leads()
            contacts_total = len(verified_leads)
            contacts_pending = sum(1 for l in verified_leads if str(l.get("outreach_status") or "").strip().lower() in ["pending", ""])
            contacts_sent = sum(1 for l in verified_leads if str(l.get("outreach_status") or "").strip().lower() in ["sent", "sending"])
            contacts_replied = sum(1 for l in verified_leads if str(l.get("outreach_status") or "").strip().lower() == "replied")
            outreach_source_name = "Verified Data sheet (tbl_verified_data)"

        # Historical Weekly Speakers metrics
        sent_speakers = self.db.query(WeeklySpeaker).filter(
            WeeklySpeaker.outreach_status == "sent"
        ).count()

        replied_speakers = self.db.query(WeeklySpeaker).filter(
            WeeklySpeaker.reply_status == "replied"
        ).count()

        return {
            "outreach_source": outreach_source_name,
            "mailbox": getattr(settings, "OUTREACH_MS_MAILBOX", "akash@adople.ai"),
            "campaign_active": getattr(settings, "OUTREACH_ACTIVE", False),
            "dry_run": getattr(settings, "OUTREACH_DRY_RUN", True),
            "teams_card_notifications": getattr(settings, "EMAIL_TEAMS_CARD_ENABLED", True),
            "gemini_model": getattr(settings, "OUTREACH_GEMINI_MODEL", "gemini-3.8-flash"),
            "scheduled_send_time": getattr(settings, "OUTREACH_SEND_TIME", "19:00"),
            "timezone": getattr(settings, "OUTREACH_TIMEZONE", "Asia/Kolkata"),
            "reply_watch_interval_minutes": getattr(settings, "OUTREACH_WATCH_INTERVAL_MINUTES", 1),
            "qualified_contacts_total": contacts_total,
            "qualified_contacts_pending": contacts_pending,
            "qualified_contacts_sent": contacts_sent,
            "qualified_contacts_replied": contacts_replied,
            "emails_sent_today": sent_today,
            "daily_cap": getattr(settings, "OUTREACH_DAILY_CAP", 0),
            "active_monitored_threads": len(state.get("threads", {})),
            "historical_weekly_speakers_sent": sent_speakers,
            "historical_weekly_speakers_replied": replied_speakers
        }

    def _load_qualified_leads(self) -> List[Dict[str, Any]]:
        """
        Loads all qualified leads (ICP score > 50) exclusively from 'Qualified Leads' worksheet / table.
        Primary source: OneDrive 'tbl_qualified_leads' or 'Qualified Leads'.
        Fallback: Local Excel 'Qualified Leads' sheet.
        """
        leads: List[Dict[str, Any]] = []

        def parse_qualified_matrix(col_map: Dict[str, int], raw_rows: List[Any], is_onedrive: bool = False) -> List[Dict[str, Any]]:
            parsed = []
            for idx, r in enumerate(raw_rows):
                if isinstance(r, dict):
                    v_raw = r.get("values", [])
                    vals = v_raw[0] if v_raw and isinstance(v_raw[0], list) else v_raw
                    row_idx = r.get("row_index", idx)
                else:
                    vals = list(r)
                    row_idx = idx

                if not isinstance(vals, (list, tuple)):
                    continue

                em_idx = col_map.get("professionalemail") or col_map.get("email")
                if em_idx is None or len(vals) <= em_idx:
                    continue

                email = str(vals[em_idx] or "").strip()
                if not email or "@" not in email or "." not in email:
                    continue

                # Strict requirement: only leads with score > 50.0
                score_idx = col_map.get("overallscore") or col_map.get("score")
                score_val = 0.0
                if score_idx is not None and len(vals) > score_idx:
                    try:
                        score_val = float(vals[score_idx] or 0.0)
                    except Exception:
                        score_val = 0.0
                if score_val <= 50.0:
                    continue

                c_type_idx = col_map.get("contacttype")
                cat_raw = str(vals[c_type_idx] or "Speaker").strip() if c_type_idx is not None and len(vals) > c_type_idx else "Speaker"
                cat_clean = normalize_category(cat_raw).capitalize()

                rank_idx = col_map.get("rank")
                qual_idx = col_map.get("qualificationstatus")
                comp_idx = col_map.get("companyname")
                dom_idx = col_map.get("companydomain")
                conf_idx = col_map.get("conferencename")
                cid_idx = col_map.get("conferenceid")
                name_idx = col_map.get("contactname") or col_map.get("name")
                title_idx = col_map.get("jobtitle")
                estat_idx = col_map.get("emailstatus")
                li_idx = col_map.get("personallinkedinurl")
                ind_idx = col_map.get("primaryindustry")
                tier_idx = col_map.get("headcounttier")

                ost_idx = col_map.get("outreachstatus")
                rep_idx = col_map.get("replystatus") or col_map.get("replaystatus")
                rec_idx = col_map.get("receivedreply") or col_map.get("receivedreplay")
                sent_idx = col_map.get("replysentiment") or col_map.get("sentiment")
                th_idx = col_map.get("threadid")
                snd_idx = col_map.get("sendmessage")

                parsed.append({
                    "row_index": row_idx,
                    "category": cat_clean,
                    "contact_type": f"Qualified {cat_clean}",
                    "rank": vals[rank_idx] if rank_idx is not None and len(vals) > rank_idx else 0,
                    "overall_score": score_val,
                    "qualification_status": str(vals[qual_idx] or "").strip() if qual_idx is not None and len(vals) > qual_idx else "MODERATE",
                    "company_name": str(vals[comp_idx] or "").strip() if comp_idx is not None and len(vals) > comp_idx else "",
                    "company_domain": str(vals[dom_idx] or "").strip() if dom_idx is not None and len(vals) > dom_idx else "",
                    "conference_name": str(vals[conf_idx] or "").strip() if conf_idx is not None and len(vals) > conf_idx else "",
                    "conference_id": str(vals[cid_idx] or "").strip() if cid_idx is not None and len(vals) > cid_idx else "",
                    "name": str(vals[name_idx] or "").strip() if name_idx is not None and len(vals) > name_idx else "",
                    "job_title": str(vals[title_idx] or "").strip() if title_idx is not None and len(vals) > title_idx else "",
                    "professional_email": email,
                    "email_status": str(vals[estat_idx] or "Verified").strip() if estat_idx is not None and len(vals) > estat_idx else "Verified",
                    "personal_linkedin_url": str(vals[li_idx] or "").strip() if li_idx is not None and len(vals) > li_idx else "",
                    "primary_industry": str(vals[ind_idx] or "").strip() if ind_idx is not None and len(vals) > ind_idx else "",
                    "headcount_tier": str(vals[tier_idx] or "").strip() if tier_idx is not None and len(vals) > tier_idx else "",
                    "outreach_status": str(vals[ost_idx] or "Pending").strip() if ost_idx is not None and len(vals) > ost_idx else "Pending",
                    "reply_status": str(vals[rep_idx] or "").strip() if rep_idx is not None and len(vals) > rep_idx else "",
                    "received_reply": str(vals[rec_idx] or "").strip() if rec_idx is not None and len(vals) > rec_idx else "",
                    "reply_sentiment": str(vals[sent_idx] or "").strip() if sent_idx is not None and len(vals) > sent_idx else "",
                    "thread_id": str(vals[th_idx] or "").strip() if th_idx is not None and len(vals) > th_idx else "",
                    "send_message": str(vals[snd_idx] or "").strip() if snd_idx is not None and len(vals) > snd_idx else "",
                    "source": "qualified_leads",
                    "raw_values": vals
                })
            return parsed

        # Primary: OneDrive Qualified Leads
        try:
            col_names, col_map, rows = self.onedrive.get_qualified_leads_table_info()
            if rows:
                leads = parse_qualified_matrix(col_map, rows, is_onedrive=True)
                if leads:
                    return leads
        except Exception as e:
            logger.warning(f"Notice reading OneDrive Qualified Leads: {e}. Reading Local Excel...")

        # Fallback: Local Excel 'Qualified Leads' sheet
        try:
            from openpyxl import load_workbook
            wb = load_workbook(self.local_excel_path, data_only=True)
            sheet_name = getattr(settings, "QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME", "Qualified Leads")
            if sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                raw_rows = list(ws.iter_rows(values_only=True))
                if len(raw_rows) > 1:
                    headers = [str(h).strip().lower().replace(" ", "").replace("_", "").replace("/", "") for h in raw_rows[0]]
                    col_map = {name: idx for idx, name in enumerate(headers)}
                    leads = parse_qualified_matrix(col_map, raw_rows[1:], is_onedrive=False)
            wb.close()
        except Exception as e:
            logger.error(f"Error reading Local Excel Qualified Leads: {e}")

        return leads

    def _load_non_qualified_leads(self) -> List[Dict[str, Any]]:
        """
        Loads all non-qualified / disqualified leads (ICP score <= 50) exclusively from 'Non -Qualified Leads' worksheet / table.
        Primary source: OneDrive 'tbl_non_qualified_leads' or 'Non -Qualified Leads'.
        Fallback: Local Excel 'Non -Qualified Leads' sheet (or 'Disqualified Leads').
        """
        leads: List[Dict[str, Any]] = []

        def parse_matrix(col_map: Dict[str, int], raw_rows: List[Any], is_onedrive: bool = False) -> List[Dict[str, Any]]:
            parsed = []
            for idx, r in enumerate(raw_rows):
                if isinstance(r, dict):
                    v_raw = r.get("values", [])
                    vals = v_raw[0] if v_raw and isinstance(v_raw[0], list) else v_raw
                    row_idx = r.get("row_index", idx)
                else:
                    vals = list(r)
                    row_idx = idx

                if not isinstance(vals, (list, tuple)):
                    continue

                em_idx = col_map.get("professionalemail") or col_map.get("email")
                if em_idx is None or len(vals) <= em_idx:
                    continue

                email = str(vals[em_idx] or "").strip()
                if not email or "@" not in email or "." not in email:
                    continue

                score_idx = col_map.get("overallscore") or col_map.get("score")
                score_val = 0.0
                if score_idx is not None and len(vals) > score_idx:
                    try:
                        score_val = float(vals[score_idx] or 0.0)
                    except Exception:
                        score_val = 0.0

                c_type_idx = col_map.get("contacttype")
                cat_raw = str(vals[c_type_idx] or "Speaker").strip() if c_type_idx is not None and len(vals) > c_type_idx else "Speaker"
                cat_clean = normalize_category(cat_raw).capitalize()

                rank_idx = col_map.get("rank")
                qual_idx = col_map.get("qualificationstatus")
                comp_idx = col_map.get("companyname")
                dom_idx = col_map.get("companydomain")
                conf_idx = col_map.get("conferencename")
                cid_idx = col_map.get("conferenceid")
                name_idx = col_map.get("contactname") or col_map.get("name")
                title_idx = col_map.get("jobtitle")
                estat_idx = col_map.get("emailstatus")
                li_idx = col_map.get("personallinkedinurl")
                ind_idx = col_map.get("primaryindustry")
                tier_idx = col_map.get("headcounttier")

                ost_idx = col_map.get("outreachstatus")
                rep_idx = col_map.get("replystatus") or col_map.get("replaystatus")
                rec_idx = col_map.get("receivedreply") or col_map.get("receivedreplay")
                sent_idx = col_map.get("replysentiment") or col_map.get("sentiment")
                th_idx = col_map.get("threadid")
                snd_idx = col_map.get("sendmessage")

                parsed.append({
                    "row_index": row_idx,
                    "category": cat_clean,
                    "contact_type": f"Disqualified {cat_clean}",
                    "rank": vals[rank_idx] if rank_idx is not None and len(vals) > rank_idx else 0,
                    "overall_score": score_val,
                    "qualification_status": str(vals[qual_idx] or "DISQUALIFIED").strip() if qual_idx is not None and len(vals) > qual_idx else "DISQUALIFIED",
                    "company_name": str(vals[comp_idx] or "").strip() if comp_idx is not None and len(vals) > comp_idx else "",
                    "company_domain": str(vals[dom_idx] or "").strip() if dom_idx is not None and len(vals) > dom_idx else "",
                    "conference_name": str(vals[conf_idx] or "").strip() if conf_idx is not None and len(vals) > conf_idx else "",
                    "conference_id": str(vals[cid_idx] or "").strip() if cid_idx is not None and len(vals) > cid_idx else "",
                    "name": str(vals[name_idx] or "").strip() if name_idx is not None and len(vals) > name_idx else "",
                    "job_title": str(vals[title_idx] or "").strip() if title_idx is not None and len(vals) > title_idx else "",
                    "professional_email": email,
                    "email_status": str(vals[estat_idx] or "Verified").strip() if estat_idx is not None and len(vals) > estat_idx else "Verified",
                    "personal_linkedin_url": str(vals[li_idx] or "").strip() if li_idx is not None and len(vals) > li_idx else "",
                    "primary_industry": str(vals[ind_idx] or "").strip() if ind_idx is not None and len(vals) > ind_idx else "",
                    "headcount_tier": str(vals[tier_idx] or "").strip() if tier_idx is not None and len(vals) > tier_idx else "",
                    "outreach_status": str(vals[ost_idx] or "Disqualified").strip() if ost_idx is not None and len(vals) > ost_idx else "Disqualified",
                    "reply_status": str(vals[rep_idx] or "").strip() if rep_idx is not None and len(vals) > rep_idx else "",
                    "received_reply": str(vals[rec_idx] or "").strip() if rec_idx is not None and len(vals) > rec_idx else "",
                    "reply_sentiment": str(vals[sent_idx] or "").strip() if sent_idx is not None and len(vals) > sent_idx else "",
                    "thread_id": str(vals[th_idx] or "").strip() if th_idx is not None and len(vals) > th_idx else "",
                    "send_message": str(vals[snd_idx] or "").strip() if snd_idx is not None and len(vals) > snd_idx else "",
                    "source": "non_qualified_leads",
                    "raw_values": vals
                })
            return parsed

        # Primary: OneDrive Non -Qualified Leads
        try:
            col_names, col_map, rows = self.onedrive.get_non_qualified_leads_table_info()
            if rows:
                leads = parse_matrix(col_map, rows, is_onedrive=True)
                if leads:
                    return leads
        except Exception as e:
            logger.debug(f"Notice reading OneDrive Non -Qualified Leads: {e}. Reading Local Excel...")

        # Fallback: Local Excel 'Non -Qualified Leads' sheet
        try:
            from openpyxl import load_workbook
            wb = load_workbook(self.local_excel_path, data_only=True)
            for sheet_candidate in [getattr(settings, "NON_QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME", "Non -Qualified Leads"), "Non -Qualified Leads", "Non-Qualified Leads", "Disqualified Leads"]:
                if sheet_candidate in wb.sheetnames:
                    ws = wb[sheet_candidate]
                    raw_rows = list(ws.iter_rows(values_only=True))
                    if len(raw_rows) > 1:
                        headers = [str(h).strip().lower().replace(" ", "").replace("_", "").replace("/", "") for h in raw_rows[0]]
                        col_map = {name: idx for idx, name in enumerate(headers)}
                        leads = parse_matrix(col_map, raw_rows[1:], is_onedrive=False)
                        if leads:
                            break
            wb.close()
        except Exception as e:
            logger.error(f"Error reading Local Excel Non -Qualified Leads: {e}")

        return leads

    def _update_qualified_leads_outreach(
        self,
        email: str,
        updates: Dict[str, Any],
        thread_id: Optional[str] = None,
        category: Optional[str] = None
    ):
        """
        Updates outreach tracking columns for a lead in 'Qualified Leads' / 'Non -Qualified Leads'
        across both OneDrive and Local Excel, and synchronizes with 'Verified Data' and the
        corresponding original Weekly sheet (Weekly Speakers, Weekly Attendees, or Weekly Exhibitors).
        """
        # 1. Update Qualified Leads on OneDrive
        try:
            self.onedrive.update_qualified_leads_contact(email=email, updates=updates, thread_id=thread_id)
        except Exception as e:
            logger.debug(f"Notice updating OneDrive Qualified Leads for {email}: {e}")

        # 2. Update Qualified Leads in Local Excel
        try:
            self.excel_mgr.update_qualified_leads_row_in_excel(email=email, updates=updates, thread_id=thread_id)
        except Exception as e:
            logger.debug(f"Notice updating Local Excel Qualified Leads for {email}: {e}")

        # 3. Update Non -Qualified Leads on OneDrive if present
        try:
            self.onedrive.update_non_qualified_leads_contact(email=email, updates=updates, thread_id=thread_id)
        except Exception as e:
            logger.debug(f"Notice updating OneDrive Non -Qualified Leads for {email}: {e}")

        # 4. Update Non -Qualified Leads in Local Excel if present
        try:
            self.excel_mgr.update_non_qualified_leads_row_in_excel(email=email, updates=updates, thread_id=thread_id)
        except Exception as e:
            logger.debug(f"Notice updating Local Excel Non -Qualified Leads for {email}: {e}")

        # 5. Keep Verified Data in sync
        try:
            self._update_verified_data_outreach(email=email, updates=updates, thread_id=thread_id, category=category)
        except Exception as e:
            logger.debug(f"Notice syncing Verified Data for {email}: {e}")

        # 6. Synchronize with the corresponding original Weekly sheet (Weekly Speakers, Weekly Attendees, Weekly Exhibitors)
        try:
            self._update_weekly_sheet_outreach(email=email, updates=updates, thread_id=thread_id, category=category)
        except Exception as e:
            logger.warning(f"Notice syncing Weekly sheet for {email}: {e}")

    def _update_weekly_sheet_outreach(
        self,
        email: str,
        updates: Dict[str, Any],
        thread_id: Optional[str] = None,
        category: Optional[str] = None
    ):
        """
        Updates outreach tracking columns in the corresponding original Weekly sheet
        ('weekly_speakers', 'weekly_attendees', or 'weekly_exhibitors') across both
        OneDrive Excel and Local Excel.
        """
        clean_email = (email or "").strip().lower()
        clean_thread = (thread_id or updates.get("Thread ID") or updates.get("thread_id") or "").strip()
        if not clean_email and not clean_thread:
            return

        outreach_status = updates.get("Outreach Status") or updates.get("outreach_status") or ""
        reply_status = updates.get("Reply Status") or updates.get("reply_status") or ""
        reply_sentiment = updates.get("Reply Sentiment") or updates.get("reply_sentiment") or updates.get("Sentiment") or ""
        received_reply = updates.get("Received Reply") or updates.get("received_reply") or ""
        sent_message = updates.get("Send Message") or updates.get("sent_message") or ""

        # Determine target categories
        norm_cat = normalize_category(category) if category else ""
        
        is_spk = (norm_cat == "speaker")
        is_att = (norm_cat == "attendee")
        is_exh = (norm_cat == "exhibitor")

        # If category is unspecified, detect from database
        if not is_spk and not is_att and not is_exh:
            if clean_email:
                is_spk = bool(self.db.query(WeeklySpeaker).filter(func.lower(WeeklySpeaker.professional_email) == clean_email).first())
                is_att = bool(self.db.query(WeeklyAttendee).filter(func.lower(WeeklyAttendee.professional_email) == clean_email).first())
                is_exh = bool(self.db.query(WeeklyExhibitor).filter(func.lower(WeeklyExhibitor.professional_email) == clean_email).first())
            if not is_spk and not is_att and not is_exh:
                is_spk = True  # Default to speaker

        # =====================================================================
        # 1. Update Weekly Speakers (Cols 15-20 in tbl_weekly_speakers / weekly_speakers)
        # =====================================================================
        if is_spk:
            try:
                # A. OneDrive tbl_weekly_speakers
                spk_map = self.onedrive.get_existing_weekly_speaker_rows_map()
                for (k_cid, k_name), (row_idx, cur_vals) in spk_map.items():
                    r_em = str(cur_vals[8] if len(cur_vals) > 8 else "").strip().lower()
                    r_th = str(cur_vals[19] if len(cur_vals) > 19 else "").strip()
                    if (clean_email and r_em == clean_email) or (clean_thread and r_th == clean_thread):
                        new_vals = list(cur_vals)
                        while len(new_vals) < 20:
                            new_vals.append("")
                        if outreach_status: new_vals[14] = outreach_status
                        if reply_status: new_vals[15] = reply_status
                        if reply_sentiment: new_vals[16] = reply_sentiment
                        if received_reply: new_vals[17] = received_reply
                        if sent_message: new_vals[18] = sent_message
                        if clean_thread: new_vals[19] = clean_thread
                        self.onedrive.update_weekly_speaker_row(row_idx, new_vals)
                        logger.info(f"✅ OneDrive tbl_weekly_speakers row {row_idx} synced for {clean_email or clean_thread}.")
                        break

                # B. Local Excel weekly_speakers
                if self.local_excel_path.exists():
                    wb = openpyxl.load_workbook(self.local_excel_path)
                    if "weekly_speakers" in wb.sheetnames:
                        ws = wb["weekly_speakers"]
                        for r in range(2, ws.max_row + 1):
                            r_em = str(ws.cell(row=r, column=9).value or "").strip().lower()
                            r_th = str(ws.cell(row=r, column=20).value or "").strip()
                            if (clean_email and r_em == clean_email) or (clean_thread and r_th == clean_thread):
                                if outreach_status: ws.cell(row=r, column=15, value=outreach_status)
                                if reply_status: ws.cell(row=r, column=16, value=reply_status)
                                if reply_sentiment: ws.cell(row=r, column=17, value=reply_sentiment)
                                if received_reply: ws.cell(row=r, column=18, value=received_reply)
                                if sent_message: ws.cell(row=r, column=19, value=sent_message)
                                if clean_thread: ws.cell(row=r, column=20, value=clean_thread)
                                wb.save(self.local_excel_path)
                                logger.info(f"✅ Local Excel weekly_speakers row {r} synced for {clean_email or clean_thread}.")
                                break
            except Exception as e:
                logger.warning(f"Notice updating Weekly Speakers for {clean_email}: {e}")

        # =====================================================================
        # 2. Update Weekly Attendees (Cols 11-16 in tbl_weekly_attendees / weekly_attendees)
        # =====================================================================
        if is_att:
            try:
                # A. OneDrive tbl_weekly_attendees
                att_map = self.onedrive.get_existing_weekly_attendee_rows_map()
                for (k_conf, k_name), (row_idx, cur_vals) in att_map.items():
                    r_em = str(cur_vals[5] if len(cur_vals) > 5 else "").strip().lower()
                    r_th = str(cur_vals[15] if len(cur_vals) > 15 else "").strip()
                    if (clean_email and r_em == clean_email) or (clean_thread and r_th == clean_thread):
                        new_vals = list(cur_vals)
                        while len(new_vals) < 16:
                            new_vals.append("")
                        if outreach_status: new_vals[10] = outreach_status
                        if reply_status: new_vals[11] = reply_status
                        if reply_sentiment: new_vals[12] = reply_sentiment
                        if received_reply: new_vals[13] = received_reply
                        if sent_message: new_vals[14] = sent_message
                        if clean_thread: new_vals[15] = clean_thread
                        self.onedrive.update_weekly_attendee_row(row_idx, new_vals)
                        logger.info(f"✅ OneDrive tbl_weekly_attendees row {row_idx} synced for {clean_email or clean_thread}.")
                        break

                # B. Local Excel weekly_attendees
                if self.local_excel_path.exists():
                    wb = openpyxl.load_workbook(self.local_excel_path)
                    if "weekly_attendees" in wb.sheetnames:
                        ws = wb["weekly_attendees"]
                        for r in range(2, ws.max_row + 1):
                            r_em = str(ws.cell(row=r, column=6).value or "").strip().lower()
                            r_th = str(ws.cell(row=r, column=16).value or "").strip()
                            if (clean_email and r_em == clean_email) or (clean_thread and r_th == clean_thread):
                                if outreach_status: ws.cell(row=r, column=11, value=outreach_status)
                                if reply_status: ws.cell(row=r, column=12, value=reply_status)
                                if reply_sentiment: ws.cell(row=r, column=13, value=reply_sentiment)
                                if received_reply: ws.cell(row=r, column=14, value=received_reply)
                                if sent_message: ws.cell(row=r, column=15, value=sent_message)
                                if clean_thread: ws.cell(row=r, column=16, value=clean_thread)
                                wb.save(self.local_excel_path)
                                logger.info(f"✅ Local Excel weekly_attendees row {r} synced for {clean_email or clean_thread}.")
                                break
            except Exception as e:
                logger.warning(f"Notice updating Weekly Attendees for {clean_email}: {e}")

        # =====================================================================
        # 3. Update Weekly Exhibitors (Cols 16-21 in weekly_exhibitors / weekly_exhibitors)
        # =====================================================================
        if is_exh:
            try:
                # A. OneDrive weekly_exhibitors
                exh_map = self.onedrive.get_existing_weekly_exhibitor_rows_map()
                for (k_conf, k_comp), (row_idx, cur_vals) in exh_map.items():
                    r_em = str(cur_vals[9] if len(cur_vals) > 9 else "").strip().lower()
                    r_th = str(cur_vals[20] if len(cur_vals) > 20 else "").strip()
                    if (clean_email and r_em == clean_email) or (clean_thread and r_th == clean_thread):
                        new_vals = list(cur_vals)
                        while len(new_vals) < 21:
                            new_vals.append("")
                        if outreach_status: new_vals[15] = outreach_status
                        if reply_status: new_vals[16] = reply_status
                        if reply_sentiment: new_vals[17] = reply_sentiment
                        if received_reply: new_vals[18] = received_reply
                        if sent_message: new_vals[19] = sent_message
                        if clean_thread: new_vals[20] = clean_thread
                        self.onedrive.update_weekly_exhibitor_row(row_idx, new_vals)
                        logger.info(f"✅ OneDrive weekly_exhibitors row {row_idx} synced for {clean_email or clean_thread}.")
                        break

                # B. Local Excel weekly_exhibitors
                if self.local_excel_path.exists():
                    wb = openpyxl.load_workbook(self.local_excel_path)
                    if "weekly_exhibitors" in wb.sheetnames:
                        ws = wb["weekly_exhibitors"]
                        for r in range(2, ws.max_row + 1):
                            r_em = str(ws.cell(row=r, column=10).value or "").strip().lower()
                            r_th = str(ws.cell(row=r, column=21).value or "").strip()
                            if (clean_email and r_em == clean_email) or (clean_thread and r_th == clean_thread):
                                if outreach_status: ws.cell(row=r, column=16, value=outreach_status)
                                if reply_status: ws.cell(row=r, column=17, value=reply_status)
                                if reply_sentiment: ws.cell(row=r, column=18, value=reply_sentiment)
                                if received_reply: ws.cell(row=r, column=19, value=received_reply)
                                if sent_message: ws.cell(row=r, column=20, value=sent_message)
                                if clean_thread: ws.cell(row=r, column=21, value=clean_thread)
                                wb.save(self.local_excel_path)
                                logger.info(f"✅ Local Excel weekly_exhibitors row {r} synced for {clean_email or clean_thread}.")
                                break
            except Exception as e:
                logger.warning(f"Notice updating Weekly Exhibitors for {clean_email}: {e}")

    def _load_verified_data_leads(self) -> List[Dict[str, Any]]:
        """
        Loads all verified contacts exclusively from the 'Verified Data' sheet / table.
        Supports both the 37-column company-grouped layout (Speakers, Attendees, Exhibitors)
        and fallback 17-column layout.
        Primary source: OneDrive 'tbl_verified_data'.
        Fallback: Local Excel 'Verified Data' sheet.
        """
        leads: List[Dict[str, Any]] = []

        def parse_matrix(col_map: Dict[str, int], raw_rows: List[Any], is_onedrive: bool = False) -> List[Dict[str, Any]]:
            parsed = []
            is_grouped_37 = any(k in col_map for k in ["speakerprofessionalemail", "attendeeprofessionalemail", "exhibitorprofessionalemail"])

            for idx, r in enumerate(raw_rows):
                vals = r.get("values", [[]])[0] if is_onedrive else list(r)
                row_idx = r.get("row_index", idx) if is_onedrive else idx

                if is_grouped_37:
                    comp = str(vals[col_map.get("companyname", 0)] or "").strip() if len(vals) > col_map.get("companyname", 0) else ""
                    dom = str(vals[col_map.get("companydomain", 1)] or "").strip() if len(vals) > col_map.get("companydomain", 1) else ""
                    conf = str(vals[col_map.get("conferencename", 2)] or "").strip() if len(vals) > col_map.get("conferencename", 2) else ""
                    cid = str(vals[col_map.get("conferenceid", 3)] or "").strip() if len(vals) > col_map.get("conferenceid", 3) else ""

                    categories = [
                        ("Speaker", "speakername", "speakerjobtitle", "speakerlinkedin", "speakerprofessionalemail", "speakeremailstatus", "speakeroutreachstatus", "speakerreplystatus", "speakerreceivedreply", "speakersentiment", "speakersentmessage", "speakerthreadid"),
                        ("Attendee", "attendeename", "attendeejobtitle", "attendeelinkedin", "attendeeprofessionalemail", "attendeeemailstatus", "attendeeoutreachstatus", "attendeereplystatus", "attendeereceivedreply", "attendeesentiment", "attendeesentmessage", "attendeethreadid"),
                        ("Exhibitor", "exhibitorname", "exhibitorjobtitle", "exhibitorlinkedin", "exhibitorprofessionalemail", "exhibitoremailstatus", "exhibitoroutreachstatus", "exhibitorreplystatus", "exhibitorreceivedreply", "exhibitorsentiment", "exhibitorsentmessage", "exhibitorthreadid")
                    ]

                    for cat_name, n_k, t_k, li_k, em_k, st_k, ost_k, rep_k, rec_k, sent_k, snd_k, th_k in categories:
                        em_col = col_map.get(em_k)
                        if em_col is not None and len(vals) > em_col:
                            email = str(vals[em_col] or "").strip()
                            st_col = col_map.get(st_k)
                            status = str(vals[st_col] or "").strip().lower() if st_col is not None and len(vals) > st_col else ""

                            if email and "@" in email and (status == "verified" or not status):
                                ost_col = col_map.get(ost_k)
                                rep_col = col_map.get(rep_k)
                                rec_col = col_map.get(rec_k)
                                sent_col = col_map.get(sent_k)
                                snd_col = col_map.get(snd_k)
                                th_col = col_map.get(th_k)
                                n_col = col_map.get(n_k)
                                t_col = col_map.get(t_k)
                                li_col = col_map.get(li_k)

                                parsed.append({
                                    "row_index": row_idx,
                                    "category": cat_name,
                                    "contact_type": f"Verified {cat_name}",
                                    "company_name": comp,
                                    "company_domain": dom,
                                    "conference_name": conf,
                                    "conference_id": cid,
                                    "name": str(vals[n_col] or "").strip() if n_col is not None and len(vals) > n_col else "",
                                    "job_title": str(vals[t_col] or "").strip() if t_col is not None and len(vals) > t_col else "",
                                    "personal_linkedin_url": str(vals[li_col] or "").strip() if li_col is not None and len(vals) > li_col else "",
                                    "professional_email": email,
                                    "email_status": "Verified",
                                    "outreach_status": str(vals[ost_col] or "").strip() if ost_col is not None and len(vals) > ost_col else "Pending",
                                    "reply_status": str(vals[rep_col] or "").strip() if rep_col is not None and len(vals) > rep_col else "",
                                    "received_reply": str(vals[rec_col] or "").strip() if rec_col is not None and len(vals) > rec_col else "",
                                    "reply_sentiment": str(vals[sent_col] or "").strip() if sent_col is not None and len(vals) > sent_col else "",
                                    "send_message": str(vals[snd_col] or "").strip() if snd_col is not None and len(vals) > snd_col else "",
                                    "thread_id": str(vals[th_col] or "").strip() if th_col is not None and len(vals) > th_col else "",
                                    "raw_values": vals
                                })
                else:
                    # Legacy 17-column format
                    em_idx = col_map.get("professionalemail")
                    if em_idx is not None and len(vals) > em_idx:
                        email = str(vals[em_idx] or "").strip()
                        if email and "@" in email:
                            c_type_idx = col_map.get("contacttype", 0)
                            conf_idx = col_map.get("conferencename", 1)
                            name_idx = col_map.get("name", 2)
                            title_idx = col_map.get("jobtitledesignation", 3)
                            comp_idx = col_map.get("companyname", 4)
                            estat_idx = col_map.get("emailstatus", 6)
                            ost_idx = col_map.get("outreachstatus", 10)
                            rep_idx = col_map.get("replaystatus", 11)
                            sent_idx = col_map.get("replaysentiment", 12)
                            rec_idx = col_map.get("receivedreplay", 13)
                            snd_idx = col_map.get("sendmessage", 14)
                            th_idx = col_map.get("threadid", 15)

                            parsed.append({
                                "row_index": row_idx,
                                "category": "Speaker",
                                "contact_type": str(vals[c_type_idx] or "").strip() if len(vals) > c_type_idx else "Speaker",
                                "company_name": str(vals[comp_idx] or "").strip() if len(vals) > comp_idx else "",
                                "company_domain": "",
                                "conference_name": str(vals[conf_idx] or "").strip() if len(vals) > conf_idx else "",
                                "conference_id": "",
                                "name": str(vals[name_idx] or "").strip() if len(vals) > name_idx else "",
                                "job_title": str(vals[title_idx] or "").strip() if len(vals) > title_idx else "",
                                "professional_email": email,
                                "email_status": str(vals[estat_idx] or "").strip() if len(vals) > estat_idx else "Verified",
                                "outreach_status": str(vals[ost_idx] or "").strip() if len(vals) > ost_idx else "Pending",
                                "reply_status": str(vals[rep_idx] or "").strip() if len(vals) > rep_idx else "",
                                "received_reply": str(vals[rec_idx] or "").strip() if len(vals) > rec_idx else "",
                                "reply_sentiment": str(vals[sent_idx] or "").strip() if len(vals) > sent_idx else "",
                                "send_message": str(vals[snd_idx] or "").strip() if len(vals) > snd_idx else "",
                                "thread_id": str(vals[th_idx] or "").strip() if len(vals) > th_idx else "",
                                "raw_values": vals
                            })

            return parsed

        # Primary: OneDrive tbl_verified_data
        try:
            col_names, col_map, rows = self.onedrive.get_verified_data_table_info()
            if rows:
                leads = parse_matrix(col_map, rows, is_onedrive=True)
                if leads:
                    return leads
        except Exception as e:
            logger.warning(f"Notice reading OneDrive tbl_verified_data: {e}. Reading Local Excel...")

        # Fallback: Local Excel 'Verified Data' sheet
        try:
            from openpyxl import load_workbook
            wb = load_workbook(self.local_excel_path, data_only=True)
            if "Verified Data" in wb.sheetnames:
                ws = wb["Verified Data"]
                raw_rows = list(ws.iter_rows(values_only=True))
                if len(raw_rows) > 1:
                    headers = [str(h).strip().lower().replace(" ", "").replace("_", "").replace("/", "") for h in raw_rows[0]]
                    col_map = {name: idx for idx, name in enumerate(headers)}
                    leads = parse_matrix(col_map, raw_rows[1:], is_onedrive=False)
        except Exception as e:
            logger.error(f"Error reading Local Excel Verified Data: {e}")

        return leads

    def _update_verified_data_outreach(
        self,
        email: str,
        updates: Dict[str, Any],
        thread_id: Optional[str] = None,
        category: Optional[str] = None
    ):
        """
        Updates outreach columns for a contact in both OneDrive 'tbl_verified_data' and Local Excel 'Verified Data'.
        """
        # 1. Update OneDrive
        try:
            self.onedrive.update_verified_data_contact(email=email, updates=updates, thread_id=thread_id, category=category)
        except Exception as e:
            logger.warning(f"Error updating OneDrive tbl_verified_data for {email}: {e}")

        # 2. Update Local Excel
        try:
            self.excel_mgr.update_verified_data_row_in_excel(email=email, updates=updates, thread_id=thread_id, category=category)
        except Exception as e:
            logger.warning(f"Error updating Local Excel Verified Data for {email}: {e}")

    def _sync_db_outreach_status(self, email: str, status: str, thread_id: str = "", full_message: str = ""):
        """Synchronizes outreach status to underlying DB models if the contact originated there."""
        try:
            clean_email = (email or "").strip().lower()
            spk = self.db.query(WeeklySpeaker).filter(func.lower(WeeklySpeaker.professional_email) == clean_email).first()
            if spk:
                spk.outreach_status = status
                if thread_id:
                    spk.email_thread_id = thread_id
                if full_message:
                    spk.sent_message = full_message
                spk.email_sent_at = datetime.utcnow()
                self.db.commit()

            att = self.db.query(WeeklyAttendee).filter(func.lower(WeeklyAttendee.professional_email) == clean_email).first()
            if att and hasattr(att, "outreach_status"):
                att.outreach_status = status
                self.db.commit()

            exh = self.db.query(WeeklyExhibitor).filter(func.lower(WeeklyExhibitor.professional_email) == clean_email).first()
            if exh and hasattr(exh, "outreach_status"):
                exh.outreach_status = status
                self.db.commit()
        except Exception as e:
            logger.debug(f"DB entity sync notice for {email}: {e}")

    def run_outreach_send_pass(self, force: bool = False, dry_run_override: Optional[bool] = None) -> Dict[str, Any]:
        """
        Executes outreach email campaign exclusively using records from the Qualified Leads sheet (ICP score > 50).
        - Strictly filters out any leads with ICP score <= 50.
        - Enforces deliverability (email_status == Verified).
        - Selects template from template.txt based on contact type:
          * Speakers -> Speakers template
          * Attendees -> Attendees template
          * Exhibitors -> Exhibitors template
        - Dispatches email via Microsoft Graph (akash@adople.ai).
        - Tracks Outreach Status, Send Message, and Thread ID in Qualified Leads (and syncs Verified Data).
        """
        with outreach_lock:
            if dry_run_override is not None:
                dry_run = dry_run_override
            else:
                dry_run = getattr(settings, "OUTREACH_DRY_RUN", True)
            active = getattr(settings, "OUTREACH_ACTIVE", False)
            if not force and not active and not dry_run:
                logger.info("Outreach is not active (OUTREACH_ACTIVE=false). Pass skipped.")
                return {"status": "inactive", "message": "Outreach inactive awaiting configuration/trigger."}

            state = load_state()
            sent_today = get_sent_today(state)
            daily_cap = getattr(settings, "OUTREACH_DAILY_CAP", 0)

            # 1. Load leads exclusively from Qualified Leads sheet (ICP score > 50)
            leads = self._load_qualified_leads()
            source_display = "Qualified Leads sheet (score > 50)"
            if not leads:
                logger.warning("No leads found in Qualified Leads sheet. Falling back to Verified Data sheet...")
                leads = self._load_verified_data_leads()
                source_display = "Verified Data sheet"

            logger.info(f"🚀 Starting Outreach Send Pass from '{source_display}' (DRY_RUN={dry_run}, Leads={len(leads)})...")

            sent_count = 0
            skipped_count = 0
            preview_list = []

            for lead in leads:
                email = (lead.get("professional_email") or "").strip().lower()
                if "@" not in email or "." not in email:
                    skipped_count += 1
                    continue

                em_status = (lead.get("email_status") or "").strip().lower()
                if em_status != "verified":
                    skipped_count += 1
                    continue

                # Strict Requirement 3: Do not send emails to leads scoring 50 or below
                score_val = float(lead.get("overall_score") or 0.0)
                if score_val > 0 and score_val <= 50.0:
                    skipped_count += 1
                    continue

                outreach_st = (lead.get("outreach_status") or "").strip().lower()
                if outreach_st in ("sent", "sending", "replied", "bounced", "do_not_contact", "failed"):
                    skipped_count += 1
                    continue

                # Check state sent_log to avoid duplicates
                already_sent = any(s.get("email") == email and s.get("status") == "sent" for s in state.get("sent_log", []))
                if already_sent:
                    skipped_count += 1
                    continue

                if daily_cap > 0 and sent_today >= daily_cap:
                    logger.info(f"Daily cap ({daily_cap}) reached.")
                    break

                name = lead.get("name") or "there"
                job_title = lead.get("job_title") or "Professional"
                company = lead.get("company_name") or "your organization"
                conf_name = lead.get("conference_name") or "the upcoming conference"
                cat_lead = lead.get("category", "Speaker")
                c_type = lead.get("contact_type") or f"Qualified {cat_lead}"

                subject, body = build_email_content(
                    speaker_name=name,
                    job_title=job_title,
                    company=company,
                    conf_name=conf_name,
                    category=cat_lead
                )
                full_message = f"Subject: {subject}\n\n{body}"

                if dry_run:
                    preview_list.append({
                        "contact_type": c_type,
                        "name": name,
                        "email": email,
                        "company": company,
                        "conference": conf_name,
                        "score": score_val,
                        "subject": subject,
                        "body_preview": body[:120]
                    })
                    sent_count += 1
                    sent_today += 1
                    logger.info(f"[DRY RUN PREVIEW] Would send to [{c_type}] (Score {score_val}): {name} <{email}> ({company})")
                    continue

                # Live Sending Logic
                try:
                    cat_lead = lead.get("category", "Speaker")
                    logger.info(f"📤 Dispatching outreach email to [{c_type}] {name} <{email}>...")
                    # Update status to sending in Qualified Leads (and sync Verified Data)
                    self._update_qualified_leads_outreach(email=email, updates={"Outreach Status": "sending", "Send Message": full_message}, category=cat_lead)

                    msg_id, conversation_id = self.graph.send_mail(email, subject, body)

                    # Update status to sent, record thread id and message in Qualified Leads (and sync Verified Data)
                    sent_updates = {
                        "Outreach Status": "sent",
                        "Send Message": full_message,
                        "Thread ID": conversation_id
                    }
                    self._update_qualified_leads_outreach(email=email, updates=sent_updates, thread_id=conversation_id, category=cat_lead)

                    # Record in state
                    dedupe_key = f"{email}|{conf_name.lower()}"
                    fresh_state = load_state()
                    fresh_state.setdefault("sent_log", []).append({
                        "email": email,
                        "conference_name": conf_name,
                        "name": name,
                        "contact_type": c_type,
                        "category": cat_lead,
                        "score": score_val,
                        "sent_at": now_iso(),
                        "status": "sent"
                    })
                    fresh_state.setdefault("threads", {})[dedupe_key] = {
                        "thread_id": conversation_id,
                        "message_id": msg_id,
                        "name": name,
                        "email": email,
                        "company": company,
                        "conference": conf_name,
                        "contact_type": c_type,
                        "category": cat_lead,
                        "score": score_val,
                        "source": "qualified_leads",
                        "sent_at": now_iso()
                    }
                    save_state(fresh_state)

                    # Sync DB entity if present
                    self._sync_db_outreach_status(email=email, status="sent", thread_id=conversation_id, full_message=full_message)

                    sent_count += 1
                    sent_today += 1
                    logger.info(f"✅ Dispatched email to [{c_type}]: {name} <{email}>")

                    delay = random.randint(getattr(settings, "OUTREACH_DELAY_MIN", 60), getattr(settings, "OUTREACH_DELAY_MAX", 120))
                    time.sleep(delay)

                except Exception as e:
                    logger.error(f"❌ Failed to send to {email}: {e}")
                    self._update_qualified_leads_outreach(email=email, updates={"Outreach Status": "failed"}, category=cat_lead)

            return {
                "status": "completed",
                "outreach_source": source_display,
                "dry_run": dry_run,
                "sent_count": sent_count,
                "skipped_count": skipped_count,
                "previews": preview_list
            }

    def poll_replies(self) -> Dict[str, Any]:
        """
        Polls mailbox akash@adople.ai for new incoming replies:
        - Runs 24/7 every 60s without interrupting existing workflows.
        - Identifies whether incoming messages belong to:
          1. Previously contacted Weekly Speakers (routes to Weekly Speakers & Speakers Replies).
          2. Contacts reached out via Qualified Leads sheet (routes to Qualified Leads & Verified Data).
          3. Contacts reached out via Verified Data sheet (routes to Verified Data).
        - Captures full back-and-forth transcript into 'Received Reply'.
        - Performs Gemini sentiment & intent analysis.
        - Sends exactly ONE Microsoft Teams Adaptive Card per new reply.
        - Prevents duplicate Teams cards using message ID tracking.
        - Updates Qualified Leads and original sheets in-place.
        """
        state = load_state()
        threads = state.get("threads", {})
        processed_ids = set(state.get("processed_reply_ids", []))
        new_replies_count = 0
        bounces_count = 0

        # 1. Previously contacted Weekly Speakers
        sent_speakers = self.db.query(WeeklySpeaker).filter(
            (WeeklySpeaker.outreach_status.in_(["sent", "replied"])) | (WeeklySpeaker.email_thread_id.isnot(None))
        ).all()
        speaker_by_thread = {s.email_thread_id: s for s in sent_speakers if s.email_thread_id}
        speaker_by_email = {(s.professional_email or "").strip().lower(): s for s in sent_speakers if s.professional_email}

        # 2. Qualified Leads contacts
        qualified_leads = self._load_qualified_leads()
        qualified_by_thread = {l["thread_id"]: l for l in qualified_leads if l.get("thread_id")}
        qualified_by_email = {l["professional_email"].lower(): l for l in qualified_leads if l.get("professional_email")}

        # 3. Non -Qualified Leads contacts
        non_qualified_leads = self._load_non_qualified_leads()
        non_qualified_by_thread = {l["thread_id"]: l for l in non_qualified_leads if l.get("thread_id")}
        non_qualified_by_email = {l["professional_email"].lower(): l for l in non_qualified_leads if l.get("professional_email")}

        # 4. Verified Data contacts
        verified_leads = self._load_verified_data_leads()
        verified_by_thread = {l["thread_id"]: l for l in verified_leads if l.get("thread_id")}
        verified_by_email = {l["professional_email"].lower(): l for l in verified_leads if l.get("professional_email")}

        for k, th in threads.items():
            t_id = th.get("thread_id")
            em = th.get("email") or k.split("|")[0]
            if t_id and t_id not in qualified_by_thread and t_id not in non_qualified_by_thread and t_id not in verified_by_thread:
                qualified_by_thread[t_id] = {
                    "professional_email": em,
                    "name": th.get("name", ""),
                    "company_name": th.get("company", ""),
                    "conference_name": th.get("conference", ""),
                    "contact_type": th.get("contact_type", "Contact"),
                    "thread_id": t_id
                }
            if em and em.lower() not in qualified_by_email and em.lower() not in non_qualified_by_email and em.lower() not in verified_by_email:
                qualified_by_email[em.lower()] = {
                    "professional_email": em,
                    "name": th.get("name", ""),
                    "company_name": th.get("company", ""),
                    "conference_name": th.get("conference", ""),
                    "contact_type": th.get("contact_type", "Contact"),
                    "thread_id": t_id or ""
                }

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
            body_text = extract_body_text_ms(msg)

            # Accurate, robust NDR and bounce detection
            is_bounce = is_bounce_email(msg, body_text)
            bounced_recipient = extract_bounce_recipient(msg, body_text) if is_bounce else None

            # Identify target: check Weekly Speakers first, then Qualified Leads, Non -Qualified Leads, Verified Data
            target_speaker = (
                speaker_by_thread.get(conv_id) 
                or (speaker_by_email.get(bounced_recipient) if bounced_recipient else None)
                or speaker_by_email.get(from_addr)
            )
            qualified_target = (
                qualified_by_thread.get(conv_id)
                or (qualified_by_email.get(bounced_recipient) if bounced_recipient else None)
                or qualified_by_email.get(from_addr)
            )
            non_qualified_target = (
                non_qualified_by_thread.get(conv_id)
                or (non_qualified_by_email.get(bounced_recipient) if bounced_recipient else None)
                or non_qualified_by_email.get(from_addr)
            )
            verified_target = (
                verified_by_thread.get(conv_id)
                or (verified_by_email.get(bounced_recipient) if bounced_recipient else None)
                or verified_by_email.get(from_addr)
            )

            if not target_speaker and not qualified_target and not non_qualified_target and not verified_target:
                # Unrelated email - ignore safely
                continue

            # IMMEDIATELY claim this message ID in memory and disk before any processing begins
            processed_ids.add(msg_id)
            mark_reply_processed(msg_id)

            contact_name = (
                target_speaker.speaker_name if target_speaker 
                else (qualified_target.get("name") if qualified_target 
                else (non_qualified_target.get("name") if non_qualified_target
                else (verified_target.get("name") if verified_target else "Contact")))
            )
            company_name = (
                target_speaker.company_name if target_speaker 
                else (qualified_target.get("company_name") if qualified_target 
                else (non_qualified_target.get("company_name") if non_qualified_target
                else (verified_target.get("company_name") if verified_target else "")))
            )
            conf_name = (
                target_speaker.conference_name if target_speaker 
                else (qualified_target.get("conference_name") if qualified_target 
                else (non_qualified_target.get("conference_name") if non_qualified_target
                else (verified_target.get("conference_name") if verified_target else "")))
            )
            contact_type = (
                "Weekly Speaker" if target_speaker 
                else (qualified_target.get("contact_type") if qualified_target 
                else (non_qualified_target.get("contact_type") if non_qualified_target
                else (verified_target.get("contact_type") if verified_target else "Verified Contact")))
            )
            contact_email = (
                target_speaker.professional_email if (target_speaker and target_speaker.professional_email)
                else (qualified_target.get("professional_email") if (qualified_target and qualified_target.get("professional_email"))
                else (non_qualified_target.get("professional_email") if (non_qualified_target and non_qualified_target.get("professional_email"))
                else (verified_target.get("professional_email") if (verified_target and verified_target.get("professional_email"))
                else (bounced_recipient or from_addr))))
            )

            # Ensure both speaker and qualified/non-qualified leads targets are resolved if contact exists across lists
            if target_speaker and not qualified_target:
                qualified_target = qualified_by_thread.get(conv_id) or (qualified_by_email.get(contact_email.lower()) if contact_email else None)
            if target_speaker and not non_qualified_target:
                non_qualified_target = non_qualified_by_thread.get(conv_id) or (non_qualified_by_email.get(contact_email.lower()) if contact_email else None)
            if target_speaker and not verified_target:
                verified_target = verified_by_thread.get(conv_id) or (verified_by_email.get(contact_email.lower()) if contact_email else None)

            # Fetch full conversation thread to build chronological transcript
            thread_msgs = self.graph.get_conversation_messages(conv_id) if conv_id else [msg]
            transcript = build_conversation_transcript_ms(thread_msgs, self.graph.mailbox, contact_name)

            sentiment = "Negative" if is_bounce else "Neutral"
            intent = "BOUNCE" if is_bounce else "OTHER"

            if is_bounce:
                bounces_count += 1
                logger.info(f"🚫 Bounce/NDR detected for [{contact_type}] {contact_name} <{contact_email}>. Teams notification card suppressed.")
            else:
                logger.info(f"📬 Incoming reply detected from [{contact_type}] {contact_name} <{contact_email}>!")
                analysis = self.gemini.analyze_reply(
                    body_text,
                    name=contact_name,
                    company=company_name,
                    conf=conf_name
                )
                intent = analysis.get("intent", "OTHER")
                sentiment = analysis.get("sentiment", "Neutral")
                new_replies_count += 1

                # Send exactly ONE Teams notification card per genuine reply
                send_teams_reply_notification(
                    speaker_name=contact_name,
                    email=contact_email,
                    conf_name=conf_name,
                    intent=intent,
                    sentiment=sentiment,
                    reply_text=body_text,
                    contact_type=contact_type
                )

            received_at_str = msg.get("receivedDateTime") or datetime.utcnow().isoformat()

            # -----------------------------------------------------------------
            # 1. Update Weekly Speakers if contact originated there
            # -----------------------------------------------------------------
            if target_speaker:
                target_speaker.reply_status = "bounced" if is_bounce else "replied"
                target_speaker.reply_sentiment = sentiment
                target_speaker.received_reply = transcript if not is_bounce else "BOUNCE: Undeliverable address"
                self.db.commit()
                self._update_onedrive_speaker_row(target_speaker)

                # Only log genuine prospect replies into tbl_speakers_replies
                if getattr(settings, "SPEAKER_REPLIES_ENABLED", True) and not is_bounce:
                    last_checked_str = target_speaker.last_checked_at.isoformat() if target_speaker.last_checked_at else datetime.utcnow().isoformat()
                    reply_row = [
                        target_speaker.speaker_id or "",
                        target_speaker.conference_id or "",
                        target_speaker.conference_name or "",
                        target_speaker.speaker_name or "",
                        target_speaker.job_title or "",
                        target_speaker.company_name or "",
                        target_speaker.personal_linkedin_url or "",
                        target_speaker.linkedin_status or "",
                        contact_email,
                        target_speaker.email_source_url or "",
                        target_speaker.speaker_source_url or "",
                        target_speaker.verification_status or "",
                        last_checked_str,
                        target_speaker.weekly_run_id or "",
                        target_speaker.outreach_status or "sent",
                        "replied",
                        sentiment,
                        body_text,
                        target_speaker.sent_message or "",
                        conv_id or "",
                        received_at_str,
                        msg_id
                    ]

                    try:
                        self.onedrive.append_speaker_reply(reply_row)
                    except Exception as e:
                        logger.error(f"Error appending reply to OneDrive tbl_speakers_replies: {e}", exc_info=True)

                    try:
                        self.excel_mgr.append_speaker_reply_to_excel(reply_row)
                    except Exception as e:
                        logger.error(f"Error appending reply to Local Excel 'Speakers Replies': {e}", exc_info=True)

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
                            professional_email=contact_email,
                            email_source_url=target_speaker.email_source_url or "",
                            speaker_source_url=target_speaker.speaker_source_url or "",
                            verification_status=target_speaker.verification_status or "",
                            last_checked_at=target_speaker.last_checked_at or datetime.utcnow(),
                            weekly_run_id=target_speaker.weekly_run_id or "",
                            outreach_status=target_speaker.outreach_status or "sent",
                            reply_status="replied",
                            reply_sentiment=sentiment,
                            received_reply=body_text,
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

            # -----------------------------------------------------------------
            # 2. Update Qualified Leads, Non -Qualified Leads, and Verified Data
            # -----------------------------------------------------------------
            if qualified_target or non_qualified_target or verified_target:
                rep_status = "bounced" if is_bounce else "replied"
                cat_target = (
                    qualified_target.get("category") if qualified_target 
                    else (non_qualified_target.get("category") if non_qualified_target
                    else (verified_target.get("category") if verified_target else "Speaker"))
                )
                reply_updates = {
                    "Outreach Status": rep_status,
                    "Reply Status": rep_status,
                    "Reply Sentiment": sentiment,
                    "Sentiment": sentiment,
                    "Received Reply": transcript if not is_bounce else "BOUNCE: Undeliverable address"
                }
                # Updates Qualified Leads, Non -Qualified Leads in OneDrive & Local Excel, and syncs Verified Data & original Weekly sheet
                self._update_qualified_leads_outreach(email=contact_email, updates=reply_updates, thread_id=conv_id, category=cat_target)
                self._sync_db_outreach_status(email=contact_email, status=rep_status, thread_id=conv_id)

                fresh_state = load_state()
                fresh_state.setdefault("replies", []).append({
                    "email": contact_email,
                    "name": contact_name,
                    "conference_name": conf_name,
                    "source": "non_qualified_leads" if non_qualified_target else ("qualified_leads" if qualified_target else "verified_data"),
                    "sentiment": sentiment,
                    "intent": intent,
                    "received_at": received_at_str,
                    "message_id": msg_id
                })
                save_state(fresh_state)
                logger.info(f"✅ Stored {'bounce' if is_bounce else 'reply'} for '{contact_name}' into 'Qualified Leads'/'Non -Qualified Leads' and original Weekly sheets & tables.")

            # Ensure persisted in state & deduplication set
            mark_reply_processed(msg_id)

        return {
            "status": "success",
            "new_replies": new_replies_count,
            "bounces": bounces_count,
            "scanned_messages": len(inbox_messages)
        }

    def send_manual_lead_outreach(
        self,
        email: str,
        force: bool = True,
        dry_run_override: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Manually triggers outreach for any lead (including disqualified leads in 'Non -Qualified Leads'):
        - Selects the appropriate category template from template.txt based on contact type:
          * Speakers -> Speakers template
          * Attendees -> Attendees template
          * Exhibitors -> Exhibitors template
        - Dispatches the email via Microsoft Graph API
        - Updates outreach tracking columns across:
          * Non -Qualified Leads / Qualified Leads
          * Corresponding original weekly sheet (Weekly Speakers, Weekly Attendees, or Weekly Exhibitors)
          * Verified Data
        - Registers thread in outreach_state.json for reply monitoring
        """
        clean_email = (email or "").strip().lower()
        if not clean_email or "@" not in clean_email or "." not in clean_email:
            return {"status": "error", "error": f"Invalid email: {email}"}

        target_lead = None

        # 1. Search Non -Qualified Leads
        for l in self._load_non_qualified_leads():
            if (l.get("professional_email") or "").strip().lower() == clean_email:
                target_lead = l
                break

        # 2. Search Qualified Leads
        if not target_lead:
            for l in self._load_qualified_leads():
                if (l.get("professional_email") or "").strip().lower() == clean_email:
                    target_lead = l
                    break

        # 3. Search Verified Data
        if not target_lead:
            for l in self._load_verified_data_leads():
                if (l.get("professional_email") or "").strip().lower() == clean_email:
                    target_lead = l
                    break

        if not target_lead:
            return {"status": "error", "error": f"Lead with email '{email}' not found in any leads sheet"}

        name = target_lead.get("name") or "there"
        job_title = target_lead.get("job_title") or "Professional"
        company = target_lead.get("company_name") or "your organization"
        conf_name = target_lead.get("conference_name") or "the upcoming conference"
        cat_lead = target_lead.get("category", "Speaker")
        c_type = target_lead.get("contact_type") or cat_lead
        score_val = float(target_lead.get("overall_score") or 0.0)

        # Build email content using category template from template.txt
        subject, body = build_email_content(
            speaker_name=name,
            job_title=job_title,
            company=company,
            conf_name=conf_name,
            category=cat_lead
        )
        full_message = f"Subject: {subject}\n\n{body}"

        dry_run = getattr(settings, "OUTREACH_DRY_RUN", True) if dry_run_override is None else dry_run_override
        if dry_run:
            return {
                "status": "dry_run_preview",
                "email": clean_email,
                "name": name,
                "category": cat_lead,
                "score": score_val,
                "subject": subject,
                "message": full_message,
                "note": "DRY_RUN mode active. No live email was dispatched."
            }

        # Live send
        try:
            self._update_qualified_leads_outreach(
                email=clean_email,
                updates={"Outreach Status": "sending", "Send Message": full_message},
                category=cat_lead
            )
            msg_id, conversation_id = self.graph.send_mail(clean_email, subject, body)

            sent_updates = {
                "Outreach Status": "sent",
                "Send Message": full_message,
                "Thread ID": conversation_id
            }
            self._update_qualified_leads_outreach(
                email=clean_email,
                updates=sent_updates,
                thread_id=conversation_id,
                category=cat_lead
            )

            # Record in state
            state = load_state()
            dedupe_key = f"{clean_email}|{conf_name.lower()}"
            state.setdefault("sent_log", []).append({
                "email": clean_email,
                "conference_name": conf_name,
                "name": name,
                "contact_type": c_type,
                "category": cat_lead,
                "score": score_val,
                "sent_at": now_iso(),
                "status": "sent",
                "manual": True
            })
            state.setdefault("threads", {})[dedupe_key] = {
                "thread_id": conversation_id,
                "message_id": msg_id,
                "name": name,
                "email": clean_email,
                "company": company,
                "conference": conf_name,
                "contact_type": c_type,
                "category": cat_lead,
                "score": score_val,
                "source": target_lead.get("source", "manual"),
                "sent_at": now_iso()
            }
            save_state(state)

            self._sync_db_outreach_status(email=clean_email, status="sent", thread_id=conversation_id, full_message=full_message)

            return {
                "status": "success",
                "email": clean_email,
                "name": name,
                "category": cat_lead,
                "score": score_val,
                "message_id": msg_id,
                "conversation_id": conversation_id
            }
        except Exception as e:
            logger.error(f"❌ Failed to send manual outreach to {clean_email}: {e}")
            self._update_qualified_leads_outreach(
                email=clean_email,
                updates={"Outreach Status": "failed"},
                category=cat_lead
            )
            return {"status": "error", "error": str(e)}

    def _update_onedrive_speaker_row(self, speaker: WeeklySpeaker):
        """Updates the speaker row in OneDrive Excel (tbl_weekly_speakers) and Local Excel."""
        if not speaker:
            return
        updates = {
            "outreach_status": speaker.outreach_status,
            "reply_status": speaker.reply_status,
            "reply_sentiment": speaker.reply_sentiment,
            "received_reply": speaker.received_reply,
            "sent_message": speaker.sent_message,
            "thread_id": speaker.email_thread_id
        }
        self._update_weekly_sheet_outreach(
            email=speaker.professional_email,
            updates=updates,
            thread_id=speaker.email_thread_id,
            category="Speaker"
        )
