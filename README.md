# Bethesda Labs – Lab Management Software (offline)

Desktop software for a blood-collection / pathology lab. It runs on the lab's own Windows PC, needs no internet, and keeps all data on that PC.

**Features**
- Patient registration and visits, with automatic Patient IDs and Visit/Sample numbers
- Referral tracking: Self / Doctor / Hospital, with doctor and hospital **commissions**, statements, paid/unpaid tracking and Excel export
- 56 common tests and 4 health packages, with prices and male/female reference ranges (all editable)
- Billing, discounts, part-payments and a receipt PDF
- Result entry with automatic High/Low flags
- **Report approval workflow**: the technician enters results, the doctor approves, and the report is **locked**. Corrections create an **amended version** with a reason; old versions are kept.
- PDF report with the lab **logo**, the pathologist's **signature**, results vs normal range, range bars and a summary of abnormal values. Unapproved reports print with a **DRAFT** watermark.
- **Logins** for the doctor/owner (full access) and technicians (no access to money, commissions or settings), with an **activity log** of who did what
- **Automatic daily backup** to this PC and to a USB drive or cloud folder, plus one-click restore
- **Licence key** with expiry and grace period. An expired licence only pauses *new* registrations; old data always stays available.
- Runs like a normal app: desktop icon, its own window, tray icon, starts with Windows

---

## A. Installing at the lab (Windows)

1. Get the installer `BethesdaLabs-Setup-x.y.z.exe` (see section D).
2. Double-click it. Windows may show **"Windows protected your PC"**, because the installer is not code-signed: click **More info → Run anyway**.
3. Keep both options ticked: **Desktop icon** and **Start automatically when Windows starts**. Auto-start keeps the daily backup running.
4. Bethesda Labs opens in its own window. Its icon (red drop) sits in the system tray near the clock. Right-click it for **Open / Back up now / Quit**.

The data lives in `C:\ProgramData\BethesdaLabs` and is **kept if the software is uninstalled or updated**.

**Updating:** run the newer installer over the old one. The data is untouched.

### First-time setup (inside the app)
1. Create the **doctor / owner** account. This name is printed as "approved by" on reports.
2. **Admin → Lab settings & logo**: lab name, address and pathologist, then upload the **logo** and **signature**. For the signature, sign on white paper, photograph it and crop it tightly.
3. **Admin → Backup & restore**: set the external folder (for example `E:\BethesdaBackup` on a USB drive that stays plugged in, or a Google Drive/OneDrive folder), then click **Back up now** to test it.
4. **Admin → Users**: add a login for each technician or receptionist.
5. **Hospitals / Doctors**: add referrers and their commission %.
6. **Tests**: check prices, and have the pathologist **verify every reference range** against the lab's analyser and reagent kit inserts.
7. **Admin → Licence**: install the licence file from the developer. A 30-day trial runs until then.

### Other PCs in the lab (optional)
Tick **Admin → Lab settings → Allow other computers…**, then restart the software (tray icon → Quit, then open it again). Other PCs open `http://<main-PC-IP>:5000` in Edge or Chrome. Allow the app through the Windows firewall if asked.

## B. Daily workflow
1. **+ New Visit**: patient, referral (Self / Doctor / Hospital), tests or package, discount, payment → **Receipt PDF**.
2. **Mark sample collected**.
3. Technician: **Enter results → Save & send for approval**.
4. Doctor: **Review & approve → Save & approve report**. The report is locked and the **Report PDF** is final.
5. Wrong value after approval? Doctor: **Amend report** (with a reason) → correct → approve again. This prints as "Amended report, Version 2"; version 1 stays in the history.
6. Doctor: **Commissions** → filter by month → pay → **Mark selected as paid** / **Export CSV**.

| | Doctor / Owner | Technician / Reception |
|---|---|---|
| Register patients, billing, receipts | ✔ | ✔ |
| Enter results, send for approval | ✔ | ✔ |
| Approve / amend reports | ✔ | ✖ |
| Commissions, doctors, hospitals, income figures | ✔ | ✖ |
| Change prices, tests, packages, settings, users, backup, licence | ✔ | ✖ |

## C. Backups and restore
- An automatic backup runs every day while the software is running, to `C:\ProgramData\BethesdaLabs\backups` **and** the external folder. The last 30 are kept in each.
- The dashboard shows a red warning if a backup has not worked for 2 days (for example, the USB drive was unplugged).
- **Admin → Backup & restore → Restore**: pick a backup and type `RESTORE`. A safety copy of the current data is saved first.
- Take the USB drive home once a week.
- **Monthly check message**: copy it from the Backup page and send it on WhatsApp as your monthly support update.

---

## D. For the developer

### Build the Windows installer
**Automatically (recommended):** every push to GitHub runs **Actions → Build Windows installer**. Open the run and download **BethesdaLabs-Windows-Installer** under *Artifacts*. Pushing a tag such as `v1.1.0` also attaches the installer to a GitHub Release.

**On a Windows PC:** install Python 3.12 and [Inno Setup 6](https://jrsoftware.org/isinfo.php), then double-click `packaging\build_windows.bat`.

### Licences (one-time setup, on YOUR computer)
```bash
pip install -r requirements.txt
python tools/make_licence.py init
```
This creates:
- `~/.bethesda/licence_private.pem`, your **secret** signing key. **Back it up** to a USB drive. Never share or commit it; if you lose it, you cannot issue licences for existing installs.
- `bethesda/licence_pubkey.pem`. **Commit and push it** so the next installer has licensing switched on. Builds without it have licensing off.

For each lab or renewal, read the **Computer ID** from the lab's *Admin → Licence* page and run:
```bash
python tools/make_licence.py issue --lab "Bethesda Labs" --expires 2027-01-31 --machine ABCD-1234-EF56-7890
```
Send the `.lic` file (or its text) to the lab and install it under *Admin → Licence*. `--grace 30` (the default) is the number of days after expiry before new registrations pause. Leave out `--machine` to allow any PC.

### Run from source (Mac / Linux / development)
```bash
./start_mac_linux.sh          # or: python run.py   (--lan, --port 8080, --no-tray)
```
When run from source, data is stored in `./data/`.

### Project layout
```
run.py / packaging/BethesdaLabs.py   start the app (launcher: server + window + tray + backups)
bethesda/app.py          screens and business logic
bethesda/security.py     logins, roles, CSRF protection, activity log
bethesda/backup.py       automatic backup, restore
bethesda/licence.py      licence check (Ed25519 signatures)
bethesda/pdf_report.py   report and receipt PDFs
bethesda/db.py           database schema, upgrades, settings
bethesda/catalog.py      default tests, ranges, packages
packaging/               PyInstaller recipe, Inno Setup installer, icon, build script
tools/make_licence.py    developer licence tool
```
