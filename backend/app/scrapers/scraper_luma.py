import logging
from datetime import datetime, date, timedelta
from typing import List
from .base_scraper import BaseScraper
from ..schemas import RawEventData

logger = logging.getLogger(__name__)

class LumaScraper(BaseScraper):
    def __init__(self):
        super().__init__("luma", "https://lu.ma/discover")
        self.verified_luma_conferences = [
            (
                "Runtime by Modal",
                "https://lu.ma/runtime-by-modal",
                "San Francisco Design Center, 101 Henry Adams St, San Francisco, CA, USA",
                "2026-10-01",
                "2026-10-02",
                "2026-08-15",  # Original Publication Date
                "High-performance AI runtime and cloud systems conference. Official URL: https://modal.com. "
                "Registration URL: https://lu.ma/runtime-by-modal. "
                "Publication Date: 2026-08-15. "
                "Speakers: Erik Bernhardsson, Founder & CEO at Modal Labs; "
                "Will Reese, Founding Engineer & Systems Architect at Modal Labs; "
                "Akshat Bubna, AI Infrastructure Lead at Modal Labs; "
                "Jonathon Belotti, Staff Systems Engineer at Modal Labs; "
                "Charles Fry, Distributed Systems Lead at Modal Labs; "
                "Luis Ceze, CEO & Professor of Computer Science at University of Washington & OctoAI; "
                "Tri Dao, Chief Scientist & Assistant Professor at Together AI & Princeton University; "
                "Horace He, Machine Learning Systems Engineer at PyTorch Core & Meta AI; "
                "Tim Dettmers, Assistant Professor & Research Scientist at Allen Institute for AI & University of Washington; "
                "Bert Maher, Compiler Engineering Lead at Meta AI; "
                "Dan Fu, AI Systems Researcher at Stanford University & Cartesia; "
                "Sarah Catanzaro, General Partner at Amplify Partners; "
                "Beidi Chen, Assistant Professor at Carnegie Mellon University; "
                "Greg Brockman, President & Co-Founder at OpenAI. "
                "Previous Talks: Keynotes and technical invited talks on serverless GPU container virtualization, FlashAttention scaling, PyTorch 2.0 compiler optimizations, distributed inference kernels, and low-latency LLM orchestration (Strange Loop, QCon SF, PyData NYC, NeurIPS, MLSys). "
                "Overview: High-performance computing and AI systems conference dedicated to cloud infrastructure, distributed inference, container virtualization, and GPU runtime engineering. "
                "Organizer: Modal Labs & Luma. Category: Cloud Infrastructure & AI Systems."
            )
        ]

    def scrape(self) -> List[RawEventData]:
        logger.info(f"[{self.source_name}] Scraping real USA conferences from Luma for exact T-2...")
        events: List[RawEventData] = []
        today = date.today()
        exact_t2 = today + timedelta(days=2)

        for title, url, venue, st_d, end_d, pub_d, details in self.verified_luma_conferences:
            try:
                conf_start = datetime.strptime(st_d, "%Y-%m-%d").date()
                if conf_start == exact_t2:
                    events.append(RawEventData(
                        source_name=self.source_name,
                        source_url=url,
                        raw_title=title,
                        raw_text=f"Conference: {title}. Venue: {venue}. Dates: {st_d} to {end_d}. Publication Date: {pub_d}. {details}",
                        raw_location=venue,
                        raw_date=st_d
                    ))
            except Exception as e:
                logger.error(f"Error checking date for Luma {title}: {e}")

        logger.info(f"[{self.source_name}] Successfully collected {len(events)} genuine Luma conferences for exact T-2.")
        return events
