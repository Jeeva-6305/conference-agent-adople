import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Date, DateTime, Boolean, Text, Integer, Float
from .database import Base

def generate_conf_id() -> str:
    return f"CONF-{datetime.now().year}-{uuid.uuid4().hex[:6].upper()}"

class Conference(Base):
    __tablename__ = "conferences"

    id = Column(Integer, primary_key=True, index=True)
    conference_id = Column(String(50), unique=True, index=True, default=generate_conf_id)
    conference_title = Column(String(255), nullable=False, index=True)
    industry_category = Column(String(100), default="Technology & Business")
    
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False)
    
    
    # Conference Overview & Details
    description = Column(Text, default="")
    
    # Location details
    venue = Column(String(255), default="Convention Center")
    city = Column(String(100), default="San Francisco")
    country = Column(String(50), default="USA")
    
    # Organizer & Links
    organizer = Column(String(255), default="")
    official_conference_url = Column(String(500), default="")
    registration_url = Column(String(500), default="")
    source_url = Column(String(500), nullable=False)
    source_name = Column(String(50), nullable=False)  # 10times, luma, eventbrite, meetup, cvent, events_in_america
    
    # Publication Status
    is_published_to_excel = Column(Boolean, default=False, index=True)
    publication_date = Column(Date, nullable=True)  # Populated with actual original conference publication date
    speakers_available = Column(String(10), default="No")  # "Yes" or "No"
    status = Column(String(50), default="discovered")  # discovered, published
    
    # Email Notification Tracking
    email_sent = Column(Boolean, default=False, index=True)
    email_sent_at = Column(DateTime, nullable=True)
    
    # Microsoft Teams Webhook Tracking
    teams_webhook_sent = Column(Boolean, default=False, index=True)
    teams_webhook_sent_at = Column(DateTime, nullable=True)
    
    created_at = Column(DateTime, default=datetime.utcnow)

    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "Conference ID": self.conference_id,
            "Conference Title": self.conference_title,
            "Industry / Category": self.industry_category,
            "Conference Start Date": self.start_date.isoformat() if self.start_date else "",
            "Conference End Date": self.end_date.isoformat() if self.end_date else "",
            "Speakers Available": self.speakers_available or "No",
            "Venue": self.venue,
            "City": self.city,
            "Country": self.country,
            "Organizer": self.organizer,
            "Official Conference URL": self.official_conference_url,
            "Registration URL": self.registration_url,
            "Source URL": self.source_url,
            "Publication Date": self.publication_date.isoformat() if self.publication_date else ""
        }

class Speaker(Base):
    __tablename__ = "speakers"

    id = Column(Integer, primary_key=True, index=True)
    conference_id = Column(String(50), index=True)
    conference_name = Column(String(255), nullable=False)
    speaker_name = Column(String(255), nullable=False)
    company_organization = Column(Text, default="")
    job_role_designation = Column(Text, default="")
    company_name = Column(Text, default="")
    official_company_website_url = Column(String(500), default="")
    linkedin_url = Column(String(500), default="")
    location = Column(String(255), default="")
    source_url = Column(String(500), default="")
    previous_speaking_info = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "Conference Name": self.conference_name,
            "Speaker Name": self.speaker_name,
            "Company Name": self.company_name or self.company_organization,
            "Job Role / Designation": self.job_role_designation,
            "Original LinkedIn Profile URL": self.linkedin_url or "",
            "Company Website URL": self.official_company_website_url or "",
            "Source URL": self.source_url or "",
            "Location": self.location or ""
        }

class Attendee(Base):
    __tablename__ = "attendees"

    id = Column(Integer, primary_key=True, index=True)
    conference_id = Column(String(50), index=True)
    conference_name = Column(String(255), nullable=False)
    expected_attendee_count = Column(String(100), default="")
    registered_attendee_count = Column(String(100), default="")
    attendee_categories = Column(String(255), default="")
    target_audience = Column(Text, default="")
    industries = Column(String(255), default="")
    job_roles = Column(Text, default="")
    source_url = Column(String(500), default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "Conference ID": self.conference_id,
            "Conference Name": self.conference_name,
            "Expected Attendee Count": self.expected_attendee_count or "",
            "Registered Attendee Count": self.registered_attendee_count or "",
            "Attendee / Participant Categories": self.attendee_categories or "",
            "Target Audience": self.target_audience or "",
            "Industries": self.industries or "",
            "Job Roles / Professions Represented": self.job_roles or "",
            "Source URL": self.source_url or ""
        }


