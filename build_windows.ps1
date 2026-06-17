# Build Pharmacy System into a standalone Windows desktop app and place a
# shortcut on the Desktop. Run this in PowerShell from the project folder:
#
#   powershell -ExecutionPolicy Bypass -File build_windows.ps1
#
# Produces: dist\ZorgaPharmacy\ZorgaPharmacy.exe  (no console window)
# and a "Pharmacy System" shortcut on your Desktop.
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
    # 'py -3' resolves to the newest installed Python, so it covers 3.14 and any
    # future version automatically. The explicit entries are fallbacks.
    $candidates = @(
        @("py", "-3"),
        @("py", "-3.14"), @("py", "-3.13"), @("py", "-3.12"),
        @("py", "-3.11"), @("py", "-3.10"),
        @("python")
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

# Recreate the virtual environment if missing, broken, or built with an old
# Python. A venv created by a since-removed Python (e.g. an old 3.9) has a dead
# python.exe stub, so probing it can error -- that must mean "recreate", not crash.
$recreate = $true
if (Test-Path $venvPy) {
    $vv = $null
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"
    try {
        $vv = & $venvPy -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
    } catch {
        $vv = $null
    }
    $ErrorActionPreference = $prevEAP

    if ($LASTEXITCODE -eq 0 -and $vv) {
        $p = $vv.Trim().Split('.')
        if ([int]$p[0] -eq 3 -and [int]$p[1] -ge 10) { $recreate = $false }
    }
    if ($recreate) {
        Write-Host "==> Existing .venv is old or broken; recreating..." -ForegroundColor Yellow
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

# Core app + build tool must succeed (these are well-supported everywhere).
& $venvPy -m pip install -r requirements.txt
Assert-LastExit "Installing core requirements"
& $venvPy -m pip install "pyinstaller>=6.0"
Assert-LastExit "Installing PyInstaller"

# Native-window backend is best-effort: on a brand-new Python it may not have a
# build yet. If it can't install, the app still works by opening in the browser.
$useNativeWindow = $true
& $venvPy -m pip install "pywebview>=5.0"
if ($LASTEXITCODE -ne 0) {
    $useNativeWindow = $false
    Write-Host ""
    Write-Host "WARNING: could not install 'pywebview' for this Python version." -ForegroundColor Yellow
    Write-Host "         The app will still build and run, but it will open in the" -ForegroundColor Yellow
    Write-Host "         default web browser instead of a native window." -ForegroundColor Yellow
    Write-Host "         For a native window, install Python 3.12 and re-run." -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "==> Collecting static files..." -ForegroundColor Cyan
$env:DJANGO_SETTINGS_MODULE = "config.settings"
& $venvPy manage.py collectstatic --noinput
Assert-LastExit "collectstatic"

Write-Host "==> Building executable with PyInstaller..." -ForegroundColor Cyan
& $venvPy -m PyInstaller --noconfirm desktop.spec
Assert-LastExit "PyInstaller build"

$exePath = Join-Path $PSScriptRoot "dist\PharmacySystem\PharmacySystem.exe"
if (-not (Test-Path $exePath)) {
    throw "Build finished but $exePath was not created."
}

Write-Host "==> Creating Desktop shortcut..." -ForegroundColor Cyan
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Pharmacy System.lnk"
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
Write-Host "You can copy the entire 'dist\PharmacySystem' folder to the client PC"
Write-Host "and double-click PharmacySystem.exe (or the Desktop shortcut)."
