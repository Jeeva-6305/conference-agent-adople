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

class AIConferenceExtraction(BaseModel):
    conference_title: str = Field(description="The formal title of the conference")
    industry_category: str = Field(description="Industry or domain, e.g. Technology, AI, Healthcare, Finance, Energy")
    start_date: str = Field(description="Conference start date in YYYY-MM-DD format")
    end_date: str = Field(description="Conference end date in YYYY-MM-DD format")
    speakers: List[str] = Field(default=[], description="List of keynote or featured speaker names")
    speaker_titles_companies: List[str] = Field(default=[], description="List of titles/companies corresponding to speakers")
    venue: str = Field(default="Conference Center", description="Venue name or hotel")
    city: str = Field(description="US City where conference takes place")
    country: str = Field(default="USA", description="Must be USA or United States")
    organizer: str = Field(default="", description="Name of organizing company or association")
    official_conference_url: str = Field(default="", description="Official conference homepage link")
    registration_url: str = Field(default="", description="Registration or ticketing URL")
    is_valid_usa_conference: bool = Field(description="True if this is a verified conference happening in the USA")

class ConferenceResponse(BaseModel):
    id: int
    conference_id: str
    conference_title: str
    industry_category: str
    start_date: date
    end_date: date
    speakers: str
    speaker_titles_companies: str
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
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class DashboardStats(BaseModel):
    total_conferences: int
    published_to_excel: int
    upcoming_2_days: int
    sources_active: int
    last_scrape_time: Optional[datetime]
    excel_path: str
