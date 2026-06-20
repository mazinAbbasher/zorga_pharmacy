"""License gate: decide whether the app is allowed to run on this machine.

Flow used by the desktop launcher:

    from licensing import gate
    if gate.is_enforced():
        ok, mid, license_path, reason = gate.check(data_dir)
        if not ok and not gate.run_activation(mid, license_path, data_dir):
            return  # refuse to start

Licensing is only enforced in the packaged build (``sys.frozen``). Running from
source during development is never gated, so there is no environment-variable
"off switch" an end user could flip in the shipped product.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from . import _rsa
from .fingerprint import machine_id
from .public_key import PUBLIC_KEY_E, PUBLIC_KEY_N

LICENSE_FILENAME = "license.key"


def is_enforced() -> bool:
    """True only in a frozen (PyInstaller) build."""
    return bool(getattr(sys, "frozen", False))


def license_path_for(data_dir: Path) -> Path:
    return Path(data_dir) / LICENSE_FILENAME


def _canonical_payload(obj: dict) -> bytes:
    """Bytes that were signed: the license object minus its signature."""
    payload = {k: v for k, v in obj.items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_bytes(raw: bytes, current_id: str) -> tuple[bool, str]:
    """Validate raw license-file bytes against *current_id*.

    Returns ``(ok, reason)`` where reason is one of: ok, corrupt,
    invalid_signature, wrong_machine.
    """
    try:
        obj = json.loads(raw.decode("utf-8"))
        signature = base64.b64decode(obj["signature"])
    except Exception:
        return False, "corrupt"
    if not _rsa.verify((PUBLIC_KEY_N, PUBLIC_KEY_E), _canonical_payload(obj), signature):
        return False, "invalid_signature"
    if obj.get("machine_id") != current_id:
        return False, "wrong_machine"
    return True, "ok"


def verify_file(path: Path, current_id: str) -> tuple[bool, str]:
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return False, "missing"
    return verify_bytes(raw, current_id)


def check(data_dir: Path) -> tuple[bool, str, Path, str]:
    """Return ``(ok, machine_id, license_path, reason)`` for *data_dir*."""
    current_id = machine_id()
    path = license_path_for(data_dir)
    ok, reason = verify_file(path, current_id)
    return ok, current_id, path, reason


def install_license(raw: bytes, license_path: Path, current_id: str) -> tuple[bool, str]:
    """Validate *raw* license bytes and, if valid, save them to *license_path*."""
    ok, reason = verify_bytes(raw, current_id)
    if ok:
        Path(license_path).write_bytes(raw)
    return ok, reason


# --------------------------------------------------------------------------
# Activation UI shown when no valid license is present.
# --------------------------------------------------------------------------
def run_activation(current_id: str, license_path: Path, data_dir: Path) -> bool:
    """Show the activation screen. Return True if a valid license now exists.

    Also writes ``machine-id.txt`` next to the data dir so the operator can
    easily email the Machine ID to you.
    """
    try:
        (Path(data_dir) / "machine-id.txt").write_text(current_id + "\n", encoding="utf-8")
    except OSError:
        pass

    if _run_activation_webview(current_id, license_path):
        return True
    return _run_activation_fallback(current_id, license_path, data_dir)


def _run_activation_webview(current_id: str, license_path: Path) -> bool:
    """Native window with the Machine ID, a copy button and a license picker."""
    try:
        import webview
    except Exception:
        return False

    state = {"activated": False}

    class _Api:
        def get_machine_id(self) -> str:
            return current_id

        def browse_and_activate(self) -> dict:
            window = webview.windows[0]
            selection = window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("License files (*.key;*.json)", "All files (*.*)"),
            )
            if not selection:
                return {"ok": False, "reason": "no_file"}
            try:
                raw = Path(selection[0]).read_bytes()
            except OSError:
                return {"ok": False, "reason": "unreadable"}
            ok, reason = install_license(raw, license_path, current_id)
            state["activated"] = ok
            return {"ok": ok, "reason": reason}

        def finish(self) -> None:
            webview.windows[0].destroy()

    try:
        webview.create_window(
            "Pharmacy System — Activation",
            html=_ACTIVATION_HTML,
            js_api=_Api(),
            width=640,
            height=560,
            resizable=False,
        )
        webview.start()
    except Exception:
        return False
    return state["activated"]


def _run_activation_fallback(current_id: str, license_path: Path, data_dir: Path) -> bool:
    """No pywebview: tell the operator the ID and where to drop the license."""
    message = (
        "Pharmacy System is not activated on this computer.\n\n"
        f"Machine ID:\n    {current_id}\n\n"
        "Send this Machine ID to your vendor to receive a license file.\n"
        f"Save the file you receive as 'license.key' in:\n    {data_dir}\n"
        f"(The Machine ID is also saved there in 'machine-id.txt'.)\n\n"
        "Then start Pharmacy System again."
    )
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "Pharmacy System", 0x40)
        except Exception:
            print(message, file=sys.stderr)
    else:
        print(message, file=sys.stderr)
    # Re-check in case the operator dropped the file in before dismissing.
    ok, _ = verify_file(license_path, current_id)
    return ok


_ACTIVATION_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  * { box-sizing: border-box; }
  body { font-family: "Segoe UI", system-ui, sans-serif; margin: 0;
         background: #0f172a; color: #e2e8f0; padding: 32px; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  p  { color: #94a3b8; line-height: 1.5; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px;
          padding: 20px; margin-top: 16px; }
  .id { font-family: Consolas, monospace; font-size: 22px; letter-spacing: 2px;
        color: #38bdf8; user-select: all; word-break: break-all; }
  button { background: #2563eb; color: #fff; border: 0; border-radius: 8px;
           padding: 10px 16px; font-size: 14px; cursor: pointer; margin-top: 10px; }
  button.secondary { background: #334155; }
  button:hover { filter: brightness(1.1); }
  ol { color: #94a3b8; line-height: 1.7; padding-left: 20px; }
  #status { margin-top: 12px; font-weight: 600; min-height: 20px; }
  .ok { color: #4ade80; } .err { color: #f87171; }
</style>
</head>
<body>
  <h1>Activate Pharmacy System</h1>
  <p>This program runs on one computer only. Send the Machine ID below to your
     vendor, then load the license file you receive.</p>

  <div class="card">
    <p style="margin:0 0 6px">Your Machine ID</p>
    <div class="id" id="mid">…</div>
    <button class="secondary" onclick="copyId()">Copy Machine ID</button>
  </div>

  <div class="card">
    <ol>
      <li>Send your Machine ID to the vendor.</li>
      <li>Save the <b>license.key</b> file they send you.</li>
      <li>Click below and select that file.</li>
    </ol>
    <button onclick="activate()">Load license file…</button>
    <div id="status"></div>
  </div>

<script>
  async function load() {
    document.getElementById('mid').textContent = await window.pywebview.api.get_machine_id();
  }
  function copyId() {
    const t = document.getElementById('mid').textContent;
    navigator.clipboard && navigator.clipboard.writeText(t);
    setStatus('Copied to clipboard.', 'ok');
  }
  function setStatus(msg, cls) {
    const s = document.getElementById('status');
    s.textContent = msg; s.className = cls || '';
  }
  async function activate() {
    setStatus('Checking…', '');
    const r = await window.pywebview.api.browse_and_activate();
    if (r.ok) {
      setStatus('Activated! Starting Pharmacy System…', 'ok');
      setTimeout(() => window.pywebview.api.finish(), 900);
    } else {
      const messages = {
        no_file: 'No file selected.',
        unreadable: 'Could not read that file.',
        corrupt: 'That file is not a valid license.',
        invalid_signature: 'This license is not genuine.',
        wrong_machine: 'This license was issued for a different computer.'
      };
      setStatus(messages[r.reason] || ('Activation failed: ' + r.reason), 'err');
    }
  }
  window.addEventListener('pywebviewready', load);
  load();
</script>
</body>
</html>"""
