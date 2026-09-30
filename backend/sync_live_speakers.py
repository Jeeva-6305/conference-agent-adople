import sys
import io
from pathlib import Path

# Force UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import SessionLocal
from app.models import Conference, Speaker
from app.storage.excel_manager import ExcelManager
from app.scrapers.live_speaker_scraper import LiveWebScraper

whova_url = 'https://whova.com/embedded/speakers/moHHtsILJDkAoZkDQbVKyZqiSRnMXDKopQ8Tl8K54FI%3D/?view=preview'

print(f"[*] Starting genuine live scraping of real speakers from {whova_url}...")
real_speakers = LiveWebScraper.scrape_speakers_from_url(whova_url)
print(f"[OK] Scraped {len(real_speakers)} real speakers!")

db = SessionLocal()
conf = db.query(Conference).filter(Conference.conference_title.ilike('%corncon%')).first()

if conf:
    # Delete old hardcoded/placeholder speakers for CornCon
    deleted = db.query(Speaker).filter(Speaker.conference_id == conf.conference_id).delete()
    print(f"[*] Removed {deleted} previous entries.")

    # Insert genuine live-scraped speakers
    added = 0
    for s in real_speakers:
        spk = Speaker(
            conference_id=conf.conference_id,
            conference_name=conf.conference_title,
            speaker_name=s['speaker_name'],
            company_organization=s.get('company_organization', s['company_name']),
            job_role_designation=s['job_role_designation'],
            company_name=s['company_name'],
            official_company_website_url=s.get('official_company_website_url', ''),
            linkedin_url=s.get('linkedin_url', ''),
            location=f"{conf.city}, {conf.country}",
            previous_speaking_info=f"Speaker at {conf.conference_title}"
        )
        db.add(spk)
        added += 1

    conf.speakers_available = "Yes" if added > 0 else "No"
    db.commit()
    print(f"[OK] Added {added} real, live-scraped speakers to Database!")

    # Sync Excel Workbook with real speakers
    all_published = db.query(Conference).filter(Conference.is_published_to_excel == True).all()
    pub_ids = [c.conference_id for c in all_published]
    all_spks = db.query(Speaker).filter(Speaker.conference_id.in_(pub_ids)).all()

    em = ExcelManager()
    em.sync_published_conferences(all_published, all_spks)
    print(f"[SUCCESS] Excel workbook synced with {len(all_published)} conferences and {len(all_spks)} real speakers!")

db.close()
