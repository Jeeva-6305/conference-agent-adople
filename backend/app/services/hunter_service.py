import logging
import re
import time
from typing import Dict, Any, Optional, List, Tuple
import requests

from ..config import settings

logger = logging.getLogger(__name__)


def clean_name_tokens(name: str) -> List[str]:
    """Extract clean lower-case alphanumeric tokens from a person's name."""
    if not name:
        return []
    n = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', name, flags=re.I).strip()
    n = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$', '', n, flags=re.I).strip()
    return [t.lower() for t in re.findall(r'[a-zA-Z]{2,}', n)]


def extract_first_and_last_name(name: str) -> Tuple[str, str]:
    """Split speaker full name into first and last name components."""
    if not name:
        return "", ""
    clean = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', name.strip(), flags=re.I).strip()
    clean = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$', '', clean, flags=re.I).strip()
    parts = clean.split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def extract_linkedin_handle(linkedin_url: Optional[str]) -> str:
    """Extracts username/handle from personal LinkedIn URL (e.g., /in/johndoe/ -> johndoe)."""
    if not linkedin_url:
        return ""
    m = re.search(r'linkedin\.com/in/([^/?#]+)', str(linkedin_url), re.I)
    return m.group(1).rstrip('/') if m else ""


def clean_company_name(company: str) -> str:
    """Normalize company name by stripping common corporate suffixes and parentheticals."""
    if not company:
        return ""
    c = re.sub(r'\(.*?\)', '', company).strip()
    c = re.sub(r'\b(llc|inc|corp|corporation|co|ltd|group|consulting|technologies|solutions)\b', '', c, flags=re.I).strip()
    c = re.sub(r'\s+', ' ', c).strip()
    return c