def make_conference_unique_key(title: str, start_date, venue: str) -> str:
    """Generate persistent unique identifier: Conference Name + Conference Date + Venue"""
    t = (title or "").strip().lower()
    d = start_date.isoformat() if hasattr(start_date, "isoformat") else str(start_date or "").strip()
    v = (venue or "").strip().lower()
    return f"{t}|{d}|{v}"


class EmailNotification(Base):
    __tablename__ = "email_notifications"

    id = Column(Integer, primary_key=True, index=True)
    conference_id = Column(String(50), index=True)
    conference_unique_key = Column(String(500), unique=True, index=True)
    conference_title = Column(String(255), nullable=False)
    conference_date = Column(Date, nullable=False)
    venue = Column(String(255), default="")
    recipient_email = Column(String(255), nullable=False, default="jeevanandham@adople.ai")
    subject = Column(String(500), nullable=False)
    status = Column(String(50), default="sent")
    email_body = Column(Text, default="")
    sent_at = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "conference_id": self.conference_id,
            "conference_unique_key": self.conference_unique_key,
            "conference_title": self.conference_title,
            "conference_date": self.conference_date.isoformat() if self.conference_date else "",
            "venue": self.venue,
            "recipient_email": self.recipient_email,
            "subject": self.subject,
            "status": self.status,
            "sent_at": self.sent_at.isoformat() if self.sent_at else "",
            "error_message": self.error_message or ""
        }


class TeamsNotification(Base):
    __tablename__ = "teams_notifications"

    id = Column(Integer, primary_key=True, index=True)
    conference_id = Column(String(50), index=True)
    conference_unique_key = Column(String(500), unique=True, index=True)
    conference_title = Column(String(255), nullable=False)
    conference_date = Column(Date, nullable=False)
    venue = Column(String(255), default="")
    webhook_url = Column(String(1000), nullable=False)
    status = Column(String(50), default="sent")
    card_payload = Column(Text, default="")
    sent_at = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "conference_id": self.conference_id,
            "conference_unique_key": self.conference_unique_key,
            "conference_title": self.conference_title,
            "conference_date": self.conference_date.isoformat() if self.conference_date else "",
            "venue": self.venue,
            "webhook_url": self.webhook_url,
            "status": self.status,
            "sent_at": self.sent_at.isoformat() if self.sent_at else "",
            "error_message": self.error_message or ""
        }


# =========================================================================
# WEEKLY CONFERENCE WORKFLOW MODELS (ISOLATED FROM T-2)
# =========================================================================

class WeeklyConference(Base):
    __tablename__ = "weekly_conferences"

    id = Column(Integer, primary_key=True, index=True)
    conference_id = Column(String(50), unique=True, index=True)
    conference_name = Column(String(255), nullable=False, index=True)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=True)
    city = Column(String(100), default="")
    state = Column(String(100), default="")
    country = Column(String(100), default="USA")
    industry = Column(String(255), default="")
    official_event_url = Column(Text, default="")
    source_name = Column(String(100), default="")
    source_url = Column(Text, default="")
    link_status = Column(String(50), default="verified")  # verified, needs_review, unverified_access_restricted, broken
    speaker_status = Column(String(50), default="No")  # Yes / No
    weekly_run_id = Column(String(100), nullable=False, index=True)
    icp_score = Column(Float, default=0.0)
    icp_rank = Column(Integer, default=0)
    icp_tier = Column(String(100), default="")
    industry_fit_score = Column(Float, default=0.0)
    audience_fit_score = Column(Float, default=0.0)
    last_checked_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "conference_id": self.conference_id,
            "conference_name": self.conference_name,
            "start_date": self.start_date.isoformat() if self.start_date else "",
            "end_date": self.end_date.isoformat() if self.end_date else "",
            "city": self.city,
            "state": self.state,
            "country": self.country,
            "industry": self.industry,
            "official_event_url": self.official_event_url,
            "source_name": self.source_name,
            "source_url": self.source_url,
            "link_status": self.link_status,
            "speaker_status": self.speaker_status,
            "weekly_run_id": self.weekly_run_id,
            "icp_score": float(self.icp_score or 0.0),
            "icp_rank": int(self.icp_rank or 0),
            "icp_tier": self.icp_tier or "",
            "industry_fit_score": float(self.industry_fit_score or 0.0),
            "audience_fit_score": float(self.audience_fit_score or 0.0),
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else ""
        }


