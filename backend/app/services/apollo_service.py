import logging
import re
import time
import urllib.parse
from typing import Dict, Any, Optional, List, Tuple
import requests

from ..config import settings

logger = logging.getLogger(__name__)


def clean_name_tokens(name: str) -> List[str]:
    """Extract clean lower-case alphanumeric tokens from a person's name."""
    if not name:
        return []
    # Strip honorifics and suffixes
    n = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', name, flags=re.I).strip()
    n = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$', '', n, flags=re.I).strip()
    tokens = [t.lower() for t in re.findall(r'[a-zA-Z]{2,}', n)]
    return tokens


def clean_company_name(company: str) -> str:
    """Normalize company name by stripping common corporate entity suffixes."""
    if not company:
        return ""
    c = re.sub(r'\(.*?\)', '', company).strip()
    c = re.sub(r'\b(llc|inc|corp|corporation|co|ltd|group|consulting|technologies|solutions)\b', '', c, flags=re.I).strip()
    c = re.sub(r'\s+', ' ', c).strip()
    return c


def is_name_match(source_name: str, candidate_name: str) -> bool:
    """Check whether candidate name sufficiently matches the target speaker name."""
    s_tokens = clean_name_tokens(source_name)
    c_tokens = clean_name_tokens(candidate_name)
    if not s_tokens or not c_tokens:
        return False

    # Exact token match or first + last match
    if s_tokens == c_tokens:
        return True
    if len(s_tokens) >= 2 and len(c_tokens) >= 2:
        # Check first and last name match
        if s_tokens[0] == c_tokens[0] and s_tokens[-1] == c_tokens[-1]:
            return True

    # Token overlap check
    overlap = set(s_tokens).intersection(set(c_tokens))
    if len(overlap) >= min(len(s_tokens), len(c_tokens)) and len(overlap) >= 2:
        return True

    return False


def is_company_match(source_company: str, candidate_company: str) -> bool:
    """Check whether candidate company matches the source company."""
    if not source_company or not candidate_company:
        return True  # If one is blank, cannot falsify
    s_comp = clean_company_name(source_company).lower()
    c_comp = clean_company_name(candidate_company).lower()

    if not s_comp or not c_comp:
        return True

    if s_comp in c_comp or c_comp in s_comp:
        return True

    s_words = set(re.findall(r'[a-zA-Z]{3,}', s_comp))
    c_words = set(re.findall(r'[a-zA-Z]{3,}', c_comp))
    if s_words and c_words and len(s_words.intersection(c_words)) > 0:
        return True

    return False


