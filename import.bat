@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Error: failed to create virtual environment. Is Python installed?
        exit /b 1
    )
)

.venv\Scripts\pip install -q -r requirements.txt

if not exist ".env" (
    if exist ".env.example" (
        echo Error: .env not found. Creating from .env.example...
        copy .env.example .env >nul
        echo Edit .env with your paths, then re-run this script.
    ) else (
        echo Error: .env not found.
    )
    exit /b 1
)

.venv\Scripts\python src\import.py %*
set IMPORT_EXIT=%ERRORLEVEL%

if "%~1"=="list" exit /b %IMPORT_EXIT%

set SAVE_NAME=%~1

if %IMPORT_EXIT% neq 0 (
    .venv\Scripts\python src\update_status.py "%SAVE_NAME%" failed import
    exit /b %IMPORT_EXIT%
)

set FAILED_STEPS=

.venv\Scripts\python src\analytics.py %*
if errorlevel 1 set FAILED_STEPS=!FAILED_STEPS! analytics

.venv\Scripts\python src\ratings.py %*
if errorlevel 1 set FAILED_STEPS=!FAILED_STEPS! ratings

.venv\Scripts\python src\draft_ratings.py %*
if errorlevel 1 set FAILED_STEPS=!FAILED_STEPS! draft_ratings

.venv\Scripts\python src\ifa_ratings.py %*
if errorlevel 1 set FAILED_STEPS=!FAILED_STEPS! ifa_ratings

if "!FAILED_STEPS!"=="" (
    .venv\Scripts\python src\update_status.py "%SAVE_NAME%" ok
) else (
    .venv\Scripts\python src\update_status.py "%SAVE_NAME%" partial !FAILED_STEPS!
)
