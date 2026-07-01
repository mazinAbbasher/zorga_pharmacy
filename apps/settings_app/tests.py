"""View-level tests for the Settings / Backup page."""

import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core import backup
from users.models import User


def _make_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE django_migrations (id INTEGER PRIMARY KEY, app TEXT)")
        conn.commit()
    finally:
        conn.close()


class SettingsBackupViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin", role="ADMIN", password="pw12345"
        )
        self.staff = User.objects.create_user(
            username="cashier", role="PHARMACIST", password="pw12345"
        )
        self.client = Client()

        self._tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self._tmp.name)
        self.live_db = self.data_dir / "db.sqlite3"
        _make_db(self.live_db)
        self._settings = override_settings(DATA_DIR=self.data_dir)
        self._settings.enable()
        self._db_patch = mock.patch.object(backup, "db_path", return_value=self.live_db)
        self._db_patch.start()

    def tearDown(self):
        self._db_patch.stop()
        self._settings.disable()
        self._tmp.cleanup()

    def test_index_requires_admin(self):
        # Non-admin is forbidden.
        self.client.login(username="cashier", password="pw12345")
        self.assertEqual(self.client.get(reverse("settings_app:index")).status_code, 403)

    def test_index_renders_for_admin(self):
        self.client.login(username="admin", password="pw12345")
        resp = self.client.get(reverse("settings_app:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Backup &amp; Restore")

    def test_download_creates_and_streams_backup(self):
        self.client.login(username="admin", password="pw12345")
        resp = self.client.post(reverse("settings_app:backup_download"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp["Content-Disposition"])
        # A copy was also kept locally.
        self.assertEqual(len(backup.list_backups()), 1)

    def test_restore_from_existing_stages_pending(self):
        made = backup.create_backup("manual")
        self.client.login(username="admin", password="pw12345")
        resp = self.client.post(
            reverse("settings_app:restore"), {"existing": made.name}, follow=True
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(backup.pending_restore_path().exists())

    def test_restore_rejects_bad_upload(self):
        self.client.login(username="admin", password="pw12345")
        bogus = tempfile.NamedTemporaryFile(suffix=".sqlite3")
        bogus.write(b"not a database")
        bogus.seek(0)
        resp = self.client.post(
            reverse("settings_app:restore"), {"backup_file": bogus}, follow=True
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(backup.pending_restore_path().exists())
