import os
import secrets
import sqlite3
import sys
from datetime import datetime

from flask import g

from . import catalog

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_data_dir():
    """Source checkout -> ./data. Installed app -> a shared, writable system folder."""
    if not getattr(sys, "frozen", False):
        return os.path.join(BASE_DIR, "data")
    if os.name == "nt":
        return os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "BalajiXRays")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/BalajiXRays")
    return os.path.expanduser("~/.balajixrays")


DATA_DIR = os.environ.get("BETHESDA_DATA_DIR") or _default_data_dir()
DB_PATH = os.path.join(DATA_DIR, "bethesda.db")
BRANDING_DIR = os.path.join(DATA_DIR, "branding")
LOCAL_BACKUP_DIR = os.path.join(DATA_DIR, "backups")

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS hospitals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT, phone TEXT, email TEXT, contact_person TEXT,
    commission_pct REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS doctors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    qualification TEXT, specialization TEXT, registration_no TEXT,
    phone TEXT, email TEXT,
    hospital_id INTEGER REFERENCES hospitals(id),
    commission_pct REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'General',
    sample_type TEXT,
    price REAL NOT NULL DEFAULT 0,
    fasting INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS parameters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_id INTEGER NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    unit TEXT,
    ref_low REAL, ref_high REAL,
    ref_low_f REAL, ref_high_f REAL,
    ref_text TEXT,
    normal_value TEXT,
    options TEXT,
    sort_order INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price REAL NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS package_tests (
    package_id INTEGER NOT NULL REFERENCES packages(id) ON DELETE CASCADE,
    test_id INTEGER NOT NULL REFERENCES tests(id),
    PRIMARY KEY (package_id, test_id)
);

CREATE TABLE IF NOT EXISTS patients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_no TEXT UNIQUE,
    name TEXT NOT NULL,
    age INTEGER,
    age_unit TEXT NOT NULL DEFAULT 'Years',
    gender TEXT,
    phone TEXT, email TEXT, address TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_no TEXT UNIQUE,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    visit_date TEXT NOT NULL,
    referral_type TEXT NOT NULL DEFAULT 'Self',      -- Self | Doctor | Hospital
    doctor_id INTEGER REFERENCES doctors(id),
    hospital_id INTEGER REFERENCES hospitals(id),
    gross_amount REAL NOT NULL DEFAULT 0,
    discount REAL NOT NULL DEFAULT 0,
    net_amount REAL NOT NULL DEFAULT 0,
    paid_amount REAL NOT NULL DEFAULT 0,
    payment_mode TEXT,
    doctor_commission_pct REAL NOT NULL DEFAULT 0,
    doctor_commission REAL NOT NULL DEFAULT 0,
    doctor_commission_paid_on TEXT,
    hospital_commission_pct REAL NOT NULL DEFAULT 0,
    hospital_commission REAL NOT NULL DEFAULT 0,
    hospital_commission_paid_on TEXT,
    status TEXT NOT NULL DEFAULT 'Registered',       -- Registered | Sample Collected | Completed
    sample_collected_at TEXT,
    reported_at TEXT,
    clinical_notes TEXT,
    remarks TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS visit_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    package_id INTEGER NOT NULL REFERENCES packages(id),
    name TEXT NOT NULL,
    price REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS visit_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    test_id INTEGER NOT NULL REFERENCES tests(id),
    visit_package_id INTEGER REFERENCES visit_packages(id),
    price REAL NOT NULL DEFAULT 0
);

-- Results keep a snapshot of the unit / reference range used at the time,
-- so editing the catalog later never changes an already-issued report.
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    parameter_id INTEGER NOT NULL REFERENCES parameters(id),
    value TEXT,
    unit TEXT,
    ref_low REAL, ref_high REAL, ref_text TEXT, normal_value TEXT,
    flag TEXT,                                       -- '', 'L', 'H', 'A' (abnormal)
    UNIQUE (visit_id, parameter_id)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'technician',          -- admin | technician
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    last_login TEXT,
    created_at TEXT NOT NULL
);