class WeeklySpeaker(Base):
    __tablename__ = "weekly_speakers"

    id = Column(Integer, primary_key=True, index=True)
    speaker_id = Column(String(50), unique=True, index=True)
    conference_id = Column(String(50), nullable=False, index=True)
    conference_name = Column(String(255), nullable=False)
    speaker_name = Column(String(255), nullable=False, index=True)
    job_title = Column(String(255), default="")
    company_name = Column(String(255), default="")
    personal_linkedin_url = Column(Text, default="")
    linkedin_status = Column(String(50), default="needs_review")  # verified, needs_review, unverified_access_restricted
    professional_email = Column(String(255), default="")
    email_source_url = Column(Text, default="")
    speaker_source_url = Column(Text, default="")
    verification_status = Column(String(50), default="needs_review")  # verified, needs_review
    weekly_run_id = Column(String(100), nullable=False, index=True)
    icp_score = Column(Float, default=0.0)
    icp_rank = Column(Integer, default=0)
    icp_tier = Column(String(100), default="")
    industry_fit_score = Column(Float, default=0.0)
    scale_fit_score = Column(Float, default=0.0)
    company_headcount_estimate = Column(String(50), default="")
    pitch_hook = Column(Text, default="")
    outreach_status = Column(String(50), default="")  # sent, sending, failed, skipped_*
    reply_status = Column(String(50), default="")     # replied, bounced
    reply_sentiment = Column(String(50), default="")  # Positive, Negative, Neutral
    received_reply = Column(Text, default="")         # full conversation transcript
    sent_message = Column(Text, default="")           # exact email body sent
    email_thread_id = Column(String(255), default="") # Microsoft Graph conversationId
    email_sent_at = Column(DateTime, nullable=True)
    follow_up_count = Column(Integer, default=0)
    follow_up_status = Column(String(50), default="")
    last_checked_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "speaker_id": self.speaker_id,
            "conference_id": self.conference_id,
            "conference_name": self.conference_name,
            "speaker_name": self.speaker_name,
            "job_title": self.job_title,
            "company_name": self.company_name,
            "personal_linkedin_url": self.personal_linkedin_url,
            "linkedin_status": self.linkedin_status,
            "professional_email": self.professional_email,
            "email_source_url": self.email_source_url,
            "speaker_source_url": self.speaker_source_url,
            "verification_status": self.verification_status,
            "weekly_run_id": self.weekly_run_id,
            "icp_score": float(self.icp_score or 0.0),
            "icp_rank": int(self.icp_rank or 0),
            "icp_tier": self.icp_tier or "",
            "industry_fit_score": float(self.industry_fit_score or 0.0),
            "scale_fit_score": float(self.scale_fit_score or 0.0),
            "company_headcount_estimate": self.company_headcount_estimate or "",
            "pitch_hook": self.pitch_hook or "",
            "outreach_status": self.outreach_status or "",
            "reply_status": self.reply_status or "",
            "reply_sentiment": self.reply_sentiment or "",
            "received_reply": self.received_reply or "",
            "email_thread_id": self.email_thread_id or "",
            "email_sent_at": self.email_sent_at.isoformat() if self.email_sent_at else "",
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else ""
        }


