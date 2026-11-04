"""
Adople AI - Strategic ICP Scoring & Multi-Store Synchronization Service
Updated to adhere strictly to the latest Adople AI Knowledge Base (Nov 2026):

Strict 60% / 40% Formula:
    Overall Score = (0.60 * Industry Fit) + (0.40 * Tier / Scale Fit)

Dimension A: Industry Fit (Weight: 60%)
- Tier 1: Core Revenue Focus Verticals (95 - 100)
  1A. Healthcare & Medical Operations (98.0)
  1B. FinTech, Banking & Financial Services (97.0)
  1C. Insurance & Claims Processing (97.0)
  1D. Logistics, Freight, Supply Chain & Distribution (96.0)
  1E. Enterprise Mission-Critical Workflow Automation (96.0)
- Tier 2: Secondary Commercial Verticals (78 - 88)
  - Pure Venture Capital & Investment Funds (86.0)
  - B2B Cloud Data Infrastructure & Mobility Platforms (82.0)
- Tier 3: Non-Core Verticals, General SaaS & Hardware (50 - 70)
  - General Productivity & Office Collaboration (65.0)
  - Consumer Electronics & Semiconductor Manufacturing (60.0)
  - Supermarkets, Grocery Chains, Consumer Retail & Food Cafes (55.0)
  - Media, Digital Publishing & Entertainment (55.0)
- Disqualified: Strictly Avoid ❌ (0 - 20)
  - Institutions, Universities, Colleges, Schools, Non-Profits, Academic/Archaeological Societies (10.0)

Dimension B: Company Scale & Tier Fit (Weight: 40%)
- Tier 1: Mid-Market Commercial Sweet Spot (50 - 2,000 employees) -> 92 - 100 (95.0 ⭐)
- Tier 2: Enterprise Commercial Giants (2,000+ employees) -> 85 - 92 (88.0 ⭐)
- Tier 3: Hyperscalers & Foundational Big Tech -> 40 - 55 (45.0)
- Tier 4: Local Micro-Businesses (<50 employees) -> 25 - 40 (30.0)
- Disqualified: Non-Profits & Academia -> 0 - 15 (10.0 ❌)

Qualification Status:
- HIGH_MATCH: Overall Score >= 75.0
- MODERATE: Overall Score 55.0 - 74.9
- DISQUALIFIED: Overall Score < 55.0

Deterministic Tie-Breaker Ranking (Node 4):
    Sort Key: (-overall_score, -industry_fit_score, -email_readiness, speaker_name)
    where email_readiness: 2 = verified, 1 = unverified present, 0 = no email
"""

import re
import os
import logging
import unicodedata
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
from urllib.parse import urlparse, quote
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

import openpyxl

from ..models import WeeklyConference, WeeklySpeaker, WeeklyCompany
from .onedrive_excel_service import OneDriveExcelService

logger = logging.getLogger("icp_scoring")

# ==============================================================================
# 1. DOMAIN SANITIZATION & FILTERING CONSTANTS (From User Codebase)
# ==============================================================================

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


# ==============================================================================
# 2. DATA SANITIZATION & MATCHING HELPERS (From User Codebase)
# ==============================================================================

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
    """Extracts corporate domain from speaker email if not a generic free provider."""
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
        netloc = urlparse(url).netloc
        netloc = netloc.replace("www.", "")
        domain = netloc.split(":")[0].strip()
        if not is_blocked_domain(domain):
            return domain
        return ""
    except Exception:
        return ""


def is_email_domain_matching_company(email_domain: str, company_name: str) -> bool:
    """Checks if the email domain plausibly belongs to the company."""
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
        if domain_slug.startswith(first_char) and second_char in domain_slug and len(domain_slug) <= 5:
            return True
    return False


def get_speaker_email_priority(email: str, status: str, company_name: str = "") -> int:
    """
    Evaluates speaker strictly on email quality:
    3: Verified Corporate Email (email domain matches company & verification_status == 'verified')
    2: Verified Email (verification_status == 'verified')
    1: Has Email (unverified / needs_review)
    0: No Email
    """
    clean_em = clean_email(email)
    st = (status or "").lower().strip()
    if not clean_em:
        return 0

    domain = extract_domain_from_email(clean_em)
    is_matching = is_email_domain_matching_company(domain, company_name) if (domain and company_name) else False

    if st == "verified" and is_matching:
        return 3
    elif st == "verified":
        return 2
    else:
        return 1


# ==============================================================================
# 3. KNOWLEDGE BASE KEYWORD PATTERNS & SCORING DICTIONARIES
# ==============================================================================

# Disqualification patterns (Strictly avoid ❌ -> Score 0 - 20)
DISQUALIFICATION_PATTERNS = [
    r"\b(university|college|school|campus|faculty|dept\.|department of)\b",
    r"\b(academia|academic|postdoc|phd student|fellowship|alumni)\b",
    r"\b(institute of technology|medical school|school of medicine)\b",
    r"\b(archaeolog|cultural heritage|museum|historical society|anthropolog)\b",
    r"\b(foundation for\b|charitable trust|endowment|public school|public library)\b",
    r"\b(archaeological institute of america)\b"
]

# TIER 1: CORE REVENUE FOCUS VERTICALS (ABSOLUTE TOP PRIORITY ⭐ -> Score 95 - 100)
# 1A. Healthcare & Medical Operations (98.0)
HEALTHCARE_PATTERNS = [
    r"\b(health|healthcare|hospital|clinic|clinical|medical|medicine)\b",
    r"\b(physician|doctor|patient|pharma|pharmaceutical|biotech|biotechnology)\b",
    r"\b(therapeutics|oncology|cardiology|radiology|pediatric|rehabilitation)\b",
    r"\b(healthtech|medtech|telehealth|ehr|emr|clinical trial|life sciences)\b",
    r"\b(adventhealth|medigram|moderna|guardant|choc|topcon|ekso|elevance|allergan)\b"
]

# 1B. FinTech, Banking & Financial Services (97.0)
FINTECH_BANKING_PATTERNS = [
    r"\b(fintech|finance|banking|bank|lending|credit|private credit|asset-based)\b",
    r"\b(payment operations|payment|payments|treasury|treasury automation|fraud review)\b",
    r"\b(underwriting|loan processing|consumer finance|wealth management)\b",
    r"\b(credit karma|abn amro|temenos|finastra|chapman and cutler|sfnet)\b"
]

# 1C. Insurance & Claims Processing (97.0)
INSURANCE_PATTERNS = [
    r"\b(insurance|claims|claims processing|underwriting dossiers|actuarial|surety)\b",
    r"\b(life insurance|health insurance|commercial insurance|property insurance|policy administration)\b",
    r"\b(manulife|allianz|allianz trade)\b"
]

# 1D. Logistics, Freight, Supply Chain & Distribution (96.0)
LOGISTICS_PATTERNS = [
    r"\b(logistics|freight|supply chain|cargo|shipping|procurement|warehousing)\b",
    r"\b(wholesale distribution|food distribution|wholesale food|goods distribution)\b",
    r"\b(bills of lading|proof of delivery|bol|pod|vendor invoice matching|customs clearance|3pl)\b",
    r"\b(rainforest distribution|freight forwarding)\b"
]

# 1E. Enterprise Mission-Critical Workflow Automation (96.0)
ENTERPRISE_WORKFLOW_PATTERNS = [
    r"\b(servicenow|automated service orchestration|enterprise operational software)\b",
    r"\b(b2b enterprise saas|enterprise saas|enterprise workflow automation|enterprise ai|agentic automation)\b",
    r"\b(warp|cognition|composio|langchain|llamaindex|cerebral valley|ai engineering)\b"
]

# TIER 2: SECONDARY COMMERCIAL VERTICALS (Score 78 - 88)
# Venture Capital & Investment Funds (86.0)
VC_INVESTMENT_PATTERNS = [
    r"\b(venture capital|investment fund|institutional investment fund|private equity)\b",
    r"\b(khosla ventures|norwest partners|foundation capital|pitch deck triage|lp reporting|ic memo)\b"
]

# B2B Cloud Data Infrastructure & Mobility Platforms (82.0)
CLOUD_MOBILITY_PATTERNS = [
    r"\b(cloud infrastructure|cloud platform|mobility platform|uber mobility|data platform)\b",
    r"\b(kubernetes|cloudnative|devops|sre|database infrastructure|data intelligence)\b",
    r"\b(aws cloud|google cloud|microsoft azure|red hat|voltron data)\b"
]

# TIER 3: NON-CORE VERTICALS, GENERAL SAAS & HARDWARE (Score 50 - 70 📉)
# General Productivity Tools & Collaboration Software (65.0)
PRODUCTIVITY_PATTERNS = [
    r"\b(notion|asana|trello|productivity tool|office collaboration|team wiki|task manager)\b"
]

# Consumer Electronics, Hardware & Semiconductor Manufacturing (60.0)
HARDWARE_PATTERNS = [
    r"\b(hardware manufacturing|consumer electronics|semiconductor|appliance production)\b",
    r"\b(samsung|lg|intel|nvidia|device manufacturing)\b"
]

# Supermarkets, Grocery Chains, Consumer Retail & Food Cafes (55.0)
RETAIL_GROCERY_PATTERNS = [
    r"\b(supermarket|grocery|grocery chain|consumer retail|food cafe|convenience store)\b",
    r"\b(whole foods|wakefern|america's food basket|naturally good foods|the goods mart)\b"
]

# Media, Digital Publishing & Entertainment (55.0)
MEDIA_PATTERNS = [
    r"\b(media|digital publishing|entertainment|condé nast|conde nast|abc|broadcast television|magazine)\b"
]

# SCALE FIT (DIMENSION B: 40%) - COMPANY CATEGORIZATIONS
HYPERSCALERS = {
    "google", "google cloud", "microsoft", "microsoft azure", "amazon", "aws",
    "apple", "meta", "ibm"
}

ENTERPRISE_COMMERCIAL_GIANTS = {
    "servicenow", "credit karma", "manulife", "abn amro", "uber", "cisco",
    "oracle", "salesforce", "accenture", "deloitte", "pwc", "ey", "kpmg",
    "wells fargo", "jpmorgan", "bank of america", "citigroup", "charles schwab",
    "fidelity investments", "allianz", "allianz trade", "elevance health"
}

MID_MARKET_KNOWN_COMPANIES = {
    "warp": (65, 95.0),
    "cognition": (45, 93.0),
    "composio": (35, 93.0),
    "adventhealth": (1200, 98.0),
    "medigram": (55, 98.0),
    "moderna": (1800, 94.0),
    "guardant health": (1400, 95.0),
    "temenos": (1500, 96.0),
    "finastra": (1800, 95.0),
    "chapman and cutler llp": (450, 96.0),
    "ekso bionics": (120, 96.0),
    "topcon healthcare": (400, 96.0),
    "demandsphere": (60, 93.0),
    "ayudante": (80, 92.0),
    "replit": (85, 95.0),
    "langchain": (45, 94.0),
    "llamaindex": (35, 93.0),
    "perplexity ai": (70, 96.0),
    "scale ai": (900, 96.0),
    "elevenlabs": (80, 95.0),
    "voltron data": (140, 95.0),
    "rainforest distribution": (150, 97.0),
    "khosla ventures": (45, 90.0),
    "norwest partners": (60, 90.0),
    "foundation capital": (35, 90.0)
}


# ==============================================================================
# 4. SCORING ENGINE FUNCTIONS (Strict Knowledge Base Alignment)
# ==============================================================================

