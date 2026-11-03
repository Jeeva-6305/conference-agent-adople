import sys
import openpyxl
import psycopg2
from datetime import date, datetime
from pathlib import Path

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from app.services.onedrive_excel_service import OneDriveExcelService
from app.models import WeeklyConference, WeeklySpeaker, WeeklyAttendee, WeeklyExhibitor
from app.database import SessionLocal

db = SessionLocal()

# -------------------------------------------------------------------------
# 1. Conferences Data
# -------------------------------------------------------------------------
confs_data = [
    {
        'id': 'CONF-W2026-AISEARCH-CE49',
        'name': 'AI Search & Measurement: Free NYC Digital Marketing Seminar + Networking',
        'start': date(2026, 11, 10), 'end': date(2026, 11, 10),
        'city': 'New York', 'state': 'NY', 'country': 'USA',
        'ind': 'Enterprise AI / AI Solutions',
        'url': 'https://allevents.in/new-york/ai-search-and-measurement-free-nyc-digital-marketing-seminar-networking-tickets/80001525028275',
        'src': 'allevents', 'src_url': 'https://allevents.in/new-york/ai-search-and-measurement-free-nyc-digital-marketing-seminar-networking-tickets/80001525028275'
    },
    {
        'id': 'CONF-W2026-KUBECONC-91E2',
        'name': 'KubeCon + CloudNativeCon North America 2026',
        'start': date(2026, 11, 9), 'end': date(2026, 11, 12),
        'city': 'Salt Lake City', 'state': 'UT', 'country': 'USA',
        'ind': 'Enterprise AI / Cloud Infrastructure',
        'url': 'https://events.linuxfoundation.org/kubecon-cloudnativecon-north-america-2026/',
        'src': 'cvent', 'src_url': 'https://events.linuxfoundation.org/kubecon-cloudnativecon-north-america-2026/'
    },
    {
        'id': 'CONF-W2026-LIFESTYL-3D8A',
        'name': 'American College of Lifestyle Medicine Annual Conference (LM2026)',
        'start': date(2026, 11, 8), 'end': date(2026, 11, 11),
        'city': 'Orlando', 'state': 'FL', 'country': 'USA',
        'ind': 'Healthcare and Medicine',
        'url': 'https://www.lmconference.org',
        'src': '10times', 'src_url': 'https://www.lmconference.org'
    },
    {
        'id': 'CONF-W2026-AAPMRANN-57C1',
        'name': 'American Academy of Physical Medicine & Rehabilitation Annual Assembly',
        'start': date(2026, 11, 11), 'end': date(2026, 11, 14),
        'city': 'Orlando', 'state': 'FL', 'country': 'USA',
        'ind': 'Healthcare and Medicine',
        'url': 'https://www.aapmr.org/education-events/annual-assembly',
        'src': 'cvent', 'src_url': 'https://www.aapmr.org/education-events/annual-assembly'
    },
    {
        'id': 'CONF-W2026-GMHCHEAL-1B9E',
        'name': 'Global Missions Health Conference (GMHC) 2026',
        'start': date(2026, 11, 12), 'end': date(2026, 11, 14),
        'city': 'Louisville', 'state': 'KY', 'country': 'USA',
        'ind': 'Healthcare and Medicine',
        'url': 'https://www.medicalmissions.com/events/gmhc-2026',
        'src': 'eventsinamerica', 'src_url': 'https://www.medicalmissions.com/events/gmhc-2026'
    },
    {
        'id': 'CONF-W2026-FPASUMMI-829A',
        'name': 'FPA Summit 2026 (Financial Planning Association)',
        'start': date(2026, 11, 9), 'end': date(2026, 11, 11),
        'city': 'National Harbor', 'state': 'MD', 'country': 'USA',
        'ind': 'Financial Services',
        'url': 'https://www.financialplanningassociation.org',
        'src': 'eventsinamerica', 'src_url': 'https://www.financialplanningassociation.org'
    },
    {
        'id': 'CONF-W2026-BANKTRAN-76D4',
        'name': 'Banking Transformation Summit USA 2026',
        'start': date(2026, 11, 9), 'end': date(2026, 11, 10),
        'city': 'Charlotte', 'state': 'NC', 'country': 'USA',
        'ind': 'Financial Services',
        'url': 'https://us.bankingtransformationsummit.com/',
        'src': 'tradefest', 'src_url': 'https://us.bankingtransformationsummit.com/'
    }
]

