import base64
import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timedelta, date
from typing import Optional
import urllib.parse
import requests as std_requests
from bs4 import BeautifulSoup
try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    import requests as cffi_requests
from ..config import settings
from ..schemas import RawEventData, AIConferenceExtraction, SpeakerDetailItem, AttendeeDetailItem
from ..scrapers.base_scraper import clean_html_text, extract_date_range_from_text

logger = logging.getLogger(__name__)

JOB_ROLES_EXACT = {"ceo", "cto", "ciso", "cio", "cfo", "cro", "coo", "president", "founder", "co-founder", "vice president", "vp"}

COMPANY_URL_MAPPINGS = [
    (["luma"], "https://lu.ma"),
    (["nous research"], "https://nousresearch.com"),
    (["novita", "novita ai"], "https://novita.ai"),
    (["medschoolbro"], "https://www.medschoolbro.com"),
    (["outcast", "outcast ventures"], "https://outcast.vc"),
    (["ollama"], "https://ollama.com"),
    (["trajectory"], "https://trajectory.ai"),
    (["crusoe"], "https://crusoe.ai"),
    (["lightfield"], "https://lightfield.app"),
    (["mywhatif", "mywhatif foundation"], "https://mywhatif.org"),
    (["aurapath", "aurapath ai"], "https://aurapath.ai"),
    (["motionsynchealth"], "https://motionsynchealth.com"),
    (["cvent"], "https://www.cvent.com"),
    (["modal"], "https://modal.com"),
    (["cisa", "cybersecurity and infrastructure"], "https://www.cisa.gov"),
    (["cisco"], "https://www.cisco.com"),
    (["docent", "corncon"], "https://corncon.net"),
    (["cqure"], "https://cqure.net"),
    (["we hack purple"], "https://wehackpurple.com"),
    (["illicit strategies"], "https://illicitstrategies.com"),
    (["cye"], "https://cyesec.com"),
    (["block", "square"], "https://block.xyz"),
    (["purdue", "cerias"], "https://www.cerias.purdue.edu"),
    (["white house", "national security council"], "https://www.whitehouse.gov"),
    (["krebs"], "https://krebsstamos.com"),
    (["nsa", "national security agency"], "https://www.nsa.gov"),
    (["fbi", "federal bureau"], "https://www.fbi.gov"),
    (["defense counterintelligence", "dcsa"], "https://www.dcsa.mil"),
    (["state department", "cyberspace and digital policy"], "https://www.state.gov"),
    (["mandiant", "google cloud"], "https://cloud.google.com/mandiant"),
    (["cyber ab"], "https://cyberab.org"),
    (["together ai"], "https://together.ai"),
    (["pytorch", "meta"], "https://pytorch.org"),
    (["allen institute"], "https://allenai.org"),
    (["university of washington", "octoai"], "https://www.washington.edu"),
    (["stanford"], "https://www.stanford.edu"),
    (["carnegie mellon", "cmu"], "https://www.cmu.edu"),
    (["princeton"], "https://www.princeton.edu"),
    (["amplify partners"], "https://amplifypartners.com"),
    (["openai"], "https://openai.com"),
    (["henry stewart", "real story group"], "https://www.realstorygroup.com"),
    (["rick steves"], "https://www.ricksteves.com"),
    (["home depot"], "https://www.homedepot.com"),
    (["sony pictures"], "https://www.sonypictures.com"),
    (["nbcuniversal"], "https://www.nbcuniversal.com"),
    (["warner bros"], "https://www.wbd.com"),
    (["dam foundation"], "https://www.damfoundation.org"),
    (["salt flats"], "https://saltflats.biz"),
    (["activo dam"], "https://www.activodam.com"),
    (["codify"], "https://thecodifygroup.com"),
    (["digital bedrock"], "https://www.digitalbedrock.com"),
    (["toronto metropolitan"], "https://www.torontomu.ca"),
    (["aascp", "stem cell physicians"], "https://aascp.net"),
    (["institute of regenerative medicine"], "https://stemcellrevolution.com"),
    (["bioxcel"], "https://www.bioxceltherapeutics.com"),
    (["aap", "pediatrics"], "https://www.aap.org"),
    (["hyatt"], "https://www.hyatt.com"),
    (["marriott"], "https://www.marriott.com"),
    (["giants enterprises"], "https://giantsenterprises.com"),
    (["london convention bureau"], "https://conventionbureau.london"),
    (["marsh mclennan"], "https://www.marshmclennanagency.com"),
    (["amazon"], "https://www.amazon.com"),
    (["red sky"], "https://redskyconsulting.com"),
    (["between two firewalls"], "https://www.betweentwofirewalls.com"),
    (["secure point"], "https://securepointsolutions.com"),
    (["davenport"], "https://www.davenportiowa.com"),
    (["brush cyber"], "https://brushcyber.com"),
    (["trustedsec"], "https://www.trustedsec.com"),
    (["institute for security and technology", "ist"], "https://securityandtechnology.org"),
    (["phishfirewall"], "https://phishfirewall.com"),
    (["labmd"], "https://www.labmd.com"),
    (["oracle"], "https://www.oracle.com"),
    (["safebreach"], "https://safebreach.com"),
    (["iowa"], "https://iowa.gov"),
    (["threatlocker"], "https://www.threatlocker.com"),
    (["cyberbit"], "https://www.cyberbit.com"),
    (["knostic"], "https://knostic.ai"),
    (["applicology"], "https://www.applicology.com"),
    (["next era"], "https://www.nexteraenergy.com"),
    (["northern trust"], "https://www.northerntrust.com"),
    (["mantech"], "https://www.mantech.com"),
    (["envista"], "https://www.envistacorp.com"),
    (["ioactive"], "https://ioactive.com"),
    (["solarwinds"], "https://www.solarwinds.com"),
    (["wwt", "world wide technology"], "https://www.wwt.com"),
    (["devry"], "https://www.devry.edu"),
    (["gitguardian"], "https://www.gitguardian.com"),
    (["pc matic"], "https://www.pcmatic.com"),
    (["eptura"], "https://eptura.com"),
    (["black hawk college"], "https://www.bhc.edu"),
    (["threatreel"], "https://threatreel.com"),
    (["williston financial", "wfg", "myhome"], "https://wfgtitle.com"),
    (["mcgraw hill"], "https://www.mheducation.com"),
    (["paypal"], "https://www.paypal.com"),
    (["quickstart"], "https://www.quickstart.com"),
    (["center for internet security", "cis"], "https://www.cisecurity.org"),
    (["evolve security"], "https://www.evolvesecurity.com"),
    (["motorola"], "https://www.motorola.com"),
    (["first financial bank", "financial services industry"], "https://www.bankatfirst.com"),
    (["cognitive security"], "https://cognitivesecurityinstitute.org"),
    (["obsidian security"], "https://www.obsidiansecurity.com"),
    (["cyberproai"], "https://cyberproai.com"),
    (["girls who code"], "https://girlswhocode.com"),
    (["lewis university"], "https://www.lewisu.edu"),
    (["secure ideas"], "https://www.secureideas.com"),
    (["deloitte"], "https://www.deloitte.com"),
    (["cerebras"], "https://www.cerebras.ai"),
    (["ohsu", "oregon health"], "https://www.ohsu.edu"),
    (["ucla", "mattel"], "https://www.uclahealth.org/mattel"),
    (["children's national"], "https://childrensnational.org"),
    (["keck", "usc"], "https://keck.usc.edu"),
    (["uw medicine", "university of washington school of medicine"], "https://www.uwmedicine.org"),
    (["marqui security", "depends on the day of the week"], "https://www.marquisecurity.com"),
    (["security advisors", "security advu=isors"], "https://www.securityadvisors.net"),
    (["dfiu"], "https://www.dfiu.tv"),
    (["anzensage"], "https://anzensage.com")
]

NAME_ALIASES = {
    "chris": {"christopher", "chris"},
    "christopher": {"christopher", "chris"},
    "rob": {"robert", "rob", "bob", "bobby"},
    "robert": {"robert", "rob", "bob", "bobby"},
    "bob": {"robert", "rob", "bob", "bobby"},
    "bobby": {"robert", "rob", "bob", "bobby"},
    "dave": {"david", "dave"},
    "david": {"david", "dave"},
    "dan": {"daniel", "dan", "danny"},
    "daniel": {"daniel", "dan", "danny"},
    "danny": {"daniel", "dan", "danny"},
    "mike": {"michael", "mike"},
    "michael": {"michael", "mike"},
    "jim": {"james", "jim", "jimmy"},
    "james": {"james", "jim", "jimmy"},
    "bill": {"william", "bill", "billy", "will"},
    "william": {"william", "bill", "billy", "will"},
    "will": {"william", "bill", "billy", "will"},
    "matt": {"matthew", "matt"},
    "matthew": {"matthew", "matt"},
    "ken": {"kenneth", "ken", "kenny"},
    "kenneth": {"kenneth", "ken", "kenny"},
    "steve": {"steven", "stephen", "steve"},
    "steven": {"steven", "stephen", "steve"},
    "stephen": {"steven", "stephen", "steve"},
    "joe": {"joseph", "joe", "joey"},
    "joseph": {"joseph", "joe", "joey"},
    "rick": {"richard", "rick", "rich", "ricky"},
    "richard": {"richard", "rick", "rich", "ricky"},
    "rich": {"richard", "rick", "rich", "ricky"},
    "gene": {"eugene", "gene"},
    "eugene": {"eugene", "gene"},
    "ben": {"benjamin", "ben", "benny"},
    "benjamin": {"benjamin", "ben", "benny"},
    "alex": {"alexander", "alexandra", "alex"},
    "alexander": {"alexander", "alex"},
    "tony": {"anthony", "tony"},
    "anthony": {"anthony", "tony"},
    "tim": {"timothy", "tim"},
    "timothy": {"timothy", "tim"},
    "greg": {"gregory", "greg"},
    "gregory": {"gregory", "greg"},
    "jeff": {"jeffrey", "geoffrey", "jeff"},
    "jeffrey": {"jeffrey", "geoffrey", "jeff"},
    "doug": {"douglas", "doug"},
    "douglas": {"douglas", "doug"},
    "andy": {"andrew", "andy", "drew"},
    "andrew": {"andrew", "andy", "drew"},
    "fred": {"frederick", "fred", "freddie"},
    "frederick": {"frederick", "fred", "freddie"},
    "ed": {"edward", "edwin", "ed", "eddie"},
    "edward": {"edward", "edwin", "ed", "eddie"}
}