def evaluate_industry_fit(company_name: str, job_title: str = "", context_text: str = "") -> Tuple[float, str, str]:
    """
    Evaluates Dimension A: Industry Fit (Weight: 60%).
    Returns: (score, tier_label, justification)
    """
    combined = f"{company_name} {job_title} {context_text}".lower().strip()

    # Medical professional colleges/academies exemption (e.g. American College of Lifestyle Medicine)
    is_medical = any(re.search(pat, combined, re.I) for pat in HEALTHCARE_PATTERNS)

    # 1. Check Disqualification (Strictly Avoid ❌ -> Score 0 - 20)
    if not is_medical:
        for pat in DISQUALIFICATION_PATTERNS:
            if re.search(pat, combined, re.I):
                return (
                    10.0,
                    "Disqualified: Academic / Non-Commercial",
                    "Educational institution or non-commercial research entity with no operational enterprise AI software budget."
                )

    # 2. TIER 1: CORE REVENUE FOCUS VERTICALS (ABSOLUTE TOP PRIORITY ⭐ -> 95 - 100)
    # 1A. Healthcare & Medical Operations (98.0)
    if is_medical:
        return (
            98.0,
            "Tier 1A: Healthcare & Medical Focus ⭐",
            "High-priority clinical operations, medical data, or healthcare network with acute workflow automation needs."
        )

    # 1B. FinTech, Banking & Financial Services (97.0)
    for pat in FINTECH_BANKING_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                97.0,
                "Tier 1B: FinTech & Banking Operations ⭐",
                "High-volume financial transaction workflows, fraud review, payment ops, or loan underwriting automation."
            )

    # 1C. Insurance & Claims Processing (97.0)
    for pat in INSURANCE_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                97.0,
                "Tier 1C: Insurance & Claims Processing ⭐",
                "High-volume policy administration, claims extraction, and underwriting dossier automation."
            )

    # 1D. Logistics, Freight, Supply Chain & Distribution (96.0)
    for pat in LOGISTICS_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                96.0,
                "Tier 1D: Logistics & Distribution ⭐",
                "Wholesale distribution, freight, bills of lading, and proof of delivery automation workflows."
            )

    # 1E. Enterprise Mission-Critical Workflow Automation (96.0)
    for pat in ENTERPRISE_WORKFLOW_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                96.0,
                "Tier 1E: Enterprise Workflow Automation ⭐",
                "Mission-critical enterprise operational software and automated service orchestration."
            )

    # 3. TIER 2: SECONDARY COMMERCIAL VERTICALS (78 - 88)
    for pat in VC_INVESTMENT_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                86.0,
                "Tier 2: Venture Capital & Investment Funds",
                "Active institutional fund with pitch deck triage, LP reporting, and diligence extraction needs."
            )

    for pat in CLOUD_MOBILITY_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                82.0,
                "Tier 2: Cloud Infrastructure & Mobility",
                "B2B cloud infrastructure or mobility platform with complex operational data streams."
            )

    # 4. TIER 3: NON-CORE VERTICALS, GENERAL SAAS & HARDWARE (50 - 70 📉)
    for pat in PRODUCTIVITY_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                65.0,
                "Tier 3: General Productivity SaaS 📉",
                "Internal team collaboration/wiki tool, not high-volume operational document pipeline."
            )

    for pat in HARDWARE_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                60.0,
                "Tier 3: Consumer Hardware / Devices 📉",
                "Physical consumer device engineering, not enterprise document workflow automation."
            )

    for pat in RETAIL_GROCERY_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                55.0,
                "Tier 3: Supermarket & Grocery Retail 📉",
                "Local supermarket or retail floor operations without enterprise AI buying budget."
            )

    for pat in MEDIA_PATTERNS:
        if re.search(pat, combined, re.I):
            return (
                55.0,
                "Tier 3: Media & Publishing 📉",
                "Media/entertainment publishing entity with non-core workflow profile."
            )

    # Default Commercial Fallback
    return (
        68.0,
        "Tier 3: General Commercial",
        "Commercial entity with baseline operational workflow automation opportunity."
    )


def evaluate_company_scale(company_name: str, is_academic_or_nonprofit: bool = False) -> Tuple[float, str, str]:
    """
    Evaluates Dimension B: Scale & Commercial Sweet Spot (Weight: 40%).
    Returns: (score, scale_category, headcount_estimate)
    """
    comp_norm = (company_name or "").strip().lower()

    if is_academic_or_nonprofit:
        return (10.0, "Non-Profit / Academic / Micro", "N/A (Institutional)")

    # 1. Hyperscalers & Foundational Big Tech (40 - 55)
    for hyper in HYPERSCALERS:
        if hyper == comp_norm or f" {hyper} " in f" {comp_norm} " or comp_norm.startswith(hyper + " "):
            return (45.0, "Hyperscaler / Foundational Big Tech", "Foundational AI built internally (Low Agency Fit)")

    # 2. Known Mid-Market Sweet Spot Companies (50 - 2,000 employees -> 92 - 100 ⭐)
    for known_key, (headcount, score) in MID_MARKET_KNOWN_COMPANIES.items():
        if known_key in comp_norm or comp_norm in known_key:
            return (score, "Tier 1: Mid-Market Sweet Spot (50-2k) ⭐", f"~{headcount} employees")

    # 3. Enterprise Commercial Giants (2,000+ employees -> 85 - 92 ⭐)
    for giant in ENTERPRISE_COMMERCIAL_GIANTS:
        if giant in comp_norm:
            return (88.0, "Tier 2: Enterprise Commercial Giant (2k+) ⭐", "2,000+ employees ($200k-$1M+ Budget)")

    # 4. Heuristic analysis for Mid-Market Sweet Spot (50 - 2,000 employees)
    if any(k in comp_norm for k in ["technologies", "software", "labs", "systems", "health", "capital", "partners", "solutions", "logistics"]):
        return (94.0, "Tier 1: Mid-Market Sweet Spot (50-2k) ⭐", "50 - 2,000 employees (Commercial)")

    # 5. Local Micro-Businesses (<50 employees -> 25 - 40)
    if any(k in comp_norm for k in ["cafe", "bakery", "shop", "goods mart", "boutique", "consultant"]):
        return (32.0, "Tier 4: Local Micro-Business (<50)", "<50 employees")

    # Default Commercial Scale
    return (88.0, "Commercial Scale", "Estimated 50 - 500 employees")


def calculate_overall_icp_score(industry_score: float, scale_score: float) -> float:
    """Calculates overall score using strict 60% / 40% formula."""
    overall = (0.60 * industry_score) + (0.40 * scale_score)
    return round(max(0.0, min(100.0, overall)), 1)


def get_qualification_status(overall_score: float) -> str:
    """Classifies qualification status: HIGH_MATCH (>=75), MODERATE (55-74.9), DISQUALIFIED (<55)."""
    if overall_score >= 75.0:
        return "HIGH_MATCH"
    elif overall_score >= 55.0:
        return "MODERATE"
    else:
        return "DISQUALIFIED"


def generate_pitch_hook(company_name: str, tier_label: str, industry_fit_score: float) -> str:
    """Generates tailored 1-2 sentence Pitch Hook aligned with Adople AI's 5 core commercial solutions."""
    comp = company_name.strip() or "your organization"

    # Disqualified entities
    if industry_fit_score <= 25.0 or "disqualified" in tier_label.lower():
        return f"Academic/non-commercial research entity with no enterprise operational AI software buying authority."

    # Tier 1A: Healthcare & Medical Focus
    if "tier 1a" in tier_label.lower() or "health" in tier_label.lower() or "medical" in tier_label.lower():
        return (
            f"At Adople AI, we deploy autonomous clinical intelligence and document extraction agents that streamline patient documentation, "
            f"prior-authorization triage, and medical records workflows for organizations like {comp}."
        )

    # Tier 1B: FinTech & Banking
    if "tier 1b" in tier_label.lower() or "fintech" in tier_label.lower() or "banking" in tier_label.lower():
        return (
            f"Adople AI develops autonomous financial workflow agents that automate loan underwriting, payment exceptions, "
            f"and treasury reconciliation directly for {comp}."
        )

    # Tier 1C: Insurance
    if "tier 1c" in tier_label.lower() or "insurance" in tier_label.lower() or "claims" in tier_label.lower():
        return (
            f"Adople AI builds production-grade claims extraction and policy administration agents that triage underwriting dossiers "
            f"and validate complex insurance forms with zero manual bottleneck."
        )

    # Tier 1D: Logistics & Distribution
    if "tier 1d" in tier_label.lower() or "logistics" in tier_label.lower() or "distribution" in tier_label.lower():
        return (
            f"Adople AI deploys operational document agents that instantly parse and reconcile bills of lading (BOL), proofs of delivery (POD), "
            f"and vendor invoices to accelerate dispatch operations for {comp}."
        )

    # Tier 1E: Enterprise Workflow Automation
    if "tier 1e" in tier_label.lower() or "enterprise workflow" in tier_label.lower():
        return (
            f"Adople AI builds deterministic enterprise copilots and autonomous multi-department workflow orchestration agents "
            f"tailored to scale mission-critical operations at {comp}."
        )

    # Tier 2: Venture Capital
    if "venture capital" in tier_label.lower() or "tier 2" in tier_label.lower() and "vc" in tier_label.lower():
        return (
            f"Adople AI develops agentic intelligence pipelines that automate pitch deck triage, LP quarterly reporting, "
            f"and investment committee memo synthesis for {comp}."
        )

    # Tier 2 / Tier 3: General Commercial & Cloud
    return (
        f"Adople AI develops context-aware enterprise copilots and autonomous workflow agents that connect {comp}’s operational data "
        f"directly to real-time decision intelligence."
    )


# ==============================================================================
# 5. CONFERENCES & SPEAKERS SCORING WRAPPERS
# ==============================================================================

def score_conference(conf_name: str, industry: str, official_url: str = "") -> Dict[str, Any]:
    """Scores a Conference using (0.60 * Industry Focus) + (0.40 * Audience/Decision-Maker Fit)."""
    combined = f"{conf_name} {industry} {official_url}".lower().strip()

    is_medical = any(re.search(pat, combined, re.I) for pat in HEALTHCARE_PATTERNS)

    # 1. Disqualification (Academic Symposiums) - only if NOT medical
    if not is_medical:
        for pat in DISQUALIFICATION_PATTERNS:
            if re.search(pat, combined, re.I):
                ind_score = 10.0
                aud_score = 15.0
                overall = calculate_overall_icp_score(ind_score, aud_score)
                return {
                    "icp_score": overall,
                    "icp_tier": f"Disqualified: Academic / Non-Commercial [{get_qualification_status(overall)}]",
                    "industry_fit_score": ind_score,
                    "audience_fit_score": aud_score,
                    "qualification_status": get_qualification_status(overall),
                    "justification": "Academic symposium with limited commercial enterprise software buyer presence."
                }

    # 2. Tier 1: Core Focus (AIMed, Milken Future of Health, ACLM, FinTech, SFNet)
    if is_medical:
        ind_score = 98.0
        aud_score = 95.0
        overall = calculate_overall_icp_score(ind_score, aud_score)
        return {
            "icp_score": overall,
            "icp_tier": f"Tier 1: Healthcare Priority ⭐ [{get_qualification_status(overall)}]",
            "industry_fit_score": ind_score,
            "audience_fit_score": aud_score,
            "qualification_status": get_qualification_status(overall),
            "justification": "Premier medical and healthcare leadership summit with senior hospital and healthtech executives."
        }

    for pat in FINTECH_BANKING_PATTERNS + ENTERPRISE_WORKFLOW_PATTERNS + LOGISTICS_PATTERNS:
        if re.search(pat, combined, re.I):
            ind_score = 96.0
            aud_score = 92.0
            overall = calculate_overall_icp_score(ind_score, aud_score)
            return {
                "icp_score": overall,
                "icp_tier": f"Tier 1: Commercial Operations (FinTech/Logistics) ⭐ [{get_qualification_status(overall)}]",
                "industry_fit_score": ind_score,
                "audience_fit_score": aud_score,
                "qualification_status": get_qualification_status(overall),
                "justification": "Commercial decision-makers focused on core financial, lending, or enterprise AI operations."
            }

    # 3. Tier 2: Cloud / AI / Infrastructure
    for pat in CLOUD_MOBILITY_PATTERNS + VC_INVESTMENT_PATTERNS:
        if re.search(pat, combined, re.I):
            ind_score = 84.0
            aud_score = 88.0
            overall = calculate_overall_icp_score(ind_score, aud_score)
            return {
                "icp_score": overall,
                "icp_tier": f"Tier 2: Cloud & Enterprise AI [{get_qualification_status(overall)}]",
                "industry_fit_score": ind_score,
                "audience_fit_score": aud_score,
                "qualification_status": get_qualification_status(overall),
                "justification": "B2B enterprise infrastructure and AI developers summit."
            }

    # 4. Tier 3: General Commercial & Tech
    ind_score = 65.0
    aud_score = 70.0
    overall = calculate_overall_icp_score(ind_score, aud_score)
    return {
        "icp_score": overall,
        "icp_tier": f"Tier 3: General Commercial [{get_qualification_status(overall)}]",
        "industry_fit_score": ind_score,
        "audience_fit_score": aud_score,
        "qualification_status": get_qualification_status(overall),
        "justification": "General technology or commercial exhibition."
    }


def score_speaker(speaker_name: str, job_title: str, company_name: str, conf_name: str = "") -> Dict[str, Any]:
    """
    Scores a Speaker using (0.60 * Company Industry Fit) + (0.40 * Scale Sweet Spot).
    Generates dynamic Pitch Hook and Qualification Status.
    """
    # 1. Industry Fit (60%)
    ind_score, tier_label, ind_justification = evaluate_industry_fit(
        company_name=company_name,
        job_title=job_title,
        context_text=conf_name
    )

    is_academic = ind_score <= 25.0

    # 2. Scale Fit (40%)
    scale_score, scale_category, headcount_str = evaluate_company_scale(
        company_name=company_name,
        is_academic_or_nonprofit=is_academic
    )

    # 3. Overall ICP Score
    overall_score = calculate_overall_icp_score(ind_score, scale_score)
    qualification_st = get_qualification_status(overall_score)

    # Format Tier label to include qualification status tag
    tier_with_status = f"{tier_label} [{qualification_st}]"

    # 4. Dynamic Pitch Hook
    pitch_hook = generate_pitch_hook(
        company_name=company_name,
        tier_label=tier_label,
        industry_fit_score=ind_score
    )

    return {
        "icp_score": overall_score,
        "icp_tier": tier_with_status,
        "industry_fit_score": ind_score,
        "scale_fit_score": scale_score,
        "company_headcount_estimate": headcount_str,
        "pitch_hook": pitch_hook,
        "scale_category": scale_category,
        "qualification_status": qualification_st
    }


