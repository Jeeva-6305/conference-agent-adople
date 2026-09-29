import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
load_dotenv()

DATA_DIR = BASE_DIR.parent / "data"
EXCEL_DIR = DATA_DIR / "excel"
EXCEL_DIR.mkdir(parents=True, exist_ok=True)

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
    
    # Automation intervals
    REMINDER_DAYS_BEFORE: int = 2
    SCRAPER_INTERVAL_MINUTES: int = 60 * 12

settings = Settings()
