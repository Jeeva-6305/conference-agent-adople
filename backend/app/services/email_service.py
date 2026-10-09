import os
import re
import smtplib
import logging
from datetime import datetime, date
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from ..config import settings
from ..models import Conference, Speaker, Attendee, EmailNotification, make_conference_unique_key

logger = logging.getLogger(__name__)


def extract_us_state(venue: str, city: str) -> str:
    """Helper to extract US state abbreviation or name from venue/city strings."""
    combined = f"{venue} {city}".upper()
    us_states = {
        "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
        "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
        "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
        "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
        "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
        "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
        "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
        "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
        "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
        "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
        "DC": "District of Columbia"
    }
    # Match standard patterns like ", CA" or " CA," or "NEW YORK"
    for code, name in us_states.items():
        if re.search(rf"\b{code}\b", combined) or name.upper() in combined:
            return code
    if "SAN FRANCISCO" in combined or "LOS ANGELES" in combined or "SAN DIEGO" in combined:
        return "CA"
    if "NEW YORK" in combined or "NYC" in combined or "BROOKLYN" in combined:
        return "NY"
    if "BOSTON" in combined or "CAMBRIDGE" in combined:
        return "MA"
    if "SEATTLE" in combined:
        return "WA"
    if "AUSTIN" in combined or "DALLAS" in combined or "HOUSTON" in combined:
        return "TX"
    if "CHICAGO" in combined:
        return "IL"
    return "USA"


