# Pharmacy System

A pharmacy management system (inventory, point-of-sale, purchases, suppliers,
customers, reporting) built with Django. It runs as a normal web application for
development and can also run as a self-contained **desktop application**.

## Features

- **POS** with FIFO batch deduction, discounts, credit sales and refunds
- **Inventory** tracking by batch with expiry handling and an audit log of stock movements
- **Purchases** and **suppliers** with payment tracking
- **Customers** with credit balances and payment history
- **Reports**: dead stock, loss/expiry, sales and profit
- **Role-based access** (Admin / Pharmacist); superusers are treated as admins

## Requirements

- Python 3.10+
- Node.js (only if you want to rebuild the Tailwind CSS; a prebuilt
  `static/css/output.css` is included)

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python manage.py migrate
python manage.py createsuperuser     # or: python manage.py init_app
python manage.py runserver
```

Open http://127.0.0.1:8000/.

### Configuration (environment variables)

The same code runs in development and in a packaged build. Behaviour is
controlled by environment variables (all optional in development):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_DEBUG` | `true` | Set to `false` for production/desktop builds |
| `DJANGO_SECRET_KEY` | insecure dev key | Required for any real deployment |
| `DJANGO_ALLOWED_HOSTS` | localhost only | Comma-separated extra hosts |
| `PHARMACY_DATA_DIR` | project dir | Where the DB, media and logs are written |
| `PHARMACY_ADMIN_USERNAME` / `PHARMACY_ADMIN_PASSWORD` | `admin` / `admin` | First-run admin created by `init_app` |

`python manage.py init_app` is idempotent: it migrates, collects static files,
and creates an admin account if none exists. It is run automatically by the
desktop launcher.

## Running as a desktop app

The desktop launcher serves the app with the Waitress WSGI server on localhost
and opens it in a native window (via `pywebview`), falling back to the default
web browser if the native GUI libraries aren't available. The database, media
and logs are stored in a per-user data directory, so nothing is written inside
the application folder.

```bash
# Linux / macOS
./run_desktop.sh

# Windows
run_desktop.bat
```

On Linux the native window needs WebKitGTK system packages
(e.g. `sudo apt install gir1.2-webkit2-4.1 python3-gi`); without them it opens
in your browser instead.

Per-user data directory:

- Linux: `~/.local/share/PharmacySystem`
- macOS: `~/Library/Application Support/PharmacySystem`
- Windows: `%LOCALAPPDATA%\PharmacySystem`

### Building a standalone executable

Run on the OS you are targeting (PyInstaller does not cross-compile):

```bash
./build_desktop.sh        # Linux/macOS, uses desktop.spec
# result: dist/PharmacySystem
```

**Windows:** see the step-by-step [WINDOWS_DESKTOP_GUIDE.md](WINDOWS_DESKTOP_GUIDE.md)
for building a native, no-console, fully offline desktop app with a Desktop
icon (one command: `build_windows.ps1`).

## Running the tests

```bash
python manage.py test
```

A custom test runner (`config/test_runner.py`) makes discovery work with the
`apps/` layout, so a bare `python manage.py test` finds every app's tests.

## Project layout

```
config/         Django project (settings, urls, wsgi/asgi, test runner)
apps/           Feature apps (added to sys.path, imported by bare label)
templates/      Project-level templates
static/         Source static assets (Tailwind output, htmx, vendor JS)
desktop.py      Desktop launcher (Waitress + native window/browser)
desktop.spec    PyInstaller build spec
```
