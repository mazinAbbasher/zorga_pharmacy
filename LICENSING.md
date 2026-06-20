# Machine-locked licensing

The desktop build runs **only on a laptop you have activated**. Copying the
built `PharmacySystem` folder to another computer produces a different *Machine
ID*, so the license you signed no longer matches and the app refuses to start.

How it works: the app computes a hardware fingerprint (Windows `MachineGuid` +
system-disk volume serial). It only runs if it finds a `license.key` that was
**cryptographically signed for that exact Machine ID** using your private key.
Only you hold the private key, so only you can issue (or move) a license.

## One-time setup (do this once, on your machine)

```bash
python tools/gen_keys.py
```

This creates:

| File | Keep / ship? |
| --- | --- |
| `private_key.json` | **SECRET.** Back it up. Never commit or ship it. (git-ignored) |
| `licensing/public_key.py` | Public key, embedded in the app. Commit & ship it. |

> ⚠️ If you lose `private_key.json` you can no longer issue licenses, and
> regenerating keys invalidates every license already in the field. Back it up
> somewhere safe (e.g. a password manager).

Then build as usual (`pyinstaller desktop.spec` / `build_windows.ps1`).

## Activating a client's laptop

1. The client installs and opens Pharmacy System. Because it isn't activated,
   an **Activation** screen appears showing their **Machine ID**
   (e.g. `A1B2-C3D4-E5F6-7890-1234`). They send you that ID.
2. On your machine, sign a license for it:

   ```bash
   python tools/sign_license.py --machine-id A1B2-C3D4-E5F6-7890-1234 \
       --name "Zorga Pharmacy - Branch 1"
   ```

   This writes `Zorga_Pharmacy_-_Branch_1-license.key`.
3. Send that file to the client. On the activation screen they click
   **"Load license file…"** and select it. The app activates and starts.

   *(Manual fallback: if the activation window can't open, the app shows the
   Machine ID in a dialog and the client drops the file, renamed to
   `license.key`, into `%LOCALAPPDATA%\PharmacySystem\`. The Machine ID is also
   saved there as `machine-id.txt`.)*

## When does a client need re-activation?

The Machine ID is stable across reboots, updates, and PC renames. It changes
(and a new license is needed) only if Windows is reinstalled or the system disk
is reformatted/replaced. Just sign a new license for the new Machine ID.

## Running from source

Licensing is enforced **only in the packaged (PyInstaller) build**. Running
`python desktop.py` from source is never gated, so development is unaffected.
There is deliberately no environment-variable off-switch in the shipped app.

## What this does and doesn't protect against

- ✅ **Stops casual copying** — the exact scenario of copying the built folder
  (or the whole data directory) to another laptop and reusing it.
- ✅ **Licenses can't be forged or rebound** without your private key, even by
  someone who fully unpacks the program.
- ⚠️ **Not tamper-proof against a skilled reverse-engineer.** A PyInstaller
  bundle can be unpacked and the Python check patched out. If you need to raise
  that bar, options are: compile the check into a C extension, obfuscate the
  bytecode (e.g. PyArmor), or move activation to an online license server.
  Ask and I can add one of these.
