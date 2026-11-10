import os
import sys
import re
import time
import datetime
import unicodedata
from pathlib import Path
from typing import List, Optional, Set, Dict, Any, Tuple
from typing_extensions import TypedDict
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import requests

try:
    import gspread
    from google.oauth2.service_account import Credentials
    HAVE_GSPREAD = True
except ImportError:
    HAVE_GSPREAD = False

from tavily import TavilyClient
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langgraph.graph import StateGraph, START, END

# Load environment configuration
backend_env = Path(__file__).resolve().parent.parent.parent / ".env"
if backend_env.exists():
    load_dotenv(backend_env, override=True)
else:
    load_dotenv(override=True)

# =====================================================================
# 1. API CLIENTS & KNOWLEDGE BASE INITIALIZATION
# =====================================================================
def get_tavily_client() -> TavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    return TavilyClient(api_key=api_key)

def get_azure_llm() -> ChatOpenAI:
    raw_url = os.getenv("AZURE_OPENAI_BASE_URL", "https://dv-aus-es-resource.services.ai.azure.com/openai/v1")
    base_url = re.sub(r'^[\[\(\"\']+|[\]\)\"\']+$', '', raw_url).strip()
    return ChatOpenAI(
        model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        base_url=base_url,
        temperature=0.0,
        seed=42
    )

tavily_client = get_tavily_client()
azure_llm = get_azure_llm()

KB_FILE_PATH = "adople_knowledge_base.md"

def load_knowledge_base(file_path: str = KB_FILE_PATH) -> str:
    candidates = [
        file_path,
        "adople_knowledge_base.md",
        "backend/adople_knowledge_base.md",
        os.path.join(os.path.dirname(__file__), "..", "..", "adople_knowledge_base.md"),
        os.path.join(os.path.dirname(__file__), "..", "adople_knowledge_base.md"),
        "/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/adople_knowledge_base.md"
    ]
    for p in candidates:
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
    raise FileNotFoundError(f"Knowledge base file '{file_path}' not found!")

adople_kb_content = load_knowledge_base()


# =====================================================================
# 2. DATA SCHEMAS & PYDANTIC MODELS
# =====================================================================
class SpeakerRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    speaker_id: str = Field(alias="Speaker_ID")
    conference_id: str = Field(alias="Conference_ID")
    conference_name: str = Field(alias="Conference_Name")
    speaker_name: Optional[str] = Field(default="", alias="Speaker_Name")
    job_title: Optional[str] = Field(default="", alias="Job_Title")
    company_name: Optional[str] = Field(default="", alias="Company_Name")
    personal_linkedin_url: Optional[str] = Field(default="", alias="Personal_LinkedIn_URL")
    linkedin_status: Optional[str] = Field(default="needs_review", alias="LinkedIn_Status")
    professional_email: Optional[str] = Field(default="", alias="Professional_Email")
    email_source_url: Optional[str] = Field(default="", alias="Email_Source_URL")
    speaker_source_url: Optional[str] = Field(default="", alias="Speaker_Source_URL")
    verification_status: Optional[str] = Field(default="needs_review", alias="Verification_Status")
    last_checked_at: Optional[str] = Field(default="", alias="Last_Checked_At")
    weekly_run_id: Optional[str] = Field(default="", alias="Weekly_Run_ID")

    # Exhibitor Data (New Incoming Columns)
    exhibitor_name: Optional[str] = Field(default="", alias="Exhibitor_Name")
    exhibitor_email: Optional[str] = Field(default="", alias="Exhibitor_Email")
    exhibitor_email_status: Optional[str] = Field(default="", alias="Exhibitor_Email_Status")
    
    # Attendee Data (New Incoming Columns)
    attendee_name: Optional[str] = Field(default="", alias="Attendee_Name")
    attendee_email: Optional[str] = Field(default="", alias="Attendee_Email")
    attendee_email_status: Optional[str] = Field(default="", alias="Attendee_Email_Status")


