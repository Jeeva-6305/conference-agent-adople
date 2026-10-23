import os
import re
import json
import logging
import urllib.request
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from ..config import settings
from ..models import Conference, Speaker, Attendee, TeamsNotification, make_conference_unique_key
from .email_service import extract_us_state

logger = logging.getLogger(__name__)


class TeamsWebhookService:
    """
    Microsoft Teams Webhook Service:
    - Builds rich, interactive Adaptive Cards conforming to Adaptive Card v1.4.
    - Sends HTTP POST requests directly to the configured Power Automate / Teams webhook.
    - Prevents duplicate postings via persistent database tracking.
    - Automatically triggered whenever conference details are added/synced to Excel.
    """

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or settings.TEAMS_WEBHOOK_URL
        self.outbox_dir = Path(settings.TEAMS_OUTPUT_DIR)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_log_path = self.outbox_dir / "webhook_outbox.log"

    def is_conference_already_sent(self, db: Session, conf: Conference) -> bool:
        """Checks if card for this conference was already dispatched successfully."""
        if conf.teams_webhook_sent:
            return True

        unique_key = make_conference_unique_key(
            conf.conference_title,
            conf.start_date,
            conf.venue
        )

        existing = db.query(TeamsNotification).filter(
            ((TeamsNotification.conference_unique_key == unique_key) |
             (TeamsNotification.conference_id == conf.conference_id)) &
            (TeamsNotification.status == "sent")
        ).first()

    def build_consolidated_adaptive_card(
        self,
        conferences: List[Conference],
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Builds ONE clean, well-organized consolidated summary Adaptive Card (v1.4)
        combining all eligible conferences.
        Displays ONLY:
        - Total Number of Conferences
        - Conference Name
        - Industry
        - Starting Date
        - Speaker Details Available: Yes or No
        """
        total_conferences = len(conferences)

        card_body: List[Dict[str, Any]] = [
            {
                "type": "Container",
                "style": "emphasis",
                "bleed": True,
                "items": [
                    {
                        "type": "TextBlock",
                        "text": "Upcoming Conferences Summary (T-2)",
                        "size": "Medium",
                        "weight": "Bolder",
                        "color": "Accent"
                    },
                    {
                        "type": "TextBlock",
                        "text": f"Total Number of Conferences: {total_conferences}",
                        "size": "Default",
                        "weight": "Bolder",
                        "spacing": "Small"
                    }
                ]
            }
        ]

        if not conferences:
            card_body.append({
                "type": "TextBlock",
                "text": "No upcoming conferences found for this period.",
                "isSubtle": True,
                "spacing": "Medium"
            })
        else:
            conference_items: List[Dict[str, Any]] = []
            for idx, conf in enumerate(conferences, 1):
                conf_name = conf.conference_title or "Untitled Conference"
                industry = conf.industry_category or "Not available"
                start_date_str = conf.start_date.isoformat() if conf.start_date else "Not available"

                # Check if speaker details are available: Yes or No
                spk_avail = "No"
                if conf.speakers_available and conf.speakers_available.strip().lower() in ["yes", "true", "1"]:
                    spk_avail = "Yes"
                elif db:
                    spk_cnt = db.query(Speaker).filter(Speaker.conference_id == conf.conference_id).count()
                    spk_avail = "Yes" if spk_cnt > 0 else "No"
                elif conf.speakers and conf.speakers.strip():
                    spk_avail = "Yes"

                conf_container = {
                    "type": "Container",
                    "separator": True,
                    "spacing": "Medium",
                    "items": [
                        {
                            "type": "TextBlock",
                            "text": f"{idx}. {conf_name}",
                            "weight": "Bolder",
                            "size": "Default",
                            "wrap": True
                        },
                        {
                            "type": "FactSet",
                            "spacing": "Small",
                            "facts": [
                                {
                                    "title": "Industry:",
                                    "value": industry
                                },
                                {
                                    "title": "Starting Date:",
                                    "value": start_date_str
                                },
                                {
                                    "title": "Speaker Details Available:",
                                    "value": spk_avail
                                }
                            ]
                        }
                    ]
                }
                conference_items.append(conf_container)

            card_body.append({
                "type": "Container",
                "spacing": "Medium",
                "items": conference_items
            })

        adaptive_card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": card_body
        }

        return adaptive_card

    def build_adaptive_card(
        self,
        conf: Conference,
        speakers: List[Speaker],
        attendee: Optional[Attendee] = None
    ) -> Dict[str, Any]:
        """
        Builds a clean Adaptive Card JSON payload containing ONLY the 9 required fields:
        1. Conference ID
        2. Conference Name
        3. Conference Date
        4. Speaker Details
        5. Industry
        6. Platform / Source Platform
        7. Venue
        8. City
        9. Original Source URL (Clickable)
        """
        # 1. Conference ID
        conf_id = conf.conference_id or "Not available"

        # 2. Conference Name
        conf_title = conf.conference_title or "Not available"

        # 3. Conference Date
        if conf.start_date:
            date_str = conf.start_date.isoformat()
            if conf.end_date and conf.end_date != conf.start_date:
                date_display = f"{date_str} to {conf.end_date.isoformat()}"
            else:
                date_display = date_str
        else:
            date_display = "Not available"

        # 4. Speaker Details
        if speakers:
            speaker_lines = []
            for spk in speakers:
                parts = [spk.speaker_name]
                role_parts = []
                if spk.job_role_designation:
                    role_parts.append(spk.job_role_designation)
                org = spk.company_organization or spk.company_name
                if org and org not in (spk.job_role_designation or ""):
                    role_parts.append(org)
                if role_parts:
                    parts.append(f"({', '.join(role_parts)})")
                if spk.linkedin_url:
                    parts.append(f"- [LinkedIn]({spk.linkedin_url})")
                speaker_lines.append(f"• {' '.join(parts)}")
            speakers_value = "\n\n".join(speaker_lines)
        else:
            speakers_value = "Not available"

        # 5. Industry
        industry = conf.industry_category or "Not available"

        # 6. Platform / Source Platform
        source_platform = conf.source_name or "Not available"

        # 7. Venue
        venue = conf.venue or "Not available"

        # 8. City
        city = conf.city or "Not available"

        # 9. Original Source URL (Clickable link)
        source_url = conf.source_url or conf.official_conference_url or ""
        if source_url:
            source_url_display = f"[{source_url}]({source_url})"
        else:
            source_url_display = "Not available"

        facts = [
            {"title": "Conference ID:", "value": conf_id},
            {"title": "Conference Name:", "value": conf_title},
            {"title": "Conference Date:", "value": date_display},
            {"title": "Speaker Details:", "value": speakers_value},
            {"title": "Industry:", "value": industry},
            {"title": "Platform / Source Platform:", "value": source_platform},
            {"title": "Venue:", "value": venue},
            {"title": "City:", "value": city},
            {"title": "Original Source URL:", "value": source_url_display}
        ]

        card_body: List[Dict[str, Any]] = [
            {
                "type": "Container",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": conf_title,
                        "size": "Large",
                        "weight": "Bolder",
                        "wrap": True,
                        "color": "Accent"
                    },
                    {
                        "type": "FactSet",
                        "facts": facts
                    }
                ]
            }
        ]

        actions: List[Dict[str, Any]] = []
        if source_url:
            actions.append({
                "type": "Action.OpenUrl",
                "title": "Open Original Source URL",
                "url": source_url
            })

        adaptive_card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": card_body,
            "actions": actions
        }

        return adaptive_card

    def send_conference_teams_card(
        self,
        db: Session,
        conf: Conference,
        speakers: List[Speaker],
        attendee: Optional[Attendee],
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Sends an Adaptive Card for a single conference to the Teams Webhook.
        Enforces deduplication, audit logging, and database tracking.
        """
        if not getattr(settings, "TEAMS_CARD_ENABLED", False):
            logger.info(f"Teams card delivery is disabled (TEAMS_CARD_ENABLED=false). Skipping '{conf.conference_title}'.")
            return {
                "status": "disabled",
                "reason": "TEAMS_CARD_ENABLED is false",
                "conference_id": conf.conference_id,
                "conference_title": conf.conference_title
            }

        unique_key = make_conference_unique_key(
            conf.conference_title,
            conf.start_date,
            conf.venue
        )

        if not force and self.is_conference_already_sent(db, conf):
            logger.info(f"Skipping duplicate Teams webhook card: '{conf.conference_title}' already sent.")
            return {
                "status": "skipped",
                "reason": "duplicate_prevented",
                "conference_id": conf.conference_id,
                "conference_title": conf.conference_title
            }

        card = self.build_adaptive_card(conf, speakers, attendee)
        payload_bytes = json.dumps(card, ensure_ascii=False).encode("utf-8")

        send_status = "sent"
        error_msg = None
        http_code = 0

        try:
            logger.info(f"Posting Adaptive Card to Teams webhook for '{conf.conference_title}'...")
            req = urllib.request.Request(
                self.webhook_url,
                data=payload_bytes,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                http_code = resp.status
                resp_body = resp.read().decode("utf-8", errors="ignore")
                logger.info(f"✅ Teams webhook accepted card for '{conf.conference_title}' (HTTP {http_code})")

            send_status = "sent"

        except urllib.error.HTTPError as e:
            http_code = e.code
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error(f"❌ Teams webhook HTTP error {http_code} for '{conf.conference_title}': {err_body}")
            send_status = "failed"
            error_msg = f"HTTP {http_code}: {err_body}"

        except Exception as e:
            logger.error(f"❌ Teams webhook network exception for '{conf.conference_title}': {e}", exc_info=True)
            send_status = "failed"
            error_msg = str(e)

        # Archive card JSON locally
        clean_slug = re.sub(r'[^a-zA-Z0-9_\-]', '_', conf.conference_title)[:50]
        json_filename = f"TeamsCard_{conf.conference_id}_{clean_slug}.json"
        json_path = self.outbox_dir / json_filename
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(card, indent=2, ensure_ascii=False))

        # Append to audit log
        now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(self.outbox_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{now_iso}] TEAMS WEBHOOK | STATUS: {send_status} | CODE: {http_code} | ID: {conf.conference_id} | TITLE: {conf.conference_title} | FILE: {json_filename}\n")

        # Record in database (upsert by conference_unique_key to prevent constraint collision)
        existing_notif = db.query(TeamsNotification).filter(
            TeamsNotification.conference_unique_key == unique_key
        ).first()

        if existing_notif:
            existing_notif.status = send_status
            existing_notif.card_payload = json.dumps(card)
            existing_notif.sent_at = datetime.utcnow()
            existing_notif.error_message = error_msg
            existing_notif.webhook_url = self.webhook_url
        else:
            notification = TeamsNotification(
                conference_id=conf.conference_id,
                conference_unique_key=unique_key,
                conference_title=conf.conference_title,
                conference_date=conf.start_date,
                venue=conf.venue or "",
                webhook_url=self.webhook_url,
                status=send_status,
                card_payload=json.dumps(card),
                sent_at=datetime.utcnow(),
                error_message=error_msg
            )
            db.add(notification)

        if send_status == "sent":
            conf.teams_webhook_sent = True
            conf.teams_webhook_sent_at = datetime.utcnow()
        db.commit()

        return {
            "status": send_status,
            "http_code": http_code,
            "conference_id": conf.conference_id,
            "conference_title": conf.conference_title,
            "archive_path": str(json_path),
            "error": error_msg
        }

    def send_consolidated_teams_card(
        self,
        db: Session,
        conferences: Optional[List[Conference]] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Sends ONE single consolidated summary Adaptive Card containing all eligible T-2 conferences
        to the configured Microsoft Teams group/webhook.
        """
        if not getattr(settings, "TEAMS_CARD_ENABLED", False):
            logger.info("📢 [Teams Service] Teams card delivery is disabled (TEAMS_CARD_ENABLED=false). Skipping.")
            return {
                "status": "disabled",
                "reason": "TEAMS_CARD_ENABLED is false",
                "total_conferences": 0
            }

        if conferences is None:
            today = date.today()
            exact_t2_date = today + timedelta(days=2)
            query = db.query(Conference).filter(
                Conference.is_published_to_excel == True,
                Conference.start_date == exact_t2_date
            )
            conferences = query.all()

        if not conferences:
            logger.info("📢 [Teams Service] No eligible T-2 conferences found to send.")
            return {
                "status": "skipped",
                "reason": "no_eligible_conferences",
                "total_conferences": 0
            }

        today_str = date.today().isoformat()
        conf_ids_str = "_".join(sorted([c.conference_id for c in conferences]))
        unique_key = f"consolidated_t2_{today_str}_{len(conferences)}_{conf_ids_str[:100]}"

        if not force:
            existing = db.query(TeamsNotification).filter(
                (TeamsNotification.conference_unique_key == unique_key) &
                (TeamsNotification.status == "sent")
            ).first()
            if existing:
                logger.info(f"📢 [Teams Service] Consolidated card for today's T-2 batch ({len(conferences)} conferences) already sent. Skipping.")
                return {
                    "status": "skipped",
                    "reason": "duplicate_prevented",
                    "total_conferences": len(conferences)
                }

        card = self.build_consolidated_adaptive_card(conferences, db=db)
        payload_bytes = json.dumps(card, ensure_ascii=False).encode("utf-8")

        send_status = "sent"
        error_msg = None
        http_code = 0

        try:
            logger.info(f"Posting consolidated Adaptive Card ({len(conferences)} conferences) to Teams webhook...")
            req = urllib.request.Request(
                self.webhook_url,
                data=payload_bytes,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                http_code = resp.status
                resp_body = resp.read().decode("utf-8", errors="ignore")
                logger.info(f"✅ Teams webhook accepted consolidated card for {len(conferences)} conferences (HTTP {http_code})")

            send_status = "sent"

        except urllib.error.HTTPError as e:
            http_code = e.code
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error(f"❌ Teams webhook HTTP error {http_code}: {err_body}")
            send_status = "failed"
            error_msg = f"HTTP {http_code}: {err_body}"

        except Exception as e:
            logger.error(f"❌ Teams webhook network exception: {e}", exc_info=True)
            send_status = "failed"
            error_msg = str(e)

        # Archive card JSON locally
        json_filename = f"TeamsConsolidatedCard_{today_str}_{len(conferences)}_confs.json"
        json_path = self.outbox_dir / json_filename
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(card, indent=2, ensure_ascii=False))

        # Append to audit log
        now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(self.outbox_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{now_iso}] TEAMS CONSOLIDATED CARD | STATUS: {send_status} | CODE: {http_code} | TOTAL: {len(conferences)} | FILE: {json_filename}\n")

        # Record in database (upsert by unique_key to prevent unique collision)
        existing_notif = db.query(TeamsNotification).filter(
            TeamsNotification.conference_unique_key == unique_key
        ).first()

        target_date = conferences[0].start_date if conferences and conferences[0].start_date else date.today()

        if existing_notif:
            existing_notif.status = send_status
            existing_notif.card_payload = json.dumps(card)
            existing_notif.sent_at = datetime.utcnow()
            existing_notif.error_message = error_msg
            existing_notif.webhook_url = self.webhook_url
        else:
            notification = TeamsNotification(
                conference_id="CONSOLIDATED",
                conference_unique_key=unique_key,
                conference_title=f"Consolidated T-2 Summary ({len(conferences)} Conferences)",
                conference_date=target_date,
                venue="Consolidated Summary",
                webhook_url=self.webhook_url,
                status=send_status,
                card_payload=json.dumps(card),
                sent_at=datetime.utcnow(),
                error_message=error_msg
            )
            db.add(notification)

        if send_status == "sent":
            for conf in conferences:
                conf.teams_webhook_sent = True
                conf.teams_webhook_sent_at = datetime.utcnow()

        db.commit()

        return {
            "status": send_status,
            "http_code": http_code,
            "total_conferences": len(conferences),
            "archive_path": str(json_path),
            "error": error_msg
        }

    def send_all_pending_teams_cards(
        self,
        db: Session,
        conferences: Optional[List[Conference]] = None,
        force: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Sends ONE consolidated summary Adaptive Card containing all eligible published conferences
        to Microsoft Teams.
        Returns a list containing the single summary dispatch result (for full compatibility with existing callers).
        """
        if not getattr(settings, "TEAMS_CARD_ENABLED", False):
            logger.info("📢 [Teams Service] Teams card delivery is disabled (TEAMS_CARD_ENABLED=false).")
            return []

        res = self.send_consolidated_teams_card(db, conferences=conferences, force=force)
        return [res] if res.get("status") != "skipped" or force else []
