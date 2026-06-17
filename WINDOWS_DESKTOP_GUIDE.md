# Pharmacy System — Windows Desktop Setup Guide

This guide turns the project into a **real Windows desktop application**: the
client double-clicks an icon, the app opens in its **own window** (not a web
browser), there is **no black terminal window**, and it works **completely
offline** (no internet needed, ever).

You will do this on a Windows laptop: clone the repo, build once, then either
use it on that machine or copy the result to the client's PC.

> **Important:** A Windows `.exe` can only be built **on Windows**. Do the build
> steps on a Windows machine (the laptop you mentioned is perfect).

---

## What the client gets

- A Desktop icon **"Pharmacy System"**.
- Double-click → the app opens in a clean native window.
- No terminal, no browser, no internet.
- All data (database, receipts, logs) is saved automatically on their PC in
  `C:\Users\<name>\AppData\Local\PharmacySystem`.

---

## Part 1 — One-time prerequisites (build laptop)

### 1.1 Install Python (3.10 or newer — required)
> **This project needs Python 3.10+ (3.12 recommended). Python 3.9 or older will
> NOT work** — Django 5.2 refuses to install on it, which is the cause of the
> `Could not find a version that satisfies the requirement Django` error.

1. Download Python from <https://www.python.org/downloads/windows/>
   (3.10–3.13 are the most battle-tested; 3.12 is the safest choice).
2. Run the installer and **tick "Add python.exe to PATH"** before clicking Install.
3. Verify in **PowerShell**:
   ```powershell
   py -3 --version
   ```
   You should see `Python 3.10` or newer. (The build script auto-detects the
   newest installed Python via the `py` launcher, so an older `python` left on
   PATH is fine — and if you previously ran the build with Python 3.9 it
   automatically discards that old `.venv` and rebuilds it.)

> **Using a brand-new Python (e.g. 3.14)?** It will work, but the packaging
> tools (`PyInstaller`, and the native-window library `pywebview`) sometimes
> don't have ready-made builds for a just-released Python yet. If `build_windows.ps1`
> fails while **installing dependencies** with an error like *"no matching
> distribution"* or a compiler error for `pywebview`/`pythonnet`, install
> **Python 3.12** instead and re-run — everything is verified to work there.

### 1.2 Install Git (to clone the repo)
- Download from <https://git-scm.com/download/win> and install with defaults.
- (Alternatively, download the repo as a ZIP and extract it.)

### 1.3 Microsoft Edge WebView2 Runtime (needed for the native window)
The native window uses Microsoft's **WebView2** engine.
- **Windows 11 and most updated Windows 10 PCs already have it** — you can skip this.
- To be safe for an offline client PC, download the **"Evergreen Standalone
  Installer"** once (while you have internet) from
  <https://developer.microsoft.com/microsoft-edge/webview2/> and copy it to a
  USB stick. Run it once on the client PC.
- If WebView2 is missing, the app still runs but opens in the default browser
  instead of a native window.

---

## Part 2 — Build the app (recommended)

This produces a self-contained folder. **Python is NOT required on the client PC.**

1. Open **PowerShell** and clone the repository:
   ```powershell
   git clone <your-repo-url> pharmacy_system
   cd pharmacy_system
   ```

2. Run the build script:
   ```powershell
   powershell -ExecutionPolicy Bypass -File build_windows.ps1
   ```
   This creates a virtual environment, installs everything, builds the app, and
   places a **"Pharmacy System"** shortcut on your Desktop. It takes a few minutes.

3. When it finishes you'll have:
   ```
   dist\PharmacySystem\PharmacySystem.exe   <- the application (no console)
   ```

4. **Test it:** double-click the Desktop shortcut (or the `.exe`). The app window
   should open. The first launch takes a few extra seconds to set up its database.

