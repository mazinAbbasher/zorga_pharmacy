import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from core import backup
from core.decorators import admin_only


@login_required
@admin_only
def index(request):
    backups = [
        {**b, "size": backup.human_size(b["size_bytes"])}
        for b in backup.list_backups()
    ]
    context = {
        "backups": backups,
        "db_size": backup.human_size(
            backup.db_path().stat().st_size if backup.db_path().exists() else 0
        ),
        "auto_keep": backup.RETENTION["auto"],
    }
    return render(request, "settings_app/index.html", context)


@login_required
@admin_only
@require_POST
def backup_download(request):
    """Create a fresh manual backup, keep a local copy, and download it."""
    try:
        path = backup.create_backup("manual")
    except Exception as exc:  # noqa: BLE001 - surface any failure to the user
        messages.error(request, f"Backup failed: {exc}")
        return redirect("settings_app:index")

    response = FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=path.name,
        content_type="application/x-sqlite3",
    )
    return response


@login_required
@admin_only
def backup_download_existing(request, name):
    """Download a backup that already exists in the local backups folder."""
    try:
        path = backup.resolve_backup(name)
    except ValueError:
        messages.error(request, "That backup could not be found.")
        return redirect("settings_app:index")
    return FileResponse(
        open(path, "rb"),
        as_attachment=True,
        filename=path.name,
        content_type="application/x-sqlite3",
    )


@login_required
@admin_only
@require_POST
def backup_delete(request, name):
    try:
        backup.delete_backup(name)
        messages.success(request, "Backup deleted.")
    except (ValueError, OSError):
        messages.error(request, "That backup could not be deleted.")
    return redirect("settings_app:index")


@login_required
@admin_only
@require_POST
def restore(request):
    """Stage a restore from an uploaded file or an existing local backup.

    The actual database swap happens on the next startup (Windows-safe), so we
    validate and stage here, then ask the user to restart.
    """
    source = request.FILES.get("backup_file")
    existing_name = request.POST.get("existing")

    try:
        if source:
            # Write the upload to a temp file so backup.stage_restore can
            # validate it as a real file before we accept it.
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=".sqlite3"
            ) as tmp:
                for chunk in source.chunks():
                    tmp.write(chunk)
                tmp_path = Path(tmp.name)
            try:
                backup.stage_restore(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)
        elif existing_name:
            backup.stage_restore(backup.resolve_backup(existing_name))
        else:
            messages.error(request, "Please choose a backup file to restore.")
            return redirect("settings_app:index")
    except ValueError as exc:
        messages.error(request, f"Restore rejected: {exc}")
        return redirect("settings_app:index")
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"Restore failed: {exc}")
        return redirect("settings_app:index")

    messages.success(
        request,
        "Backup accepted. Close and reopen the application to complete the "
        "restore — a safety copy of the current data is saved automatically.",
    )
    return redirect("settings_app:index")
