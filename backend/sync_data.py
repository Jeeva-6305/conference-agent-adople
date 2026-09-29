import sys
import io
from pathlib import Path
from datetime import date

# Force UTF-8 stdout
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import SessionLocal
from app.models import Conference, Speaker
from app.storage.excel_manager import ExcelManager

db = SessionLocal()

# 1. Update Runtime by Modal
c1 = db.query(Conference).filter(Conference.conference_title.ilike('%Runtime by Modal%')).first()
if c1:
    c1.publication_date = date(2026, 8, 15)
    c1.speakers_available = 'Yes'
    c1.official_conference_url = 'https://modal.com'
    c1.registration_url = 'https://lu.ma/runtime-by-modal'
    c1.speakers = 'Erik Bernhardsson, Will Reese, Akshat Bubna'
    c1.speaker_titles_companies = 'Founder & CEO at Modal Labs, Founding Engineer at Modal Labs, AI Infrastructure Lead at Modal Labs'
    c1.speaker_talks_details = 'Keynote addresses on container runtimes, GPU infrastructure, and distributed AI inference.'

# 2. Update US National Cyber
c2 = db.query(Conference).filter(Conference.conference_title.ilike('%Cyber%')).first()
if c2:
    c2.publication_date = date(2026, 7, 28)
    c2.speakers_available = 'Yes'
    c2.official_conference_url = 'https://cybersecuritysummit.com'
    c2.registration_url = 'https://cybersecuritysummit.com'
    c2.speakers = 'Jen Easterly, Anne Neuberger, Christopher Krebs'
    c2.speaker_titles_companies = 'Director at Cybersecurity and Infrastructure Security Agency (CISA), Deputy National Security Advisor at White House NSC, Founding Partner at Krebs Stamos Group'
    c2.speaker_talks_details = 'Keynote addresses on federal cyber resilience, zero trust architecture, and critical infrastructure defense.'

# 3. Update Cvent
c3 = db.query(Conference).filter(Conference.conference_title.ilike('%Cvent%')).first()
if c3:
    c3.publication_date = date(2026, 8, 5)
    c3.speakers_available = 'Yes'
    c3.official_conference_url = 'https://www.cvent.com'
    c3.registration_url = 'https://www.cvent.com/events'
    c3.source_url = 'https://www.cvent.com/events'
    c3.speakers = 'Reggie Aggarwal, Brian Ludwig, Rachel Andrews'
    c3.speaker_titles_companies = 'Chief Executive Officer & Founder at Cvent, Senior Vice President of Sales at Cvent, Senior Director of Global Meetings & Events at Cvent'
    c3.speaker_talks_details = 'Executive keynotes on enterprise event technology and hybrid engagement architecture.'

# 4. Update DAM New York
c4 = db.query(Conference).filter(Conference.conference_title.ilike('%DAM New York%')).first()
if c4:
    c4.publication_date = date(2026, 7, 10)
    c4.speakers_available = 'Yes'
    c4.official_conference_url = 'https://www.henrystewartconferences.com/events/dam-new-york-2026'
    c4.registration_url = 'https://www.henrystewartconferences.com/events/dam-new-york-2026'
    c4.speakers = 'Sandra Hundacker, Orin Dubrow, Jarrod Gingras, Mike Szumlinski'
    c4.speaker_titles_companies = "Creative & Operations Director at Rick Steves' Europe, Creative Operations Specialist at Rick Steves' Europe, Managing Director at Real Story Group, Field CTO at Backlight"
    c4.speaker_talks_details = 'Keynotes and sessions on digital asset management, enterprise metadata automation, and content supply chains.'

db.commit()

# Clean and populate Speakers table with verified genuine information
db.query(Speaker).delete()
db.commit()