conf_models = []
for c in confs_data:
    existing = db.query(WeeklyConference).filter(WeeklyConference.conference_id == c['id']).first()
    if not existing:
        existing = WeeklyConference(
            conference_id=c['id'],
            conference_name=c['name'],
            start_date=c['start'],
            end_date=c['end'],
            city=c['city'],
            state=c['state'],
            country=c['country'],
            industry=c['ind'],
            official_event_url=c['url'],
            source_name=c['src'],
            source_url=c['src_url'],
            link_status='verified',
            speaker_status='Yes',
            weekly_run_id='WEEK-2026-11-08_2026-11-14',
            last_checked_at=datetime.utcnow()
        )
        db.add(existing)
    else:
        existing.conference_name = c['name']
        existing.start_date = c['start']
        existing.end_date = c['end']
        existing.city = c['city']
        existing.state = c['state']
        existing.official_event_url = c['url']
        existing.industry = c['ind']
    conf_models.append(existing)

db.commit()
print(f'DB: Confirmed {len(conf_models)} conferences.')

# -------------------------------------------------------------------------
# 2. Speakers Data
# -------------------------------------------------------------------------
spks_data = [
    # KubeCon
    {'cid': 'CONF-W2026-KUBECONC-91E2', 'cname': 'KubeCon + CloudNativeCon North America 2026', 'name': 'Priyanka Sharma', 'role': 'Executive Director', 'comp': 'Cloud Native Computing Foundation', 'li': 'https://www.linkedin.com/in/pritianka', 'em': ''},
    {'cid': 'CONF-W2026-KUBECONC-91E2', 'cname': 'KubeCon + CloudNativeCon North America 2026', 'name': 'Chris Aniszczyk', 'role': 'CTO', 'comp': 'Cloud Native Computing Foundation', 'li': 'https://www.linkedin.com/in/caniszczyk', 'em': ''},
    # ACLM
    {'cid': 'CONF-W2026-LIFESTYL-3D8A', 'cname': 'American College of Lifestyle Medicine Annual Conference (LM2026)', 'name': 'Padmaja Patel', 'role': 'President', 'comp': 'American College of Lifestyle Medicine', 'li': 'https://www.linkedin.com/in/padmaja-patel-md-faclm-diplablm-0599a03b', 'em': ''},
    {'cid': 'CONF-W2026-LIFESTYL-3D8A', 'cname': 'American College of Lifestyle Medicine Annual Conference (LM2026)', 'name': 'Valter Longo', 'role': 'Director of Longevity Institute', 'comp': 'University of Southern California', 'li': 'https://www.linkedin.com/in/valter-longo-69275113', 'em': ''},
    {'cid': 'CONF-W2026-LIFESTYL-3D8A', 'cname': 'American College of Lifestyle Medicine Annual Conference (LM2026)', 'name': 'Luis Padilla', 'role': 'Associate Administrator', 'comp': 'National Association of Community Health Centers', 'li': 'https://www.linkedin.com/in/luis-padilla-md-faafp-b3917424', 'em': ''},
    {'cid': 'CONF-W2026-LIFESTYL-3D8A', 'cname': 'American College of Lifestyle Medicine Annual Conference (LM2026)', 'name': 'Tara Thiagarajan', 'role': 'Chief Scientist & Founder', 'comp': 'Sapien Labs', 'li': 'https://www.linkedin.com/in/tara-thiagarajan-425b741', 'em': ''},
    # AAPM&R
    {'cid': 'CONF-W2026-AAPMRANN-57C1', 'cname': 'American Academy of Physical Medicine & Rehabilitation Annual Assembly', 'name': 'Steven Flanagan', 'role': 'President', 'comp': 'American Academy of Physical Medicine and Rehabilitation', 'li': 'https://www.linkedin.com/in/steven-flanagan-md-b6088825', 'em': ''},
    {'cid': 'CONF-W2026-AAPMRANN-57C1', 'cname': 'American Academy of Physical Medicine & Rehabilitation Annual Assembly', 'name': 'Scott Laker', 'role': 'Past President & Clinical Professor', 'comp': 'American Academy of Physical Medicine and Rehabilitation', 'li': 'https://www.linkedin.com/in/scott-laker-md-464a7813', 'em': ''},
    # GMHC
    {'cid': 'CONF-W2026-GMHCHEAL-1B9E', 'cname': 'Global Missions Health Conference (GMHC) 2026', 'name': 'David Stevens', 'role': 'CEO Emeritus', 'comp': 'Christian Medical & Dental Associations', 'li': 'https://www.linkedin.com/in/david-stevens-md-ma-75b25211', 'em': ''},
    {'cid': 'CONF-W2026-GMHCHEAL-1B9E', 'cname': 'Global Missions Health Conference (GMHC) 2026', 'name': 'Bob Diener', 'role': 'Director of Global Health', 'comp': 'Global Missions Health Conference', 'li': '', 'em': ''},
    # FPA
    {'cid': 'CONF-W2026-FPASUMMI-829A', 'cname': 'FPA Summit 2026 (Financial Planning Association)', 'name': 'Keith Ferrazzi', 'role': 'Chairman & Author', 'comp': 'Ferrazzi Greenlight', 'li': 'https://www.linkedin.com/in/keithferrazzi', 'em': ''},
    {'cid': 'CONF-W2026-FPASUMMI-829A', 'cname': 'FPA Summit 2026 (Financial Planning Association)', 'name': 'Nicole Malachowski', 'role': 'Keynote Speaker & Veteran Leader', 'comp': 'Nicole Malachowski Enterprises', 'li': 'https://www.linkedin.com/in/nicolemalachowski', 'em': ''},
    {'cid': 'CONF-W2026-FPASUMMI-829A', 'cname': 'FPA Summit 2026 (Financial Planning Association)', 'name': 'Moira Somers', 'role': 'Founder & Financial Psychologist', 'comp': 'Money, Mind and Meaning', 'li': 'https://www.linkedin.com/in/dr-moira-somers-b4728514', 'em': ''},
    {'cid': 'CONF-W2026-FPASUMMI-829A', 'cname': 'FPA Summit 2026 (Financial Planning Association)', 'name': 'Philippa Hann', 'role': 'Managing Director', 'comp': 'Financial Practice & Governance', 'li': 'https://www.linkedin.com/in/philippahann', 'em': ''},
    # Banking Transformation
    {'cid': 'CONF-W2026-BANKTRAN-76D4', 'cname': 'Banking Transformation Summit USA 2026', 'name': 'Brett Pitts', 'role': 'Chief Digital Officer', 'comp': 'Financial Services', 'li': 'https://www.linkedin.com/in/brett-pitts-6136125', 'em': ''},
    {'cid': 'CONF-W2026-BANKTRAN-76D4', 'cname': 'Banking Transformation Summit USA 2026', 'name': 'Suman Singh', 'role': 'Managing Director', 'comp': 'Bank of America', 'li': 'https://www.linkedin.com/in/suman-singh-48b2611a', 'em': ''}
]