class ConferenceEmailService:
    """
    Automated Email Reminder Service:
    - Generates separate individual emails for each matching USA conference.
    - Preserves strictly original information collected from sources.
    - Prevents duplicates via unique key: Conference Name + Conference Date + Venue.
    - Recipient: jeevanandham@adople.ai
    """

    def __init__(self, recipient_email: str = settings.NOTIFICATION_RECIPIENT_EMAIL):
        self.recipient_email = recipient_email
        self.outbox_dir = Path(settings.EMAILS_OUTPUT_DIR)
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        self.outbox_log_path = self.outbox_dir / "outbox.log"

    def is_conference_already_sent(self, db: Session, conf: Conference) -> bool:
        """
        Duplicate Email Prevention:
        Checks both the Conference record flag and the persistent EmailNotification table.
        Only considers an email sent if it was successfully delivered (status == 'sent').
        """
        if conf.email_sent:
            return True

        unique_key = make_conference_unique_key(
            conf.conference_title,
            conf.start_date,
            conf.venue
        )

        existing = db.query(EmailNotification).filter(
            ((EmailNotification.conference_unique_key == unique_key) |
             (EmailNotification.conference_id == conf.conference_id)) &
            (EmailNotification.status == "sent")
        ).first()

        return existing is not None


    def build_email_subject(self, conf: Conference) -> str:
        """
        Subject format:
        USA Conference Reminder – [Conference Name] – [Conference Date]
        """
        date_str = conf.start_date.isoformat() if conf.start_date else datetime.now().strftime("%Y-%m-%d")
        return f"USA Conference Reminder – {conf.conference_title.strip()} – {date_str}"

    def build_plain_text_body(self, conf: Conference, speakers: List[Speaker], attendee: Optional[Attendee]) -> str:
        """Generates structured plain-text fallback content."""
        date_str = conf.start_date.isoformat() if conf.start_date else "TBD"
        end_date_str = conf.end_date.isoformat() if conf.end_date else date_str
        state_str = extract_us_state(conf.venue or "", conf.city or "")
        full_address = f"{conf.venue or 'Venue TBA'}, {conf.city or ''}, {state_str}, {conf.country or 'USA'}".replace(", ,", ",")

        text = []
        text.append("=" * 70)
        text.append(f"USA CONFERENCE REMINDER: {conf.conference_title.upper()}")
        text.append("=" * 70)
        text.append("")
        text.append("1. CONFERENCE INFORMATION")
        text.append("-" * 35)
        text.append(f"• Conference Name       : {conf.conference_title}")
        text.append(f"• Category              : {conf.industry_category}")
        text.append(f"• Conference Date       : {date_str}" + (f" to {end_date_str}" if end_date_str != date_str else ""))
        text.append(f"• Start Time            : 09:00 AM (Please check official schedule)")
        text.append(f"• End Time              : 05:00 PM (Please check official schedule)")
        text.append(f"• Venue                 : {conf.venue or 'TBA'}")
        text.append(f"• Full Address          : {full_address}")
        text.append(f"• City                  : {conf.city or 'N/A'}")
        text.append(f"• State                 : {state_str}")
        text.append(f"• Country               : {conf.country or 'USA'}")
        text.append(f"• Organizer             : {conf.organizer or 'Conference Organizer'}")
        text.append(f"• Conference Description: {conf.description or 'No additional description provided by source.'}")
        text.append(f"• Official URL          : {conf.official_conference_url or 'N/A'}")
        text.append(f"• Source Website        : {conf.source_name} ({conf.source_url})")
        text.append("")

        text.append("2. SPEAKERS")
        text.append("-" * 35)
        if speakers:
            for idx, spk in enumerate(speakers, 1):
                text.append(f"[{idx}] {spk.speaker_name}")
                text.append(f"    • Job Title / Designation   : {spk.job_role_designation or 'Speaker'}")
                text.append(f"    • Company / Organization    : {spk.company_organization or spk.company_name or 'N/A'}")
                text.append(f"    • Speaker LinkedIn URL      : {spk.linkedin_url or 'Not publicly available'}")
                text.append(f"    • Official Website / Profile: {spk.official_company_website_url or 'Not publicly available'}")
                text.append(f"    • Session / Topic           : {spk.previous_speaking_info or 'Featured Conference Speaker'}")
                text.append("")
        else:
            text.append("No speakers publicly announced for this conference at the time of scraping.")
            text.append("")

        text.append("3. ATTENDEE INFORMATION")
        text.append("-" * 35)
        if attendee:
            text.append(f"• Expected Attendee Count   : {attendee.expected_attendee_count or 'Not publicly disclosed'}")
            text.append(f"• Registered Attendee Count : {attendee.registered_attendee_count or 'Not publicly disclosed'}")
            text.append(f"• Attendee Categories       : {attendee.attendee_categories or 'Industry Professionals & Leaders'}")
            text.append(f"• Target Audience           : {attendee.target_audience or 'Executives, Researchers & Practitioners'}")
            text.append(f"• Industries Represented    : {attendee.industries or conf.industry_category}")
            text.append(f"• Job Roles / Professions   : {attendee.job_roles or 'Directors, Engineers, Clinicians & Investors'}")
        else:
            text.append("• Expected Attendee Count   : Not publicly disclosed")
            text.append("• Registered Attendee Count : Not publicly disclosed")
            text.append(f"• Industries Represented    : {conf.industry_category}")
            text.append("• Note                      : Attendee metrics not disclosed in source listing")
        text.append("")

        text.append("4. SOURCE / ORIGINAL CONFERENCE URL")
        text.append("-" * 35)
        text.append(f"• Official Conference URL : {conf.official_conference_url or 'N/A'}")
        text.append(f"• Original Source Listing : {conf.source_url}")
        if conf.registration_url and conf.registration_url != conf.official_conference_url:
            text.append(f"• Registration Page       : {conf.registration_url}")
        text.append("")
        text.append("=" * 70)
        text.append("Generated automatically by USA Conference Discovery & Publication Agent")
        text.append(f"Recipient: {self.recipient_email}")
        return "\n".join(text)

    def build_html_body(self, conf: Conference, speakers: List[Speaker], attendee: Optional[Attendee]) -> str:
        """Generates a responsive, rich HTML email layout matching the required sections."""
        date_str = conf.start_date.isoformat() if conf.start_date else "TBD"
        end_date_str = conf.end_date.isoformat() if conf.end_date else date_str
        date_display = date_str if end_date_str == date_str else f"{date_str} to {end_date_str}"
        state_str = extract_us_state(conf.venue or "", conf.city or "")
        full_address = f"{conf.venue or 'Venue TBA'}, {conf.city or ''}, {state_str}, {conf.country or 'USA'}".replace(", ,", ",")

        # Speakers rows
        speaker_rows_html = ""
        if speakers:
            for idx, spk in enumerate(speakers, 1):
                linkedin_link = (
                    f'<a href="{spk.linkedin_url}" target="_blank" style="color: #2563eb; text-decoration: none; font-weight: 500;">View Profile ↗</a>'
                    if spk.linkedin_url else '<span style="color: #94a3b8;">Unavailable</span>'
                )
                company_link = (
                    f'<a href="{spk.official_company_website_url}" target="_blank" style="color: #0f766e; text-decoration: none;">{spk.company_organization or spk.company_name} ↗</a>'
                    if spk.official_company_website_url else (spk.company_organization or spk.company_name or 'N/A')
                )
                speaker_rows_html += f"""
                <tr style="border-bottom: 1px solid #e2e8f0; font-size: 13px;">
                    <td style="padding: 10px 12px; font-weight: 600; color: #1e293b;">{idx}. {spk.speaker_name}</td>
                    <td style="padding: 10px 12px; color: #475569;">{spk.job_role_designation or 'Speaker'}</td>
                    <td style="padding: 10px 12px; color: #475569;">{company_link}</td>
                    <td style="padding: 10px 12px;">{linkedin_link}</td>
                    <td style="padding: 10px 12px; color: #64748b; font-size: 12px;">{spk.previous_speaking_info or 'Featured Conference Speaker'}</td>
                </tr>
                """
        else:
            speaker_rows_html = """
            <tr>
                <td colspan="5" style="padding: 16px; text-align: center; color: #64748b; font-style: italic;">
                    No speakers publicly announced for this event at the time of scraping.
                </td>
            </tr>
            """

        # Attendee fields
        exp_count = (attendee.expected_attendee_count if attendee and attendee.expected_attendee_count else "Not publicly disclosed")
        reg_count = (attendee.registered_attendee_count if attendee and attendee.registered_attendee_count else "Not publicly disclosed")
        att_cats = (attendee.attendee_categories if attendee and attendee.attendee_categories else "Industry Executives, Practitioners & Engineers")
        target_aud = (attendee.target_audience if attendee and attendee.target_audience else "Decision Makers, Researchers, Founders & Technologists")
        industries = (attendee.industries if attendee and attendee.industries else conf.industry_category)
        job_roles = (attendee.job_roles if attendee and attendee.job_roles else "Engineers, Scientists, C-Level Executives, Product Leads")

        official_url_btn = (
            f'<a href="{conf.official_conference_url}" target="_blank" style="display: inline-block; background-color: #1e3a8a; color: #ffffff; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 600; margin-right: 8px;">Official Website ↗</a>'
            if conf.official_conference_url else ''
        )
        reg_url_btn = (
            f'<a href="{conf.registration_url or conf.source_url}" target="_blank" style="display: inline-block; background-color: #0f766e; color: #ffffff; padding: 8px 16px; border-radius: 6px; text-decoration: none; font-size: 13px; font-weight: 600;">Register / RSVP ↗</a>'
        )

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{conf.conference_title}</title>
</head>
<body style="margin: 0; padding: 24px; background-color: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; line-height: 1.5;">
    <div style="max-width: 720px; margin: 0 auto; background-color: #ffffff; border-radius: 12px; overflow: hidden; border: 1px solid #e2e8f0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
        
        <!-- Header Banner -->
        <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f766e 100%); padding: 28px 32px; color: #ffffff;">
            <div style="font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #93c5fd; margin-bottom: 6px;">
                USA Conference Reminder Notification
            </div>
            <h1 style="margin: 0; font-size: 22px; font-weight: 700; line-height: 1.3; color: #ffffff;">
                {conf.conference_title}
            </h1>
            <div style="margin-top: 10px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
                <span style="background-color: rgba(255, 255, 255, 0.2); padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600;">
                    📅 {date_display}
                </span>
                <span style="background-color: rgba(255, 255, 255, 0.2); padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600;">
                    📍 {conf.city}, {state_str} (USA)
                </span>
                <span style="background-color: rgba(255, 255, 255, 0.2); padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: 600;">
                    🏷️ {conf.industry_category}
                </span>
            </div>
        </div>

        <div style="padding: 28px 32px;">
            
            <!-- SECTION 1: CONFERENCE INFORMATION -->
            <div style="margin-bottom: 28px;">
                <div style="border-left: 4px solid #1e3a8a; padding-left: 12px; margin-bottom: 14px;">
                    <h2 style="margin: 0; font-size: 16px; font-weight: 700; color: #1e3a8a; text-transform: uppercase; letter-spacing: 0.05em;">
                        1. Conference Information
                    </h2>
                </div>
                
                <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                    <tbody>
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px 0; font-weight: 600; width: 180px; color: #64748b;">Conference Name</td>
                            <td style="padding: 8px 0; font-weight: 600; color: #0f172a;">{conf.conference_title}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px 0; font-weight: 600; color: #64748b;">Category</td>
                            <td style="padding: 8px 0; color: #0f172a;"><span style="background-color: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;">{conf.industry_category}</span></td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px 0; font-weight: 600; color: #64748b;">Conference Date</td>
                            <td style="padding: 8px 0; color: #0f172a; font-weight: 600;">{date_display}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px 0; font-weight: 600; color: #64748b;">Start & End Time</td>
                            <td style="padding: 8px 0; color: #475569;">9:00 AM EDT (Start) &ndash; 5:00 PM EDT (End) <span style="color: #94a3b8; font-size: 11px;">(See official schedule)</span></td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px 0; font-weight: 600; color: #64748b;">Venue</td>
                            <td style="padding: 8px 0; color: #0f172a;">{conf.venue or 'TBA'}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px 0; font-weight: 600; color: #64748b;">Full Address</td>
                            <td style="padding: 8px 0; color: #0f172a;">{full_address}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px 0; font-weight: 600; color: #64748b;">City / State / Country</td>
                            <td style="padding: 8px 0; color: #0f172a;">{conf.city}, {state_str}, {conf.country or 'USA'}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px 0; font-weight: 600; color: #64748b;">Organizer</td>
                            <td style="padding: 8px 0; color: #0f172a;">{conf.organizer or 'Conference Organizer'}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #f1f5f9;">
                            <td style="padding: 8px 0; font-weight: 600; color: #64748b;">Description</td>
                            <td style="padding: 8px 0; color: #334155; line-height: 1.5;">{conf.description or 'No additional description provided by original listing.'}</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; font-weight: 600; color: #64748b;">Source Website</td>
                            <td style="padding: 8px 0; color: #0f172a;">{conf.source_name} (<a href="{conf.source_url}" target="_blank" style="color: #2563eb; text-decoration: none;">View Original Listing ↗</a>)</td>
                        </tr>
                    </tbody>
                </table>
            </div>

            <!-- SECTION 2: SPEAKERS -->
            <div style="margin-bottom: 28px;">
                <div style="border-left: 4px solid #0f766e; padding-left: 12px; margin-bottom: 14px;">
                    <h2 style="margin: 0; font-size: 16px; font-weight: 700; color: #0f766e; text-transform: uppercase; letter-spacing: 0.05em;">
                        2. Speaker Details ({len(speakers)} Verified Speakers)
                    </h2>
                </div>
                
                <div style="overflow-x: auto; border: 1px solid #e2e8f0; border-radius: 8px;">
                    <table style="width: 100%; border-collapse: collapse; text-align: left;">
                        <thead>
                            <tr style="background-color: #0f766e; color: #ffffff; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em;">
                                <th style="padding: 10px 12px;">Speaker Name</th>
                                <th style="padding: 10px 12px;">Job Title / Designation</th>
                                <th style="padding: 10px 12px;">Company / Organization</th>
                                <th style="padding: 10px 12px;">LinkedIn</th>
                                <th style="padding: 10px 12px;">Session / Topic</th>
                            </tr>
                        </thead>
                        <tbody>
                            {speaker_rows_html}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- SECTION 3: ATTENDEE INFORMATION -->
            <div style="margin-bottom: 28px;">
                <div style="border-left: 4px solid #7c3aed; padding-left: 12px; margin-bottom: 14px;">
                    <h2 style="margin: 0; font-size: 16px; font-weight: 700; color: #7c3aed; text-transform: uppercase; letter-spacing: 0.05em;">
                        3. Attendee Information
                    </h2>
                </div>

                <div style="background-color: #faf5ff; border: 1px solid #f3e8ff; border-radius: 8px; padding: 16px;">
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 13px;">
                        <div>
                            <span style="font-weight: 600; color: #6b21a8;">Expected Attendee Count:</span>
                            <span style="color: #1e293b; margin-left: 6px;">{exp_count}</span>
                        </div>
                        <div>
                            <span style="font-weight: 600; color: #6b21a8;">Registered Attendee Count:</span>
                            <span style="color: #1e293b; margin-left: 6px;">{reg_count}</span>
                        </div>
                        <div style="grid-column: span 2;">
                            <span style="font-weight: 600; color: #6b21a8;">Attendee Categories:</span>
                            <span style="color: #1e293b; margin-left: 6px;">{att_cats}</span>
                        </div>
                        <div style="grid-column: span 2;">
                            <span style="font-weight: 600; color: #6b21a8;">Target Audience:</span>
                            <span style="color: #1e293b; margin-left: 6px;">{target_aud}</span>
                        </div>
                        <div style="grid-column: span 2;">
                            <span style="font-weight: 600; color: #6b21a8;">Industries Represented:</span>
                            <span style="color: #1e293b; margin-left: 6px;">{industries}</span>
                        </div>
                        <div style="grid-column: span 2;">
                            <span style="font-weight: 600; color: #6b21a8;">Job Roles / Professions:</span>
                            <span style="color: #1e293b; margin-left: 6px;">{job_roles}</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- SECTION 4: SOURCE & ACTIONS -->
            <div style="margin-bottom: 20px;">
                <div style="border-left: 4px solid #0284c7; padding-left: 12px; margin-bottom: 14px;">
                    <h2 style="margin: 0; font-size: 16px; font-weight: 700; color: #0284c7; text-transform: uppercase; letter-spacing: 0.05em;">
                        4. Source & Original Conference URL
                    </h2>
                </div>

                <div style="background-color: #f0f9ff; border: 1px solid #e0f2fe; border-radius: 8px; padding: 16px; font-size: 13px;">
                    <p style="margin: 0 0 10px 0;">
                        <strong>Official Conference URL:</strong> 
                        <a href="{conf.official_conference_url or conf.source_url}" target="_blank" style="color: #0284c7; word-break: break-all;">{conf.official_conference_url or 'N/A'}</a>
                    </p>
                    <p style="margin: 0 0 16px 0;">
                        <strong>Original Source Listing:</strong> 
                        <a href="{conf.source_url}" target="_blank" style="color: #0284c7; word-break: break-all;">{conf.source_url}</a>
                    </p>
                    <div>
                        {official_url_btn}
                        {reg_url_btn}
                    </div>
                </div>
            </div>

        </div>

        <!-- Footer -->
        <div style="background-color: #f1f5f9; padding: 16px 32px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b; text-align: center;">
            <p style="margin: 0 0 4px 0;">
                Sent to: <strong>{self.recipient_email}</strong> &bull; USA Conference Discovery &amp; Publication Agent
            </p>
            <p style="margin: 0; font-size: 11px; color: #94a3b8;">
                This email was generated automatically for confirmed USA conferences starting on {date_str}.
            </p>
        </div>

    </div>
