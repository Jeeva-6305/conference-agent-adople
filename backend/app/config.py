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
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "noreply@conference-agent.ai"))
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")

    # Automation intervals

    REMINDER_DAYS_BEFORE: int = int(os.getenv("REMINDER_DAYS_BEFORE", 2))
    SCRAPER_INTERVAL_MINUTES: int = int(os.getenv("SCRAPER_INTERVAL_MINUTES", 60))

    # Microsoft Graph & OneDrive Excel Settings
    SHAREPOINT_CLIENT_ID: str = os.getenv("SHAREPOINT_CLIENT_ID", "")
    SHAREPOINT_CLIENT_SECRET: str = os.getenv("SHAREPOINT_CLIENT_SECRET", "")
    SHAREPOINT_TENANT_ID: str = os.getenv("SHAREPOINT_TENANT_ID", "")
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

    # Apollo API (LinkedIn Discovery Only)
    APOLLO_API_KEY: str = os.getenv("APOLLO_API_KEY", "")
    APOLLO_ENRICHMENT_ENABLED: bool = os.getenv("APOLLO_ENRICHMENT_ENABLED", "true").lower() in ("true", "1", "yes")

    # Hunter.io API (Professional Email Discovery & Verification Only)
    HUNTER_API_KEY: str = os.getenv("HUNTER_API_KEY", "")
    HUNTER_EMAIL_ENRICHMENT_ENABLED: bool = os.getenv("HUNTER_EMAIL_ENRICHMENT_ENABLED", "true").lower() in ("true", "1", "yes")
    HUNTER_BASE_URL: str = os.getenv("HUNTER_BASE_URL", "https://api.hunter.io/v2")

settings = Settings()