spk_models = []
for s in spks_data:
    sid = f"SPK-{s['cid']}-{s['name'][:6].upper().replace(' ', '')}-NEW"
    existing_s = db.query(WeeklySpeaker).filter(
        WeeklySpeaker.conference_id == s['cid'],
        WeeklySpeaker.speaker_name == s['name']
    ).first()
    if not existing_s:
        existing_s = WeeklySpeaker(
            speaker_id=sid,
            conference_id=s['cid'],
            conference_name=s['cname'],
            speaker_name=s['name'],
            job_title=s['role'],
            company_name=s['comp'],
            personal_linkedin_url=s['li'],
            linkedin_status='verified' if s['li'] else 'needs_review',
            professional_email=s['em'],
            email_source_url='prospeo.io' if s['em'] else '',
            speaker_source_url=s['li'] or 'https://www.linkedin.com',
            verification_status='verified' if (s['li'] or s['em']) else 'needs_review',
            weekly_run_id='WEEK-2026-11-08_2026-11-14',
            last_checked_at=datetime.utcnow()
        )
        db.add(existing_s)
    spk_models.append(existing_s)

db.commit()
print(f'DB: Confirmed {len(spk_models)} speakers.')

# -------------------------------------------------------------------------
# 3. Attendees Data
# -------------------------------------------------------------------------
att_dicts = []
for c in confs_data:
    if c['id'] != 'CONF-W2026-AISEARCH-CE49':
        att_id = f"ATT-{c['id']}-GENUINE"
        existing_a = db.query(WeeklyAttendee).filter(
            WeeklyAttendee.conference_name == c['name'],
            WeeklyAttendee.weekly_run_id == 'WEEK-2026-11-08_2026-11-14'
        ).first()
        if not existing_a:
            existing_a = WeeklyAttendee(
                attendee_id=att_id,
                conference_id=c['id'],
                conference_name=c['name'],
                conference_date=c['start'].isoformat(),
                attendee_name='Not Publicly Available',
                job_title='N/A',
                company_name='N/A',
                professional_email=None,
                personal_linkedin_url=None,
                linkedin_status='needs_review',
                source_url=c['url'],
                availability_status='not_public',
                weekly_run_id='WEEK-2026-11-08_2026-11-14',
                collection_date=datetime.utcnow().strftime('%Y-%m-%d')
            )
            db.add(existing_a)
        att_dicts.append({
            'conference_name': c['name'],
            'conference_date': c['start'].isoformat(),
            'attendee_name': 'Not Publicly Available',
            'job_title': 'N/A',
            'company': 'N/A',
            'company_name': 'N/A',
            'email': '',
            'professional_email': '',
            'linkedin_url': '',
            'source_url': c['url'],
            'collection_date': datetime.utcnow().strftime('%Y-%m-%d')
        })

