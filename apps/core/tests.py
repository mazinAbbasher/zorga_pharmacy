"""Tests for the database backup/restore machinery (core.backup).

The live database is in-memory during tests, so these tests build real SQLite
files in a temp directory and point ``backup.db_path`` at them. That exercises
the actual snapshot/restore code paths without touching the test DB.
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from core import backup


def _make_db(path: Path, marker: str = "seed") -> None:
    """Create a minimal but valid Pharmacy-looking SQLite database file."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT)")
        conn.execute("CREATE TABLE marker (value TEXT)")
        conn.execute("INSERT INTO marker (value) VALUES (?)", (marker,))
        conn.commit()
    finally:
        conn.close()


def _read_marker(path: Path) -> str:
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT value FROM marker").fetchone()[0]
    finally:
        conn.close()


class BackupCoreTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.live_db = self.data_dir / "db.sqlite3"
        _make_db(self.live_db, marker="live")

        # Route all backup paths into the temp data dir and at our fake live DB.
        self._settings = override_settings(DATA_DIR=self.data_dir)
        self._settings.enable()
        self._db_patch = mock.patch.object(backup, "db_path", return_value=self.live_db)
        self._db_patch.start()

    def tearDown(self):
        self._db_patch.stop()
        self._settings.disable()
        self._tmp.cleanup()

    # -- creation / listing / retention -----------------------------------

    def test_create_backup_produces_valid_readable_copy(self):
        path = backup.create_backup("manual")
        self.assertTrue(path.exists())
        self.assertTrue(path.name.startswith("manual-"))
        backup.validate_sqlite(path)  # must not raise
        self.assertEqual(_read_marker(path), "live")

    def test_list_backups_sorted_newest_first_with_kind(self):
        a = backup.create_backup("auto")
        # Force a later timestamp so ordering is unambiguous.
        b = a.with_name("manual-20990101-000000.sqlite3")
        b.write_bytes(a.read_bytes())
        listed = backup.list_backups()
        self.assertEqual(listed[0]["name"], b.name)
        self.assertEqual(listed[0]["kind"], "manual")
        self.assertIn("auto", {i["kind"] for i in listed})

    def test_prune_keeps_only_retention_limit_for_auto(self):
        from datetime import datetime, timedelta

        keep = backup.RETENTION["auto"]
        bdir = self.data_dir / "backups"
        bdir.mkdir(exist_ok=True)
        base = datetime(2024, 1, 1)
        for i in range(keep + 5):
            ts = (base + timedelta(minutes=i)).strftime(backup._TS_FORMAT)
            (bdir / f"auto-{ts}.sqlite3").write_bytes(b"SQLite format 3\x00")
        backup.prune_backups("auto")
        autos = [b for b in backup.list_backups() if b["kind"] == "auto"]
        self.assertEqual(len(autos), keep)

    def test_manual_backups_are_never_pruned(self):
        self.assertIsNone(backup.RETENTION["manual"])

    # -- validation --------------------------------------------------------

    def test_validate_rejects_non_sqlite(self):
        bad = self.data_dir / "bad.sqlite3"
        bad.write_text("this is not a database")
        with self.assertRaises(ValueError):
            backup.validate_sqlite(bad)

    def test_validate_rejects_foreign_sqlite(self):
        foreign = self.data_dir / "foreign.sqlite3"
        conn = sqlite3.connect(str(foreign))
        conn.execute("CREATE TABLE something (x INTEGER)")
        conn.commit()
        conn.close()
        with self.assertRaises(ValueError):
            backup.validate_sqlite(foreign)

    def test_resolve_backup_blocks_path_traversal(self):
        with self.assertRaises(ValueError):
            backup.resolve_backup("../db.sqlite3")
        with self.assertRaises(ValueError):
            backup.resolve_backup("evil.txt")

    # -- restore (staged) --------------------------------------------------

    def test_stage_and_apply_restore_swaps_db_and_keeps_safety_copy(self):
        # A different backup we want to restore to.
        other = self.data_dir / "other.sqlite3"
        _make_db(other, marker="restored")

        backup.stage_restore(other)
        self.assertTrue(backup.pending_restore_path().exists())
        # Live DB untouched until applied.
        self.assertEqual(_read_marker(self.live_db), "live")

        applied = backup.apply_pending_restore()
        self.assertTrue(applied)
        self.assertFalse(backup.pending_restore_path().exists())
        # Live DB now holds the restored data...
        self.assertEqual(_read_marker(self.live_db), "restored")
        # ...and a pre-restore safety copy of the old data exists.
        pre = [b for b in backup.list_backups() if b["kind"] == "pre-restore"]
        self.assertEqual(len(pre), 1)
        self.assertEqual(_read_marker(self.data_dir / "backups" / pre[0]["name"]), "live")

    def test_apply_pending_restore_noop_when_nothing_staged(self):
        self.assertFalse(backup.apply_pending_restore())

    def test_invalid_staged_file_is_quarantined_not_applied(self):
        pending = backup.pending_restore_path()
        pending.write_text("garbage, not a database")
        self.assertFalse(backup.apply_pending_restore())
        # Live DB is untouched and the bad file is set aside.
        self.assertEqual(_read_marker(self.live_db), "live")
        self.assertFalse(pending.exists())
        self.assertTrue(pending.with_suffix(".sqlite3.invalid").exists())

    # -- auto backup -------------------------------------------------------

    def test_auto_backup_skips_when_recent_backup_exists(self):
        first = backup.auto_backup_on_startup()
        self.assertIsNotNone(first)
        # A second immediate call should be de-duplicated (too recent).
        self.assertIsNone(backup.auto_backup_on_startup())
