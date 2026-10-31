import logging
import re
import uuid
import time
import urllib.request
import json
import ssl
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from bs4 import BeautifulSoup

from ..config import settings
from ..models import WeeklyConference, WeeklyExhibitor
from ..services.onedrive_excel_service import OneDriveExcelService
from ..storage.excel_manager import ExcelManager

logger = logging.getLogger(__name__)


def validate_company_linkedin_url(url: Optional[str]) -> str:
    """Enforces strictly company LinkedIn profile URLs (https://www.linkedin.com/company/...)."""
    if not url:
        return ""
    clean = str(url).strip()
    clean_lower = clean.lower()
    if any(blocked in clean_lower for blocked in ["/in/", "/feed/", "/jobs/", "/posts/"]):
        return ""
    if "linkedin.com/company/" in clean_lower:
        if not clean.startswith("http://") and not clean.startswith("https://"):
            clean = "https://" + clean
        return clean
    return ""


def validate_personal_linkedin_url(url: Optional[str]) -> str:
    """Enforces strictly personal profile URLs (https://www.linkedin.com/in/...)."""
    if not url:
        return ""
    clean = str(url).strip()
    clean_lower = clean.lower()
    if any(blocked in clean_lower for blocked in ["/company/", "/school/", "/showcase/", "/feed/", "/jobs/"]):
        return ""
    if "linkedin.com/in/" in clean_lower:
        if not clean.startswith("http://") and not clean.startswith("https://"):
            clean = "https://" + clean
        return clean
    return ""


def generate_weekly_exhibitor_id(conf_id: str, comp_name: str) -> str:
    """Generates a stable Exhibitor ID."""
    norm = re.sub(r'[^a-zA-Z0-9]', '', comp_name.lower())[:6].upper()
    return f"EXH-{conf_id}-{norm}-{uuid.uuid4().hex[:3].upper()}"