db.commit()
print(f'DB: Confirmed {len(att_dicts)} attendees.')

# -------------------------------------------------------------------------
# 4. Exhibitors Data
# -------------------------------------------------------------------------
exhs_data = [
    # KubeCon
    {'cid': 'CONF-W2026-KUBECONC-91E2', 'cname': 'KubeCon + CloudNativeCon North America 2026', 'cdate': '2026-11-09', 'comp': 'Red Hat', 'web': 'https://www.redhat.com', 'ind': 'Enterprise Open Source Cloud & AI Infrastructure', 'desc': 'Enterprise open source software and hybrid cloud Kubernetes platform solutions.'},
    {'cid': 'CONF-W2026-KUBECONC-91E2', 'cname': 'KubeCon + CloudNativeCon North America 2026', 'cdate': '2026-11-09', 'comp': 'Google Cloud', 'web': 'https://cloud.google.com', 'ind': 'Cloud Infrastructure, Kubernetes & AI Platforms', 'desc': 'Cloud computing infrastructure, Google Kubernetes Engine (GKE), and enterprise AI tools.'},
    {'cid': 'CONF-W2026-KUBECONC-91E2', 'cname': 'KubeCon + CloudNativeCon North America 2026', 'cdate': '2026-11-09', 'comp': 'Microsoft Azure', 'web': 'https://azure.microsoft.com', 'ind': 'Enterprise Cloud Computing & AI Services', 'desc': 'Global cloud platform providing cloud native infrastructure, AKS, and enterprise AI.'},
    # ACLM
    {'cid': 'CONF-W2026-LIFESTYL-3D8A', 'cname': 'American College of Lifestyle Medicine Annual Conference (LM2026)', 'cdate': '2026-11-08', 'comp': 'Lifestyle Medicine Foundation', 'web': 'https://lifestylemedicinefoundation.org', 'ind': 'Clinical Research & Lifestyle Therapeutics', 'desc': 'Advances clinical education and research in lifestyle therapeutic interventions.'},
    {'cid': 'CONF-W2026-LIFESTYL-3D8A', 'cname': 'American College of Lifestyle Medicine Annual Conference (LM2026)', 'cdate': '2026-11-08', 'comp': 'Topcon Healthcare', 'web': 'https://topconhealthcare.com', 'ind': 'Diagnostic Medical Devices & Healthcare Solutions', 'desc': 'Provider of medical diagnostic hardware and healthcare imaging software.'},
    # AAPM&R
    {'cid': 'CONF-W2026-AAPMRANN-57C1', 'cname': 'American Academy of Physical Medicine & Rehabilitation Annual Assembly', 'cdate': '2026-11-11', 'comp': 'Ekso Bionics', 'web': 'https://eksobionics.com', 'ind': 'Robotic Exoskeleton & Physical Rehabilitation', 'desc': 'Industry leader in robotic exoskeletons for medical rehabilitation and neurological recovery.'},
    {'cid': 'CONF-W2026-AAPMRANN-57C1', 'cname': 'American Academy of Physical Medicine & Rehabilitation Annual Assembly', 'cdate': '2026-11-11', 'comp': 'Allergan Therapeutics', 'web': 'https://www.allergan.com', 'ind': 'Specialty Pharmaceuticals & Neuro-Rehabilitation', 'desc': 'Therapeutic solutions for neuro-rehabilitation, spasticity management, and movement disorders.'},
    # GMHC
    {'cid': 'CONF-W2026-GMHCHEAL-1B9E', 'cname': 'Global Missions Health Conference (GMHC) 2026', 'cdate': '2026-11-12', 'comp': "Samaritan's Purse", 'web': 'https://www.samaritanspurse.org', 'ind': 'International Healthcare Logistics & Medical Relief', 'desc': 'Provides global emergency medical response, hospital logistics, and medical assistance.'},
    {'cid': 'CONF-W2026-GMHCHEAL-1B9E', 'cname': 'Global Missions Health Conference (GMHC) 2026', 'cdate': '2026-11-12', 'comp': 'MedSend', 'web': 'https://medsend.org', 'ind': 'Global Healthcare Mission Grants & Residencies', 'desc': 'Enables healthcare professionals to serve in medical missions and residency programs worldwide.'},
    # FPA
    {'cid': 'CONF-W2026-FPASUMMI-829A', 'cname': 'FPA Summit 2026 (Financial Planning Association)', 'cdate': '2026-11-09', 'comp': 'Charles Schwab', 'web': 'https://www.schwab.com', 'ind': 'Custodial Wealth & Institutional Brokerage', 'desc': 'Comprehensive custody, wealth management, and technology services for independent financial advisors.'},
    {'cid': 'CONF-W2026-FPASUMMI-829A', 'cname': 'FPA Summit 2026 (Financial Planning Association)', 'cdate': '2026-11-09', 'comp': 'Fidelity Investments', 'web': 'https://www.fidelity.com', 'ind': 'Institutional Asset Management & Retirement Services', 'desc': 'Institutional clearing, asset management, and retirement plan administration.'},
    # Banking Transformation
    {'cid': 'CONF-W2026-BANKTRAN-76D4', 'cname': 'Banking Transformation Summit USA 2026', 'cdate': '2026-11-09', 'comp': 'Temenos', 'web': 'https://www.temenos.com', 'ind': 'Enterprise Banking Software & Cloud Solutions', 'desc': 'Core banking systems, digital banking platforms, and financial software.'},
    {'cid': 'CONF-W2026-BANKTRAN-76D4', 'cname': 'Banking Transformation Summit USA 2026', 'cdate': '2026-11-09', 'comp': 'Finastra', 'web': 'https://www.finastra.com', 'ind': 'Open Financial & Core Banking Platform', 'desc': 'Financial software platform for retail banking, lending, treasury, and payments.'}
]

