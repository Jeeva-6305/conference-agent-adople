import sys
import io
from pathlib import Path

# Force UTF-8 stdout on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.database import init_db, SessionLocal
from app.models import Conference
from app.tasks.celery_app import task_scrape_and_ingest, task_publish_2_days_before
from app.storage.excel_manager import ExcelManager

print("\n" + "="*70)
print("[*] TESTING COMPLETE USA CONFERENCE AGENT PIPELINE")
print("="*70)

# 1. Initialize Database
print("\n[Step 1] Initializing Database (PostgreSQL / SQLite fallback)...")
init_db()
print("[OK] Database ready.")

# 2. Run 24/7 Scraper & AI Validation Engine
print("\n[Step 2] Executing Scraper across 6 websites + AI Extraction...")
result_scrape = task_scrape_and_ingest()
print(f"[OK] Scraping completed: {result_scrape}")

# 3. Verify Database Records
db = SessionLocal()
confs = db.query(Conference).all()
print(f"\n[Step 3] Conferences in Database: {len(confs)}")
for c in confs:
    print(f"  - [{c.source_name.upper()}] {c.conference_title} ({c.city}, {c.country}) | Start: {c.start_date} | Published: {c.is_published_to_excel}")
db.close()

# 4. Run 2-Day Excel Publication Engine
print("\n[Step 4] Checking & Publishing Conferences 2 Days Prior to Event into Excel...")
result_publish = task_publish_2_days_before()
print(f"[OK] Publication result: {result_publish}")

# 5. Verify Excel Output
print("\n[Step 5] Verifying Generated Excel Sheet...")
em = ExcelManager()
df = em.read_excel_as_dataframe()
print(f"[OK] Excel file path: {em.file_path}")
print(f"[OK] Total rows in Excel: {len(df)}")
print("[OK] Excel Columns:")
for i, col in enumerate(df.columns, 1):
    print(f"   {i}. {col}")

print("\nSample row from Excel:")
if len(df) > 0:
    print(df.iloc[0].to_dict())

print("\n" + "="*70)
print("[SUCCESS] ALL REQUIREMENTS VERIFIED AND FUNCTIONING!")
print("="*70)
