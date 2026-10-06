@echo off
title Conference Discovery & Teams Agent Engine
echo ======================================================================
echo    Starting Conference Discovery & Teams Webhook Agent Engine
echo ======================================================================
echo.

cd /d "%~dp0"

echo [1/2] Launching Backend Server (FastAPI + Background Scheduler)...
start "Conference Backend (FastAPI)" cmd /k "venv\Scripts\activate && python -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8001 --reload"

echo [2/2] Launching Frontend Web Dashboard (Next.js)...
start "Conference Dashboard (Next.js)" cmd /k "cd conference-app && npm run dev"

echo.
echo ======================================================================
echo  [SUCCESS] All systems active!
echo  - Backend & Auto Scheduler: http://localhost:8001
echo  - Frontend Dashboard:        http://localhost:3000
echo.
echo  The 24/7 background scheduler automatically triggers immediately
echo  on startup to discover 2-day-ahead conferences, update Excel,
echo  send emails, and dispatch Teams cards with ZERO manual interaction.
echo ======================================================================