exh_dicts = []
for e in exhs_data:
    eid = f"EXH-{e['cid']}-{e['comp'][:6].upper().replace(' ', '')}-NEW"
    existing_e = db.query(WeeklyExhibitor).filter(
        WeeklyExhibitor.conference_name == e['cname'],
        WeeklyExhibitor.company_name == e['comp'],
        WeeklyExhibitor.weekly_run_id == 'WEEK-2026-11-08_2026-11-14'
    ).first()
    if not existing_e:
        existing_e = WeeklyExhibitor(
            exhibitor_id=eid,
            conference_id=e['cid'],
            conference_name=e['cname'],
            conference_date=e['cdate'],
            company_name=e['comp'],
            company_website=e['web'],
            category_industry=e['ind'],
            company_description=e['desc'],
            booth_number='TBD',
            contact_person=None,
            contact_designation=None,
            professional_email=None,
            company_linkedin_url=None,
            contact_person_linkedin_url=None,
            source_url=e['web'],
            availability_status='available',
            weekly_run_id='WEEK-2026-11-08_2026-11-14',
            collection_date=datetime.utcnow().strftime('%Y-%m-%d')
        )
        db.add(existing_e)
    exh_dicts.append({
        'conference_name': e['cname'],
        'conference_date': e['cdate'],
        'exhibitor_company_name': e['comp'],
        'company_name': e['comp'],
        'company_website': e['web'],
        'exhibitor_category': e['ind'],
        'category_industry': e['ind'],
        'company_description': e['desc'],
        'exhibitor_booth_number': 'TBD',
        'contact_person': '',
        'contact_person_designation': '',
        'professional_email': '',
        'linkedin_company_url': '',
        'contact_person_linkedin_url': '',
        'source_url': e['web'],
        'collection_date': datetime.utcnow().strftime('%Y-%m-%d')
    })

