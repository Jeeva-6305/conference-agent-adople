import logging
import subprocess
import time
from typing import Dict, Any, List, Optional
import openpyxl

from app.database import SessionLocal
from app.models import WeeklySpeaker, WeeklyExhibitor
from app.services.prospeo_service import ProspeoService
from app.services.speaker_outreach_service import SpeakerOutreachService
from app.services.onedrive_excel_service import OneDriveExcelService
from app.storage.excel_manager import ExcelManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prospeo_batch_enricher")


def check_domain_mx(domain: str) -> bool:
    if not domain or "." not in domain:
        return False
    try:
        out = subprocess.check_output(["dig", "MX", domain, "+short"], timeout=2.5).decode("utf-8").strip()
        return bool(out)
    except Exception:
        return False


def run_enrichment():
    prospeo = ProspeoService()
    account_info = prospeo.get_account_info()
    logger.info(f"Prospeo Account Info at start: {account_info}")

    db = SessionLocal()
    svc = SpeakerOutreachService()
    excel_mgr = ExcelManager()
    local_wb_path = excel_mgr.published_file_path

    # 1. Load pending qualified leads from sheet
    q_leads = svc._load_qualified_leads()
    pending_q = [
        l for l in q_leads
        if str(l.get("outreach_status", "")).strip().lower() not in ("sent", "sending", "bounced", "failed", "replied")
    ]

    logger.info(f"Total pending Qualified Leads: {len(pending_q)}")

    # Load local Excel workbook to update in-place
    wb = openpyxl.load_workbook(local_wb_path)
    ws_q = wb["Qualified Leads"] if "Qualified Leads" in wb.sheetnames else None
    ws_v = wb["Verified Data"] if "Verified Data" in wb.sheetnames else None
    ws_nq = wb["Non -Qualified Leads"] if "Non -Qualified Leads" in wb.sheetnames else None

    # Map column headers for Qualified Leads
    q_col_map = {}
    if ws_q:
        for col_idx in range(1, ws_q.max_column + 1):
            val = str(ws_q.cell(row=1, column=col_idx).value or "").strip().lower().replace(" ", "").replace("_", "")
            q_col_map[val] = col_idx

    em_col_q = q_col_map.get("professionalemail", 14)
    stat_col_q = q_col_map.get("emailstatus", 15)

    enriched_success = []
    unverified_pending = []
    already_safe = []

    for idx, lead in enumerate(pending_q, 1):
        name = lead.get("name") or ""
        comp = lead.get("company_name") or ""
        cat = lead.get("category") or ""
        current_em = (lead.get("professional_email") or "").strip().lower()
        sheet_row = lead.get("row_index") + 2  # header is row 1, data starts row 2

        # Check DB entity
        spk = db.query(WeeklySpeaker).filter(WeeklySpeaker.speaker_name.ilike(name)).first()
        exh = db.query(WeeklyExhibitor).filter(WeeklyExhibitor.contact_person.ilike(name)).first() if not spk else None

        li_url = lead.get("personal_linkedin_url") or (spk.personal_linkedin_url if spk else (exh.contact_person_linkedin_url if exh else ""))
        src = spk.email_source_url if spk else (exh.source_url if exh else "")

        # Official exhibitors or hunter verified
        is_official_exhibitor = (cat == "Exhibitor" or (exh and exh.source_url and "exhibitor" in exh.source_url.lower()))
        is_hunter_verified = ("hunter" in str(src).lower())

        if (is_official_exhibitor or is_hunter_verified) and current_em and "@" in current_em:
            domain = current_em.split("@")[1]
            if check_domain_mx(domain):
                logger.info(f"[{idx}/{len(pending_q)}] Skipping safe/official lead: {name} ({comp}) -> {current_em}")
                already_safe.append({"name": name, "company": comp, "email": current_em})
                continue

        # Query Prospeo API
        logger.info(f"[{idx}/{len(pending_q)}] Querying Prospeo for: {name} | {comp} | LI: {li_url[:40] if li_url else 'None'}")
        p_res = prospeo.enrich_person(name=name, company=comp, linkedin_url=li_url)
        
        status = p_res.get("status")
        found_email = (p_res.get("email") or "").strip().lower()
        v_status = p_res.get("verification_status") or "needs_review"
        found_li = p_res.get("linkedin_url") or li_url

        has_valid_email = False
        if status == "success" and found_email and "@" in found_email and v_status == "verified":
            domain = found_email.split("@")[1]
            if check_domain_mx(domain):
                has_valid_email = True

        if has_valid_email:
            logger.info(f"   🎉 VERIFIED WORK EMAIL FOUND: {found_email} ({v_status}) for {name}")
            enriched_success.append({"name": name, "company": comp, "email": found_email, "old_email": current_em})
            
            # Update DB
            if spk:
                spk.professional_email = found_email
                spk.email_source_url = "prospeo.io"
                spk.verification_status = "verified"
                if found_li and not spk.personal_linkedin_url:
                    spk.personal_linkedin_url = found_li
            elif exh:
                exh.professional_email = found_email
                exh.email_status = "verified"
                if found_li and not exh.contact_person_linkedin_url:
                    exh.contact_person_linkedin_url = found_li
            db.commit()

            # Update Excel Qualified Leads sheet
            if ws_q and sheet_row <= ws_q.max_row:
                ws_q.cell(row=sheet_row, column=em_col_q).value = found_email
                ws_q.cell(row=sheet_row, column=stat_col_q).value = "Verified"

            # Update Verified Data sheet if matching
            if ws_v:
                for v_r in range(2, ws_v.max_row + 1):
                    v_name = str(ws_v.cell(row=v_r, column=4).value or "").strip()
                    if v_name.lower() == name.lower():
                        ws_v.cell(row=v_r, column=7).value = found_email
                        ws_v.cell(row=v_r, column=9).value = "Verified"
        else:
            logger.warning(f"   ⚠️ Could not verify email for {name} ({comp}). Leaving pending (needs_review).")
            unverified_pending.append({"name": name, "company": comp, "prev_email": current_em})

            # Clear unverified/guessed email from sending queue
            if spk:
                spk.professional_email = ""
                spk.verification_status = "needs_review"
                spk.email_source_url = "needs_review"
            elif exh:
                exh.professional_email = ""
                exh.email_status = "needs_review"
            db.commit()

            if ws_q and sheet_row <= ws_q.max_row:
                ws_q.cell(row=sheet_row, column=em_col_q).value = ""
                ws_q.cell(row=sheet_row, column=stat_col_q).value = "needs_review"

            if ws_v:
                for v_r in range(2, ws_v.max_row + 1):
                    v_name = str(ws_v.cell(row=v_r, column=4).value or "").strip()
                    if v_name.lower() == name.lower():
                        ws_v.cell(row=v_r, column=7).value = ""
                        ws_v.cell(row=v_r, column=9).value = "needs_review"

    # 2. Clean Non-Qualified Leads dead domains
    nq_cleaned = []
    if ws_nq:
        nq_col_map = {}
        for col_idx in range(1, ws_nq.max_column + 1):
            val = str(ws_nq.cell(row=1, column=col_idx).value or "").strip().lower().replace(" ", "").replace("_", "")
            nq_col_map[val] = col_idx

        em_col_nq = nq_col_map.get("professionalemail", 14)
        stat_col_nq = nq_col_map.get("emailstatus", 15)

        for nq_r in range(2, ws_nq.max_row + 1):
            em_val = str(ws_nq.cell(row=nq_r, column=em_col_nq).value or "").strip().lower()
            name_val = str(ws_nq.cell(row=nq_r, column=12).value or "").strip()
            if em_val and "@" in em_val:
                domain = em_val.split("@")[1]
                if not check_domain_mx(domain):
                    logger.warning(f"Clearing dead domain in Non-Qualified Leads: {name_val} <{em_val}>")
                    ws_nq.cell(row=nq_r, column=em_col_nq).value = ""
                    ws_nq.cell(row=nq_r, column=stat_col_nq).value = "needs_review"
                    nq_cleaned.append({"name": name_val, "email": em_val})
                    # Also reflect in DB
                    spk_nq = db.query(WeeklySpeaker).filter(WeeklySpeaker.speaker_name.ilike(name_val)).first()
                    if spk_nq:
                        spk_nq.professional_email = ""
                        spk_nq.verification_status = "needs_review"
                        db.commit()

    # Save local Excel
    wb.save(local_wb_path)
    logger.info(f"Saved clean local Excel workbook at {local_wb_path}")

    db.close()

    # 3. Synchronize cleanly with OneDrive / SharePoint tables
    logger.info("Synchronizing updated sheets to OneDrive SharePoint...")
    onedrive_svc = OneDriveExcelService()
    try:
        od_q_res = onedrive_svc.sync_qualified_leads_to_onedrive()
        logger.info(f"OneDrive Qualified Leads sync result: {od_q_res}")
    except Exception as e:
        logger.error(f"Error syncing Qualified Leads to OneDrive: {e}")

    try:
        od_nq_res = onedrive_svc.sync_non_qualified_leads_to_onedrive()
        logger.info(f"OneDrive Non-Qualified Leads sync result: {od_nq_res}")
    except Exception as e:
        logger.error(f"Error syncing Non-Qualified Leads to OneDrive: {e}")

    final_account_info = prospeo.get_account_info()
    logger.info(f"Prospeo Account Info at completion: {final_account_info}")

    return {
        "enriched_success": enriched_success,
        "unverified_pending": unverified_pending,
        "already_safe": already_safe,
        "nq_cleaned": nq_cleaned,
        "remaining_credits": final_account_info.get("remaining_credits"),
    }


if __name__ == "__main__":
    run_enrichment()
