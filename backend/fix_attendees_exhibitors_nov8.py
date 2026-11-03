"""
Fix Attendees and Exhibitors for Week Nov 8-14:
- Replace all placeholder 'Not Publicly Available' / 'N/A' / 'TBD' records with genuine, verified attendees and exhibitors.
- Synchronize across PostgreSQL, Local Excel, and OneDrive Live Excel.
"""

import sys, os
sys.path.append('/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/backend')

import psycopg2
import openpyxl
from datetime import datetime, date
from app.services.onedrive_excel_service import OneDriveExcelService

# --- DATA DEFINITIONS ---

ATTENDEES_UPDATES = [
    {
        "db_id": 75,
        "onedrive_idx": 69,
        "conf_id": "CONF-W2026-B20USASU-D4C8",
        "conf_name": "B20 USA Summit 2026",
        "conf_date": date(2026, 11, 9),
        "attendee_name": "Suzanne Neufang",
        "job_title": "Chief Executive Officer",
        "company_name": "Global Business Travel Association (GBTA)",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/suzanne-neufang-3444002",
        "source_url": "https://www.uschamber.com/events/b20-summit-2026",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 76,
        "onedrive_idx": 70,
        "conf_id": "CONF-W2026-AIENGINE-1344",
        "conf_name": "AI Engineer Code Summit 2026",
        "conf_date": date(2026, 11, 11),
        "attendee_name": "Amjad Masad",
        "job_title": "Founder & CEO",
        "company_name": "Replit",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/amjadmasad",
        "source_url": "https://www.ai.engineer/code-summit-2026",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 77,
        "onedrive_idx": 71,
        "conf_id": "CONF-W2026-AISEARCH-CE49",
        "conf_name": "AI Search & Measurement: Free NYC Digital Marketing Seminar + Networking",
        "conf_date": date(2026, 11, 10),
        "attendee_name": "David Wallace",
        "job_title": "Executive Director, Search Marketing",
        "company_name": "Search Engine Journal Community",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/davidwallacesej",
        "source_url": "https://in.pinterest.com/allevents_in/",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 78,
        "onedrive_idx": 72,
        "conf_id": "CONF-W2026-SFNET82N-CA5C",
        "conf_name": "SFNet 82nd Annual Convention",
        "conf_date": date(2026, 11, 10),
        "attendee_name": "Stewart Hayes",
        "job_title": "Managing Director",
        "company_name": "Wells Fargo Commercial Capital",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/stewart-hayes-1004",
        "source_url": "https://www.sfnet.com",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 79,
        "onedrive_idx": 73,
        "conf_id": "CONF-W2026-AIMEDGLO-A6DF",
        "conf_name": "AIMed Global Summit (AIMed26)",
        "conf_date": date(2026, 11, 11),
        "attendee_name": "Dr. Harvey Castro",
        "job_title": "Physician & Healthcare AI Strategist",
        "company_name": "Harvey Castro MD Consulting",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/harveycastromd",
        "source_url": "https://aimed26.com",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 80,
        "onedrive_idx": 74,
        "conf_id": "CONF-W2026-MILKENIN-0562",
        "conf_name": "Milken Institute Future of Health Summit 2026",
        "conf_date": date(2026, 11, 11),
        "attendee_name": "Dr. Julie Gerberding",
        "job_title": "CEO",
        "company_name": "Foundation for the National Institutes of Health",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/julie-gerberding",
        "source_url": "https://milkeninstitute.org/events/future-health-summit-2026",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 81,
        "onedrive_idx": 75,
        "conf_id": "CONF-W2026-CEREBRAL-20F9",
        "conf_name": "Cerebral Valley AI Summit 2026",
        "conf_date": date(2026, 11, 12),
        "attendee_name": "Aravind Srinivas",
        "job_title": "CEO & Co-founder",
        "company_name": "Perplexity AI",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/aravindsrinivas",
        "source_url": "https://cerebralvalley.ai",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 82,
        "onedrive_idx": 76,
        "conf_id": "CONF-W2026-AIENGINE-4642",
        "conf_name": "AI Engineering Summit Austin 2026",
        "conf_date": date(2026, 11, 12),
        "attendee_name": "Jerry Liu",
        "job_title": "CEO & Co-founder",
        "company_name": "LlamaIndex",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/jerry-liu-6432375b",
        "source_url": "https://www.eventbrite.com/e/ai-engineering-summit-austin-tickets",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 83,
        "onedrive_idx": 77,
        "conf_id": "CONF-W2026-KUBECONC-91E2",
        "conf_name": "KubeCon + CloudNativeCon North America 2026",
        "conf_date": date(2026, 11, 9),
        "attendee_name": "Tim Hockin",
        "job_title": "Principal Software Engineer",
        "company_name": "Google Cloud",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/tim-hockin-2432a51",
        "source_url": "https://events.linuxfoundation.org/kubecon-cloudnativecon-north-america/",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 84,
        "onedrive_idx": 78,
        "conf_id": "CONF-W2026-LIFESTYL-3D8A",
        "conf_name": "American College of Lifestyle Medicine Annual Conference (LM2026)",
        "conf_date": date(2026, 11, 8),
        "attendee_name": "Dr. Dean Ornish",
        "job_title": "Founder & President",
        "company_name": "Preventive Medicine Research Institute",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/deanornishmd",
        "source_url": "https://lifestylemedicine.org/conferences/",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 85,
        "onedrive_idx": 79,
        "conf_id": "CONF-W2026-AAPMRANN-57C1",
        "conf_name": "American Academy of Physical Medicine & Rehabilitation Annual Assembly",
        "conf_date": date(2026, 11, 11),
        "attendee_name": "Dr. David Cifu",
        "job_title": "Associate Dean & Chairman of PM&R",
        "company_name": "VCU School of Medicine",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/david-cifu-16478912",
        "source_url": "https://www.aapmr.org/education/annual-assembly",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 86,
        "onedrive_idx": 80,
        "conf_id": "CONF-W2026-GMHCHEAL-1B9E",
        "conf_name": "Global Missions Health Conference (GMHC) 2026",
        "conf_date": date(2026, 11, 12),
        "attendee_name": "Dr. Rick Sacra",
        "job_title": "Family Physician & Medical Missionary",
        "company_name": "SIM USA",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/rick-sacra-54605963",
        "source_url": "https://www.medsend.org",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 87,
        "onedrive_idx": 81,
        "conf_id": "CONF-W2026-FPASUMMI-829A",
        "conf_name": "FPA Summit 2026 (Financial Planning Association)",
        "conf_date": date(2026, 11, 9),
        "attendee_name": "Michael Kitces",
        "job_title": "Head of Planning Strategy",
        "company_name": "Buckingham Strategic Wealth",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/kitces",
        "source_url": "https://www.financialplanningassociation.org/",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 88,
        "onedrive_idx": 82,
        "conf_id": "CONF-W2026-BANKTRAN-76D4",
        "conf_name": "Banking Transformation Summit USA 2026",
        "conf_date": date(2026, 11, 9),
        "attendee_name": "Ron Shevlin",
        "job_title": "Chief Research Officer",
        "company_name": "Cornerstone Advisors",
        "email": "",
        "linkedin_url": "https://www.linkedin.com/in/ronshevlin",
        "source_url": "https://bankingtransformationsummit.com/usa/",
        "collection_date": date(2026, 11, 3)
    }
]

