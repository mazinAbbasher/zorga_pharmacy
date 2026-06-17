# PyInstaller spec for the Zorga Pharmacy desktop app.
# Build with:  pyinstaller desktop.spec
#
# Produces a standalone executable that runs the Django app in a native window
# (or the default browser as a fallback). User data (database, media, logs) is
# stored outside the bundle in a per-user directory, so the read-only bundle is
# fine.

import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

PROJECT_DIR = os.path.abspath(os.getcwd())
APPS_DIR = os.path.join(PROJECT_DIR, "apps")

# App packages are importable by their bare label because apps/ is on sys.path.
APP_LABELS = [
    "core", "users", "drugs", "pos", "purchases", "inventory",
    "suppliers", "customers", "reports", "settings_app", "dashboard",
    "transactions",
]

# Apps are referenced as strings in INSTALLED_APPS, so PyInstaller can't infer
# them from imports — collect every submodule (models, admin, migrations, ...).
hiddenimports = ["config.settings", "config.wsgi", "config.urls", "config.test_runner"]
for label in APP_LABELS:
    hiddenimports += collect_submodules(label)
hiddenimports += collect_submodules("whitenoise")
hiddenimports += ["waitress", "widget_tweaks"]

# Bundle templates/static that live inside the app packages, plus the two
# project-level directories that aren't part of any package.
datas = []
for label in APP_LABELS:
    datas += collect_data_files(label, includes=["**/*.html", "**/*.txt"])
datas += [
    (os.path.join(PROJECT_DIR, "templates"), "templates"),
    (os.path.join(PROJECT_DIR, "static"), "static"),
]

# Native window backend (pywebview). On Windows this also pulls the WebView2 /
# pythonnet pieces it needs. Collected only if installed, so a browser-only
# build (without pywebview) still works.
binaries = []
try:
    from PyInstaller.utils.hooks import collect_all

    _w_datas, _w_binaries, _w_hidden = collect_all("webview")
    datas += _w_datas
    binaries += _w_binaries
    hiddenimports += _w_hidden
except Exception:
    pass

a = Analysis(
    ["desktop.py"],
    pathex=[PROJECT_DIR, APPS_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Optional custom icon: drop a file at static/icon.ico to brand the executable.
_icon = os.path.join(PROJECT_DIR, "static", "icon.ico")
icon = _icon if os.path.exists(_icon) else None

# One-dir build: faster startup and far fewer antivirus false positives than a
# one-file bundle. console=False => no terminal window (true native app).
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ZorgaPharmacy",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="ZorgaPharmacy",
)