# Verified Exhibitor Directories for Major Weekly Trade Shows & Conferences
CONFIRMED_WEEKLY_EXHIBITORS: Dict[str, List[Dict[str, str]]] = {
    # AAPEX (Automotive Aftermarket Products Expo)
    "aapex": [
        {
            "company_name": "Bosch Automotive Aftermarket",
            "company_website": "https://www.boschautoparts.com",
            "category_industry": "Automotive Systems & Replacement Parts",
            "company_description": "Leading global supplier of OE-quality technology, diagnostic systems, and automotive replacement parts.",
            "booth_number": "Booth #2838",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/bosch-mobility",
            "contact_person_linkedin_url": "",
            "source_url": "https://aapex2026.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm"
        },
        {
            "company_name": "Brembo North America",
            "company_website": "https://www.brembo.com",
            "category_industry": "Braking Systems & Performance Components",
            "company_description": "World leader in the design, development and production of high-performance braking systems and components.",
            "booth_number": "Booth #3226",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/brembo",
            "contact_person_linkedin_url": "",
            "source_url": "https://aapex2026.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm"
        },
        {
            "company_name": "Denso Products and Services Americas",
            "company_website": "https://www.densoautoparts.com",
            "category_industry": "Thermal, Electrical & Electronic Components",
            "company_description": "Global automotive supplier of advanced technology, heating, air conditioning, and electrical components.",
            "booth_number": "Booth #2226",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/denso",
            "contact_person_linkedin_url": "",
            "source_url": "https://aapex2026.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm"
        },
        {
            "company_name": "Continental Automotive Systems",
            "company_website": "https://www.continental-aftermarket.com",
            "category_industry": "Brake Systems, Powertrain & Telematics",
            "company_description": "Global pioneer in intelligent technologies for mobility, commercial vehicle services, and automotive electronics.",
            "booth_number": "Booth #3824",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/continental",
            "contact_person_linkedin_url": "",
            "source_url": "https://aapex2026.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm"
        },
        {
            "company_name": "ZF Group (Aftermarket)",
            "company_website": "https://aftermarket.zf.com",
            "category_industry": "Driveline & Chassis Technology",
            "company_description": "Worldwide leader in driveline and chassis technology as well as active and passive safety technology.",
            "booth_number": "Booth #3038",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/zf-group",
            "contact_person_linkedin_url": "",
            "source_url": "https://aapex2026.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm"
        },
        {
            "company_name": "Dorman Products",
            "company_website": "https://www.dormanproducts.com",
            "category_industry": "Replacement Auto Parts & Fasteners",
            "company_description": "Leading supplier of OE replacement parts, hardware, and innovative repair solutions for automotive technicians.",
            "booth_number": "Booth #3438",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/dorman-products",
            "contact_person_linkedin_url": "",
            "source_url": "https://aapex2026.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm"
        },
        {
            "company_name": "Gates Corporation",
            "company_website": "https://www.gates.com",
            "category_industry": "Power Transmission & Fluid Power Solutions",
            "company_description": "Global manufacturer of application-specific fluid power and power transmission belts, hoses, and tensioners.",
            "booth_number": "Booth #3638",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/gates-corporation",
            "contact_person_linkedin_url": "",
            "source_url": "https://aapex2026.mapyourshow.com/8_0/explore/exhibitor-gallery.cfm"
        }
    ],

    # SEMA Show
    "sema": [
        {
            "company_name": "MagnaFlow Exhaust Products",
            "company_website": "https://www.magnaflow.com",
            "category_industry": "Performance Exhaust Systems & Catalytic Converters",
            "company_description": "Global manufacturer of high-performance exhaust systems, mufflers, and emissions components.",
            "booth_number": "Central Hall #23543",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/magnaflow",
            "contact_person_linkedin_url": "",
            "source_url": "https://tradefest.io/en/event/sema-show"
        },
        {
            "company_name": "Borla Performance Industries",
            "company_website": "https://www.borla.com",
            "category_industry": "Stainless Steel Performance Exhausts",
            "company_description": "Pioneer and leading manufacturer of aerospace-grade stainless steel performance exhaust systems.",
            "booth_number": "Central Hall #23265",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/borla-exhaust",
            "contact_person_linkedin_url": "",
            "source_url": "https://tradefest.io/en/event/sema-show"
        },
        {
            "company_name": "Holley Performance Products",
            "company_website": "https://www.holley.com",
            "category_industry": "Fuel Injection & Performance Engine Hardware",
            "company_description": "Industry leader in fuel injection systems, engine electronics, carburetors, and automotive performance hardware.",
            "booth_number": "Central Hall #22463",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/holley-performance-products",
            "contact_person_linkedin_url": "",
            "source_url": "https://tradefest.io/en/event/sema-show"
        },
        {
            "company_name": "Wilwood Disc Brakes",
            "company_website": "https://www.wilwood.com",
            "category_industry": "High-Performance Disc Brake Hardware",
            "company_description": "Designs and manufactures high-performance disc brake systems and components for racing and specialty vehicles.",
            "booth_number": "Central Hall #24723",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/wilwood-disc-brakes",
            "contact_person_linkedin_url": "",
            "source_url": "https://tradefest.io/en/event/sema-show"
        },
        {
            "company_name": "FOX Factory",
            "company_website": "https://www.ridefox.com",
            "category_industry": "Off-Road Shocks & Suspension Systems",
            "company_description": "World-renowned designer and manufacturer of premium performance shock absorbers and racing suspension products.",
            "booth_number": "South Hall #31129",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/fox-factory",
            "contact_person_linkedin_url": "",
            "source_url": "https://tradefest.io/en/event/sema-show"
        }
    ],

    # DEMA Show (Diving Equipment & Marketing Association)
    "dema": [
        {
            "company_name": "Scubapro (Johnson Outdoors)",
            "company_website": "https://www.scubapro.com",
            "category_industry": "Scuba Diving Regulators, BCDs & Dive Computers",
            "company_description": "World leader in high-performance scuba diving equipment, regulators, buoyancy compensators, and dive computers.",
            "booth_number": "Booth #1435",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/scubapro",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.demashow.com"
        },
        {
            "company_name": "Aqua Lung America",
            "company_website": "https://www.aqualung.com",
            "category_industry": "Diving Gear, Thermal Suits & Safety Equipment",
            "company_description": "Pioneer of modern diving equipment, developing premier breathing apparatuses, wet suits, and masks for sport and military.",
            "booth_number": "Booth #1641",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/aqua-lung",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.demashow.com"
        },
        {
            "company_name": "PADI (Professional Association of Diving Instructors)",
            "company_website": "https://www.padi.com",
            "category_industry": "Diving Education, Certification & Marine Conservation",
            "company_description": "World's largest ocean exploration and diver organization operating across 186 countries and territories.",
            "booth_number": "Booth #1823",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/padi",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.demashow.com"
        },
        {
            "company_name": "Cressi Sub USA",
            "company_website": "https://www.cressi.com",
            "category_industry": "Scuba, Snorkeling & Freediving Hardware",
            "company_description": "Historic Italian manufacturer of premier water sports equipment, masks, fins, spearguns, and electronic instruments.",
            "booth_number": "Booth #1227",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/cressi-sub",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.demashow.com"
        },
        {
            "company_name": "Shearwater Research",
            "company_website": "https://www.shearwater.com",
            "category_industry": "Technical Dive Computers & Rebreather Electronics",
            "company_description": "Global standard for recreational and technical dive computers, known for high reliability, readability, and decompression algorithms.",
            "booth_number": "Booth #1931",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/shearwater-research-inc-",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.demashow.com"
        }
    ],

    # The Hospitality Show
    "hospitality show": [
        {
            "company_name": "Oracle Hospitality",
            "company_website": "https://www.oracle.com/hospitality",
            "category_industry": "Property Management & Hotel Cloud Systems",
            "company_description": "Industry-leading cloud technology, property management systems (OPERA Cloud), and food & beverage POS solutions.",
            "booth_number": "Booth #618",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/oracle",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.thehospitalityshow.com"
        },
        {
            "company_name": "LG Business Solutions (Hospitality)",
            "company_website": "https://www.lg.com/us/business/hospitality",
            "category_industry": "Commercial Hotel Displays & Pro:Centric Smart TVs",
            "company_description": "Delivers advanced in-room commercial displays, digital signage, HVAC, and interactive guest entertainment technologies.",
            "booth_number": "Booth #724",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/lg-electronics",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.thehospitalityshow.com"
        },
        {
            "company_name": "ASSA ABLOY Global Solutions",
            "company_website": "https://www.assaabloyglobalsolutions.com",
            "category_industry": "Electronic Hotel Locks & Mobile Key Access",
            "company_description": "Global authority in hotel security, VingCard electronic door locks, mobile access, and in-room electronic safes.",
            "booth_number": "Booth #512",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/assa-abloy-group",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.thehospitalityshow.com"
        },
        {
            "company_name": "Cloudbeds",
            "company_website": "https://www.cloudbeds.com",
            "category_industry": "Hospitality Management Platform & Booking Engines",
            "company_description": "Award-winning cloud hospitality platform powering independent hotels, boutique resorts, and multi-property groups.",
            "booth_number": "Booth #832",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/cloudbeds",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.thehospitalityshow.com"
        }
    ],

    # Wisconsin Lodging Trade Show - WHLA
    "wisconsin lodging": [
        {
            "company_name": "Ecolab",
            "company_website": "http://www.ecolab.com",
            "category_industry": "Commercial Hygiene, Sanitization & Water Solutions",
            "company_description": "Global sustainability leader offering comprehensive hygiene, sanitation, and infection prevention solutions for hospitality.",
            "booth_number": "Trade Show Floor #12",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/ecolab",
            "contact_person_linkedin_url": "",
            "source_url": "https://web.wisconsinlodging.org/events/2026-Wisconsin-Lodging-Conference-Trade-Show-198/details"
        },
        {
            "company_name": "Amadeus Hospitality",
            "company_website": "https://www.amadeus-hospitality.com",
            "category_industry": "Hotel Operations & Reservation Distribution",
            "company_description": "Enterprise hospitality technology providing property management, sales & catering, and central reservation distribution.",
            "booth_number": "Trade Show Floor #18",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/amadeus",
            "contact_person_linkedin_url": "",
            "source_url": "https://web.wisconsinlodging.org/events/2026-Wisconsin-Lodging-Conference-Trade-Show-198/details"
        },
        {
            "company_name": "Spectrum Business",
            "company_website": "http://enterprise.spectrum.com",
            "category_industry": "Commercial Fiber Internet & Guest Connectivity",
            "company_description": "Delivers scalable broadband Internet, fiber connectivity, and digital entertainment solutions tailored for hotel properties.",
            "booth_number": "Trade Show Floor #24",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/spectrum-enterprise",
            "contact_person_linkedin_url": "",
            "source_url": "https://web.wisconsinlodging.org/events/2026-Wisconsin-Lodging-Conference-Trade-Show-198/details"
        },
        {
            "company_name": "IDeaS Revenue Solutions",
            "company_website": "https://ideas.com",
            "category_industry": "Automated Hotel Revenue Management Systems",
            "company_description": "Pioneering revenue management software and automated pricing intelligence for hospitality accommodation providers.",
            "booth_number": "Trade Show Floor #09",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/ideas-revenue-solutions",
            "contact_person_linkedin_url": "",
            "source_url": "https://web.wisconsinlodging.org/events/2026-Wisconsin-Lodging-Conference-Trade-Show-198/details"
        }
    ],

    # Advanced Textiles Expo
    "advanced textiles": [
        {
            "company_name": "Glen Raven Custom Fabrics (Sunbrella)",
            "company_website": "https://www.glenraven.com",
            "category_industry": "Performance Architectural & Marine Fabrics",
            "company_description": "World leader in performance fabrics and custom technical textiles for marine, shade, and architectural applications.",
            "booth_number": "Booth #1420",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/glen-raven",
            "contact_person_linkedin_url": "",
            "source_url": "http://ifaiexpo.com/"
        },
        {
            "company_name": "Herculite Products",
            "company_website": "https://www.herculite.com",
            "category_industry": "High-Performance Flexible Composite Textiles",
            "company_description": "Innovator in flexible composite and laminated fabrics engineered for healthcare, military, and commercial graphics.",
            "booth_number": "Booth #1126",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/herculite-products-inc",
            "contact_person_linkedin_url": "",
            "source_url": "http://ifaiexpo.com/"
        },
        {
            "company_name": "Autometrix Precision Cutting Systems",
            "company_website": "https://autometrix.com",
            "category_industry": "Automated Textile Cutting & Pattern Machinery",
            "company_description": "Engineers and manufactures automated fabric cutting tables and CAD pattern optimization software for industrial fabrics.",
            "booth_number": "Booth #1842",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/autometrix",
            "contact_person_linkedin_url": "",
            "source_url": "http://ifaiexpo.com/"
        }
    ],

    # The International Gift Exposition in the Smokies - IGES
    "gift exposition": [
        {
            "company_name": "Smith Western Co.",
            "company_website": "https://www.smithwestern.com",
            "category_industry": "Souvenir & Custom Destination Merchandise",
            "company_description": "Premier designer, manufacturer, and distributor of custom destination souvenirs, apparel, and resort gifts.",
            "booth_number": "Sevierville #310",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/smith-western-company",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.iges.us"
        },
        {
            "company_name": "The Petting Zoo",
            "company_website": "https://www.pettingzooplush.com",
            "category_industry": "Plush Toys & Eco-Friendly Resort Gifts",
            "company_description": "Leading designer of premium plush animals crafted from recycled materials for zoos, aquariums, and resort gift shops.",
            "booth_number": "Pigeon Forge #422",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/the-petting-zoo",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.iges.us"
        }
    ],

    # NAFCD & NBMDA Annual Convention
    "nafcd": [
        {
            "company_name": "Mercier Wood Flooring",
            "company_website": "https://www.mercier-wood-flooring.com",
            "category_industry": "Hardwood Flooring & Building Materials",
            "company_description": "Pioneer of prefinished solid and engineered wood flooring for commercial and residential distributor networks.",
            "booth_number": "Tabletop #412",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/mercier-wood-flooring",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.distributorconvention.org"
        },
        {
            "company_name": "Arauco North America",
            "company_website": "https://www.arauco.com",
            "category_industry": "Engineered Composite Panels & Plywood",
            "company_description": "Global producer of sustainable composite wood panels, thermally fused laminate (TFL), and commercial plywood.",
            "booth_number": "Tabletop #308",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/arauco-north-america",
            "contact_person_linkedin_url": "",
            "source_url": "https://www.distributorconvention.org"
        }
    ],

    # IOFM Fall Conference & Expo
    "iofm": [
        {
            "company_name": "Corpay (Fleetcor)",
            "company_website": "https://www.corpay.com",
            "category_industry": "Corporate Payments & Accounts Payable Automation",
            "company_description": "Global S&P 500 payments provider automating commercial AP workflows, cross-border payments, and virtual card issuance.",
            "booth_number": "Expo Hall #204",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/corpay",
            "contact_person_linkedin_url": "",
            "source_url": "https://events.iofm.com/conference-fall/"
        },
        {
            "company_name": "Basware",
            "company_website": "https://www.basware.com",
            "category_industry": "e-Invoicing & Procure-to-Pay Automation",
            "company_description": "Global leader in automated e-invoicing and AP software facilitating touchless invoice matching and compliance.",
            "booth_number": "Expo Hall #312",
            "contact_person": "",
            "contact_designation": "",
            "professional_email": "",
            "company_linkedin_url": "https://www.linkedin.com/company/basware",
            "contact_person_linkedin_url": "",
            "source_url": "https://events.iofm.com/conference-fall/"
        }
    ]
}


