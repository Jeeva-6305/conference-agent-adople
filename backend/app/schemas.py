from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field

class RawEventData(BaseModel):
    source_name: str
    source_url: str
    raw_title: str
    raw_text: str
    raw_location: Optional[str] = None
    raw_date: Optional[str] = None

class SpeakerDetailItem(BaseModel):
    speaker_name: str = Field(description="Full name of speaker")
    job_role_designation: str = Field(default="", description="Job role or designation")
    company_organization: str = Field(default="", description="Company or organization name")
    company_name: str = Field(default="", description="Company name")
    official_company_website_url: Optional[str] = Field(default="", description="Official website URL where the speaker works")
    linkedin_url: Optional[str] = Field(default="", description="Speaker's original LinkedIn profile URL")
    location: str = Field(default="", description="Location or city/state of speaker/organization")
    previous_speaking_info: Optional[str] = Field(default="", description="Previous speaking information or talks if available")

class AttendeeDetailItem(BaseModel):
    expected_attendee_count: Optional[str] = Field(default="", description="Expected attendee count if available, or empty")
    registered_attendee_count: Optional[str] = Field(default="", description="Registered attendee count if publicly available, or empty")
    attendee_categories: Optional[str] = Field(default="", description="Attendee / participant categories")
    target_audience: Optional[str] = Field(default="", description="Target audience description")
    industries: Optional[str] = Field(default="", description="Industries represented")
    job_roles: Optional[str] = Field(default="", description="Job roles and professions represented")

class AIConferenceExtraction(BaseModel):
    conference_title: str = Field(description="The formal title of the conference")
    industry_category: str = Field(description="Industry or domain, e.g. Technology, AI, Healthcare, Finance, Energy")
    start_date: str = Field(description="Conference start date in YYYY-MM-DD format")
    end_date: str = Field(description="Conference end date in YYYY-MM-DD format")
    speakers: List[str] = Field(default=[], description="List of all keynote or featured speaker names")
    speaker_titles_companies: List[str] = Field(default=[], description="List of titles/companies corresponding to speakers")
    speaker_details: List[SpeakerDetailItem] = Field(default=[], description="All extracted speaker profiles with full available details")
    attendee_details: Optional[AttendeeDetailItem] = Field(default=None, description="Extracted attendee and participant profile info")
    speaker_talks_details: Optional[str] = Field(default="", description="Previous talks, keynotes, or speaking details")
    description: Optional[str] = Field(default="", description="Comprehensive verified conference overview")
    venue: str = Field(default="Conference Center", description="Venue name or hotel")
    city: str = Field(description="US City where conference takes place")
    country: str = Field(default="USA", description="Must be USA or United States")
    organizer: str = Field(default="", description="Name of organizing company or association")
    official_conference_url: str = Field(default="", description="Official conference homepage link")
    registration_url: str = Field(default="", description="Registration or ticketing URL")
    publication_date: Optional[str] = Field(default="", description="Original conference publication or announcement date (YYYY-MM-DD)")
    speakers_available: Optional[str] = Field(default="Yes", description="'Yes' if speakers/auditors available, 'No' otherwise")
    is_valid_usa_conference: bool = Field(description="True if this is a verified conference happening in the USA")


class ConferenceResponse(BaseModel):
    id: int
    conference_id: str
    conference_title: str
    industry_category: str
    start_date: date
    end_date: date
    speakers: Optional[str] = ""
    speaker_titles_companies: Optional[str] = ""
    speaker_talks_details: Optional[str] = ""
    description: Optional[str] = ""
    venue: str
    city: str
    country: str
    organizer: str
    official_conference_url: str
    registration_url: str
    source_url: str
    source_name: str
    is_published_to_excel: bool
    publication_date: Optional[date]
    speakers_available: Optional[str] = "Yes"
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class SpeakerResponse(BaseModel):
    id: int
    conference_id: str
    conference_name: str
    speaker_name: str
    company_organization: str
    job_role_designation: str
    company_name: str
    official_company_website_url: Optional[str] = ""
    linkedin_url: Optional[str] = ""
    location: str
    previous_speaking_info: Optional[str] = ""
    created_at: datetime

    class Config:
        from_attributes = True

class AttendeeResponse(BaseModel):
    id: int
    conference_id: str
    conference_name: str
    expected_attendee_count: Optional[str] = ""
    registered_attendee_count: Optional[str] = ""
    attendee_categories: Optional[str] = ""
    target_audience: Optional[str] = ""
    industries: Optional[str] = ""
    job_roles: Optional[str] = ""
    source_url: Optional[str] = ""
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_conferences: int
    published_to_excel: int
    upcoming_2_days: int
    sources_active: int
    last_scrape_time: Optional[datetime] = None
    next_scrape_time: Optional[datetime] = None
    scheduler_interval: Optional[str] = "Every 1 hour"
    excel_path: str