class ApolloService:
    """
    Official Apollo.io REST API Client:
    - People Match endpoint (POST /api/v1/people/match) for professional email & profile enrichment.
    - People Search endpoint (POST /api/v1/mixed_people/search) for missing LinkedIn profile discovery.
    - Identity verification between target speaker details and Apollo returned data.
    - Graceful handling of API credit exhaustion, rate limits, plan restrictions (e.g. Free plan), and timeouts.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "APOLLO_API_KEY", "") or ""
        self.base_url = "https://api.apollo.io/api/v1"
        self.headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key
        }
        self.last_call_time = 0.0
        self.min_interval = 0.25  # Rate-limit safety spacing: max 4 req/sec

    def _rate_limit_throttle(self):
        """Enforces minimum time interval between consecutive Apollo API calls."""
        elapsed = time.time() - self.last_call_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_call_time = time.time()

    def match_person(
        self,
        name: str,
        company: str = "",
        job_title: str = "",
        linkedin_url: str = "",
        domain: str = ""
    ) -> Dict[str, Any]:
        """
        Calls Apollo's official People Match endpoint:
        POST https://api.apollo.io/api/v1/people/match
        Finds the speaker's original professional email and verified profile attributes.
        """
        if not self.api_key:
            return {
                "status": "error",
                "message": "APOLLO_API_KEY is not configured in backend environment."
            }

        self._rate_limit_throttle()

        name_parts = name.strip().split()
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        payload: Dict[str, Any] = {
            "name": name.strip(),
            "first_name": first_name,
            "last_name": last_name,
            "reveal_personal_emails": False
        }

        if company:
            payload["organization_name"] = company.strip()
        if job_title:
            payload["title"] = job_title.strip()
        if linkedin_url and "linkedin.com" in linkedin_url.lower():
            payload["linkedin_url"] = linkedin_url.strip()
        if domain:
            payload["domain"] = domain.strip()

        url = f"{self.base_url}/people/match"

        for attempt in range(1, 4):
            try:
                resp = requests.post(url, json=payload, headers=self.headers, timeout=15)
                status_code = resp.status_code

                if status_code == 200:
                    data = resp.json()
                    person = data.get("person")
                    if not person:
                        return {
                            "status": "not_found",
                            "message": "Person match returned no profile record in Apollo."
                        }

                    # Validate identity before accepting
                    ret_name = person.get("name") or f"{person.get('first_name', '')} {person.get('last_name', '')}".strip()
                    ret_org = person.get("organization", {}).get("name") if isinstance(person.get("organization"), dict) else ""

                    if not is_name_match(name, ret_name):
                        logger.warning(
                            f"Apollo Match Identity Mismatch: Requested '{name}', but Apollo returned '{ret_name}'. Rejecting match."
                        )
                        return {
                            "status": "needs_review",
                            "message": f"Identity mismatch: returned name '{ret_name}' does not match speaker '{name}'."
                        }

                    email = person.get("email") or ""
                    email_status = person.get("email_status") or "verified" if email else "unavailable"
                    ret_li = person.get("linkedin_url") or ""

                    logger.info(f"✅ Apollo People Match: Verified '{name}' ({company}) -> Email: '{email}', Status: '{email_status}'")
                    return {
                        "status": "success",
                        "email": email,
                        "email_status": email_status,
                        "linkedin_url": ret_li,
                        "organization_name": ret_org,
                        "title": person.get("title") or "",
                        "raw_person": person
                    }

                elif status_code == 403:
                    err_json = resp.json() if resp.text else {}
                    err_msg = err_json.get("error", "Access Denied")
                    logger.warning(f"⚠️ Apollo API 403: {err_msg}")
                    return {
                        "status": "api_restricted",
                        "code": 403,
                        "message": err_msg
                    }

                elif status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", 2 * attempt))
                    logger.warning(f"Apollo API Rate Limit (429). Backing off for {retry_after}s (Attempt {attempt}/3)...")
                    time.sleep(retry_after)
                    continue

                elif status_code == 404:
                    return {
                        "status": "not_found",
                        "code": 404,
                        "message": "Speaker profile not found in Apollo database."
                    }

                else:
                    logger.warning(f"Apollo API HTTP {status_code}: {resp.text[:200]}")
                    return {
                        "status": "error",
                        "code": status_code,
                        "message": f"Apollo API HTTP {status_code}: {resp.text[:200]}"
                    }

            except requests.Timeout:
                logger.warning(f"Apollo API match timeout on '{name}' (Attempt {attempt}/3)")
                if attempt == 3:
                    return {"status": "error", "message": "Apollo API request timed out."}
                time.sleep(1)
            except Exception as e:
                logger.error(f"Apollo API match exception for '{name}': {e}")
                return {"status": "error", "message": str(e)}

        return {"status": "error", "message": "Exceeded retry attempts on Apollo People Match."}

    def search_people(
        self,
        name: str,
        company: str = "",
        job_title: str = ""
    ) -> Dict[str, Any]:
        """
        Calls Apollo's People Search endpoint:
        POST https://api.apollo.io/api/v1/mixed_people/search
        Discovers potential profiles for speakers who are missing LinkedIn URLs.
        """
        if not self.api_key:
            return {"status": "error", "message": "APOLLO_API_KEY is not configured."}

        self._rate_limit_throttle()

        payload: Dict[str, Any] = {
            "q_person_name": name.strip(),
            "page": 1,
            "per_page": 5
        }
        if company:
            payload["q_organization_name"] = company.strip()
        if job_title and job_title.lower() not in ["speaker", "keynote speaker"]:
            payload["person_titles"] = [job_title.strip()]

        url = f"{self.base_url}/mixed_people/search"

        try:
            resp = requests.post(url, json=payload, headers=self.headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                people = data.get("people", [])
                if not people:
                    return {"status": "not_found", "candidates": []}

                matched_candidates = []
                for p in people:
                    c_name = p.get("name") or f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
                    c_org = p.get("organization", {}).get("name") if isinstance(p.get("organization"), dict) else ""
                    c_li = p.get("linkedin_url") or ""

                    if is_name_match(name, c_name) and is_company_match(company, c_org):
                        matched_candidates.append({
                            "name": c_name,
                            "company": c_org,
                            "job_title": p.get("title") or "",
                            "linkedin_url": c_li,
                            "email": p.get("email") or "",
                            "email_status": p.get("email_status") or ""
                        })

                if len(matched_candidates) == 1 and matched_candidates[0]["linkedin_url"]:
                    cand = matched_candidates[0]
                    return {
                        "status": "success",
                        "linkedin_url": cand["linkedin_url"],
                        "email": cand["email"],
                        "email_status": cand["email_status"],
                        "candidate": cand
                    }
                elif len(matched_candidates) > 1:
                    return {
                        "status": "needs_review",
                        "message": f"Multiple ambiguous profiles found in Apollo ({len(matched_candidates)} matches).",
                        "candidates": matched_candidates
                    }
                else:
                    return {
                        "status": "not_found",
                        "message": "No candidates in Apollo passed identity verification."
                    }

            elif resp.status_code == 403:
                err_json = resp.json() if resp.text else {}
                err_msg = err_json.get("error", "Access Denied")
                return {"status": "api_restricted", "code": 403, "message": err_msg}

            else:
                return {"status": "error", "code": resp.status_code, "message": resp.text[:200]}

        except Exception as e:
            return {"status": "error", "message": str(e)}