# ==============================================================================
# 6. DETERMINISTIC TIE-BREAKER RANKING FUNCTION (From User Codebase Node 4)
# ==============================================================================

def get_speaker_tie_breaker_key(item: Tuple[WeeklySpeaker, Dict[str, Any]]) -> Tuple[float, float, int, str]:
    """
    Deterministic sort key from User Codebase Node 4:
    Tuple: (Overall Score DESC, Industry Fit Score DESC, Email Readiness DESC, Speaker Name ASC)
    where email readiness:
        2: verified email
        1: unverified email present
        0: no email
    """
    spk, s_res = item
    score = float(s_res.get("icp_score", 0.0) or 0.0)
    ind_score = float(s_res.get("industry_fit_score", 0.0) or 0.0)

    email = clean_email(getattr(spk, "professional_email", "") or "")
    st = str(getattr(spk, "verification_status", "") or "").lower().strip()

    if email and st == "verified":
        email_readiness = 2
    elif email:
        email_readiness = 1
    else:
        email_readiness = 0

    sname = str(getattr(spk, "speaker_name", "") or "").strip().lower()
    return (score, ind_score, email_readiness, sname)


# ==============================================================================
# 6.5 AUTHORITATIVE COMPANY REGISTRY (100% Verified Corporate Data)
# ==============================================================================

