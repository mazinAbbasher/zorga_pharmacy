#!/usr/bin/env bash
# Build a standalone Zorga Pharmacy executable with PyInstaller.
# Run on the OS you want to target (PyInstaller does not cross-compile).
set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -r requirements-desktop.txt

echo "Collecting static files..."
DJANGO_SETTINGS_MODULE=config.settings "$VENV/bin/python" manage.py collectstatic --noinput

echo "Building executable..."
"$VENV/bin/pyinstaller" --noconfirm desktop.spec

echo
echo "Done. Executable is in: dist/ZorgaPharmacy"
