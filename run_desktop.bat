@echo off
REM Launch Zorga Pharmacy as a desktop app (Windows).
REM Creates the virtualenv and installs dependencies on first run.
setlocal
cd /d "%~dp0"

if not exist ".venv\" (
    echo Creating virtual environment...
    python -m venv .venv
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\pip install -r requirements-desktop.txt
)

.venv\Scripts\python desktop.py
endlocal
