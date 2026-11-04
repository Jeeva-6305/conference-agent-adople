import os
import sys
import re
import time
import datetime
from typing import List, Optional, Set, Dict, Any
from typing_extensions import TypedDict
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import gspread
from google.oauth2.service_account import Credentials
from tavily import TavilyClient
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langgraph.graph import StateGraph, START, END

load_dotenv(override=True)

# =====================================================================
# 1. API CLIENTS & KNOWLEDGE BASE INITIALIZATION
# =====================================================================
# 1. Initialize Tavily Web Search Client
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# 2. Azure OpenAI LLM (Unified for both Node 2 Intelligence & Node 3 Scoring)
azure_llm = ChatOpenAI(
    model=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    base_url=os.getenv("AZURE_OPENAI_BASE_URL"),
    temperature=0.0,
    seed=42
)

KB_FILE_PATH = "adople_knowledge_base.md"

def load_knowledge_base(file_path: str = KB_FILE_PATH) -> str:
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
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
    speaker_name: str = Field(alias="Speaker_Name")
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


class LeadScoreResult(BaseModel):
    strategic_analysis: str = Field(description="Detailed rationale justifying the scores based on the Knowledge Base.")
    industry_fit_score: float = Field(description="0-100: Core Focus (Healthcare, FinTech, Banking, Insurance, Logistics, Supply Chain, Enterprise Automation)=95-100, Secondary (Venture Capital, B2B Cloud Infra)=78-88, Non-Core (General Productivity/Wiki SaaS, Hardware Manufacturing, Consumer Retail, Media)=50-70, Education/Institutions/Non-Profit=0-20")
    tier_fit_score: float = Field(description="0-100: Mid-Market (50-2000 emp)=92-100, Enterprise Commercial Giants (2000+ emp)=85-92, Hyperscalers=40-55, Micro (<50 emp)=25-40, Non-Profits/Academia=0-15")
    overall_company_score: float = Field(description="Calculated strictly as: (0.60 * industry_fit_score) + (0.40 * tier_fit_score)")
    qualification_status: str = Field(description="'HIGH_MATCH' (>= 75), 'MODERATE' (55-74), or 'DISQUALIFIED' (< 55)")


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
    """Strips all non-alphanumeric characters and lowercases."""
    return re.sub(r'[^a-zA-Z0-9]', '', str(s)).lower()

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
    preventing third-party emails (like gartner.com for Whole Foods or diligentglobal.com for Khosla) from being trusted.
    """
    if not email_domain or not company_name:
        return False
        
    domain_slug = email_domain.split(".")[0].lower()
    comp_clean = clean_token(company_name)
    
    # 1. Direct substring: "samsung" in "samsungventures", "rainforest" in "rainforestdistribution"
    if domain_slug in comp_clean or comp_clean in domain_slug:
        return True
        
    # 2. Token overlap: e.g. "rainforest" from ["rainforest", "distribution"]
    words = [w.lower() for w in re.findall(r'[a-zA-Z0-9]+', company_name) if len(w) >= 3]
    for w in words:
        if w in domain_slug:
            return True
            
    # 3. Acronym / Abbreviation match:
    # e.g., "Norwest Partners" -> "nvp" (starts with 'n', ends with 'p', length <= 4)
    if len(words) >= 2:
        first_char = words[0][0]
        second_char = words[1][0]
        if domain_slug.startswith(first_char) and second_char in domain_slug:
            if len(domain_slug) <= 4:
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
    email = clean_string(getattr(lead, "professional_email", "")).lower()
    status = clean_string(getattr(lead, "verification_status", "")).lower()
    
    if not email:
        return 0
        
    domain = extract_domain_from_email(email)
    is_matching = is_email_domain_matching_company(domain, lead.company_name) if domain else False
    
    if status == "verified" and is_matching:
        return 3
    elif status == "verified":
        return 2
    else:
        return 1


# =====================================================================
# 5. GOOGLE SHEETS CONNECTION & EXPORT HELPERS (OPTION A + IDEA 3)
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
    "Personal_LinkedIn_URL",
    "Speaker_ID",
    "Evaluated_At"
]

def verify_environment_and_credentials() -> None:
    """Pre-flight check: Validates that all necessary API keys and credentials exist before execution begins."""
    missing = []
    if not os.getenv("AZURE_OPENAI_API_KEY"):
        missing.append("AZURE_OPENAI_API_KEY")
    if not os.getenv("AZURE_OPENAI_BASE_URL"):
        missing.append("AZURE_OPENAI_BASE_URL")
    if not os.getenv("TAVILY_API_KEY"):
        missing.append("TAVILY_API_KEY")
    if not os.getenv("CONFERENCE_SHEET_ID"):
        missing.append("CONFERENCE_SHEET_ID")
        
    creds_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
    if not os.path.exists(creds_file):
        missing.append(f"Google Credentials file ('{creds_file}')")
        
    if not os.path.exists(KB_FILE_PATH):
        missing.append(f"Knowledge Base file ('{KB_FILE_PATH}')")

    if missing:
        err_msg = "\n❌ CRITICAL PRODUCTION CONFIGURATION ERROR:\n"
        for m in missing:
            err_msg += f"   • Missing or invalid: {m}\n"
        err_msg += "\nPlease check your .env and working directory before running in production."
        raise RuntimeError(err_msg)
    
    print("🛡️ [Pre-Flight Check] All API credentials, Google Service Account, and Knowledge Base verified!")

def connect_to_google_sheet(
    credentials_json_path: str,
    spreadsheet_name_or_id: str,
    worksheet_name: str = "Sheet1"
) -> gspread.Worksheet:
    """Authenticates with Google Sheets API and safely returns worksheet with exponential backoff retry."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file(credentials_json_path, scopes=scopes)
    client = gspread.authorize(creds)
    
    last_err = None
    for attempt in range(3):
        try:
            try:
                spreadsheet = client.open_by_key(spreadsheet_name_or_id)
            except Exception:
                try:
                    spreadsheet = client.open_by_url(spreadsheet_name_or_id)
                except Exception:
                    spreadsheet = client.open(spreadsheet_name_or_id)
                
            try:
                return spreadsheet.worksheet(worksheet_name)
            except Exception:
                return spreadsheet.get_worksheet(0)
        except Exception as e:
            last_err = e
            time.sleep(2.0 * (attempt + 1))
            
    raise RuntimeError(f"Failed to connect to Google Sheet '{spreadsheet_name_or_id}' after 3 attempts: {last_err}")

