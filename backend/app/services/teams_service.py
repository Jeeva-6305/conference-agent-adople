import os
import re
import json
import logging
import urllib.request
from datetime import datetime, date
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

        return existing is not None

    def build_adaptive_card(
        self,
        conf: Conference,
        speakers: List[Speaker],
        attendee: Optional[Attendee]
    ) -> Dict[str, Any]:
        """
        Builds a rich Adaptive Card JSON payload.
        Power Automate's 'Post card in a chat or channel' receives triggerBody()
        and renders this natively in the Teams group chat.
        """
        date_str = conf.start_date.isoformat() if conf.start_date else datetime.now().strftime("%Y-%m-%d")
        end_date_str = conf.end_date.isoformat() if conf.end_date else date_str
        date_display = date_str if end_date_str == date_str else f"{date_str} to {end_date_str}"
        state_str = extract_us_state(conf.venue or "", conf.city or "")
        full_address = f"{conf.venue or 'Venue TBA'}, {conf.city or ''}, {state_str}, {conf.country or 'USA'}".replace(", ,", ",")

        # Conference Details FactSet
        facts = [
            {"title": "Conference:", "value": conf.conference_title},
            {"title": "Category:", "value": conf.industry_category or "Technology & AI"},
            {"title": "Date:", "value": date_display},
            {"title": "Timing:", "value": "9:00 AM EDT (Start) – 5:00 PM EDT (End)"},
            {"title": "Venue:", "value": conf.venue or "Conference Center"},
            {"title": "Full Address:", "value": full_address},
            {"title": "Location:", "value": f"{conf.city}, {state_str}, {conf.country or 'USA'}"},
            {"title": "Organizer:", "value": conf.organizer or "Conference Organizer"},
            {"title": "Source:", "value": f"{conf.source_name} ({conf.source_url})"}
        ]

        card_body: List[Dict[str, Any]] = [
            # Header Container with accent background styling
            {
                "type": "Container",
                "style": "accent",
                "bleed": True,
                "items": [
                    {
                        "type": "TextBlock",
                        "text": "🏛️ USA CONFERENCE REMINDER NOTIFICATION",
                        "size": "Small",
                        "weight": "Bolder",
                        "color": "Light",
                        "spacing": "None"
                    },
                    {
                        "type": "TextBlock",
                        "text": conf.conference_title,
                        "size": "Large",
                        "weight": "Bolder",
                        "wrap": True,
                        "color": "Light",
                        "spacing": "Small"
                    },
                    {
                        "type": "ColumnSet",
                        "spacing": "Small",
                        "columns": [
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": f"📅 {date_display}",
                                        "weight": "Bolder",
                                        "color": "Light",
                                        "size": "Small"
                                    }
                                ]
                            },
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": f"📍 {conf.city}, {state_str}",
                                        "weight": "Bolder",
                                        "color": "Light",
                                        "size": "Small"
                                    }
                                ]
                            },
                            {
                                "type": "Column",
                                "width": "auto",
                                "items": [
                                    {
                                        "type": "TextBlock",
                                        "text": f"🏷️ {conf.industry_category}",
                                        "weight": "Bolder",
                                        "color": "Light",
                                        "size": "Small"
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            # Section 1: Overview & Details
            {
                "type": "Container",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": "📋 Conference Information",
                        "size": "Medium",
                        "weight": "Bolder",
                        "separator": True
                    },
                    {
                        "type": "FactSet",
                        "facts": facts
                    }
                ]
            }
        ]

        # Add Description if present
        if conf.description:
            card_body.append({
                "type": "Container",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": f"**Description:** {conf.description[:400]}" + ("..." if len(conf.description) > 400 else ""),
                        "wrap": True,
                        "size": "Small",
                        "isSubtle": True
                    }
                ]
            })

        # Section 2: Speakers Section
        speaker_elements: List[Dict[str, Any]] = [
            {
                "type": "TextBlock",
                "text": f"🎤 Verified Speakers ({len(speakers)})",
                "size": "Medium",
                "weight": "Bolder",
                "separator": True
            }
        ]

        if speakers:
            speaker_facts = []
            for idx, spk in enumerate(speakers[:10], 1):  # Limit to 10 for clean layout
                role_company = f"{spk.job_role_designation or 'Speaker'} @ {spk.company_organization or spk.company_name or 'Independent'}"
                linkedin_text = f" ({spk.linkedin_url})" if spk.linkedin_url else ""
                speaker_facts.append({
                    "title": f"[{idx}] {spk.speaker_name}:",
                    "value": f"{role_company}{linkedin_text}"
                })
            speaker_elements.append({
                "type": "FactSet",
                "facts": speaker_facts
            })
            if len(speakers) > 10:
                speaker_elements.append({
                    "type": "TextBlock",
                    "text": f"*...and {len(speakers) - 10} additional speakers listed in Excel & UI.*",
                    "isSubtle": True,
                    "size": "Small"
                })
        else:
            speaker_elements.append({
                "type": "TextBlock",
                "text": "_No speakers publicly announced for this event at time of scraping._",
                "isSubtle": True,
                "size": "Small"
            })

        card_body.append({
            "type": "Container",
            "items": speaker_elements
        })

        # Section 3: Attendee Information
        att_facts = [
            {"title": "Expected Attendees:", "value": (attendee.expected_attendee_count if attendee and attendee.expected_attendee_count else "Not publicly disclosed")},
            {"title": "Registered Attendees:", "value": (attendee.registered_attendee_count if attendee and attendee.registered_attendee_count else "Not publicly disclosed")},
            {"title": "Categories:", "value": (attendee.attendee_categories if attendee and attendee.attendee_categories else "Industry Executives & Practitioners")},
            {"title": "Target Audience:", "value": (attendee.target_audience if attendee and attendee.target_audience else "Founders, Engineers, Researchers & Investors")},
            {"title": "Industries:", "value": (attendee.industries if attendee and attendee.industries else conf.industry_category)}
        ]

        card_body.append({
            "type": "Container",
            "items": [
                {
                    "type": "TextBlock",
                    "text": "👥 Attendee Demographics",
                    "size": "Medium",
                    "weight": "Bolder",
                    "separator": True
                },
                {
                    "type": "FactSet",
                    "facts": att_facts
                }
            ]
        })

        # Section 4: Action Buttons
        actions: List[Dict[str, Any]] = []
        if conf.official_conference_url:
            actions.append({
                "type": "Action.OpenUrl",
                "title": "🌐 Official Website",
                "url": conf.official_conference_url
            })
        if conf.registration_url:
            actions.append({
                "type": "Action.OpenUrl",
                "title": "📝 Register / RSVP",
                "url": conf.registration_url
            })
        if conf.source_url:
            actions.append({
                "type": "Action.OpenUrl",
                "title": "🔗 Source Listing",
                "url": conf.source_url
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

        # Record in database
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

    def send_all_pending_teams_cards(
        self,
        db: Session,
        conferences: Optional[List[Conference]] = None,
        force: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Sends individual Adaptive Cards to Microsoft Teams for each matching published conference.
        If 5 conferences match, sends 5 cards.
        """
        if conferences is None:
            today = date.today()
            exact_t2_date = today.fromordinal(today.toordinal() + 2)
            query = db.query(Conference).filter(
                Conference.is_published_to_excel == True,
                Conference.start_date == exact_t2_date
            )
            if not force:
                query = query.filter(Conference.teams_webhook_sent == False)
            conferences = query.all()

        results = []
        logger.info(f"📢 [Teams Service] Processing {len(conferences)} conference card(s) for Teams Webhook...")

        for conf in conferences:
            speakers = db.query(Speaker).filter(Speaker.conference_id == conf.conference_id).all()
            attendee = db.query(Attendee).filter(Attendee.conference_id == conf.conference_id).first()
            res = self.send_conference_teams_card(db, conf, speakers, attendee, force=force)
            results.append(res)

        logger.info(f"📢 [Teams Service] Completed Teams webhook delivery: {len(results)} processed.")
        return results