class OrganizedCompanyProfile(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    company_domain: str = Field(default="", description="Clean company root domain (e.g. 'afbasket.com' or 'servicenow.com'). NEVER a directory or social media.")
    official_website: str = Field(default="", description="Full homepage URL (e.g. 'https://www.afbasket.com')")
    primary_industry: str = Field(default="", description="Specific industry & segment (e.g., 'Supermarket & Grocery Retail', 'Food & Beverage Wholesale', 'Venture Capital', 'Life Insurance', 'Enterprise SaaS')")
    headcount_tier: str = Field(default="", description="Scale category: 'Micro (<50)', 'Mid-Market Sweet Spot (50-500)', 'Upper Mid-Market (500-2,000)', 'Enterprise Giant (2,000+)', or 'Non-Profit / Academic'")
    core_products_and_services: str = Field(default="", description="Explanation of core products/services and who buys them")
    us_market_presence: str = Field(default="", description="HQ location and US operating presence")
    operational_workflows_analysis: str = Field(default="", description="Specific analysis of daily manual/document workflows (invoices, bills of lading, claims, purchase orders, tickets, compliance)")
    key_business_highlights: str = Field(default="", description="Notable business facts (public/private, growth, footprint)")


class EnrichedLead(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    raw_lead: SpeakerRecord
    profile: OrganizedCompanyProfile
    tavily_raw_text: str = ""


def determine_qualification_status(overall_score: float) -> str:
    """
    Strict business rule:
    - DISQUALIFIED strictly for overall score < 50.0
    - MODERATE for 50.0 <= overall score < 75.0
    - HIGH_MATCH for overall score >= 75.0
    """
    val = float(overall_score or 0.0)
    if val >= 75.0:
        return "HIGH_MATCH"
    elif val >= 50.0:
        return "MODERATE"
    else:
        return "DISQUALIFIED"


class LeadScoreResult(BaseModel):
    strategic_analysis: str = Field(description="Detailed rationale justifying the scores based on the Knowledge Base.")
    industry_fit_score: float = Field(description="0-100: Core Focus (Healthcare, FinTech, Banking, Insurance, Logistics, Supply Chain, Enterprise Automation)=95-100, Secondary (Venture Capital, B2B Cloud Infra)=78-88, Non-Core (General Productivity/Wiki SaaS, Hardware Manufacturing, Consumer Retail, Media)=50-70, Education/Institutions/Non-Profit=0-20")
    tier_fit_score: float = Field(description="0-100: Mid-Market (50-2000 emp)=92-100, Enterprise Commercial Giants (2000+ emp)=85-92, Hyperscalers=40-55, Micro (<50 emp)=25-40, Non-Profits/Academia=0-15")
    overall_company_score: float = Field(description="Calculated strictly as: (0.60 * industry_fit_score) + (0.40 * tier_fit_score)")
    qualification_status: str = Field(default="", description="'HIGH_MATCH' (>= 75.0), 'MODERATE' (50.0-74.9), or 'DISQUALIFIED' (< 50.0)")

    def model_post_init(self, __context: Any) -> None:
        # Guarantee strict qualification status: DISQUALIFIED only if score < 50.0
        self.qualification_status = determine_qualification_status(self.overall_company_score)


class EvaluatedLead(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    enriched_lead: Any
    score_details: LeadScoreResult


class RankedLead(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    rank: int                               # 1, 2, 3... up to N
    company_name: str                       # e.g., "Manulife"
    domain: str                             # e.g., "manulife.com"
    overall_score: float                    # e.g., 67.4
    industry_score: float                   # e.g., 89.0
    tier_score: float                       # e.g., 35.0
    qualification_status: str               # "HIGH_MATCH", "MODERATE", etc.
    
    # Speaker & Outreach Data
    speaker_id: str                         # Unique ID from Master Sheet
    speaker_name: str                       # e.g., "Suzanne Philion"
    job_title: str                          # e.g., "CMO"
    email: str                              # e.g., "suzanne_philion@manulife.com"
    email_status: str                       # "verified" vs "needs_review"
    linkedin_url: str                       # Personal LinkedIn URL
    conference_name: str                    # Conference name
    
    # Exhibitor Data (New Incoming Columns)
    exhibitor_name: str = ""
    exhibitor_email: str = ""
    exhibitor_email_status: str = ""
    
    # Attendee Data (New Incoming Columns)
    attendee_name: str = ""
    attendee_email: str = ""
    attendee_email_status: str = ""
    
    # Original Reference
    evaluated_lead: Any


# =====================================================================
# 3. LANGGRAPH STATE DEFINITION
# =====================================================================
class PipelineState(TypedDict):
    # Stores speaker IDs that were already evaluated in previous runs/weeks
    processed_speaker_ids: Set[str]
    
    # Newly detected leads for this run that need ranking
    new_leads: List[SpeakerRecord]
    
    # Speaker IDs of alternate speakers from the same company that were skipped
    duplicate_speaker_ids: List[str]
    
    # Metadata about the current execution
    current_weekly_run_id: Optional[str]
    total_new_count: int

    # Node 2: Profile Enriched Leads
    enriched_leads: List[EnrichedLead]

    # Node 3: 60/40 Scored Leads
    scored_leads: List[EvaluatedLead]

    # Node 4: Ranked Leads
    top_10_leads: List[RankedLead]
    all_ranked_leads: List[RankedLead]

    # Node 5: Output Sync Status
    exported_count: int


# =====================================================================
# 4. UTILITIES & DATA SANITIZATION HELPERS
# =====================================================================
FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "aol.com", "protonmail.com", "zoho.com", "mail.com", "yandex.com", "gmx.com"
}

BLOCKED_DOMAINS = {
    # Social & Community
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
    "reddit.com", "glassdoor.com", "indeed.com",
    # Lead Gen & Directory Aggregators
    "leadiq.com", "zoominfo.com", "apollo.io", "nombase.com", "crunchbase.com",
    "pitchbook.com", "yelp.com", "yellowpages.com", "dnb.com", "tavily.com",
    "google.com", "wikipedia.org", "mapquest.com", "traderknows.com", "cbinsights.com", "owler.com",
    # News, PR Wires & Trade Publications
    "retail-merchandiser.com", "supermarketnews.com", "bloomberg.com", "globenewswire.com",
    "prnewswire.com", "businesswire.com", "medium.com", "substack.com", "reuters.com",
    "forbes.com", "techcrunch.com", "venturebeat.com", "fooddive.com", "grocerydive.com",
    "restaurantdive.com", "cspdailynews.com", "cstoredecisions.com"
}

def clean_string(val: Any) -> str:
    """Strips whitespace and removes double spaces."""
    if val is None:
        return ""
    text = str(val).strip()
    return re.sub(r'\s+', ' ', text)

def clean_token(s: str) -> str:
    """Strips all non-alphanumeric characters, normalizes accents, and lowercases."""
    norm = unicodedata.normalize('NFKD', str(s)).encode('ASCII', 'ignore').decode('utf-8')
    return re.sub(r'[^a-zA-Z0-9]', '', norm).lower()

def clean_email(val: Any) -> str:
    """Cleans email, removes mailto:, lowercases, strips brackets."""
    text = clean_string(val).lower()
    text = text.replace("mailto:", "").replace("[", "").replace("]", "")
    match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text)
    return match.group(0) if match else ""

def clean_url(val: Any) -> str:
    """Ensures clean URL format with https."""
    text = clean_string(val)
    if not text or text.lower() in ["n/a", "none", "-"]:
        return ""
    if text.startswith("http://"):
        text = "https://" + text[7:]
    return text

def extract_domain_from_email(email_str: str) -> str:
    """Extracts ground-truth corporate domain from speaker email if not a generic email provider."""
    if not email_str or "@" not in email_str:
        return ""
    clean = email_str.strip().lower()
    match = re.search(r'@([\w\.-]+\.\w+)', clean)
    if match:
        domain = match.group(1).replace("www.", "").strip()
        if domain not in FREE_EMAIL_DOMAINS and "." in domain:
            return domain
    return ""

def is_blocked_domain(url_or_domain: str) -> bool:
    """Checks whether a domain belongs to a directory, social platform, or aggregator."""
    if not url_or_domain:
        return False
    clean = url_or_domain.lower().replace("https://", "").replace("http://", "").replace("www.", "")
    domain = clean.split("/")[0].split(":")[0].strip()
    return any(domain == b or domain.endswith("." + b) for b in BLOCKED_DOMAINS)

def extract_domain_from_url(url: str) -> str:
    """Extract clean domain automatically from URL, excluding aggregators."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse
        netloc = urlparse(url).netloc
        netloc = netloc.replace("www.", "")
        domain = netloc.split(":")[0].strip()
        if not is_blocked_domain(domain):
            return domain
        return ""
    except Exception:
        return ""

def is_email_domain_matching_company(email_domain: str, company_name: str) -> bool:
    """
    Checks if the email domain plausibly belongs to the company,
    preventing third-party emails from being trusted.
    """
    if not email_domain or not company_name:
        return False
        
    domain_slug = email_domain.split(".")[0].lower()
    comp_clean = clean_token(company_name)
    
    # 1. Direct substring
    if domain_slug in comp_clean or comp_clean in domain_slug:
        return True
        
    # 2. Token overlap
    words = [w.lower() for w in re.findall(r'[a-zA-Z0-9]+', company_name) if len(w) >= 3]
    for w in words:
        if w in domain_slug:
            return True
            
    # 3. Acronym / Abbreviation match
    if len(words) >= 2:
        first_char = words[0][0]
        second_char = words[1][0]
        if domain_slug.startswith(first_char) and second_char in domain_slug:
            if len(domain_slug) <= 5:
                return True

    return False

def pick_best_company_url(results: List[Dict[str, Any]], company_name: str) -> str:
    """
    Selects the best matching official corporate URL from Tavily search results,
    filtering out blogs, directories, and trade publications.
    """
    candidates = []
    for r in results:
        url = r.get("url", "")
        if not url or is_blocked_domain(url):
            continue
        domain = extract_domain_from_url(url)
        if not domain:
            continue
        if is_email_domain_matching_company(domain, company_name):
            return url
        candidates.append(url)
    return candidates[0] if candidates else ""

def get_speaker_email_priority(lead: SpeakerRecord) -> int:
    """
    Evaluates speaker strictly on email quality (NO job title weighting).
    Priority:
    3: Verified Corporate Email (email domain matches company & verification_status == 'verified')
    2: Verified Email (verification_status == 'verified')
    1: Has Email (unverified / needs_review)
    0: No Email
    """
    all_emails = [
        (getattr(lead, "professional_email", ""), getattr(lead, "verification_status", "")),
        (getattr(lead, "exhibitor_email", ""), getattr(lead, "exhibitor_email_status", "")),
        (getattr(lead, "attendee_email", ""), getattr(lead, "attendee_email_status", ""))
    ]
    
    best_priority = 0
    for em_raw, st_raw in all_emails:
        email = clean_string(em_raw).lower()
        status = clean_string(st_raw).lower()
        if not email:
            continue
            
        domain = extract_domain_from_email(email)
        is_matching = is_email_domain_matching_company(domain, getattr(lead, "company_name", "")) if domain else False
        
        if (status == "verified" or "verified" in status) and is_matching:
            best_priority = max(best_priority, 3)
        elif status == "verified" or "verified" in status:
            best_priority = max(best_priority, 2)
        else:
            best_priority = max(best_priority, 1)
            
    return best_priority


# =====================================================================
# 5. MICROSOFT SHAREPOINT / GRAPH API EXCEL INTEGRATION
# =====================================================================
CURATED_SHEET_HEADERS = [
    "Rank",
    "Overall_Score",
    "Company_Name",
    "Company_Domain",
    "Conference_Name",
    "Qualification_Status",
    "Primary_Industry",
    "Headcount_Tier",
    "Speaker_Name",
    "Job_Title",
    "Professional_Email",
    "Email_Status",
    "Exhibitor_Name",
    "Exhibitor_Email",
    "Exhibitor_Email_Status",
    "Attendee_Name",
    "Attendee_Email",
    "Attendee_Email_Status",
    "Personal_LinkedIn_URL",
    "Speaker_ID",
    "Evaluated_At"
]

SHAREPOINT_TENANT_ID = os.getenv("SHAREPOINT_TENANT_ID", "")
SHAREPOINT_CLIENT_ID = os.getenv("SHAREPOINT_CLIENT_ID", "")
SHAREPOINT_CLIENT_SECRET = os.getenv("SHAREPOINT_CLIENT_SECRET", "")
SHAREPOINT_DRIVE_ID = os.getenv("SHAREPOINT_DRIVE_ID", "")
SHAREPOINT_ITEM_ID = os.getenv("SHAREPOINT_ITEM_ID", "")

SHAREPOINT_MASTER_SHEET = os.getenv("SHAREPOINT_MASTER_SHEET", "Verified Data")
SHAREPOINT_LATEST_SHEET = os.getenv("SHAREPOINT_LATEST_SHEET", "latest_week_scoring")
SHAREPOINT_HISTORY_SHEET = os.getenv("SHAREPOINT_HISTORY_SHEET", "Companies scoring")
SHAREPOINT_QUALIFIED_SHEET = os.getenv("SHAREPOINT_QUALIFIED_SHEET", "Qualified Leads")
SHAREPOINT_NON_QUALIFIED_SHEET = os.getenv("SHAREPOINT_NON_QUALIFIED_SHEET", "Non -Qualified Leads")

QUALIFIED_LEADS_HEADERS = [
    "Rank",
    "Overall_Score",
    "Qualification_Status",
    "Company_Name",
    "Company_Domain",
    "Conference_Name",
    "Conference_ID",
    "Contact_Type",
    "Contact_Name",
    "Job_Title",
    "Professional_Email",
    "Email_Status",
    "Personal_LinkedIn_URL",
    "Primary_Industry",
    "Headcount_Tier",
    "Evaluated_At",
    "Outreach Status",
    "Reply Status",
    "Received Reply",
    "Reply Sentiment",
    "Thread ID",
    "Send Message"
]

def col_num_to_letter(n: int) -> str:
    """Converts 1-based column number to Excel column letters (1 -> A, 21 -> U)."""
    string = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        string = chr(65 + remainder) + string
    return string

class SharePointExcelClient:
    """Production client for Microsoft Graph API Excel operations."""
    
    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        drive_id: Optional[str] = None,
        item_id: Optional[str] = None
    ):
        self.tenant_id = tenant_id or os.getenv("SHAREPOINT_TENANT_ID", SHAREPOINT_TENANT_ID)
        self.client_id = client_id or os.getenv("SHAREPOINT_CLIENT_ID", SHAREPOINT_CLIENT_ID)
        self.client_secret = client_secret or os.getenv("SHAREPOINT_CLIENT_SECRET", SHAREPOINT_CLIENT_SECRET)
        self.drive_id = drive_id or os.getenv("SHAREPOINT_DRIVE_ID", SHAREPOINT_DRIVE_ID)
        self.item_id = item_id or os.getenv("SHAREPOINT_ITEM_ID", SHAREPOINT_ITEM_ID)
        
        self._token: Optional[str] = None
        self._token_expires_at: float = 0

    def get_token(self) -> str:
        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        token_data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
        }
        res = requests.post(token_url, data=token_data, timeout=15)
        if res.status_code != 200:
            raise RuntimeError(f"Failed to authenticate with Microsoft Graph ({res.status_code}): {res.text}")
        
        payload = res.json()
        self._token = payload["access_token"]
        expires_in = payload.get("expires_in", 3600)
        self._token_expires_at = time.time() + float(expires_in)
        return self._token

    @property
    def headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def get_used_range(self, sheet_name: str) -> List[List[Any]]:
        """Returns 2D array of all values in used range of worksheet."""
        url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/worksheets('{sheet_name}')/usedRange"
        res = requests.get(url, headers=self.headers, timeout=25)
        if res.status_code != 200:
            raise RuntimeError(f"Error reading usedRange from '{sheet_name}' ({res.status_code}): {res.text}")
        return res.json().get("values", [])

    def get_records(self, sheet_name: str) -> List[Dict[str, Any]]:
        """Returns list of row dicts keyed by header name."""
        values = self.get_used_range(sheet_name)
        if not values or len(values) < 2:
            return []
        headers = [str(h).strip() for h in values[0]]
        records = []
        for row in values[1:]:
            record = {}
            for col_idx, h in enumerate(headers):
                val = row[col_idx] if col_idx < len(row) else ""
                record[h] = val
            records.append(record)
        return records

    def update_range(self, sheet_name: str, address: str, values: List[List[Any]]) -> None:
        """Updates a specific range address with 2D values."""
        url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/worksheets('{sheet_name}')/range(address='{address}')"
        res = requests.patch(url, headers=self.headers, json={"values": values}, timeout=30)
        if res.status_code != 200:
            raise RuntimeError(f"Error updating range '{address}' on '{sheet_name}' ({res.status_code}): {res.text}")

    def clear_range(self, sheet_name: str, address: str) -> None:
        """Clears range contents and formats."""
        url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/worksheets('{sheet_name}')/range(address='{address}')/clear"
        res = requests.post(url, headers=self.headers, json={"applyTo": "all"}, timeout=20)
        if res.status_code not in (200, 204):
            raise RuntimeError(f"Error clearing range '{address}' on '{sheet_name}' ({res.status_code}): {res.text}")

    def format_range_fill(self, sheet_name: str, address: str, color_hex: str) -> None:
        """Formats range background fill color."""
        url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/worksheets('{sheet_name}')/range(address='{address}')/format/fill"
        res = requests.patch(url, headers=self.headers, json={"color": color_hex}, timeout=20)
        if res.status_code not in (200, 204):
            print(f"⚠️ Note on fill formatting for {sheet_name} {address}: {res.status_code}")

    def format_range_font(self, sheet_name: str, address: str, bold: bool = True) -> None:
        """Formats range font properties."""
        url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/worksheets('{sheet_name}')/range(address='{address}')/format/font"
        res = requests.patch(url, headers=self.headers, json={"bold": bold}, timeout=20)
        if res.status_code not in (200, 204):
            print(f"⚠️ Note on font formatting for {sheet_name} {address}: {res.status_code}")

    def ensure_worksheet_exists(self, sheet_name: str) -> None:
        """Ensures worksheet exists on SharePoint/OneDrive workbook."""
        url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/worksheets"
        try:
            res = requests.post(url, headers=self.headers, json={"name": sheet_name}, timeout=15)
            if res.status_code in (200, 201, 409):
                return
        except Exception:
            pass

    def get_table_records(self, table_name: str, fallback_sheet_name: str = "") -> Tuple[List[str], List[List[Any]]]:
        """Reads headers and rows from a named Excel table on SharePoint, falling back to worksheet usedRange."""
        if table_name:
            try:
                cols_url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/tables/{table_name}/columns"
                c_res = requests.get(cols_url, headers=self.headers, timeout=20)
                if c_res.status_code == 200:
                    col_names = [str(c.get("name", "")) for c in c_res.json().get("value", [])]
                    rows_url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/tables/{table_name}/rows"
                    r_res = requests.get(rows_url, headers=self.headers, timeout=25)
                    if r_res.status_code == 200:
                        rows = []
                        for item in r_res.json().get("value", []):
                            vals = item.get("values", [[]])[0]
                            while len(vals) < len(col_names):
                                vals.append("")
                            rows.append(vals)
                        return col_names, rows
            except Exception:
                pass
        if fallback_sheet_name:
            try:
                vals = self.get_used_range(fallback_sheet_name)
                if vals and len(vals) > 1:
                    col_names = [str(c) for c in vals[0]]
                    return col_names, [list(r) for r in vals[1:]]
                elif vals:
                    return [str(c) for c in vals[0]], []
            except Exception:
                pass
        return [], []

    def delete_sheet_tables(self, sheet_name: str, table_names: Optional[List[str]] = None) -> None:
        """Deletes Excel tables on a worksheet before rewriting range & recreating named table."""
        from urllib.parse import quote
        ws_enc = quote(sheet_name)
        url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/worksheets('{ws_enc}')/tables"
        try:
            res = requests.get(url, headers=self.headers, timeout=20)
            if res.status_code != 200:
                return
            for tbl in res.json().get("value", []):
                tname = tbl.get("name", "")
                tid = tbl.get("id", "")
                if table_names is None or tname in table_names:
                    del_target = tid or tname
                    if del_target:
                        requests.delete(
                            f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/tables/{del_target}",
                            headers=self.headers,
                            timeout=20,
                        )
        except Exception as e:
            print(f"⚠️ Notice deleting table(s) on '{sheet_name}': {e}")

    def create_and_name_table(
        self,
        sheet_name: str,
        range_address: str,
        table_name: str,
        style: str = "TableStyleMedium2",
    ) -> None:
        """Creates an Excel table over `'sheet_name'!range_address` and renames it cleanly."""
        try:
            add_url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/tables/add"
            res = requests.post(
                add_url,
                headers=self.headers,
                json={"address": f"'{sheet_name}'!{range_address}", "hasHeaders": True},
                timeout=20,
            )
            if res.status_code in (200, 201):
                table_id = res.json().get("id")
                if table_id:
                    patch_url = f"https://graph.microsoft.com/v1.0/drives/{self.drive_id}/items/{self.item_id}/workbook/tables/{table_id}"
                    requests.patch(
                        patch_url,
                        headers=self.headers,
                        json={"name": table_name, "style": style},
                        timeout=20,
                    )
        except Exception as e:
            print(f"⚠️ Notice creating table '{table_name}' on '{sheet_name}': {e}")

def get_sharepoint_client() -> SharePointExcelClient:
    return SharePointExcelClient()

def apply_sharepoint_color_formatting(
    client: SharePointExcelClient,
    sheet_name: str,
    start_row: int,
    ranked_leads: List[RankedLead]
) -> None:
    """Applies visual row colors in atomic chunks: High Match (Green #D9EAD3), Moderate (Yellow #FFF2CC), Disqualified (Gray #F3F3F3)."""
    if not ranked_leads:
        return
        
    last_col_letter = col_num_to_letter(len(CURATED_SHEET_HEADERS))  # 'U'
    
    current_status = None
    chunk_start = start_row
    
    for i, lead in enumerate(ranked_leads):
        row_num = start_row + i
        status = lead.qualification_status.upper()
        if current_status is None:
            current_status = status
            chunk_start = row_num
        elif status != current_status:
            chunk_end = row_num - 1
            color = "#D9EAD3" if current_status == "HIGH_MATCH" else ("#FFF2CC" if current_status == "MODERATE" else "#F3F3F3")
            client.format_range_fill(sheet_name, f"A{chunk_start}:{last_col_letter}{chunk_end}", color)
            current_status = status
            chunk_start = row_num
            
    if current_status is not None:
        chunk_end = start_row + len(ranked_leads) - 1
        color = "#D9EAD3" if current_status == "HIGH_MATCH" else ("#FFF2CC" if current_status == "MODERATE" else "#F3F3F3")
        client.format_range_fill(sheet_name, f"A{chunk_start}:{last_col_letter}{chunk_end}", color)

def verify_environment_and_credentials() -> None:
    """Pre-flight check: Validates that all necessary API keys and credentials exist before execution begins."""
    missing = []
    if not os.getenv("AZURE_OPENAI_API_KEY"):
        missing.append("AZURE_OPENAI_API_KEY")
    if not os.getenv("AZURE_OPENAI_BASE_URL"):
        missing.append("AZURE_OPENAI_BASE_URL")
    if not os.getenv("TAVILY_API_KEY"):
        missing.append("TAVILY_API_KEY")
        
    tenant_id = os.getenv("SHAREPOINT_TENANT_ID", SHAREPOINT_TENANT_ID)
    client_id = os.getenv("SHAREPOINT_CLIENT_ID", SHAREPOINT_CLIENT_ID)
    client_secret = os.getenv("SHAREPOINT_CLIENT_SECRET", SHAREPOINT_CLIENT_SECRET)
    drive_id = os.getenv("SHAREPOINT_DRIVE_ID", SHAREPOINT_DRIVE_ID)
    item_id = os.getenv("SHAREPOINT_ITEM_ID", SHAREPOINT_ITEM_ID)
    
    if not tenant_id:
        missing.append("SHAREPOINT_TENANT_ID")
    if not client_id:
        missing.append("SHAREPOINT_CLIENT_ID")
    if not client_secret:
        missing.append("SHAREPOINT_CLIENT_SECRET")
    if not drive_id:
        missing.append("SHAREPOINT_DRIVE_ID")
    if not item_id:
        missing.append("SHAREPOINT_ITEM_ID")

    try:
        load_knowledge_base()
    except Exception:
        missing.append(f"Knowledge Base file ('{KB_FILE_PATH}')")

    if missing:
        err_msg = "\n❌ CRITICAL PRODUCTION CONFIGURATION ERROR:\n"
        for m in missing:
            err_msg += f"   • Missing or invalid: {m}\n"
        err_msg += "\nPlease check your .env and working directory before running in production."
        raise RuntimeError(err_msg)
    
    print("🛡️ [Pre-Flight Check] All API credentials, Microsoft SharePoint credentials, and Knowledge Base verified!")

def sync_to_local_excel(ranked_leads: List[RankedLead]) -> None:
    """Mirrors the 21-column ranked leads to Local Excel tabs 'latest_week_scoring' and 'Companies scoring'."""
    try:
        from openpyxl import load_workbook
        from openpyxl.styles import PatternFill, Font
        local_path = Path("/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/data/excel/usa_conferences_published.xlsx")
        if not local_path.exists():
            return
        wb = load_workbook(local_path)
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 1. Update latest_week_scoring (strictly current cycle only)
        if "latest_week_scoring" in wb.sheetnames:
            ws_latest = wb["latest_week_scoring"]
            if ws_latest.max_row >= 2:
                ws_latest.delete_rows(2, ws_latest.max_row - 1)
            
            # Write headers
            for col_idx, h in enumerate(CURATED_SHEET_HEADERS, 1):
                cell = ws_latest.cell(row=1, column=col_idx, value=h)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
            
            # Write rows
            for r_idx, lead in enumerate(ranked_leads, 2):
                prof = lead.evaluated_lead.enriched_lead.profile
                row_vals = [
                    lead.rank,
                    lead.overall_score,
                    lead.company_name,
                    lead.domain,
                    lead.conference_name,
                    lead.qualification_status,
                    prof.primary_industry,
                    prof.headcount_tier,
                    lead.speaker_name,
                    lead.job_title,
                    lead.email if lead.email != "Not Available" else "",
                    lead.email_status if lead.email != "Not Available" else "",
                    getattr(lead, "exhibitor_name", "") or "",
                    getattr(lead, "exhibitor_email", "") or "",
                    getattr(lead, "exhibitor_email_status", "") or "",
                    getattr(lead, "attendee_name", "") or "",
                    getattr(lead, "attendee_email", "") or "",
                    getattr(lead, "attendee_email_status", "") or "",
                    lead.linkedin_url if lead.linkedin_url != "Not Available" else "",
                    lead.speaker_id,
                    now_str
                ]
                color = "D9EAD3" if lead.qualification_status == "HIGH_MATCH" else ("FFF2CC" if lead.qualification_status == "MODERATE" else "F3F3F3")
                fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                for c_idx, val in enumerate(row_vals, 1):
                    c = ws_latest.cell(row=r_idx, column=c_idx, value=val)
                    c.fill = fill

        # 2. Append to Companies scoring (deduplicated against existing rows)
        if "Companies scoring" in wb.sheetnames:
            ws_hist = wb["Companies scoring"]
            if ws_hist.max_row < 1 or not ws_hist.cell(row=1, column=1).value:
                for col_idx, h in enumerate(CURATED_SHEET_HEADERS, 1):
                    cell = ws_hist.cell(row=1, column=col_idx, value=h)
                    cell.font = Font(bold=True)
                    cell.fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")

            existing_hist_keys: Set[Tuple[str, str, str]] = set()
            existing_comp_conf: Set[Tuple[str, str]] = set()
            last_non_empty = 1
            for r_idx in range(2, ws_hist.max_row + 1):
                row_vals_existing = [ws_hist.cell(row=r_idx, column=c).value for c in range(1, len(CURATED_SHEET_HEADERS) + 1)]
                if any(v is not None and str(v).strip() != "" for v in row_vals_existing):
                    last_non_empty = r_idx
                    c_name = str(row_vals_existing[2] or "").strip().lower()
                    cf_name = str(row_vals_existing[4] or "").strip().lower()
                    s_id = str(row_vals_existing[19] or "").strip().lower()
                    if c_name or cf_name:
                        existing_hist_keys.add((c_name, cf_name, s_id))
                        existing_comp_conf.add((c_name, cf_name))

            start_row = last_non_empty + 1
            appended_offset = 0
            for lead in ranked_leads:
                c_key = (lead.company_name or "").strip().lower()
                cf_key = (lead.conference_name or "").strip().lower()
                s_key = (lead.speaker_id or "").strip().lower()
                if (c_key, cf_key, s_key) in existing_hist_keys or (cf_key and (c_key, cf_key) in existing_comp_conf):
                    continue
                existing_hist_keys.add((c_key, cf_key, s_key))
                if cf_key:
                    existing_comp_conf.add((c_key, cf_key))
                row_num = start_row + appended_offset
                appended_offset += 1
                prof = lead.evaluated_lead.enriched_lead.profile
                row_vals = [
                    lead.rank,
                    lead.overall_score,
                    lead.company_name,
                    lead.domain,
                    lead.conference_name,
                    lead.qualification_status,
                    prof.primary_industry,
                    prof.headcount_tier,
                    lead.speaker_name,
                    lead.job_title,
                    lead.email if lead.email != "Not Available" else "",
                    lead.email_status if lead.email != "Not Available" else "",
                    getattr(lead, "exhibitor_name", "") or "",
                    getattr(lead, "exhibitor_email", "") or "",
                    getattr(lead, "exhibitor_email_status", "") or "",
                    getattr(lead, "attendee_name", "") or "",
                    getattr(lead, "attendee_email", "") or "",
                    getattr(lead, "attendee_email_status", "") or "",
                    lead.linkedin_url if lead.linkedin_url != "Not Available" else "",
                    lead.speaker_id,
                    now_str
                ]
                color = "D9EAD3" if lead.qualification_status == "HIGH_MATCH" else ("FFF2CC" if lead.qualification_status == "MODERATE" else "F3F3F3")
                fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
                for c_idx, val in enumerate(row_vals, 1):
                    c = ws_hist.cell(row=row_num, column=c_idx, value=val)
                    c.fill = fill

        wb.save(local_path)
        print("💾 [Local Excel] Successfully mirrored rankings to 'latest_week_scoring' and 'Companies scoring'!")

        # 3. Qualified Leads in Local Excel (Score > 50)
        try:
            sync_qualified_leads_to_local_excel(ranked_leads)
        except Exception as e:
            print(f"⚠️ Notice syncing Qualified Leads to Local Excel: {e}")

        # 4. Non -Qualified Leads in Local Excel (Score < 50)
        try:
            sync_non_qualified_leads_to_local_excel(ranked_leads)
        except Exception as e:
            print(f"⚠️ Notice syncing Non -Qualified Leads to Local Excel: {e}")
    except Exception as e:
        print(f"⚠️ Notice mirroring to Local Excel: {e}")

def _load_verified_data_index() -> Tuple[Dict[Tuple[str, str], List[List[Any]]], Dict[str, List[List[Any]]], Dict[str, int]]:
    """Loads Local Excel 'Verified Data' rows indexed by (company, conference) and company."""
    local_path = Path("/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/data/excel/usa_conferences_published.xlsx")
    ver_by_comp_conf: Dict[Tuple[str, str], List[List[Any]]] = {}
    ver_by_comp: Dict[str, List[List[Any]]] = {}
    h_map: Dict[str, int] = {}
    if local_path.exists():
        try:
            from openpyxl import load_workbook
            wb = load_workbook(local_path, data_only=True)
            if "Verified Data" in wb.sheetnames:
                ws_ver = wb["Verified Data"]
                raw_ver = list(ws_ver.iter_rows(values_only=True))
                if raw_ver and len(raw_ver) > 1:
                    headers = [str(h or "").strip().lower().replace(" ", "").replace("_", "") for h in raw_ver[0]]
                    h_map = {name: idx for idx, name in enumerate(headers)}
                    c_col = h_map.get("companyname", 0)
                    cf_col = h_map.get("conferencename", 2)
                    for r in raw_ver[1:]:
                        r_list = list(r)
                        cname = str(r_list[c_col] or "").strip().lower() if len(r_list) > c_col else ""
                        cfname = str(r_list[cf_col] or "").strip().lower() if len(r_list) > cf_col else ""
                        if cname:
                            ver_by_comp.setdefault(cname, []).append(r_list)
                            if cfname:
                                ver_by_comp_conf.setdefault((cname, cfname), []).append(r_list)
            wb.close()
        except Exception:
            pass
    return ver_by_comp_conf, ver_by_comp, h_map


def _is_valid_lead_email(em: str) -> bool:
    clean = (em or "").strip().lower()
    if not clean or "@" not in clean or "." not in clean:
        return False
    if clean in ("not available", "not publicly available", "n/a", "none"):
        return False
    return True


def build_qualified_leads_rows(
    ranked_leads: Optional[List[RankedLead]] = None,
    min_score: float = 50.0
) -> List[List[Any]]:
    """
    Extracts individual qualified lead contacts from scoring results for companies with ICP score strictly > min_score (50.0).
    Adds all relevant lead details for Speakers, Attendees, and Exhibitors across all matching Verified Data rows.
    Deduplicates leads strictly by email.
    Appends the 6 required Outreach Tracking Columns initialized to Pending/empty.
    """
    qualified_rows: List[List[Any]] = []
    seen_emails: Set[str] = set()

    local_path = Path("/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/data/excel/usa_conferences_published.xlsx")
    ver_by_comp_conf, ver_by_comp, h_map = _load_verified_data_index()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _append_contact(rank, score, qual, comp, dom, conf, cid, ctype, name, title, email, stat, li, ind, tier, eval_at):
        if not _is_valid_lead_email(email):
            return
        clean_em = email.strip().lower()
        if clean_em in seen_emails:
            return
        seen_emails.add(clean_em)
        n_str = str(name or "").strip()
        if n_str.lower() in ("not publicly available", "not available", "n/a"):
            n_str = ""
        t_str = str(title or "").strip()
        if t_str.lower() in ("not publicly available", "not available", "n/a"):
            t_str = ""
        qualified_rows.append([
            rank, score, qual, comp, dom, conf, cid,
            ctype, n_str, t_str, clean_em, stat or "Verified", li,
            ind, tier, eval_at,
            "Pending", "", "", "", "", ""
        ])

    if ranked_leads:
        for lead in ranked_leads:
            score = float(lead.overall_score or 0.0)
            if score <= min_score:
                continue

            prof = lead.evaluated_lead.enriched_lead.profile
            comp = lead.company_name
            dom = lead.domain
            conf = lead.conference_name
            rank = lead.rank
            qual = lead.qualification_status
            ind = prof.primary_industry
            tier = prof.headcount_tier
            spk_id = lead.speaker_id

            matched_rows = ver_by_comp_conf.get((comp.lower(), conf.lower())) or ver_by_comp.get(comp.lower(), [])
            first_v = matched_rows[0] if matched_rows else []
            cid = (first_v[h_map.get("conferenceid", 3)] if len(first_v) > h_map.get("conferenceid", 3) and first_v[h_map.get("conferenceid", 3)] else spk_id)

            # 1. Contacts directly carried on RankedLead
            spk_title_0 = str(first_v[h_map.get("speakerjobtitle", 5)] or "") if len(first_v) > h_map.get("speakerjobtitle", 5) else ""
            spk_li_0 = str(first_v[h_map.get("speakerlinkedin", 6)] or "") if len(first_v) > h_map.get("speakerlinkedin", 6) else ""
            _append_contact(
                rank, score, qual, comp, dom, conf, cid,
                "Speaker", lead.speaker_name, lead.job_title or spk_title_0,
                lead.email if lead.email != "Not Available" else "",
                lead.email_status if lead.email != "Not Available" else "Verified",
                (lead.linkedin_url if lead.linkedin_url != "Not Available" else "") or spk_li_0,
                ind, tier, now_str,
            )
            att_title_0 = str(first_v[h_map.get("attendeejobtitle", 16)] or "") if len(first_v) > h_map.get("attendeejobtitle", 16) else ""
            att_li_0 = str(first_v[h_map.get("attendeelinkedin", 17)] or "") if len(first_v) > h_map.get("attendeelinkedin", 17) else ""
            _append_contact(
                rank, score, qual, comp, dom, conf, cid,
                "Attendee", getattr(lead, "attendee_name", ""), att_title_0,
                getattr(lead, "attendee_email", ""),
                getattr(lead, "attendee_email_status", "") or "Verified",
                att_li_0,
                ind, tier, now_str,
            )
            exh_title_0 = str(first_v[h_map.get("exhibitorjobtitle", 27)] or "") if len(first_v) > h_map.get("exhibitorjobtitle", 27) else ""
            exh_li_0 = str(first_v[h_map.get("exhibitorlinkedin", 28)] or "") if len(first_v) > h_map.get("exhibitorlinkedin", 28) else ""
            _append_contact(
                rank, score, qual, comp, dom, conf, cid,
                "Exhibitor", getattr(lead, "exhibitor_name", ""), exh_title_0,
                getattr(lead, "exhibitor_email", ""),
                getattr(lead, "exhibitor_email_status", "") or "Verified",
                exh_li_0,
                ind, tier, now_str,
            )

            # 2. All additional verified contacts in Verified Data for this company (+ conference)
            for v_row in matched_rows:
                row_cid = (v_row[h_map.get("conferenceid", 3)] if len(v_row) > h_map.get("conferenceid", 3) and v_row[h_map.get("conferenceid", 3)] else cid)
                _append_contact(
                    rank, score, qual, comp, dom, conf, row_cid, "Speaker",
                    str(v_row[h_map.get("speakername", 4)] or "") if len(v_row) > h_map.get("speakername", 4) else "",
                    str(v_row[h_map.get("speakerjobtitle", 5)] or "") if len(v_row) > h_map.get("speakerjobtitle", 5) else "",
                    str(v_row[h_map.get("speakerprofessionalemail", 7)] or "") if len(v_row) > h_map.get("speakerprofessionalemail", 7) else "",
                    str(v_row[h_map.get("speakeremailstatus", 8)] or "Verified") if len(v_row) > h_map.get("speakeremailstatus", 8) else "Verified",
                    str(v_row[h_map.get("speakerlinkedin", 6)] or "") if len(v_row) > h_map.get("speakerlinkedin", 6) else "",
                    ind, tier, now_str,
                )
                _append_contact(
                    rank, score, qual, comp, dom, conf, row_cid, "Attendee",
                    str(v_row[h_map.get("attendeename", 15)] or "") if len(v_row) > h_map.get("attendeename", 15) else "",
                    str(v_row[h_map.get("attendeejobtitle", 16)] or "") if len(v_row) > h_map.get("attendeejobtitle", 16) else "",
                    str(v_row[h_map.get("attendeeprofessionalemail", 18)] or "") if len(v_row) > h_map.get("attendeeprofessionalemail", 18) else "",
                    str(v_row[h_map.get("attendeeemailstatus", 19)] or "Verified") if len(v_row) > h_map.get("attendeeemailstatus", 19) else "Verified",
                    str(v_row[h_map.get("attendeelinkedin", 17)] or "") if len(v_row) > h_map.get("attendeelinkedin", 17) else "",
                    ind, tier, now_str,
                )
                _append_contact(
                    rank, score, qual, comp, dom, conf, row_cid, "Exhibitor",
                    str(v_row[h_map.get("exhibitorname", 26)] or "") if len(v_row) > h_map.get("exhibitorname", 26) else "",
                    str(v_row[h_map.get("exhibitorjobtitle", 27)] or "") if len(v_row) > h_map.get("exhibitorjobtitle", 27) else "",
                    str(v_row[h_map.get("exhibitorprofessionalemail", 29)] or "") if len(v_row) > h_map.get("exhibitorprofessionalemail", 29) else "",
                    str(v_row[h_map.get("exhibitoremailstatus", 30)] or "Verified") if len(v_row) > h_map.get("exhibitoremailstatus", 30) else "Verified",
                    str(v_row[h_map.get("exhibitorlinkedin", 28)] or "") if len(v_row) > h_map.get("exhibitorlinkedin", 28) else "",
                    ind, tier, now_str,
                )

    else:
        # Fallback: extract from local Excel latest_week_scoring
        if local_path.exists():
            try:
                from openpyxl import load_workbook
                wb = load_workbook(local_path, data_only=True)
                if "latest_week_scoring" in wb.sheetnames:
                    ws_score = wb["latest_week_scoring"]
                    for r in range(2, ws_score.max_row + 1):
                        vals = [c.value for c in ws_score[r]]
                        if not any(vals):
                            continue
                        try:
                            score = float(vals[1] or 0.0)
                        except (ValueError, TypeError):
                            continue
                        if score <= min_score:
                            continue
                        rank = vals[0]
                        comp = str(vals[2] or "").strip()
                        dom = str(vals[3] or "").strip()
                        conf = str(vals[4] or "").strip()
                        qual = str(vals[5] or "").strip()
                        ind = str(vals[6] or "").strip()
                        tier = str(vals[7] or "").strip()
                        spk_id = str(vals[19] or "").strip()
                        eval_at = str(vals[20] or "").strip() or now_str

                        matched_rows = ver_by_comp_conf.get((comp.lower(), conf.lower())) or ver_by_comp.get(comp.lower(), [])
                        first_v = matched_rows[0] if matched_rows else []
                        cid = first_v[h_map.get("conferenceid", 3)] if len(first_v) > h_map.get("conferenceid", 3) and first_v[h_map.get("conferenceid", 3)] else spk_id

                        _append_contact(
                            rank, score, qual, comp, dom, conf, cid, "Speaker",
                            vals[8], vals[9], vals[10], vals[11], vals[18], ind, tier, eval_at
                        )
                        _append_contact(
                            rank, score, qual, comp, dom, conf, cid, "Attendee",
                            vals[15], "", vals[16], vals[17], "", ind, tier, eval_at
                        )
                        _append_contact(
                            rank, score, qual, comp, dom, conf, cid, "Exhibitor",
                            vals[12], "", vals[13], vals[14], "", ind, tier, eval_at
                        )
                        for v_row in matched_rows:
                            row_cid = v_row[h_map.get("conferenceid", 3)] if len(v_row) > h_map.get("conferenceid", 3) and v_row[h_map.get("conferenceid", 3)] else cid
                            _append_contact(
                                rank, score, qual, comp, dom, conf, row_cid, "Speaker",
                                str(v_row[h_map.get("speakername", 4)] or "") if len(v_row) > h_map.get("speakername", 4) else "",
                                str(v_row[h_map.get("speakerjobtitle", 5)] or "") if len(v_row) > h_map.get("speakerjobtitle", 5) else "",
                                str(v_row[h_map.get("speakerprofessionalemail", 7)] or "") if len(v_row) > h_map.get("speakerprofessionalemail", 7) else "",
                                str(v_row[h_map.get("speakeremailstatus", 8)] or "Verified") if len(v_row) > h_map.get("speakeremailstatus", 8) else "Verified",
                                str(v_row[h_map.get("speakerlinkedin", 6)] or "") if len(v_row) > h_map.get("speakerlinkedin", 6) else "",
                                ind, tier, eval_at,
                            )
                            _append_contact(
                                rank, score, qual, comp, dom, conf, row_cid, "Attendee",
                                str(v_row[h_map.get("attendeename", 15)] or "") if len(v_row) > h_map.get("attendeename", 15) else "",
                                str(v_row[h_map.get("attendeejobtitle", 16)] or "") if len(v_row) > h_map.get("attendeejobtitle", 16) else "",
                                str(v_row[h_map.get("attendeeprofessionalemail", 18)] or "") if len(v_row) > h_map.get("attendeeprofessionalemail", 18) else "",
                                str(v_row[h_map.get("attendeeemailstatus", 19)] or "Verified") if len(v_row) > h_map.get("attendeeemailstatus", 19) else "Verified",
                                str(v_row[h_map.get("attendeelinkedin", 17)] or "") if len(v_row) > h_map.get("attendeelinkedin", 17) else "",
                                ind, tier, eval_at,
                            )
                            _append_contact(
                                rank, score, qual, comp, dom, conf, row_cid, "Exhibitor",
                                str(v_row[h_map.get("exhibitorname", 26)] or "") if len(v_row) > h_map.get("exhibitorname", 26) else "",
                                str(v_row[h_map.get("exhibitorjobtitle", 27)] or "") if len(v_row) > h_map.get("exhibitorjobtitle", 27) else "",
                                str(v_row[h_map.get("exhibitorprofessionalemail", 29)] or "") if len(v_row) > h_map.get("exhibitorprofessionalemail", 29) else "",
                                str(v_row[h_map.get("exhibitoremailstatus", 30)] or "Verified") if len(v_row) > h_map.get("exhibitoremailstatus", 30) else "Verified",
                                str(v_row[h_map.get("exhibitorlinkedin", 28)] or "") if len(v_row) > h_map.get("exhibitorlinkedin", 28) else "",
                                ind, tier, eval_at,
                            )
                wb.close()
            except Exception:
                pass

    return qualified_rows


def _align_lead_rows_to_headers(
    raw_headers: List[str],
    raw_rows: List[List[Any]],
    target_headers: List[str],
) -> List[List[Any]]:
    """Aligns SharePoint table/range rows by normalized header name into target_headers order."""
    if not raw_rows:
        return []
    if not raw_headers:
        return [list(r)[:len(target_headers)] for r in raw_rows if any(r)]
    h_map = {
        str(h or "").strip().lower().replace(" ", "").replace("_", "").replace("replay", "reply"): idx
        for idx, h in enumerate(raw_headers)
    }
    target_norm = [h.lower().replace(" ", "").replace("_", "") for h in target_headers]
    aligned_rows: List[List[Any]] = []
    for r in raw_rows:
        if not any(r):
            continue
        aligned: List[Any] = []
        for nh in target_norm:
            src_idx = h_map.get(nh)
            if src_idx is None and nh == "professionalemail":
                src_idx = h_map.get("email")
            elif src_idx is None and nh == "contactname":
                src_idx = h_map.get("name")
            elif src_idx is None and nh == "replysentiment":
                src_idx = h_map.get("sentiment")
            aligned.append(r[src_idx] if src_idx is not None and src_idx < len(r) else "")
        aligned_rows.append(aligned)
    return aligned_rows


def _union_merge_sharepoint_lead_rows(
    existing_rows: List[List[Any]],
    incoming_rows: List[List[Any]],
    headers: List[str],
    default_status: str = "Pending",
) -> List[List[Any]]:
    """
    Union-merges existing historical SharePoint lead rows with newly scored incoming rows
    using lowercase Professional_Email (or Company+Contact+Conference fallback),
    preserving outreach tracking states with precedence replied > bounced > sent > sending > failed > pending/disqualified.
    Sorts descending by Overall_Score and reassigns Rank 1..N.
    """
    cur_h_map = {h.lower().replace(" ", "").replace("_", ""): idx for idx, h in enumerate(headers)}
    em_col = cur_h_map.get("professionalemail", 10)
    comp_col = cur_h_map.get("companyname", 3)
    name_col = cur_h_map.get("contactname", 8)
    conf_col = cur_h_map.get("conferencename", 5)
    score_col = cur_h_map.get("overallscore", 1)
    ost_col = cur_h_map.get("outreachstatus", 16)
    rep_col = cur_h_map.get("replystatus", 17)
    rec_col = cur_h_map.get("receivedreply", 18)
    sent_col = cur_h_map.get("replysentiment", 19)
    th_col = cur_h_map.get("threadid", 20)
    snd_col = cur_h_map.get("sendmessage", 21)

    precedence = {
        "replied": 5,
        "bounced": 4,
        "do_not_contact": 4,
        "sent": 3,
        "sending": 2,
        "failed": 1,
        "pending": 0,
        "disqualified": 0,
        "": -1,
    }

    def _row_key(row_vals: List[Any]) -> str:
        em = str(row_vals[em_col] or "").strip().lower()
        if em and "@" in em:
            return f"em:{em}"
        comp = str(row_vals[comp_col] or "").strip().lower()
        name = str(row_vals[name_col] or "").strip().lower()
        conf = str(row_vals[conf_col] or "").strip().lower()
        return f"alt:{comp}|{name}|{conf}"

    merged_map: Dict[str, List[Any]] = {}
    order_keys: List[str] = []

    for r in existing_rows:
        padded = list(r)
        while len(padded) < len(headers):
            padded.append("")
        padded = padded[:len(headers)]
        if not any(padded[1:]):
            continue
        k = _row_key(padded)
        if not k or k == "alt:||":
            continue
        if k not in merged_map:
            merged_map[k] = padded
            order_keys.append(k)

    for r in incoming_rows:
        padded = list(r)
        while len(padded) < len(headers):
            padded.append("")
        padded = padded[:len(headers)]
        k = _row_key(padded)
        if not k or k == "alt:||":
            continue

        if k not in merged_map:
            merged_map[k] = padded
            order_keys.append(k)
        else:
            prev = merged_map[k]
            for idx in range(len(headers)):
                if idx in (ost_col, rep_col, rec_col, sent_col, th_col, snd_col):
                    continue
                if (padded[idx] is None or str(padded[idx]).strip() == "") and prev[idx] not in (None, ""):
                    padded[idx] = prev[idx]

            prev_st = str(prev[ost_col] or "").strip()
            new_st = str(padded[ost_col] or "").strip()
            if precedence.get(prev_st.lower(), 0) >= precedence.get(new_st.lower(), 0):
                if prev_st:
                    padded[ost_col] = prev_st
            if not padded[ost_col]:
                padded[ost_col] = default_status

            for track_idx in (rep_col, rec_col, sent_col, th_col, snd_col):
                if str(prev[track_idx] or "").strip() and not str(padded[track_idx] or "").strip():
                    padded[track_idx] = prev[track_idx]

            merged_map[k] = padded

    merged_list = [merged_map[k] for k in order_keys]

    def _score_val(row_vals: List[Any]) -> float:
        try:
            return float(row_vals[score_col] or 0.0)
        except (ValueError, TypeError):
            return 0.0

    merged_list.sort(key=lambda row_vals: (-_score_val(row_vals), str(row_vals[comp_col] or "").lower()))
    for rank_idx, row_vals in enumerate(merged_list, 1):
        row_vals[0] = rank_idx
    return merged_list


def sync_qualified_leads_to_local_excel(ranked_leads: Optional[List[RankedLead]] = None) -> int:
    """Mirrors qualified leads (score > 50) to Local Excel 'Qualified Leads' worksheet with outreach tracking columns."""
    from ..storage.excel_manager import ExcelManager
    em = ExcelManager()
    qualified_rows = build_qualified_leads_rows(ranked_leads, min_score=50.0)
    em.sync_qualified_leads_to_excel(qualified_rows, headers=QUALIFIED_LEADS_HEADERS)
    return len(qualified_rows)


def export_qualified_leads_to_sharepoint(
    client: SharePointExcelClient,
    ranked_leads: Optional[List[RankedLead]] = None
) -> int:
    """Exports union-merged qualified leads (score > 50) to SharePoint 'Qualified Leads' preserving historical rows & outreach tracking."""
    sheet_name = os.getenv("SHAREPOINT_QUALIFIED_SHEET", SHAREPOINT_QUALIFIED_SHEET)
    client.ensure_worksheet_exists(sheet_name)
    qualified_rows = build_qualified_leads_rows(ranked_leads, min_score=50.0)
    if not qualified_rows:
        return 0

    ex_headers, ex_rows = client.get_table_records("tbl_qualified_leads", fallback_sheet_name=sheet_name)
    aligned_existing = _align_lead_rows_to_headers(ex_headers, ex_rows, QUALIFIED_LEADS_HEADERS)
    merged_rows = _union_merge_sharepoint_lead_rows(
        aligned_existing, qualified_rows, QUALIFIED_LEADS_HEADERS, default_status="Pending"
    )

    all_data = [QUALIFIED_LEADS_HEADERS] + merged_rows
    last_col = col_num_to_letter(len(QUALIFIED_LEADS_HEADERS))
    clear_end = max(500, len(all_data) + 50, len(ex_rows) + 50)

    client.delete_sheet_tables(sheet_name, ["tbl_qualified_leads"])
    client.clear_range(sheet_name, f"A1:{last_col}{clear_end}")
    client.update_range(sheet_name, f"A1:{last_col}{len(all_data)}", all_data)
    client.format_range_fill(sheet_name, f"A1:{last_col}1", "#D9E1F2")
    client.format_range_font(sheet_name, f"A1:{last_col}1", bold=True)
    client.format_range_font(sheet_name, f"A2:{last_col}{len(all_data)}", bold=False)

    # Chunk fill colors across contiguous runs to minimize Graph API PATCH calls
    current_color = None
    chunk_start = 2
    for idx, q in enumerate(merged_rows, 2):
        try:
            q_score = float(q[1] or 0.0)
        except (ValueError, TypeError):
            q_score = 0.0
        row_color = "#D9EAD3" if str(q[2]).upper() == "HIGH_MATCH" or q_score >= 75.0 else "#FFF2CC"
        if current_color is None:
            current_color = row_color
            chunk_start = idx
        elif row_color != current_color:
            client.format_range_fill(sheet_name, f"A{chunk_start}:{last_col}{idx - 1}", current_color)
            current_color = row_color
            chunk_start = idx
    if current_color is not None:
        client.format_range_fill(sheet_name, f"A{chunk_start}:{last_col}{len(all_data)}", current_color)

    client.create_and_name_table(sheet_name, f"A1:{last_col}{len(all_data)}", "tbl_qualified_leads", style="TableStyleMedium2")
    print(f"🌟 [SharePoint] '{sheet_name}' union-synced {len(merged_rows)} total qualified leads ({len(qualified_rows)} incoming, score > 50)!")
    return len(merged_rows)


def build_and_sync_qualified_leads(ranked_leads: Optional[List[RankedLead]] = None) -> Dict[str, Any]:
    """Generates Qualified Leads (score > 50) and syncs both Local Excel and SharePoint."""
    client = get_sharepoint_client()
    local_count = sync_qualified_leads_to_local_excel(ranked_leads)
    sp_count = export_qualified_leads_to_sharepoint(client, ranked_leads)
    return {"status": "success", "local_count": local_count, "sharepoint_count": sp_count}


def build_non_qualified_leads_rows(
    ranked_leads: Optional[List[RankedLead]] = None,
    max_score: float = 50.0
) -> List[List[Any]]:
    """
    Extracts individual non-qualified / disqualified lead contacts from scoring results with ICP score strictly < max_score (50.0).
    Adds all relevant lead details for Speakers, Attendees, and Exhibitors across all matching Verified Data rows.
    Deduplicates leads strictly by email.
    Appends the 6 required Outreach Tracking Columns initialized to Disqualified/empty.
    """
    non_qual_rows: List[List[Any]] = []
    seen_emails: Set[str] = set()

    local_path = Path("/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/data/excel/usa_conferences_published.xlsx")
    ver_by_comp_conf, ver_by_comp, h_map = _load_verified_data_index()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _append_contact(rank, score, qual, comp, dom, conf, cid, ctype, name, title, email, stat, li, ind, tier, eval_at):
        if not _is_valid_lead_email(email):
            return
        clean_em = email.strip().lower()
        if clean_em in seen_emails:
            return
        seen_emails.add(clean_em)
        n_str = str(name or "").strip()
        if n_str.lower() in ("not publicly available", "not available", "n/a"):
            n_str = ""
        t_str = str(title or "").strip()
        if t_str.lower() in ("not publicly available", "not available", "n/a"):
            t_str = ""
        non_qual_rows.append([
            rank, score, qual, comp, dom, conf, cid,
            ctype, n_str, t_str, clean_em, stat or "Verified", li,
            ind, tier, eval_at,
            "Disqualified", "", "", "", "", ""
        ])

    if ranked_leads:
        for lead in ranked_leads:
            score = float(lead.overall_score or 0.0)
            if score >= max_score:
                continue

            prof = lead.evaluated_lead.enriched_lead.profile
            comp = lead.company_name
            dom = lead.domain
            conf = lead.conference_name
            rank = lead.rank
            qual = lead.qualification_status
            ind = prof.primary_industry
            tier = prof.headcount_tier
            spk_id = lead.speaker_id

            matched_rows = ver_by_comp_conf.get((comp.lower(), conf.lower())) or ver_by_comp.get(comp.lower(), [])
            first_v = matched_rows[0] if matched_rows else []
            cid = first_v[h_map.get("conferenceid", 3)] if len(first_v) > h_map.get("conferenceid", 3) and first_v[h_map.get("conferenceid", 3)] else spk_id

            # 1. Contacts directly carried on RankedLead
            spk_title_0 = str(first_v[h_map.get("speakerjobtitle", 5)] or "") if len(first_v) > h_map.get("speakerjobtitle", 5) else ""
            spk_li_0 = str(first_v[h_map.get("speakerlinkedin", 6)] or "") if len(first_v) > h_map.get("speakerlinkedin", 6) else ""
            _append_contact(
                rank, score, qual, comp, dom, conf, cid,
                "Speaker", lead.speaker_name, lead.job_title or spk_title_0,
                lead.email if lead.email != "Not Available" else "",
                lead.email_status if lead.email != "Not Available" else "Verified",
                (lead.linkedin_url if lead.linkedin_url != "Not Available" else "") or spk_li_0,
                ind, tier, now_str,
            )
            att_title_0 = str(first_v[h_map.get("attendeejobtitle", 16)] or "") if len(first_v) > h_map.get("attendeejobtitle", 16) else ""
            att_li_0 = str(first_v[h_map.get("attendeelinkedin", 17)] or "") if len(first_v) > h_map.get("attendeelinkedin", 17) else ""
            _append_contact(
                rank, score, qual, comp, dom, conf, cid,
                "Attendee", getattr(lead, "attendee_name", ""), att_title_0,
                getattr(lead, "attendee_email", ""),
                getattr(lead, "attendee_email_status", "") or "Verified",
                att_li_0,
                ind, tier, now_str,
            )
            exh_title_0 = str(first_v[h_map.get("exhibitorjobtitle", 27)] or "") if len(first_v) > h_map.get("exhibitorjobtitle", 27) else ""
            exh_li_0 = str(first_v[h_map.get("exhibitorlinkedin", 28)] or "") if len(first_v) > h_map.get("exhibitorlinkedin", 28) else ""
            _append_contact(
                rank, score, qual, comp, dom, conf, cid,
                "Exhibitor", getattr(lead, "exhibitor_name", ""), exh_title_0,
                getattr(lead, "exhibitor_email", ""),
                getattr(lead, "exhibitor_email_status", "") or "Verified",
                exh_li_0,
                ind, tier, now_str,
            )

            # 2. All additional verified contacts in Verified Data for this company (+ conference)
            for v_row in matched_rows:
                row_cid = v_row[h_map.get("conferenceid", 3)] if len(v_row) > h_map.get("conferenceid", 3) and v_row[h_map.get("conferenceid", 3)] else cid
                _append_contact(
                    rank, score, qual, comp, dom, conf, row_cid, "Speaker",
                    str(v_row[h_map.get("speakername", 4)] or "") if len(v_row) > h_map.get("speakername", 4) else "",
                    str(v_row[h_map.get("speakerjobtitle", 5)] or "") if len(v_row) > h_map.get("speakerjobtitle", 5) else "",
                    str(v_row[h_map.get("speakerprofessionalemail", 7)] or "") if len(v_row) > h_map.get("speakerprofessionalemail", 7) else "",
                    str(v_row[h_map.get("speakeremailstatus", 8)] or "Verified") if len(v_row) > h_map.get("speakeremailstatus", 8) else "Verified",
                    str(v_row[h_map.get("speakerlinkedin", 6)] or "") if len(v_row) > h_map.get("speakerlinkedin", 6) else "",
                    ind, tier, now_str,
                )
                _append_contact(
                    rank, score, qual, comp, dom, conf, row_cid, "Attendee",
                    str(v_row[h_map.get("attendeename", 15)] or "") if len(v_row) > h_map.get("attendeename", 15) else "",
                    str(v_row[h_map.get("attendeejobtitle", 16)] or "") if len(v_row) > h_map.get("attendeejobtitle", 16) else "",
                    str(v_row[h_map.get("attendeeprofessionalemail", 18)] or "") if len(v_row) > h_map.get("attendeeprofessionalemail", 18) else "",
                    str(v_row[h_map.get("attendeeemailstatus", 19)] or "Verified") if len(v_row) > h_map.get("attendeeemailstatus", 19) else "Verified",
                    str(v_row[h_map.get("attendeelinkedin", 17)] or "") if len(v_row) > h_map.get("attendeelinkedin", 17) else "",
                    ind, tier, now_str,
                )
                _append_contact(
                    rank, score, qual, comp, dom, conf, row_cid, "Exhibitor",
                    str(v_row[h_map.get("exhibitorname", 26)] or "") if len(v_row) > h_map.get("exhibitorname", 26) else "",
                    str(v_row[h_map.get("exhibitorjobtitle", 27)] or "") if len(v_row) > h_map.get("exhibitorjobtitle", 27) else "",
                    str(v_row[h_map.get("exhibitorprofessionalemail", 29)] or "") if len(v_row) > h_map.get("exhibitorprofessionalemail", 29) else "",
                    str(v_row[h_map.get("exhibitoremailstatus", 30)] or "Verified") if len(v_row) > h_map.get("exhibitoremailstatus", 30) else "Verified",
                    str(v_row[h_map.get("exhibitorlinkedin", 28)] or "") if len(v_row) > h_map.get("exhibitorlinkedin", 28) else "",
                    ind, tier, now_str,
                )

    else:
        if local_path.exists():
            try:
                from openpyxl import load_workbook
                wb = load_workbook(local_path, data_only=True)
                if "latest_week_scoring" in wb.sheetnames:
                    ws_score = wb["latest_week_scoring"]
                    for r in range(2, ws_score.max_row + 1):
                        vals = [c.value for c in ws_score[r]]
                        if not any(vals):
                            continue
                        try:
                            score = float(vals[1] or 0.0)
                        except (ValueError, TypeError):
                            continue
                        if score >= max_score:
                            continue
                        rank = vals[0]
                        comp = str(vals[2] or "").strip()
                        dom = str(vals[3] or "").strip()
                        conf = str(vals[4] or "").strip()
                        qual = str(vals[5] or "").strip()
                        ind = str(vals[6] or "").strip()
                        tier = str(vals[7] or "").strip()
                        spk_id = str(vals[19] or "").strip()
                        eval_at = str(vals[20] or "").strip() or now_str

                        matched_rows = ver_by_comp_conf.get((comp.lower(), conf.lower())) or ver_by_comp.get(comp.lower(), [])
                        first_v = matched_rows[0] if matched_rows else []
                        cid = first_v[h_map.get("conferenceid", 3)] if len(first_v) > h_map.get("conferenceid", 3) and first_v[h_map.get("conferenceid", 3)] else spk_id

                        _append_contact(
                            rank, score, qual, comp, dom, conf, cid, "Speaker",
                            vals[8], vals[9], vals[10], vals[11], vals[18], ind, tier, eval_at
                        )
                        _append_contact(
                            rank, score, qual, comp, dom, conf, cid, "Attendee",
                            vals[15], "", vals[16], vals[17], "", ind, tier, eval_at
                        )
                        _append_contact(
                            rank, score, qual, comp, dom, conf, cid, "Exhibitor",
                            vals[12], "", vals[13], vals[14], "", ind, tier, eval_at
                        )
                        for v_row in matched_rows:
                            row_cid = v_row[h_map.get("conferenceid", 3)] if len(v_row) > h_map.get("conferenceid", 3) and v_row[h_map.get("conferenceid", 3)] else cid
                            _append_contact(
                                rank, score, qual, comp, dom, conf, row_cid, "Speaker",
                                str(v_row[h_map.get("speakername", 4)] or "") if len(v_row) > h_map.get("speakername", 4) else "",
                                str(v_row[h_map.get("speakerjobtitle", 5)] or "") if len(v_row) > h_map.get("speakerjobtitle", 5) else "",
                                str(v_row[h_map.get("speakerprofessionalemail", 7)] or "") if len(v_row) > h_map.get("speakerprofessionalemail", 7) else "",
                                str(v_row[h_map.get("speakeremailstatus", 8)] or "Verified") if len(v_row) > h_map.get("speakeremailstatus", 8) else "Verified",
                                str(v_row[h_map.get("speakerlinkedin", 6)] or "") if len(v_row) > h_map.get("speakerlinkedin", 6) else "",
                                ind, tier, eval_at,
                            )
                            _append_contact(
                                rank, score, qual, comp, dom, conf, row_cid, "Attendee",
                                str(v_row[h_map.get("attendeename", 15)] or "") if len(v_row) > h_map.get("attendeename", 15) else "",
                                str(v_row[h_map.get("attendeejobtitle", 16)] or "") if len(v_row) > h_map.get("attendeejobtitle", 16) else "",
                                str(v_row[h_map.get("attendeeprofessionalemail", 18)] or "") if len(v_row) > h_map.get("attendeeprofessionalemail", 18) else "",
                                str(v_row[h_map.get("attendeeemailstatus", 19)] or "Verified") if len(v_row) > h_map.get("attendeeemailstatus", 19) else "Verified",
                                str(v_row[h_map.get("attendeelinkedin", 17)] or "") if len(v_row) > h_map.get("attendeelinkedin", 17) else "",
                                ind, tier, eval_at,
                            )
                            _append_contact(
                                rank, score, qual, comp, dom, conf, row_cid, "Exhibitor",
                                str(v_row[h_map.get("exhibitorname", 26)] or "") if len(v_row) > h_map.get("exhibitorname", 26) else "",
                                str(v_row[h_map.get("exhibitorjobtitle", 27)] or "") if len(v_row) > h_map.get("exhibitorjobtitle", 27) else "",
                                str(v_row[h_map.get("exhibitorprofessionalemail", 29)] or "") if len(v_row) > h_map.get("exhibitorprofessionalemail", 29) else "",
                                str(v_row[h_map.get("exhibitoremailstatus", 30)] or "Verified") if len(v_row) > h_map.get("exhibitoremailstatus", 30) else "Verified",
                                str(v_row[h_map.get("exhibitorlinkedin", 28)] or "") if len(v_row) > h_map.get("exhibitorlinkedin", 28) else "",
                                ind, tier, eval_at,
                            )
                wb.close()
            except Exception:
                pass

    return non_qual_rows


def sync_non_qualified_leads_to_local_excel(ranked_leads: Optional[List[RankedLead]] = None) -> int:
    """Mirrors non-qualified leads (score < 50) to Local Excel 'Non -Qualified Leads' worksheet with outreach tracking columns."""
    from ..storage.excel_manager import ExcelManager
    em = ExcelManager()
    non_qual_rows = build_non_qualified_leads_rows(ranked_leads, max_score=50.0)
    em.sync_non_qualified_leads_to_excel(non_qual_rows, headers=QUALIFIED_LEADS_HEADERS)
    return len(non_qual_rows)


def export_non_qualified_leads_to_sharepoint(
    client: SharePointExcelClient,
    ranked_leads: Optional[List[RankedLead]] = None
) -> int:
    """Exports union-merged non-qualified leads (score < 50) to SharePoint 'Non -Qualified Leads' preserving historical rows & outreach tracking."""
    sheet_name = os.getenv("SHAREPOINT_NON_QUALIFIED_SHEET", SHAREPOINT_NON_QUALIFIED_SHEET)
    client.ensure_worksheet_exists(sheet_name)
    non_qual_rows = build_non_qualified_leads_rows(ranked_leads, max_score=50.0)
    if not non_qual_rows:
        return 0

    ex_headers, ex_rows = client.get_table_records("tbl_non_qualified_leads", fallback_sheet_name=sheet_name)
    aligned_existing = _align_lead_rows_to_headers(ex_headers, ex_rows, QUALIFIED_LEADS_HEADERS)
    merged_rows = _union_merge_sharepoint_lead_rows(
        aligned_existing, non_qual_rows, QUALIFIED_LEADS_HEADERS, default_status="Disqualified"
    )

    all_data = [QUALIFIED_LEADS_HEADERS] + merged_rows
    last_col = col_num_to_letter(len(QUALIFIED_LEADS_HEADERS))
    clear_end = max(500, len(all_data) + 50, len(ex_rows) + 50)

    client.delete_sheet_tables(sheet_name, ["tbl_non_qualified_leads"])
    client.clear_range(sheet_name, f"A1:{last_col}{clear_end}")
    client.update_range(sheet_name, f"A1:{last_col}{len(all_data)}", all_data)
    client.format_range_fill(sheet_name, f"A1:{last_col}1", "#D9E1F2")
    client.format_range_font(sheet_name, f"A1:{last_col}1", bold=True)
    client.format_range_font(sheet_name, f"A2:{last_col}{len(all_data)}", bold=False)
    client.format_range_fill(sheet_name, f"A2:{last_col}{len(all_data)}", "#FCE5CD")
    client.create_and_name_table(sheet_name, f"A1:{last_col}{len(all_data)}", "tbl_non_qualified_leads", style="TableStyleMedium2")

    print(f"🌟 [SharePoint] '{sheet_name}' union-synced {len(merged_rows)} total non-qualified leads ({len(non_qual_rows)} incoming, score < 50)!")
    return len(merged_rows)

def build_and_sync_non_qualified_leads(ranked_leads: Optional[List[RankedLead]] = None) -> Dict[str, Any]:
    """Generates Non -Qualified Leads (score < 50) and syncs both Local Excel and SharePoint."""
    client = get_sharepoint_client()
    local_count = sync_non_qualified_leads_to_local_excel(ranked_leads)
    sp_count = export_non_qualified_leads_to_sharepoint(client, ranked_leads)
    return {"status": "success", "local_count": local_count, "sharepoint_count": sp_count}

def export_ranked_leads_to_sharepoint(
    client: SharePointExcelClient,
    ranked_leads: List[RankedLead]
) -> int:
    """Exports ALL evaluated leads to two tabs: 'latest_week_scoring' (fresh weekly rankings) and 'Companies scoring' with 21 columns and status color highlights."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def format_row(lead: RankedLead) -> List[Any]:
        prof = lead.evaluated_lead.enriched_lead.profile
        return [
            lead.rank,
            lead.overall_score,
            lead.company_name,
            lead.domain,
            lead.conference_name,
            lead.qualification_status,
            prof.primary_industry,
            prof.headcount_tier,
            lead.speaker_name,
            lead.job_title,
            lead.email if lead.email != "Not Available" else "",
            lead.email_status if lead.email != "Not Available" else "",
            getattr(lead, "exhibitor_name", "") or "",
            getattr(lead, "exhibitor_email", "") or "",
            getattr(lead, "exhibitor_email_status", "") or "",
            getattr(lead, "attendee_name", "") or "",
            getattr(lead, "attendee_email", "") or "",
            getattr(lead, "attendee_email_status", "") or "",
            lead.linkedin_url if lead.linkedin_url != "Not Available" else "",
            lead.speaker_id,
            now_str
        ]

    all_rows_to_insert = [format_row(lead) for lead in ranked_leads]

    if not all_rows_to_insert:
        print("⚠️ No ranked leads to export.")
        return 0

    latest_sheet = os.getenv("SHAREPOINT_LATEST_SHEET", SHAREPOINT_LATEST_SHEET)
    history_sheet = os.getenv("SHAREPOINT_HISTORY_SHEET", SHAREPOINT_HISTORY_SHEET)
    last_col_letter = col_num_to_letter(len(CURATED_SHEET_HEADERS))  # 'U'

    # -----------------------------------------------------------------
    # TAB 1: latest_week_scoring (Cleared and overwritten with current weekly rankings only + Color Highlights)
    # -----------------------------------------------------------------
    print(f"📋 [SharePoint] Refreshing '{latest_sheet}' tab with ALL {len(all_rows_to_insert)} rankings (21 columns)...")
    client.ensure_worksheet_exists(latest_sheet)
    try:
        existing_latest = client.get_used_range(latest_sheet)
    except Exception:
        existing_latest = []
    all_latest_data = [CURATED_SHEET_HEADERS] + all_rows_to_insert
    latest_clear_end = max(500, len(all_latest_data) + 50, len(existing_latest) + 50)
    try:
        client.clear_range(latest_sheet, f"A1:{last_col_letter}{latest_clear_end}")
    except Exception as e:
        print(f"⚠️ Notice clearing '{latest_sheet}': {e}")

    latest_range = f"A1:{last_col_letter}{len(all_latest_data)}"
    client.update_range(latest_sheet, latest_range, all_latest_data)
    
    # Format Header Row (Soft Blue + Bold)
    client.format_range_fill(latest_sheet, f"A1:{last_col_letter}1", "#D9E1F2")
    client.format_range_font(latest_sheet, f"A1:{last_col_letter}1", bold=True)
    
    # Reset Data Rows Font to Normal (not bold)
    client.format_range_font(latest_sheet, f"A2:{last_col_letter}{len(all_latest_data)}", bold=False)
    
    # Format Lead Rows (Green for High Match, Yellow for Moderate, Gray for Disqualified)
    apply_sharepoint_color_formatting(client, latest_sheet, start_row=2, ranked_leads=ranked_leads)
    print(f"🎨 [SharePoint] Visual status colors applied to '{latest_sheet}'!")
    print(f"📥 [SharePoint] '{latest_sheet}' tab successfully updated with all {len(all_rows_to_insert)} companies!")

    # -----------------------------------------------------------------
    # TAB 2: Companies scoring (Permanent historical archive, deduplicated + Color Highlights)
    # -----------------------------------------------------------------
    client.ensure_worksheet_exists(history_sheet)
    try:
        existing_history = client.get_used_range(history_sheet)
    except Exception:
        existing_history = []

    if not existing_history:
        all_hist_data = [CURATED_SHEET_HEADERS] + all_rows_to_insert
        client.update_range(history_sheet, f"A1:{last_col_letter}{len(all_hist_data)}", all_hist_data)
        client.format_range_fill(history_sheet, f"A1:{last_col_letter}1", "#D9E1F2")
        client.format_range_font(history_sheet, f"A1:{last_col_letter}1", bold=True)
        apply_sharepoint_color_formatting(client, history_sheet, start_row=2, ranked_leads=ranked_leads)
        print(f"🏛️ [SharePoint] '{history_sheet}' tab archived {len(all_rows_to_insert)} companies with status colors!")
    else:
        existing_hist_keys: Set[Tuple[str, str, str]] = set()
        existing_comp_conf: Set[Tuple[str, str]] = set()
        last_non_empty = 1
        for r_idx, row_vals_existing in enumerate(existing_history[1:], start=2):
            if any(v is not None and str(v).strip() != "" for v in row_vals_existing[:len(CURATED_SHEET_HEADERS)]):
                last_non_empty = r_idx
                c_name = str(row_vals_existing[2] if len(row_vals_existing) > 2 else "").strip().lower()
                cf_name = str(row_vals_existing[4] if len(row_vals_existing) > 4 else "").strip().lower()
                s_id = str(row_vals_existing[19] if len(row_vals_existing) > 19 else "").strip().lower()
                if c_name or cf_name:
                    existing_hist_keys.add((c_name, cf_name, s_id))
                    existing_comp_conf.add((c_name, cf_name))

        leads_to_append: List[RankedLead] = []
        rows_to_append: List[List[Any]] = []
        for lead_obj, row_vals in zip(ranked_leads, all_rows_to_insert):
            c_key = (lead_obj.company_name or "").strip().lower()
            cf_key = (lead_obj.conference_name or "").strip().lower()
            s_key = (lead_obj.speaker_id or "").strip().lower()
            if (c_key, cf_key, s_key) in existing_hist_keys or (cf_key and (c_key, cf_key) in existing_comp_conf):
                continue
            existing_hist_keys.add((c_key, cf_key, s_key))
            if cf_key:
                existing_comp_conf.add((c_key, cf_key))
            leads_to_append.append(lead_obj)
            rows_to_append.append(row_vals)

        if rows_to_append:
            start_row = last_non_empty + 1
            end_row = start_row + len(rows_to_append) - 1
            hist_range = f"A{start_row}:{last_col_letter}{end_row}"
            client.update_range(history_sheet, hist_range, rows_to_append)
            apply_sharepoint_color_formatting(client, history_sheet, start_row=start_row, ranked_leads=leads_to_append)
            print(f"🏛️ [SharePoint] '{history_sheet}' tab appended {len(rows_to_append)} new companies with status colors!")
        else:
            print(f"🏛️ [SharePoint] '{history_sheet}' already contains all {len(all_rows_to_insert)} companies (0 duplicates appended).")

    # Mirror to local Excel (latest_week_scoring, Companies scoring, Qualified Leads)
    sync_to_local_excel(ranked_leads)

    # -----------------------------------------------------------------
    # TAB 3: Qualified Leads (Leads with ICP score > 50 with Outreach Tracking Columns)
    # -----------------------------------------------------------------
    try:
        export_qualified_leads_to_sharepoint(client, ranked_leads)
    except Exception as e:
        print(f"⚠️ Notice exporting Qualified Leads to SharePoint: {e}")

    # -----------------------------------------------------------------
    # TAB 4: Non -Qualified Leads (Leads with ICP score < 50 with Outreach Tracking Columns)
    # -----------------------------------------------------------------
    try:
        export_non_qualified_leads_to_sharepoint(client, ranked_leads)
    except Exception as e:
        print(f"⚠️ Notice exporting Non -Qualified Leads to SharePoint: {e}")

    return len(all_rows_to_insert)

def mark_leads_evaluated_in_sharepoint(
    client: SharePointExcelClient,
    evaluated_speaker_ids: List[str]
) -> None:
    """Marks leads as EVALUATED in the SharePoint Master Sheet ('Verified Data') in a single atomic batch."""
    master_sheet = os.getenv("SHAREPOINT_MASTER_SHEET", SHAREPOINT_MASTER_SHEET)
    print(f"\n🔄 [SharePoint Master Sheet] Updating 'Evaluation_Status' for {len(evaluated_speaker_ids)} leads...")
    
    values = client.get_used_range(master_sheet)
    if not values or len(values) < 1:
        print("⚠️ Master sheet is empty.")
        return
        
    headers = [str(h).strip() for h in values[0]]
    
    if "Evaluation_Status" not in headers:
        status_col_idx = len(headers) + 1
        col_letter = col_num_to_letter(status_col_idx)
        client.update_range(master_sheet, f"{col_letter}1", [["Evaluation_Status"]])
        print(f"   ✓ Created 'Evaluation_Status' column at {col_letter}1")
    else:
        status_col_idx = headers.index("Evaluation_Status") + 1
        col_letter = col_num_to_letter(status_col_idx)

    conf_col_idx = headers.index("Conference ID") if "Conference ID" in headers else (headers.index("Conference_ID") if "Conference_ID" in headers else -1)
    spk_col_idx = headers.index("Speaker Name") if "Speaker Name" in headers else (headers.index("Speaker_Name") if "Speaker_Name" in headers else -1)
    exh_col_idx = headers.index("Exhibitor Name") if "Exhibitor Name" in headers else (headers.index("Exhibitor_Name") if "Exhibitor_Name" in headers else -1)
    att_col_idx = headers.index("Attendee Name") if "Attendee Name" in headers else (headers.index("Attendee_Name") if "Attendee_Name" in headers else -1)
    comp_col_idx = headers.index("Company Name") if "Company Name" in headers else (headers.index("Company_Name") if "Company_Name" in headers else -1)
    explicit_id_col = headers.index("Speaker_ID") if "Speaker_ID" in headers else (headers.index("Speaker ID") if "Speaker ID" in headers else -1)

    target_ids_set = set(str(sid).strip() for sid in evaluated_speaker_ids)
    
    status_values = []
    updated_count = 0
    
    for row_idx, row in enumerate(values[1:], start=2):
        existing_status = row[status_col_idx - 1] if status_col_idx - 1 < len(row) else ""
        
        if explicit_id_col != -1 and explicit_id_col < len(row) and str(row[explicit_id_col]).strip():
            row_spk_id = clean_string(row[explicit_id_col])
        else:
            conf_raw = str(row[conf_col_idx]).strip() if conf_col_idx != -1 and conf_col_idx < len(row) and row[conf_col_idx] is not None else ""
            conf_val = clean_token(conf_raw) if conf_raw else "CONF"
            spk_raw = row[spk_col_idx] if spk_col_idx != -1 and spk_col_idx < len(row) else ""
            exh_raw = row[exh_col_idx] if exh_col_idx != -1 and exh_col_idx < len(row) else ""
            att_raw = row[att_col_idx] if att_col_idx != -1 and att_col_idx < len(row) else ""
            participant_val = clean_token(spk_raw or exh_raw or att_raw or "LEAD")
            comp_val = clean_token(row[comp_col_idx]) if comp_col_idx != -1 and comp_col_idx < len(row) else ""
            row_spk_id = f"{conf_val}_{participant_val}_{comp_val}"
            
        comp_name_val = row[comp_col_idx] if comp_col_idx != -1 and comp_col_idx < len(row) else ""
        
        if row_spk_id in target_ids_set or str(existing_status).strip().upper() in ["EVALUATED", "PROCESSED"]:
            status_values.append(["EVALUATED"])
            if row_spk_id in target_ids_set and str(existing_status).strip().upper() != "EVALUATED":
                updated_count += 1
                print(f"   ✓ Row {row_idx}: {comp_name_val} ({row_spk_id}) marked as EVALUATED")
        else:
            status_values.append([existing_status])

    if status_values:
        client.update_range(master_sheet, f"{col_letter}2:{col_letter}{len(values)}", status_values)
        print(f"✅ [SharePoint Master Sheet] Successfully updated {updated_count} rows as 'EVALUATED'!")

    # Mirror Evaluation_Status to Local Excel
    try:
        from openpyxl import load_workbook
        local_path = Path("/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/data/excel/usa_conferences_published.xlsx")
        if local_path.exists():
            wb = load_workbook(local_path)
            if "Verified Data" in wb.sheetnames:
                ws = wb["Verified Data"]
                raw_rows = list(ws.iter_rows(values_only=False))
                if raw_rows:
                    header_cells = [c.value for c in raw_rows[0]]
                    eval_col = None
                    for ci, hv in enumerate(header_cells, 1):
                        if str(hv).strip().lower() in ("evaluation_status", "evaluation status"):
                            eval_col = ci
                            break
                    if not eval_col:
                        eval_col = len(header_cells) + 1
                        ws.cell(row=1, column=eval_col, value="Evaluation_Status")
                    if len(raw_rows) - 1 == len(status_values):
                        for row_idx, r_cells in enumerate(raw_rows[1:], start=2):
                            ws.cell(row=row_idx, column=eval_col, value=status_values[row_idx - 2][0])
                    else:
                        lh_map = {str(hv or "").strip(): ci - 1 for ci, hv in enumerate(header_cells, 1)}
                        l_cid = lh_map.get("Conference ID", lh_map.get("Conference_ID", -1))
                        l_spk = lh_map.get("Speaker Name", lh_map.get("Speaker_Name", -1))
                        l_exh = lh_map.get("Exhibitor Name", lh_map.get("Exhibitor_Name", -1))
                        l_att = lh_map.get("Attendee Name", lh_map.get("Attendee_Name", -1))
                        l_cmp = lh_map.get("Company Name", lh_map.get("Company_Name", -1))
                        for row_idx, r_cells in enumerate(raw_rows[1:], start=2):
                            r_vals = [c.value for c in r_cells]
                            c_raw = str(r_vals[l_cid]).strip() if l_cid != -1 and l_cid < len(r_vals) and r_vals[l_cid] else ""
                            c_tok = clean_token(c_raw) if c_raw else "CONF"
                            p_raw = (
                                (r_vals[l_spk] if l_spk != -1 and l_spk < len(r_vals) else "")
                                or (r_vals[l_exh] if l_exh != -1 and l_exh < len(r_vals) else "")
                                or (r_vals[l_att] if l_att != -1 and l_att < len(r_vals) else "")
                                or "LEAD"
                            )
                            cmp_tok = clean_token(r_vals[l_cmp]) if l_cmp != -1 and l_cmp < len(r_vals) else ""
                            local_id = f"{c_tok}_{clean_token(p_raw)}_{cmp_tok}"
                            if local_id in target_ids_set:
                                ws.cell(row=row_idx, column=eval_col, value="EVALUATED")
                    wb.save(local_path)
                    print("💾 [Local Excel] Verified Data 'Evaluation_Status' synchronized.")
    except Exception as e:
        print(f"⚠️ Notice mirroring Evaluation_Status to Local Excel: {e}")


# =====================================================================
# 6. NODE CORE IMPLEMENTATION FUNCTIONS
# =====================================================================

# --- NODE 1 CORE LOGIC ---
def node_1_fetch_unprocessed_from_sheet(
    sheet: Any,
    state: PipelineState
) -> Dict[str, Any]:
    if isinstance(sheet, list):
        records_raw = sheet
    elif hasattr(sheet, "get_records"):
        master_sheet_name = os.getenv("SHAREPOINT_MASTER_SHEET", SHAREPOINT_MASTER_SHEET)
        records_raw = sheet.get_records(master_sheet_name)
    elif hasattr(sheet, "get_all_records"):
        records_raw = sheet.get_all_records()
    else:
        raise ValueError(f"Unsupported sheet object: {type(sheet)}")

    already_processed: Set[str] = state.get("processed_speaker_ids", set())
    
    clean_leads: List[SpeakerRecord] = []
    company_leads_map: Dict[str, SpeakerRecord] = {}
    seen_ids: Set[str] = set()
    seen_name_companies: Set[str] = set()
    
    skipped_evaluated = 0
    duplicates_count = 0
    invalid_rows_count = 0

    print(f"\n🧹 [Node 1] Ingesting & Checking Master Sheet ({len(records_raw)} rows)...")

    for row in records_raw:
        def get_field(*keys):
            for k in keys:
                if k in row and row[k] is not None and str(row[k]).strip() != "":
                    return row[k]
            return ""

        eval_status = str(get_field(
            "Evaluation_Status", "Evaluation Status", "evaluation_status"
        )).strip().upper()
        if eval_status in ["EVALUATED", "PROCESSED", "RANKED"]:
            skipped_evaluated += 1
            continue

        company = clean_string(get_field("Company Name", "Company_Name", "Company", "company_name"))
        spk_name = clean_string(get_field("Speaker Name", "Speaker_Name", "speaker_name", "Speaker"))
        conf_id = clean_string(get_field("Conference ID", "Conference_ID", "conference_id", "ConferenceId"))
        conf_name = clean_string(get_field("Conference Name", "Conference_Name", "conference_name"))

        # Exhibitor Incoming Columns
        exh_name = clean_string(get_field("Exhibitor Name", "Exhibitor_Name", "exhibitor_name"))
        exh_email = clean_email(get_field("Exhibitor Professional Email", "Exhibitor_Email", "Exhibitor Email", "exhibitor_email"))
        exh_status = "Verified" if exh_email else ""

        # Attendee Incoming Columns
        att_name = clean_string(get_field("Attendee Name", "Attendee_Name", "attendee_name"))
        att_email = clean_email(get_field("Attendee Professional Email", "Attendee_Email", "Attendee Email", "attendee_email"))
        att_status = "Verified" if att_email else ""

        # Speaker Incoming Columns
        email = clean_email(get_field("Speaker Professional Email", "Professional_Email", "Professional Email", "Email", "professional_email", "Speaker_Email", "Speaker Email"))
        email_status = "Verified" if email else ""
        job_title = clean_string(get_field("Speaker Job Title", "Job_Title", "Job Title", "Title", "job_title"))
        linkedin = clean_url(get_field("Speaker LinkedIn", "Personal_LinkedIn_URL", "Personal LinkedIn URL", "LinkedIn", "personal_linkedin_url"))
        speaker_url = clean_url(get_field("Speaker_Source_URL", "Speaker Source URL", "speaker_source_url"))

        # Lead Ingestion Rule: Company Name exists AND at least one participant exists (Speaker, Exhibitor, or Attendee)
        has_participant = bool(spk_name or exh_name or att_name or email or exh_email or att_email)
        if not company or not has_participant:
            invalid_rows_count += 1
            continue

        spk_id = clean_string(get_field("Speaker_ID", "Speaker ID", "speaker_id", "SpeakerID"))
        if not spk_id:
            conf_part = clean_token(conf_id) if conf_id else "CONF"
            participant_part = clean_token(spk_name or exh_name or att_name or "LEAD")
            comp_part = clean_token(company)
            spk_id = f"{conf_part}_{participant_part}_{comp_part}"

        person_token = clean_token(spk_name or exh_name or att_name)
        name_company_key = f"{person_token}:::{company.lower()}"
        comp_key = clean_token(company)

        if spk_id in already_processed or spk_id in seen_ids or name_company_key in seen_name_companies:
            duplicates_count += 1
            # Merge any non-empty Exhibitor or Attendee details from this duplicate row into the existing record
            if comp_key in company_leads_map:
                existing = company_leads_map[comp_key]
                if not existing.exhibitor_name and exh_name:
                    existing.exhibitor_name = exh_name
                    existing.exhibitor_email = exh_email
                    existing.exhibitor_email_status = exh_status
                if not existing.attendee_name and att_name:
                    existing.attendee_name = att_name
                    existing.attendee_email = att_email
                    existing.attendee_email_status = att_status
                if not existing.speaker_name and spk_name:
                    existing.speaker_name = spk_name
                    existing.job_title = job_title
                    existing.professional_email = email
                    existing.verification_status = email_status
            continue

        seen_ids.add(spk_id)
        seen_name_companies.add(name_company_key)

        cleaned_row = {
            "Speaker_ID": spk_id,
            "Conference_ID": conf_id,
            "Conference_Name": conf_name,
            "Speaker_Name": spk_name,
            "Job_Title": job_title,
            "Company_Name": company,
            "Personal_LinkedIn_URL": linkedin,
            "LinkedIn_Status": clean_string(get_field("LinkedIn_Status", "LinkedIn Status", "linkedin_status")),
            "Professional_Email": email,
            "Email_Source_URL": clean_string(get_field("Email_Source_URL", "Email Source URL", "email_source_url")),
            "Speaker_Source_URL": speaker_url,
            "Verification_Status": email_status,
            "Last_Checked_At": clean_string(get_field("Last_Checked_At", "Last Checked At", "last_checked_at")),
            "Weekly_Run_ID": clean_string(get_field("Weekly_Run_ID", "Weekly Run ID", "weekly_run_id")),
            "Exhibitor_Name": exh_name,
            "Exhibitor_Email": exh_email,
            "Exhibitor_Email_Status": exh_status,
            "Attendee_Name": att_name,
            "Attendee_Email": att_email,
            "Attendee_Email_Status": att_status,
        }
        
        try:
            lead = SpeakerRecord(**cleaned_row)
            clean_leads.append(lead)
            company_leads_map[comp_key] = lead
        except Exception:
            invalid_rows_count += 1

    # -----------------------------------------------------------------
    # COMPANY DEDUPLICATION & MULTI-ROLE MERGING:
    # Keep ONLY ONE representative lead per company
    # Rule: Check email verification (3: verified corp, 2: verified, 1: unverified, 0: none)
    # Tie-Breaker: "Keep before" (Python max preserves first-seen element)
    # Contact Enrichment: Merge Speaker + Exhibitor + Attendee across ALL rows of that company
    # -----------------------------------------------------------------
    company_groups: Dict[str, List[SpeakerRecord]] = {}
    for lead in clean_leads:
        comp_key = clean_token(lead.company_name)
        if comp_key not in company_groups:
            company_groups[comp_key] = []
        company_groups[comp_key].append(lead)

    deduped_leads: List[SpeakerRecord] = []
    duplicate_speaker_ids: List[str] = []

    for comp_key, speakers in company_groups.items():
        if len(speakers) == 1:
            deduped_leads.append(speakers[0])
        else:
            best_lead = max(speakers, key=get_speaker_email_priority)
            
            # Bi-directional contact enrichment
            for spk in speakers:
                if not best_lead.exhibitor_name and spk.exhibitor_name:
                    best_lead.exhibitor_name = spk.exhibitor_name
                if not best_lead.exhibitor_email and spk.exhibitor_email:
                    best_lead.exhibitor_email = spk.exhibitor_email
                if not best_lead.exhibitor_email_status and spk.exhibitor_email_status:
                    best_lead.exhibitor_email_status = spk.exhibitor_email_status
                    
                if not best_lead.attendee_name and spk.attendee_name:
                    best_lead.attendee_name = spk.attendee_name
                if not best_lead.attendee_email and spk.attendee_email:
                    best_lead.attendee_email = spk.attendee_email
                if not best_lead.attendee_email_status and spk.attendee_email_status:
                    best_lead.attendee_email_status = spk.attendee_email_status

                if not best_lead.speaker_name and spk.speaker_name:
                    best_lead.speaker_name = spk.speaker_name
                    best_lead.job_title = spk.job_title
                if not best_lead.professional_email and spk.professional_email:
                    best_lead.professional_email = spk.professional_email
                    best_lead.verification_status = spk.verification_status
                if not best_lead.personal_linkedin_url and spk.personal_linkedin_url:
                    best_lead.personal_linkedin_url = spk.personal_linkedin_url
            
            deduped_leads.append(best_lead)
            
            for spk in speakers:
                if spk.speaker_id != best_lead.speaker_id:
                    duplicate_speaker_ids.append(spk.speaker_id)
                    best_score = get_speaker_email_priority(best_lead)
                    spk_score = get_speaker_email_priority(spk)
                    display_name = best_lead.speaker_name or best_lead.exhibitor_name or best_lead.attendee_name or "Contact"
                    other_name = spk.speaker_name or spk.exhibitor_name or spk.attendee_name or "Contact"
                    print(f"   👥 Duplicate company '{best_lead.company_name}': Keeping '{display_name}' (Email Score: {best_score}), skipping '{other_name}' (Email Score: {spk_score})")

    weekly_id = deduped_leads[0].weekly_run_id if deduped_leads else None

    print(f"📊 [Node 1 Summary]")
    print(f"   • Total rows in sheet: {len(records_raw)}")
    print(f"   • Previously EVALUATED rows skipped: {skipped_evaluated} ⏭️")
    print(f"   • Duplicates / Blanks filtered: {duplicates_count + invalid_rows_count}")
    print(f"   • Alternate speakers from same company deduplicated: {len(duplicate_speaker_ids)} 👥")
    print(f"   • Unique Companies to Process: {len(deduped_leads)} ✨\n")

    return {
        "new_leads": deduped_leads,
        "duplicate_speaker_ids": duplicate_speaker_ids,
        "current_weekly_run_id": weekly_id,
        "total_new_count": len(deduped_leads)
    }


# --- NODE 2 CORE LOGIC: AZURE LLM ENRICHMENT & DOMAIN RESOLVER ---
profile_parser = JsonOutputParser(pydantic_object=OrganizedCompanyProfile)

research_prompt = PromptTemplate.from_template("""You are a Senior B2B Corporate Intelligence Analyst.
Examine the live web search facts about an organization and produce a complete structured intelligence dossier.
CRITICAL RULES:
1. NEVER leave any string field empty.
2. For 'company_domain', determine and output ONLY the organization's TRUE official corporate root domain (e.g., 'khoslaventures.com', 'wholefoodsmarket.com', 'afbasket.com', 'rainforestdistribution.com').
   - If the corporate email domain hint is from a third-party consulting firm or agency (e.g. 'gartner.com' for Whole Foods, 'diligentglobal.com' for Khosla Ventures), DISCARD IT and identify the company's real root corporate domain using your world knowledge and the found URL.
   - NEVER output trade publications (e.g. 'retail-merchandiser.com'), news sites, social media, or directories like 'linkedin.com', 'leadiq.com', 'nombase.com', 'yelp.com', or 'tavily.com'.
3. For 'primary_industry', be specific (e.g., 'Supermarket & Grocery Retail', 'Food & Beverage Wholesale Distribution', 'Venture Capital', 'Life Insurance', 'Enterprise Cloud Platform'). Do NOT output generic 'General Commercial / Services' unless totally impossible to determine.
4. If the organization is a Non-Profit or Academic institution (like Archaeological Institute of America), set headcount_tier to 'Non-Profit / Academic'.

Company / Organization Name: {company_name}
Speaker Context: {speaker_name} ({job_title}) at {conference_name}
Corporate Email Domain Hint: {email_domain_hint}
LIVE WEB SEARCH FACTS:
{search_overview}
FOUND OFFICIAL URL:
{found_url}

{format_instructions}
""")

enrichment_chain = research_prompt | azure_llm | profile_parser

def search_company_with_tavily(
    company_name: str,
    speaker_name: str = "",
    conference_name: str = ""
) -> Dict[str, str]:
    """Production-grade targeted homepage Tavily web search with lexical URL ranking and blog filtering."""
    clean_name = company_name.strip()
    if not clean_name or clean_name.lower() in ["unknown", "n/a", "none"]:
        return {"url": "", "overview": "No company name provided."}

    if len(clean_name) <= 5:
        context_parts = [f'"{clean_name}"']
        if speaker_name:
            context_parts.append(speaker_name)
        if conference_name:
            context_parts.append(conference_name)
        context_parts.append("official corporate website homepage")
        query = " ".join(context_parts)
    else:
        query = f'"{clean_name}" official website homepage'

    for attempt in range(2):
        try:
            response = tavily_client.search(
                query=query,
                search_depth="basic",
                max_results=5,
                include_answer=True
            )
            overview = response.get("answer", "")
            results = response.get("results", [])

            official_url = pick_best_company_url(results, clean_name)

            if not overview and results:
                overview = " ".join([r.get("content", "") for r in results[:2]])

            return {"url": official_url, "overview": overview[:1200]}
        except Exception as e:
            if attempt == 0:
                time.sleep(1.0)
                continue
            print(f"⚠️ Tavily error for {clean_name}: {e}")
            return {"url": "", "overview": f"Company: {clean_name}."}

def node_2_hybrid_enrichment(leads: List[Any]) -> List[EnrichedLead]:
    """Node 2: Multi-layer intelligence enrichment using Tavily + Azure OpenAI with 4-step domain resolution."""
    enriched_leads: List[EnrichedLead] = []
    company_cache: Dict[str, OrganizedCompanyProfile] = {}
    total = len(leads)
    
    print(f"\n⚡ [Node 2: Deep Corporate Research (Azure OpenAI)] Processing {total} leads...\n")

    for i, lead in enumerate(leads, 1):
        company_key = lead.company_name.lower().strip()
        contact_display = lead.speaker_name or lead.exhibitor_name or lead.attendee_name or "Contact"
        print(f"[{i}/{total}] Deep Research: {lead.company_name} ({contact_display})...")
        
        any_email = lead.professional_email or lead.exhibitor_email or lead.attendee_email
        raw_email_domain = extract_domain_from_email(any_email)
        email_domain = ""
        if raw_email_domain:
            if is_email_domain_matching_company(raw_email_domain, lead.company_name):
                email_domain = raw_email_domain
                print(f"   📧 Ground-Truth Email Domain Verified: '{email_domain}'")
            else:
                print(f"   ⚠️ Third-party / consulting email domain '{raw_email_domain}' detected for '{lead.company_name}' - ignoring in favor of Tavily + Azure research.")

        if company_key in company_cache:
            print(f"   ⚡ Reusing cached profile for {lead.company_name}!")
            profile = company_cache[company_key]
            raw_text = "Retrieved from run cache"
        else:
            tavily_result = search_company_with_tavily(
                company_name=lead.company_name,
                speaker_name=contact_display,
                conference_name=lead.conference_name
            )
            raw_text = tavily_result["overview"]
            found_url = tavily_result["url"]
            
            profile = None
            for attempt in range(2):
                try:
                    profile_dict = enrichment_chain.invoke({
                        "company_name": lead.company_name,
                        "speaker_name": contact_display,
                        "job_title": lead.job_title or "Executive",
                        "conference_name": lead.conference_name,
                        "email_domain_hint": email_domain or "None (determine official root domain from company name and official URL)",
                        "search_overview": raw_text,
                        "found_url": found_url,
                        "format_instructions": profile_parser.get_format_instructions()
                    })
                    profile = OrganizedCompanyProfile(**profile_dict)
                    break
                except Exception as e:
                    if attempt == 0:
                        time.sleep(1.0)
                        continue
                    print(f"⚠️ Azure LLM profile parsing error: {e}")
                    profile = OrganizedCompanyProfile(
                        company_domain="",
                        official_website=found_url,
                        primary_industry="General Commercial / Services",
                        headcount_tier="Mid-Market Sweet Spot (50-500)",
                        core_products_and_services=raw_text[:150],
                        us_market_presence="United States",
                        operational_workflows_analysis="Standard operational and document processing workflows.",
                        key_business_highlights=""
                    )

            if email_domain:
                profile.company_domain = email_domain
            else:
                clean_dom = profile.company_domain.lower().replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].strip()
                if clean_dom and not is_blocked_domain(clean_dom) and "." in clean_dom:
                    profile.company_domain = clean_dom
                elif found_url:
                    url_domain = extract_domain_from_url(found_url)
                    if url_domain:
                        profile.company_domain = url_domain
                    else:
                        profile.company_domain = re.sub(r'[^a-zA-Z0-9]', '', lead.company_name).lower() + ".com"
                else:
                    profile.company_domain = re.sub(r'[^a-zA-Z0-9]', '', lead.company_name).lower() + ".com"

            if not profile.official_website or is_blocked_domain(profile.official_website):
                profile.official_website = f"https://{profile.company_domain}"

            lower_text = (lead.company_name + " " + raw_text).lower()
            is_non_profit = any(w in lower_text for w in ["non-profit", "nonprofit", "archaeol", "institute", "foundation", "museum", "society"])
            is_commercial_entity = any(w in lower_text for w in ["venture", "capital", "partners", "fund", "invest", "holding", "llc", "inc", "corp"])
            if is_commercial_entity:
                is_non_profit = False

            if is_non_profit:
                profile.primary_industry = profile.primary_industry or "Non-Profit / Research & Education"
                profile.headcount_tier = "Non-Profit / Academic"
                profile.core_products_and_services = profile.core_products_and_services or "Academic research, publications, grants, and education programs."
                profile.operational_workflows_analysis = profile.operational_workflows_analysis or "Handles member subscriptions, journal publishing, and grant application reviews."

            company_cache[company_key] = profile
            time.sleep(0.2)

        enriched = EnrichedLead(
            raw_lead=lead,
            profile=profile,
            tavily_raw_text=raw_text
        )
        enriched_leads.append(enriched)

        print(f"   🌐 Verified Domain: {profile.company_domain} ({profile.official_website})")
        print(f"   🏢 Industry: {profile.primary_industry} | Tier: {profile.headcount_tier}")
        print(f"   📍 Location / US: {profile.us_market_presence}")
        print(f"   💼 Products: {profile.core_products_and_services[:80]}...\n")

    print(f"✅ [Node 2 Complete] Generated clean profiles for {len(enriched_leads)} companies!")
    return enriched_leads


# --- NODE 3 CORE LOGIC: KNOWLEDGE BASE 60/40 SCORING ---
score_parser = JsonOutputParser(pydantic_object=LeadScoreResult)

scoring_prompt = PromptTemplate.from_template("""You are the Chief Strategy & Evaluation Officer for Adople AI.
You must strictly score the company by applying the rules from the official Adople AI Knowledge Base below.
Conclude with a calculated score based on the 60% Industry / 40% Tier formula.

=================== ADOPLE AI KNOWLEDGE BASE ===================
{knowledge_base}
================================================================

Evaluate this company:
- Company Name: {company_name} ({domain})
- Headcount Tier: {company_tier}
- Industry: {industry}
- Core Products: {products}
- Daily Operational Bottlenecks: {operations}
- Speaker Context: {speaker_name} ({job_title})

Calculate the scores strictly following the 60% / 40% rules.
{format_instructions}
""")

scoring_chain = scoring_prompt | azure_llm | score_parser

def node_3_evaluate_and_score(enriched_leads: List[Any]) -> List[EvaluatedLead]:
    evaluated_leads: List[EvaluatedLead] = []
    total = len(enriched_leads)
    
    print(f"\n🎯 [Node 3: Azure OpenAI (60/40)] Scoring {total} companies...\n")

    for i, item in enumerate(enriched_leads, 1):
        lead = item.raw_lead
        prof = item.profile
        
        print(f"[{i}/{total}] Evaluating: {lead.company_name} ({prof.company_domain})...")
        
        score_res = None
        for attempt in range(2):
            try:
                score_dict = scoring_chain.invoke({
                    "knowledge_base": adople_kb_content,
                    "company_name": lead.company_name,
                    "domain": prof.company_domain,
                    "company_tier": prof.headcount_tier,
                    "industry": prof.primary_industry,
                    "products": prof.core_products_and_services,
                    "operations": prof.operational_workflows_analysis,
                    "speaker_name": lead.speaker_name or lead.exhibitor_name or lead.attendee_name or "Contact",
                    "job_title": lead.job_title or "Executive",
                    "format_instructions": score_parser.get_format_instructions()
                })
                score_res = LeadScoreResult(**score_dict)
                break
            except Exception as e:
                if attempt == 0:
                    time.sleep(1.0)
                    continue
                print(f"⚠️ Scoring error for {lead.company_name} (using fallback score): {e}\n")
                score_res = LeadScoreResult(
                    strategic_analysis=f"Automated fallback score due to evaluation error: {e}",
                    industry_fit_score=50.0,
                    tier_fit_score=50.0,
                    overall_company_score=50.0,
                    qualification_status="MODERATE"
                )

        evaluated = EvaluatedLead(
            enriched_lead=item,
            score_details=score_res
        )
        evaluated_leads.append(evaluated)
        
        print(f"   ⭐ Overall Score: {score_res.overall_company_score:.1f}/100 [{score_res.qualification_status}]")
        print(f"   📊 Industry (60%): {score_res.industry_fit_score} | Tier (40%): {score_res.tier_fit_score}\n")

        time.sleep(0.2)

    print(f"✅ [Node 3 Complete] Successfully evaluated {len(evaluated_leads)}/{total} companies!")
    return evaluated_leads


# --- NODE 4 CORE LOGIC: DETERMINISTIC TIE-BREAKER RANKING ---
def get_tie_breaker_sort_key(item: EvaluatedLead):
    """Returns a sorting tuple: (Overall Score, Industry Score, Email Status). Safe against None."""
    score = float(getattr(item.score_details, "overall_company_score", 0.0) or 0.0)
    ind_score = float(getattr(item.score_details, "industry_fit_score", 0.0) or 0.0)
    
    raw = item.enriched_lead.raw_lead
    has_verified = (
        (getattr(raw, 'professional_email', '') and "verified" in str(getattr(raw, 'verification_status', '')).lower()) or
        (getattr(raw, 'exhibitor_email', '') and "verified" in str(getattr(raw, 'exhibitor_email_status', '')).lower()) or
        (getattr(raw, 'attendee_email', '') and "verified" in str(getattr(raw, 'attendee_email_status', '')).lower())
    )
    has_any = bool(
        getattr(raw, 'professional_email', '') or
        getattr(raw, 'exhibitor_email', '') or
        getattr(raw, 'attendee_email', '')
    )
    
    if has_verified:
        email_readiness = 2
    elif has_any:
        email_readiness = 1
    else:
        email_readiness = 0

    return (score, ind_score, email_readiness)

def node_4_rank_and_select_top_10(
    evaluated_leads: List[EvaluatedLead],
    state: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    print(f"\n🏆 [Node 4: Ranking Engine] Sorting {len(evaluated_leads)} evaluated companies...\n")

    sorted_leads = sorted(evaluated_leads, key=get_tie_breaker_sort_key, reverse=True)
    ranked_results: List[RankedLead] = []

    for idx, item in enumerate(sorted_leads, 1):
        raw = item.enriched_lead.raw_lead
        prof = item.enriched_lead.profile
        sc = item.score_details

        lead_status = determine_qualification_status(sc.overall_company_score)
        ranked_lead = RankedLead(
            rank=idx,
            company_name=raw.company_name,
            domain=prof.company_domain,
            overall_score=round(sc.overall_company_score, 1),
            industry_score=round(sc.industry_fit_score, 1),
            tier_score=round(sc.tier_fit_score, 1),
            qualification_status=lead_status,
            speaker_id=raw.speaker_id,
            speaker_name=raw.speaker_name,
            job_title=raw.job_title,
            email=raw.professional_email or "Not Available",
            email_status=raw.verification_status,
            linkedin_url=raw.personal_linkedin_url or "Not Available",
            conference_name=raw.conference_name,
            exhibitor_name=getattr(raw, "exhibitor_name", "") or "",
            exhibitor_email=getattr(raw, "exhibitor_email", "") or "",
            exhibitor_email_status=getattr(raw, "exhibitor_email_status", "") or "",
            attendee_name=getattr(raw, "attendee_name", "") or "",
            attendee_email=getattr(raw, "attendee_email", "") or "",
            attendee_email_status=getattr(raw, "attendee_email_status", "") or "",
            evaluated_lead=item
        )
        ranked_results.append(ranked_lead)

    top_10 = ranked_results[:10]

    print("=" * 145)
    print(f"{'STATUS':<6} | {'RANK':<5} | {'COMPANY':<22} | {'SCORE':<6} | {'SPK STATUS':<12} | {'EXH STATUS':<12} | {'ATT STATUS':<12} | {'CONTACTS'}")
    print("=" * 145)
    for r in ranked_results:
        icon = "🟢" if r.overall_score >= 75.0 else ("🟡" if r.overall_score >= 50.0 else "⚪")
        contacts = []
        if r.speaker_name: contacts.append(f"Spk: {r.speaker_name}")
        if r.exhibitor_name: contacts.append(f"Exh: {r.exhibitor_name}")
        if r.attendee_name: contacts.append(f"Att: {r.attendee_name}")
        contact_display = "; ".join(contacts) if contacts else "N/A"
        spk_st = r.email_status or "-"
        exh_st = r.exhibitor_email_status or "-"
        att_st = r.attendee_email_status or "-"
        print(f"{icon:<6} | #{r.rank:<4} | {r.company_name:<22} | {r.overall_score:<6.1f} | {spk_st:<12} | {exh_st:<12} | {att_st:<12} | {contact_display}")
    print("=" * 145)

    print(f"\n✅ [Node 4 Complete] Ranked all {len(ranked_results)} companies (Top {len(top_10)} prioritized)!")

    if state is not None:
        state["top_10_leads"] = top_10
        state["all_ranked_leads"] = ranked_results

    return {
        "top_10_leads": top_10,
        "all_ranked_leads": ranked_results
    }


# =====================================================================
# 7. LANGGRAPH NODE WRAPPERS & CONDITIONAL ROUTING
# =====================================================================
def node_1_ingestion(state: PipelineState) -> Dict[str, Any]:
    """LangGraph Node 1: Ingests unprocessed rows from Microsoft SharePoint Master Sheet."""
    verify_environment_and_credentials()
    client = get_sharepoint_client()
    return node_1_fetch_unprocessed_from_sheet(client, state)


def check_has_new_leads(state: PipelineState) -> str:
    """Conditional Edge: Stops execution gracefully if no new leads found."""
    total_new = state.get("total_new_count", 0)
    if total_new == 0:
        print("\n⏹️ [LangGraph Router] No new unprocessed leads in Master Sheet. Exiting pipeline safely.")
        return "end"
    print(f"\n🚀 [LangGraph Router] Found {total_new} new lead(s). Routing to Node 2 (Deep Research)...")
    return "continue"


def node_2_enrichment_node(state: PipelineState) -> Dict[str, Any]:
    """LangGraph Node 2: Performs Tavily + Azure OpenAI intelligence enrichment."""
    leads = state.get("new_leads", [])
    enriched_leads = node_2_hybrid_enrichment(leads)
    return {"enriched_leads": enriched_leads}


def node_3_scoring_node(state: PipelineState) -> Dict[str, Any]:
    """LangGraph Node 3: Applies 60/40 Knowledge Base scoring via Azure OpenAI."""
    enriched_leads = state.get("enriched_leads", [])
    scored_leads = node_3_evaluate_and_score(enriched_leads)
    return {"scored_leads": scored_leads}


def node_4_ranking_node(state: PipelineState) -> Dict[str, Any]:
    """LangGraph Node 4: Sorts leads with deterministic tie-breakers and slices Top 10."""
    scored_leads = state.get("scored_leads", [])
    ranking_output = node_4_rank_and_select_top_10(scored_leads, state=state)
    return ranking_output


def node_5_export_sync_node(state: PipelineState) -> Dict[str, Any]:
    """LangGraph Node 5: Exports all leads to SharePoint (latest_week_scoring + Companies scoring) & syncs Master Sheet."""
    all_ranked = state.get("all_ranked_leads", [])
    if not all_ranked:
        all_ranked = state.get("top_10_leads", [])
    scored = state.get("scored_leads", [])
    
    if not all_ranked and not scored:
        print("⚠️ No leads to export in Node 5.")
        return {"exported_count": 0}

    client = get_sharepoint_client()

    # 1. Export to SharePoint (latest_week_scoring + Companies scoring)
    exported_count = export_ranked_leads_to_sharepoint(client, all_ranked)

    # 2. Update Master Sheet ('Verified Data')
    all_evaluated_ids = [item.enriched_lead.raw_lead.speaker_id for item in scored]
    if not all_evaluated_ids:
        all_evaluated_ids = [lead.speaker_id for lead in all_ranked]

    duplicate_ids = state.get("duplicate_speaker_ids", [])
    all_ids_to_mark = list(set(all_evaluated_ids + duplicate_ids))

    mark_leads_evaluated_in_sharepoint(client, all_ids_to_mark)

    updated_processed = set(state.get("processed_speaker_ids", set())).union(set(all_ids_to_mark))
    print("\n🎉 Node 5 Complete! latest_week_scoring & Companies scoring updated with all 21 columns (including Exhibitor & Attendee details), and Master Sheet is synchronized.")
    
    return {
        "exported_count": exported_count,
        "processed_speaker_ids": updated_processed
    }


# =====================================================================
# 8. LANGGRAPH WORKFLOW ASSEMBLY & EDGES
# =====================================================================
def build_conference_ranking_graph():
    """Builds and compiles the complete multi-node LangGraph pipeline."""
    workflow = StateGraph(PipelineState)

    # 1. Register all nodes
    workflow.add_node("node_1_ingestion", node_1_ingestion)
    workflow.add_node("node_2_enrichment", node_2_enrichment_node)
    workflow.add_node("node_3_scoring", node_3_scoring_node)
    workflow.add_node("node_4_ranking", node_4_ranking_node)
    workflow.add_node("node_5_export_sync", node_5_export_sync_node)

    # 2. Connect Edges
    workflow.add_edge(START, "node_1_ingestion")
    
    workflow.add_conditional_edges(
        "node_1_ingestion",
        check_has_new_leads,
        {
            "continue": "node_2_enrichment",
            "end": END
        }
    )
    
    workflow.add_edge("node_2_enrichment", "node_3_scoring")
    workflow.add_edge("node_3_scoring", "node_4_ranking")
    workflow.add_edge("node_4_ranking", "node_5_export_sync")
    workflow.add_edge("node_5_export_sync", END)

    return workflow.compile()


# Globally compiled app ready to import or invoke
app = build_conference_ranking_graph()


# =====================================================================
# 9. INTEGRATION SERVICE CLASS FOR EXISTING APPLICATION WORKFLOWS
# =====================================================================
class ICPScoringService:
    """
    Service wrapper for the LangGraph AI Reranking Pipeline.
    Maintains 100% backward compatibility with main.py, weekly_service.py, and scheduler.
    """
    def __init__(self, db: Optional[Any] = None):
        self.db = db

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def run_pipeline(self, initial_state: Optional[PipelineState] = None) -> Dict[str, Any]:
        """Runs the compiled LangGraph pipeline."""
        state = initial_state or {
            "processed_speaker_ids": set(),
            "new_leads": [],
            "duplicate_speaker_ids": [],
            "current_weekly_run_id": None,
            "total_new_count": 0,
            "enriched_leads": [],
            "scored_leads": [],
            "top_10_leads": [],
            "all_ranked_leads": [],
            "exported_count": 0
        }
        return app.invoke(state)

    def score_and_publish_weekly_run(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes the AI Reranking LangGraph pipeline:
        - Ingests unprocessed verified contacts (Speakers, Attendees, Exhibitors)
        - Runs Tavily web research and Azure OpenAI intelligence profiling
        - Scores via 60/40 Knowledge Base formula (Azure OpenAI)
        - Sorts and ranks deterministically (Node 4)
        - Exports to latest_week_scoring and Companies scoring (with color highlights)
        - Marks leads as EVALUATED in Verified Data
        """
        print(f"\n🚀 [ICP Reranking Service] Starting LangGraph AI Scoring & Reranking Pipeline (run_id: {run_id})...")
        initial_state: PipelineState = {
            "processed_speaker_ids": set(),
            "new_leads": [],
            "duplicate_speaker_ids": [],
            "current_weekly_run_id": run_id,
            "total_new_count": 0,
            "enriched_leads": [],
            "scored_leads": [],
            "top_10_leads": [],
            "all_ranked_leads": [],
            "exported_count": 0
        }
        final_state = app.invoke(initial_state)
        
        return {
            "status": "success",
            "weekly_run_id": run_id,
            "total_new_ingested": final_state.get("total_new_count", 0),
            "ranked_count": len(final_state.get("all_ranked_leads", [])),
            "top_10_count": len(final_state.get("top_10_leads", [])),
            "exported_count": final_state.get("exported_count", 0)
        }


# =====================================================================
# 10. COMPATIBILITY WRAPPERS
# =====================================================================
def score_conference(conf_name: str, industry: str, official_url: str = "") -> Dict[str, Any]:
    """Compatibility helper returning baseline conference evaluation structure."""
    return {
        "conference_name": conf_name,
        "industry": industry,
        "fit_score": 85.0,
        "rationale": f"Automated profile for {conf_name}"
    }

def score_speaker(speaker_name: str, job_title: str, company_name: str, conf_name: str = "") -> Dict[str, Any]:
    """Compatibility helper returning baseline speaker evaluation structure."""
    return {
        "speaker_name": speaker_name,
        "job_title": job_title,
        "company_name": company_name,
        "overall_score": 75.0,
        "industry_fit_score": 80.0,
        "scale_fit_score": 70.0,
        "qualification_status": "HIGH_MATCH",
        "pitch_hook": f"Practical AI solutions for {company_name}"
    }


# =====================================================================
# 11. STANDALONE EXECUTION ENTRYPOINT
# =====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🚀 Running Adople AI Conference Ranking LangGraph Pipeline")
    print("=" * 70)

    initial_state: PipelineState = {
        "processed_speaker_ids": set(),
        "new_leads": [],
        "duplicate_speaker_ids": [],
        "current_weekly_run_id": None,
        "total_new_count": 0,
        "enriched_leads": [],
        "scored_leads": [],
        "top_10_leads": [],
        "all_ranked_leads": [],
        "exported_count": 0
    }

    final_state = app.invoke(initial_state)

    print("\n" + "=" * 70)
    print("🏁 Pipeline Run Complete!")
    print(f"   • Total New Leads Ingested: {final_state.get('total_new_count', 0)}")
    print(f"   • Companies Exported to Curated Sheet: {final_state.get('exported_count', 0)}")
    print("=" * 70)
