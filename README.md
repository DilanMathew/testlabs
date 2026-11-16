# Bethesda Labs – Lab Management (runs offline on your computer)

A local application for a blood-collection / pathology lab:

- **Patient registration and visits** with auto-generated Patient IDs (`P-YYYYMMDD-0001`) and Visit/Sample numbers (`BL-YYYYMMDD-0001`)
- **Referral tracking** for every visit: *Self / Walk-in*, *Referred by Doctor*, or *Referred by Hospital* (optionally with the treating doctor)
- **Commissions**: a % per doctor and per hospital, calculated on the net bill and editable per visit. Includes statements per doctor/hospital, mark paid/unpaid, and CSV export for Excel
- **Test catalog** of 56 common tests in 8 categories (Haematology, Coagulation, Diabetes, Biochemistry, Cardiac, Hormones, Immunology/Serology, Clinical Pathology) with parameters, units, prices and male/female reference ranges, plus 4 health packages. All of it is editable
- **Billing**: packages and individual tests, discount, part-payment, balance due, payment mode, and a receipt PDF
- **Result entry**: values turn red (high) or blue (low) as you type
- **PDF report**: each actual value next to its reference (safe) range, H/L flags, a colour bar showing where the result falls, a summary of out-of-range values, and pathologist signature lines
- **Dashboard**: daily visits, billing, collections, pending reports, patient dues and unpaid commissions
- **One-click backup** of the database

Everything is stored in one file, `data/bethesda.db`, on your computer. No internet is needed.

---

## 1. Install (one time)

1. Install **Python 3.10 or newer** from <https://www.python.org/downloads/>.
   *Windows:* tick **"Add Python to PATH"** during installation.
2. Download this project (GitHub → **Code → Download ZIP**) and unzip it, for example to `C:\BethesdaLabs`.

## 2. Start the application

- **Windows:** double-click **`start_windows.bat`**
- **Mac / Linux:** open Terminal in the folder and run `./start_mac_linux.sh`

The first start takes about a minute because it installs the requirements. After that it starts in seconds and opens your browser at **http://127.0.0.1:5000**.
Keep the black console window open while you work, and close it to stop the app.

> Tip (Windows): right-click `start_windows.bat` → *Send to → Desktop (create shortcut)* to get a desktop icon.

### Use it from several computers in the lab
Run `start_windows.bat --lan` (or `./start_mac_linux.sh --lan`) on the main PC. Other PCs on the same Wi-Fi/LAN can then open `http://<main-PC-IP>:5000`. Allow Python through the Windows firewall when Windows asks.

## 3. First-time setup (inside the app)

1. **Settings**: lab name, address, phone, pathologist name and qualification, report footer, currency.
2. **Hospitals** → add the hospitals/clinics that refer patients, with their commission %.
3. **Doctors** → add the referring doctors, with their commission % and, optionally, their hospital.
4. **Tests**: check prices and **verify every reference range against your analyser/reagent kit inserts**. The defaults are typical adult values.
5. **Packages**: adjust or add health packages.

## 4. Daily workflow

1. **+ New Visit**: enter the patient (or find a returning patient under *Patients → New visit*), choose how they came (Self / Doctor / Hospital), tick the tests or a package, add any discount and the amount paid, then **Register visit**. Print the **Receipt PDF** if needed.
2. Collect the sample → **Mark sample collected**.
3. When the analysis is done → **Enter results** → **Save & mark report completed**.
4. **Report PDF**: print it, or save it and send it to the patient or doctor.
5. **Commissions**: filter by month and doctor/hospital, review the statement, pay, then select the rows → **Mark selected as paid**. Use **Export CSV** to open it in Excel.

## 5. Backups (important)

Go to **Settings → Download backup now** at the end of every day and copy the file to a USB drive or a cloud folder.
To restore, stop the app and replace `data/bethesda.db` with a backup file (rename it to `bethesda.db`).

## 6. Good to know

- Reports keep a snapshot of the reference range used at the time. Editing the catalog later does not change reports you have already issued.
- Removing a parameter that has been used in past results only hides it for new results, so old reports stay intact.
- Patient data is confidential. The `data/` folder is excluded from git, so never upload it anywhere.

## Project layout

```
run.py                   starts the app (python run.py [--lan] [--port 5000])
bethesda/app.py          all screens / business logic
bethesda/db.py           database schema, settings, numbering
bethesda/catalog.py      default test list, reference ranges, packages
bethesda/pdf_report.py   PDF report + receipt
bethesda/ranges.py       range / H-L flag logic
bethesda/templates/      HTML pages
data/bethesda.db         your data (created on first run)
```