-- Every approved report is frozen here; corrections create a new version.
CREATE TABLE IF NOT EXISTS report_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id INTEGER NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    sections_json TEXT NOT NULL,
    remarks TEXT,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    amend_reason TEXT,
    UNIQUE (visit_id, version)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    username TEXT,
    action TEXT NOT NULL,
    details TEXT
);

CREATE INDEX IF NOT EXISTS ix_visits_date ON visits(visit_date);
CREATE INDEX IF NOT EXISTS ix_audit_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS ix_visits_patient ON visits(patient_id);
"""

DEFAULT_SETTINGS = {
    "lab_name": "Balaji X Rays",
    "lab_tagline": "X-Ray & Diagnostic Laboratory",
    "lab_address": "Address line, City - PIN",
    "lab_phone": "+91 00000 00000",
    "lab_email": "info@balajixrays.example",
    "pathologist_name": "Dr. Pathologist Name",
    "pathologist_qualification": "MD (Pathology)",
    "technician_name": "",
    "currency": "Rs.",
    "report_footer": "Results relate only to the sample tested. Please correlate clinically. "
                     "Reference ranges are for adults unless stated otherwise.",
    "default_doctor_commission": "10",
    "default_hospital_commission": "15",
    "backup_dir": "",            # external folder: USB drive or a cloud-synced folder
    "backup_keep": "30",         # number of daily backups kept in each folder
    "allow_lan": "0",            # 1 = other PCs on the lab network may connect
}

# Columns added after the first release; added automatically to older databases.
MIGRATIONS = {
    "visits": {
        "approved_by": "TEXT",
        "approved_at": "TEXT",
        "report_version": "INTEGER NOT NULL DEFAULT 0",
        "amend_reason": "TEXT",
        "created_by": "TEXT",
    },
}


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def migrate(conn):
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, decl in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def secret_key():
    """Random per-installation key for signing login sessions."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, "secret.key")
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    migrate(conn)
    conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('installed_on', ?)", (now()[:10],))
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))
    if conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0] == 0:
        seed_catalog(conn)
    conn.commit()
    conn.close()


def seed_catalog(conn):
    for code, name, cat, sample, price, fasting, params in catalog.TESTS:
        cur = conn.execute(
            "INSERT INTO tests(code, name, category, sample_type, price, fasting) VALUES (?,?,?,?,?,?)",
            (code, name, cat, sample, price, fasting))
        tid = cur.lastrowid
        for i, (pname, unit, lo, hi, lof, hif, text, normal, options) in enumerate(params):
            conn.execute(
                """INSERT INTO parameters(test_id, name, unit, ref_low, ref_high, ref_low_f, ref_high_f,
                                          ref_text, normal_value, options, sort_order)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (tid, pname, unit, lo, hi, lof, hif, text, normal, options, i))
    for code, name, price, test_codes in catalog.PACKAGES:
        cur = conn.execute("INSERT INTO packages(code, name, price) VALUES (?,?,?)", (code, name, price))
        pid = cur.lastrowid
        for tc in test_codes:
            row = conn.execute("SELECT id FROM tests WHERE code=?", (tc,)).fetchone()
            if row:
                conn.execute("INSERT OR IGNORE INTO package_tests VALUES (?,?)", (pid, row[0]))


def set_setting(key, value, conn=None):
    (conn or get_db()).execute(
        "INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value))


def get_settings(conn=None):
    rows = (conn or get_db()).execute("SELECT key, value FROM settings").fetchall()
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in rows})
    return s


def next_number(prefix, table, column):
    """Sequential numbers like BL-20261116-0001 (resets daily)."""
    day = datetime.now().strftime("%Y%m%d")
    stem = f"{prefix}-{day}-"
    row = get_db().execute(
        f"SELECT {column} FROM {table} WHERE {column} LIKE ? ORDER BY {column} DESC LIMIT 1",
        (stem + "%",)).fetchone()
    n = int(row[0].rsplit("-", 1)[1]) + 1 if row else 1
    return f"{stem}{n:04d}"
