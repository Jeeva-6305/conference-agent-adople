import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Date, DateTime, Boolean, Text, Integer
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
    speakers_available = Column(String(10), default="Yes")  # "Yes" or "No"
    status = Column(String(50), default="discovered")  # discovered, published
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "Conference ID": self.conference_id,
            "Conference Title": self.conference_title,
            "Industry / Category": self.industry_category,
            "Conference Start Date": self.start_date.isoformat() if self.start_date else "",
            "Conference End Date": self.end_date.isoformat() if self.end_date else "",
            "Speakers Available": self.speakers_available or "Yes",
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
    company_organization = Column(String(255), default="")
    job_role_designation = Column(String(255), default="")
    company_name = Column(String(255), default="")
    official_company_website_url = Column(String(500), default="")
    linkedin_url = Column(String(500), default="")
    location = Column(String(255), default="")
    previous_speaking_info = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "Speaker Name": self.speaker_name,
            "Conference Name": self.conference_name,
            "Company / Organization": self.company_organization,
            "Job Role / Designation": self.job_role_designation,
            "Company Name": self.company_name,
            "Official Company Website URL": self.official_company_website_url or "",
            "Speaker LinkedIn Profile URL": self.linkedin_url or "",
            "Location": self.location
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

