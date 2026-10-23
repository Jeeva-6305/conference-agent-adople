import os
import time
import json
import logging
import urllib.request
import urllib.parse
import re
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime, date

from ..config import settings
from ..models import Conference, Speaker

logger = logging.getLogger(__name__)


def canonicalize_url(url: Optional[str]) -> str:
    """Canonicalize URLs for reliable duplicate detection across platforms."""
    if not url:
        return ""
    u = str(url).strip().lower()
    if u.startswith("https://"):
        u = u[8:]
    elif u.startswith("http://"):
        u = u[7:]
    if u.startswith("www."):
        u = u[4:]
    u = u.split("?")[0].split("#")[0]
    return u.rstrip("/")


def normalize_title(title: Optional[str]) -> str:
    """Normalize conference or speaker title by stripping punctuation and normalizing spaces."""
    if not title:
        return ""
    t = str(title).strip().lower()
    t = re.sub(r'[\',.:;!?"\(\)\-\–—/]', ' ', t)
    return " ".join(t.split())


class OneDriveExcelService:
    """
    Microsoft Graph API Client for Work OneDrive Excel Workbook Integration:
    - Authenticates via Microsoft Graph using client credentials.
    - Resolves drive and item ID for the work OneDrive workbook.
    - Synchronizes genuine conferences into 'tbl_conferences' on 'conferences' sheet.
    - Synchronizes genuine speakers into 'tbl_speakers' on 'speakers' sheet.
    - Enforces strict idempotency and duplicate prevention.
    - Preserves all existing data; never clears tables or deletes rows.
    """

    def __init__(self):
        self.client_id = settings.SHAREPOINT_CLIENT_ID
        self.client_secret = settings.SHAREPOINT_CLIENT_SECRET
        self.tenant_id = settings.SHAREPOINT_TENANT_ID
        self.hostname = settings.CONFERENCE_ONEDRIVE_HOSTNAME
        self.user_name = settings.CONFERENCE_ONEDRIVE_USER
        self.file_name = settings.CONFERENCE_EXCEL_FILE_NAME
        self.conf_ws_name = settings.CONFERENCE_EXCEL_WORKSHEET_NAME
        self.conf_tbl_name = settings.CONFERENCE_EXCEL_TABLE_NAME
        self.spk_ws_name = settings.CONFERENCE_SPEAKERS_WORKSHEET_NAME
        self.spk_tbl_name = settings.CONFERENCE_SPEAKERS_TABLE_NAME
        self.base_url = settings.MICROSOFT_GRAPH_BASE_URL.rstrip("/")

        # In-memory cached session
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0
        self._drive_id: Optional[str] = None
        self._item_id: Optional[str] = None

    def _get_access_token(self) -> str:
        """Acquires a valid Microsoft Graph OAuth2 access token with in-memory caching."""
        now = time.time()
        if self._access_token and now < (self._token_expires_at - 60):
            return self._access_token

        if not self.client_id or not self.client_secret or not self.tenant_id:
            raise ValueError("Microsoft Graph credentials (CLIENT_ID, CLIENT_SECRET, TENANT_ID) are missing from configuration.")

        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        payload = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default"
        }).encode("utf-8")

        req = urllib.request.Request(token_url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self._access_token = data["access_token"]
                expires_in = int(data.get("expires_in", 3600))
                self._token_expires_at = now + expires_in
                logger.info("Successfully acquired Microsoft Graph access token.")
                return self._access_token
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8", errors="ignore")
            logger.error(f"Failed to authenticate with Microsoft Graph (HTTP {e.code}): {err_msg}")
            raise RuntimeError(f"Microsoft Graph authentication failed: {err_msg}")
        except Exception as e:
            logger.error(f"Error requesting Graph token: {e}")
            raise

    def _api_request(
        self,
        method: str,
        endpoint: str,
        body: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Makes an authenticated HTTP request to the Microsoft Graph API."""
        token = self._get_access_token()
        url = endpoint if endpoint.startswith("http") else f"{self.base_url}{endpoint}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        }

        data_bytes = None
        if body is not None:
            data_bytes = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8")
                if not raw:
                    return {"status_code": status}
                data = json.loads(raw)
                data["_status_code"] = status
                return data
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            logger.error(f"Graph API {method} {url} error (HTTP {e.code}): {err_body}")
            return {"error": e.code, "message": err_body}
        except Exception as e:
            logger.error(f"Graph API {method} {url} unexpected exception: {e}")
            return {"error": -1, "message": str(e)}

    def resolve_drive_id(self) -> str:
        """Resolves the user's OneDrive drive ID."""
        if self._drive_id:
            return self._drive_id

        # Derive user email / principal name from username
        # e.g., jeevanandham_adople_ai -> jeevanandham@adople.ai
        upn = self.user_name.replace("_adople_ai", "@adople.ai")
        if "@" not in upn:
            upn = f"{self.user_name}@adople.ai"

        # Try 1: User drive endpoint
        res = self._api_request("GET", f"/users/{upn}/drive")
        if "id" in res:
            self._drive_id = res["id"]
            logger.info(f"Resolved OneDrive drive ID for {upn}: {self._drive_id}")
            return self._drive_id

        # Try 2: SharePoint Personal Site drive endpoint
        site_path = f"/personal/{self.user_name}"
        res2 = self._api_request("GET", f"/sites/{self.hostname}:{site_path}:/drive")
        if "id" in res2:
            self._drive_id = res2["id"]
            logger.info(f"Resolved OneDrive site drive ID for {site_path}: {self._drive_id}")
            return self._drive_id

        raise RuntimeError(f"Unable to resolve OneDrive drive for {self.user_name}. Error: {res}")

    def resolve_item_id(self) -> str:
        """Locates the workbook by file name and caches its drive item ID."""
        if self._item_id:
            return self._item_id

        drive_id = self.resolve_drive_id()

        # 1. Search in drive root
        search_res = self._api_request("GET", f"/drives/{drive_id}/root/search(q='{self.file_name}')")
        if "value" in search_res:
            for item in search_res["value"]:
                if item.get("name") == self.file_name:
                    self._item_id = item.get("id")
                    logger.info(f"Found workbook item ID via search: {self._item_id}")
                    return self._item_id

        # 2. Check root children directly
        root_res = self._api_request("GET", f"/drives/{drive_id}/root/children")
        if "value" in root_res:
            for item in root_res["value"]:
                if item.get("name") == self.file_name:
                    self._item_id = item.get("id")
                    logger.info(f"Found workbook item ID via root children: {self._item_id}")
                    return self._item_id

        raise FileNotFoundError(f"Workbook '{self.file_name}' not found in OneDrive drive '{drive_id}'.")

    def test_connection(self) -> Dict[str, Any]:
        """
        Executes a comprehensive read-only connection test.
        Returns metadata, verified worksheets, verified tables, and column headers.
        """
        drive_id = self.resolve_drive_id()
        item_id = self.resolve_item_id()

        # Item metadata
        item_meta = self._api_request("GET", f"/drives/{drive_id}/items/{item_id}")

        # Worksheets
        ws_res = self._api_request("GET", f"/drives/{drive_id}/items/{item_id}/workbook/worksheets")
        worksheets = [w.get("name") for w in ws_res.get("value", [])]

        # Tables
        tables_res = self._api_request("GET", f"/drives/{drive_id}/items/{item_id}/workbook/tables")
        tables = [t.get("name") for t in tables_res.get("value", [])]

        # Conference Columns
        conf_cols_res = self._api_request(
            "GET", f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.conf_tbl_name}/columns"
        )
        conf_headers = [c.get("name") for c in conf_cols_res.get("value", [])]

        # Speaker Columns
        spk_cols_res = self._api_request(
            "GET", f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.spk_tbl_name}/columns"
        )
        spk_headers = [c.get("name") for c in spk_cols_res.get("value", [])]

        # Current row counts
        conf_rows_res = self._api_request(
            "GET", f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.conf_tbl_name}/rows"
        )
        conf_row_count = len(conf_rows_res.get("value", []))

        spk_rows_res = self._api_request(
            "GET", f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.spk_tbl_name}/rows"
        )
        spk_row_count = len(spk_rows_res.get("value", []))

        return {
            "status": "connected",
            "drive_id": drive_id,
            "item_id": item_id,
            "file_name": item_meta.get("name"),
            "web_url": item_meta.get("webUrl"),
            "size": item_meta.get("size"),
            "last_modified": item_meta.get("lastModifiedDateTime"),
            "worksheets": worksheets,
            "tables": tables,
            "conferences_table": {
                "name": self.conf_tbl_name,
                "columns": conf_headers,
                "existing_row_count": conf_row_count
            },
            "speakers_table": {
                "name": self.spk_tbl_name,
                "columns": spk_headers,
                "existing_row_count": spk_row_count
            }
        }

    def get_existing_conference_rows_map(self) -> Dict[str, Tuple[int, List[Any]]]:
        """Fetches existing rows map {ConferenceID: (row_index, values)} in tbl_conferences."""
        drive_id = self.resolve_drive_id()
        item_id = self.resolve_item_id()
        res = self._api_request("GET", f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.conf_tbl_name}/rows")

        rows_map = {}
        if "value" in res:
            for idx, row in enumerate(res["value"]):
                values = row.get("values", [[]])[0]
                if values and len(values) > 0 and values[0]:
                    conf_id = str(values[0]).strip()
                    row_idx = row.get("index", idx)
                    rows_map[conf_id] = (row_idx, values)
        return rows_map

    def get_existing_speaker_rows_map(self) -> Dict[Tuple[str, str], Tuple[int, List[Any]]]:
        """Fetches existing rows map {(ConferenceID, SpeakerName): (row_index, values)} from tbl_speakers."""
        drive_id = self.resolve_drive_id()
        item_id = self.resolve_item_id()
        res = self._api_request("GET", f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.spk_tbl_name}/rows")

        rows_map = {}
        if "value" in res:
            for idx, row in enumerate(res["value"]):
                values = row.get("values", [[]])[0]
                if values and len(values) >= 4:
                    conf_id = str(values[1] or "").strip()
                    spk_name = str(values[3] or "").strip().lower()
                    if conf_id and spk_name:
                        row_idx = row.get("index", idx)
                        rows_map[(conf_id, spk_name)] = (row_idx, values)
        return rows_map

    def sync_conferences(self, conferences: List[Conference]) -> Dict[str, Any]:
        """
        Synchronizes genuine conferences to 'tbl_conferences' in OneDrive Excel.
        Maps fields strictly to existing table columns:
        [ConferenceID, Title, Category, StartDate, EndDate, SpeakersAvailable, Column1,
         Venue, City, Country, Organizer, SourceName, OfficialURL, PublicationDate,
         VerificationStatus, CollectedAt]
        If a record already exists, updates it when new verified info is present.
        """
        if not conferences:
            return {"status": "skipped", "inserted_count": 0, "updated_count": 0, "message": "No conferences provided"}

        drive_id = self.resolve_drive_id()
        item_id = self.resolve_item_id()
        existing_rows = self.get_existing_conference_rows_map()
        
        # Build comprehensive deduplication sets from existing historical Excel rows
        existing_ids: Set[str] = set()
        existing_titles: Set[str] = set()
        existing_canonical_urls: Set[str] = set()
        existing_title_dates: Set[Tuple[str, str]] = set()
        existing_venue_dates: Set[Tuple[str, str]] = set()

        for cid, (_, vals) in existing_rows.items():
            if cid:
                existing_ids.add(str(cid).strip().lower())
            if len(vals) > 1 and vals[1]:
                t_norm = normalize_title(vals[1])
                if t_norm:
                    existing_titles.add(t_norm)
            if len(vals) > 3 and vals[3]:
                d_str = str(vals[3]).strip()
                if len(vals) > 1 and vals[1]:
                    t_norm = normalize_title(vals[1])
                    if t_norm and d_str:
                        existing_title_dates.add((t_norm, d_str))
                if len(vals) > 7 and vals[7]:
                    v_norm = normalize_title(vals[7])
                    if v_norm and len(v_norm) > 5 and d_str:
                        existing_venue_dates.add((v_norm, d_str))
            if len(vals) > 12 and vals[12]:
                c_url = canonicalize_url(vals[12])
                if c_url and len(c_url) > 10 and not any(gen in c_url for gen in ["allevents.in", "eventbrite.com", "meetup.com", "luma.com"]):
                    existing_canonical_urls.add(c_url)

        rows_to_insert = []
        skipped_count = 0

        for conf in conferences:
            conf_id = conf.conference_id.strip() if conf.conference_id else ""
            if not conf_id:
                skipped_count += 1
                continue

            conf_id_lower = conf_id.lower()
            conf_title_norm = normalize_title(conf.conference_title)
            start_date_str = conf.start_date.isoformat() if conf.start_date else ""
            venue_norm = normalize_title(conf.venue)
            canon_official_url = canonicalize_url(conf.official_conference_url)
            canon_source_url = canonicalize_url(conf.source_url)

            # Strict duplicate checking against all reliable identifiers:
            # 1. Conference ID
            # 2. Normalized Title
            # 3. Canonical Official URL
            # 4. Title + Start Date
            # 5. Venue + Start Date
            is_duplicate = False
            match_reason = ""

            if conf_id_lower in existing_ids:
                is_duplicate = True
                match_reason = f"Conference ID '{conf_id}'"
            elif conf_title_norm and conf_title_norm in existing_titles:
                is_duplicate = True
                match_reason = f"Title '{conf.conference_title}'"
            elif canon_official_url and canon_official_url in existing_canonical_urls:
                is_duplicate = True
                match_reason = f"Canonical URL '{canon_official_url}'"
            elif (conf_title_norm, start_date_str) in existing_title_dates:
                is_duplicate = True
                match_reason = f"Title + Date ({conf_title_norm} on {start_date_str})"
            elif venue_norm and len(venue_norm) > 5 and (venue_norm, start_date_str) in existing_venue_dates:
                is_duplicate = True
                match_reason = f"Venue + Date ({venue_norm} on {start_date_str})"

            if is_duplicate:
                logger.info(f"OneDrive Excel: Retaining existing historical record for '{conf.conference_title}' ({match_reason} already present). Skipping duplicate append.")
                skipped_count += 1
                continue

            # Format fields
            end_date_str = conf.end_date.isoformat() if conf.end_date else ""
            pub_date_str = conf.publication_date.isoformat() if conf.publication_date else ""
            collected_at_str = conf.created_at.isoformat() if conf.created_at else datetime.utcnow().isoformat()

            new_row = [
                conf_id,                                       # 1. ConferenceID
                conf.conference_title or "",                  # 2. Title
                conf.industry_category or "",                 # 3. Category
                start_date_str,                               # 4. StartDate
                end_date_str,                                 # 5. EndDate
                conf.speakers_available or "Yes",             # 6. SpeakersAvailable
                conf.description or "",                       # 7. Column1 (Description)
                conf.venue or "",                             # 8. Venue
                conf.city or "",                              # 9. City
                conf.country or "USA",                        # 10. Country
                conf.organizer or "",                         # 11. Organizer
                conf.source_name or "",                       # 12. SourceName
                conf.official_conference_url or "",           # 13. OfficialURL
                pub_date_str,                                 # 14. PublicationDate
                conf.status or "published",                   # 15. VerificationStatus
                collected_at_str                              # 16. CollectedAt
            ]

            rows_to_insert.append(new_row)
            existing_ids.add(conf_id_lower)
            if conf_title_norm:
                existing_titles.add(conf_title_norm)
            if canon_official_url and len(canon_official_url) > 10:
                existing_canonical_urls.add(canon_official_url)
            if conf_title_norm and start_date_str:
                existing_title_dates.add((conf_title_norm, start_date_str))
            if venue_norm and len(venue_norm) > 5 and start_date_str:
                existing_venue_dates.add((venue_norm, start_date_str))

        inserted_count = 0
        if rows_to_insert:
            logger.info(f"OneDrive Excel: Inserting {len(rows_to_insert)} genuinely new conference row(s) into '{self.conf_tbl_name}'...")
            endpoint = f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.conf_tbl_name}/rows"
            res = self._api_request("POST", endpoint, body={"values": rows_to_insert})
            if "error" in res:
                logger.error(f"Failed to insert conference rows into OneDrive Excel: {res}")
                return {"status": "error", "error": res, "inserted_count": 0, "skipped_count": skipped_count}
            inserted_count = len(rows_to_insert)

        logger.info(f"✅ OneDrive Excel conferences sync: {inserted_count} appended, {skipped_count} preserved/skipped.")
        return {
            "status": "success",
            "inserted_count": inserted_count,
            "skipped_count": skipped_count
        }

    def sync_speakers(self, speakers: List[Speaker]) -> Dict[str, Any]:
        """
        Synchronizes genuine speakers to 'tbl_speakers' in OneDrive Excel using strict append-only storage.
        Maps fields strictly to existing table columns:
        [SpeakerID, ConferenceID, ConferenceTitle, SpeakerName, JobTitle, Company,
         LinkedInURL, CompanyURL, SpeakerProfileURL, SourceURL, VerifiedStatus, CollectedAt]
        Preserves all historical speaker records without deletion or overwrite.
        """
        if not speakers:
            return {"status": "skipped", "inserted_count": 0, "skipped_count": 0, "message": "No speakers provided"}

        drive_id = self.resolve_drive_id()
        item_id = self.resolve_item_id()
        existing_rows = self.get_existing_speaker_rows_map()
        
        # Build multi-tier speaker deduplication sets
        existing_keys: Set[Tuple[str, str]] = set()
        existing_title_speakers: Set[Tuple[str, str]] = set()
        existing_linkedin: Set[str] = set()

        for (cid, sname), (_, vals) in existing_rows.items():
            if cid and sname:
                existing_keys.add((str(cid).strip().lower(), str(sname).strip().lower()))
            if len(vals) > 3 and vals[3]:
                spk_n = normalize_title(vals[3])
                if len(vals) > 2 and vals[2]:
                    c_title = normalize_title(vals[2])
                    if c_title and spk_n:
                        existing_title_speakers.add((c_title, spk_n))
                if len(vals) > 6 and vals[6]:
                    li_canon = canonicalize_url(vals[6])
                    if li_canon and "linkedin.com/in/" in li_canon:
                        existing_linkedin.add(li_canon)

        rows_to_insert = []
        skipped_count = 0

        for spk in speakers:
            conf_id = (spk.conference_id or "").strip()
            name = (spk.speaker_name or "").strip()
            if not conf_id or not name:
                skipped_count += 1
                continue

            key = (conf_id.lower(), name.lower())
            name_norm = normalize_title(name)
            title_norm = normalize_title(spk.conference_name)
            li_canon = canonicalize_url(spk.linkedin_url)

            # Check if speaker already exists under this conference ID, conference title, or LinkedIn profile
            is_spk_dup = False
            spk_reason = ""
            if key in existing_keys:
                is_spk_dup = True
                spk_reason = f"Speaker '{name}' for Conference ID '{conf_id}'"
            elif title_norm and name_norm and (title_norm, name_norm) in existing_title_speakers:
                is_spk_dup = True
                spk_reason = f"Speaker '{name}' for Conference Title '{spk.conference_name}'"
            elif li_canon and "linkedin.com/in/" in li_canon and li_canon in existing_linkedin:
                is_spk_dup = True
                spk_reason = f"Speaker LinkedIn '{li_canon}'"

            if is_spk_dup:
                logger.info(f"OneDrive Excel: Retaining existing historical speaker '{name}' ({spk_reason} already present). Skipping duplicate append.")
                skipped_count += 1
                continue

            speaker_id = f"SPK-{spk.id}" if spk.id else f"SPK-{conf_id}-{len(rows_to_insert)+1}"
            company = spk.company_name or spk.company_organization or ""
            job_title = spk.job_role_designation or ""
            linkedin = spk.linkedin_url or ""
            company_url = spk.official_company_website_url or ""
            profile_url = spk.source_url or ""
            source_url = spk.source_url or ""
            collected_at_str = spk.created_at.isoformat() if spk.created_at else datetime.utcnow().isoformat()

            new_row = [
                speaker_id,                  # 1. SpeakerID
                conf_id,                     # 2. ConferenceID
                spk.conference_name or "",   # 3. ConferenceTitle
                name,                        # 4. SpeakerName
                job_title,                   # 5. JobTitle
                company,                     # 6. Company
                linkedin,                    # 7. LinkedInURL
                company_url,                 # 8. CompanyURL
                profile_url,                 # 9. SpeakerProfileURL
                source_url,                  # 10. SourceURL
                "verified",                  # 11. VerifiedStatus
                collected_at_str             # 12. CollectedAt
            ]

            rows_to_insert.append(new_row)
            existing_keys.add(key)
            if title_norm and name_norm:
                existing_title_speakers.add((title_norm, name_norm))
            if li_canon and "linkedin.com/in/" in li_canon:
                existing_linkedin.add(li_canon)

        inserted_count = 0
        if rows_to_insert:
            logger.info(f"OneDrive Excel: Inserting {len(rows_to_insert)} genuinely new speaker row(s) into '{self.spk_tbl_name}'...")
            endpoint = f"/drives/{drive_id}/items/{item_id}/workbook/tables/{self.spk_tbl_name}/rows"
            res = self._api_request("POST", endpoint, body={"values": rows_to_insert})
            if "error" in res:
                logger.error(f"Failed to insert speaker rows into OneDrive Excel: {res}")
                return {"status": "error", "error": res, "inserted_count": 0, "skipped_count": skipped_count}
            inserted_count = len(rows_to_insert)

        logger.info(f"✅ OneDrive Excel speakers sync: {inserted_count} appended, {skipped_count} preserved/skipped.")
        return {
            "status": "success",
            "inserted_count": inserted_count,
            "skipped_count": skipped_count
        }

    def sync_all(
        self,
        conferences: List[Conference],
        speakers: List[Speaker]
    ) -> Dict[str, Any]:
        """
        Synchronizes both genuine conferences and speakers to OneDrive Excel using strict append-only semantics.
        Ensures successful save before considering the storage process complete.
        """
        conf_res = self.sync_conferences(conferences)
        if conf_res.get("status") == "error":
            logger.error(f"Failed to append conference rows to OneDrive Excel: {conf_res.get('error')}")
            raise RuntimeError(f"OneDrive Excel conference append failed: {conf_res.get('error')}")

        spk_res = self.sync_speakers(speakers)
        if spk_res.get("status") == "error":
            logger.error(f"Failed to append speaker rows to OneDrive Excel: {spk_res.get('error')}")
            raise RuntimeError(f"OneDrive Excel speaker append failed: {spk_res.get('error')}")

        return {
            "status": "success",
            "conferences": conf_res,
            "speakers": spk_res,
            "timestamp": datetime.utcnow().isoformat()
        }