def connect_curated_sheet() -> gspread.Spreadsheet:
    """Connects to the Curated Google Spreadsheet container with exponential backoff retry."""
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
    curated_sheet_id = os.getenv("CURATED_SHEET_ID", "1Z-MVz-DLJ55JUni-8EWbWRIuEezzNqn_gUkjcUEkSiE")
    
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(credentials_path, scopes=scopes)
    gc = gspread.authorize(creds)
    
    last_err = None
    for attempt in range(3):
        try:
            try:
                return gc.open_by_key(curated_sheet_id)
            except Exception:
                return gc.open_by_url(curated_sheet_id)
        except Exception as e:
            last_err = e
            time.sleep(2.0 * (attempt + 1))
            
    raise RuntimeError(f"Failed to connect to Curated Sheet '{curated_sheet_id}' after 3 attempts: {last_err}")

def apply_score_color_formatting(
    worksheet: gspread.Worksheet,
    start_row: int,
    ranked_leads: List[RankedLead]
):
    """Applies visual row colors: Soft Green (>=50), Soft Yellow (35-49.9), Soft Gray (<35)."""
    green_ranges = []
    yellow_ranges = []
    gray_ranges = []

    for i, lead in enumerate(ranked_leads):
        row_num = start_row + i
        range_str = f"A{row_num}:O{row_num}"
        score = lead.overall_score
        if score >= 50.0:
            green_ranges.append(range_str)
        elif score >= 35.0:
            yellow_ranges.append(range_str)
        else:
            gray_ranges.append(range_str)

    try:
        if green_ranges:
            worksheet.format(green_ranges, {
                "backgroundColor": {"red": 0.85, "green": 0.92, "blue": 0.83}  # Soft Green
            })
        if yellow_ranges:
            worksheet.format(yellow_ranges, {
                "backgroundColor": {"red": 1.0, "green": 0.96, "blue": 0.80}   # Soft Yellow
            })
        if gray_ranges:
            worksheet.format(gray_ranges, {
                "backgroundColor": {"red": 0.94, "green": 0.94, "blue": 0.94}  # Soft Gray
            })
    except Exception as e:
        print(f"⚠️ Warning: Note on color formatting for {worksheet.title}: {e}")