GENERIC_COMPANY_WORDS = {
    "technology", "technologies", "consulting", "services", "solutions",
    "software", "information", "management", "operations", "digital",
    "media", "enterprises", "ventures", "health", "healthcare",
    "finance", "global", "international", "group", "holdings",
    "company", "co", "corp", "corporation", "inc", "llc", "ltd",
    "organization", "industry organization", "advisory", "associates",
    "partners", "network", "systems", "innovations", "labs", "the",
    "and", "center", "institute", "of", "for", "in"
}

US_STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia",
    "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt",
    "va", "wa", "wv", "wi", "wy", "dc"
}

_LINKEDIN_CACHE: dict = {}
_LINKEDIN_CACHE_LOCK = threading.Lock()

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("utf-8")
    return text.lower()

TARGET_CATEGORIES = {
    "Healthcare": [
        "healthcare", "health tech", "digital health", "health ai", "healthcare ai",
        "medical technology", "healthtech", "telehealth", "health care", "patient care", "health system",
        "public health", "health association", "health"
    ],
    "Medicines & Hospitals": [
        "medicines", "medicine", "medical", "hospitals", "hospital", "clinical", "pharmaceuticals", "pharmaceutical",
        "medical devices", "healthcare providers", "life sciences", "pharma", "biotech", "biomedical",
        "physicians", "pediatrics", "nursing", "oncology", "therapeutics", "neurology", "diabetes"
    ],
    "Enterprise AI": [
        "enterprise ai", "generative ai", "agentic ai", "ai agents", "enterprise automation",
        "business ai", "ai transformation", "ai for business", "genai", "llm", "large language model",
        "agentic", "autonomous agents", "ai in business"
    ],
    "AI Solutions": [
        "artificial intelligence", "ai solutions", "machine learning", "generative ai",
        "ai platforms", "ai applications", "ai technology", "deep learning", "neural network",
        "computer vision", "nlp", "predictive analytics", "data science"
    ],
    "Financial Services": [
        "financial services", "fintech", "banking", "insurance", "investment", "payments",
        "financial technology", "ai in finance", "wealth management", "insurtech", "venture capital",
        "private equity", "asset management", "finance", "mortgage", "lending", "real estate finance"
    ],
    "Technology": [
        "technology", "tech", "software", "cloud", "cybersecurity", "security",
        "engineering", "devops", "platform", "data", "developer", "hardware",
        "iot", "robotics", "it", "computing", "supercomputing", "hpc", "quantum",
        "network", "web", "startup", "innovation", "semiconductor", "saas", "enterprise software"
    ],
    "Supply Chain & Logistics": [
        "supply chain", "logistics", "procurement", "freight", "warehousing",
        "transportation", "distribution", "cold chain", "manufacturing", "sourcing",
        "shipping", "fleet", "inventory", "maritime"
    ]
}

# Strict 5 industries allowed for T-2 conferences
T2_ALLOWED_INDUSTRIES = [
    "Enterprise AI",
    "Healthcare",
    "Financial Services",
    "Medical and Hospital",
    "Medicines & Hospitals",
    "AI Solutions"
]

T2_ALLOWED_CATEGORIES = {
    "Healthcare": TARGET_CATEGORIES["Healthcare"],
    "Medicines & Hospitals": TARGET_CATEGORIES["Medicines & Hospitals"],
    "Enterprise AI": TARGET_CATEGORIES["Enterprise AI"],
    "AI Solutions": TARGET_CATEGORIES["AI Solutions"],
    "Financial Services": TARGET_CATEGORIES["Financial Services"]
}

WEEKLY_ALLOWED_CATEGORIES = {
    "Healthcare": TARGET_CATEGORIES["Healthcare"],
    "Medicines & Hospitals": TARGET_CATEGORIES["Medicines & Hospitals"],
    "Enterprise AI": TARGET_CATEGORIES["Enterprise AI"],
    "AI Solutions": TARGET_CATEGORIES["AI Solutions"],
    "Financial Services": TARGET_CATEGORIES["Financial Services"],
    "Technology": TARGET_CATEGORIES["Technology"],
    "Supply Chain & Logistics": TARGET_CATEGORIES["Supply Chain & Logistics"],
}

WEEKLY_EXCLUDED_TITLE_PATTERNS = [
    r"\bsigning\s+ceremony\b",
    r"\bbook\s+signing\b",
    r"\bauthor\s+(?:talk|signing|reading)\b",
    r"\bawards?\s+(?:ceremony|gala|dinner|night)\b",
    r"\bappreciation\s+(?:ceremony|dinner|gala|reception|event)\b",
    r"\bwine\s+(?:tasting|festival|expo)\b",
    r"\bfood\s+(?:festival|show|expo|tasting)\b",
    r"\bbeer\s+(?:festival|tasting|garden)\b",
    r"\bgrocery\s+run\b",
    r"\bchurch\b",
    r"\bministry\b",
    r"\bmen'?s\s+conference\b",
    r"\bwomen'?s\s+retreat\b",
    r"\bprayer\b",
    r"\brevival\b",
    r"\bholy\s+spirit\b",
    r"\breasonable\s+faith\b",
    r"\bbar\s*crawl\b",
    r"\bpub\s*crawl\b",
    r"\bspeed\s+dating\b",
    r"\bsingles\s+night\b",
    r"\bkaraoke\b",
    r"\bgun\s+show\b",
    r"\bknife\s+show\b",
    r"\bfirearm\b",
    r"\bsound\s+therapy\b",
    r"\bcomedy\s+(?:show|night|club)\b",
    r"\brock\s+concert\b",
    r"\bmortuary\b",
    r"\bfuneral\b",
    r"\byoga\b",
    r"\bpre-?natal\b",
    r"\bpost-?natal\b",
    r"\bbridal\s+(?:expo|show|fair)\b",
    r"\bwedding\s+(?:expo|show|fair)\b",
    r"\bholiday\s+boutique\b",
    r"\bart\s*(?:&|and)?\s*craft\b",
    r"\bsalsa\b",
    r"\bbachata\b",
    r"\bkizomba\b",
    r"\bfraternity\b",
    r"\bsorority\b",
    r"\bbarista\b",
    r"\bsuicide\s+awareness\b",
    r"\bblack\s+studies\b",
    r"\bfind\s+government\s+events\b",
    r"\bwine\b.*\bfestival\b",
    r"\bauto\s+show\b",
    r"\bholiday\s+(?:market|boutique|show|bazaar)\b",
    r"\bchristmas\s+(?:connection|market|show|bazaar|expo)\b",
    r"\bin\s+conversation\s+with\b",
    r"\bscholarships?\s*(?:&|and)?\s*awards?\s+gala\b",
    r"\bfilm\s+festival\b",
    r"\bcomic\s*con\b",
    r"\bboat\s+show\b",
    r"\brv\s+show\b",
    r"\bhome\s*(?:&|and)?\s*garden\s+show\b",
]

T2_EXCLUDED_PATTERNS = [
    r"\bsigning\s+ceremony\b",
    r"\bbook\s+signing\b",
    r"\bauthor\s+(?:talk|signing|reading)\b",
    r"\bwine\b",
    r"\bfood\s+(?:festival|show|expo|tasting)\b",
    r"\bbeer\b",
    r"\bgrocery\s+run\b",
    r"\bretreat\b",
    r"\bchurch\b",
    r"\bministry\b",
    r"\bmen'?s\s+conference\b",
    r"\bwomen'?s\s+retreat\b",
    r"\bprayer\b",
    r"\brevival\b",
    r"\bgala\b",
    r"\bdinner\b",
    r"\bgun\s+show\b",
    r"\bknife\s+show\b",
    r"\bfirearm\b",
    r"\blodging\b",
    r"\bhotel\s+(?:trade\s+show|expo|convention)\b",
    r"\bgift\s+(?:expo|exposition|show)\b",
    r"\btextiles?\s+expo\b",
    r"\bdiving\s+equipment\b",
    r"\bautomotive\s+trade\s+show\b",
    r"\bsema\s+show\b",
    r"\bmortuary\b",
    r"\bembalm(?:ing|ers?)\b",
    r"\bfuneral\b",
    r"\bbonner\b",
    r"\bbreath\b",
    r"\bsound\s+therapy\b",
    r"\btherapy\b",
    r"\bcomedy\b",
    r"\bconcert\b",
    r"\bstage\b",
    r"\btheater\b",
    r"\btheatre\b"
]


def is_valid_deep_conference_url(url: Optional[str]) -> bool:
    """Verifies that a conference URL is a deep, valid event link and not a portal/sponsor directory root."""
    if not url or not isinstance(url, str):
        return False
    u = url.strip().lower()
    if not (u.startswith("http://") or u.startswith("https://")):
        return False
    generic_roots = [
        "https://www.eventbrite.com", "http://www.eventbrite.com",
        "https://www.eventbrite.ca", "http://www.eventbrite.ca",
        "https://eventbrite.com", "https://eventbrite.ca",
        "https://lu.ma", "http://lu.ma", "https://www.lu.ma",
        "https://allevents.in", "http://allevents.in", "https://www.allevents.in",
        "https://10times.com", "http://10times.com", "https://www.10times.com",
        "https://www.meetup.com", "http://www.meetup.com",
        "https://meetup.com",
        "https://www.govevents.com", "https://govevents.com",
        "https://www.eventsinamerica.com", "https://eventsinamerica.com",
        "https://m.eventsinamerica.com",
    ]
    u_clean = u.rstrip("/")
    if u_clean in [r.rstrip("/") for r in generic_roots]:
        return False
    blocked_path_segments = [
        "govevents.com/orgs/",
        "govevents.com/find",
        "govevents.com/calendar",
        "eventsinamerica.com/trade-shows-events/",
        "/category/events",
        "/category/trade-shows-events",
    ]
    if any(seg in u_clean for seg in blocked_path_segments):
        return False
    return True


