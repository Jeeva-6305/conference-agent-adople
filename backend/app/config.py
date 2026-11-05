import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
load_dotenv()

DATA_DIR = BASE_DIR.parent / "data"
EXCEL_DIR = DATA_DIR / "excel"
EXCEL_DIR.mkdir(parents=True, exist_ok=True)
EMAILS_DIR = DATA_DIR / "emails"
EMAILS_DIR.mkdir(parents=True, exist_ok=True)
TEAMS_DIR = DATA_DIR / "teams"
TEAMS_DIR.mkdir(parents=True, exist_ok=True)

class Settings:
    PROJECT_NAME: str = "USA Conference Discovery & Publication Agent"
    VERSION: str = "1.0.0"
    
    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg2://postgres:1234@localhost:5432/conference_db"
    )
    SQLITE_FALLBACK_URL: str = f"sqlite:///{BASE_DIR}/conferences_local.db"
    
    # AI Agent
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    
    # Celery & Redis
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Excel storage
    EXCEL_OUTPUT_PATH: str = str(EXCEL_DIR / "usa_conferences_published.xlsx")
    EMAILS_OUTPUT_DIR: str = str(EMAILS_DIR)
    TEAMS_OUTPUT_DIR: str = str(TEAMS_DIR)
    
    # Microsoft Teams Webhook Settings
    TEAMS_WEBHOOK_URL: str = os.getenv(
        "TEAMS_WEBHOOK_URL",
        "https://defaultbea3524823744c5c95d34a5f7071d9.88.environment.api.powerplatform.com:443/powerautomate/automations/direct/cu/02/workflows/65dbfcbeb4244e48bbbdc8efb8e55874/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=X5RzCAGsf3_Dr9hw_yIC1Lbp26SuS3bBuJebBHnPLEY"
    )
    TEAMS_CARD_ENABLED: bool = os.getenv("TEAMS_CARD_ENABLED", "false").lower() in ("true", "1", "yes")

    # Email Notification Settings
    NOTIFICATION_RECIPIENT_EMAIL: str = os.getenv("NOTIFICATION_RECIPIENT_EMAIL", "jeevanandham@adople.ai")
    EMAIL_REMINDER_ENABLED: bool = os.getenv("EMAIL_REMINDER_ENABLED", "false").lower() in ("true", "1", "yes")
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "microsoft_graph").lower()
    EMAIL_DRY_RUN: bool = os.getenv("EMAIL_DRY_RUN", "false").lower() in ("true", "1", "yes")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "noreply@conference-agent.ai"))
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")

    # Automation intervals
    T2_WORKFLOW_ENABLED: bool = os.getenv("T2_WORKFLOW_ENABLED", "true").lower() in ("true", "1", "yes")
    REMINDER_DAYS_BEFORE: int = int(os.getenv("REMINDER_DAYS_BEFORE", 2))
    SCRAPER_INTERVAL_MINUTES: int = int(os.getenv("SCRAPER_INTERVAL_MINUTES", 60))

    # Microsoft Graph & OneDrive Excel Settings
    SHAREPOINT_CLIENT_ID: str = os.getenv("SHAREPOINT_CLIENT_ID", "")
    SHAREPOINT_CLIENT_SECRET: str = os.getenv("SHAREPOINT_CLIENT_SECRET", "")
    SHAREPOINT_TENANT_ID: str = os.getenv("SHAREPOINT_TENANT_ID", "")
    SHAREPOINT_DRIVE_ID: str = os.getenv("SHAREPOINT_DRIVE_ID", "")
    SHAREPOINT_ITEM_ID: str = os.getenv("SHAREPOINT_ITEM_ID", "")
    SHAREPOINT_MASTER_SHEET: str = os.getenv("SHAREPOINT_MASTER_SHEET", "Verified Data")
    SHAREPOINT_LATEST_SHEET: str = os.getenv("SHAREPOINT_LATEST_SHEET", "latest_week_scoring")
    SHAREPOINT_HISTORY_SHEET: str = os.getenv("SHAREPOINT_HISTORY_SHEET", "Companies scoring")

    # Azure OpenAI & Tavily for AI Reranking Pipeline
    AZURE_OPENAI_BASE_URL: str = os.getenv("AZURE_OPENAI_BASE_URL", "https://dv-aus-es-resource.services.ai.azure.com/openai/v1")
    AZURE_OPENAI_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.4-mini")
    AZURE_OPENAI_API_KEY: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
    CONFERENCE_ONEDRIVE_HOSTNAME: str = os.getenv("CONFERENCE_ONEDRIVE_HOSTNAME", "adopleaiinf-my.sharepoint.com")
    CONFERENCE_ONEDRIVE_USER: str = os.getenv("CONFERENCE_ONEDRIVE_USER", "jeevanandham_adople_ai")
    CONFERENCE_EXCEL_FILE_NAME: str = os.getenv("CONFERENCE_EXCEL_FILE_NAME", "Conference_Agent_Conferences.xlsx")
    CONFERENCE_EXCEL_WORKSHEET_NAME: str = os.getenv("CONFERENCE_EXCEL_WORKSHEET_NAME", "conferences")
    CONFERENCE_EXCEL_TABLE_NAME: str = os.getenv("CONFERENCE_EXCEL_TABLE_NAME", "tbl_conferences")
    CONFERENCE_SPEAKERS_WORKSHEET_NAME: str = os.getenv("CONFERENCE_SPEAKERS_WORKSHEET_NAME", "speakers")
    CONFERENCE_SPEAKERS_TABLE_NAME: str = os.getenv("CONFERENCE_SPEAKERS_TABLE_NAME", "tbl_speakers")
    MICROSOFT_GRAPH_BASE_URL: str = os.getenv("MICROSOFT_GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")

    # Weekly Conference Scraping & OneDrive Excel Settings
    WEEKLY_AGENT_ENABLED: bool = os.getenv("WEEKLY_AGENT_ENABLED", "false").lower() in ("true", "1", "yes")
    WEEKLY_TIMEZONE: str = os.getenv("WEEKLY_TIMEZONE", "America/New_York")
    WEEKLY_REFRESH_ENABLED: bool = os.getenv("WEEKLY_REFRESH_ENABLED", "true").lower() in ("true", "1", "yes")
    WEEKLY_SCRAPE_LEAD_DAYS: int = int(os.getenv("WEEKLY_SCRAPE_LEAD_DAYS", "3"))
    WEEKLY_TEAMS_CARD_ENABLED: bool = os.getenv("WEEKLY_TEAMS_CARD_ENABLED", "false").lower() in ("true", "1", "yes")

    WEEKLY_CONFERENCE_EXCEL_WORKSHEET_NAME: str = os.getenv("WEEKLY_CONFERENCE_EXCEL_WORKSHEET_NAME", "weekly_conferences")
    WEEKLY_CONFERENCE_EXCEL_TABLE_NAME: str = os.getenv("WEEKLY_CONFERENCE_EXCEL_TABLE_NAME", "tbl_weekly_conferences")
    WEEKLY_SPEAKERS_EXCEL_WORKSHEET_NAME: str = os.getenv("WEEKLY_SPEAKERS_EXCEL_WORKSHEET_NAME", "weekly_speakers")
    WEEKLY_SPEAKERS_EXCEL_TABLE_NAME: str = os.getenv("WEEKLY_SPEAKERS_EXCEL_TABLE_NAME", "tbl_weekly_speakers")
    WEEKLY_SOURCE_LOG_EXCEL_WORKSHEET_NAME: str = os.getenv("WEEKLY_SOURCE_LOG_EXCEL_WORKSHEET_NAME", "weekly_source_run_log")
    WEEKLY_SOURCE_LOG_EXCEL_TABLE_NAME: str = os.getenv("WEEKLY_SOURCE_LOG_EXCEL_TABLE_NAME", "tbl_weekly_source_run_log")
    WEEKLY_ATTENDEES_EXCEL_WORKSHEET_NAME: str = os.getenv("WEEKLY_ATTENDEES_EXCEL_WORKSHEET_NAME", os.getenv("WEEKLY_ATTENDEE_WORKSHEET_NAME", "weekly_attendees"))
    WEEKLY_ATTENDEES_EXCEL_TABLE_NAME: str = os.getenv("WEEKLY_ATTENDEES_EXCEL_TABLE_NAME", os.getenv("WEEKLY_ATTENDEE_TABLE_NAME", "tbl_weekly_attendees"))
    WEEKLY_ATTENDEE_COLLECTION_ENABLED: bool = os.getenv("WEEKLY_ATTENDEE_COLLECTION_ENABLED", "true").lower() in ("true", "1", "yes")

    # Weekly Exhibitor Collection Configuration
    WEEKLY_EXHIBITOR_COLLECTION_ENABLED: bool = os.getenv("WEEKLY_EXHIBITOR_COLLECTION_ENABLED", "true").lower() in ("true", "1", "yes")
    WEEKLY_EXHIBITOR_WORKSHEET_NAME: str = os.getenv("WEEKLY_EXHIBITOR_WORKSHEET_NAME", "weekly_exhibitors")
    WEEKLY_EXHIBITOR_TABLE_NAME: str = os.getenv("WEEKLY_EXHIBITOR_TABLE_NAME", "weekly_exhibitors")
    WEEKLY_EXHIBITOR_SOURCE_VALIDATION: bool = os.getenv("WEEKLY_EXHIBITOR_SOURCE_VALIDATION", "true").lower() in ("true", "1", "yes")
    WEEKLY_EXHIBITOR_DUPLICATE_CHECK: bool = os.getenv("WEEKLY_EXHIBITOR_DUPLICATE_CHECK", "true").lower() in ("true", "1", "yes")
    WEEKLY_EXHIBITOR_APPEND_ONLY: bool = os.getenv("WEEKLY_EXHIBITOR_APPEND_ONLY", "true").lower() in ("true", "1", "yes")

    # Weekly ICP Strategic Scoring Configuration
    WEEKLY_ICP_SCORING_ENABLED: bool = os.getenv("WEEKLY_ICP_SCORING_ENABLED", "true").lower() in ("true", "1", "yes")
    WEEKLY_LATEST_SCORING_WORKSHEET_NAME: str = os.getenv("WEEKLY_LATEST_SCORING_WORKSHEET_NAME", "latest_week_scoring")

    # Prospeo.io API (High Accuracy LinkedIn Profile & Professional Email Enrichment)
    PROSPEO_API_KEY: str = os.getenv("PROSPEO_API_KEY", "")
    PROSPEO_ENRICHMENT_ENABLED: bool = os.getenv("PROSPEO_ENRICHMENT_ENABLED", "true").lower() in ("true", "1", "yes")

    # Apollo API (LinkedIn Discovery Only)
    APOLLO_API_KEY: str = os.getenv("APOLLO_API_KEY", "")
    APOLLO_ENRICHMENT_ENABLED: bool = os.getenv("APOLLO_ENRICHMENT_ENABLED", "true").lower() in ("true", "1", "yes")

    # Hunter.io API (Professional Email Discovery & Verification Only)
    HUNTER_API_KEY: str = os.getenv("HUNTER_API_KEY", "")
    HUNTER_EMAIL_ENRICHMENT_ENABLED: bool = os.getenv("HUNTER_EMAIL_ENRICHMENT_ENABLED", "true").lower() in ("true", "1", "yes")
    HUNTER_BASE_URL: str = os.getenv("HUNTER_BASE_URL", "https://api.hunter.io/v2")

    # Microsoft Graph Outreach Configuration (akash@adople.ai)
    OUTREACH_MS_TENANT_ID: str = os.getenv("OUTREACH_MS_TENANT_ID", "")
    OUTREACH_MS_CLIENT_ID: str = os.getenv("OUTREACH_MS_CLIENT_ID", "")
    OUTREACH_MS_CLIENT_SECRET: str = os.getenv("OUTREACH_MS_CLIENT_SECRET", "")
    OUTREACH_MS_MAILBOX: str = os.getenv("OUTREACH_MS_MAILBOX", "akash@adople.ai")
    OUTREACH_SENDER_NAME: str = os.getenv("SENDER_NAME", "Akash")
    OUTREACH_SENDER_TITLE: str = os.getenv("SENDER_TITLE", "Founder")
    OUTREACH_COMPANY: str = os.getenv("COMPANY", "Adople AI")
    OUTREACH_TEMPLATE_FILE: str = os.getenv("TEMPLATE_FILE", "template.txt")
    OUTREACH_SEND_TIME: str = os.getenv("SEND_TIME", "19:00")
    OUTREACH_SEND_DAY: str = os.getenv("OUTREACH_SEND_DAY", os.getenv("SEND_DAY", "thu"))
    OUTREACH_WATCH_INTERVAL_MINUTES: int = int(os.getenv("WATCH_INTERVAL_MINUTES", "5"))
    OUTREACH_DAILY_CAP: int = int(os.getenv("DAILY_CAP", "0"))
    OUTREACH_DRY_RUN: bool = os.getenv("DRY_RUN", "1").lower() in ("1", "true", "yes")
    OUTREACH_DELAY_MIN: int = int(os.getenv("DELAY_MIN", "60"))
    OUTREACH_DELAY_MAX: int = int(os.getenv("DELAY_MAX", "120"))
    OUTREACH_ALLOWED_EMAIL_STATUS: str = os.getenv("ALLOWED_EMAIL_STATUS", "verified")
    OUTREACH_SKIP_IF_ALREADY_REPLIED: bool = os.getenv("SKIP_IF_ALREADY_REPLIED", "1").lower() in ("1", "true", "yes")
    OUTREACH_GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    OUTREACH_USE_GEMINI: bool = os.getenv("USE_GEMINI", "1").lower() in ("1", "true", "yes")
    EMAIL_TEAMS_CARD_ENABLED: bool = os.getenv("EMAIL_TEAMS_CARD_ENABLED", os.getenv("EMAIL_TEAMS_CARD", "true")).lower() in ("1", "true", "yes")
    OUTREACH_STATE_FILE: str = os.getenv("STATE_FILE", "outreach_state.json")
    OUTREACH_ACTIVE: bool = os.getenv("OUTREACH_ACTIVE", "false").lower() in ("1", "true", "yes")
    OUTREACH_TIMEZONE: str = os.getenv("OUTREACH_TIMEZONE", "Asia/Kolkata")
    OUTREACH_SOURCE: str = os.getenv("OUTREACH_SOURCE", "qualified_leads")
    VERIFIED_DATA_EXCEL_TABLE_NAME: str = os.getenv("VERIFIED_DATA_EXCEL_TABLE_NAME", "tbl_verified_data")
    VERIFIED_DATA_EXCEL_WORKSHEET_NAME: str = os.getenv("VERIFIED_DATA_EXCEL_WORKSHEET_NAME", "Verified Data")
    QUALIFIED_LEADS_EXCEL_TABLE_NAME: str = os.getenv("QUALIFIED_LEADS_EXCEL_TABLE_NAME", "tbl_qualified_leads")
    QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME: str = os.getenv("QUALIFIED_LEADS_EXCEL_WORKSHEET_NAME", "Qualified Leads")
    FOLLOW_UP_ENABLED: bool = os.getenv("FOLLOW_UP_ENABLED", "false").lower() in ("1", "true", "yes")

    # Speaker Replies Configuration (Dedicated Sheet & Table)
    SPEAKER_REPLIES_ENABLED: bool = os.getenv("SPEAKER_REPLIES_ENABLED", "true").lower() in ("true", "1", "yes")
    SPEAKER_REPLIES_WORKSHEET_NAME: str = os.getenv("SPEAKER_REPLIES_WORKSHEET_NAME", "Speakers Replies")
    SPEAKER_REPLIES_TABLE_NAME: str = os.getenv("SPEAKER_REPLIES_TABLE_NAME", "tbl_speakers_replies")
    SPEAKER_REPLIES_SOURCE_WORKSHEET: str = os.getenv("SPEAKER_REPLIES_SOURCE_WORKSHEET", "weekly_speakers")
    SPEAKER_REPLIES_SOURCE_TABLE: str = os.getenv("SPEAKER_REPLIES_SOURCE_TABLE", "tbl_weekly_speakers")
    SPEAKER_REPLIES_APPEND_ONLY: bool = os.getenv("SPEAKER_REPLIES_APPEND_ONLY", "true").lower() in ("true", "1", "yes")
    SPEAKER_REPLIES_COPY_FULL_SPEAKER_ROW: bool = os.getenv("SPEAKER_REPLIES_COPY_FULL_SPEAKER_ROW", "true").lower() in ("true", "1", "yes")
    SPEAKER_REPLIES_PRESERVE_MULTIPLE_REPLIES: bool = os.getenv("SPEAKER_REPLIES_PRESERVE_MULTIPLE_REPLIES", "true").lower() in ("true", "1", "yes")
    SPEAKER_REPLIES_PREVENT_DUPLICATES: bool = os.getenv("SPEAKER_REPLIES_PREVENT_DUPLICATES", "true").lower() in ("true", "1", "yes")

settings = Settings()

