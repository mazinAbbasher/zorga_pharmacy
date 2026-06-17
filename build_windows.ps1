# Build Zorga Pharmacy into a standalone Windows desktop app and place a
# shortcut on the Desktop. Run this in PowerShell from the project folder:
#
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
#
# Produces: dist\ZorgaPharmacy\ZorgaPharmacy.exe  (no console window)
# and a "Zorga Pharmacy" shortcut on your Desktop.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "==> Checking Python..." -ForegroundColor Cyan
python --version

if (-not (Test-Path ".venv")) {
    Write-Host "==> Creating virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
}

Write-Host "==> Installing dependencies (this can take a few minutes)..." -ForegroundColor Cyan
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements-desktop.txt

Write-Host "==> Collecting static files..." -ForegroundColor Cyan
$env:DJANGO_SETTINGS_MODULE = "config.settings"
.\.venv\Scripts\python manage.py collectstatic --noinput

Write-Host "==> Building executable with PyInstaller..." -ForegroundColor Cyan
.\.venv\Scripts\pyinstaller --noconfirm desktop.spec

$exePath = Join-Path $PSScriptRoot "dist\ZorgaPharmacy\ZorgaPharmacy.exe"
if (-not (Test-Path $exePath)) {
    throw "Build failed: $exePath was not created."
}

Write-Host "==> Creating Desktop shortcut..." -ForegroundColor Cyan
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Zorga Pharmacy.lnk"
$wsh = New-Object -ComObject WScript.Shell
$shortcut = $wsh.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $exePath
$shortcut.WorkingDirectory = Split-Path $exePath
$iconPath = Join-Path $PSScriptRoot "static\icon.ico"
if (Test-Path $iconPath) { $shortcut.IconLocation = $iconPath }
$shortcut.Save()

Write-Host ""
Write-Host "Done!" -ForegroundColor Green
Write-Host "App:      $exePath"
Write-Host "Shortcut: $shortcutPath"
Write-Host ""
Write-Host "You can copy the entire 'dist\ZorgaPharmacy' folder to the client PC"
Write-Host "and double-click ZorgaPharmacy.exe (or the Desktop shortcut)."