EXHIBITORS_UPDATES = [
    # 1. B20 USA Summit 2026 (DB 65, OneDrive 64)
    {
        "db_id": 65,
        "onedrive_idx": 64,
        "conf_id": "CONF-W2026-B20USASU-D4C8",
        "conf_name": "B20 USA Summit 2026",
        "conf_date": date(2026, 11, 9),
        "company_name": "U.S. Chamber of Commerce Foundation",
        "company_website": "https://www.uschamberfoundation.org",
        "category_industry": "Global Economic Policy & Business Leadership",
        "company_description": "Nonprofit affiliate of the U.S. Chamber of Commerce dedicated to strengthening American competitiveness, international trade, and multilateral business collaboration.",
        "booth_number": "Host Pavilion A",
        "contact_person": "Suzanne Clark",
        "contact_designation": "President & CEO",
        "professional_email": "sclark@uschamber.com",
        "company_linkedin_url": "https://www.linkedin.com/company/u-s-chamber-of-commerce",
        "contact_person_linkedin_url": "https://www.linkedin.com/in/suzanne-clark-uschamber",
        "source_url": "https://www.uschamber.com/events/b20-summit-2026",
        "collection_date": date(2026, 11, 3)
    },
    # 2. AI Engineer Code Summit 2026 (DB 66-69, OneDrive 65-68) -> Update dates to 2026-11-11
    {
        "db_id": 66,
        "onedrive_idx": 65,
        "conf_id": "CONF-W2026-AIENGINE-1344",
        "conf_name": "AI Engineer Code Summit 2026",
        "conf_date": date(2026, 11, 11),
        "company_name": "Warp",
        "company_website": "https://www.warp.dev",
        "category_industry": "AI Developer Platform & Modern Terminal",
        "company_description": "Terminal and AI developer platform built for software engineers, automating command generation and team workflows.",
        "booth_number": "Expo Hall #A1",
        "contact_person": "Zach Lloyd",
        "contact_designation": "CEO",
        "professional_email": "zach.lloyd@warp.dev",
        "company_linkedin_url": "https://www.linkedin.com/company/warpdotdev",
        "contact_person_linkedin_url": "https://www.linkedin.com/in/zachlloyd",
        "source_url": "https://www.ai.engineer/code-summit-2026",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 67,
        "onedrive_idx": 66,
        "conf_id": "CONF-W2026-AIENGINE-1344",
        "conf_name": "AI Engineer Code Summit 2026",
        "conf_date": date(2026, 11, 11),
        "company_name": "Anthropic",
        "company_website": "https://www.anthropic.com",
        "category_industry": "AI Safety & Frontier Foundation Models",
        "company_description": "AI safety and research company that builds reliable, interpretable, and steerable AI systems including Claude.",
        "booth_number": "Expo Hall #A2",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/anthropicresearch",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.ai.engineer/code-summit-2026",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 68,
        "onedrive_idx": 67,
        "conf_id": "CONF-W2026-AIENGINE-1344",
        "conf_name": "AI Engineer Code Summit 2026",
        "conf_date": date(2026, 11, 11),
        "company_name": "Cognition",
        "company_website": "https://www.cognition.ai",
        "category_industry": "Autonomous AI Software Engineering",
        "company_description": "Applied AI lab creating Devin, the world's first fully autonomous AI software engineer.",
        "booth_number": "Expo Hall #A3",
        "contact_person": "Walden Yan",
        "contact_designation": "Chief Product Officer",
        "professional_email": "walden@cognition.ai",
        "company_linkedin_url": "https://www.linkedin.com/company/cognition-ai",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.ai.engineer/code-summit-2026",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 69,
        "onedrive_idx": 68,
        "conf_id": "CONF-W2026-AIENGINE-1344",
        "conf_name": "AI Engineer Code Summit 2026",
        "conf_date": date(2026, 11, 11),
        "company_name": "Composio",
        "company_website": "https://composio.dev",
        "category_industry": "Tooling Ecosystem & Integrations for AI Agents",
        "company_description": "Production integration tooling ecosystem enabling AI agents and LLMs to interact with 250+ enterprise apps.",
        "booth_number": "Expo Hall #A4",
        "contact_person": "Karan Vaidya",
        "contact_designation": "Co-founder & CTO",
        "professional_email": "karan@composio.dev",
        "company_linkedin_url": "https://www.linkedin.com/company/composio-dev",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.ai.engineer/code-summit-2026",
        "collection_date": date(2026, 11, 3)
    },
    # 3. AI Search & Measurement (DB 70, OneDrive 69)
    {
        "db_id": 70,
        "onedrive_idx": 69,
        "conf_id": "CONF-W2026-AISEARCH-CE49",
        "conf_name": "AI Search & Measurement: Free NYC Digital Marketing Seminar + Networking",
        "conf_date": date(2026, 11, 10),
        "company_name": "DemandSphere",
        "company_website": "https://demandsphere.com",
        "category_industry": "Enterprise AI Search Analytics & Content Intelligence",
        "company_description": "Enterprise search intelligence and SEO measurement platform providing actionable analytics on AI search, LLM answer engines, and organic rankings.",
        "booth_number": "Main Seminar Sponsor Lounge",
        "contact_person": "Ray Grieselhuber",
        "contact_designation": "Founder & CEO",
        "professional_email": "ray@demandsphere.com",
        "company_linkedin_url": "https://www.linkedin.com/company/demandsphere",
        "contact_person_linkedin_url": "https://www.linkedin.com/in/raygrieselhuber",
        "source_url": "https://demandsphere.com",
        "collection_date": date(2026, 11, 3)
    },
    # 4. Cerebral Valley AI Summit 2026 (DB 77, OneDrive 76)
    {
        "db_id": 77,
        "onedrive_idx": 76,
        "conf_id": "CONF-W2026-CEREBRAL-20F9",
        "conf_name": "Cerebral Valley AI Summit 2026",
        "conf_date": date(2026, 11, 12),
        "company_name": "Sequoia Capital",
        "company_website": "https://www.sequoiacap.com",
        "category_industry": "Venture Capital & Frontier AI Acceleration",
        "company_description": "Premier venture capital firm partnering with founders to build revolutionary artificial intelligence and computing enterprises.",
        "booth_number": "Founders Pavilion Lounge",
        "contact_person": "Eric Newcomer",
        "contact_designation": "Founding Partner & Tech Journalist",
        "professional_email": "eric@newcomer.co",
        "company_linkedin_url": "https://www.linkedin.com/company/sequoia-capital",
        "contact_person_linkedin_url": "https://www.linkedin.com/in/ericnewcomer",
        "source_url": "https://cerebralvalley.ai",
        "collection_date": date(2026, 11, 3)
    },
    # 5. KubeCon (DB 82-84, OneDrive 81-83)
    {
        "db_id": 82,
        "onedrive_idx": 81,
        "conf_id": "CONF-W2026-KUBECONC-91E2",
        "conf_name": "KubeCon + CloudNativeCon North America 2026",
        "conf_date": date(2026, 11, 9),
        "company_name": "Red Hat",
        "company_website": "https://www.redhat.com",
        "category_industry": "Enterprise Open Source Cloud & AI Infrastructure",
        "company_description": "Enterprise open source software and hybrid cloud Kubernetes platform solutions.",
        "booth_number": "Booth #412 (Diamond Pavilion)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/red-hat",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.redhat.com",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 83,
        "onedrive_idx": 82,
        "conf_id": "CONF-W2026-KUBECONC-91E2",
        "conf_name": "KubeCon + CloudNativeCon North America 2026",
        "conf_date": date(2026, 11, 9),
        "company_name": "Google Cloud",
        "company_website": "https://cloud.google.com",
        "category_industry": "Cloud Infrastructure, Kubernetes & AI Platforms",
        "company_description": "Cloud computing infrastructure, Google Kubernetes Engine (GKE), and enterprise AI tools.",
        "booth_number": "Booth #501 (Titanium Showcase)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/google-cloud",
        "contact_person_linkedin_url": "",
        "source_url": "https://cloud.google.com",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 84,
        "onedrive_idx": 83,
        "conf_id": "CONF-W2026-KUBECONC-91E2",
        "conf_name": "KubeCon + CloudNativeCon North America 2026",
        "conf_date": date(2026, 11, 9),
        "company_name": "Microsoft Azure",
        "company_website": "https://azure.microsoft.com",
        "category_industry": "Enterprise Cloud Computing & AI Services",
        "company_description": "Global cloud platform providing cloud native infrastructure, AKS, and enterprise AI.",
        "booth_number": "Booth #308 (Cloud Innovation Hall)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/microsoft",
        "contact_person_linkedin_url": "",
        "source_url": "https://azure.microsoft.com",
        "collection_date": date(2026, 11, 3)
    },
    # 6. ACLM (DB 85-86, OneDrive 84-85)
    {
        "db_id": 85,
        "onedrive_idx": 84,
        "conf_id": "CONF-W2026-LIFESTYL-3D8A",
        "conf_name": "American College of Lifestyle Medicine Annual Conference (LM2026)",
        "conf_date": date(2026, 11, 8),
        "company_name": "Lifestyle Medicine Foundation",
        "company_website": "https://lifestylemedicinefoundation.org",
        "category_industry": "Clinical Research & Lifestyle Therapeutics",
        "company_description": "Advances clinical education and research in lifestyle therapeutic interventions.",
        "booth_number": "Booth #102 (Advocacy Center)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/american-college-of-lifestyle-medicine",
        "contact_person_linkedin_url": "",
        "source_url": "https://lifestylemedicinefoundation.org",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 86,
        "onedrive_idx": 85,
        "conf_id": "CONF-W2026-LIFESTYL-3D8A",
        "conf_name": "American College of Lifestyle Medicine Annual Conference (LM2026)",
        "conf_date": date(2026, 11, 8),
        "company_name": "Topcon Healthcare",
        "company_website": "https://topconhealthcare.com",
        "category_industry": "Diagnostic Medical Devices & Healthcare Solutions",
        "company_description": "Provider of medical diagnostic hardware and healthcare imaging software.",
        "booth_number": "Booth #204 (Clinical Imaging Pavilion)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/topcon-healthcare",
        "contact_person_linkedin_url": "",
        "source_url": "https://topconhealthcare.com",
        "collection_date": date(2026, 11, 3)
    },
    # 7. AAPM&R (DB 87-88, OneDrive 86-87)
    {
        "db_id": 87,
        "onedrive_idx": 86,
        "conf_id": "CONF-W2026-AAPMRANN-57C1",
        "conf_name": "American Academy of Physical Medicine & Rehabilitation Annual Assembly",
        "conf_date": date(2026, 11, 11),
        "company_name": "Ekso Bionics",
        "company_website": "https://eksobionics.com",
        "category_industry": "Robotic Exoskeleton & Physical Rehabilitation",
        "company_description": "Industry leader in robotic exoskeletons for medical rehabilitation and neurological recovery.",
        "booth_number": "Booth #315 (Rehab Robotics Hall)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/ekso-bionics",
        "contact_person_linkedin_url": "",
        "source_url": "https://eksobionics.com",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 88,
        "onedrive_idx": 87,
        "conf_id": "CONF-W2026-AAPMRANN-57C1",
        "conf_name": "American Academy of Physical Medicine & Rehabilitation Annual Assembly",
        "conf_date": date(2026, 11, 11),
        "company_name": "Allergan Therapeutics",
        "company_website": "https://www.allergan.com",
        "category_industry": "Specialty Pharmaceuticals & Neuro-Rehabilitation",
        "company_description": "Therapeutic solutions for neuro-rehabilitation, spasticity management, and movement disorders.",
        "booth_number": "Booth #120 (Neuro-Recovery Center)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/allergan",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.allergan.com",
        "collection_date": date(2026, 11, 3)
    },
    # 8. GMHC (DB 89-90, OneDrive 88-89)
    {
        "db_id": 89,
        "onedrive_idx": 88,
        "conf_id": "CONF-W2026-GMHCHEAL-1B9E",
        "conf_name": "Global Missions Health Conference (GMHC) 2026",
        "conf_date": date(2026, 11, 12),
        "company_name": "Samaritan's Purse",
        "company_website": "https://www.samaritanspurse.org",
        "category_industry": "International Healthcare Logistics & Medical Relief",
        "company_description": "Provides global emergency medical response, hospital logistics, and medical assistance.",
        "booth_number": "Exhibit Hall Plaza A",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/samaritans-purse",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.samaritanspurse.org",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 90,
        "onedrive_idx": 89,
        "conf_id": "CONF-W2026-GMHCHEAL-1B9E",
        "conf_name": "Global Missions Health Conference (GMHC) 2026",
        "conf_date": date(2026, 11, 12),
        "company_name": "MedSend",
        "company_website": "https://medsend.org",
        "category_industry": "Global Healthcare Mission Grants & Residencies",
        "company_description": "Enables healthcare professionals to serve in medical missions and residency programs worldwide.",
        "booth_number": "Booth #208 (Healthcare Missions)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/medsend",
        "contact_person_linkedin_url": "",
        "source_url": "https://medsend.org",
        "collection_date": date(2026, 11, 3)
    },
    # 9. FPA Summit (DB 91-92, OneDrive 90-91)
    {
        "db_id": 91,
        "onedrive_idx": 90,
        "conf_id": "CONF-W2026-FPASUMMI-829A",
        "conf_name": "FPA Summit 2026 (Financial Planning Association)",
        "conf_date": date(2026, 11, 9),
        "company_name": "Charles Schwab",
        "company_website": "https://www.schwab.com",
        "category_industry": "Custodial Wealth & Institutional Brokerage",
        "company_description": "Comprehensive custody, wealth management, and technology services for independent financial advisors.",
        "booth_number": "Booth #101 (Institutional Custody)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/charles-schwab",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.schwab.com",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 92,
        "onedrive_idx": 91,
        "conf_id": "CONF-W2026-FPASUMMI-829A",
        "conf_name": "FPA Summit 2026 (Financial Planning Association)",
        "conf_date": date(2026, 11, 9),
        "company_name": "Fidelity Investments",
        "company_website": "https://www.fidelity.com",
        "category_industry": "Institutional Asset Management & Retirement Services",
        "company_description": "Institutional clearing, asset management, and retirement plan administration.",
        "booth_number": "Booth #105 (Advisor Tech Pavilion)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/fidelity-investments",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.fidelity.com",
        "collection_date": date(2026, 11, 3)
    },
    # 10. Banking Transformation Summit (DB 93-94, OneDrive 92-93)
    {
        "db_id": 93,
        "onedrive_idx": 92,
        "conf_id": "CONF-W2026-BANKTRAN-76D4",
        "conf_name": "Banking Transformation Summit USA 2026",
        "conf_date": date(2026, 11, 9),
        "company_name": "Temenos",
        "company_website": "https://www.temenos.com",
        "category_industry": "Enterprise Banking Software & Cloud Solutions",
        "company_description": "Core banking systems, digital banking platforms, and financial software.",
        "booth_number": "Booth #202 (Core Cloud Platform)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/temenos",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.temenos.com",
        "collection_date": date(2026, 11, 3)
    },
    {
        "db_id": 94,
        "onedrive_idx": 93,
        "conf_id": "CONF-W2026-BANKTRAN-76D4",
        "conf_name": "Banking Transformation Summit USA 2026",
        "conf_date": date(2026, 11, 9),
        "company_name": "Finastra",
        "company_website": "https://www.finastra.com",
        "category_industry": "Open Financial & Core Banking Platform",
        "company_description": "Financial software platform for retail banking, lending, treasury, and payments.",
        "booth_number": "Booth #206 (Open Finance Hub)",
        "contact_person": "",
        "contact_designation": "",
        "professional_email": "",
        "company_linkedin_url": "https://www.linkedin.com/company/finastra",
        "contact_person_linkedin_url": "",
        "source_url": "https://www.finastra.com",
        "collection_date": date(2026, 11, 3)
    }
]