def export_ranked_leads_to_curated_sheet(
    spreadsheet: gspread.Spreadsheet,
    ranked_leads: List[RankedLead]
) -> int:
    """Exports ALL evaluated leads to two tabs: 'Latest_Run' (fresh weekly top) and 'All_History'."""
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows_to_insert = []

    for lead in ranked_leads:
        prof = lead.evaluated_lead.enriched_lead.profile
        row = [
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
            lead.email,
            lead.email_status,
            lead.linkedin_url,
            lead.speaker_id,
            now_str
        ]
        rows_to_insert.append(row)

    if not rows_to_insert:
        print("⚠️ No ranked leads to export.")
        return 0

    # -----------------------------------------------------------------
    # TAB 1: Latest_Run (Cleared & refreshed so latest batch is on top)
    # -----------------------------------------------------------------
    try:
        latest_tab = spreadsheet.worksheet("Latest_Run")
    except Exception:
        latest_tab = spreadsheet.add_worksheet(title="Latest_Run", rows=len(rows_to_insert) + 20, cols=20)

    print("📋 [Curated Sheet] Refreshing 'Latest_Run' tab with latest batch...")
    latest_tab.clear()
    latest_tab.insert_row(CURATED_SHEET_HEADERS, 1)
    try:
        latest_tab.format("A1:O1", {
            "textFormat": {"bold": True},
            "backgroundColor": {"red": 0.90, "green": 0.93, "blue": 0.98}
        })
    except Exception:
        pass
        
    latest_tab.append_rows(rows_to_insert, value_input_option="USER_ENTERED")
    apply_score_color_formatting(latest_tab, start_row=2, ranked_leads=ranked_leads)
    print(f"📥 [Curated Sheet] 'Latest_Run' tab updated with {len(rows_to_insert)} companies!")

    # -----------------------------------------------------------------
    # TAB 2: All_History (Permanent historical archive)
    # -----------------------------------------------------------------
    try:
        history_tab = spreadsheet.worksheet("All_History")
    except Exception:
        history_tab = spreadsheet.add_worksheet(title="All_History", rows=1000, cols=20)

    existing_history_headers = history_tab.row_values(1)
    if not existing_history_headers:
        history_tab.insert_row(CURATED_SHEET_HEADERS, 1)
        try:
            history_tab.format("A1:O1", {
                "textFormat": {"bold": True},
                "backgroundColor": {"red": 0.90, "green": 0.93, "blue": 0.98}
            })
        except Exception:
            pass
        start_history_row = 2
    else:
        start_history_row = len(history_tab.col_values(1)) + 1

    history_tab.append_rows(rows_to_insert, value_input_option="USER_ENTERED")
    apply_score_color_formatting(history_tab, start_row=start_history_row, ranked_leads=ranked_leads)
    print(f"🏛️ [Curated Sheet] 'All_History' tab archived {len(rows_to_insert)} companies!")

    return len(rows_to_insert)

