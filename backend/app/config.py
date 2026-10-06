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

    # Email Notification Settings
    NOTIFICATION_RECIPIENT_EMAIL: str = os.getenv("NOTIFICATION_RECIPIENT_EMAIL", "jeevanandham@adople.ai")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", 587))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "noreply@conference-agent.ai"))
    SMTP_USE_TLS: bool = os.getenv("SMTP_USE_TLS", "True").lower() in ("true", "1", "yes")

    # Automation intervals

    REMINDER_DAYS_BEFORE: int = int(os.getenv("REMINDER_DAYS_BEFORE", 2))
    SCRAPER_INTERVAL_MINUTES: int = int(os.getenv("SCRAPER_INTERVAL_MINUTES", 60))

settings = Settings()