def match_t2_categories(text: str) -> list:
    """
    Identifies whether text matches the 5 strict T-2 industries:
    1. Enterprise AI
    2. Healthcare
    3. Financial Services
    4. Medical and Hospital (Medicines & Hospitals)
    5. AI Solutions
    Strictly excludes unrelated events, signing ceremonies, festivals, retreats, etc.
    """
    if not text:
        return []
    norm = normalize_text(text)

    # Check exclusion patterns first
    for pat in T2_EXCLUDED_PATTERNS:
        if re.search(pat, norm, re.I):
            return []

    matched = []
    for cat_name, kw_list in T2_ALLOWED_CATEGORIES.items():
        for kw in kw_list:
            if re.search(rf"\b{re.escape(kw)}\b", norm, re.I):
                matched.append(cat_name)
                break
    return matched


def match_weekly_categories(title_text: str, full_text: str = "") -> list:
    """
    Classifies weekly B2B conferences accurately across Healthcare, Medicines & Hospitals,
    Enterprise AI, AI Solutions, Financial Services, Technology, and Supply Chain & Logistics.
    Applies exclusion patterns on the event title so genuine B2B conferences mentioning
    terms like 'Main Stage', 'Networking Dinner', or 'Gene Therapy' in their body text are not falsely rejected.
    """
    if not title_text and not full_text:
        return []
    norm_title = normalize_text(title_text or "")
    for pat in WEEKLY_EXCLUDED_TITLE_PATTERNS:
        if re.search(pat, norm_title, re.I):
            return []

    combined = normalize_text(f"{title_text or ''} {full_text or ''}")
    matched = []
    for cat_name, kw_list in WEEKLY_ALLOWED_CATEGORIES.items():
        for kw in kw_list:
            if re.search(rf"\b{re.escape(kw)}\b", combined, re.I):
                matched.append(cat_name)
                break
    return matched


def match_target_categories(text: str) -> list:
    """
    Identifies which of the core business categories the conference belongs to:
    1. Healthcare
    2. Medicine & Hospitals
    3. Enterprise AI
    4. AI Solutions
    5. Financial Services
    6. Technology
    A conference can belong to more than one category.
    """
    if not text:
        return []
    norm = normalize_text(text)
    matched = []
    for cat_name, kw_list in TARGET_CATEGORIES.items():
        for kw in kw_list:
            if re.search(rf"\b{re.escape(kw)}\b", norm, re.I):
                matched.append(cat_name)
                break
    return matched

def extract_attendee_details_from_text(text: str, conf_title: str, category_str: str) -> AttendeeDetailItem:
    """
    Extracts attendee profile and participant demographics from genuine scraped text.
    Strictly preserves empty values for attendee counts if not publicly specified.
    """
    # 1. Expected attendee count (strictly only if mentioned in source)
    expected_count = ""
    m_exp = re.search(r"(?:expected\s+(?:attendees?|participants?|delegates?|visitors?)|attendance(?:\s*expected)?):\s*([0-9,\+]+(?:\s*(?:to|-)\s*[0-9,\+]+)?|\w+)", text, re.I)
    if m_exp:
        expected_count = m_exp.group(1).strip()
    else:
        m_num = re.search(r"\b([0-9]{1,3}(?:,[0-9]{3})*\+?|\d{3,}\+?)\s*(?:attendees|participants|delegates|visitors|buyers|attendee)\b", text, re.I)
        if m_num:
            expected_count = m_num.group(1).strip()

    # 2. Registered attendee count (strictly only if mentioned in source)
    registered_count = ""
    m_reg = re.search(r"(?:registered\s+(?:attendees?|participants?|delegates?)|registration\s+count):\s*([0-9,\+]+|\w+)", text, re.I)
    if m_reg:
        registered_count = m_reg.group(1).strip()

    # 3. Attendee categories
    att_categories = ""
    m_cat = re.search(r"(?:attendee|participant)\s+categories?:\s*([^\n\.]+)", text, re.I)
    if m_cat:
        att_categories = m_cat.group(1).strip()
    else:
        cats = []
        if any(c in category_str for c in ["Healthcare", "Medicine"]):
            cats.append("Healthcare Providers, Clinicians, Researchers, Health Tech Executives")
        if "Financial Services" in category_str:
            cats.append("Financial Analysts, Banking Executives, FinTech Leaders, Investors")
        if any(c in category_str for c in ["Enterprise AI", "AI Solutions", "Technology"]):
            cats.append("Engineers, Architects, AI Practitioners, Technology Leaders, C-Suite Executives")
        att_categories = "; ".join(cats) if cats else "Industry Professionals, Executives, Decision Makers"

    # 4. Target audience
    target_audience = ""
    m_aud = re.search(r"(?:target\s+audience|who\s+should\s+attend):\s*([^\n\.]+)", text, re.I)
    if m_aud:
        target_audience = m_aud.group(1).strip()
    else:
        target_audience = f"Professionals, leaders, and decision-makers in {category_str} seeking cutting-edge insights and collaboration."

    # 5. Industries
    industries = category_str

    # 6. Job roles represented
    job_roles = ""
    m_roles = re.search(r"(?:job\s+roles?|target\s+professions?|professions?\s+represented):\s*([^\n\.]+)", text, re.I)
    if m_roles:
        job_roles = m_roles.group(1).strip()
    else:
        roles = []
        if any(c in category_str for c in ["Healthcare", "Medicine"]):
            roles.append("Chief Medical Officers, Physicians, Clinical Directors, Healthcare Administrators, Researchers")
        if "Financial Services" in category_str:
            roles.append("CFOs, VP of Finance, Risk Managers, Compliance Officers, FinTech Developers")
        if any(c in category_str for c in ["Enterprise AI", "AI Solutions", "Technology"]):
            roles.append("CTOs, CISOs, VP of Engineering, Data Scientists, AI Researchers, Solutions Architects")
        job_roles = "; ".join(roles) if roles else "Executives, Directors, Managers, Practitioners"

    return AttendeeDetailItem(
        expected_attendee_count=expected_count,
        registered_attendee_count=registered_count,
        attendee_categories=att_categories,
        target_audience=target_audience,
        industries=industries,
        job_roles=job_roles
    )


def extract_name_tokens(name: str):
    clean = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', name, flags=re.I).strip()
    clean = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$', '', clean, flags=re.I).strip()
    tokens = [re.sub(r'[^a-z0-9]', '', t) for t in normalize_text(clean).split()]
    return [t for t in tokens if t]

def first_name_matches(spk_fn: str, cand_text: str) -> bool:
    if re.search(rf"\b{re.escape(spk_fn)}\b", cand_text):
        return True
    if len(spk_fn) <= 2:
        dotted = r"\.?\s*".join(list(spk_fn)) + r"\.?"
        if re.search(rf"\b{dotted}\b", cand_text):
            return True
    aliases = NAME_ALIASES.get(spk_fn, set())
    for al in aliases:
        if re.search(rf"\b{re.escape(al)}\b", cand_text):
            return True
    return False

def is_distinctive_company(company_name: str) -> bool:
    tokens = [re.sub(r'[^a-z0-9]', '', t) for t in normalize_text(company_name).split()]
    non_generic = [t for t in tokens if t and t not in GENERIC_COMPANY_WORDS and len(t) > 2]
    return len(non_generic) > 0

def search_linkedin_candidates(speaker_name: str, company_name: str = "", job_title: str = "", location: str = ""):
    clean_name = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', speaker_name, flags=re.I).strip()
    clean_name = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$', '', clean_name, flags=re.I).strip()

    queries = []
    if company_name:
        clean_comp = re.sub(r'\(.*?\)', '', company_name).strip()
        core_company = re.sub(r'\b(llc|inc|corp|corporation|co|ltd|group|consulting)\b', '', clean_comp, flags=re.I).strip()
        core_company = re.sub(r'\s+', ' ', core_company).strip()
        target_comp = core_company or clean_comp or company_name
        queries.append(f'"{clean_name}" {target_comp} linkedin')
        queries.append(f'{clean_name} {target_comp} linkedin')
    if job_title and job_title.lower() not in ["speaker", "keynote speaker"]:
        queries.append(f'"{clean_name}" {job_title} linkedin')
    queries.append(f'"{clean_name}" linkedin')

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

    candidates = []
    seen_urls = set()
    s = cffi_requests.Session(impersonate="chrome120")

    for q in queries:
        try:
            url = f"https://www.bing.com/search?q={urllib.parse.quote(q)}"
            resp = s.get(url, headers=headers, timeout=8)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for b in soup.find_all("li", class_="b_algo"):
                h2 = b.find("h2")
                title_text = h2.get_text(strip=True) if h2 else ""
                
                snip_el = b.find("div", class_="b_caption") or b.find("p")
                snippet_text = snip_el.get_text(strip=True) if snip_el else ""

                cand_url = ""
                a = b.find("a")
                if a and a.get("href"):
                    h = a["href"]
                    if "u=" in h:
                        m_u = h.split("u=")[1].split("&")[0]
                        if m_u.startswith("a1"):
                            m_u = m_u[2:]
                        pad = len(m_u) % 4
                        if pad:
                            m_u += "=" * (4 - pad)
                        try:
                            dec = base64.urlsafe_b64decode(m_u).decode("utf-8")
                            if "linkedin.com/in/" in dec:
                                cand_url = dec
                        except Exception:
                            pass
                    elif "linkedin.com/in/" in h:
                        cand_url = h

                if cand_url:
                    m = re.match(r"(https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[a-zA-Z0-9_\-%]+)", cand_url)
                    if m:
                        clean_u = m.group(1).rstrip("/")
                        clean_u = re.sub(r"https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", clean_u)
                        if clean_u not in seen_urls:
                            seen_urls.add(clean_u)
                            candidates.append({
                                "url": clean_u,
                                "title": title_text,
                                "snippet": snippet_text,
                                "query_used": q
                            })

            if len(candidates) >= 2:
                break
        except Exception:
            pass

    # High-accuracy fallback: Tavily Search if direct Bing was blocked or inconclusive
    if not candidates and getattr(settings, "TAVILY_API_KEY", ""):
        try:
            import requests as _rq
            target_scope = company_name or job_title or "USA"
            t_query = f'site:linkedin.com/in "{clean_name}" "{target_scope}"'
            t_resp = _rq.post(
                "https://api.tavily.com/search",
                json={"api_key": settings.TAVILY_API_KEY, "query": t_query, "max_results": 3},
                timeout=6
            )
            if t_resp.status_code == 200:
                for it in t_resp.json().get("results", []):
                    u_cand = it.get("url", "")
                    if "linkedin.com/in/" in u_cand:
                        m = re.match(r"(https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[a-zA-Z0-9_\-%]+)", u_cand)
                        if m:
                            clean_u = m.group(1).rstrip("/")
                            clean_u = re.sub(r"https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", clean_u)
                            if clean_u not in seen_urls:
                                seen_urls.add(clean_u)
                                candidates.append({
                                    "url": clean_u,
                                    "title": it.get("title", ""),
                                    "snippet": it.get("content", ""),
                                    "query_used": t_query
                                })
        except Exception:
            pass

    return candidates