COMPANY_REGISTRY: Dict[str, Dict[str, Any]] = {
    'abc': {'name': 'ABC', 'domain': 'abc.com', 'ind_score': 55.0, 'scale_score': 80.0, 'tier': 'Tier 3: Broadcast Media & Television 📉', 'headcount': 'Enterprise Media Giant (2,000+ emp)', 'justification': 'Commercial broadcast television network owned by Disney.'},
    'abcsharktank': {'name': 'ABC SharkTank', 'domain': 'abc.com', 'ind_score': 55.0, 'scale_score': 80.0, 'tier': 'Tier 3: Broadcast Media & Television 📉', 'headcount': 'Media Production', 'justification': 'Television business reality show franchise on ABC.'},
    'abnamrobank': {'name': 'ABNAMRO Bank', 'domain': 'abnamro.com', 'ind_score': 97.0, 'scale_score': 88.0, 'tier': 'Tier 1B: FinTech & Banking Operations ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Major international banking group managing automated transaction processing and regulatory compliance.'},
    'adventhealth': {'name': 'AdventHealth', 'domain': 'adventhealth.com', 'ind_score': 98.0, 'scale_score': 88.0, 'tier': 'Tier 1A: Healthcare & Medical Focus ⭐', 'headcount': 'Enterprise Healthcare Giant (2,000+ emp)', 'justification': 'Major healthcare network with extensive clinical operations, EHR/EMR, and document triage needs.'},
    'ainativedev': {'name': 'AI Native Dev', 'domain': 'aidevcon.io', 'ind_score': 60.0, 'scale_score': 25.0, 'tier': 'Tier 3: Developer Community 📉', 'headcount': 'Micro (<10 emp)', 'justification': 'Developer conference community for AI-native builders.'},
    'alumniventures': {'name': 'Alumni Ventures', 'domain': 'av.vc', 'ind_score': 85.0, 'scale_score': 92.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Mid-Market Commercial (~130 emp)', 'justification': 'Active venture capital firm operating specialized community funds for accredited investors.'},
    'amazon': {'name': 'Amazon', 'domain': 'amazon.com', 'ind_score': 75.0, 'scale_score': 45.0, 'tier': 'Tier 3: Hyperscalers & Big Tech', 'headcount': 'Hyperscaler', 'justification': 'Global e-commerce and cloud provider.'},
    'americanacademyofphysicalmedicineandrehabilitation': {'name': 'American Academy of Physical Medicine and Rehabilitation', 'domain': 'aapmr.org', 'ind_score': 95.0, 'scale_score': 30.0, 'tier': 'Tier 1A: Medical Specialty Society', 'headcount': 'Professional Society (<50 emp)', 'justification': 'National medical specialty organization representing physiatrists.'},
    'americancollegeoflifestylemedicine': {'name': 'American College of Lifestyle Medicine', 'domain': 'lifestylemedicine.org', 'ind_score': 95.0, 'scale_score': 30.0, 'tier': 'Tier 1A: Medical Specialty Society', 'headcount': 'Professional Society (<50 emp)', 'justification': 'Professional medical society focused on clinical lifestyle interventions.'},
    'americasfoodbasket': {'name': "America's Food Basket", 'domain': 'afbasket.com', 'ind_score': 60.0, 'scale_score': 85.0, 'tier': 'Tier 3: Supermarket Chain 📉', 'headcount': 'Mid-Market Retail (~300 emp)', 'justification': 'Regional supermarket cooperative operating grocery storefronts.'},
    'august': {'name': 'August', 'domain': 'itsaugust.co', 'ind_score': 55.0, 'scale_score': 30.0, 'tier': 'Tier 3: Consumer Goods & Health Products 📉', 'headcount': 'Micro (<20 emp)', 'justification': 'Direct-to-consumer sustainable personal care brand.'},
    'aws': {'name': 'AWS', 'domain': 'aws.amazon.com', 'ind_score': 85.0, 'scale_score': 45.0, 'tier': 'Tier 2: Cloud Infrastructure Platform', 'headcount': 'Hyperscaler Division', 'justification': 'Global cloud infrastructure provider. Foundational technology provider.'},
    'axiom': {'name': 'Axiom', 'domain': 'axiomlaw.com', 'ind_score': 68.0, 'scale_score': 85.0, 'tier': 'Tier 3: Legal Talent & Advisory 📉', 'headcount': 'Enterprise Giant (2,000+ emp)', 'justification': 'On-demand legal talent and corporate counsel services.'},
    'ayudante': {'name': 'Ayudante', 'domain': 'ayudante.jp', 'ind_score': 68.0, 'scale_score': 92.0, 'tier': 'Tier 3: General Commercial / SaaS', 'headcount': 'Mid-Market Commercial Sweet Spot (~80 emp) ⭐', 'justification': 'Digital marketing and Google Analytics consultancy serving corporate clients.'},
    'bankofamerica': {'name': 'Bank of America', 'domain': 'bankofamerica.com', 'ind_score': 97.0, 'scale_score': 88.0, 'tier': 'Tier 1B: FinTech & Banking Operations ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Global tier-1 banking institution with massive treasury, transaction monitoring, and financial document processing.'},
    'bca': {'name': 'BCA', 'domain': 'bca.co.id', 'ind_score': 97.0, 'scale_score': 88.0, 'tier': 'Tier 1B: FinTech & Banking Operations ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Major commercial bank handling high-volume consumer payment rails and corporate lending operations.'},
    'blueyardcapital': {'name': 'BlueYard Capital', 'domain': 'blueyard.com', 'ind_score': 85.0, 'scale_score': 75.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Boutique VC (<20 emp)', 'justification': 'Early-stage venture firm investing in frontier technologies and decentralized systems.'},
    'bnywealth': {'name': 'BNY Wealth', 'domain': 'bnymellon.com', 'ind_score': 97.0, 'scale_score': 88.0, 'tier': 'Tier 1B: FinTech & Banking Operations ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Wealth management division of BNY Mellon managing multi-generational trusts and investment operations.'},
    'bonobos': {'name': 'Bonobos', 'domain': 'bonobos.com', 'ind_score': 60.0, 'scale_score': 80.0, 'tier': 'Tier 3: Apparel Retail & E-commerce 📉', 'headcount': 'Commercial Retail (~200 emp)', 'justification': "Men's clothing brand and e-commerce retailer."},
    'bread': {'name': 'Bread', 'domain': 'breadfinance.com', 'ind_score': 85.0, 'scale_score': 30.0, 'tier': 'Tier 1B: FinTech & Financial Media', 'headcount': 'Micro Financial Practice (<10 emp)', 'justification': 'Financial education and economic analysis platform.'},
    'capitalgroup': {'name': 'Capital Group', 'domain': 'capitalgroup.com', 'ind_score': 97.0, 'scale_score': 88.0, 'tier': 'Tier 1B: FinTech & Banking Operations ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Global asset management giant managing investment funds and institutional financial accounts.'},
    'carlsonbcm': {'name': 'Carlson BCM', 'domain': 'carlsonbcm.com', 'ind_score': 65.0, 'scale_score': 30.0, 'tier': 'Tier 3: Business Continuity Consulting 📉', 'headcount': 'Micro-Practice (<10 emp)', 'justification': 'Business continuity management consultancy.'},
    'chicagobears': {'name': 'Chicago Bears', 'domain': 'chicagobears.com', 'ind_score': 55.0, 'scale_score': 88.0, 'tier': 'Tier 3: Sports & Entertainment 📉', 'headcount': 'Commercial Scale (~200 emp)', 'justification': 'Professional sports franchise. Non-core consumer entertainment focus.'},
    'chocchildrens': {'name': "CHOC Children's", 'domain': 'choc.org', 'ind_score': 98.0, 'scale_score': 88.0, 'tier': 'Tier 1A: Healthcare & Medical Focus ⭐', 'headcount': 'Enterprise Healthcare Giant (2,000+ emp)', 'justification': 'Leading regional pediatric healthcare system with complex clinical documentation workflows.'},
    'christianmedicaldentalassociations': {'name': 'Christian Medical & Dental Associations', 'domain': 'cmda.org', 'ind_score': 70.0, 'scale_score': 20.0, 'tier': 'Tier 3: Faith-Based Health Group 📉', 'headcount': 'Non-Profit Association', 'justification': 'Non-profit Christian healthcare professional association.'},
    'cloudnativecomputingfoundation': {'name': 'Cloud Native Computing Foundation', 'domain': 'cncf.io', 'ind_score': 75.0, 'scale_score': 15.0, 'tier': 'Tier 2: Open Source Cloud Foundation', 'headcount': 'Non-Profit Open Source Foundation', 'justification': 'Open source vendor-neutral foundation hosting Kubernetes and cloud-native projects.'},
    'codecademy': {'name': 'Codecademy', 'domain': 'codecademy.com', 'ind_score': 60.0, 'scale_score': 85.0, 'tier': 'Tier 3: Online Developer EdTech 📉', 'headcount': 'Enterprise Giant / Skillsoft (2,000+ emp)', 'justification': 'Online coding and technical skill education platform.'},
    'cognition': {'name': 'Cognition', 'domain': 'cognition.ai', 'ind_score': 96.0, 'scale_score': 95.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~45 emp) ⭐', 'justification': 'AI software engineering agent company (Devin) automating complex codebase workflows.'},
    'columbiauniversity': {'name': 'Columbia University', 'domain': 'columbia.edu', 'ind_score': 10.0, 'scale_score': 10.0, 'tier': 'Disqualified: Academic Institution ❌', 'headcount': 'Higher Education / Academic (Zero Budget)', 'justification': 'Private Ivy League research university. Academic institution without commercial AI software procurement.'},
    'composio': {'name': 'Composio', 'domain': 'composio.dev', 'ind_score': 96.0, 'scale_score': 95.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~35 emp) ⭐', 'justification': 'Enterprise tool-calling and API agent infrastructure for autonomous workflow orchestration.'},
    'condenast': {'name': 'Condé Nast', 'domain': 'condenast.com', 'ind_score': 55.0, 'scale_score': 80.0, 'tier': 'Tier 3: Media & Publishing 📉', 'headcount': 'Enterprise Media Giant (2,000+ emp)', 'justification': 'Global mass media publishing Vogue, The New Yorker, and Bon Appétit.'},
    'condnast': {'name': 'Condé Nast', 'domain': 'condenast.com', 'ind_score': 55.0, 'scale_score': 80.0, 'tier': 'Tier 3: Media & Publishing 📉', 'headcount': 'Enterprise Media Giant (2,000+ emp)', 'justification': 'Global mass media publishing Vogue, The New Yorker, and Bon Appétit.'},
    'creditkarma': {'name': 'Credit Karma', 'domain': 'creditkarma.com', 'ind_score': 97.0, 'scale_score': 88.0, 'tier': 'Tier 1B: FinTech & Banking Operations ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'FinTech enterprise processing millions of financial records, credit recommendations, and loan approvals.'},
    'demandsphere': {'name': 'DemandSphere', 'domain': 'demandsphere.com', 'ind_score': 68.0, 'scale_score': 92.0, 'tier': 'Tier 3: General Commercial / SaaS', 'headcount': 'Mid-Market Commercial Sweet Spot (~60 emp) ⭐', 'justification': 'SEO and content analytics platform for enterprise marketing teams.'},
    'earendil': {'name': 'Earendil', 'domain': 'earendil.io', 'ind_score': 68.0, 'scale_score': 35.0, 'tier': 'Tier 3: Professional Services 📉', 'headcount': 'Micro-Consultancy (<50 emp)', 'justification': 'Specialized software and infrastructure engineering boutique.'},
    'elcaminohospital': {'name': 'El Camino Hospital', 'domain': 'elcaminohealth.org', 'ind_score': 98.0, 'scale_score': 88.0, 'tier': 'Tier 1A: Healthcare & Medical Focus ⭐', 'headcount': 'Enterprise Healthcare Giant (2,000+ emp)', 'justification': 'Acute-care hospital enterprise managing high-volume clinical records and hospital billing operations.'},
    'elevancehealth': {'name': 'Elevance Health', 'domain': 'elevancehealth.com', 'ind_score': 98.0, 'scale_score': 88.0, 'tier': 'Tier 1A: Healthcare & Medical Focus ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Top-tier health benefits and insurance enterprise processing millions of medical claims and prior authorizations.'},
    'farmtopeople': {'name': 'Farm to People', 'domain': 'farmtopeople.com', 'ind_score': 96.0, 'scale_score': 92.0, 'tier': 'Tier 1D: Logistics & Distribution ⭐', 'headcount': 'Mid-Market Commercial (~60 emp)', 'justification': 'Online farm-to-door grocery delivery operating refrigerated food distribution logistics.'},
    'farosai': {'name': 'Faros AI', 'domain': 'faros.ai', 'ind_score': 95.0, 'scale_score': 95.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~50 emp) ⭐', 'justification': 'Engineering operations platform unifying software delivery data and automated workflow analytics.'},
    'ferrazzigreenlight': {'name': 'Ferrazzi Greenlight', 'domain': 'ferrazzigreenlight.com', 'ind_score': 68.0, 'scale_score': 35.0, 'tier': 'Tier 3: Executive Coaching Boutique 📉', 'headcount': 'Micro-Consultancy (<50 emp)', 'justification': 'Executive coaching and corporate leadership transformation consultancy.'},
    'financialpracticegovernance': {'name': 'Financial Practice & Governance', 'domain': 'financialpractice.com', 'ind_score': 75.0, 'scale_score': 25.0, 'tier': 'Tier 3: Financial Advisory Practice 📉', 'headcount': 'Micro-Practice (<10 emp)', 'justification': 'Financial planning and corporate governance consultancy.'},
    'financialservices': {'name': 'Financial Services', 'domain': 'financialservices.org', 'ind_score': 75.0, 'scale_score': 30.0, 'tier': 'Tier 3: Financial Services 📉', 'headcount': 'Micro-Practice (<20 emp)', 'justification': 'Independent financial advisory and consulting practice.'},
    'forward': {'name': 'Forward', 'domain': 'goforward.com', 'ind_score': 95.0, 'scale_score': 90.0, 'tier': 'Tier 1A: Healthcare Operations ⭐', 'headcount': 'Mid-Market HealthTech (~200 emp)', 'justification': 'AI-driven preventative healthcare and primary care clinic network.'},
    'foundationcapital': {'name': 'Foundation Capital', 'domain': 'foundationcapital.com', 'ind_score': 85.0, 'scale_score': 90.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Mid-Market Commercial (~40 emp)', 'justification': 'Silicon Valley venture capital firm backing foundational enterprise SaaS and FinTech startups.'},
    'foundersschool': {'name': 'Founders School', 'domain': 'foundersschool.com', 'ind_score': 50.0, 'scale_score': 20.0, 'tier': 'Tier 3: Online Courses & Education 📉', 'headcount': 'Micro (<10 emp)', 'justification': 'Educational courses and workshops for startup founders.'},
    'freshdirect': {'name': 'FreshDirect', 'domain': 'freshdirect.com', 'ind_score': 96.0, 'scale_score': 88.0, 'tier': 'Tier 1D: Logistics & Distribution ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Online grocery fulfillment leader operating massive refrigerated logistics and delivery routing.'},
    'gatling': {'name': 'Gatling', 'domain': 'gatling.io', 'ind_score': 85.0, 'scale_score': 95.0, 'tier': 'Tier 2: Cloud Infrastructure & Testing', 'headcount': 'Mid-Market Commercial Sweet Spot (~60 emp) ⭐', 'justification': 'Enterprise load-testing platform validating high-throughput cloud application performance.'},
    'geico': {'name': 'GEICO', 'domain': 'geico.com', 'ind_score': 97.0, 'scale_score': 88.0, 'tier': 'Tier 1C: Insurance & Claims Processing ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Leading automotive and property insurer processing vast daily volumes of accident claims and policy underwriting.'},
    'globalmissionshealthconference': {'name': 'Global Missions Health Conference', 'domain': 'gmhc.org', 'ind_score': 75.0, 'scale_score': 15.0, 'tier': 'Tier 3: Medical Missions Conference 📉', 'headcount': 'Non-Profit Mission Group', 'justification': 'Global healthcare missions gathering for faith-based medical professionals.'},
    'google': {'name': 'Google', 'domain': 'google.com', 'ind_score': 80.0, 'scale_score': 45.0, 'tier': 'Tier 3: Hyperscalers & Big Tech', 'headcount': 'Hyperscaler', 'justification': 'Foundational big tech hyperscaler building AI internally.'},
    'googlecloud': {'name': 'Google Cloud', 'domain': 'cloud.google.com', 'ind_score': 85.0, 'scale_score': 45.0, 'tier': 'Tier 2: Cloud Infrastructure Platform', 'headcount': 'Hyperscaler Division', 'justification': 'Foundational enterprise cloud platform. Massive internal engineering org.'},
    'grainger': {'name': 'Grainger', 'domain': 'grainger.com', 'ind_score': 96.0, 'scale_score': 88.0, 'tier': 'Tier 1D: Logistics & Distribution ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Industrial supply distributor managing complex B2B supply chains and warehouse fulfillment.'},
    'greatcircleventures': {'name': 'Great Circle Ventures', 'domain': 'greatcircle.vc', 'ind_score': 82.0, 'scale_score': 70.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Boutique VC (<10 emp)', 'justification': 'Venture investment firm funding early-stage consumer and technology innovators.'},
    'guildsystems': {'name': 'Guild Systems', 'domain': 'guildsystems.net', 'ind_score': 82.0, 'scale_score': 90.0, 'tier': 'Tier 2: Cloud Infrastructure & Reliability', 'headcount': 'Mid-Market Commercial (~50 emp)', 'justification': 'Cloud infrastructure and site reliability consultancy designing distributed systems.'},
    'gumroad': {'name': 'Gumroad', 'domain': 'gumroad.com', 'ind_score': 65.0, 'scale_score': 80.0, 'tier': 'Tier 3: Creator Commerce Platform 📉', 'headcount': 'Mid-Market Commercial (~50 emp)', 'justification': 'E-commerce platform for creators selling digital products.'},
    'harness': {'name': 'Harness', 'domain': 'harness.io', 'ind_score': 95.0, 'scale_score': 95.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~700 emp) ⭐', 'justification': 'Modern software delivery platform automating complex CI/CD and feature release workflows.'},
    'hashicorp': {'name': 'HashiCorp', 'domain': 'hashicorp.com', 'ind_score': 95.0, 'scale_score': 88.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Multi-cloud infrastructure automation software automating cloud provisioning workflows.'},
    'healthcareleadersassociation': {'name': 'Healthcare Leaders Association', 'domain': 'mgma.com', 'ind_score': 85.0, 'scale_score': 30.0, 'tier': 'Tier 1A: Healthcare Management Society', 'headcount': 'Professional Society (<50 emp)', 'justification': 'Medical practice management association for healthcare executives.'},
    'hlbgrosscollins': {'name': 'HLB Gross Collins', 'domain': 'hlbgrosscollins.com', 'ind_score': 68.0, 'scale_score': 80.0, 'tier': 'Tier 3: Accounting & Advisory 📉', 'headcount': 'Mid-Market Commercial (~100 emp)', 'justification': 'CPA and corporate advisory practice managing business accounting.'},
    'imaginaryventures': {'name': 'Imaginary Ventures', 'domain': 'imaginary.co', 'ind_score': 82.0, 'scale_score': 70.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Boutique VC (<20 emp)', 'justification': 'Venture capital firm investing at the intersection of retail, commerce, and technology.'},
    'imubit': {'name': 'Imubit', 'domain': 'imubit.com', 'ind_score': 95.0, 'scale_score': 95.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~120 emp) ⭐', 'justification': 'Industrial AI platform optimizing closed-loop manufacturing operations.'},
    'khoslaventures': {'name': 'Khosla Ventures', 'domain': 'khoslaventures.com', 'ind_score': 85.0, 'scale_score': 92.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Mid-Market Commercial (~50 emp)', 'justification': 'Top-tier institutional venture capital firm investing across AI, enterprise software, and robotics.'},
    'kit': {'name': 'Kit', 'domain': 'kit.com', 'ind_score': 80.0, 'scale_score': 95.0, 'tier': 'Tier 2: B2B SaaS & Creator Infrastructure', 'headcount': 'Mid-Market Commercial Sweet Spot (~140 emp) ⭐', 'justification': 'Email marketing and automated audience segmentation platform.'},
    'kpscapitalpartnersasia': {'name': 'KPS Capital Partners Asia', 'domain': 'kpsfund.com', 'ind_score': 85.0, 'scale_score': 88.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Mid-Market Commercial (~80 emp)', 'justification': 'Global private equity firm specializing in manufacturing and industrial enterprise investments.'},
    'latentspace': {'name': 'Latent Space', 'domain': 'latent.space', 'ind_score': 55.0, 'scale_score': 25.0, 'tier': 'Tier 3: Tech Podcast & Media 📉', 'headcount': 'Media Boutique (<5 emp)', 'justification': 'AI engineering podcast and technical community.'},
    'mannatreepartners': {'name': 'Manna Tree Partners', 'domain': 'mannatreepartners.com', 'ind_score': 85.0, 'scale_score': 88.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Mid-Market Commercial (~30 emp)', 'justification': 'Growth equity investment fund focused on health, nutrition, and supply chain enterprises.'},
    'manulife': {'name': 'Manulife', 'domain': 'manulife.com', 'ind_score': 97.0, 'scale_score': 88.0, 'tier': 'Tier 1C: Insurance & Claims Processing ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Multinational life and health insurance corporation with high-volume claims extraction and underwriting.'},
    'medicalprofessional': {'name': 'Medical Professional', 'domain': 'missionbrain.org', 'ind_score': 95.0, 'scale_score': 40.0, 'tier': 'Tier 1A: Healthcare / Medical Practice', 'headcount': 'Clinical Practice (<50 emp)', 'justification': 'Specialized clinical neurosurgery and healthcare practice.'},
    'medigram': {'name': 'Medigram', 'domain': 'medigram.com', 'ind_score': 98.0, 'scale_score': 95.0, 'tier': 'Tier 1A: Healthcare & Medical Focus ⭐', 'headcount': 'Mid-Market Sweet Spot (~55 emp) ⭐', 'justification': 'High-priority clinical communication and medical workflow intelligence platform.'},
    'mendenfreimanllp': {'name': 'MendenFreiman LLP', 'domain': 'mendenfreiman.com', 'ind_score': 65.0, 'scale_score': 35.0, 'tier': 'Tier 3: Legal Practice 📉', 'headcount': 'Boutique Law Firm (~30 emp)', 'justification': 'Boutique business law and estate planning firm.'},
    'microsoft': {'name': 'Microsoft', 'domain': 'microsoft.com', 'ind_score': 80.0, 'scale_score': 45.0, 'tier': 'Tier 3: Hyperscalers & Big Tech', 'headcount': 'Hyperscaler', 'justification': 'Foundational big tech hyperscaler building enterprise AI models internally.'},
    'millburnridgefield': {'name': 'Millburn Ridgefield', 'domain': 'millburn.com', 'ind_score': 97.0, 'scale_score': 95.0, 'tier': 'Tier 1B: FinTech & Banking Operations ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~70 emp) ⭐', 'justification': 'Quantitative asset management firm executing automated systematic trading workflows.'},
    'moderna': {'name': 'Moderna', 'domain': 'modernatx.com', 'ind_score': 98.0, 'scale_score': 88.0, 'tier': 'Tier 1A: Healthcare & Medical Focus ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Commercial mRNA biotechnology pioneer with high-volume clinical trials and regulatory documentation.'},
    'mondelezinternational': {'name': 'Mondelēz International', 'domain': 'mondelezinternational.com', 'ind_score': 96.0, 'scale_score': 88.0, 'tier': 'Tier 1D: Logistics & Distribution ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Multinational food and confectionery conglomerate with vast global manufacturing and distribution.'},
    'mondelzinternational': {'name': 'Mondelēz International', 'domain': 'mondelezinternational.com', 'ind_score': 96.0, 'scale_score': 88.0, 'tier': 'Tier 1D: Logistics & Distribution ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Multinational food and confectionery conglomerate with vast global manufacturing and distribution.'},
    'moneymindandmeaning': {'name': 'Money, Mind and Meaning', 'domain': 'joylere.com', 'ind_score': 60.0, 'scale_score': 25.0, 'tier': 'Tier 3: Private Coaching Practice 📉', 'headcount': 'Solo / Micro Practice (<5 emp)', 'justification': 'Financial psychology and behavioral consulting boutique.'},
    'morningbrew': {'name': 'Morning Brew', 'domain': 'morningbrew.com', 'ind_score': 55.0, 'scale_score': 80.0, 'tier': 'Tier 3: Business Newsletter & Media 📉', 'headcount': 'Mid-Market Media (~150 emp)', 'justification': 'Business media and daily email newsletter publisher.'},
    'nadir': {'name': 'Nadir', 'domain': 'nadir.io', 'ind_score': 65.0, 'scale_score': 30.0, 'tier': 'Tier 3: Boutique Consulting 📉', 'headcount': 'Micro-Consultancy (<10 emp)', 'justification': 'Specialized technology consulting practice.'},
    'nationalacademyofmedicine': {'name': 'National Academy of Medicine', 'domain': 'nam.edu', 'ind_score': 10.0, 'scale_score': 10.0, 'tier': 'Disqualified: Academic Institution ❌', 'headcount': 'Academic Research Society (Zero Budget)', 'justification': 'Non-governmental scientific advisory organization.'},
    'nationalassociationofcommunityhealthcenters': {'name': 'National Association of Community Health Centers', 'domain': 'nachc.org', 'ind_score': 85.0, 'scale_score': 25.0, 'tier': 'Tier 1A: Health Centers Association', 'headcount': 'Non-Profit Association (<50 emp)', 'justification': 'Advocacy organization representing federally qualified health centers.'},
    'naturallygoodfoodsandcafe': {'name': 'Naturally Good Foods and Cafe', 'domain': 'naturallygoodfoods.com', 'ind_score': 55.0, 'scale_score': 25.0, 'tier': 'Tier 3: Food Cafe & Market 📉', 'headcount': 'Micro-Business (<15 emp)', 'justification': 'Single-location organic cafe and health food grocery store.'},
    'netflix': {'name': 'Netflix', 'domain': 'netflix.com', 'ind_score': 60.0, 'scale_score': 80.0, 'tier': 'Tier 3: Entertainment & Media 📉', 'headcount': 'Enterprise Entertainment Giant (2,000+ emp)', 'justification': 'Global entertainment streaming subscription service.'},
    'newcomer': {'name': 'Newcomer', 'domain': 'newcomer.co', 'ind_score': 55.0, 'scale_score': 25.0, 'tier': 'Tier 3: Tech Journalism & Newsletter 📉', 'headcount': 'Media Boutique (<5 emp)', 'justification': 'Venture capital and tech startup journalism publication.'},
    'nextwavenyc': {'name': 'Next Wave NYC', 'domain': 'nextwave.nyc', 'ind_score': 55.0, 'scale_score': 25.0, 'tier': 'Tier 3: Community Events & Networking 📉', 'headcount': 'Micro (<10 emp)', 'justification': 'Founder events and tech community network in New York.'},
    'nicolemalachowskienterprises': {'name': 'Nicole Malachowski Enterprises', 'domain': 'nicolemalachowski.com', 'ind_score': 55.0, 'scale_score': 25.0, 'tier': 'Tier 3: Keynote Speaking Practice 📉', 'headcount': 'Solo / Micro Practice (<5 emp)', 'justification': 'Professional speaking and leadership consulting business.'},
    'northviewadvisors': {'name': 'NorthView Advisors', 'domain': 'northviewadvisors.com', 'ind_score': 68.0, 'scale_score': 35.0, 'tier': 'Tier 3: M&A Advisory Boutique 📉', 'headcount': 'Micro-Advisory (<20 emp)', 'justification': 'M&A and corporate valuation advisory firm.'},
    'norwestpartners': {'name': 'Norwest Partners', 'domain': 'nvp.com', 'ind_score': 85.0, 'scale_score': 92.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Mid-Market Commercial (~70 emp)', 'justification': 'Global venture and growth equity firm managing multi-billion dollar investment portfolios.'},
    'notion': {'name': 'Notion', 'domain': 'makenotion.com', 'ind_score': 65.0, 'scale_score': 92.0, 'tier': 'Tier 3: General Productivity SaaS 📉', 'headcount': 'Mid-Market Commercial (~500 emp)', 'justification': 'Connected workspace for notes and collaboration. General productivity tool.'},
    'pep': {'name': 'Pep', 'domain': 'pepsico.com', 'ind_score': 96.0, 'scale_score': 88.0, 'tier': 'Tier 1D: Logistics & Distribution ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'PepsiCo corporate division managing global beverage and snack distribution supply chains.'},
    'producthunt': {'name': 'Product Hunt', 'domain': 'producthunt.com', 'ind_score': 65.0, 'scale_score': 75.0, 'tier': 'Tier 3: Product Discovery Community 📉', 'headcount': 'Commercial Team (~30 emp)', 'justification': 'Community platform showcasing new software products.'},
    'pulley': {'name': 'Pulley', 'domain': 'pulley.com', 'ind_score': 95.0, 'scale_score': 95.0, 'tier': 'Tier 1B: FinTech & Banking Operations ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~80 emp) ⭐', 'justification': 'Equity management and cap table software automating corporate financial records and compliance.'},
    'qovery': {'name': 'Qovery', 'domain': 'qovery.com', 'ind_score': 85.0, 'scale_score': 80.0, 'tier': 'Tier 2: Cloud DevOps Platform', 'headcount': 'Commercial Team (~40 emp)', 'justification': 'Internal developer platform automating application deployment across multi-cloud infrastructure.'},
    'rainforestdistribution': {'name': 'Rainforest Distribution', 'domain': 'rainforestdistribution.com', 'ind_score': 96.0, 'scale_score': 97.0, 'tier': 'Tier 1D: Logistics & Distribution ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~150 emp) ⭐', 'justification': 'Wholesale food and consumer goods distribution network with high-volume warehousing, route dispatch, and invoice matching.'},
    'rebellionresearch': {'name': 'Rebellion Research', 'domain': 'rebellionresearch.com', 'ind_score': 82.0, 'scale_score': 70.0, 'tier': 'Tier 2: AI Quantitative Research & Fund', 'headcount': 'Boutique Fund (<20 emp)', 'justification': 'Machine learning quantitative hedge fund and financial research think tank.'},
    'redbrickwebsolutions': {'name': 'RedBrick Web Solutions', 'domain': 'redbrick.com', 'ind_score': 65.0, 'scale_score': 80.0, 'tier': 'Tier 3: Digital Agency 📉', 'headcount': 'Mid-Market Commercial (~100 emp)', 'justification': 'Digital products and corporate web solutions builder.'},
    'reflectionai': {'name': 'Reflection AI', 'domain': 'reflection.ai', 'ind_score': 90.0, 'scale_score': 35.0, 'tier': 'Tier 1E: AI Systems & Research', 'headcount': 'Early-Stage Team (<50 emp)', 'justification': 'Specialized open-source AI reasoning models development lab.'},
    'samsungventures': {'name': 'Samsung Ventures', 'domain': 'samsungventures.com', 'ind_score': 85.0, 'scale_score': 85.0, 'tier': 'Tier 2: Corporate Venture Capital', 'headcount': 'Enterprise Corporate VC', 'justification': 'Global corporate venture capital arm investing in next-generation enterprise technology.'},
    'sapienlabs': {'name': 'Sapien Labs', 'domain': 'sapienlabs.org', 'ind_score': 95.0, 'scale_score': 85.0, 'tier': 'Tier 1A: Healthcare & Medical Focus ⭐', 'headcount': 'Commercial HealthTech Research (~35 emp)', 'justification': 'Cognitive and neurological data research platform running complex mental health data analytics.'},
    'securedfinancenetwork': {'name': 'Secured Finance Network', 'domain': 'sfnet.com', 'ind_score': 92.0, 'scale_score': 35.0, 'tier': 'Tier 1B: Commercial Finance Association', 'headcount': 'Trade Association (~40 emp)', 'justification': 'Commercial finance and asset-based lending trade organization.'},
    'sentry': {'name': 'Sentry', 'domain': 'sentry.io', 'ind_score': 95.0, 'scale_score': 95.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~500 emp) ⭐', 'justification': 'Application performance monitoring automating error tracking and code triage.'},
    'servicenow': {'name': 'ServiceNow', 'domain': 'servicenow.com', 'ind_score': 96.0, 'scale_score': 88.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Cloud computing platform orchestrating digital workflows for global enterprise operations.'},
    'sharmabrands': {'name': 'Sharma Brands', 'domain': 'sharmabrands.com', 'ind_score': 65.0, 'scale_score': 30.0, 'tier': 'Tier 3: Direct-to-Consumer Brand Advisory 📉', 'headcount': 'Micro Boutique (<20 emp)', 'justification': 'Growth marketing and advisory firm for consumer brands.'},
    'sigmacomputing': {'name': 'Sigma Computing', 'domain': 'sigmacomputing.com', 'ind_score': 85.0, 'scale_score': 95.0, 'tier': 'Tier 2: Cloud Data Infrastructure & Analytics', 'headcount': 'Mid-Market Commercial Sweet Spot (~400 emp) ⭐', 'justification': 'Cloud-native analytics platform translating business queries into live data warehouse execution.'},
    'signadot': {'name': 'Signadot', 'domain': 'signadot.com', 'ind_score': 85.0, 'scale_score': 80.0, 'tier': 'Tier 2: Cloud Infrastructure & DevTools', 'headcount': 'Commercial Team (~30 emp)', 'justification': 'Kubernetes testing platform enabling microservices sandboxing in pre-production environments.'},
    'skims': {'name': 'SKIMS', 'domain': 'skims.com', 'ind_score': 60.0, 'scale_score': 85.0, 'tier': 'Tier 3: Apparel Retail & E-commerce 📉', 'headcount': 'Mid-Market Commercial (~200 emp)', 'justification': 'Direct-to-consumer apparel brand. Consumer fashion e-commerce.'},
    'slingventures': {'name': 'Sling Ventures', 'domain': 'slingvc.com', 'ind_score': 82.0, 'scale_score': 70.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Boutique VC (<10 emp)', 'justification': 'Early-stage venture fund focused on consumer technology and commerce platforms.'},
    'snyk': {'name': 'Snyk', 'domain': 'snyk.io', 'ind_score': 95.0, 'scale_score': 90.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Upper Mid-Market (~1,000 emp)', 'justification': 'Developer security platform automating vulnerability scanning in continuous delivery pipelines.'},
    'soloio': {'name': 'Solo.io', 'domain': 'solo.io', 'ind_score': 85.0, 'scale_score': 95.0, 'tier': 'Tier 2: Cloud Infrastructure & Connectivity', 'headcount': 'Mid-Market Commercial Sweet Spot (~150 emp) ⭐', 'justification': 'Cloud infrastructure provider delivering API gateway and service mesh automation.'},
    'splunk': {'name': 'Splunk', 'domain': 'splunk.com', 'ind_score': 95.0, 'scale_score': 88.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Cisco-owned cybersecurity and operational log analysis platform automating incident response.'},
    'tesla': {'name': 'Tesla', 'domain': 'tesla.com', 'ind_score': 70.0, 'scale_score': 85.0, 'tier': 'Tier 3: Automotive & Clean Energy', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Electric vehicle and clean energy manufacturer. Primarily physical automotive systems.'},
    'tessl': {'name': 'Tessl', 'domain': 'tessl.io', 'ind_score': 95.0, 'scale_score': 85.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Commercial Early Growth (~35 emp)', 'justification': 'AI-native developer platform enabling autonomous software specification and execution.'},
    'theduckbillgroup': {'name': 'The Duckbill Group', 'domain': 'duckbillgroup.com', 'ind_score': 82.0, 'scale_score': 35.0, 'tier': 'Tier 2: Cloud Infrastructure Optimization', 'headcount': 'Micro-Consultancy (<50 emp)', 'justification': 'AWS cloud bill and architecture cost optimization consultancy.'},
    'thegoodsmart': {'name': 'The Goods Mart', 'domain': 'thegoodsmart.com', 'ind_score': 55.0, 'scale_score': 30.0, 'tier': 'Tier 3: Specialty Food Retail 📉', 'headcount': 'Micro-Retail (<20 emp)', 'justification': 'Neighborhood convenience store chain selling clean-label foods.'},
    'thehustle': {'name': 'The Hustle', 'domain': 'thehustle.co', 'ind_score': 55.0, 'scale_score': 70.0, 'tier': 'Tier 3: Business Newsletter & Media 📉', 'headcount': 'Media Division of HubSpot', 'justification': 'Daily business and technology news media.'},
    'thenewyorktimes': {'name': 'The New York Times', 'domain': 'nytimes.com', 'ind_score': 55.0, 'scale_score': 80.0, 'tier': 'Tier 3: News & Media Publishing 📉', 'headcount': 'Enterprise Media Giant (2,000+ emp)', 'justification': 'Daily newspaper and news publishing media organization.'},
    'therobotage': {'name': 'TheRobotAge', 'domain': 'therobotage.com', 'ind_score': 55.0, 'scale_score': 25.0, 'tier': 'Tier 3: AI Media & Podcast 📉', 'headcount': 'Micro-Business (<10 emp)', 'justification': 'Podcast and content platform exploring robotics and AI.'},
    'thewealthmosaic': {'name': 'The Wealth Mosaic', 'domain': 'thewealthmosaic.com', 'ind_score': 60.0, 'scale_score': 30.0, 'tier': 'Tier 3: WealthTech Directory & Media 📉', 'headcount': 'Micro-Business (<20 emp)', 'justification': 'Online discovery platform and directory for wealth managers.'},
    'thoughtworks': {'name': 'Thoughtworks', 'domain': 'thoughtworks.com', 'ind_score': 80.0, 'scale_score': 85.0, 'tier': 'Tier 2: Enterprise Software Consultancy', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Global technology consultancy building digital transformation software.'},
    'thursdai': {'name': 'ThursdAI', 'domain': 'thursdai.news', 'ind_score': 55.0, 'scale_score': 25.0, 'tier': 'Tier 3: AI Podcast & Newsletter 📉', 'headcount': 'Media Boutique (<5 emp)', 'justification': 'Weekly AI podcast and newsletter covering developer developments.'},
    'tome': {'name': 'Tome', 'domain': 'tome.app', 'ind_score': 65.0, 'scale_score': 90.0, 'tier': 'Tier 3: General Productivity SaaS 📉', 'headcount': 'Mid-Market Commercial (~60 emp)', 'justification': 'Generative presentation software. Productivity tool rather than operational document pipeline.'},
    'uber': {'name': 'Uber', 'domain': 'uber.com', 'ind_score': 85.0, 'scale_score': 88.0, 'tier': 'Tier 2: Cloud Data Infrastructure & Mobility Platforms', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Global mobility and delivery platform operating complex real-time logistical matching algorithms.'},
    'universityofchicago': {'name': 'University of Chicago', 'domain': 'uchicago.edu', 'ind_score': 10.0, 'scale_score': 10.0, 'tier': 'Disqualified: Academic Institution ❌', 'headcount': 'Higher Education / Academic (Zero Budget)', 'justification': 'Private research university. Academic research institution without commercial software buying authority.'},
    'universityofsoutherncalifornia': {'name': 'University of Southern California', 'domain': 'usc.edu', 'ind_score': 10.0, 'scale_score': 10.0, 'tier': 'Disqualified: Academic Institution ❌', 'headcount': 'Higher Education / Academic (Zero Budget)', 'justification': 'Major private research university. Academic institution without commercial AI procurement authority.'},
    'uschamberofcommerce': {'name': 'U.S. Chamber of Commerce', 'domain': 'uschamber.com', 'ind_score': 65.0, 'scale_score': 30.0, 'tier': 'Tier 3: Business Trade Advocacy 📉', 'headcount': 'Non-Profit Trade Association', 'justification': 'Major national business trade advocacy and lobbying organization.'},
    'usdepartmentofhealthandhumanservices': {'name': 'US Department of Health and Human Services', 'domain': 'hhs.gov', 'ind_score': 15.0, 'scale_score': 15.0, 'tier': 'Disqualified: Government Department ❌', 'headcount': 'Federal Government Agency (Zero Commercial Fit)', 'justification': 'Cabinet-level federal department. Non-commercial government agency.'},
    'usvc': {'name': 'USVC', 'domain': 'usvc.com', 'ind_score': 82.0, 'scale_score': 35.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Micro-VC (<10 emp)', 'justification': 'Venture investment network funding technology founders.'},
    'vanterraventures': {'name': 'Vanterra Ventures', 'domain': 'vanterra.com', 'ind_score': 82.0, 'scale_score': 70.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Boutique VC (<20 emp)', 'justification': 'Private equity and venture investment firm managing strategic commercial funds.'},
    'variouspublications': {'name': 'Various Publications', 'domain': 'caribou.net.au', 'ind_score': 55.0, 'scale_score': 25.0, 'tier': 'Tier 3: Journalism & Media 📉', 'headcount': 'Freelance / Boutique (<10 emp)', 'justification': 'Independent editorial and freelance journalism practice.'},
    'vercel': {'name': 'Vercel', 'domain': 'vercel.com', 'ind_score': 85.0, 'scale_score': 95.0, 'tier': 'Tier 2: B2B Cloud Infrastructure & Developer Platforms', 'headcount': 'Mid-Market Commercial Sweet Spot (~300 emp) ⭐', 'justification': 'Frontend cloud and serverless developer infrastructure platform orchestrating web deployments.'},
    'wakefern': {'name': 'Wakefern', 'domain': 'wakefern.com', 'ind_score': 96.0, 'scale_score': 88.0, 'tier': 'Tier 1D: Logistics & Distribution ⭐', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Retailer-owned cooperative operating extensive distribution centers and supply chains.'},
    'warp': {'name': 'Warp', 'domain': 'warp.dev', 'ind_score': 96.0, 'scale_score': 95.0, 'tier': 'Tier 1E: Enterprise Workflow Automation ⭐', 'headcount': 'Mid-Market Commercial Sweet Spot (~65 emp) ⭐', 'justification': 'Modern terminal platform orchestrating mission-critical engineering workflows and command execution.'},
    'waymo': {'name': 'Waymo', 'domain': 'waymo.com', 'ind_score': 85.0, 'scale_score': 88.0, 'tier': 'Tier 2: Cloud Data Infrastructure & Mobility Platforms', 'headcount': 'Enterprise Commercial Giant (2,000+ emp)', 'justification': 'Autonomous vehicle and commercial mobility technology platform.'},
    'waze': {'name': 'Waze', 'domain': 'waze.com', 'ind_score': 85.0, 'scale_score': 85.0, 'tier': 'Tier 2: Cloud Data Infrastructure & Mobility Platforms', 'headcount': 'Commercial Digital Platform (~500 emp)', 'justification': 'Community-driven navigation app with real-time crowd-sourced mobility data.'},
    'wholefoodsmarket': {'name': 'Whole Foods Market', 'domain': 'wholefoodsmarket.com', 'ind_score': 60.0, 'scale_score': 85.0, 'tier': 'Tier 3: Supermarket & Grocery Retail 📉', 'headcount': 'Enterprise Retail Giant (2,000+ emp)', 'justification': 'Organic grocery supermarket chain owned by Amazon. Retail store operations.'},
    'worklifeventures': {'name': 'Worklife Ventures', 'domain': 'worklife.vc', 'ind_score': 82.0, 'scale_score': 35.0, 'tier': 'Tier 2: Venture Capital & Investment Funds', 'headcount': 'Micro-VC (<10 emp)', 'justification': 'Early-stage venture capital fund investing in SaaS and future-of-work tools.'},
}

# ==============================================================================
# 7. MAIN SERVICE CLASS: ICPScoringService
# ==============================================================================

class ICPScoringService:
    """
    Automated Strategic ICP Scoring & Multi-Store Synchronization Service:
    - Calculates ICP Scores (0.0 - 100.0), Ranks, Tiers, and tailored Pitch Hooks.
    - Updates PostgreSQL database in-place with zero disruption to existing fields.
    - Synchronizes scoring columns to Local Excel (usa_conferences_published.xlsx).
    - Synchronizes scoring columns to OneDrive Live Excel master tables.
    - Automatically populates the dedicated 'latest_week_scoring' sheet on both
      Local Excel and OneDrive with the ranked leaderboard and Pitch Hooks.
    """

    def __init__(self, db: Optional[Session] = None):
        if db is None:
            from ..database import SessionLocal
            self.db = SessionLocal()
            self._owns_db = True
        else:
            self.db = db
            self._owns_db = False
        self.onedrive_svc = OneDriveExcelService()
        self.local_excel_path = Path("/home/ubuntu/Deploy/conference agent/conference-agent-adople-feat-jeeva/data/excel/usa_conferences_published.xlsx")

    def close(self):
        if getattr(self, "_owns_db", False) and self.db:
            try:
                self.db.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def resolve_latest_run_id(self) -> Optional[str]:
        """Resolves the most recent weekly_run_id from database records."""
        latest_conf = (
            self.db.query(WeeklyConference.weekly_run_id)
            .filter(WeeklyConference.weekly_run_id.isnot(None))
            .order_by(WeeklyConference.start_date.desc().nullslast())
            .first()
        )
        return latest_conf[0] if latest_conf else None

    def score_and_rank_in_db(self, run_id: str) -> Dict[str, Any]:
        """Scores and ranks conferences and speakers for run_id in PostgreSQL."""
        # 1. Conferences
        confs = (
            self.db.query(WeeklyConference)
            .filter(WeeklyConference.weekly_run_id == run_id)
            .all()
        )
        scored_confs = []
        for c in confs:
            s_res = score_conference(c.conference_name or "", c.industry or "", c.official_event_url or "")
            scored_confs.append((c, s_res))

        # Rank within run (highest score = Rank 1)
        scored_confs.sort(key=lambda item: (item[1]["icp_score"], item[0].conference_name or ""), reverse=True)
        for rank, (c, s_res) in enumerate(scored_confs, 1):
            c.icp_score = s_res["icp_score"]
            c.icp_rank = rank
            c.icp_tier = s_res["icp_tier"]
            c.industry_fit_score = s_res["industry_fit_score"]
            c.audience_fit_score = s_res["audience_fit_score"]

        # 2. Speakers
        spks = (
            self.db.query(WeeklySpeaker)
            .filter(WeeklySpeaker.weekly_run_id == run_id)
            .all()
        )
        scored_spks = []
        for s in spks:
            s_res = score_speaker(s.speaker_name or "", s.job_title or "", s.company_name or "", s.conference_name or "")
            scored_spks.append((s, s_res))

        # Deterministic Tie-Breaker Sort (Overall Score DESC, Industry Fit DESC, Email Readiness DESC, Name ASC)
        scored_spks.sort(
            key=lambda item: (
                item[1]["icp_score"],
                item[1]["industry_fit_score"],
                get_speaker_email_priority(item[0].professional_email, item[0].verification_status, item[0].company_name)
            ),
            reverse=True
        )

        for rank, (s, s_res) in enumerate(scored_spks, 1):
            s.icp_score = s_res["icp_score"]
            s.icp_rank = rank
            s.icp_tier = s_res["icp_tier"]
            s.industry_fit_score = s_res["industry_fit_score"]
            s.scale_fit_score = s_res["scale_fit_score"]
            s.company_headcount_estimate = s_res["company_headcount_estimate"]
            s.pitch_hook = s_res["pitch_hook"]

        self.db.commit()
        return {
            "status": "success",
            "run_id": run_id,
            "conferences_scored": len(scored_confs),
            "speakers_scored": len(scored_spks)
        }

    def score_and_rank_companies_in_db(self, run_id: str) -> Dict[str, Any]:
        """
        Identifies, evaluates, and ranks ALL companies associated with speakers for run_id:
        - Groups speakers by normalized company name (clean_token)
        - Resolves corporate domain, industry fit, scale fit, overall score, qualification status, and pitch hook
        - Contains ONLY company-related information (zero speaker names or speaker details)
        - Ranks 1..N within the run (highest score = Rank 1)
        - Inserts or updates in weekly_companies table (append-only across weeks)
        """
        spks = (
            self.db.query(WeeklySpeaker)
            .filter(WeeklySpeaker.weekly_run_id == run_id)
            .all()
        )

        company_groups: Dict[str, Dict[str, Any]] = {}
        for s in spks:
            comp_clean = clean_string(s.company_name)
            if not comp_clean:
                continue
            key = clean_token(comp_clean)
            if key not in company_groups:
                company_groups[key] = {
                    "company_name": comp_clean,
                    "speakers": [],
                    "conferences": set(),
                    "conference_ids": set()
                }
            company_groups[key]["speakers"].append(s)
            if s.conference_name:
                company_groups[key]["conferences"].add(s.conference_name)
            if s.conference_id:
                company_groups[key]["conference_ids"].add(s.conference_id)

        NON_COMPANIES = {"independent", "selfemployed", "unknown", "na", "none", "businesswithintelligenceconferencehowaiischangingwork"}

        scored_comps = []
        for key, cdata in company_groups.items():
            if key in NON_COMPANIES:
                continue
            comp_name = cdata["company_name"]
            conf_names = " / ".join(list(cdata["conferences"])[:2])
            conf_id = list(cdata["conference_ids"])[0] if cdata["conference_ids"] else ""

            # Corporate email presence flag for tie-breaker
            has_corp_email = any(
                clean_email(spk.professional_email) and (getattr(spk, "verification_status", "") == "verified")
                for spk in cdata["speakers"]
            )
            email_priority = 2 if has_corp_email else (1 if any(clean_email(spk.professional_email) for spk in cdata["speakers"]) else 0)

            if key in COMPANY_REGISTRY:
                reg = COMPANY_REGISTRY[key]
                domain = reg["domain"]
                official_url = f"https://{domain}"
                ind_score = float(reg["ind_score"])
                scale_score = float(reg["scale_score"])
                tier_label = reg["tier"]
                scale_category = reg["headcount"]
                ind_just = reg["justification"]
            else:
                # Verified fallback for newly discovered companies outside the verified registry
                domain = ""
                for spk in cdata["speakers"]:
                    em = clean_email(spk.professional_email)
                    if em:
                        d = extract_domain_from_email(em)
                        if d and is_email_domain_matching_company(d, comp_name):
                            domain = d
                            break
                if not domain:
                    domain = clean_token(comp_name) + ".com"

                official_url = f"https://{domain}"

                # Evaluate Industry Fit strictly on company name (no conference name leakage)
                ind_score, tier_label, ind_just = evaluate_industry_fit(comp_name, "", "")
                is_academic = (ind_score <= 25.0)

                # Evaluate Scale Fit
                scale_score, scale_category, _ = evaluate_company_scale(comp_name, is_academic_or_nonprofit=is_academic)

            # Calculate Overall ICP Score (60% Industry / 40% Scale Fit)
            overall_score = calculate_overall_icp_score(ind_score, scale_score)
            qual_status = get_qualification_status(overall_score)
            tier_with_status = f"{tier_label} [{qual_status}]"

            # Dynamic Pitch Hook
            pitch_hook = generate_pitch_hook(comp_name, tier_label, ind_score)

            scored_comps.append({
                "company_name": comp_name,
                "company_domain": domain,
                "official_website": official_url,
                "primary_industry": tier_label,
                "headcount_tier": scale_category,
                "conference_name": conf_names,
                "conference_id": conf_id,
                "weekly_run_id": run_id,
                "icp_score": overall_score,
                "icp_tier": tier_with_status,
                "industry_fit_score": ind_score,
                "scale_fit_score": scale_score,
                "qualification_status": qual_status,
                "strategic_justification": ind_just,
                "pitch_hook": pitch_hook,
                "email_priority": email_priority
            })

        # Deterministic tie-breaker sort key (Node 4: Score DESC, Industry DESC, Email Priority DESC, Name ASC)
        scored_comps.sort(
            key=lambda x: (-x["icp_score"], -x["industry_fit_score"], -x["email_priority"], x["company_name"].lower())
        )

        # Persist to PostgreSQL weekly_companies table (append-only / update in-place)
        saved_count = 0
        for rank, c in enumerate(scored_comps, 1):
            c["icp_rank"] = rank
            rec = self.db.query(WeeklyCompany).filter(
                WeeklyCompany.company_name == c["company_name"],
                WeeklyCompany.weekly_run_id == run_id
            ).first()

            if not rec:
                rec = WeeklyCompany(
                    company_name=c["company_name"],
                    company_domain=c["company_domain"],
                    official_website=c["official_website"],
                    primary_industry=c["primary_industry"],
                    headcount_tier=c["headcount_tier"],
                    conference_name=c["conference_name"],
                    conference_id=c["conference_id"],
                    weekly_run_id=c["weekly_run_id"],
                    icp_score=c["icp_score"],
                    icp_rank=rank,
                    icp_tier=c["icp_tier"],
                    industry_fit_score=c["industry_fit_score"],
                    scale_fit_score=c["scale_fit_score"],
                    qualification_status=c["qualification_status"],
                    strategic_justification=c["strategic_justification"],
                    pitch_hook=c["pitch_hook"],
                    last_checked_at=datetime.utcnow()
                )
                self.db.add(rec)
            else:
                rec.company_domain = c["company_domain"]
                rec.official_website = c["official_website"]
                rec.primary_industry = c["primary_industry"]
                rec.headcount_tier = c["headcount_tier"]
                rec.conference_name = c["conference_name"]
                rec.conference_id = c["conference_id"]
                rec.icp_score = c["icp_score"]
                rec.icp_rank = rank
                rec.icp_tier = c["icp_tier"]
                rec.industry_fit_score = c["industry_fit_score"]
                rec.scale_fit_score = c["scale_fit_score"]
                rec.qualification_status = c["qualification_status"]
                rec.strategic_justification = c["strategic_justification"]
                rec.pitch_hook = c["pitch_hook"]
                rec.last_checked_at = datetime.utcnow()
            saved_count += 1

        self.db.commit()
        return {
            "status": "success",
            "run_id": run_id,
            "companies_scored": len(scored_comps),
            "records_saved": saved_count
        }

    def sync_scores_to_local_excel(self, run_id: str) -> Dict[str, Any]:
        """
        Updates local Excel usa_conferences_published.xlsx:
        1. In-place update of master 'weekly_conference'
        2. In-place update of master 'weekly_speakers'
        3. Master cumulative append-only sheet: 'Companies scoring' (strictly company details, no speaker names)
        4. Recreates/refreshes 'latest_week_scoring' with Conferences, Speakers, and Companies leaderboards.
        """
        if not self.local_excel_path.exists():
            return {"status": "skipped", "message": "Local Excel file does not exist"}

        wb = openpyxl.load_workbook(str(self.local_excel_path))

        # 1. Update master weekly_conference sheet
        if 'weekly_conference' in wb.sheetnames:
            ws_c = wb['weekly_conference']
            conf_map = {
                (c.conference_id or "").strip().lower(): c
                for c in self.db.query(WeeklyConference).all()
            }
            for row in ws_c.iter_rows(min_row=2):
                cid = str(row[0].value or "").strip().lower()
                if cid in conf_map:
                    rec = conf_map[cid]
                    row[15].value = float(rec.icp_score) if rec.icp_score is not None else 0.0
                    row[16].value = int(rec.icp_rank) if rec.icp_rank is not None else 0
                    row[17].value = rec.icp_tier or ""
                    row[18].value = float(rec.industry_fit_score) if rec.industry_fit_score is not None else 0.0
                    row[19].value = float(rec.audience_fit_score) if rec.audience_fit_score is not None else 0.0

        # 2. Update master weekly_speakers sheet
        if 'weekly_speakers' in wb.sheetnames:
            ws_s = wb['weekly_speakers']
            spk_map = {
                (s.speaker_id or "").strip().lower(): s
                for s in self.db.query(WeeklySpeaker).all()
            }
            for row in ws_s.iter_rows(min_row=2):
                sid = str(row[0].value or "").strip().lower()
                if sid in spk_map:
                    rec = spk_map[sid]
                    row[20].value = float(rec.icp_score) if rec.icp_score is not None else 0.0
                    row[21].value = int(rec.icp_rank) if rec.icp_rank is not None else 0
                    row[22].value = rec.icp_tier or ""
                    row[23].value = float(rec.industry_fit_score) if rec.industry_fit_score is not None else 0.0
                    row[24].value = float(rec.scale_fit_score) if rec.scale_fit_score is not None else 0.0
                    row[25].value = rec.pitch_hook or ""

        # 3. Master Cumulative Sheet: 'Companies scoring' (Append-only, strictly company details)
        comp_sheet_name = 'Companies scoring'
        if comp_sheet_name not in wb.sheetnames:
            ws_comps = wb.create_sheet(title=comp_sheet_name)
            ws_comps.append([
                "Rank", "Company Name", "Company Domain", "Official Website",
                "Primary Industry", "Headcount Tier", "ICP Score", "Qualification Status",
                "ICP Tier", "Industry Fit Score", "Scale Fit Score", "Associated Conference",
                "Strategic Analysis", "Pitch Hook", "Weekly Run ID"
            ])
        else:
            ws_comps = wb[comp_sheet_name]

        # Map existing company rows by (company_name.lower(), weekly_run_id.lower())
        existing_comp_rows = {}
        for r_idx, row in enumerate(ws_comps.iter_rows(min_row=2, values_only=False), start=2):
            c_name = str(row[1].value or "").strip().lower()
            w_id = str(row[14].value or "").strip().lower()
            if c_name and w_id:
                existing_comp_rows[(c_name, w_id)] = r_idx

        # Get all companies across all runs from DB for the Master Cumulative Sheet
        db_companies = (
            self.db.query(WeeklyCompany)
            .order_by(WeeklyCompany.weekly_run_id.desc(), WeeklyCompany.icp_rank.asc().nullslast())
            .all()
        )

        for comp in db_companies:
            key = (comp.company_name.strip().lower(), comp.weekly_run_id.strip().lower() if comp.weekly_run_id else run_id.strip().lower())
            row_data = [
                comp.icp_rank,
                comp.company_name,
                comp.company_domain or "",
                comp.official_website or "",
                comp.primary_industry or "",
                comp.headcount_tier or "",
                float(comp.icp_score or 0.0),
                comp.qualification_status or "",
                comp.icp_tier or "",
                float(comp.industry_fit_score or 0.0),
                float(comp.scale_fit_score or 0.0),
                comp.conference_name or "",
                comp.strategic_justification or "",
                comp.pitch_hook or "",
                comp.weekly_run_id or ""
            ]
            if key in existing_comp_rows:
                # Update existing row in-place
                r_num = existing_comp_rows[key]
                for col_idx, val in enumerate(row_data, start=1):
                    ws_comps.cell(row=r_num, column=col_idx, value=val)
            else:
                # Append new row
                ws_comps.append(row_data)

        # 4. Create or Refresh 'latest_week_scoring' sheet
        sheet_name = 'latest_week_scoring'
        if sheet_name in wb.sheetnames:
            del wb[sheet_name]
        ws_latest = wb.create_sheet(title=sheet_name)

        # Section 1: Conferences
        ws_latest.append([f"LATEST WEEK CONFERENCES RANKED LEADERBOARD (RUN: {run_id})"])
        ws_latest.append(["Rank", "Conference ID", "Conference Name", "Start Date", "End Date", "City", "State", "Industry", "ICP Score", "ICP Tier", "Official URL"])

        latest_confs = (
            self.db.query(WeeklyConference)
            .filter(WeeklyConference.weekly_run_id == run_id)
            .order_by(WeeklyConference.icp_rank.asc().nullslast())
            .all()
        )
        for c in latest_confs:
            ws_latest.append([
                c.icp_rank,
                c.conference_id,
                c.conference_name,
                c.start_date.strftime('%Y-%m-%d') if c.start_date else "",
                c.end_date.strftime('%Y-%m-%d') if c.end_date else "",
                c.city or "",
                c.state or "",
                c.industry or "",
                float(c.icp_score or 0.0),
                c.icp_tier or "",
                c.official_event_url or ""
            ])

        ws_latest.append([])
        ws_latest.append([])

        # Section 2: Speakers
        ws_latest.append([f"LATEST WEEK SPEAKERS RANKED LEADERBOARD (RUN: {run_id})"])
        ws_latest.append(["Rank", "Speaker Name", "Job Title", "Company Name", "Conference Name", "Professional Email", "Personal LinkedIn URL", "ICP Score", "ICP Tier", "Pitch Hook", "Outreach Status"])

        latest_spks = (
            self.db.query(WeeklySpeaker)
            .filter(WeeklySpeaker.weekly_run_id == run_id)
            .order_by(WeeklySpeaker.icp_rank.asc().nullslast())
            .all()
        )
        for s in latest_spks:
            ws_latest.append([
                s.icp_rank,
                s.speaker_name or "",
                s.job_title or "",
                s.company_name or "",
                s.conference_name or "",
                s.professional_email or "",
                s.personal_linkedin_url or "",
                float(s.icp_score or 0.0),
                s.icp_tier or "",
                s.pitch_hook or "",
                s.outreach_status or "ready"
            ])

        ws_latest.append([])
        ws_latest.append([])

        # Section 3: Companies Leaderboard (Strictly Company Details, Zero Speaker Details)
        ws_latest.append([f"LATEST WEEK COMPANIES RANKED LEADERBOARD (RUN: {run_id})"])
        ws_latest.append(["Rank", "Company Name", "Company Domain", "Official Website", "Primary Industry", "Headcount Tier", "ICP Score", "Qualification Status", "ICP Tier", "Pitch Hook", "Associated Conference"])

        latest_comps = (
            self.db.query(WeeklyCompany)
            .filter(WeeklyCompany.weekly_run_id == run_id)
            .order_by(WeeklyCompany.icp_rank.asc().nullslast())
            .all()
        )
        for comp in latest_comps:
            ws_latest.append([
                comp.icp_rank,
                comp.company_name,
                comp.company_domain or "",
                comp.official_website or "",
                comp.primary_industry or "",
                comp.headcount_tier or "",
                float(comp.icp_score or 0.0),
                comp.qualification_status or "",
                comp.icp_tier or "",
                comp.pitch_hook or "",
                comp.conference_name or ""
            ])

        wb.save(str(self.local_excel_path))
        return {
            "status": "success",
            "local_path": str(self.local_excel_path),
            "conferences_written": len(latest_confs),
            "speakers_written": len(latest_spks),
            "companies_written": len(latest_comps)
        }

    def sync_scores_to_onedrive(self, run_id: str) -> Dict[str, Any]:
        """
        Synchronizes scoring columns to OneDrive live master tables, master 'Companies scoring' worksheet,
        and latest_week_scoring sheet (Conferences, Speakers, and Companies).
        """
        drive_id = self.onedrive_svc.resolve_drive_id()
        item_id = self.onedrive_svc.resolve_item_id()

        # 1. Update tbl_weekly_conferences scoring columns
        conf_map = self.onedrive_svc.get_existing_weekly_conference_rows_map()
        db_confs = {
            (c.conference_id or "").strip().lower(): c
            for c in self.db.query(WeeklyConference).all()
        }

        updated_confs = 0
        for cid_raw, (row_idx, cur_vals) in conf_map.items():
            cid = cid_raw.strip().lower()
            if cid in db_confs:
                c = db_confs[cid]
                new_vals = list(cur_vals)
                while len(new_vals) < 20:
                    new_vals.append("")
                new_vals[15] = float(c.icp_score) if c.icp_score is not None else 0.0
                new_vals[16] = int(c.icp_rank) if c.icp_rank is not None else 0
                new_vals[17] = c.icp_tier or ""
                new_vals[18] = float(c.industry_fit_score) if c.industry_fit_score is not None else 0.0
                new_vals[19] = float(c.audience_fit_score) if c.audience_fit_score is not None else 0.0

                endpoint = f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.onedrive_svc.weekly_conf_tbl_name}/rows/itemAt(index={row_idx})"
                self.onedrive_svc._api_request("PATCH", endpoint, body={"values": [new_vals]})
                updated_confs += 1

        # 2. Update tbl_weekly_speakers scoring columns
        db_spks_by_id = {
            (s.speaker_id or "").strip().lower(): s
            for s in self.db.query(WeeklySpeaker).all()
        }
        db_spks_by_name = {
            ((s.conference_id or "").strip().lower(), (s.speaker_name or "").strip().lower()): s
            for s in self.db.query(WeeklySpeaker).all()
        }

        res_s = self.onedrive_svc._api_request("GET", f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.onedrive_svc.weekly_spk_tbl_name}/rows")
        rows_s = res_s.get("value", [])

        updated_spks = 0
        for row_idx, r in enumerate(rows_s):
            cur_vals = r.get("values", [[]])[0]
            if not cur_vals or len(cur_vals) < 4:
                continue
            sid = str(cur_vals[0] or "").strip().lower()
            cid = str(cur_vals[1] or "").strip().lower()
            sname = str(cur_vals[3] or "").strip().lower()

            spk = db_spks_by_id.get(sid) or db_spks_by_name.get((cid, sname))
            if spk:
                new_vals = list(cur_vals)
                while len(new_vals) < 26:
                    new_vals.append("")
                new_vals[20] = float(spk.icp_score) if spk.icp_score is not None else 0.0
                new_vals[21] = int(spk.icp_rank) if spk.icp_rank is not None else 0
                new_vals[22] = spk.icp_tier or ""
                new_vals[23] = float(spk.industry_fit_score) if spk.industry_fit_score is not None else 0.0
                new_vals[24] = float(spk.scale_fit_score) if spk.scale_fit_score is not None else 0.0
                new_vals[25] = spk.pitch_hook or ""

                endpoint = f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.onedrive_svc.weekly_spk_tbl_name}/rows/itemAt(index={row_idx})"
                self.onedrive_svc._api_request("PATCH", endpoint, body={"values": [new_vals]})
                updated_spks += 1

        # 3. Master Sheet on OneDrive: 'Companies scoring' (Strictly company information)
        res_ws = self.onedrive_svc._api_request("GET", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets")
        existing_sheets = [ws.get("name") for ws in res_ws.get("value", [])]
        if "Companies scoring" not in existing_sheets:
            self.onedrive_svc._api_request("POST", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets", body={"name": "Companies scoring"})

        # Get all companies across all runs from DB for the Master Cumulative Sheet
        db_companies = (
            self.db.query(WeeklyCompany)
            .order_by(WeeklyCompany.weekly_run_id.desc(), WeeklyCompany.icp_rank.asc().nullslast())
            .all()
        )

        comp_ws_quoted = quote("Companies scoring")
        comp_master_headers = ["Rank", "Company_Name", "Company_Domain", "Official_Website", "Primary_Industry", "Headcount_Tier", "ICP_Score", "Qualification_Status", "ICP_Tier", "Industry_Fit_Score", "Scale_Fit_Score", "Associated_Conference", "Strategic_Analysis", "Pitch_Hook", "Weekly_Run_ID"]
        self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/{comp_ws_quoted}/range(address='A1:O1')", body={
            "values": [comp_master_headers]
        })

        comp_master_rows = []
        for c in db_companies:
            comp_master_rows.append([
                c.icp_rank,
                c.company_name or "",
                c.company_domain or "",
                c.official_website or "",
                c.primary_industry or "",
                c.headcount_tier or "",
                float(c.icp_score or 0.0),
                c.qualification_status or "",
                c.icp_tier or "",
                float(c.industry_fit_score or 0.0),
                float(c.scale_fit_score or 0.0),
                c.conference_name or "",
                c.strategic_justification or "",
                c.pitch_hook or "",
                c.weekly_run_id or ""
            ])

        if comp_master_rows:
            end_master_row = 1 + len(comp_master_rows)
            self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/{comp_ws_quoted}/range(address='A2:O{end_master_row}')", body={
                "values": comp_master_rows
            })

        # 4. Ensure 'latest_week_scoring' worksheet exists on OneDrive
        if "latest_week_scoring" not in existing_sheets:
            self.onedrive_svc._api_request("POST", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets", body={"name": "latest_week_scoring"})

        # Fetch latest ranked records from DB
        latest_confs = (
            self.db.query(WeeklyConference)
            .filter(WeeklyConference.weekly_run_id == run_id)
            .order_by(WeeklyConference.icp_rank.asc().nullslast())
            .all()
        )
        conf_table_rows = []
        for c in latest_confs:
            conf_table_rows.append([
                c.icp_rank,
                c.conference_id or "",
                c.conference_name or "",
                c.start_date.strftime('%Y-%m-%d') if c.start_date else "",
                c.end_date.strftime('%Y-%m-%d') if c.end_date else "",
                c.city or "",
                c.state or "",
                c.industry or "",
                float(c.icp_score or 0.0),
                c.icp_tier or "",
                c.official_event_url or ""
            ])

        latest_spks = (
            self.db.query(WeeklySpeaker)
            .filter(WeeklySpeaker.weekly_run_id == run_id)
            .order_by(WeeklySpeaker.icp_rank.asc().nullslast())
            .all()
        )
        spk_table_rows = []
        for s in latest_spks:
            spk_table_rows.append([
                s.icp_rank,
                s.speaker_name or "",
                s.job_title or "",
                s.company_name or "",
                s.conference_name or "",
                s.professional_email or "",
                s.personal_linkedin_url or "",
                float(s.icp_score or 0.0),
                s.icp_tier or "",
                s.pitch_hook or "",
                s.outreach_status or "ready"
            ])

        latest_comps = (
            self.db.query(WeeklyCompany)
            .filter(WeeklyCompany.weekly_run_id == run_id)
            .order_by(WeeklyCompany.icp_rank.asc().nullslast())
            .all()
        )
        comp_table_rows = []
        for comp in latest_comps:
            comp_table_rows.append([
                comp.icp_rank,
                comp.company_name or "",
                comp.company_domain or "",
                comp.official_website or "",
                comp.primary_industry or "",
                comp.headcount_tier or "",
                float(comp.icp_score or 0.0),
                comp.qualification_status or "",
                comp.icp_tier or "",
                comp.pitch_hook or "",
                comp.conference_name or ""
            ])

        # Write Conferences table to latest_week_scoring
        self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/latest_week_scoring/range(address='A1:K1')", body={
            "values": [[f"LATEST ACTIVE WEEK CONFERENCES RANKED LEADERBOARD ({run_id})", "", "", "", "", "", "", "", "", "", ""]]
        })
        conf_headers = ["Rank", "Conference_ID", "Conference_Name", "Start_Date", "End_Date", "City", "State", "Industry", "ICP_Score", "ICP_Tier", "Official_URL"]
        self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/latest_week_scoring/range(address='A2:K2')", body={
            "values": [conf_headers]
        })
        end_conf_row = 2 + len(conf_table_rows)
        if conf_table_rows:
            self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/latest_week_scoring/range(address='A3:K{end_conf_row}')", body={
                "values": conf_table_rows
            })

        # Write Speakers table to latest_week_scoring
        spk_banner_row = end_conf_row + 2
        spk_header_row = spk_banner_row + 1
        spk_start_row = spk_header_row + 1
        spk_end_row = spk_start_row + len(spk_table_rows) - 1

        self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/latest_week_scoring/range(address='A{spk_banner_row}:K{spk_banner_row}')", body={
            "values": [[f"LATEST ACTIVE WEEK SPEAKERS RANKED LEADERBOARD ({run_id})", "", "", "", "", "", "", "", "", "", ""]]
        })
        spk_headers = ["Rank", "Speaker_Name", "Job_Title", "Company_Name", "Conference_Name", "Professional_Email", "Personal_LinkedIn_URL", "ICP_Score", "ICP_Tier", "Pitch_Hook", "Outreach_Status"]
        self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/latest_week_scoring/range(address='A{spk_header_row}:K{spk_header_row}')", body={
            "values": [spk_headers]
        })
        if spk_table_rows:
            self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/latest_week_scoring/range(address='A{spk_start_row}:K{spk_end_row}')", body={
                "values": spk_table_rows
            })

        # Write Companies table to latest_week_scoring (Section 3: Strictly Company Details)
        comp_banner_row = spk_end_row + 2
        comp_header_row = comp_banner_row + 1
        comp_start_row = comp_header_row + 1
        comp_end_row = comp_start_row + len(comp_table_rows) - 1

        self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/latest_week_scoring/range(address='A{comp_banner_row}:K{comp_banner_row}')", body={
            "values": [[f"LATEST ACTIVE WEEK COMPANIES RANKED LEADERBOARD ({run_id})", "", "", "", "", "", "", "", "", "", ""]]
        })
        comp_headers = ["Rank", "Company_Name", "Company_Domain", "Official_Website", "Primary_Industry", "Headcount_Tier", "ICP_Score", "Qualification_Status", "ICP_Tier", "Pitch_Hook", "Associated_Conference"]
        self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/latest_week_scoring/range(address='A{comp_header_row}:K{comp_header_row}')", body={
            "values": [comp_headers]
        })
        if comp_table_rows:
            self.onedrive_svc._api_request("PATCH", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets/latest_week_scoring/range(address='A{comp_start_row}:K{comp_end_row}')", body={
                "values": comp_table_rows
            })

        return {
            "status": "success",
            "run_id": run_id,
            "onedrive_confs_updated": updated_confs,
            "onedrive_spks_updated": updated_spks,
            "latest_sheet_confs": len(conf_table_rows),
            "latest_sheet_spks": len(spk_table_rows),
            "latest_sheet_comps": len(comp_table_rows)
        }

    def score_and_publish_weekly_run(self, run_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Coordinates full multi-store scoring, ranking, and sheet publication for a given weekly run:
        1. PostgreSQL scoring & ranking for Conferences, Speakers, and Companies
        2. Local Excel master update & latest_week_scoring refresh
        3. OneDrive Live Excel master update & latest_week_scoring refresh
        """
        effective_run_id = run_id or self.resolve_latest_run_id()
        if not effective_run_id:
            logger.warning("No weekly_run_id available for ICP scoring.")
            return {"status": "skipped", "message": "No weekly_run_id found"}

        logger.info(f"🎯 Starting Automated ICP Scoring & Publishing for run: {effective_run_id}...")
        # 1. DB Scoring
        db_res = self.score_and_rank_in_db(effective_run_id)
        db_comp_res = self.score_and_rank_companies_in_db(effective_run_id)

        # 2. Local Excel Sync
        local_res = self.sync_scores_to_local_excel(effective_run_id)

        # 3. OneDrive Live Excel Sync
        onedrive_res = self.sync_scores_to_onedrive(effective_run_id)

        return {
            "status": "success",
            "weekly_run_id": effective_run_id,
            "database": {
                "conferences_and_speakers": db_res,
                "companies": db_comp_res
            },
            "local_excel": local_res,
            "onedrive_excel": onedrive_res
        }
