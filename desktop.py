#!/usr/bin/env python
"""Desktop launcher for Pharmacy System.

Runs the Django application as a self-contained desktop program:

* stores the database, media and logs in a writable per-user data directory;
* generates and persists a unique SECRET_KEY on first run;
* applies migrations / collects static files / ensures an admin account exists;
* serves the app with the production-grade Waitress WSGI server on localhost;
* opens it in a native window (pywebview) or, failing that, the default browser.

Usage:
    python desktop.py
"""

import os
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "PharmacySystem"
HOST = "127.0.0.1"


def user_data_dir() -> Path:
    """Return a per-user, writable directory for application data."""
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_or_create_secret_key(data_dir: Path) -> str:
    key_file = data_dir / "secret_key.txt"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_urlsafe(64)
    key_file.write_text(key)
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return key


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def configure_environment() -> Path:
    data_dir = user_data_dir()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ["PHARMACY_DATA_DIR"] = str(data_dir)
    os.environ.setdefault("DJANGO_DEBUG", "false")
    os.environ.setdefault("DJANGO_SECRET_KEY", load_or_create_secret_key(data_dir))
    # Content zoom for the desktop window (Windows display scaling makes the
    # native window render larger than a browser). Lower = smaller; "1" = off.
    # Change this default to your preferred size, e.g. "0.7" or "0.8".
    os.environ.setdefault("PHARMACY_ZOOM", "0.75")
    return data_dir


def wait_until_serving(url: str, timeout: float = 20.0) -> bool:
    import urllib.error
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except urllib.error.HTTPError:
            return True  # server responded (e.g. 302 to login)
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    return False


def ensure_std_streams(data_dir: Path) -> None:
    """Give the process valid stdout/stderr when launched without a console.

    A windowed build (PyInstaller console=False, or pythonw.exe) sets
    sys.stdout/sys.stderr to None, so any print() or Django management-command
    output raises ``'NoneType' object has no attribute 'write'``. Redirect them
    to a log file so output is captured instead of crashing.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        stream = open(
            data_dir / "desktop-console.log", "a", encoding="utf-8", buffering=1
        )
    except Exception:
        import io

        stream = io.StringIO()
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def main() -> int:
    data_dir = configure_environment()
    ensure_std_streams(data_dir)

    import django

    django.setup()

    from django.core.management import call_command

    # First-run / every-run setup: migrate, collect static, ensure admin.
    call_command("init_app")

    port = find_free_port()
    url = f"http://{HOST}:{port}/"

    from config.wsgi import application
    from waitress import serve

    server = threading.Thread(
        target=serve,
        args=(application,),
        kwargs={"host": HOST, "port": port, "threads": 8, "_quiet": True},
        daemon=True,
    )
    server.start()

    if not wait_until_serving(url):
        print("Error: the application server did not start.", file=sys.stderr)
        return 1

    print(f"Pharmacy System is running. Data directory: {data_dir}")
    print(f"Open {url} if a window does not appear.")

    # Prefer a native desktop window; fall back to the default web browser.
    try:
        import webview  # pywebview

        # --- Window size & behaviour -------------------------------------
        # width/height : the window's restored (non-maximized) size in pixels.
        # min_size     : smallest the user can shrink it to (keeps layout intact).
        # maximized    : True  -> open filling the screen (recommended for POS).
        # fullscreen   : True  -> borderless kiosk mode (no title bar / controls).
        # resizable    : False -> lock the window to a fixed size.
        # Tweak the values below to taste.
        webview.create_window(
            "Pharmacy System",
            url,
            width=1280,
            height=820,
            min_size=(1024, 700),
            resizable=True,
            maximized=True,
            fullscreen=False,
        )
        # Note: content scaling/zoom is handled server-side by
        # core.middleware.DesktopZoomMiddleware (driven by PHARMACY_ZOOM), so it
        # applies reliably to every page without depending on JS timing.

        webview.start()
    except Exception:
        import webbrowser

        webbrowser.open(url)
        print("Press Ctrl+C to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    return 0


def _report_fatal_error(exc: BaseException) -> None:
    """Surface a startup crash even though the windowed build has no console.

    Writes a crash file next to the data directory and, on Windows, shows a
    native message box so the operator sees something went wrong.
    """
    import traceback

    details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        crash_path = user_data_dir() / "startup-error.log"
        crash_path.write_text(details)
        location = str(crash_path)
    except Exception:
        location = "(could not write crash log)"

    message = (
        "Pharmacy System failed to start.\n\n"
        f"{exc}\n\nDetails were written to:\n{location}"
    )
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Pharmacy System", 0x10)
        except Exception:
            pass
    print(message, file=sys.stderr)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - last-resort startup guard
        _report_fatal_error(exc)
        raise SystemExit(1)
