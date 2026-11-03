import logging
import re
import time
from typing import Dict, Any, Optional, Tuple
import requests

from ..config import settings

logger = logging.getLogger(__name__)


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


class ProspeoService:
    """
    Official Prospeo REST API Client:
    - B2B Email & LinkedIn Profile Enrichment Engine.
    - Resolves verified professional corporate emails from LinkedIn profile URLs or (Name + Company).
    - Performs real-time SMTP inbox deliverability verification (near-zero bounce rate < 2%).
    - Discovers verified personal LinkedIn URLs for speakers where missing.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "PROSPEO_API_KEY", "") or ""
        self.base_url = "https://api.prospeo.io"
        self.headers = {
            "Content-Type": "application/json",
            "X-KEY": self.api_key
        }
        self.last_call_time = 0.0
        self.min_interval = 3.0  # Safety rate limit spacing: max 1 req every 3.0 sec

    def _rate_limit_throttle(self):
        """Enforces minimum time interval between consecutive Prospeo API calls."""
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call_time = time.time()

    def get_account_info(self) -> Dict[str, Any]:
        """Queries Prospeo account information, plan status, and remaining credits."""
        if not self.api_key:
            return {"status": "error", "message": "PROSPEO_API_KEY is not configured."}
        try:
            self._rate_limit_throttle()
            url = f"{self.base_url}/account-information"
            resp = requests.get(url, headers={"X-KEY": self.api_key}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if not data.get("error"):
                    resp_data = data.get("response", {})
                    return {
                        "status": "success",
                        "current_plan": resp_data.get("current_plan"),
                        "remaining_credits": resp_data.get("remaining_credits"),
                        "used_credits": resp_data.get("used_credits"),
                        "renewal_date": resp_data.get("next_quota_renewal_date"),
                        "raw": resp_data
                    }
                return {"status": "error", "message": data.get("error_code", "API Error")}
            return {"status": "error", "code": resp.status_code, "message": resp.text[:200]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def enrich_person(
        self,
        name: str = "",
        company: str = "",
        linkedin_url: str = ""
    ) -> Dict[str, Any]:
        """
        Enriches a speaker using Prospeo /enrich-person:
        - If personal LinkedIn profile is available: matches via linkedin_url.
        - If LinkedIn profile is missing: matches via (first_name, last_name, company_name).
        - Returns verified professional email and discovered LinkedIn profile URL.
        """
        if not self.api_key:
            return {"status": "error", "message": "PROSPEO_API_KEY is not configured."}

        self._rate_limit_throttle()

        data_payload: Dict[str, Any] = {}
        valid_li = validate_personal_linkedin_url(linkedin_url)
        if valid_li:
            data_payload["linkedin_url"] = valid_li

        fname, lname = extract_first_and_last_name(name)
        if fname:
            data_payload["first_name"] = fname
        if lname:
            data_payload["last_name"] = lname
        if company:
            data_payload["company_name"] = company.strip()

        if not data_payload:
            return {"status": "error", "message": "Insufficient parameters for Prospeo enrichment."}

        payload = {
            "only_verified_email": False,
            "enrich_mobile": False,
            "data": data_payload
        }

        url = f"{self.base_url}/enrich-person"

        for attempt in range(1, 4):
            try:
                resp = requests.post(url, json=payload, headers=self.headers, timeout=20)
                status_code = resp.status_code

                if status_code == 200:
                    res_json = resp.json()
                    if not res_json.get("error"):
                        person = res_json.get("person") or {}
                        company_info = res_json.get("company") or {}

                        # Discovered LinkedIn URL
                        raw_li = person.get("linkedin_url") or ""
                        matched_li = validate_personal_linkedin_url(raw_li)

                        # Discovered Professional Email & Verification
                        raw_email_obj = person.get("email")
                        email_addr = ""
                        ver_status = "needs_review"

                        if isinstance(raw_email_obj, dict):
                            email_addr = (raw_email_obj.get("email") or "").strip().lower()
                            st = (raw_email_obj.get("status") or "").upper()
                            if st in ("VERIFIED", "VALID"):
                                ver_status = "verified"
                        elif isinstance(raw_email_obj, str) and "@" in raw_email_obj:
                            email_addr = raw_email_obj.strip().lower()
                            ver_status = "verified"

                        job_title = person.get("current_job_title") or ""
                        full_name = person.get("full_name") or f"{fname} {lname}".strip()

                        logger.info(
                            f"✅ Prospeo Enrichment Succeeded for '{full_name}': "
                            f"Email: {email_addr or 'N/A'} ({ver_status}), "
                            f"LinkedIn: {matched_li or 'N/A'}"
                        )

                        return {
                            "status": "success",
                            "email": email_addr,
                            "verification_status": ver_status,
                            "linkedin_url": matched_li,
                            "job_title": job_title,
                            "full_name": full_name,
                            "company_name": company_info.get("name") or company,
                            "raw": res_json
                        }

                    err_code = res_json.get("error_code", "UNKNOWN")
                    if err_code == "NO_MATCH":
                        return {"status": "not_found", "message": "Prospeo found no matching profile."}
                    return {"status": "error", "message": f"Prospeo error: {err_code}"}

                elif status_code == 400:
                    err_json = resp.json() if resp.text else {}
                    err_code = err_json.get("error_code", "")
                    if err_code == "NO_MATCH":
                        return {"status": "not_found", "message": "No match found in Prospeo."}
                    elif err_code == "INSUFFICIENT_CREDITS":
                        logger.warning("⚠️ Prospeo API: Insufficient credits remaining.")
                        return {"status": "quota_exceeded", "message": "Prospeo credits exhausted."}
                    return {"status": "error", "code": 400, "message": f"Prospeo 400: {err_code}"}

                elif status_code == 429:
                    logger.warning(f"Prospeo 429 Rate Limit. Backing off for {5 * attempt}s (Attempt {attempt}/3)...")
                    time.sleep(5 * attempt)
                    continue

                else:
                    return {"status": "error", "code": status_code, "message": resp.text[:200]}

            except requests.Timeout:
                logger.warning(f"Prospeo request timeout (Attempt {attempt}/3)")
                if attempt == 3:
                    return {"status": "error", "message": "Prospeo request timed out."}
                time.sleep(1)
            except Exception as e:
                logger.error(f"Prospeo enrichment exception for '{name}': {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "error", "message": "Prospeo enrichment failed after 3 attempts."}

