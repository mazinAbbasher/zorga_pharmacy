"""Database backup & restore for the desktop (SQLite) build.

Everything here uses only the Python standard library and Django's own
connection settings, so it keeps working inside the packaged Windows binary
after the source tree is deleted.

Design notes
------------
* **Consistent snapshots.** Backups are produced with SQLite's online backup
  API (``sqlite3.Connection.backup``), not a plain file copy, so a backup taken
  while the app is running is never half-written or corrupt.

* **Windows-safe restore.** On Windows the live ``db.sqlite3`` is locked by the
  running server's connections and cannot be overwritten in place. So a restore
  is *staged*: the chosen backup is written to ``pending_restore.sqlite3`` and
  the actual swap happens at the next startup, in :func:`apply_pending_restore`,
  before Django opens any connection. The user just restarts the app.

* **Automatic backups.** :func:`auto_backup_on_startup` runs from ``init_app``
  on every launch, de-duplicated by time so opening the app repeatedly in one
  day doesn't pile up copies, and old automatic backups are pruned.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection, connections

# ---------------------------------------------------------------------------
# Locations & naming
# ---------------------------------------------------------------------------

#: Backups older than this many hours are the trigger point for a new automatic
#: backup on startup (prevents piling up copies when the app is reopened a lot).
AUTO_BACKUP_MIN_INTERVAL_HOURS = 12

#: How many backups of each kind to keep. User "manual" backups are kept
#: forever (they're deliberate); automatic and pre-restore safety copies are
#: capped so the folder can't grow without bound.
RETENTION = {
    "auto": 15,
    "pre-restore": 5,
    "manual": None,  # keep all
}

_TS_FORMAT = "%Y%m%d-%H%M%S"
_NAME_RE = re.compile(r"^(auto|manual|pre-restore)-(\d{8}-\d{6})\.sqlite3$")


def db_path() -> Path:
    """Absolute path to the live SQLite database file."""
    return Path(connection.settings_dict["NAME"])


def backups_dir() -> Path:
    """Directory that holds backup files, created on demand."""
    path = Path(settings.DATA_DIR) / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pending_restore_path() -> Path:
    """Staging file consumed by :func:`apply_pending_restore` at startup."""
    return Path(settings.DATA_DIR) / "pending_restore.sqlite3"


def _timestamp() -> str:
    return datetime.now().strftime(_TS_FORMAT)


# ---------------------------------------------------------------------------
# Creating backups
# ---------------------------------------------------------------------------

def _snapshot(source: Path, dest: Path) -> None:
    """Write a consistent copy of the SQLite DB at *source* to *dest*.

    Uses the online backup API so it is safe even while the app is writing.
    """
    src_conn = sqlite3.connect(str(source), timeout=30)
    try:
        dest_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()


def create_backup(kind: str = "manual") -> Path:
    """Create a new consistent backup and return its path.

    ``kind`` is one of ``manual``, ``auto`` or ``pre-restore`` and controls both
    the filename prefix and the retention policy applied afterwards.
    """
    if kind not in RETENTION:
        raise ValueError(f"unknown backup kind: {kind!r}")

    dest = backups_dir() / f"{kind}-{_timestamp()}.sqlite3"
    # Flush any pending writes on Django's own connection first so the snapshot
    # includes the very latest committed data.
    connection.ensure_connection()
    _snapshot(db_path(), dest)
    prune_backups(kind)
    return dest


# ---------------------------------------------------------------------------
# Listing / pruning
# ---------------------------------------------------------------------------

def _parse(name: str):
    """Return ``(kind, datetime)`` for a backup filename, or ``None``."""
    match = _NAME_RE.match(name)
    if not match:
        return None
    kind, ts = match.groups()
    try:
        return kind, datetime.strptime(ts, _TS_FORMAT)
    except ValueError:
        return None


def list_backups():
    """Return backups newest-first as dicts: name, kind, created, size_bytes."""
    items = []
    for entry in backups_dir().glob("*.sqlite3"):
        parsed = _parse(entry.name)
        if not parsed:
            continue
        kind, created = parsed
        try:
            size = entry.stat().st_size
        except OSError:
            continue
        items.append(
            {
                "name": entry.name,
                "kind": kind,
                "created": created,
                "size_bytes": size,
            }
        )
    items.sort(key=lambda i: i["created"], reverse=True)
    return items


def prune_backups(kind: str) -> None:
    """Delete the oldest backups of *kind* beyond its retention limit."""
    keep = RETENTION.get(kind)
    if keep is None:
        return
    same_kind = [b for b in list_backups() if b["kind"] == kind]  # newest first
    for backup in same_kind[keep:]:
        try:
            (backups_dir() / backup["name"]).unlink()
        except OSError:
            pass


def resolve_backup(name: str) -> Path:
    """Return the safe, validated path to a backup named *name*.

    Guards against path traversal: only bare filenames matching the backup
    naming scheme that actually live in the backups directory are accepted.
    """
    if not _NAME_RE.match(name or ""):
        raise ValueError("invalid backup name")
    path = (backups_dir() / name).resolve()
    if path.parent != backups_dir().resolve() or not path.is_file():
        raise ValueError("backup not found")
    return path


def delete_backup(name: str) -> None:
    resolve_backup(name).unlink()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_sqlite(path: Path) -> None:
    """Raise ``ValueError`` unless *path* is a usable Pharmacy database.

    Checks the SQLite header, runs a quick integrity check, and confirms the
    file actually looks like this application's database (has the Django tables)
    so a user can't accidentally restore an unrelated file.
    """
    path = Path(path)
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError("The file is empty or does not exist.")

    with open(path, "rb") as fh:
        if fh.read(16) != b"SQLite format 3\x00":
            raise ValueError("This is not a valid SQLite database file.")

    conn = sqlite3.connect(str(path))
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise ValueError("The database file is corrupted (integrity check failed).")
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        conn.close()

    if "django_migrations" not in tables:
        raise ValueError(
            "This does not look like a Pharmacy System database backup."
        )


# ---------------------------------------------------------------------------
# Restore (staged) — applied at next startup
# ---------------------------------------------------------------------------

def stage_restore(source: Path) -> None:
    """Validate *source* and stage it to be restored on the next startup.

    Does not touch the live database, so it is safe to call while the app is
    running (including on Windows, where the live file is locked).
    """
    source = Path(source)
    validate_sqlite(source)
    # Copy (not move) so an uploaded temp file or an existing local backup both
    # work and the original is left intact.
    shutil.copyfile(source, pending_restore_path())


def _remove_sidecars(base: Path) -> None:
    """Delete SQLite -wal/-shm/-journal sidecar files next to *base*."""
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(str(base) + suffix)
        if sidecar.exists():
            try:
                sidecar.unlink()
            except OSError:
                pass


def apply_pending_restore() -> bool:
    """If a staged restore exists, swap it into place. Return True if applied.

    Must run at startup *before* any database connection is opened. Safely
    snapshots the current database to a ``pre-restore`` backup first, then
    replaces the live file. If the staged file turns out to be invalid it is
    quarantined and the current database is left untouched.
    """
    pending = pending_restore_path()
    if not pending.exists():
        return False

    live = db_path()
    try:
        validate_sqlite(pending)
    except ValueError:
        # Don't destroy a good database with a bad staged file; set it aside.
        pending.rename(pending.with_suffix(".sqlite3.invalid"))
        return False

    # Make sure nothing holds the live file open before we replace it.
    connections.close_all()

    # Safety copy of what's about to be overwritten (best effort).
    if live.exists():
        try:
            dest = backups_dir() / f"pre-restore-{_timestamp()}.sqlite3"
            _snapshot(live, dest)
            prune_backups("pre-restore")
        except Exception:
            pass

    _remove_sidecars(live)
    shutil.move(str(pending), str(live))
    _remove_sidecars(live)
    return True


# ---------------------------------------------------------------------------
# Automatic backup on startup
# ---------------------------------------------------------------------------

def latest_backup_time():
    """Datetime of the most recent backup of any kind, or ``None``."""
    backups = list_backups()
    return backups[0]["created"] if backups else None


def auto_backup_on_startup() -> Path | None:
    """Create an automatic backup unless a recent one already exists.

    Called once per launch from ``init_app``. Returns the new backup's path, or
    ``None`` if a backup was made recently enough to skip. Never raises — a
    backup failure must not stop the app from starting.
    """
    try:
        if not db_path().exists():
            return None
        newest = latest_backup_time()
        if newest is not None:
            age_hours = (datetime.now() - newest).total_seconds() / 3600
            if age_hours < AUTO_BACKUP_MIN_INTERVAL_HOURS:
                return None
        return create_backup("auto")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
