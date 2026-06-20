"""Compute a stable, per-machine hardware fingerprint (the "Machine ID").

The Machine ID is a short, human-friendly hash derived from identifiers that
are unique to one computer and stable across reboots. Copying the program to a
different laptop produces a different Machine ID, so a license signed for the
original machine no longer matches.

Windows is the production target. Linux/macOS paths exist so the app (and the
test suite) run during development.

Note on stability: the Machine ID changes if Windows is reinstalled or the
system disk is reformatted/replaced. That is expected — such a machine needs a
fresh license. It does *not* change on normal updates, reboots, or renaming the
PC.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
import uuid


def _windows_machine_guid() -> str:
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Cryptography",
        0,
        winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
    ) as key:
        value, _ = winreg.QueryValueEx(key, "MachineGuid")
        return str(value).strip()


def _windows_volume_serial(root: str = "C:\\") -> str:
    import ctypes

    serial = ctypes.c_uint(0)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root), None, 0, ctypes.byref(serial), None, None, None, 0
    )
    return f"{serial.value:08X}" if ok else ""


def _raw_identity() -> str:
    """Return a raw, platform-specific identity string (pre-hash)."""
    if sys.platform.startswith("win"):
        guid = _windows_machine_guid()
        try:
            volume = _windows_volume_serial()
        except Exception:
            volume = ""
        return f"WINv1|{guid}|{volume}"

    if sys.platform == "darwin":
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"], text=True
        )
        for line in out.splitlines():
            if "IOPlatformUUID" in line:
                return "MACv1|" + line.split('"')[-2]
        return "MACv1|" + hex(uuid.getnode())

    # Linux / other: the systemd machine-id is per-installation and stable.
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, encoding="utf-8") as handle:
                value = handle.read().strip()
            if value:
                return f"LINUXv1|{value}"
        except OSError:
            continue
    return f"GENERICv1|{uuid.getnode():012x}|{platform.node()}"


def _format(digest_hex: str) -> str:
    """Take the first 20 hex chars and group them as XXXX-XXXX-XXXX-XXXX-XXXX."""
    head = digest_hex.upper()[:20]
    return "-".join(head[i : i + 4] for i in range(0, 20, 4))


def machine_id() -> str:
    """Return this machine's fingerprint, e.g. ``A1B2-C3D4-E5F6-7890-1234``.

    Falls back to an unmistakable error token if hardware identifiers cannot be
    read, so the gate fails closed rather than matching an empty value.
    """
    try:
        raw = _raw_identity()
    except Exception:
        raw = ""
    if not raw:
        return "ERROR-NOID-0000-0000-0000"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return _format(digest)