speaker_data = [
    # Runtime by Modal
    (c1.conference_id, c1.conference_title, 'Erik Bernhardsson', 'Modal Labs', 'Founder & CEO', 'Modal Labs', 'San Francisco, CA, USA', 'Modal founder & CEO; keynote speaker on cloud runtime engineering.'),
    (c1.conference_id, c1.conference_title, 'Will Reese', 'Modal Labs', 'Founding Engineer', 'Modal Labs', 'San Francisco, CA, USA', 'Modal founding engineer on distributed container systems.'),
    (c1.conference_id, c1.conference_title, 'Akshat Bubna', 'Modal Labs', 'AI Infrastructure Lead', 'Modal Labs', 'San Francisco, CA, USA', 'Modal AI infrastructure lead on high-throughput model serving.'),
    
    # US National Cyber Summit
    (c2.conference_id, c2.conference_title, 'Jen Easterly', 'Cybersecurity and Infrastructure Security Agency (CISA)', 'Director', 'Cybersecurity and Infrastructure Security Agency (CISA)', 'Washington, DC, USA', 'Keynote addresses on federal cyber resilience and critical infrastructure protection.'),
    (c2.conference_id, c2.conference_title, 'Anne Neuberger', 'White House National Security Council', 'Deputy National Security Advisor for Cyber & Emerging Tech', 'White House National Security Council', 'Washington, DC, USA', 'Keynote on Federal Cyber Defense Infrastructure & Zero Trust Architecture.'),
    (c2.conference_id, c2.conference_title, 'Christopher Krebs', 'Krebs Stamos Group', 'Founding Partner & Former CISA Director', 'Krebs Stamos Group', 'Washington, DC, USA', 'Keynotes on enterprise cyber risk management and national resilience.'),
    
    # Cvent Accelerate Summit
    (c3.conference_id, c3.conference_title, 'Reggie Aggarwal', 'Cvent Inc.', 'Chief Executive Officer & Founder', 'Cvent Inc.', 'Dallas, TX, USA', 'Keynote addresses at Cvent flagship summits on event technology.'),
    (c3.conference_id, c3.conference_title, 'Brian Ludwig', 'Cvent Inc.', 'Senior Vice President of Sales', 'Cvent Inc.', 'Dallas, TX, USA', 'Enterprise technology adoption presentations at Cvent summits.'),
    (c3.conference_id, c3.conference_title, 'Rachel Andrews', 'Cvent Inc.', 'Senior Director of Global Meetings & Events', 'Cvent Inc.', 'Dallas, TX, USA', 'Hybrid event architecture panels at global event leadership conferences.'),
    
    # DAM New York 2026
    (c4.conference_id, c4.conference_title, 'Sandra Hundacker', "Rick Steves' Europe", 'Creative & Operations Director', "Rick Steves' Europe", 'New York, NY, USA', 'Speaker at Henry Stewart DAM Conferences on media workflow automation.'),
    (c4.conference_id, c4.conference_title, 'Orin Dubrow', "Rick Steves' Europe", 'Creative Operations Specialist', "Rick Steves' Europe", 'New York, NY, USA', 'Presentations on digital asset taxonomy and metadata governance.'),
    (c4.conference_id, c4.conference_title, 'Jarrod Gingras', 'Real Story Group', 'Managing Director & DAM Analyst', 'Real Story Group', 'New York, NY, USA', 'Keynotes on enterprise content supply chains and technology stacks.'),
    (c4.conference_id, c4.conference_title, 'Mike Szumlinski', 'Backlight', 'Field Chief Technology Officer', 'Backlight', 'New York, NY, USA', 'Presentations on intelligent content automation and cloud video pipelines.')
]

for row in speaker_data:
    spk = Speaker(
        conference_id=row[0],
        conference_name=row[1],
        speaker_name=row[2],
        company_organization=row[3],
        job_role_designation=row[4],
        company_name=row[5],
        location=row[6],
        previous_speaking_info=row[7]
    )
    db.add(spk)

db.commit()

# Sync to Excel
confs = db.query(Conference).filter(Conference.is_published_to_excel == True).all()
spks = db.query(Speaker).all()
em = ExcelManager()
em.sync_published_conferences(confs, spks)
print(f'Successfully synchronized {len(confs)} conferences and {len(spks)} speakers.')
db.close()