class WeeklyCompany(Base):
    __tablename__ = "weekly_companies"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(255), nullable=False, index=True)
    company_domain = Column(String(255), default="")
    official_website = Column(Text, default="")
    primary_industry = Column(String(255), default="")
    headcount_tier = Column(String(100), default="")
    conference_name = Column(String(255), default="")
    conference_id = Column(String(50), default="")
    weekly_run_id = Column(String(100), nullable=False, index=True)
    icp_score = Column(Float, default=0.0)
    icp_rank = Column(Integer, default=0)
    icp_tier = Column(String(100), default="")
    industry_fit_score = Column(Float, default=0.0)
    scale_fit_score = Column(Float, default=0.0)
    qualification_status = Column(String(50), default="")
    strategic_justification = Column(Text, default="")
    pitch_hook = Column(Text, default="")
    last_checked_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "company_name": self.company_name,
            "company_domain": self.company_domain,
            "official_website": self.official_website,
            "primary_industry": self.primary_industry,
            "headcount_tier": self.headcount_tier,
            "conference_name": self.conference_name,
            "conference_id": self.conference_id,
            "weekly_run_id": self.weekly_run_id,
            "icp_score": float(self.icp_score or 0.0),
            "icp_rank": int(self.icp_rank or 0),
            "icp_tier": self.icp_tier or "",
            "industry_fit_score": float(self.industry_fit_score or 0.0),
            "scale_fit_score": float(self.scale_fit_score or 0.0),
            "qualification_status": self.qualification_status or "",
            "strategic_justification": self.strategic_justification or "",
            "pitch_hook": self.pitch_hook or "",
            "last_checked_at": self.last_checked_at.isoformat() if self.last_checked_at else ""
        }


class WeeklySourceRunLog(Base):
    __tablename__ = "weekly_source_run_log"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String(100), nullable=False, index=True)
    run_date = Column(Date, nullable=False)
    source_name = Column(String(100), nullable=False)
    source_status = Column(String(50), default="success")  # success, error, timeout, unverified_access_restricted
    pages_checked = Column(Integer, default=1)
    conferences_found = Column(Integer, default=0)
    conferences_accepted = Column(Integer, default=0)
    speakers_found = Column(Integer, default=0)
    error_details = Column(Text, default="")
    duration_seconds = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "run_date": self.run_date.isoformat() if self.run_date else "",
            "source_name": self.source_name,
            "source_status": self.source_status,
            "pages_checked": self.pages_checked,
            "conferences_found": self.conferences_found,
            "conferences_accepted": self.conferences_accepted,
            "speakers_found": self.speakers_found,
            "error_details": self.error_details or "",
            "duration_seconds": self.duration_seconds
        }


class WeeklyTeamsCardLog(Base):
    __tablename__ = "weekly_teams_card_log"

    id = Column(Integer, primary_key=True, index=True)
    weekly_run_id = Column(String(100), unique=True, index=True)
    target_start_date = Column(Date, nullable=False)
    target_end_date = Column(Date, nullable=False)
    total_conferences = Column(Integer, default=0)
    industry_summary = Column(Text, default="")
    webhook_url = Column(String(1000), default="")
    status = Column(String(50), default="sent")
    card_payload = Column(Text, default="")
    sent_at = Column(DateTime, default=datetime.utcnow)
    error_message = Column(Text, nullable=True)


class WeeklyAttendee(Base):
    __tablename__ = "weekly_attendees"

    id = Column(Integer, primary_key=True, index=True)
    attendee_id = Column(String(50), unique=True, index=True)
    conference_id = Column(String(50), nullable=False, index=True)
    conference_name = Column(String(255), nullable=False, index=True)
    conference_date = Column(Date, nullable=True)
    attendee_name = Column(String(255), nullable=False, index=True)
    job_title = Column(String(255), default="")
    company_name = Column(String(255), default="")
    professional_email = Column(String(255), default="")
    email_status = Column(String(50), default="Not Found")  # Verified, Not Found
    personal_linkedin_url = Column(Text, default="")
    linkedin_status = Column(String(50), default="needs_review")  # verified, not_found, not_applicable
    source_url = Column(Text, default="")
    availability_status = Column(String(50), default="Available")  # Available, Not Publicly Available
    weekly_run_id = Column(String(100), nullable=False, index=True)
    collection_date = Column(Date, default=date.today)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "attendee_id": self.attendee_id,
            "conference_id": self.conference_id,
            "conference_name": self.conference_name,
            "conference_date": self.conference_date.isoformat() if self.conference_date else "",
            "attendee_name": self.attendee_name,
            "job_title": self.job_title,
            "company_name": self.company_name,
            "professional_email": self.professional_email,
            "email_status": self.email_status,
            "personal_linkedin_url": self.personal_linkedin_url,
            "linkedin_status": self.linkedin_status,
            "source_url": self.source_url,
            "availability_status": self.availability_status,
            "weekly_run_id": self.weekly_run_id,
            "collection_date": self.collection_date.isoformat() if self.collection_date else ""
        }


