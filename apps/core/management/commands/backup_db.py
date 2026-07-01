"""Create a database backup from the command line.

Handy for scheduled backups (e.g. Windows Task Scheduler) or manual use:

    python manage.py backup_db

The backup is written to ``<data dir>/backups`` alongside the ones the app
makes automatically.
"""

from django.core.management.base import BaseCommand

from core import backup


class Command(BaseCommand):
    help = "Create a consistent backup of the database in the backups folder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--kind",
            choices=["manual", "auto"],
            default="manual",
            help="Backup kind, which controls retention (default: manual).",
        )

    def handle(self, *args, **options):
        path = backup.create_backup(options["kind"])
        size = backup.human_size(path.stat().st_size)
        self.stdout.write(self.style.SUCCESS(f"Backup created: {path} ({size})"))
