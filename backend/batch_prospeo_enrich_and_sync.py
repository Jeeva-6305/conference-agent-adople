import sys
from pathlib import Path
repo_root = str(Path(__file__).resolve().parent.parent)
backend_root = str(Path(__file__).resolve().parent)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

import logging
import subprocess
import time
import openpyxl
from typing import Dict, Any, List, Optional

from backend.app.database import SessionLocal
from backend.app.models import WeeklySpeaker, WeeklyExhibitor
from backend.app.services.prospeo_service import ProspeoService
from backend.app.services.onedrive_excel_service import OneDriveExcelService
from backend.app.storage.excel_manager import ExcelManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prospeo_lead_enricher")


def check_domain_mx(domain: str) -> bool:
    if not domain or "." not in domain:
        return False
    try:
        out = subprocess.check_output(["dig", "MX", domain, "+short"], timeout=2.5).decode("utf-8").strip()
        return bool(out)
    except Exception:
        return False


def run():
    prospeo = ProspeoService()
    account_info = prospeo.get_account_info()
    logger.info(f"Prospeo Account Info at start: {account_info}")

    od = OneDriveExcelService()
    db = SessionLocal()
    excel_mgr = ExcelManager()
    local_wb_path = excel_mgr.file_path

    # =========================================================================
    # PART 1: QUALIFIED LEADS
    # =========================================================================
    logger.info("=== Loading Qualified Leads from SharePoint Online ===")
    q_cols, q_col_map, q_rows = od.get_qualified_leads_table_info()
    logger.info(f"Total Qualified Leads in SharePoint: {len(q_rows)}")

    name_idx = q_col_map.get("contactname") or 8
    comp_idx = q_col_map.get("companyname") or 3
    cat_idx = q_col_map.get("contacttype") or 7
    em_idx = q_col_map.get("professionalemail") or 10
    stat_idx = q_col_map.get("emailstatus") or 11
    li_idx = q_col_map.get("personallinkedinurl") or 12
    ost_idx = q_col_map.get("outreachstatus") or 17

    enriched_qualified = []
    unverified_qualified = []
    already_safe_qualified = []

    for r_obj in q_rows:
        row_idx = r_obj["row_index"]
        vals = list(r_obj["values"])

        outreach_st = str(vals[ost_idx] or "").strip().lower()
        if outreach_st in ("sent", "sending", "bounced", "failed", "replied"):
            continue

        name = str(vals[name_idx] or "").strip()
        comp = str(vals[comp_idx] or "").strip()
        cat = str(vals[cat_idx] or "").strip()

        if not name or not comp:
            continue
        curr_em = str(vals[em_idx] or "").strip().lower()
        curr_li = str(vals[li_idx] or "").strip()

        # Check DB entity
        spk = db.query(WeeklySpeaker).filter(WeeklySpeaker.speaker_name.ilike(name)).first()
        exh = db.query(WeeklyExhibitor).filter(WeeklyExhibitor.contact_person.ilike(name)).first() if not spk else None

        db_li = spk.personal_linkedin_url if spk else (exh.contact_person_linkedin_url if exh else "")
        target_li = curr_li or db_li
        src = spk.email_source_url if spk else (exh.source_url if exh else "")

        is_official = ("exhibitor" in cat.lower() or (exh and exh.source_url and "exhibitor" in exh.source_url.lower()))
        is_hunter = ("hunter" in str(src).lower())

        if (is_official or is_hunter) and curr_em and "@" in curr_em:
            domain = curr_em.split("@")[1]
            if check_domain_mx(domain):
                logger.info(f"Skipping official/hunter safe lead: {name} ({comp}) -> {curr_em}")
                already_safe_qualified.append({"name": name, "company": comp, "email": curr_em})
                continue

        # Query Prospeo API
        logger.info(f"🔍 [Prospeo Query] Row {row_idx}: {name} | {comp} | LI: {target_li[:40] if target_li else 'None'}")
        p_res = prospeo.enrich_person(name=name, company=comp, linkedin_url=target_li)

        status = p_res.get("status")
        found_em = (p_res.get("email") or "").strip().lower()
        v_stat = (p_res.get("verification_status") or "needs_review").lower()
        found_li = p_res.get("linkedin_url") or target_li

        is_valid_work_email = False
        if status == "success" and found_em and "@" in found_em and v_stat == "verified":
            domain = found_em.split("@")[1]
            if check_domain_mx(domain):
                is_valid_work_email = True

        if is_valid_work_email:
            logger.info(f"   ✅ [VERIFIED EMAIL FOUND] {found_em} (Verified) for {name}")
            enriched_qualified.append({"name": name, "company": comp, "email": found_em, "old_email": curr_em})

            # Update row values
            vals[em_idx] = found_em
            vals[stat_idx] = "Verified"
            if found_li and li_idx < len(vals):
                vals[li_idx] = found_li

            # Update SharePoint Online
            od.update_qualified_leads_row(row_index=row_idx, values=vals)

            # Update PostgreSQL
            if spk:
                spk.professional_email = found_em
                spk.email_source_url = "prospeo.io"
                spk.verification_status = "verified"
                if found_li and not spk.personal_linkedin_url:
                    spk.personal_linkedin_url = found_li
            elif exh:
                exh.professional_email = found_em
                exh.email_status = "verified"
                if found_li and not exh.contact_person_linkedin_url:
                    exh.contact_person_linkedin_url = found_li
            db.commit()

        else:
            logger.warning(f"   ⚠️ [UNVERIFIED] Prospeo could not verify email for {name} ({comp}). Leaving pending.")
            unverified_qualified.append({"name": name, "company": comp, "prev_email": curr_em})

            # Leave empty rather than guessed
            vals[em_idx] = ""
            vals[stat_idx] = "needs_review"
            od.update_qualified_leads_row(row_index=row_idx, values=vals)

            if spk:
                spk.professional_email = ""
                spk.email_source_url = "needs_review"
                spk.verification_status = "needs_review"
            elif exh:
                exh.professional_email = ""
                exh.email_status = "needs_review"
            db.commit()

    # =========================================================================
    # PART 2: NON-QUALIFIED LEADS REVIEW & CLEANUP
    # =========================================================================
    logger.info("=== Loading Non-Qualified Leads from SharePoint Online ===")
    nq_cols, nq_col_map, nq_rows = od.get_non_qualified_leads_table_info()
    logger.info(f"Total Non-Qualified Leads in SharePoint: {len(nq_rows)}")

    nq_em_idx = nq_col_map.get("professionalemail") or 10
    nq_stat_idx = nq_col_map.get("emailstatus") or 11
    nq_ost_idx = nq_col_map.get("outreachstatus") or 17
    nq_name_idx = nq_col_map.get("contactname") or 8
    nq_comp_idx = nq_col_map.get("companyname") or 3

    cleaned_nq = []
    valid_nq = []

    for r_obj in nq_rows:
        row_idx = r_obj["row_index"]
        vals = list(r_obj["values"])

        outreach_st = str(vals[nq_ost_idx] or "").strip().lower()
        if outreach_st in ("sent", "sending", "bounced", "failed", "replied"):
            continue

        name = str(vals[nq_name_idx] or "").strip()
        comp = str(vals[nq_comp_idx] or "").strip()
        curr_em = str(vals[nq_em_idx] or "").strip().lower()

        if not name or not comp:
            continue

        if curr_em and "@" in curr_em:
            domain = curr_em.split("@")[1]
            if not check_domain_mx(domain):
                logger.warning(f"Cleaning dead domain in Non-Qualified Leads row {row_idx}: {name} <{curr_em}>")
                vals[nq_em_idx] = ""
                vals[nq_stat_idx] = "needs_review"
                od.update_non_qualified_leads_row(row_index=row_idx, values=vals)

                spk_nq = db.query(WeeklySpeaker).filter(WeeklySpeaker.speaker_name.ilike(name)).first()
                if spk_nq:
                    spk_nq.professional_email = ""
                    spk_nq.verification_status = "needs_review"
                    db.commit()

                cleaned_nq.append({"name": name, "company": comp, "email": curr_em})
            else:
                valid_nq.append({"name": name, "company": comp, "email": curr_em})

    # =========================================================================
    # PART 3: SYNC LOCAL EXCEL FROM SHAREPOINT
    # =========================================================================
    logger.info("Syncing updated master excel from SharePoint Online to local file...")
    token = od._get_access_token()
    drive_id = od.resolve_drive_id()
    item_id = od.resolve_item_id()
    import requests
    url = f"{od.base_url}/drives/{drive_id}/items/{item_id}/content"
    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if resp.status_code == 200:
        with open(local_wb_path, "wb") as f:
            f.write(resp.content)
        logger.info(f"Successfully refreshed {local_wb_path} from SharePoint Online!")

    final_account_info = prospeo.get_account_info()
    logger.info(f"Prospeo Account Info at completion: {final_account_info}")

    db.close()

    print("\n" + "=" * 60)
    print("ENRICHMENT & CLEANUP SUMMARY")
    print("=" * 60)
    print(f"Qualified Leads - Verified Work Emails Found: {len(enriched_qualified)}")
    for e in enriched_qualified:
        print(f"  ✅ {e['name']} | {e['company']} -> {e['email']}")
    print(f"\nQualified Leads - Unverified / Left Pending: {len(unverified_qualified)}")
    for u in unverified_qualified:
        print(f"  ⚠️ {u['name']} | {u['company']} (was: {u['prev_email']})")
    print(f"\nQualified Leads - Already Safe (Official Exhibitors / Hunter): {len(already_safe_qualified)}")
    for s in already_safe_qualified:
        print(f"  🛡️ {s['name']} | {s['company']} -> {s['email']}")
    print(f"\nNon-Qualified Leads - Cleaned Dead Domains: {len(cleaned_nq)}")
    for c in cleaned_nq:
        print(f"  🧹 Cleared dead domain: {c['name']} <{c['email']}>")
    print(f"Non-Qualified Leads - Valid MX domains remaining: {len(valid_nq)}")
    print(f"\nProspeo Credits Remaining: {final_account_info.get('remaining_credits')}")
    print("=" * 60)


if __name__ == "__main__":
    run()