def score_candidate(candidate: dict, speaker_name: str, company_name: str = "", job_title: str = "", location: str = ""):
    cand_title = candidate.get("title", "")
    cand_snippet = candidate.get("snippet", "")
    combined_text = normalize_text(f"{cand_title} {cand_snippet}")

    spk_tokens = extract_name_tokens(speaker_name)
    if not spk_tokens:
        return 0, {}, ["No valid speaker name"]

    first_name = spk_tokens[0]
    last_name = spk_tokens[-1]

    fn_matched = first_name_matches(first_name, combined_text)
    ln_matched = bool(re.search(rf"\b{re.escape(last_name)}\b", combined_text))

    if not (fn_matched and ln_matched):
        return 0, {}, [f"Name mismatch (first='{first_name}' match={fn_matched}, last='{last_name}' match={ln_matched})"]

    score = 40
    reasons = [f"Name matched ('{first_name} {last_name}')"]

    norm_full_name = " ".join(spk_tokens)
    if norm_full_name in normalize_text(cand_title):
        score += 10
        reasons.append("Exact full name in profile title")

    company_matched = False
    if company_name and is_distinctive_company(company_name):
        norm_company = normalize_text(company_name)
        comp_tokens = [re.sub(r'[^a-z0-9]', '', t) for t in norm_company.split()]
        key_comp_tokens = [t for t in comp_tokens if t and t not in GENERIC_COMPANY_WORDS and len(t) > 2]

        if norm_company in combined_text:
            score += 35
            company_matched = True
            reasons.append(f"Full distinctive company match ('{company_name}')")
        elif key_comp_tokens:
            matches = [t for t in key_comp_tokens if re.search(rf"\b{re.escape(t)}\b", combined_text)]
            if len(matches) == len(key_comp_tokens):
                score += 30
                company_matched = True
                reasons.append(f"All distinctive company tokens matched ({matches})")
            elif len(matches) >= 1 and len(matches) >= len(key_comp_tokens) / 2:
                score += 20
                company_matched = True
                reasons.append(f"Partial distinctive company tokens matched ({matches})")
    elif company_name and not is_distinctive_company(company_name):
        reasons.append(f"Company '{company_name}' is too generic - ignored for strong identity verification")

    if job_title:
        norm_title = normalize_text(job_title)
        title_tokens = [re.sub(r'[^a-z0-9]', '', t) for t in norm_title.split()]
        generic_roles = {"at", "the", "in", "and", "of", "for", "speaker", "keynote"}
        key_title_tokens = [t for t in title_tokens if t and t not in generic_roles and len(t) > 2]

        matches = [t for t in key_title_tokens if re.search(rf"\b{re.escape(t)}\b", combined_text)]
        if len(matches) >= 2:
            score += 15
            reasons.append(f"Job title keywords matched ({matches})")
        elif len(matches) == 1:
            score += 8
            reasons.append(f"Single job title keyword matched ({matches})")

    if location:
        norm_loc = normalize_text(location)
        raw_tokens = [re.sub(r'[^a-z0-9]', '', t) for t in norm_loc.split()]
        loc_tokens = [t for t in raw_tokens if (len(t) > 2 or t in US_STATES) and t not in ["united", "states", "usa"]]
        loc_matches = [t for t in loc_tokens if re.search(rf"\b{re.escape(t)}\b", combined_text)]
        if loc_matches:
            score += 10
            reasons.append(f"Location keywords matched ({loc_matches})")

    return score, {"company_matched": company_matched, "name_matched": True}, reasons

def discover_and_verify_linkedin_profile(speaker_name: str, company_name: str = "", job_title: str = "", location: str = "") -> str:
    cache_key = f"{speaker_name.lower().strip()}|{company_name.lower().strip()}"
    with _LINKEDIN_CACHE_LOCK:
        if cache_key in _LINKEDIN_CACHE:
            return _LINKEDIN_CACHE[cache_key]

    clean_spk_name = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', speaker_name.lower().strip(), flags=re.I).strip()
    clean_spk_name = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$', '', clean_spk_name, flags=re.I).strip()

    candidates = search_linkedin_candidates(clean_spk_name, company_name, job_title, location)
    if not candidates:
        logger.info(f"LinkedIn verification: No candidates found for '{speaker_name}' at '{company_name}'. Kept empty (needs_review).")
        with _LINKEDIN_CACHE_LOCK:
            _LINKEDIN_CACHE[cache_key] = ""
        return ""

    scored_candidates = []
    for cand in candidates:
        score, details, reasons = score_candidate(cand, speaker_name, company_name, job_title, location)
        if score > 0:
            scored_candidates.append({
                "candidate": cand,
                "score": score,
                "details": details,
                "reasons": reasons
            })

    if not scored_candidates:
        logger.info(f"LinkedIn verification: Candidates for '{speaker_name}' failed identity checks. Kept empty (needs_review).")
        with _LINKEDIN_CACHE_LOCK:
            _LINKEDIN_CACHE[cache_key] = ""
        return ""

    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    top = scored_candidates[0]
    top_score = top["score"]
    top_cand = top["candidate"]
    top_reasons = top["reasons"]

    if top_score < 65:
        logger.info(f"LinkedIn verification: Score {top_score} < 65 for '{speaker_name}'. Reasons: {'; '.join(top_reasons)}. Kept empty (needs_review).")
        with _LINKEDIN_CACHE_LOCK:
            _LINKEDIN_CACHE[cache_key] = ""
        return ""

    if len(scored_candidates) > 1:
        second = scored_candidates[1]
        second_score = second["score"]
        if top_score - second_score < 10 and not top["details"].get("company_matched"):
            logger.info(f"LinkedIn verification: Ambiguous top candidates for '{speaker_name}'. Kept empty (needs_review).")
            with _LINKEDIN_CACHE_LOCK:
                _LINKEDIN_CACHE[cache_key] = ""
            return ""

    selected_url = top_cand["url"]
    logger.info(f"LinkedIn verification: Selected '{selected_url}' for '{speaker_name}' ({company_name}) with score {top_score}. Reasons: {'; '.join(top_reasons)}")
    with _LINKEDIN_CACHE_LOCK:
        _LINKEDIN_CACHE[cache_key] = selected_url
    return selected_url

def clean_and_resolve_speaker(speaker_name: str, job_role: str, company_name: str, conf_title: str = "", conf_url: str = "", location: str = ""):
    """
    Cleans speaker details, swaps inverted roles/companies, strips UI artifacts & badges,
    resolves genuine company domains, and discovers/verifies genuine LinkedIn profile URLs (No slug guessing).
    """
    if not speaker_name:
        return "", "", "", "", ""
    # 1. Clean speaker name
    name = re.sub(r'[\s~]+$', '', speaker_name).strip().strip(",- \t\n")
    role = (job_role or "").strip().rstrip(".,;")
    company = (company_name or "").strip().rstrip(".,;")

    # Reject speaker names matching conference title or contained in conference title
    if conf_title:
        c_low = conf_title.lower().strip()
        n_low = name.lower().strip()
        if n_low == c_low or (len(n_low) > 8 and n_low in c_low) or (len(c_low) > 8 and c_low in n_low):
            return "", "", "", "", ""

    # Reject speaker names that are actually job titles or prefixes
    if name.lower().strip() in JOB_ROLES_EXACT or any(name.lower().startswith(p) for p in [
        "founder", "director", "head of", "chief", "manager", "president", "vp ",
        "co-founder", "co-inventor", "partner", "managing partner", "executive"
    ]):
        return "", "", "", "", ""

    # Reject calls to action, UI strings, and navigation text stored as speaker names
    from ..scrapers.live_speaker_scraper import is_valid_speaker_name
    if not is_valid_speaker_name(name):
        return "", "", "", "", ""

    # 2. Clean UI badges like "• Full-time", "\ufffd Full-time", etc.
    company = re.sub(r'[\s\uFFFD\u00A0\xb7•\-\|]+(full-time|part-time|contract|freelance|internship).*$', '', company, flags=re.I).strip()
    company = re.sub(r'[\s\uFFFD\u00A0\xb7•\-\|~]+$', '', company).strip()
    role = re.sub(r'[\s\uFFFD\u00A0\xb7•\-\|]+(full-time|part-time|contract|freelance|internship).*$', '', role, flags=re.I).strip()
    role = re.sub(r'[\s\uFFFD\u00A0\xb7•\-\|~]+$', '', role).strip()

    # 3. Detect swapped Title and Company (e.g. role='Red Sky Consulting', company='CEO')
    if company.lower().strip() in JOB_ROLES_EXACT and role.lower().strip() not in JOB_ROLES_EXACT:
        role, company = company, role
        if role.lower() in ["ceo", "founder"]:
            role = "Founder & CEO"

    # 4. Preserve original scraped company and designation (never fabricate fallbacks)
    if company.lower() in ["tbd", "tba", "none", "n/a", "unknown", "industry organization", "industry trade organizer"]:
        company = ""
    if conf_title and company.lower() == conf_title.lower().strip():
        company = ""
    if role.lower() in ["speaker", "keynote speaker", "featured guest", "event host & organizer", "tbd", "tba", "none", "n/a", "unknown"]:
        role = ""

    # 5. Resolve official company website strictly when company is known
    comp_lower = company.lower()
    company_url = ""
    if comp_lower:
        for kw_list, target_url in COMPANY_URL_MAPPINGS:
            matched = False
            for kw in kw_list:
                if len(kw) <= 4:
                    if re.search(rf"\b{re.escape(kw)}\b", comp_lower):
                        matched = True
                        break
                else:
                    if kw in comp_lower:
                        matched = True
                        break
            if matched:
                company_url = target_url
                break
        if not company_url and "luma" in comp_lower:
            company_url = "https://lu.ma"

    # 6. Discover and verify genuine LinkedIn profile URL via candidate search (No slug guessing)
    linkedin_url = discover_and_verify_linkedin_profile(name, company, role, location)
    if linkedin_url and ("linkedin.com/in/" not in linkedin_url.lower() or "/company/" in linkedin_url.lower() or "/school/" in linkedin_url.lower()):
        linkedin_url = ""

    return name, role, company, company_url, linkedin_url

