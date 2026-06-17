@echo off
REM Launch Pharmacy System as a desktop app (Windows).
REM Creates the virtualenv and installs dependencies on first run.
REM Requires Python 3.10+ (3.12 recommended).
setlocal
cd /d "%~dp0"

REM Prefer the newest installed Python via the py launcher; fall back to python.
set "PY=py -3"
%PY% -c "import sys" >nul 2>&1
if errorlevel 1 set "PY=python"

if not exist ".venv\" (
    echo Creating virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 ( echo Failed to create venv. Install Python 3.10+. & pause & exit /b 1 )
    .venv\Scripts\python -m pip install --upgrade pip
    .venv\Scripts\python -m pip install -r requirements.txt
    if errorlevel 1 ( echo Core dependency install failed. & pause & exit /b 1 )
    REM Native window is best-effort; app falls back to the browser without it.
    .venv\Scripts\python -m pip install "pywebview>=5.0"
    if errorlevel 1 ( echo Note: pywebview unavailable - app will open in browser. )
)

.venv\Scripts\python desktop.py
endlocal
