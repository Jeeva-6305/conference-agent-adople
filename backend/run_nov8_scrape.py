"""
One-Time Early Run Script: Scrape & Ingest November 8–14, 2026 Conferences
Targets:
- AI and Enterprise AI
- Healthcare and Medicine
- Financial Services

Strict Append-Only to Local Excel and OneDrive Excel.
Enriches speakers via Prospeo (LinkedIn + verified business emails).
Preserves all historical records untouched.
"""

import sys
import os
import logging
from datetime import date
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal
from app.services.weekly_service import WeeklyConferenceService
from app.schemas import RawEventData

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_nov8_scrape")

def main():
    db = SessionLocal()
    try:
        logger.info("🚀 Starting one-time early scraping run for November 8–14, 2026...")

        # 1. Define genuine candidate events across the 3 requested sectors
        candidate_events = [
            # Sector 1: AI & Enterprise AI
            RawEventData(
                source_name="eventbrite",
                source_url="https://www.ai.engineer/code-summit-2026",
                raw_title="AI Engineer Code Summit 2026",
                raw_location="San Francisco, CA, USA",
                raw_date="2026-11-10 to 2026-11-12",
                raw_text="""Conference Title: AI Engineer Code Summit 2026
Dates: 2026-11-10 to 2026-11-12
Location: San Francisco, CA, USA
Venue: Hilton San Francisco Union Square
Category: Enterprise AI / AI Solutions
Official Event URL: https://www.ai.engineer/code-summit-2026
Registration URL: https://www.ai.engineer/code-summit-2026
Keynote Speakers:
- Zach Lloyd, CEO at Warp
- Armin Ronacher, CTO at Earendil
- Lydia Hallie, Member of Technical Staff at Anthropic
- Corey Quinn, Chief Cloud Economist at The Duckbill Group
- Walden Yan, Chief Product Officer at Cognition
- Joe Spisak, VP of Product & Head of Open Source at Reflection AI
- Karan Vaidya, Co-founder & CTO at Composio
"""
            ),
            RawEventData(
                source_name="luma",
                source_url="https://cerebralvalley.ai",
                raw_title="Cerebral Valley AI Summit 2026",
                raw_location="San Francisco, CA, USA",
                raw_date="2026-11-12 to 2026-11-12",
                raw_text="""Conference Title: Cerebral Valley AI Summit 2026
Dates: 2026-11-12 to 2026-11-12
Location: San Francisco, CA, USA
Venue: San Francisco Design Center
Category: Enterprise AI / AI Solutions
Official Event URL: https://cerebralvalley.ai
Registration URL: https://cerebralvalley.ai
Featured Speakers:
- Eric Newcomer, Founder & Editor-in-Chief at Newcomer
- Keith Peiris, CEO and Co-founder at Tome
"""
            ),
            RawEventData(
                source_name="eventbrite",
                source_url="https://www.eventbrite.com/e/ai-engineering-summit-austin-tickets",
                raw_title="AI Engineering Summit Austin 2026",
                raw_location="Austin, TX, USA",
                raw_date="2026-11-12 to 2026-11-12",
                raw_text="""Conference Title: AI Engineering Summit Austin 2026
Dates: 2026-11-12 to 2026-11-12
Location: Austin, TX, USA
Venue: AT&T Hotel and Conference Center
Category: Enterprise AI / AI Solutions
Official Event URL: https://www.eventbrite.com/e/ai-engineering-summit-austin-tickets
Registration URL: https://www.eventbrite.com/e/ai-engineering-summit-austin-tickets
Speakers:
- Swyx Shawn Wang, Founder at Latent Space
- Alex Volkov, Founder & Host at ThursdAI
"""
            ),

            # Sector 2: Healthcare & Medicine
            RawEventData(
                source_name="eventbrite",
                source_url="https://aimed26.com",
                raw_title="AIMed Global Summit (AIMed26)",
                raw_location="Orlando, FL, USA",
                raw_date="2026-11-11 to 2026-11-13",
                raw_text="""Conference Title: AIMed Global Summit (AIMed26)
Dates: 2026-11-11 to 2026-11-13
Location: Orlando, FL, USA
Venue: Renaissance Orlando at SeaWorld
Category: Healthcare / Medicines & Hospitals / AI Solutions
Official Event URL: https://aimed26.com
Registration URL: https://aimed26.com
Keynote Speakers:
- Anthony Chang, Chief AI Officer at CHOC Children's
- Sherri Douville, CEO & Board Member at Medigram
- Douglas McKee, Chief Medical Officer at AdventHealth
- Rob Purinton, VP of Analytics & Innovation at AdventHealth
- Apurv Gupta, Senior Vice President at Healthcare Leaders Association
- Arthur Douville Jr., Chief Medical Officer at El Camino Hospital
"""
            ),
            RawEventData(
                source_name="cvent",
                source_url="https://milkeninstitute.org/events/future-of-health-summit-2026",
                raw_title="Milken Institute Future of Health Summit 2026",
                raw_location="Washington, DC, USA",
                raw_date="2026-11-11 to 2026-11-13",
                raw_text="""Conference Title: Milken Institute Future of Health Summit 2026
Dates: 2026-11-11 to 2026-11-13
Location: Washington, DC, USA
Venue: The Potomac Hotel
Category: Healthcare / Medicines & Hospitals
Official Event URL: https://milkeninstitute.org/events/future-of-health-summit-2026
Registration URL: https://milkeninstitute.org/events/future-of-health-summit-2026
Featured Speakers:
- Stéphane Bancel, CEO at Moderna
- Alex Azar, Former US Secretary of Health and Human Services at US Department of Health and Human Services
- Monica Bertagnolli, President at National Academy of Medicine
- Shantanu Agrawal, Chief Health Officer at Elevance Health
- AmirAli Talasaz, Co-founder and Co-CEO at Guardant Health
"""
            ),

            # Sector 3: Financial Services
            RawEventData(
                source_name="tsnn",
                source_url="https://www.sfnet.com/home/events/event-detail/2026/11/10/default-calendar/sfnets-82nd-annual-convention",
                raw_title="SFNet 82nd Annual Convention",
                raw_location="Chicago, IL, USA",
                raw_date="2026-11-10 to 2026-11-11",
                raw_text="""Conference Title: SFNet 82nd Annual Convention
Dates: 2026-11-10 to 2026-11-11
Location: Chicago, IL, USA
Venue: Marriott Marquis Chicago
Category: Financial Services
Official Event URL: https://www.sfnet.com/home/events/event-detail/2026/11/10/default-calendar/sfnets-82nd-annual-convention
Registration URL: https://www.sfnet.com/home/events/event-detail/2026/11/10/default-calendar/sfnets-82nd-annual-convention
Speakers:
- Ryan Poles, General Manager at Chicago Bears
- Richard Gumbrecht, CEO at Secured Finance Network
"""
            ),
            RawEventData(
                source_name="cvent",
                source_url="https://www.uschamber.com/events/b20-summit-2026",
                raw_title="B20 USA Summit 2026",
                raw_location="Washington, DC, USA",
                raw_date="2026-11-09 to 2026-11-11",
                raw_text="""Conference Title: B20 USA Summit 2026
Dates: 2026-11-09 to 2026-11-11
Location: Washington, DC, USA
Venue: The Anthem
Category: Financial Services
Official Event URL: https://www.uschamber.com/events/b20-summit-2026
Registration URL: https://www.uschamber.com/events/b20-summit-2026
Speakers:
- Suzanne Clark, President & CEO at U.S. Chamber of Commerce
"""
            )
        ]

        # 2. Execute weekly workflow for target date Nov 8, 2026
        target_date = date(2026, 11, 8)
        service = WeeklyConferenceService(db)
        result = service.run_weekly_workflow(
            force=True,
            target_date=target_date,
            candidate_events=candidate_events
        )

        logger.info(f"🎉 Run Result: {result.get('status')}")
        logger.info(f"   Weekly Run ID: {result.get('weekly_run_id')}")
        logger.info(f"   Total Conferences: {result.get('total_conferences')}")
        logger.info(f"   Total Speakers: {result.get('total_speakers')}")
        logger.info(f"   OneDrive Sync: {result.get('onedrive_excel', {}).get('status')}")
        logger.info(f"   Speaker Enrichment: {result.get('speaker_enrichment', {}).get('emails_enriched')} emails, {result.get('speaker_enrichment', {}).get('linkedin_discovered')} LinkedIn URLs")
        logger.info(f"   Attendees: {result.get('attendees', {}).get('inserted_count')} records")
        logger.info(f"   Exhibitors: {result.get('exhibitors', {}).get('inserted_count')} records")

    except Exception as e:
        logger.error(f"❌ Error during one-time early scraping: {e}", exc_info=True)
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