def mark_leads_evaluated_in_master_sheet(
    master_sheet: gspread.Worksheet,
    evaluated_speaker_ids: List[str]
):
    print(f"\n🔄 [Master Sheet] Updating 'Evaluation_Status' for {len(evaluated_speaker_ids)} leads...")
    headers = master_sheet.row_values(1)
    
    # Ensure Evaluation_Status column exists
    if "Evaluation_Status" not in headers:
        next_col = len(headers) + 1
        master_sheet.update_cell(1, next_col, "Evaluation_Status")
        status_col_idx = next_col
    else:
        status_col_idx = headers.index("Evaluation_Status") + 1

    spk_col_idx = headers.index("Speaker_ID") + 1
    company_col_idx = headers.index("Company_Name") + 1 if "Company_Name" in headers else None

    all_speaker_ids = master_sheet.col_values(spk_col_idx)
    all_companies = master_sheet.col_values(company_col_idx) if company_col_idx else []
    target_ids_set = set(str(sid).strip() for sid in evaluated_speaker_ids)
    
    cells_to_update = []
    for row_idx, spk_id in enumerate(all_speaker_ids[1:], start=2):
        spk_str = str(spk_id).strip()
        comp_str = all_companies[row_idx - 1] if row_idx - 1 < len(all_companies) else ""
        
        # Match by Speaker_ID
        if spk_str in target_ids_set:
            cells_to_update.append(
                gspread.Cell(row=row_idx, col=status_col_idx, value="EVALUATED")
            )
            print(f"   ✓ Row {row_idx}: {comp_str} ({spk_str}) marked as EVALUATED")

    if cells_to_update:
        # Batch updates in chunks of 100 to avoid Google Sheets rate limits
        batch_size = 100
        for i in range(0, len(cells_to_update), batch_size):
            chunk = cells_to_update[i:i + batch_size]
            try:
                master_sheet.update_cells(chunk)
                time.sleep(0.5)
            except Exception as e:
                print(f"⚠️ Warning updating master sheet chunk {i}: {e}")
        print(f"✅ [Master Sheet] Successfully marked {len(cells_to_update)} rows as 'EVALUATED'!")


# =====================================================================
# 6. NODE CORE IMPLEMENTATION FUNCTIONS
# =====================================================================

