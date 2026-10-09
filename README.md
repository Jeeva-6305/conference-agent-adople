# 🇺🇸 USA Conference Discovery & 2-Day Publication AI Agent

An automated 24/7 AI-powered agent that monitors and extracts conference details and speaker information across **6 major websites** for conferences held in the **USA**, validates them using **Google Gemini AI**, stores them in **PostgreSQL**, and publishes their full details into an **Excel sheet exactly 2 days before each conference starts**.

---

## 🏛️ System Architecture & Workflow

```
┌────────────────────────────────────────────────────────────────────────┐
│ 1. Conference Sources (6 Websites)                                     │
│    • 10times (10times.com/usa/conferences)                             │
│    • Luma (lu.ma/discover)                                             │
│    • Eventbrite (eventbrite.com/d/united-states/conferences/)           │
│    • Meetup (meetup.com/find/?keywords=conference&location=us)         │
│    • Cvent (cvent.com/events)                                          │
│    • Events in America (eventsinamerica.com)                           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Raw HTML & Metadata
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 2. Data Collection Layer                                               │
│    • Requests, BeautifulSoup4, Multi-threaded concurrent workers       │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Candidate Event Streams
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 3. AI Extraction & Validation Agent                                    │
│    • Google Gemini API (gemini-2.5-flash)                              │
│    • Enforces USA location validation                                  │
│    • Extracts Title, Dates, Speakers, Companies, Venue, City, URLs     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Structured Validated Data
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 4. PostgreSQL Database                                                 │
│    • SQLAlchemy ORM (with automatic SQLite fallback for local test)    │
│    • Stores discovered conferences, speaker profiles, and statuses     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ T-2 Days Publication Trigger
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 5. Scheduler & Publication Engine (Celery + Redis / APScheduler)       │
│    • Scans database for events starting in exactly 2 days              │
│    • Appends verified records to the styled Excel spreadsheet          │
│    • Updates publication status and timestamp                          │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│ 6. Output & Interfaces                                                 │
│    • Formatted Excel Sheet (.xlsx) with 15 required columns            │
│    • Modern React (Next.js) + Tailwind CSS Dashboard                   │
│    • FastAPI Backend REST Endpoints (port 8000)                        │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Excel Sheet Schema (15 Required Columns)

The published Excel spreadsheet (`data/excel/usa_conferences_published.xlsx`) contains:

| # | Column Name | Description |
|---|---|---|
| 1 | `Conference ID` | Unique identifier (e.g., `CONF-2026-XXXXXX`) |
| 2 | `Conference Title` | Verified formal conference title |
| 3 | `Industry / Category` | Domain (AI, Cloud, FinTech, Healthcare, Energy) |
| 4 | `Conference Start Date` | Event start date (`YYYY-MM-DD`) |
| 5 | `Conference End Date` | Event end date (`YYYY-MM-DD`) |
| 6 | `Speakers` | Keynote & featured speakers list |
| 7 | `Speaker Titles / Companies` | Designations and organizations of speakers |
| 8 | `Venue` | Convention center, hall, or hotel |
| 9 | `City` | USA City (San Francisco, New York, Austin, Chicago, etc.) |
| 10 | `Country` | Verified as `USA` |
| 11 | `Organizer` | Host association or corporate organizer |
| 12 | `Official Conference URL` | Primary conference homepage |
| 13 | `Registration URL` | Direct ticketing / registration link |
| 14 | `Source URL` | Listing page on 10times, Luma, Eventbrite, etc. |
| 15 | `Publication Date` | Date published to Excel (**exactly 2 days before event**) |

---

## 🚀 Quick Start Guide

### 1. Environment Configuration

In `backend/.env`:
```ini
# PostgreSQL Connection
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/conference_db

# Gemini AI Key (from https://aistudio.google.com/)
GEMINI_API_KEY=your_gemini_api_key

# Redis (optional; APScheduler runs automatically if Redis is inactive)
REDIS_URL=redis://localhost:6379/0

# Automation
SCRAPER_INTERVAL_MINUTES=720
REMINDER_DAYS_BEFORE=2
```

---

### 2. Run the Backend API & Scheduler

In PowerShell (with virtual environment active):

```powershell
cd c:\conference-agent\GeneralConferenceScraper

# Activate virtual environment
.\venv\Scripts\Activate.ps1

# Start FastAPI server on port 8000
python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

- **Swagger Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check**: [http://localhost:8000/api/health](http://localhost:8000/api/health)
- **Direct Excel Download**: [http://localhost:8000/api/excel/download](http://localhost:8000/api/excel/download)

---

### 3. Run the Frontend Dashboard

In a separate terminal:

```powershell
cd c:\conference-agent\GeneralConferenceScraper\conference-app

# Start Next.js development server
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

---

### 4. Run Automated End-to-End Test

To test the entire pipeline (scraping, AI validation, database insertion, 2-day reminder check, and Excel generation):

```powershell
python .\backend\test_pipeline.py
```