> **Windows SmartScreen** may warn that the app is from an unknown publisher
> (because it isn't code-signed). Click **More info → Run anyway**. This is
> normal for in-house apps. To remove the warning permanently you'd need a code
> signing certificate (optional).

### Deliver to the client PC
- Copy the **entire `dist\PharmacySystem` folder** to the client PC (USB stick or
  network). Put it somewhere stable, e.g. `C:\PharmacySystem`.
- Create a Desktop shortcut on the client PC: right-click `PharmacySystem.exe` →
  **Send to → Desktop (create shortcut)**, then rename it to "Pharmacy System".
- (Optional) Run the WebView2 installer from Part 1.3 if the window doesn't appear.

That's it — the client now double-clicks the icon and uses the system fully offline.

---

## Part 3 — Alternative: run without building (simplest, needs Python)

If the PyInstaller build gives you trouble, you can run the app directly. This
requires Python to be installed on the machine, but is very reliable.

1. Clone the repo and open PowerShell in the folder.
2. First-time setup:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements-desktop.txt
   ```
3. Create a **no-console** launcher shortcut:
   - Right-click on the Desktop → **New → Shortcut**.
   - For the location, paste (adjust the path to your folder):
     ```
     C:\path\to\pharmacy_system\.venv\Scripts\pythonw.exe C:\path\to\pharmacy_system\desktop.py
     ```
     `pythonw.exe` (with the **w**) runs with **no terminal window**.
   - Name it "Pharmacy System". Set **Start in** to the project folder.
   - (Optional) Right-click the shortcut → Properties → **Change Icon** to pick
     `static\icon.ico`.

Double-clicking that shortcut opens the app in its native window, fully offline.

---

## Part 4 — Make it look polished (optional)

### Add an app icon
1. Put an icon file at `static\icon.ico` **before** building (Part 2). PNG → ICO
   converters are available offline, or use any `.ico` you have.
2. The build script automatically uses it for the executable and the shortcut.

### Pin it / autostart
- **Pin to Taskbar/Start:** right-click the `.exe` → Pin to Start / Taskbar.
- **Start automatically at login:** press `Win + R`, type `shell:startup`, press
  Enter, and copy the "Pharmacy System" shortcut into that folder.

---

## Part 5 — First run & day-to-day use

- **First login:** username `admin`, password `admin`.
  **Change this password immediately** after the first sign-in (Users section).
  - To set different initial credentials, before first launch set environment
    variables `PHARMACY_ADMIN_USERNAME` and `PHARMACY_ADMIN_PASSWORD`.
- **Where data lives (client PC):**
  `C:\Users\<name>\AppData\Local\PharmacySystem`
  - `db.sqlite3` — all pharmacy data (drugs, sales, customers, ...)
  - `media\` — uploaded files
  - `pharmacy.log` — activity/error log
- **Backups:** simply copy `db.sqlite3` somewhere safe regularly (USB/network).
  To restore, copy it back into the same folder while the app is closed.

---

## Part 6 — Troubleshooting

| Symptom | Fix |
| --- | --- |
| App opens in a **browser** instead of a window | Install the WebView2 Runtime (Part 1.3). |
| Nothing happens / it closes immediately | Check `...\AppData\Local\PharmacySystem\startup-error.log` and `pharmacy.log`. |
| SmartScreen blocks it | **More info → Run anyway** (unsigned in-house app). |
| Antivirus quarantines the `.exe` | Add an exclusion for the `PharmacySystem` folder (common with PyInstaller apps). |
| `Could not find a version that satisfies the requirement Django==5.2.x` | Your Python is too old (e.g. 3.9). Install Python 3.10+ (Part 1.1), delete `.venv`, and re-run. |
| "python is not recognized" during build | Reinstall Python with **Add to PATH** ticked (Part 1.1). |
| Build error about a missing module | Run the build again; ensure `pip install -r requirements-desktop.txt` succeeded. |
| Forgot admin password | Delete `db.sqlite3` to reset to a fresh database (⚠️ erases all data), or ask a developer to reset it. |

---

## Quick reference

```powershell
# Build a distributable desktop app + Desktop shortcut
powershell -ExecutionPolicy Bypass -File build_windows.ps1

# Run directly during development (browser or window)
python desktop.py
```

Everything runs locally. **No internet connection is required at any point** once
Python (build machine) and, if needed, the WebView2 Runtime (client machine) are
installed.