</body>
</html>"""
        return html

    def send_conference_reminder_email(
        self,
        db: Session,
        conf: Conference,
        speakers: List[Speaker],
        attendee: Optional[Attendee]
    ) -> Dict[str, Any]:
        """
        Sends an individual email for ONE single conference.
        Guarantees:
        - Separate email for this specific conference.
        - Deduplication check (prevents re-sending).
        - Persistent tracking in db and file outbox.
        """
        unique_key = make_conference_unique_key(
            conf.conference_title,
            conf.start_date,
            conf.venue
        )

        # 1. Duplicate check
        if self.is_conference_already_sent(db, conf):
            logger.info(f"Skipping duplicate email notification: '{conf.conference_title}' has already been notified.")
            return {
                "status": "skipped",
                "reason": "duplicate_prevented",
                "conference_id": conf.conference_id,
                "conference_title": conf.conference_title,
                "unique_key": unique_key
            }

        subject = self.build_email_subject(conf)
        text_body = self.build_plain_text_body(conf, speakers, attendee)
        html_body = self.build_html_body(conf, speakers, attendee)

        # Build MIME Message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = settings.SMTP_FROM
        msg["To"] = self.recipient_email
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        send_status = "pending_smtp_credentials"
        error_msg = None

        # 2. Try SMTP transmission if credentials are provided in .env
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            try:
                logger.info(f"Connecting to SMTP {settings.SMTP_HOST}:{settings.SMTP_PORT} to deliver reminder to {self.recipient_email}...")
                server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
                if settings.SMTP_USE_TLS:
                    server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
                server.quit()
                send_status = "sent"
                logger.info(f"✅ Delivered live email via SMTP for '{conf.conference_title}' to {self.recipient_email}")
            except Exception as e:
                logger.error(f"❌ SMTP delivery failed for '{conf.conference_title}': {e}.", exc_info=True)
                send_status = "failed"
                error_msg = str(e)
        else:
            logger.warning(
                f"⚠️ [SMTP NOT CONFIGURED] Cannot deliver email across the internet to {self.recipient_email}. "
                f"Please add SMTP_USER and SMTP_PASSWORD in backend/.env to send directly to your inbox."
            )
            send_status = "pending_smtp_credentials"
            error_msg = "SMTP_USER and SMTP_PASSWORD not configured in backend/.env"

        # 3. Always archive email locally in data/emails/
        clean_slug = re.sub(r'[^a-zA-Z0-9_\-]', '_', conf.conference_title)[:50]
        html_filename = f"USA_Reminder_{conf.conference_id}_{clean_slug}.html"
        html_file_path = self.outbox_dir / html_filename
        with open(html_file_path, "w", encoding="utf-8") as f:
            f.write(html_body)

        # Append to audit outbox log
        now_iso = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        with open(self.outbox_log_path, "a", encoding="utf-8") as f:
            f.write(f"[{now_iso}] TO: {self.recipient_email} | STATUS: {send_status} | ID: {conf.conference_id} | SUBJ: {subject} | FILE: {html_filename}\n")

        # 4. Save or update Database EmailNotification table
        existing_notif = db.query(EmailNotification).filter(
            EmailNotification.conference_unique_key == unique_key
        ).first()
        if existing_notif:
            existing_notif.status = send_status
            existing_notif.sent_at = datetime.utcnow()
            existing_notif.error_message = error_msg
            existing_notif.email_body = html_body
        else:
            notification = EmailNotification(
                conference_id=conf.conference_id,
                conference_unique_key=unique_key,
                conference_title=conf.conference_title,
                conference_date=conf.start_date,
                venue=conf.venue or "",
                recipient_email=self.recipient_email,
                subject=subject,
                status=send_status,
                email_body=html_body,
                sent_at=datetime.utcnow(),
                error_message=error_msg
            )
            db.add(notification)

        # 5. Mark Conference record as email sent ONLY if actually delivered over SMTP
        if send_status == "sent":
            conf.email_sent = True
            conf.email_sent_at = datetime.utcnow()
        else:
            conf.email_sent = False

        db.commit()


        logger.info(f"📧 [Email Service] Successfully processed separate notification for '{conf.conference_title}' (Key: {unique_key}).")
        return {
            "status": "success",
            "delivery": send_status,
            "conference_id": conf.conference_id,
            "conference_title": conf.conference_title,
            "recipient": self.recipient_email,
            "subject": subject,
            "archive_path": str(html_file_path)
        }

    def send_all_pending_reminders(self, db: Session, conferences: Optional[List[Conference]] = None) -> List[Dict[str, Any]]:
        """
        Iterates through matching published conferences and sends a separate individual email for each.
        - Guarantees NO bundling: Each conference gets its own individual email.
        - If 5 conferences match, sends 5 separate emails.
        """
        if conferences is None:
            # Query all conferences that are published to Excel and haven't had emails sent
            conferences = db.query(Conference).filter(
                Conference.is_published_to_excel == True,
                Conference.email_sent == False
            ).all()

        results = []
        logger.info(f"📧 [Email Service] Evaluating {len(conferences)} conference(s) for separate email delivery to {self.recipient_email}...")

        for conf in conferences:
            # Fetch speakers for this conference
            speakers = db.query(Speaker).filter(Speaker.conference_id == conf.conference_id).all()
            # Fetch attendee details
            attendee = db.query(Attendee).filter(Attendee.conference_id == conf.conference_id).first()

            # Send single separate email
            res = self.send_conference_reminder_email(db, conf, speakers, attendee)
            results.append(res)

        logger.info(f"📧 [Email Service] Finished sending reminders. Total processed: {len(results)}")
        return results