class WeeklyExhibitor(Base):
    __tablename__ = "weekly_exhibitors"

    id = Column(Integer, primary_key=True, index=True)
    exhibitor_id = Column(String(50), unique=True, index=True)
    conference_id = Column(String(50), nullable=False, index=True)
    conference_name = Column(String(255), nullable=False, index=True)
    conference_date = Column(Date, nullable=True)
    company_name = Column(String(255), nullable=False, index=True)
    company_website = Column(Text, default="")
    category_industry = Column(String(255), default="")
    company_description = Column(Text, default="")
    booth_number = Column(String(100), default="")
    contact_person = Column(String(255), default="")
    contact_designation = Column(String(255), default="")
    professional_email = Column(String(255), default="")
    email_status = Column(String(50), default="Not Found")  # Verified, Not Found
    company_linkedin_url = Column(Text, default="")
    contact_person_linkedin_url = Column(Text, default="")
    source_url = Column(Text, default="")
    availability_status = Column(String(50), default="Available")  # Available, Not Publicly Available
    weekly_run_id = Column(String(100), nullable=False, index=True)
    collection_date = Column(Date, default=date.today)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "exhibitor_id": self.exhibitor_id,
            "conference_id": self.conference_id,
            "conference_name": self.conference_name,
            "conference_date": self.conference_date.isoformat() if self.conference_date else "",
            "company_name": self.company_name,
            "company_website": self.company_website,
            "category_industry": self.category_industry,
            "company_description": self.company_description,
            "booth_number": self.booth_number,
            "contact_person": self.contact_person,
            "contact_designation": self.contact_designation,
            "professional_email": self.professional_email,
            "email_status": self.email_status,
            "company_linkedin_url": self.company_linkedin_url,
            "contact_person_linkedin_url": self.contact_person_linkedin_url,
            "source_url": self.source_url,
            "availability_status": self.availability_status,
            "weekly_run_id": self.weekly_run_id,
            "collection_date": self.collection_date.isoformat() if self.collection_date else ""
        }


class SpeakerReply(Base):
    """
    Dedicated Speaker Reply Model:
    Stores every distinct incoming reply message from an outreach email.
    Preserves multiple replies per speaker without overwriting.
    """
    __tablename__ = "speaker_replies"

    id = Column(Integer, primary_key=True, index=True)
    speaker_id = Column(String(50), index=True)
    conference_id = Column(String(50), index=True)
    conference_name = Column(String(255), default="")
    speaker_name = Column(String(255), nullable=False)
    job_title = Column(String(255), default="")
    company_name = Column(String(255), default="")
    personal_linkedin_url = Column(Text, default="")
    linkedin_status = Column(String(50), default="")
    professional_email = Column(String(255), index=True)
    email_source_url = Column(Text, default="")
    speaker_source_url = Column(Text, default="")
    verification_status = Column(String(50), default="")
    last_checked_at = Column(DateTime, default=datetime.utcnow)
    weekly_run_id = Column(String(100), default="")
    outreach_status = Column(String(50), default="sent")
    reply_status = Column(String(50), default="replied")
    reply_sentiment = Column(String(50), default="Neutral")
    received_reply = Column(Text, default="")
    sent_message = Column(Text, default="")
    thread_id = Column(String(255), index=True)
    reply_received_at = Column(DateTime, default=datetime.utcnow)
    message_id = Column(String(255), unique=True, index=True)
    original_speaker_id = Column(String(50), index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "speaker_id": self.speaker_id,
            "conference_id": self.conference_id,
            "conference_name": self.conference_name,
            "speaker_name": self.speaker_name,
            "job_title": self.job_title,
            "company_name": self.company_name,
            "professional_email": self.professional_email,
            "reply_sentiment": self.reply_sentiment,
            "received_reply": self.received_reply,
            "reply_received_at": self.reply_received_at.isoformat() if self.reply_received_at else "",
            "message_id": self.message_id,
            "thread_id": self.thread_id,
        }