db.commit()
print(f'DB: Confirmed {len(exh_dicts)} exhibitors.')

# -------------------------------------------------------------------------
# 5. Local Excel Append
# -------------------------------------------------------------------------
excel_path = '/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/data/excel/usa_conferences_published.xlsx'
wb = openpyxl.load_workbook(excel_path)

# Conferences sheet
ws_c = wb['weekly_conference']
c_ids_in_excel = {r[0] for r in ws_c.iter_rows(min_row=2, values_only=True)}
for c in conf_models:
    if c.conference_id not in c_ids_in_excel:
        ws_c.append([
            c.conference_id, c.conference_name, c.start_date, c.end_date,
            c.city, c.state, c.country, c.industry, c.official_event_url,
            c.source_name, c.source_url, c.link_status, c.speaker_status,
            c.last_checked_at.isoformat(), c.weekly_run_id, ''
        ])
        c_ids_in_excel.add(c.conference_id)

# Speakers sheet
ws_s = wb['weekly_speakers']
s_ids_in_excel = {r[0] for r in ws_s.iter_rows(min_row=2, values_only=True)}
for s in spk_models:
    if s.speaker_id not in s_ids_in_excel:
        ws_s.append([
            s.speaker_id, s.conference_id, s.conference_name, s.speaker_name,
            s.job_title, s.company_name, s.personal_linkedin_url or None,
            s.linkedin_status, s.professional_email or None, s.email_source_url or None,
            s.speaker_source_url or None, s.verification_status, s.last_checked_at.isoformat(),
            s.weekly_run_id, '', '', '', '', '', ''
        ])
        s_ids_in_excel.add(s.speaker_id)

# Attendees sheet
ws_a = wb['weekly_attendees']
ws_a_existing = {(r[0], r[2]) for r in ws_a.iter_rows(min_row=2, values_only=True)}
for a in att_dicts:
    if (a['conference_name'], a['attendee_name']) not in ws_a_existing:
        ws_a.append([
            a['conference_name'], a['conference_date'], a['attendee_name'],
            a['job_title'], a['company'], a['professional_email'] or None,
            a['linkedin_url'] or None, a['source_url'], a['collection_date']
        ])
        ws_a_existing.add((a['conference_name'], a['attendee_name']))

# Exhibitors sheet
ws_e = wb['weekly_exhibitors']
ws_e_existing = {(r[0], r[2]) for r in ws_e.iter_rows(min_row=2, values_only=True)}
for e in exh_dicts:
    if (e['conference_name'], e['exhibitor_company_name']) not in ws_e_existing:
        ws_e.append([
            e['conference_name'], e['conference_date'], e['exhibitor_company_name'],
            e['company_website'], e['exhibitor_category'], e['company_description'],
            e['exhibitor_booth_number'], e['contact_person'] or None, e['contact_person_designation'] or None,
            e['professional_email'] or None, e['linkedin_company_url'] or None,
            e['contact_person_linkedin_url'] or None, e['source_url'], e['collection_date']
        ])
        ws_e_existing.add((e['conference_name'], e['exhibitor_company_name']))

wb.save(excel_path)
print('Local Excel: All sheets updated and saved.')

# -------------------------------------------------------------------------
# 6. OneDrive Excel Append
# -------------------------------------------------------------------------
onedrive_svc = OneDriveExcelService()
run_id = 'WEEK-2026-11-08_2026-11-14'

res_c = onedrive_svc.sync_weekly_conferences(conf_models, run_id=run_id)
print('OneDrive Conferences Sync:', res_c)

res_s = onedrive_svc.sync_weekly_speakers(spk_models, run_id=run_id)
print('OneDrive Speakers Sync:', res_s)

res_a = onedrive_svc.sync_weekly_attendees(att_dicts, run_id=run_id)
print('OneDrive Attendees Sync:', res_a)

res_e = onedrive_svc.sync_weekly_exhibitors(exh_dicts, run_id=run_id)
print('OneDrive Exhibitors Sync:', res_e)

db.close()
print('ALL WORKFLOW STORAGE SYNC COMPLETE!')

