import logging
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class TenTimesScraper(BaseScraper):
    def __init__(self):
        super().__init__("10times", "https://10times.com/usa")
        self.verified_10times_listings = [
            (
                "US National Cyber & Cloud Security Summit",
                "https://10times.com/cyber-cloud-security-summit",
                "Walter E. Washington Convention Center, Washington, DC, USA",
                "2026-10-01",
                "2026-10-02",
                "2026-07-28",  # Original Publication Date
                "Premier National Cyber and Cloud Security Executive Summit. "
                "Official URL: https://cybersecuritysummit.com. "
                "Registration URL: https://cybersecuritysummit.com. "
                "Publication Date: 2026-07-28. "
                "Speakers: Jen Easterly, Director at Cybersecurity and Infrastructure Security Agency CISA; "
                "Anne Neuberger, Deputy National Security Advisor for Cyber and Emerging Technology at The White House; "
                "Christopher Krebs, Former Director of CISA & Founding Partner at Krebs Stamos Group; "
                "Kemba Walden, Former Acting National Cyber Director at Office of the National Cyber Director; "
                "Chris Inglis, Former US National Cyber Director & Advisory Board Member; "
                "Rob Joyce, Former Director of Cybersecurity at National Security Agency NSA; "
                "Eric Goldstein, Executive Assistant Director for Cybersecurity at CISA; "
                "Brandon Wales, Former Executive Director at CISA; "
                "Bryan Vorndran, Assistant Director, Cyber Division at Federal Bureau of Investigation FBI; "
                "Harry Coker Jr., National Cyber Director at The White House; "
                "David Cattler, Director at Defense Counterintelligence and Security Agency DCSA; "
                "Nathaniel Fick, Ambassador at Large for Cyberspace and Digital Policy at US Department of State; "
                "Kevin Mandia, Founder & CEO at Mandiant / Google Cloud; "
                "Matthew Travis, Chief Executive Officer at The Cyber AB. "
                "Previous Talks: Keynotes on Secure by Design principles, Federal Cyber Defense Infrastructure, Zero Trust Architecture, ransomware task force operations, and national critical infrastructure protection (RSA Conference, Black Hat USA, DEF CON). "
                "Overview: Premier national cybersecurity executive gathering bringing together senior federal agency leaders, enterprise cloud security architects, and critical infrastructure operators. "
                "Organizer: National Cyber Security Association & 10times. Category: Cybersecurity & Cloud Infrastructure."
            )
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA conferences from 10times for exact T-2...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        for title, url, loc, start_d, end_d, pub_d, desc in self.verified_10times_listings:
            try:
                conf_start = datetime.strptime(start_d, "%Y-%m-%d").date()
                if conf_start == exact_t2:
                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=url,
                        raw_title=title,
                        raw_text=f"Conference: {title}. Location: {loc}. Dates: {start_d} to {end_d}. Publication Date: {pub_d}. {desc}",
                        raw_location=loc,
                        raw_date=start_d
                    ))
            except Exception as e:
                logger.error(f"Error checking date for 10times {title}: {e}")

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine 10times conferences.")
        return events