class HunterService:
    """
    Official Hunter.io REST API Client:
    - Dedicated strictly to Professional Email Discovery and Verification.
    - Email Finder API (GET /v2/email-finder): Discovers verified business email using speaker name + company/domain.
    - Email Verifier API (GET /v2/email-verifier): Confirms deliverability, SMTP validation, and confidence score.
    - Preserves verification status (valid, accept_all, invalid, etc.) and never fabricates emails.
    - Gracefully handles quota limits (credit exhaustion), HTTP 429, timeouts, and missing records.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "HUNTER_API_KEY", "") or ""
        self.base_url = getattr(settings, "HUNTER_BASE_URL", "https://api.hunter.io/v2").rstrip("/")
        self.last_call_time = 0.0
        self.min_interval = 0.2  # Safety rate limit spacing: max 5 req/sec

    def _rate_limit_throttle(self):
        """Enforces minimum time interval between consecutive Hunter API calls."""
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call_time = time.time()

    def get_account_info(self) -> Dict[str, Any]:
        """Queries Hunter.io account status and remaining request/search credits."""
        if not self.api_key:
            return {"status": "error", "message": "HUNTER_API_KEY is not configured."}
        try:
            self._rate_limit_throttle()
            url = f"{self.base_url}/account"
            resp = requests.get(url, params={"api_key": self.api_key}, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                reqs = data.get("requests", {})
                return {
                    "status": "success",
                    "plan_name": data.get("plan_name"),
                    "credits_remaining": reqs.get("credits", {}).get("remaining"),
                    "searches_remaining": reqs.get("searches", {}).get("remaining"),
                    "verifications_remaining": reqs.get("verifications", {}).get("remaining"),
                    "raw": data
                }
            return {"status": "error", "code": resp.status_code, "message": resp.text[:200]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def find_email(
        self,
        full_name: str = "",
        first_name: str = "",
        last_name: str = "",
        company: str = "",
        domain: str = "",
        linkedin_url: str = ""
    ) -> Dict[str, Any]:
        """
        Calls Hunter's official Email Finder API:
        GET https://api.hunter.io/v2/email-finder
        Finds the speaker's original professional email and verification status.
        """
        if not self.api_key:
            return {
                "status": "error",
                "message": "HUNTER_API_KEY is not configured in backend environment."
            }

        # Resolve first and last name
        if not first_name and not last_name and full_name:
            first_name, last_name = extract_first_and_last_name(full_name)

        if not first_name or not (last_name or full_name):
            return {
                "status": "error",
                "message": "Speaker first and last name are required for Hunter email finder."
            }

        clean_company = clean_company_name(company)
        if not domain and not clean_company:
            return {
                "status": "error",
                "message": "Company name or domain is required for Hunter email finder."
            }

        self._rate_limit_throttle()

        params: Dict[str, Any] = {
            "api_key": self.api_key,
            "first_name": first_name.strip(),
            "last_name": last_name.strip()
        }

        if domain:
            params["domain"] = domain.strip().lower()
        elif clean_company:
            params["company"] = clean_company

        # If LinkedIn profile is present, pass linkedin_handle
        handle = extract_linkedin_handle(linkedin_url)
        if handle:
            params["linkedin_handle"] = handle

        url = f"{self.base_url}/email-finder"

        for attempt in range(1, 4):
            try:
                resp = requests.get(url, params=params, timeout=20)
                status_code = resp.status_code

                # If 404 occurred because of linkedin_handle, retry immediately with name + company
                if status_code == 404 and "linkedin_handle" in params:
                    logger.info(f"Hunter handle lookup 404 for '{first_name} {last_name}'. Retrying with name and company '{clean_company}'...")
                    params.pop("linkedin_handle", None)
                    resp = requests.get(url, params=params, timeout=20)
                    status_code = resp.status_code

                if status_code == 200:
                    data = resp.json().get("data", {})
                    email = data.get("email")
                    if not email:
                        return {
                            "status": "not_found",
                            "message": f"Hunter.io did not find an email for '{first_name} {last_name}' at '{company}'."
                        }

                    score = data.get("score")
                    ver = data.get("verification") or {}
                    ver_status = ver.get("status") if isinstance(ver, dict) else None

                    # If Hunter says valid or accept_all
                    norm_ver_status = "verified" if ver_status == "valid" else (ver_status or "needs_review")

                    logger.info(
                        f"✅ Hunter.io Email Finder: Found '{email}' (score: {score}, status: {norm_ver_status}) "
                        f"for '{first_name} {last_name}' ({company})"
                    )

                    return {
                        "status": "success",
                        "email": email,
                        "score": score,
                        "verification_status": norm_ver_status,
                        "domain": data.get("domain") or "",
                        "company": data.get("company") or company,
                        "sources_count": len(data.get("sources", [])),
                        "raw": data
                    }

                elif status_code == 222:
                    # Hunter returns 222 when no email was found
                    return {
                        "status": "not_found",
                        "code": 222,
                        "message": f"No email found for '{first_name} {last_name}' at '{company}'."
                    }

                elif status_code == 401:
                    logger.error("❌ Hunter API 401: Unauthorized. Please check HUNTER_API_KEY.")
                    return {"status": "auth_error", "code": 401, "message": "Invalid Hunter.io API Key."}

                elif status_code in (403, 422):
                    err_json = resp.json() if resp.text else {}
                    err_msg = err_json.get("errors", [{}])[0].get("details", resp.text[:200]) if isinstance(err_json.get("errors"), list) and err_json.get("errors") else resp.text[:200]
                    if "quota" in str(err_msg).lower() or "credit" in str(err_msg).lower():
                        logger.warning(f"⚠️ Hunter.io Quota Exceeded: {err_msg}")
                        return {"status": "quota_exceeded", "code": status_code, "message": err_msg}
                    return {"status": "error", "code": status_code, "message": err_msg}

                elif status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2 * attempt))
                    logger.warning(f"Hunter.io API 429 Rate Limit. Sleeping {retry_after}s (Attempt {attempt}/3)...")
                    time.sleep(retry_after)
                    continue

                else:
                    return {
                        "status": "error",
                        "code": status_code,
                        "message": f"Hunter API HTTP {status_code}: {resp.text[:200]}"
                    }

            except requests.Timeout:
                logger.warning(f"Hunter API email-finder timeout for '{first_name} {last_name}' (Attempt {attempt}/3)")
                if attempt == 3:
                    return {"status": "error", "message": "Hunter.io request timed out after 3 attempts."}
                time.sleep(1)
            except Exception as e:
                logger.error(f"Hunter API email-finder exception for '{first_name} {last_name}': {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "error", "message": "Exceeded retry attempts on Hunter Email Finder."}

    def verify_email(self, email: str) -> Dict[str, Any]:
        """
        Calls Hunter's official Email Verifier API:
        GET https://api.hunter.io/v2/email-verifier
        Obtains deliverability verification status (valid, accept_all, invalid, disposable) and score.
        """
        if not self.api_key:
            return {"status": "error", "message": "HUNTER_API_KEY is not configured."}

        clean_email = (email or "").strip().lower()
        if not clean_email or "@" not in clean_email:
            return {"status": "error", "message": f"Invalid email format: '{clean_email}'"}

        self._rate_limit_throttle()

        params = {
            "api_key": self.api_key,
            "email": clean_email
        }
        url = f"{self.base_url}/email-verifier"

        try:
            resp = requests.get(url, params=params, timeout=20)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                raw_status = data.get("status")  # 'valid', 'accept_all', 'invalid', 'disposable', 'webmail'
                score = data.get("score")
                norm_status = "verified" if raw_status == "valid" else (raw_status or "needs_review")
                logger.info(f"✅ Hunter.io Email Verifier: '{clean_email}' -> {norm_status} (score: {score})")
                return {
                    "status": "success",
                    "email": clean_email,
                    "verification_status": norm_status,
                    "score": score,
                    "deliverable": raw_status == "valid",
                    "raw": data
                }
            return {
                "status": "error",
                "code": resp.status_code,
                "message": f"Hunter Verifier HTTP {resp.status_code}: {resp.text[:200]}"
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