# --- NODE 1 CORE LOGIC ---
def node_1_fetch_unprocessed_from_sheet(
    sheet: gspread.Worksheet,
    state: PipelineState
) -> Dict[str, Any]:
    records_raw = sheet.get_all_records()
    already_processed: Set[str] = state.get("processed_speaker_ids", set())
    
    clean_leads: List[SpeakerRecord] = []
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

        eval_status = str(get_field("Evaluation_Status", "Evaluation Status", "evaluation_status")).strip().upper()
        if eval_status in ["EVALUATED", "PROCESSED", "RANKED"]:
            skipped_evaluated += 1
            continue

        spk_id = clean_string(get_field("Speaker_ID", "Speaker ID", "speaker_id"))
        spk_name = clean_string(get_field("Speaker_Name", "Speaker Name", "speaker_name"))
        company = clean_string(get_field("Company_Name", "Company Name", "Company", "company_name"))
        email = clean_email(get_field("Professional_Email", "Professional Email", "Email", "professional_email"))
        linkedin = clean_url(get_field("Personal_LinkedIn_URL", "Personal LinkedIn URL", "LinkedIn", "personal_linkedin_url"))
        speaker_url = clean_url(get_field("Speaker_Source_URL", "Speaker Source URL", "speaker_source_url"))

        if not spk_id or not spk_name or not company:
            invalid_rows_count += 1
            continue

        if spk_id in already_processed or spk_id in seen_ids:
            duplicates_count += 1
            continue

        name_company_key = f"{spk_name.lower()}:::{company.lower()}"
        if name_company_key in seen_name_companies:
            duplicates_count += 1
            continue

        seen_ids.add(spk_id)
        seen_name_companies.add(name_company_key)

        cleaned_row = {
            "Speaker_ID": spk_id,
            "Conference_ID": clean_string(get_field("Conference_ID", "Conference ID", "conference_id")),
            "Conference_Name": clean_string(get_field("Conference_Name", "Conference Name", "conference_name")),
            "Speaker_Name": spk_name,
            "Job_Title": clean_string(get_field("Job_Title", "Job Title", "Title", "job_title")),
            "Company_Name": company,
            "Personal_LinkedIn_URL": linkedin,
            "LinkedIn_Status": clean_string(get_field("LinkedIn_Status", "LinkedIn Status", "linkedin_status")),
            "Professional_Email": email,
            "Email_Source_URL": clean_string(get_field("Email_Source_URL", "Email Source URL", "email_source_url")),
            "Speaker_Source_URL": speaker_url,
            "Verification_Status": clean_string(get_field("Verification_Status", "Verification Status", "Email_Status", "verification_status")),
            "Last_Checked_At": clean_string(get_field("Last_Checked_At", "Last Checked At", "last_checked_at")),
            "Weekly_Run_ID": clean_string(get_field("Weekly_Run_ID", "Weekly Run ID", "weekly_run_id")),
        }
        
        try:
            lead = SpeakerRecord(**cleaned_row)
            clean_leads.append(lead)
        except Exception:
            invalid_rows_count += 1

    # -----------------------------------------------------------------
    # COMPANY DEDUPLICATION: Keep ONLY ONE representative speaker per company
    # Rule: Check email verification (3: verified corp, 2: verified, 1: unverified, 0: none)
    # Tie-Breaker: "Keep before" (Python max preserves first-seen element)
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
            # Python's max() with key returns the FIRST element encountered if scores are tied ("keep before")
            best_speaker = max(speakers, key=get_speaker_email_priority)
            deduped_leads.append(best_speaker)
            
            for spk in speakers:
                if spk.speaker_id != best_speaker.speaker_id:
                    duplicate_speaker_ids.append(spk.speaker_id)
                    best_score = get_speaker_email_priority(best_speaker)
                    spk_score = get_speaker_email_priority(spk)
                    print(f"   👥 Duplicate company '{best_speaker.company_name}': Keeping '{best_speaker.speaker_name}' (Email Score: {best_score}), skipping '{spk.speaker_name}' (Email Score: {spk_score})")

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

    # High-precision homepage queries: Avoid informational 'overview/what they do' phrases that trigger trade magazine articles
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

            # Filter out trade magazines, directories, and social media, prioritizing true corporate homepages
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
        print(f"[{i}/{total}] Deep Research: {lead.company_name} (Speaker: {lead.speaker_name})...")
        
        # Step 1: Corporate Email Domain Sanity Check (Reject third-party / agency domains)
        raw_email_domain = extract_domain_from_email(lead.professional_email)
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
            # Step 2: Targeted Homepage Tavily Search with Lexical Filtering
            tavily_result = search_company_with_tavily(
                company_name=lead.company_name,
                speaker_name=lead.speaker_name,
                conference_name=lead.conference_name
            )
            raw_text = tavily_result["overview"]
            found_url = tavily_result["url"]
            
            # Step 3: Azure OpenAI Corporate Intelligence & Domain Arbiter
            profile = None
            for attempt in range(2):
                try:
                    profile_dict = enrichment_chain.invoke({
                        "company_name": lead.company_name,
                        "speaker_name": lead.speaker_name,
                        "job_title": lead.job_title,
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

            # Step 4: High-Precision Domain Assignment & Guardrails
            if email_domain:
                # Verified corporate email domain takes top priority
                profile.company_domain = email_domain
            else:
                # Sanitize LLM or search-derived domain
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

            # Layer 5: Non-Profit / Academic Safety Guard
            lower_text = (lead.company_name + " " + raw_text).lower()
            is_non_profit = any(w in lower_text for w in ["non-profit", "nonprofit", "archaeol", "institute", "foundation", "museum", "society"])
            
            # Avoid false positive on commercial VCs or funds with "capital", "venture", "fund"
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
                    "speaker_name": lead.speaker_name,
                    "job_title": lead.job_title,
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
    email = str(getattr(raw, 'professional_email', '') or '').strip()
    status = str(getattr(raw, 'verification_status', '') or '').lower().strip()
    
    if email and status == 'verified':
        email_readiness = 2
    elif email:
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

        ranked_lead = RankedLead(
            rank=idx,
            company_name=raw.company_name,
            domain=prof.company_domain,
            overall_score=round(sc.overall_company_score, 1),
            industry_score=round(sc.industry_fit_score, 1),
            tier_score=round(sc.tier_fit_score, 1),
            qualification_status=sc.qualification_status,
            speaker_id=raw.speaker_id,
            speaker_name=raw.speaker_name,
            job_title=raw.job_title,
            email=raw.professional_email or "Not Available",
            email_status=raw.verification_status,
            linkedin_url=raw.personal_linkedin_url or "Not Available",
            conference_name=raw.conference_name,
            evaluated_lead=item
        )
        ranked_results.append(ranked_lead)

    top_10 = ranked_results[:10]

    print("=" * 98)
    print(f"{'STATUS':<6} | {'RANK':<5} | {'COMPANY':<22} | {'SCORE':<6} | {'INDUSTRY':<10} | {'EMAIL STATUS':<14} | {'SPEAKER & TITLE'}")
    print("=" * 98)
    for r in ranked_results:
        icon = "🟢" if r.overall_score >= 50 else ("🟡" if r.overall_score >= 35 else "⚪")
        print(f"{icon:<6} | #{r.rank:<4} | {r.company_name:<22} | {r.overall_score:<6.1f} | {r.industry_score:<10.1f} | {r.email_status:<14} | {r.speaker_name} ({r.job_title})")
    print("=" * 98)

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
    """LangGraph Node 1: Ingests unprocessed rows from Google Master Sheet."""
    verify_environment_and_credentials()
    
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
    spreadsheet_name_or_id = os.getenv("CONFERENCE_SHEET_ID")
    worksheet_name = os.getenv("CONFERENCE_WORKSHEET_NAME", "Sheet1")
    
    master_worksheet = connect_to_google_sheet(
        credentials_json_path=credentials_path,
        spreadsheet_name_or_id=spreadsheet_name_or_id,
        worksheet_name=worksheet_name
    )
    
    return node_1_fetch_unprocessed_from_sheet(master_worksheet, state)


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
    """LangGraph Node 5: Exports all leads to Curated Sheet (Latest_Run + All_History) & syncs Master Sheet."""
    all_ranked = state.get("all_ranked_leads", [])
    if not all_ranked:
        all_ranked = state.get("top_10_leads", [])
    scored = state.get("scored_leads", [])
    
    if not all_ranked and not scored:
        print("⚠️ No leads to export in Node 5.")
        return {"exported_count": 0}

    # 1. Export to Curated Sheet (Option A colors + Idea 3 tabs)
    curated_spreadsheet = connect_curated_sheet()
    print(f"🔗 Connected to Curated Spreadsheet: '{curated_spreadsheet.title}'")
    exported_count = export_ranked_leads_to_curated_sheet(curated_spreadsheet, all_ranked)

    # 2. Update Master Sheet
    credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "service_account.json")
    spreadsheet_name_or_id = os.getenv("CONFERENCE_SHEET_ID")
    worksheet_name = os.getenv("CONFERENCE_WORKSHEET_NAME", "Sheet1")
    master_worksheet = connect_to_google_sheet(
        credentials_json_path=credentials_path,
        spreadsheet_name_or_id=spreadsheet_name_or_id,
        worksheet_name=worksheet_name
    )

    all_evaluated_ids = [item.enriched_lead.raw_lead.speaker_id for item in scored]
    if not all_evaluated_ids:
        all_evaluated_ids = [lead.speaker_id for lead in all_ranked]

    # Include duplicate speakers from same company so they are also marked EVALUATED in Master Sheet
    duplicate_ids = state.get("duplicate_speaker_ids", [])
    all_ids_to_mark = list(set(all_evaluated_ids + duplicate_ids))

    mark_leads_evaluated_in_master_sheet(master_worksheet, all_ids_to_mark)

    updated_processed = set(state.get("processed_speaker_ids", set())).union(set(all_ids_to_mark))
    print("\n🎉 Node 5 Complete! Latest_Run & All_History updated with colors, and Master Sheet is synchronized.")
    
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
    
    # Conditional edge: if 0 leads, route to END; otherwise continue to Node 2
    workflow.add_conditional_edges(
        "node_1_ingestion",
        check_has_new_leads,
        {
            "continue": "node_2_enrichment",
            "end": END
        }
    )
    
    # Linear sequential pipeline edges
    workflow.add_edge("node_2_enrichment", "node_3_scoring")
    workflow.add_edge("node_3_scoring", "node_4_ranking")
    workflow.add_edge("node_4_ranking", "node_5_export_sync")
    workflow.add_edge("node_5_export_sync", END)

    return workflow.compile()


# Globally compiled app ready to import or invoke
app = build_conference_ranking_graph()


# =====================================================================
# 9. EXECUTION ENTRYPOINT
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