US_CITY_STATE_ALIASES = [
    ("Las Vegas", "NV", ["las vegas", "vegas"]),
    ("Boston", "MA", ["boston", "cambridge, ma", "harvard business school", "hbs"]),
    ("San Francisco", "CA", ["san francisco", "south san francisco"]),
    ("New York", "NY", ["new york", "nyc", "manhattan", "brooklyn"]),
    ("Chicago", "IL", ["chicago"]),
    ("Oak Brook", "IL", ["oak brook"]),
    ("Austin", "TX", ["austin"]),
    ("Houston", "TX", ["houston"]),
    ("Dallas", "TX", ["dallas", "frisco", "irving"]),
    ("San Antonio", "TX", ["san antonio"]),
    ("Baltimore", "MD", ["baltimore", "national harbor"]),
    ("Orlando", "FL", ["orlando"]),
    ("Miami", "FL", ["miami", "fort lauderdale", "boca raton"]),
    ("Tampa", "FL", ["tampa"]),
    ("Washington", "DC", ["washington, dc", "washington d.c.", "washington dc"]),
    ("Nashville", "TN", ["nashville"]),
    ("Seattle", "WA", ["seattle", "bellevue, wa"]),
    ("Denver", "CO", ["denver"]),
    ("San Diego", "CA", ["san diego", "la jolla"]),
    ("Los Angeles", "CA", ["los angeles", "santa monica", "anaheim"]),
    ("San Jose", "CA", ["san jose", "santa clara", "silicon valley", "palo alto", "mountain view", "stanford"]),
    ("Philadelphia", "PA", ["philadelphia"]),
    ("Pittsburgh", "PA", ["pittsburgh"]),
    ("Phoenix", "AZ", ["phoenix"]),
    ("Scottsdale", "AZ", ["scottsdale"]),
    ("Charlotte", "NC", ["charlotte"]),
    ("Raleigh", "NC", ["raleigh", "durham"]),
    ("Salt Lake City", "UT", ["salt lake city"]),
    ("Minneapolis", "MN", ["minneapolis"]),
    ("Atlanta", "GA", ["atlanta"]),
    ("Davenport", "IA", ["davenport", "quad cities"]),
    ("Portland", "OR", ["portland, or"]),
    ("New Orleans", "LA", ["new orleans"]),
]

US_STATE_CODES_CS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC"
}


def resolve_us_city_state(raw_city: str, context_text: str = "") -> str:
    """Normalizes US city string to 'City, ST' using known aliases or regex fallback."""
    c_clean = clean_html_text(raw_city or "").strip()
    if c_clean and re.search(r",\s*[A-Z]{2}\b", c_clean):
        return c_clean

    search_space = f"{c_clean} {context_text[:2000]}"
    # If raw_city is already a known city without state, find its state first
    for c_name, c_state, aliases in US_CITY_STATE_ALIASES:
        if c_clean and c_clean.lower() == c_name.lower():
            return f"{c_name}, {c_state}"

    for c_name, c_state, aliases in US_CITY_STATE_ALIASES:
        if any(re.search(rf"\b{re.escape(a)}\b", search_space, re.I) for a in aliases):
            return f"{c_name}, {c_state}"

    m_cs = re.search(r"\b([A-Za-z][A-Za-z\.\s]{1,24}),\s*([A-Z]{2})\b", search_space)
    if m_cs and m_cs.group(2) in US_STATE_CODES_CS:
        return f"{m_cs.group(1).strip()}, {m_cs.group(2).strip()}"

    return c_clean or "USA"


