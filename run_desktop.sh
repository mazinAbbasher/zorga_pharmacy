#!/usr/bin/env bash
# Launch Zorga Pharmacy as a desktop app (Linux/macOS).
# Creates the virtualenv and installs dependencies on first run.
set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --upgrade pip >/dev/null
    # Use the desktop extras (native window). Falls back to the browser if the
    # system WebKitGTK libraries are missing.
    "$VENV/bin/pip" install -r requirements-desktop.txt
fi

exec "$VENV/bin/python" desktop.py
