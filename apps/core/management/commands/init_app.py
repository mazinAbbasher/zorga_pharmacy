"""Prepare the application for use.

Idempotent first-run setup used by the desktop launcher (and handy in any
deployment): applies database migrations, collects static files, and ensures an
administrator account exists. Safe to run on every startup.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Migrate the database, collect static files, and ensure an admin user exists."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-collectstatic",
            action="store_true",
            help="Do not run collectstatic (useful in development).",
        )

    def handle(self, *args, **options):
        # A staged restore must be swapped in before any DB connection is opened
        # (migrate below is the first one), so this comes first.
        from core import backup

        if backup.apply_pending_restore():
            self.stdout.write(self.style.WARNING("Restored database from staged backup."))

        self.stdout.write("Applying database migrations...")
        call_command("migrate", interactive=False, verbosity=1)

        if not options["skip_collectstatic"]:
            self.stdout.write("Collecting static files...")
            call_command("collectstatic", interactive=False, verbosity=0)

        self._ensure_admin()

        # Automatic safety backup (no-op if a recent one already exists).
        if backup.auto_backup_on_startup():
            self.stdout.write("Saved an automatic database backup.")

    def _ensure_admin(self):
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            return

        username = os.environ.get("PHARMACY_ADMIN_USERNAME", "admin")
        password = os.environ.get("PHARMACY_ADMIN_PASSWORD", "admin")
        email = os.environ.get("PHARMACY_ADMIN_EMAIL", "admin@example.com")

        user = User.objects.create_superuser(
            username=username, email=email, password=password
        )
        # Mark as ADMIN role too so the role-based UI/permissions line up.
        if hasattr(user, "role"):
            user.role = "ADMIN"
            user.save(update_fields=["role"])

        self.stdout.write(
            self.style.WARNING(
                f"Created initial administrator '{username}'. "
                "Please sign in and change the password immediately."
            )
        )