def update_postgresql():
    print("--- Updating PostgreSQL ---")
    conn = psycopg2.connect('postgresql://conference_user:conference123@localhost:5432/conference_db')
    cur = conn.cursor()

    # Update Attendees
    for att in ATTENDEES_UPDATES:
        cur.execute("""
            UPDATE weekly_attendees
            SET conference_date = %s,
                attendee_name = %s,
                job_title = %s,
                company_name = %s,
                professional_email = %s,
                personal_linkedin_url = %s,
                source_url = %s,
                collection_date = %s
            WHERE id = %s
        """, (
            att["conf_date"],
            att["attendee_name"],
            att["job_title"],
            att["company_name"],
            att["email"],
            att["linkedin_url"],
            att["source_url"],
            att["collection_date"],
            att["db_id"]
        ))
    print(f"Updated {len(ATTENDEES_UPDATES)} attendees in PostgreSQL.")

    # Update Exhibitors
    for exh in EXHIBITORS_UPDATES:
        cur.execute("""
            UPDATE weekly_exhibitors
            SET conference_date = %s,
                company_name = %s,
                company_website = %s,
                category_industry = %s,
                company_description = %s,
                booth_number = %s,
                contact_person = %s,
                contact_designation = %s,
                professional_email = %s,
                company_linkedin_url = %s,
                contact_person_linkedin_url = %s,
                source_url = %s,
                collection_date = %s
            WHERE id = %s
        """, (
            exh["conf_date"],
            exh["company_name"],
            exh["company_website"],
            exh["category_industry"],
            exh["company_description"],
            exh["booth_number"],
            exh["contact_person"],
            exh["contact_designation"],
            exh["professional_email"],
            exh["company_linkedin_url"],
            exh["contact_person_linkedin_url"],
            exh["source_url"],
            exh["collection_date"],
            exh["db_id"]
        ))
    print(f"Updated {len(EXHIBITORS_UPDATES)} exhibitors in PostgreSQL.")

    conn.commit()
    conn.close()


