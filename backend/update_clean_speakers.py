import sys
import io
from pathlib import Path

# Force UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import SessionLocal
from app.models import Conference, Speaker
from app.storage.excel_manager import ExcelManager
from app.ai.extractor import clean_and_resolve_speaker

def sanitize_and_sync_all_speakers():
    db = SessionLocal()
    speakers = db.query(Speaker).all()
    print(f"[*] Processing and cleaning {len(speakers)} speakers in PostgreSQL...")

    updated_count = 0
    for s in speakers:
        c_name, c_role, c_comp, c_url, c_li = clean_and_resolve_speaker(
            s.speaker_name, s.job_role_designation, s.company_name, location=s.location
        )
        
        has_changed = (
            s.speaker_name != c_name or
            s.job_role_designation != c_role or
            s.company_name != c_comp or
            s.official_company_website_url != c_url or
            s.linkedin_url != c_li
        )

        if has_changed:
            s.speaker_name = c_name
            s.job_role_designation = c_role
            s.company_name = c_comp
            s.company_organization = c_comp
            s.official_company_website_url = c_url
            s.linkedin_url = c_li
            updated_count += 1

    db.commit()
    print(f"[OK] Successfully updated {updated_count} speaker records in PostgreSQL database!")

    # Synchronize published conferences and speakers to Excel
    all_published = db.query(Conference).filter(Conference.is_published_to_excel == True).all()
    pub_ids = [c.conference_id for c in all_published]
    all_spks = db.query(Speaker).filter(Speaker.conference_id.in_(pub_ids)).all()

    em = ExcelManager()
    em.sync_published_conferences(all_published, all_spks)
    print(f"[SUCCESS] Excel workbook synced with {len(all_published)} conferences and {len(all_spks)} clean speakers!")

    db.close()

if __name__ == '__main__':
    sanitize_and_sync_all_speakers()
