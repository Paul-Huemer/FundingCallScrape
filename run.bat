@echo off
rem Funding Radar
rem   run.bat          -> open the dashboard
rem   run.bat update   -> fetch the newest calls now (5-7 min), then open the dashboard
rem The shared GitHub Pages version updates itself every Monday (see .github/workflows/update.yml).
cd /d "%~dp0"
if /i "%~1"=="update" (
  python -m scraper.main --fresh
  if errorlevel 1 (
    echo Update failed - see messages above.
    pause
    exit /b 1
  )
)
start "" "%~dp0dashboard\index.html"
