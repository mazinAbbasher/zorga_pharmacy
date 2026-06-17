# Build Zorga Pharmacy into a standalone Windows desktop app and place a
# shortcut on the Desktop. Run this in PowerShell from the project folder:
#
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
#
# Produces: dist\ZorgaPharmacy\ZorgaPharmacy.exe  (no console window)
# and a "Zorga Pharmacy" shortcut on your Desktop.
#
# Requires Python 3.10 or newer (3.12 recommended).

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Stop immediately if the last external program (pip, pyinstaller, ...) failed.
# ($ErrorActionPreference only covers PowerShell cmdlets, not .exe exit codes.)
function Assert-LastExit($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." }
}

# Invoke an interpreter described as a string array (e.g. @('py','-3.12') or
# @('python')) with extra arguments, splatting safely for any length.
function Invoke-Py($cmd, [string[]]$rest) {
    if ($cmd.Count -gt 1) {
        $pre = $cmd[1..($cmd.Count - 1)]
        & $cmd[0] @pre @rest
    } else {
        & $cmd[0] @rest
    }
}

# Find a Python 3.10+ interpreter. Tries the 'py' launcher first so a freshly
# installed 3.12 is used even if an old 'python' is still on PATH.
function Find-Python {
    $candidates = @(
        @("py", "-3.13"), @("py", "-3.12"), @("py", "-3.11"), @("py", "-3.10"),
        @("py", "-3"), @("python")
    )
    foreach ($c in $candidates) {
        try {
            $v = Invoke-Py $c @("-c", "import sys;print('%d.%d' % sys.version_info[:2])") 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) {
                $p = $v.Trim().Split('.')
                if ([int]$p[0] -eq 3 -and [int]$p[1] -ge 10) {
                    Write-Host ("    using '" + ($c -join ' ') + "' -> Python " + $v.Trim()) -ForegroundColor DarkGray
                    return , $c
                }
            }
        } catch { }
    }
    return $null
}

Write-Host "==> Looking for Python 3.10+ ..." -ForegroundColor Cyan
$py = Find-Python
if (-not $py) {
    Write-Host ""
    Write-Host "ERROR: No Python 3.10+ found." -ForegroundColor Red
    Write-Host "This project needs Python 3.10 or newer (3.12 recommended)."
    Write-Host "Install it from https://www.python.org/downloads/windows/"
    Write-Host "and tick 'Add python.exe to PATH', then run this script again."
    exit 1
}

$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

# Recreate the virtual environment if missing or built with an old Python.
$recreate = $true
if (Test-Path $venvPy) {
    $vv = & $venvPy -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and $vv) {
        $p = $vv.Trim().Split('.')
        if ([int]$p[0] -eq 3 -and [int]$p[1] -ge 10) { $recreate = $false }
    }
    if ($recreate) {
        Write-Host "==> Existing .venv uses an old Python; recreating..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force ".venv"
    }
}

if ($recreate) {
    Write-Host "==> Creating virtual environment..." -ForegroundColor Cyan
    Invoke-Py $py @("-m", "venv", ".venv")
    Assert-LastExit "Creating virtual environment"
}

Write-Host "==> Installing dependencies (this can take a few minutes)..." -ForegroundColor Cyan
& $venvPy -m pip install --upgrade pip
Assert-LastExit "pip upgrade"
& $venvPy -m pip install -r requirements-desktop.txt
Assert-LastExit "Installing requirements"

Write-Host "==> Collecting static files..." -ForegroundColor Cyan
$env:DJANGO_SETTINGS_MODULE = "config.settings"
& $venvPy manage.py collectstatic --noinput
Assert-LastExit "collectstatic"

Write-Host "==> Building executable with PyInstaller..." -ForegroundColor Cyan
& $venvPy -m PyInstaller --noconfirm desktop.spec
Assert-LastExit "PyInstaller build"

$exePath = Join-Path $PSScriptRoot "dist\ZorgaPharmacy\ZorgaPharmacy.exe"
if (-not (Test-Path $exePath)) {
    throw "Build finished but $exePath was not created."
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
