#!/usr/bin/env python3
"""
CLI utility to preview and send test emails for outreach leads or custom email addresses.
Strictly adheres to predefined email templates and initial outreach tense.
"""
import sys
import requests
import argparse

API_BASE = "http://127.0.0.1:8001/api/studio"

def get_sample_lead():
    try:
        resp = requests.get(f"{API_BASE}/leads?category=qualified&upcoming_only=true", timeout=10)
        if resp.status_code == 200:
            leads = resp.json().get("leads", [])
            if leads:
                return leads[0]
    except Exception:
        pass
    return {
        "contact_name": "Myke Roeschlein",
        "job_title": "President and CFO",
        "company_name": "Texas Capital",
        "conference_name": "SMALL BUSINESS EXPO HOUSTON",
        "contact_type": "Speaker",
        "primary_industry": "Commercial Banking"
    }

def send_to_custom_recipients(recipients: list, use_llm: bool = False):
    print(f"\n🚀 Sending test email to {len(recipients)} recipient(s) (use_llm={use_llm})...")
    sample_lead = get_sample_lead()
    print(f"Sample Lead Context: {sample_lead.get('contact_name')} ({sample_lead.get('company_name')}) — {sample_lead.get('conference_name')}\n")

    for idx, email in enumerate(recipients, 1):
        clean_email = email.strip()
        if not clean_email:
            continue
        print(f"[{idx}/{len(recipients)}] Preparing email for {clean_email}...")

        # 1. Generate email anchored to template
        gen_resp = requests.post(f"{API_BASE}/generate-email", json={
            "contact_name": sample_lead.get("contact_name", "Myke Roeschlein"),
            "job_title": sample_lead.get("job_title", "President and CFO"),
            "company_name": sample_lead.get("company_name", "Texas Capital"),
            "conference_name": sample_lead.get("conference_name", "SMALL BUSINESS EXPO HOUSTON"),
            "contact_type": sample_lead.get("contact_type", "Speaker"),
            "industry": sample_lead.get("primary_industry", "Commercial Banking"),
            "use_llm": use_llm
        }, timeout=20)

        if gen_resp.status_code != 200:
            print(f"❌ Failed to generate email: {gen_resp.text}")
            continue

        email_data = gen_resp.json()
        subject = f"[TEST] {email_data.get('subject')}"
        body = email_data.get("body")

        print(f"   Subject: {subject}")
        print(f"   Preview: {body.splitlines()[0] if body else ''}")

        # 2. Send test email
        send_resp = requests.post(f"{API_BASE}/send-test", json={
            "recipient_email": clean_email,
            "subject": subject,
            "body": body,
            "lead_id": sample_lead.get("id"),
            "conference_name": sample_lead.get("conference_name")
        }, timeout=20)

        if send_resp.status_code == 200:
            res_json = send_resp.json()
            print(f"   ✅ Sent successfully to {clean_email}!")
            print(f"   Message ID: {res_json.get('message_id')[:30]}...\n")
        else:
            print(f"   ❌ Send failed: {send_resp.text}\n")

def preview_or_send_top_leads(num_leads: int = 5, test_override_email: str = None, dry_run: bool = False, use_llm: bool = False):
    print(f"\n📋 Fetching top {num_leads} upcoming qualified leads (use_llm={use_llm})...")
    resp = requests.get(f"{API_BASE}/leads?category=qualified&upcoming_only=true", timeout=10)
    if resp.status_code != 200:
        print(f"❌ Failed to fetch leads: {resp.text}")
        return

    leads = resp.json().get("leads", [])[:num_leads]
    if not leads:
        print("❌ No qualified leads found.")
        return

    print(f"Found {len(leads)} leads.\n")

    for idx, lead in enumerate(leads, 1):
        target_email = test_override_email if test_override_email else lead.get("professional_email")
        print(f"--- Lead #{idx} ---")
        print(f"Name:       {lead.get('contact_name')} ({lead.get('job_title')})")
        print(f"Company:    {lead.get('company_name')}")
        print(f"Conference: {lead.get('conference_name')}")
        print(f"Target To:  {target_email} {'(Test Override)' if test_override_email else '(Real Lead Email)'}")

        # Generate template
        gen_resp = requests.post(f"{API_BASE}/generate-email", json={
            "contact_name": lead.get("contact_name", ""),
            "job_title": lead.get("job_title", ""),
            "company_name": lead.get("company_name", ""),
            "conference_name": lead.get("conference_name", ""),
            "contact_type": lead.get("contact_type", "Speaker"),
            "industry": lead.get("primary_industry", "ai"),
            "use_llm": use_llm
        }, timeout=20)

        if gen_resp.status_code != 200:
            print(f"❌ Generation failed: {gen_resp.text}\n")
            continue

        email_data = gen_resp.json()
        subject = f"[TEST] {email_data.get('subject')}" if test_override_email else email_data.get('subject')
        body = email_data.get("body")

        print(f"Subject:    {subject}")
        print(f"Opening:    {body.splitlines()[0] if body else ''}")

        if dry_run:
            print("Status:     [DRY RUN - Email not dispatched]\n")
        else:
            send_resp = requests.post(f"{API_BASE}/send-test", json={
                "recipient_email": target_email,
                "subject": subject,
                "body": body,
                "lead_id": lead.get("id"),
                "conference_name": lead.get("conference_name")
            }, timeout=20)
            if send_resp.status_code == 200:
                print(f"Status:     ✅ Sent successfully to {target_email}!\n")
            else:
                print(f"Status:     ❌ Send failed: {send_resp.text}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Send test emails for outreach leads")
    parser.add_argument("--recipients", nargs="+", help="Send test emails to these specific email addresses")
    parser.add_argument("--top", type=int, default=5, help="Number of top qualified leads (default: 5)")
    parser.add_argument("--to", type=str, help="Route all 5 lead drafts to a single test email address (safe mode)")
    parser.add_argument("--llm", action="store_true", help="Enable LLM personalization (default: False, uses official template)")
    parser.add_argument("--dry-run", action="store_true", help="Preview email generation without sending")

    args = parser.parse_args()

    if args.recipients:
        send_to_custom_recipients(args.recipients, use_llm=args.llm)
    else:
        preview_or_send_top_leads(num_leads=args.top, test_override_email=args.to, dry_run=args.dry_run, use_llm=args.llm)