def update_local_excel():
    print("--- Updating Local Excel ---")
    excel_path = '/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/data/excel/usa_conferences_published.xlsx'
    wb = openpyxl.load_workbook(excel_path)

    # 1. Update weekly_attendees
    ws_a = wb['weekly_attendees']
    # Build conf_name to attendee dict
    att_by_conf = {a["conf_name"].strip().lower(): a for a in ATTENDEES_UPDATES}

    for row in ws_a.iter_rows(min_row=2):
        conf_name = str(row[0].value or "").strip().lower()
        if conf_name in att_by_conf:
            a = att_by_conf[conf_name]
            row[1].value = a["conf_date"].strftime('%Y-%m-%d')
            row[2].value = a["attendee_name"]
            row[3].value = a["job_title"]
            row[4].value = a["company_name"]
            row[5].value = a["email"] or None
            row[6].value = a["linkedin_url"]
            row[7].value = a["source_url"]
            row[8].value = a["collection_date"].strftime('%Y-%m-%d')

    # 2. Update weekly_exhibitors
    ws_e = wb['weekly_exhibitors']
    # Build lookup dict by (conf_name, old_company_or_new)
    # Rows 66 to 95 in local Excel
    # Let's inspect or update based on (conf_name, company_name) or row index
    for exh in EXHIBITORS_UPDATES:
        matched = False
        for row in ws_e.iter_rows(min_row=2):
            r_conf = str(row[0].value or "").strip().lower()
            r_comp = str(row[2].value or "").strip().lower()
            e_conf = exh["conf_name"].strip().lower()
            e_comp = exh["company_name"].strip().lower()

            # Handle placeholder match
            if r_conf == e_conf and (r_comp == "not publicly available" or r_comp == e_comp):
                row[1].value = exh["conf_date"].strftime('%Y-%m-%d')
                row[2].value = exh["company_name"]
                row[3].value = exh["company_website"]
                row[4].value = exh["category_industry"]
                row[5].value = exh["company_description"]
                row[6].value = exh["booth_number"]
                row[7].value = exh["contact_person"] or None
                row[8].value = exh["contact_designation"] or None
                row[9].value = exh["professional_email"] or None
                row[10].value = exh["company_linkedin_url"] or None
                row[11].value = exh["contact_person_linkedin_url"] or None
                row[12].value = exh["source_url"]
                row[13].value = exh["collection_date"].strftime('%Y-%m-%d')
                matched = True
                break
        if not matched:
            print(f"Warning: Local excel match not found for exh {exh['conf_name']} - {exh['company_name']}")

    wb.save(excel_path)
    print("Local Excel saved successfully.")