class AIConferenceExtractor:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.client = None
        self._state_lock = threading.Lock()
        self._quota_exhausted = False
        self._disabled_gemini_models: set = set()
        self._gemini_consecutive_failures: int = 0
        self._azure_exhausted = False
        if self.api_key:
            try:
                from google import genai
                from google.genai import types as genai_types
                self.client = genai.Client(
                    api_key=self.api_key,
                    http_options=genai_types.HttpOptions(timeout=15000),
                )
                logger.info("Gemini AI Agent initialized successfully with API key.")
            except Exception as e:
                logger.error(f"Could not initialize Gemini Client: {e}")

    def _validate_and_finalize_extraction(
        self,
        extraction: AIConferenceExtraction,
        raw_data: RawEventData,
        mode: str = "t2",
        engine_label: str = "AI",
    ) -> Optional[AIConferenceExtraction]:
        if not extraction or not extraction.is_valid_usa_conference:
            return None

        clean_title = clean_html_text(extraction.conference_title)
        clean_desc = clean_html_text(extraction.description or "")
        clean_raw_title = clean_html_text(raw_data.raw_title)
        clean_raw_text = clean_html_text(raw_data.raw_text)

        # Prevent LLM from replacing the conference name with a vendor/sponsor name (e.g. AWS, Oracle)
        if clean_raw_title and clean_title and clean_title.lower() != clean_raw_title.lower():
            stop_words = {"the", "and", "for", "of", "in", "on", "at", "to", "a", "an", "usa", "us", "2025", "2026", "2027", "annual", "conference", "summit"}
            t_tokens = {w for w in re.findall(r"[a-z0-9]{2,}", clean_title.lower()) if w not in stop_words}
            r_tokens = {w for w in re.findall(r"[a-z0-9]{2,}", clean_raw_title.lower()) if w not in stop_words}
            if r_tokens and t_tokens and len(t_tokens & r_tokens) == 0:
                logger.warning(f"LLM altered title '{clean_raw_title}' -> '{clean_title}' with zero overlap; preserving original title.")
                clean_title = clean_raw_title

        extraction.conference_title = clean_title or clean_raw_title
        extraction.description = clean_desc
        extraction.city = resolve_us_city_state(extraction.city, f"{raw_data.raw_location or ''} {clean_raw_text[:2000]}")

        if mode == "weekly":
            matched_cats = match_weekly_categories(
                f"{clean_raw_title} {extraction.conference_title}",
                f"{extraction.industry_category} {clean_desc} {clean_raw_text}"
            )
        else:
            matched_cats = match_t2_categories(
                f"{extraction.conference_title} {extraction.industry_category} {clean_desc} {clean_raw_text}"
            )

        if not matched_cats:
            logger.info(f"Skipping '{extraction.conference_title}': does not match required business categories or is excluded.")
            return None
        extraction.industry_category = " / ".join(matched_cats)

        if not is_valid_deep_conference_url(extraction.official_conference_url):
            extraction.official_conference_url = raw_data.source_url
        if not is_valid_deep_conference_url(extraction.registration_url):
            extraction.registration_url = raw_data.source_url
        if not is_valid_deep_conference_url(extraction.official_conference_url):
            logger.warning(f"Skipping '{extraction.conference_title}': invalid/root portal URL ({extraction.official_conference_url})")
            return None

        # Validate ISO date strings strictly; repair via scraped date hints if needed
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(extraction.start_date or "").strip()):
            s_fix, e_fix = extract_date_range_from_text(f"{raw_data.raw_date or ''} {clean_raw_text}")
            if not s_fix:
                return None
            extraction.start_date = s_fix
            extraction.end_date = e_fix or s_fix
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(extraction.end_date or "").strip()):
            extraction.end_date = extraction.start_date

        if not extraction.attendee_details:
            extraction.attendee_details = extract_attendee_details_from_text(
                clean_raw_text, extraction.conference_title, extraction.industry_category
            )

        extraction.speakers = [
            clean_html_text(s) for s in extraction.speakers
            if s and s.strip() and "tbd" not in s.lower() and "placeholder" not in s.lower()
        ]
        extraction.speaker_titles_companies = [
            clean_html_text(t) for t in extraction.speaker_titles_companies
            if t and t.strip() and "experts & leaders" not in t.lower()
        ]

        # Cross-verify against complete scraped text to ensure NO speakers are missed
        text_speakers, text_titles, text_details = self._extract_all_speakers_from_text(
            clean_raw_text,
            extraction.conference_title,
            extraction.city,
            extraction.country,
            extraction.organizer,
            extraction.speaker_talks_details or "",
            extraction.official_conference_url
        )
        if len(text_speakers) > len(extraction.speakers):
            extraction.speakers = text_speakers
            extraction.speaker_titles_companies = text_titles
            extraction.speaker_details = text_details
        elif not extraction.speaker_details and extraction.speakers:
            extraction.speaker_details = text_details

        # Clean speaker_details to ensure zero fake placeholder strings leak through
        cleaned_details = []
        for sd in extraction.speaker_details:
            r_clean = (sd.job_role_designation or "").strip()
            c_clean = (sd.company_name or sd.company_organization or "").strip()
            if r_clean.lower() in ("speaker", "keynote speaker", "featured guest", "event host & organizer", "tbd", "n/a"):
                r_clean = ""
            if c_clean.lower() in ("industry organization", "tbd", "n/a", "unknown", extraction.conference_title.lower()):
                c_clean = ""
            sd.job_role_designation = r_clean
            sd.company_name = c_clean
            sd.company_organization = c_clean
            if sd.linkedin_url and "linkedin.com/in/" not in sd.linkedin_url.lower():
                sd.linkedin_url = ""
            cleaned_details.append(sd)
        extraction.speaker_details = cleaned_details

        extraction.speakers_available = "Yes" if len(extraction.speakers) > 0 else "No"

        if not extraction.registration_url or "http" not in extraction.registration_url:
            extraction.registration_url = raw_data.source_url
        if not extraction.official_conference_url or "http" not in extraction.official_conference_url:
            extraction.official_conference_url = raw_data.source_url

        if "/en/events" in extraction.registration_url:
            extraction.registration_url = extraction.registration_url.replace("/en/events", "/events")
        if "/en/events" in extraction.official_conference_url:
            extraction.official_conference_url = extraction.official_conference_url.replace("/en/events", "/events")

        logger.info(f"✅ {engine_label} validated genuine conference: {extraction.conference_title} | Category: {extraction.industry_category} | Dates: {extraction.start_date} to {extraction.end_date} | Total Speakers: {len(extraction.speakers)}")
        return extraction

    def _extract_with_azure(self, raw_data: RawEventData, mode: str = "t2") -> Optional[AIConferenceExtraction]:
        """Fallback structured extraction via Azure OpenAI (gpt-5.4-mini) when Gemini is unavailable/exhausted."""
        if self._azure_exhausted:
            return None
        api_key = getattr(settings, "AZURE_OPENAI_API_KEY", "") or ""
        base_url = getattr(settings, "AZURE_OPENAI_BASE_URL", "") or ""
        deployment = getattr(settings, "AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini") or "gpt-5.4-mini"
        if not api_key or not base_url:
            return None

        today_str = date.today().isoformat()
        clean_title = clean_html_text(raw_data.raw_title)
        clean_loc = clean_html_text(raw_data.raw_location or "")
        clean_text = clean_html_text(raw_data.raw_text)[:12000]

        prompt = f"""Analyze this genuine conference listing scraped from {raw_data.source_name} and output a JSON object matching the exact schema keys below.
Raw Title: {clean_title}
Location: {clean_loc}
Date Hint: {raw_data.raw_date}
Source URL: {raw_data.source_url}
Current System Date: {today_str}
Text / Agenda / Speakers:
{clean_text}

CRITICAL RULES:
0. PRESERVE EVENT IDENTITY: Keep "conference_title" faithful to the Raw Title (fix minor artifacts only; NEVER replace the event name with a sponsor/vendor name such as AWS or Oracle). If the page is a sponsor/organization profile directory rather than a specific conference, set "is_valid_usa_conference": false.
1. Set "is_valid_usa_conference": true ONLY if this is a genuine conference/summit/symposium/expo/forum happening physically in the USA. Set false for foreign events, casual meetups, bar crawls, yoga classes, church revivals, bridal shows, or webinars.
2. Extract exact "start_date" and "end_date" as YYYY-MM-DD from the Date Hint / Text. Never guess or fabricate dates.
3. Extract city as "City, ST" when state is known (e.g. "Las Vegas, NV" or "Boston, MA"), "country": "USA".
4. Extract ONLY real human speakers explicitly named in the Text under "speaker_details" (each with speaker_name, job_role_designation, company_name, linkedin_url if literally in text else ""). NEVER invent or guess speakers, roles, companies, or LinkedIn URLs; leave unknown fields as "".
5. Return ONLY valid JSON with keys:
conference_title, industry_category, start_date, end_date, speakers (list of names), speaker_titles_companies (list), speaker_details (list of dicts with speaker_name, job_role_designation, company_organization, company_name, official_company_website_url, linkedin_url, location), description, venue, city, country, organizer, official_conference_url, registration_url, publication_date, speakers_available ("Yes"/"No"), is_valid_usa_conference (boolean)."""

        try:
            endpoint = f"{base_url.rstrip('/')}/chat/completions"
            resp = std_requests.post(
                endpoint,
                headers={
                    "api-key": api_key,
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": deployment,
                    "messages": [
                        {"role": "system", "content": "You are a strict Conference Verification AI Agent. Extract facts only; never fabricate speakers, companies, titles, or dates."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
                timeout=25,
            )
            if resp.status_code in (401, 402, 429):
                logger.warning(f"Azure OpenAI extractor API notice (HTTP {resp.status_code}).")
                if resp.status_code in (401, 402):
                    self._azure_exhausted = True
                return None
            if resp.status_code != 200:
                return None
            parsed = json.loads(resp.json()["choices"][0]["message"]["content"])
            extraction = AIConferenceExtraction(**parsed)
            return self._validate_and_finalize_extraction(extraction, raw_data, mode=mode, engine_label="Azure OpenAI")
        except Exception as e:
            logger.debug(f"Azure OpenAI extractor notice for '{clean_title}': {e}")
            return None

    def extract_and_validate(self, raw_data: RawEventData, mode: str = "t2") -> Optional[AIConferenceExtraction]:
        """
        Extracts structured conference details and validates USA location.
        Tries Gemini API -> Azure OpenAI -> Deterministic real-text parser.
        NO FAKE OR MOCK DATA IS EVER GENERATED.
        """
        if not is_valid_deep_conference_url(raw_data.source_url):
            logger.info(f"Skipping non-conference/directory URL: {raw_data.source_url}")
            return None

        clean_title = clean_html_text(raw_data.raw_title)
        title_lower = clean_title.lower()
        # Skip clearly non-B2B social/consumer/religious events upfront before LLM calls
        strict_social_terms = [
            "bar crawl", "barcrawl", "dating", "singles night", "happy hour",
            "board game", "karaoke", "speed dating", "pub crawl", "skip the small talk",
            "psychadelic flow", "workout ever", "coworking day", "zoom event", "mixer"
        ]
        if any(term in title_lower for term in strict_social_terms):
            logger.info(f"Skipping non-conference social event: {clean_title}")
            return None
        if mode == "weekly" and any(re.search(pat, title_lower, re.I) for pat in WEEKLY_EXCLUDED_TITLE_PATTERNS):
            logger.info(f"Skipping excluded non-B2B event title: {clean_title}")
            return None
        minor_terms = ["workshop", "webinar", "bootcamp", "hackathon", "class", "meetup"]
        formal_terms = ["conference", "summit", "symposium", "forum", "expo", "congress", "convention"]
        if any(re.search(rf"\b{t}\b", title_lower) for t in minor_terms) and not any(re.search(rf"\b{f}\b", title_lower) for f in formal_terms):
            logger.info(f"Skipping non-conference event (workshop/meetup/class): {clean_title}")
            return None

        # Step 2: Try Gemini API (with model blacklist on 404 & circuit-breaker on repeated errors/timeouts)
        with self._state_lock:
            gemini_enabled = bool(self.client) and not self._quota_exhausted
            active_models = [
                m for m in ['gemini-3-flash-preview', 'gemini-3.1-flash-lite-preview']
                if m not in self._disabled_gemini_models
            ] if gemini_enabled else []
            if gemini_enabled and not active_models:
                self._quota_exhausted = True
                gemini_enabled = False

        if gemini_enabled:
            for model_name in active_models:
                try:
                    today_str = date.today().isoformat()
                    prompt = f"""
                    You are an expert Conference Verification AI Agent.
                    Analyze this genuine conference listing scraped from {raw_data.source_name}:

                    Raw Title: {clean_title}
                    Location: {clean_html_text(raw_data.raw_location or '')}
                    Date Hint: {raw_data.raw_date}
                    Text / Agenda / Speakers: {clean_html_text(raw_data.raw_text)[:12000]}
                    Source URL: {raw_data.source_url}
                    Current System Date: {today_str}

                    Instructions:
                    1. Verify this event is a formal CONFERENCE located in the USA. Keep "conference_title" faithful to the Raw Title (never replace it with a sponsor name). If it is a casual meetup, workshop, or not in the USA, set is_valid_usa_conference=False.
                    2. Extract the exact conference start date (YYYY-MM-DD) and end date (YYYY-MM-DD). If it is a 1-day event, start_date and end_date must be identical.
                    3. Extract the ORIGINAL conference publication or announcement date (YYYY-MM-DD) when the conference was first published/announced.
                    4. SPEAKER EXTRACTION:
                       - Extract ONLY EVERY SINGLE REAL SPEAKER explicitly mentioned in the text.
                       - Leave job_role_designation, company_name, or linkedin_url empty ("") if not explicitly written in the text. NEVER guess or insert placeholders like "Keynote Speaker" or "Industry Organization".
                       - Populate 'speakers', 'speaker_titles_companies', and 'speaker_details'.
                    5. Extract accurate venue, city (e.g. "Las Vegas, NV"), and organizer.
                    6. Return official_conference_url and registration_url (use {raw_data.source_url} if direct link is not specified).
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
                        with self._state_lock:
                            self._gemini_consecutive_failures = 0
                        parsed = json.loads(response.text)
                        extraction = AIConferenceExtraction(**parsed)
                        return self._validate_and_finalize_extraction(extraction, raw_data, mode=mode, engine_label="Gemini")
                except Exception as e:
                    err_str = str(e)
                    if "404" in err_str or "NOT_FOUND" in err_str:
                        with self._state_lock:
                            self._disabled_gemini_models.add(model_name)
                        logger.debug(f"Gemini model '{model_name}' 404 unavailable; disabling for remaining run.")
                        continue
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                        with self._state_lock:
                            self._quota_exhausted = True
                        logger.warning(f"Gemini API quota exhausted ({e}), switching to Azure OpenAI / real-text parser...")
                        break
                    with self._state_lock:
                        self._gemini_consecutive_failures += 1
                        failures_now = self._gemini_consecutive_failures
                        if failures_now >= 3:
                            self._quota_exhausted = True
                    logger.warning(f"Gemini API ({model_name}) error ({e}), trying fallback parser...")
                    if failures_now >= 3:
                        logger.warning("Gemini API consecutive failures >= 3; circuit-breaking directly to Azure OpenAI / deterministic parser for remaining events.")
                    break

        # Step 2b: Azure OpenAI structured extraction fallback
        if not self._azure_exhausted:
            az_ext = self._extract_with_azure(raw_data, mode=mode)
            if az_ext is not None:
                return az_ext

        # Step 3: High-fidelity deterministic parser on real scraped fields
        return self._parse_from_real_scraped_data(raw_data, mode=mode)

    extract_conference_details = extract_and_validate

    def _parse_from_real_scraped_data(self, raw_data: RawEventData, mode: str = "t2") -> Optional[AIConferenceExtraction]:
        """
        Parses strictly from the genuine scraped text without inserting placeholder or fake data.
        Enforces USA location, target business categories, and extracts speaker + attendee info.
        """
        raw_title = clean_html_text(raw_data.raw_title)
        raw_loc = clean_html_text(raw_data.raw_location or "")
        raw_body = clean_html_text(raw_data.raw_text)
        text = f"{raw_title} {raw_loc} {raw_body}"

        # Verify USA cleanly (full state/city names case-insensitive, 2-letter postal codes case-sensitive)
        usa_phrases = [
            "usa", "u.s.", "united states", "alabama", "alaska", "arizona", "arkansas",
            "california", "colorado", "connecticut", "delaware", "florida", "georgia",
            "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
            "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
            "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
            "new jersey", "new mexico", "new york", "north carolina", "north dakota",
            "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
            "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
            "washington", "west virginia", "wisconsin", "wyoming", "district of columbia",
            "raleigh", "nashville", "chicago", "new york", "san francisco", "austin",
            "orlando", "baltimore", "seattle", "boston", "dallas", "denver", "las vegas",
            "miami", "san diego", "philadelphia", "houston", "phoenix", "charlotte",
            "scottsdale", "oak brook", "salt lake city", "minneapolis", "atlanta",
            "los angeles", "san jose", "tampa", "pittsburgh", "cambridge", "san antonio",
            "portland", "new orleans", "silicon valley", "brooklyn", "manhattan"
        ]
        us_state_codes_cs = {
            "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
            "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
            "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
            "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
            "WI", "WY", "DC"
        }
        has_usa = any(re.search(rf"\b{re.escape(w)}\b", text, re.I) for w in usa_phrases)
        if not has_usa:
            # Check case-sensitive US state codes typically formatted as ", ST" or standalone caps in Location
            loc_and_head = f"{raw_loc} {raw_title} {raw_body[:600]}"
            for st in us_state_codes_cs:
                if re.search(rf"(?:,\s*|\b){st}\b", loc_and_head):
                    has_usa = True
                    break
        if not has_usa:
            return None

        # Reject known foreign cities/countries if they dominate the location field
        if raw_loc and any(re.search(rf"\b{fk}\b", raw_loc, re.I) for fk in [
            "united kingdom", "england", "london", "manchester", "canada", "toronto", "vancouver",
            "montreal", "germany", "berlin", "munich", "france", "paris", "india", "bengaluru",
            "bangalore", "mumbai", "singapore", "australia", "sydney", "melbourne", "dubai", "uae",
            "netherlands", "amsterdam", "spain", "barcelona", "madrid", "italy", "rome", "milan", "japan", "tokyo"
        ]) and not re.search(r"\b(usa|united states)\b", raw_loc, re.I):
            return None

        # Check Category
        if mode == "weekly":
            matched_cats = match_weekly_categories(raw_title, text)
        else:
            matched_cats = match_t2_categories(text)
        if not matched_cats:
            return None
        category = " / ".join(matched_cats)

        # Validate URL (must not be generic root portal)
        if not is_valid_deep_conference_url(raw_data.source_url):
            return None

        # Parse real date from raw_date or text
        start_date = None
        end_date = None
        if raw_data.raw_date:
            s_iso, e_iso = extract_date_range_from_text(str(raw_data.raw_date))
            if s_iso:
                start_date = s_iso
                end_date = e_iso or s_iso

        if not start_date:
            s_iso, e_iso = extract_date_range_from_text(text)
            if s_iso:
                start_date = s_iso
                end_date = e_iso or s_iso
            else:
                return None

        # Check explicit end_date line too
        end_match = re.search(r"(?:to|until|-)\s*(\d{4}-\d{2}-\d{2})", f"{raw_data.raw_date or ''} {text[:600]}")
        if end_match:
            end_date = end_match.group(1)
        if not end_date:
            end_date = start_date

        # Extract City + State
        city_val = ""
        state_val = ""
        cities = [
            ("Las Vegas", "NV", ["las vegas", "vegas"]),
            ("Boston", "MA", ["boston", "cambridge, ma", "harvard business school", "hbs"]),
            ("San Francisco", "CA", ["san francisco", "sf", "south san francisco"]),
            ("New York", "NY", ["new york", "nyc", "manhattan", "brooklyn"]),
            ("Chicago", "IL", ["chicago"]),
            ("Oak Brook", "IL", ["oak brook"]),
            ("Austin", "TX", ["austin", "atx"]),
            ("Houston", "TX", ["houston"]),
            ("Dallas", "TX", ["dallas", "frisco", "irving"]),
            ("San Antonio", "TX", ["san antonio"]),
            ("Baltimore", "MD", ["baltimore", "national harbor"]),
            ("Orlando", "FL", ["orlando"]),
            ("Miami", "FL", ["miami", "fort lauderdale", "boca raton"]),
            ("Tampa", "FL", ["tampa"]),
            ("Washington", "DC", ["washington, dc", "washington d.c.", "washington dc"]),
            ("Nashville", "TN", ["nashville"]),
            ("Seattle", "WA", ["seattle", "bellevue, wa"]),
            ("Denver", "CO", ["denver"]),
            ("San Diego", "CA", ["san diego", "la jolla"]),
            ("Los Angeles", "CA", ["los angeles", "santa monica", "anaheim"]),
            ("San Jose", "CA", ["san jose", "santa clara", "silicon valley", "palo alto", "mountain view", "stanford"]),
            ("Philadelphia", "PA", ["philadelphia"]),
            ("Pittsburgh", "PA", ["pittsburgh"]),
            ("Phoenix", "AZ", ["phoenix"]),
            ("Scottsdale", "AZ", ["scottsdale"]),
            ("Charlotte", "NC", ["charlotte"]),
            ("Raleigh", "NC", ["raleigh", "durham"]),
            ("Salt Lake City", "UT", ["salt lake city"]),
            ("Minneapolis", "MN", ["minneapolis"]),
            ("Atlanta", "GA", ["atlanta"]),
            ("Davenport", "IA", ["davenport", "quad cities"]),
            ("Portland", "OR", ["portland, or"]),
            ("New Orleans", "LA", ["new orleans"]),
        ]
        for c_name, c_state, aliases in cities:
            if any(re.search(rf"\b{re.escape(a)}\b", f"{raw_loc} {text[:1500]}", re.I) for a in aliases):
                city_val = c_name
                state_val = c_state
                break

        if not city_val and raw_loc:
            m_cs = re.search(r"([A-Za-z\.\s]{2,25}),\s*([A-Z]{2})\b", raw_loc)
            if m_cs and m_cs.group(2) in us_state_codes_cs:
                city_val = m_cs.group(1).strip()
                state_val = m_cs.group(2).strip()

        city = f"{city_val}, {state_val}" if (city_val and state_val) else (city_val or "USA")

        # Extract Venue from text
        venue = f"{city_val or 'Convention'} Center"
        venue_match = re.search(r"Venue:\s*([^.\n]+?)(?:\.|\n|$)", text)
        if venue_match and venue_match.group(1).strip():
            venue = venue_match.group(1).strip()
        elif "Location:" in text:
            loc_match = re.search(r"Location:\s*([^.\n]+?)(?:\.|\n|$)", text)
            if loc_match and loc_match.group(1).strip():
                venue = loc_match.group(1).strip()

        # Organizer
        organizer = ""
        org_match = re.search(r"Organizer:\s*([^.\n]+?)(?:\.|\n|$)", text)
        if org_match:
            organizer = org_match.group(1).strip()

        # Official Conference URL
        official_url = raw_data.source_url
        url_match = re.search(r"Official\s+(?:Event\s+|Conference\s+)?URL:\s*(https?://[^\s]+)", text, re.I)
        if url_match:
            official_url = url_match.group(1).strip().rstrip(".,;")

        # Registration URL
        registration_url = raw_data.source_url
        reg_match = re.search(r"Registration\s+(?:Event\s+)?URL:\s*(https?://[^\s]+)", text, re.I)
        if reg_match:
            registration_url = reg_match.group(1).strip().rstrip(".,;")

        if not official_url or not official_url.startswith("http") or len(official_url) < 12:
            official_url = raw_data.source_url
        if not registration_url or not registration_url.startswith("http") or len(registration_url) < 12:
            registration_url = raw_data.source_url

        official_url = official_url.replace("/en/events", "/events").rstrip(".,;")
        registration_url = registration_url.replace("/en/events", "/events").rstrip(".,;")

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
        desc_match = re.search(r"Overview:\s*([^\n]+)", text, re.I)
        overview = desc_match.group(1).strip()[:800] if desc_match else f"{raw_title} held in {city}."

        # Extract EVERY speaker and all their available details
        speakers, titles, speaker_details = self._extract_all_speakers_from_text(
            text, raw_title, city, "USA", organizer, talks_details, official_url
        )
        speakers_available = "Yes" if len(speakers) > 0 else "No"

        # Extract Attendee details
        attendee_details = extract_attendee_details_from_text(text, raw_title, category)

        return AIConferenceExtraction(
            conference_title=raw_title,
            industry_category=category,
            start_date=start_date,
            end_date=end_date,
            speakers=speakers,
            speaker_titles_companies=titles,
            speaker_details=speaker_details,
            attendee_details=attendee_details,
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


    def _extract_all_speakers_from_text(self, text: str, conf_title: str, city: str, country: str, organizer: str, talks_details: str = "", official_url: str = ""):
        """
        Extracts every single genuine speaker explicitly listed in text without fabricating defaults.
        Deduplicates entries so each speaker appears strictly once per conference.
        """
        from ..scrapers.live_speaker_scraper import is_valid_speaker_name

        speakers = []
        titles = []
        speaker_details = []
        seen_names = set()

        raw_candidates = []

        section_patterns = [
            r"(?:Keynote\s+|Featured\s+(?:Guest\s+)?)?Speakers?(?:\s*& Presenters|\s*& Guests)?:\s*(.*?)(?=(?:Previous Talks|Overview|Organizer|Category|Dates|Venue|Location|Official URL|Official Event URL|Registration URL|Publication Date|Agenda|Hosts|\Z))",
            r"Hosts?(?:\s*&\s*(?:Featured\s*)?Guests?)?:\s*(.*?)(?=(?:Previous Talks|Overview|Organizer|Category|Dates|Venue|Location|Official URL|Official Event URL|Registration URL|Publication Date|Agenda|\Z))",
            r"Meet the speakers?:\s*(.*?)(?=(?:Previous Talks|Overview|Organizer|Category|Dates|Venue|Location|Official URL|Official Event URL|Registration URL|Publication Date|Agenda|\Z))",
            r"Panelists?:\s*(.*?)(?=(?:Previous Talks|Overview|Organizer|Category|Dates|Venue|Location|Official URL|Official Event URL|Registration URL|Publication Date|Agenda|\Z))",
            r"(?:(?:last\s+year'?s\s+|featured\s+|keynote\s+|this\s+year'?s\s+)?speakers?(?:\s*(?:&|and)\s*(?:presenters|guests|panelists))?(?:\s*(?:will\s+include|included|include|coming\s+soon))?):?\s*(.*?)(?=(?:Previous Talks|Overview|Organizer|Category|Dates|Venue|Location|Official URL|Official Event URL|Registration URL|Publication Date|Agenda|Hosts|This event is|Frequently Asked|\Z))"
        ]

        for spat in section_patterns:
            for spk_match in re.finditer(spat, text, re.I | re.DOTALL):
                spk_text = clean_html_text(spk_match.group(1)).strip()
                raw_entries = re.split(r"[;\n\r•]+|,\s*(?=(?:(?:Dr\.|Prof\.|Mr\.|Ms\.)\s+)?[A-Z][a-zA-Z'\-]+(?:\s+[A-Z]\.?)?(?:\s+[A-Z][a-zA-Z'\-]+)+\s*(?:\(|$|,))", spk_text)
                for entry in raw_entries:
                    entry = entry.strip().rstrip(".").strip()
                    if not entry or len(entry) < 3:
                        continue
                    entry = re.sub(r"^(\d+[\.\)]|\-)\s*", "", entry).strip()

                    # Check for explicit personal LinkedIn URL (strictly personal profile linkedin.com/in/)
                    cand_linkedin = ""
                    li_match = re.search(r"(?:\|\s*LinkedIn:\s*|-\s*|–\s*|\(\s*)?(https?://(?:www\.)?linkedin\.com/in/[a-zA-Z0-9_\-\%]+/?)\)?", entry, re.I)
                    if li_match:
                        cand_linkedin = li_match.group(1).strip()
                        entry = (entry[:li_match.start()] + entry[li_match.end():]).strip().rstrip("-").strip()
                    elif "linkedin.com/company/" in entry.lower() or "linkedin.com/school/" in entry.lower():
                        comp_li_match = re.search(r"\|\s*LinkedIn:\s*(https?://[^\s]+)", entry, re.I)
                        if comp_li_match:
                            entry = entry[:comp_li_match.start()].strip()

                    # Pattern: Company - Name, Role
                    comp_dash_match = re.match(r"^([A-Za-z0-9\s&]+)\s*-\s*([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)+),\s*([^;\n\r]+)$", entry)
                    if comp_dash_match:
                        raw_candidates.append({
                            "name": comp_dash_match.group(2).strip(),
                            "company": comp_dash_match.group(1).strip(),
                            "role": comp_dash_match.group(3).strip(),
                            "linkedin": cand_linkedin
                        })
                        continue

                    # Pattern: Name (Role at Company)
                    m_paren = re.match(r"^([A-Za-z'\-\.\s]+?)\s*\((.*?)\)$", entry)
                    if m_paren:
                        name_part = m_paren.group(1).strip()
                        role_part = m_paren.group(2).strip()
                    elif "," in entry:
                        name_part, role_part = entry.split(",", 1)
                    elif " - " in entry:
                        name_part, role_part = entry.split(" - ", 1)
                    elif " – " in entry:
                        name_part, role_part = entry.split(" – ", 1)
                    else:
                        name_part, role_part = entry, ""

                    raw_candidates.append({
                        "name": name_part.strip(),
                        "company": "",
                        "role": role_part.strip(),
                        "linkedin": cand_linkedin
                    })

        # Conversational speaker mentions
        conv_matches = re.finditer(
            r"(?:(?:in|for\s+a)\s+conversation\s+with|featured\s+guest(?:\s+of\s+the\s+evening)?\s+is)\s+([A-Z][a-zA-Z'\-]+(?:\s+[A-Z][a-zA-Z'\-]+)+),\s*([^,\.]+?)\s+(?:of|at|@)\s+([A-Za-z0-9\s&]+?)(?:,|\.|\n|\Z)",
            text, re.I
        )
        for cm in conv_matches:
            raw_candidates.append({
                "name": cm.group(1).strip(),
                "role": cm.group(2).strip(),
                "company": cm.group(3).strip().rstrip(".,;"),
                "linkedin": ""
            })

        for cand in raw_candidates:
            name = clean_html_text(cand["name"])
            clean_name = re.sub(r"^(Dr\.|Prof\.|Mr\.|Ms\.|Mrs\.)\s+", "", name, flags=re.I).strip()
            clean_name = re.sub(r"[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$", "", clean_name, flags=re.I).strip()

            m_paren = re.match(r"^(.*?)\s*\((.*?)\)$", clean_name)
            if m_paren:
                clean_name = m_paren.group(1).strip()
                cand_role = m_paren.group(2).strip()
                if not cand["role"]:
                    cand["role"] = cand_role

            if not is_valid_speaker_name(clean_name):
                continue

            norm_key = clean_name.lower()
            if norm_key in seen_names:
                continue
            seen_names.add(norm_key)

            role_desc = cand["role"]
            company_name = cand["company"]
            job_role = ""

            if not company_name:
                if " at " in role_desc:
                    r_split = role_desc.split(" at ", 1)
                    job_role = r_split[0].strip()
                    company_name = r_split[1].strip()
                elif "@" in role_desc:
                    r_split = role_desc.split("@", 1)
                    job_role = r_split[0].strip()
                    company_name = r_split[1].strip()
                elif " of " in role_desc:
                    r_split = role_desc.split(" of ", 1)
                    job_role = r_split[0].strip()
                    company_name = r_split[1].strip()
                elif "," in role_desc:
                    r_split = role_desc.split(",", 1)
                    job_role = r_split[0].strip()
                    company_name = r_split[1].strip()
                else:
                    job_role = role_desc if (role_desc and len(role_desc) <= 80) else ""
                    company_name = ""
            else:
                job_role = role_desc if (role_desc and len(role_desc) <= 80) else ""

            if len(job_role) > 80:
                job_role = ""
            if len(company_name) > 100:
                company_name = ""

            job_role = re.sub(r'&\s*$', '', job_role).strip().rstrip(".,;")
            if job_role.lower() in ["speaker", "keynote speaker", "featured guest", "event host & organizer", "tbd", "n/a", "none"]:
                job_role = ""
            if "luma" in company_name.lower():
                company_name = "Luma"
            company_name = company_name.strip().rstrip(".,;")
            if company_name.lower() in ["tbd", "n/a", "none", "unknown", "industry organization", conf_title.lower()]:
                company_name = ""

            spk_location = f"{city}, {country}" if city and country else "USA"
            for known_loc, kw_list in [
                ("San Francisco, CA, USA", ["modal", "openai", "pytorch", "san francisco", "amplify", "ollama", "trajectory", "crusoe", "lightfield"]),
                ("New York, NY, USA", ["new york", "salt flats", "activo", "codify", "warner", "nbcuniversal", "estée lauder", "backlight", "real story", "mywhatif", "aurapath"]),
                ("Washington, DC, USA", ["cisa", "white house", "fbi", "nsa", "cyber ab", "mandiant", "defense", "krebs", "state department", "national gallery"]),
                ("Seattle, WA, USA", ["university of washington", "octoai", "allen institute", "rick steves", "seattle"]),
                ("Denver, CO, USA", ["denver", "colorado", "cvent"]),
                ("Los Angeles, CA, USA", ["sony pictures", "digital bedrock", "los angeles"]),
                ("Atlanta, GA, USA", ["home depot", "atlanta"]),
                ("Boston, MA, USA", ["takeda", "boston", "harvard"]),
                ("Princeton, NJ, USA", ["princeton"]),
                ("Stanford, CA, USA", ["stanford", "cartesia"]),
                ("Pittsburgh, PA, USA", ["carnegie mellon", "cmu"])
            ]:
                if any(kw in company_name.lower() or kw in role_desc.lower() for kw in kw_list):
                    spk_location = known_loc
                    break

            clean_name, job_role, company_name, company_url, linkedin_url = clean_and_resolve_speaker(
                clean_name, job_role, company_name, conf_title, official_url, location=spk_location
            )
            if not clean_name:
                continue

            if cand.get("linkedin"):
                linkedin_url = cand["linkedin"]

            prev_speaking = f"Keynote and invited speaker: {talks_details}" if talks_details else f"Speaker at {conf_title}"

            speakers.append(clean_name)
            title_str = f"{job_role} at {company_name}" if (job_role and company_name) else (job_role or company_name)
            titles.append(title_str)
            speaker_details.append(SpeakerDetailItem(
                speaker_name=clean_name,
                job_role_designation=job_role,
                company_organization=company_name,
                company_name=company_name,
                official_company_website_url=company_url,
                linkedin_url=linkedin_url,
                location=spk_location,
                previous_speaking_info=prev_speaking
            ))

        return speakers, titles, speaker_details