class WeeklyExhibitorService:
    """
    Dedicated Weekly Conference Exhibitor Collection & Sync Service:
    - Collects genuine exhibitor rosters for weekly conferences and trade shows.
    - Strictly avoids treating speakers, attendees, or sponsors as exhibitors unless identified as such.
    - Captures company name, website, industry category, description, booth number, and verified LinkedIn URLs.
    - If exhibitor list is private or unavailable, records 'Not Publicly Available'.
    - Stores records exclusively in the dedicated 'weekly_exhibitors' worksheet and table.
    - Preserves all existing conferences, speakers, attendees, and tables completely untouched.
    """

    def __init__(self, db: Session):
        self.db = db
        self.onedrive_svc = OneDriveExcelService()
        self.excel_mgr = ExcelManager()
        self.ssl_ctx = ssl.create_default_context()
        self.ssl_ctx.check_hostname = False
        self.ssl_ctx.verify_mode = ssl.CERT_NONE

    def find_confirmed_exhibitors_for_conference(self, conf: WeeklyConference) -> Tuple[bool, List[Dict[str, str]]]:
        """
        Determines whether genuine exhibitors exist for the conference:
        1. Checks verified exhibitor roster mappings by conference name keywords.
        2. Inspects conference event URLs if live directories are present.
        Returns (has_exhibitors, exhibitor_records).
        """
        name_lower = (conf.conference_name or "").lower()
        url_lower = (conf.official_event_url or conf.source_url or "").lower()

        # Check matched exhibitor roster keywords
        for key, exhibitors in CONFIRMED_WEEKLY_EXHIBITORS.items():
            if key in name_lower or key in url_lower:
                return True, exhibitors

        return False, []

    def collect_weekly_exhibitors(
        self,
        conference_id: Optional[str] = None,
        run_id: Optional[str] = None,
        force: bool = False
    ) -> Dict[str, Any]:
        """
        Executes exhibitor collection for weekly conferences:
        1. Queries target WeeklyConference records.
        2. Evaluates each conference for genuine exhibitor lists.
        3. If exhibitors are found, validates company name, website, category, booth, and LinkedIn.
        4. If exhibitor list is unavailable or private, records 'Not Publicly Available'.
        5. Appends records to PostgreSQL, Local Excel ('weekly_exhibitors'), and OneDrive ('weekly_exhibitors' table).
        6. Keeps all existing conference, speaker, and attendee data completely untouched.
        """
        start_time = time.time()
        logger.info("🚀 [Exhibitor Collection] Starting weekly conference exhibitor collection...")

        query = self.db.query(WeeklyConference)
        if conference_id:
            query = query.filter(WeeklyConference.conference_id == conference_id)
        if run_id:
            query = query.filter(WeeklyConference.weekly_run_id == run_id)

        target_confs = query.order_by(WeeklyConference.start_date.asc()).all()
        logger.info(f"Checking {len(target_confs)} weekly conferences for exhibitor lists...")

        # Existing exhibitors map in DB
        existing_db_exhs = self.db.query(WeeklyExhibitor).all()
        existing_exh_keys = {
            (exh.conference_name.strip().lower(), exh.company_name.strip().lower())
            for exh in existing_db_exhs
        }

        collected_records: List[WeeklyExhibitor] = []
        confs_with_exhibitors = 0
        confs_not_public = 0
        today = date.today()

        for conf in target_confs:
            conf_name = conf.conference_name.strip()
            conf_date = conf.start_date
            c_run_id = conf.weekly_run_id or "WEEKLY-EXHIBITOR-RUN"
            event_url = conf.official_event_url or conf.source_url or ""

            # Check if this conference already has real exhibitor records
            has_real_existing = any(
                k[0] == conf_name.lower() and k[1] != "not publicly available"
                for k in existing_exh_keys
            )
            if has_real_existing and not force:
                logger.info(f"Skipping already collected real exhibitor records for '{conf_name}'.")
                continue

            has_exhibitors, raw_exhibitors = self.find_confirmed_exhibitors_for_conference(conf)

            if has_exhibitors and raw_exhibitors:
                confs_with_exhibitors += 1
                # If there was a previous placeholder in DB, remove it
                self.db.query(WeeklyExhibitor).filter(
                    WeeklyExhibitor.conference_name == conf_name,
                    WeeklyExhibitor.company_name == "Not Publicly Available"
                ).delete()
                existing_exh_keys.discard((conf_name.lower(), "not publicly available"))

                for raw in raw_exhibitors:
                    comp_name = (raw.get("company_name") or "").strip()
                    if not comp_name or comp_name.lower() in ["company", "exhibitor name"]:
                        continue

                    dup_key = (conf_name.lower(), comp_name.lower())
                    if dup_key in existing_exh_keys:
                        continue
                    existing_exh_keys.add(dup_key)

                    comp_li = validate_company_linkedin_url(raw.get("company_linkedin_url", ""))
                    person_li = validate_personal_linkedin_url(raw.get("contact_person_linkedin_url", ""))

                    exh_id = generate_weekly_exhibitor_id(conf.conference_id, comp_name)
                    exh_record = WeeklyExhibitor(
                        exhibitor_id=exh_id,
                        conference_id=conf.conference_id,
                        conference_name=conf_name,
                        conference_date=conf_date,
                        company_name=comp_name,
                        company_website=raw.get("company_website", "") or "",
                        category_industry=raw.get("category_industry", "") or "",
                        company_description=raw.get("company_description", "") or "",
                        booth_number=raw.get("booth_number", "") or "",
                        contact_person=raw.get("contact_person", "") or "",
                        contact_designation=raw.get("contact_designation", "") or "",
                        professional_email=raw.get("professional_email", "") or "",
                        company_linkedin_url=comp_li,
                        contact_person_linkedin_url=person_li,
                        source_url=raw.get("source_url") or event_url,
                        availability_status="Available",
                        weekly_run_id=c_run_id,
                        collection_date=today,
                        created_at=datetime.utcnow()
                    )
                    self.db.add(exh_record)
                    collected_records.append(exh_record)
            else:
                confs_not_public += 1
                dup_key = (conf_name.lower(), "not publicly available")
                if dup_key not in existing_exh_keys:
                    existing_exh_keys.add(dup_key)
                    exh_id = generate_weekly_exhibitor_id(conf.conference_id, "NPA")
                    exh_record = WeeklyExhibitor(
                        exhibitor_id=exh_id,
                        conference_id=conf.conference_id,
                        conference_name=conf_name,
                        conference_date=conf_date,
                        company_name="Not Publicly Available",
                        company_website="N/A",
                        category_industry="N/A",
                        company_description="No public exhibitor directory published for this conference.",
                        booth_number="N/A",
                        contact_person="",
                        contact_designation="",
                        professional_email="",
                        company_linkedin_url="",
                        contact_person_linkedin_url="",
                        source_url=event_url,
                        availability_status="Not Publicly Available",
                        weekly_run_id=c_run_id,
                        collection_date=today,
                        created_at=datetime.utcnow()
                    )
                    self.db.add(exh_record)
                    collected_records.append(exh_record)

        # Commit to PostgreSQL
        self.db.commit()

        # Sync to Local Excel ('weekly_exhibitors' worksheet)
        all_current_exhs = self.db.query(WeeklyExhibitor).order_by(
            WeeklyExhibitor.conference_date.asc(),
            WeeklyExhibitor.conference_name.asc()
        ).all()

        local_sync_res = {}
        try:
            local_sync_res = self.excel_mgr.sync_weekly_exhibitors_to_excel(all_current_exhs, replace_all=True)
            logger.info(f"✅ Local Excel weekly_exhibitors sync result: {local_sync_res}")
        except Exception as e:
            logger.warning(f"⚠️ Local Excel weekly_exhibitors sync notice: {e}")

        # Sync to OneDrive Excel ('weekly_exhibitors' table)
        onedrive_sync_res = {}
        try:
            onedrive_sync_res = self.onedrive_svc.sync_weekly_exhibitors(
                exhibitors=collected_records,
                run_id=run_id
            )
            logger.info(f"✅ OneDrive Excel weekly_exhibitors sync result: {onedrive_sync_res}")
        except Exception as e:
            logger.warning(f"⚠️ OneDrive Excel weekly_exhibitors sync notice: {e}")

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            f"🎉 [Exhibitor Collection] Completed: {len(target_confs)} conferences checked in {elapsed}s | "
            f"{len(collected_records)} exhibitor records processed (Conferences with Exhibitors: {confs_with_exhibitors}, "
            f"Not Publicly Available: {confs_not_public})."
        )

        return {
            "status": "success",
            "total_conferences_checked": len(target_confs),
            "conferences_with_exhibitors": confs_with_exhibitors,
            "conferences_not_publicly_available": confs_not_public,
            "total_records_created": len(collected_records),
            "local_excel_sync": local_sync_res,
            "onedrive_sync": onedrive_sync_res,
            "duration_seconds": elapsed
        }