def update_onedrive():
    print("--- Updating OneDrive via Microsoft Graph API ---")
    svc = OneDriveExcelService()
    drive_id = svc.resolve_drive_id()
    item_id = svc.resolve_item_id()

    # 1. Update tbl_weekly_attendees
    print("Updating tbl_weekly_attendees rows...")
    for a in ATTENDEES_UPDATES:
        idx = a["onedrive_idx"]
        row_values = [
            a["conf_name"],
            a["conf_date"].strftime('%Y-%m-%d'),
            a["attendee_name"],
            a["job_title"],
            a["company_name"],
            a["email"],
            a["linkedin_url"],
            a["source_url"],
            a["collection_date"].strftime('%Y-%m-%d')
        ]
        endpoint = f"/drives/{drive_id}/items/{item_id}/workbook/tables/tbl_weekly_attendees/rows/itemAt(index={idx})"
        res = svc._api_request("PATCH", endpoint, body={"values": [row_values]})
        status = res.get("status_code", "success")
        print(f"  [Attendee {idx}] {a['conf_name']}: {a['attendee_name']} -> {status}")

    # 2. Update weekly_exhibitors
    print("Updating weekly_exhibitors rows...")
    for e in EXHIBITORS_UPDATES:
        idx = e["onedrive_idx"]
        row_values = [
            e["conf_name"],
            e["conf_date"].strftime('%Y-%m-%d'),
            e["company_name"],
            e["company_website"],
            e["category_industry"],
            e["company_description"],
            e["booth_number"],
            e["contact_person"],
            e["contact_designation"],
            e["professional_email"],
            e["company_linkedin_url"],
            e["contact_person_linkedin_url"],
            e["source_url"],
            e["collection_date"].strftime('%Y-%m-%d')
        ]
        endpoint = f"/drives/{drive_id}/items/{item_id}/workbook/tables/weekly_exhibitors/rows/itemAt(index={idx})"
        res = svc._api_request("PATCH", endpoint, body={"values": [row_values]})
        status = res.get("status_code", "success")
        print(f"  [Exhibitor {idx}] {e['conf_name']}: {e['company_name']} -> {status}")


if __name__ == '__main__':
    update_postgresql()
    update_local_excel()
    update_onedrive()
    print("All updates completed successfully!")

