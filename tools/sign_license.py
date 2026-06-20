#!/usr/bin/env python
"""Issue a license for one client machine.

A client opens the app on a new computer, sees their Machine ID on the
activation screen, and sends it to you. You run:

    python tools/sign_license.py --machine-id A1B2-C3D4-E5F6-7890-1234 \\
        --name "Zorga Pharmacy - Branch 1"

This writes a `license.key` file. Send it to the client; they load it from the
activation screen (or drop it into their data folder). It works only on the
machine whose ID you signed.

Requires private_key.json (created by tools/gen_keys.py).
"""

import argparse
import base64
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from licensing import _rsa  # noqa: E402
from licensing.gate import _canonical_payload  # noqa: E402

PRIVATE_KEY_FILE = ROOT / "private_key.json"
MACHINE_ID_RE = re.compile(r"^[0-9A-F]{4}(-[0-9A-F]{4}){4}$")


def main() -> int:
    parser = argparse.ArgumentParser(description="Sign a per-machine license.")
    parser.add_argument("--machine-id", required=True, help="ID from the client's activation screen")
    parser.add_argument("--name", default="", help="Client / branch name (recorded in the license)")
    parser.add_argument("--out", default="", help="Output path (default: <name>-license.key)")
    args = parser.parse_args()

    machine_id = args.machine_id.strip().upper()
    if not MACHINE_ID_RE.match(machine_id):
        print(f"Error: '{machine_id}' is not a valid Machine ID "
              "(expected XXXX-XXXX-XXXX-XXXX-XXXX, hex).", file=sys.stderr)
        return 2

    if not PRIVATE_KEY_FILE.exists():
        print(f"Error: {PRIVATE_KEY_FILE} not found. Run tools/gen_keys.py first.",
              file=sys.stderr)
        return 2
    key = json.loads(PRIVATE_KEY_FILE.read_text(encoding="utf-8"))

    license_obj = {
        "version": 1,
        "machine_id": machine_id,
        "issued_to": args.name,
        "issued_at": dt.date.today().isoformat(),
    }
    signature = _rsa.sign(key, _canonical_payload(license_obj))
    license_obj["signature"] = base64.b64encode(signature).decode("ascii")

    out = Path(args.out) if args.out else ROOT / (
        (re.sub(r"[^A-Za-z0-9_-]+", "_", args.name) + "-" if args.name else "")
        + "license.key"
    )
    out.write_text(json.dumps(license_obj, indent=2), encoding="utf-8")
    print(f"Signed license for {machine_id} -> {out}")
    print("Send this file to the client.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
