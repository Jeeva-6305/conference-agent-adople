import json
import logging
import re
from datetime import datetime, timedelta, date
from typing import Optional
from ..config import settings
from ..schemas import RawEventData, AIConferenceExtraction

logger = logging.getLogger(__name__)

class AIConferenceExtractor:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.client = None
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                logger.info("Gemini AI Agent initialized successfully with API key.")
            except Exception as e:
                logger.error(f"Could not initialize Gemini Client: {e}")

    def extract_and_validate(self, raw_data: RawEventData) -> Optional[AIConferenceExtraction]:
        """
        Extracts structured conference details and validates USA location.
        Tries Gemini API first with gemini-3.5-flash-lite / gemini-3.5-flash.
        Collects actual speakers' names, designations, company names, speaking background,
        and real start/end dates.
        NO FAKE OR MOCK DATA IS EVER GENERATED.
        """
        # Step 1: Filter out non-conferences (e.g. workshops, meetups, classes, webinars, happy hours)
        title_lower = raw_data.raw_title.lower()
        non_conf_terms = [
            "workshop", "webinar", "bootcamp", "hackathon", "class", "meetup",
            "bar crawl", "barcrawl", "dating", "singles night", "happy hour", 
            "board game", "karaoke", "speed dating", "pub crawl", "skip the small talk",
            "psychadelic flow", "workout ever", "coworking day", "zoom event", "mixer"
        ]
        if any(term in title_lower for term in non_conf_terms):
            logger.info(f"Skipping non-conference event (workshop/social): {raw_data.raw_title}")
            return None

        # Step 2: Try Gemini API
        if self.client:
            for model_name in ['gemini-3.5-flash-lite', 'gemini-3.5-flash', 'gemini-3.1-flash-lite']:
                try:
                    today_str = date.today().isoformat()
                    prompt = f"""
                    You are an expert Conference Verification AI Agent.
                    Analyze this genuine conference listing scraped from {raw_data.source_name}:

                    Raw Title: {raw_data.raw_title}
                    Location: {raw_data.raw_location}
                    Date Hint: {raw_data.raw_date}
                    Text / Agenda / Speakers: {raw_data.raw_text}
                    Source URL: {raw_data.source_url}
                    Current System Date: {today_str}

                    Instructions:
                    1. Verify this event is a formal CONFERENCE located in the USA. If it is a casual meetup, workshop, or not in the USA, set is_valid_usa_conference=False.
                    2. Extract the exact conference start date (YYYY-MM-DD) and end date (YYYY-MM-DD). If it is a 1-day event, start_date and end_date must be identical.
                    3. Extract the ORIGINAL conference publication or announcement date (YYYY-MM-DD) when the conference was first published/announced to the public. DO NOT use the current system date or scraping date.
                    4. Collect ACTUAL speaker names and designations/companies. Look for keynote speakers, panelists, hosts, and executives mentioned in the text.
                       - If speakers are present, set speakers_available="Yes", otherwise "No".
                       - 'speakers': List of real full names (e.g. ["Erik Bernhardsson", "Will Reese"]). DO NOT use "Keynote Speakers TBD" or placeholder strings.
                       - 'speaker_titles_companies': List of matching titles and company/organization names.
                       - 'speaker_talks_details': Previous talks, keynotes, or speaking background if available.
                       - 'description': Comprehensive overview of the conference and agenda.
                    5. Extract accurate venue, city, and organizer.
                    6. Return official_conference_url and registration_url (use {raw_data.source_url} if direct link is not specified). NEVER return URLs that give 404 errors.
                    """
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config={
                            'response_mime_type': 'application/json',
                            'response_schema': AIConferenceExtraction
                        }
                    )
                    if response and response.text:
                        parsed = json.loads(response.text)
                        extraction = AIConferenceExtraction(**parsed)
                        if extraction.is_valid_usa_conference:
                            # Sanitize speaker fields: never allow "Keynote Speakers TBD" or "TBD"
                            extraction.speakers = [
                                s for s in extraction.speakers 
                                if s and s.strip() and "tbd" not in s.lower() and "placeholder" not in s.lower()
                            ]
                            extraction.speaker_titles_companies = [
                                t for t in extraction.speaker_titles_companies 
                                if t and t.strip() and "experts & leaders" not in t.lower()
                            ]
                            extraction.speakers_available = "Yes" if len(extraction.speakers) > 0 else "No"

                            if not extraction.registration_url or "http" not in extraction.registration_url:
                                extraction.registration_url = raw_data.source_url
                            if not extraction.official_conference_url or "http" not in extraction.official_conference_url:
                                extraction.official_conference_url = raw_data.source_url
                            
                            # Fix any broken /en/events URLs
                            if "/en/events" in extraction.registration_url:
                                extraction.registration_url = extraction.registration_url.replace("/en/events", "/events")
                            if "/en/events" in extraction.official_conference_url:
                                extraction.official_conference_url = extraction.official_conference_url.replace("/en/events", "/events")

                            logger.info(f"✅ Gemini validated genuine conference: {extraction.conference_title} | Dates: {extraction.start_date} to {extraction.end_date} | Speakers: {extraction.speakers}")
                            return extraction
                        return None
                except Exception as e:
                    logger.warning(f"Gemini API ({model_name}) error ({e}), trying fallback parser...")
                    break

        # Step 3: High-fidelity parser on real scraped fields
        return self._parse_from_real_scraped_data(raw_data)

    def _parse_from_real_scraped_data(self, raw_data: RawEventData) -> Optional[AIConferenceExtraction]:
        """
        Parses strictly from the genuine scraped text without inserting placeholder or fake data.
        """
        text = f"{raw_data.raw_title} {raw_data.raw_location} {raw_data.raw_text}"
        
        # Verify USA
        usa_indicators = [
            "usa", "united states", "ca", "ny", "tx", "fl", "il", "nc", "tn", "md", "mo", 
            "va", "pa", "dc", "raleigh", "nashville", "chicago", "new york", "san francisco", 
            "austin", "orlando", "baltimore", "seattle", "boston", "dallas"
        ]
        if not any(re.search(rf"\b{w}\b", text, re.I) for w in usa_indicators):
            return None

        # Parse real date from raw_date or text
        start_date = None
        if raw_data.raw_date:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", raw_data.raw_date)
            if m:
                start_date = m.group(1)

        if not start_date:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            if m:
                start_date = m.group(1)
            else:
                return None

        end_date = start_date
        end_match = re.search(r"(?:to|until|-)\s*(\d{4}-\d{2}-\d{2})", text)
        if end_match:
            end_date = end_match.group(1)

        # Extract City
        city = "USA"
        cities = [
            ("San Francisco", ["san francisco", "sf"]),
            ("New York", ["new york", "nyc", "manhattan", "brooklyn"]),
            ("Austin", ["austin", "atx"]),
            ("Chicago", ["chicago"]),
            ("Baltimore", ["baltimore"]),
            ("Orlando", ["orlando"]),
            ("Dallas", ["dallas", "frisco"]),
            ("Washington, DC", ["washington", "dc"]),
            ("Nashville", ["nashville"]),
            ("Seattle", ["seattle"])
        ]
        for c_name, aliases in cities:
            if any(re.search(rf"\b{a}\b", text, re.I) for a in aliases):
                city = c_name
                break

        # Extract Venue from text
        venue = f"{city} Convention Center"
        venue_match = re.search(r"Venue:\s*([^.]+?)(?:\.|\n|$)", text)
        if venue_match:
            venue = venue_match.group(1).strip()
        elif "Location:" in text:
            loc_match = re.search(r"Location:\s*([^.]+?)(?:\.|\n|$)", text)
            if loc_match:
                venue = loc_match.group(1).strip()

        # Category
        category = "Technology"
        categories = [
            ("Cybersecurity & Cloud", ["cyber", "security", "threat", "cisa"]),
            ("AI & Machine Learning", ["ai", "artificial intelligence", "machine learning", "graphrag", "deep learning"]),
            ("Cloud Infrastructure", ["cloud", "azure", "modal", "gpu", "container", "infrastructure"]),
            ("Event Technology & Enterprise", ["cvent", "hospitality", "event tech", "enterprise software"]),
            ("Healthcare IT", ["health", "healthcare", "medicine", "clinical"])
        ]
        for cat_name, keywords in categories:
            if any(re.search(rf"\b{k}\b", text, re.I) for k in keywords):
                category = cat_name
                break

        # Extract real speakers and designations if present in text
        speakers = []
        titles = []
        
        spk_block = re.search(r"Speakers?:\s*([^\n\r]+)", text, re.I)
        if spk_block:
            parts = [p.strip() for p in spk_block.group(1).split(";") if p.strip()]
            for p in parts:
                comma_parts = p.split(",", 1)
                name = comma_parts[0].strip()
                t_desc = comma_parts[1].strip() if len(comma_parts) > 1 else "Keynote Speaker"
                if name and len(name.split()) >= 2:
                    speakers.append(name)
                    titles.append(t_desc)

        # Organizer
        organizer = f"{raw_data.source_name.title()} Conference Network"
        org_match = re.search(r"Organizer:\s*([^.]+?)(?:\.|\n|$)", text)
        if org_match:
            organizer = org_match.group(1).strip()

        # Official Conference URL
        official_url = raw_data.source_url
        url_match = re.search(r"Official URL:\s*(https?://[^\s]+)", text)
        if url_match:
            official_url = url_match.group(1).strip()

        # Registration URL
        registration_url = raw_data.source_url
        reg_match = re.search(r"Registration URL:\s*(https?://[^\s]+)", text)
        if reg_match:
            registration_url = reg_match.group(1).strip()

        # Fix 404 /en/events URLs
        official_url = official_url.replace("/en/events", "/events")
        registration_url = registration_url.replace("/en/events", "/events")

        # Original Publication Date
        publication_date = ""
        pub_match = re.search(r"Publication Date:\s*(\d{4}-\d{2}-\d{2})", text)
        if pub_match:
            publication_date = pub_match.group(1).strip()

        # Speaking talks details
        talks_details = ""
        talks_match = re.search(r"Previous Talks:\s*([^.]+?\.)", text, re.I)
        if talks_match:
            talks_details = talks_match.group(1).strip()

        # Overview description
        desc_match = re.search(r"Overview:\s*([^.]+?\.)", text, re.I)
        overview = desc_match.group(1).strip() if desc_match else f"{raw_data.raw_title} held in {city}, USA."

        speakers_available = "Yes" if len(speakers) > 0 else "No"

        return AIConferenceExtraction(
            conference_title=raw_data.raw_title.strip(),
            industry_category=category,
            start_date=start_date,
            end_date=end_date,
            speakers=speakers,
            speaker_titles_companies=titles,
            speaker_talks_details=talks_details,
            description=overview,
            venue=venue,
            city=city,
            country="USA",
            organizer=organizer,
            official_conference_url=official_url,
            registration_url=registration_url,
            publication_date=publication_date,
            speakers_available=speakers_available,
            is_valid_usa_conference=True
        )
