"""Login, roles, CSRF protection and the audit log."""
import secrets
from datetime import datetime, timedelta

from flask import abort, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, now

ROLES = {"admin": "Doctor / Owner (full access)", "technician": "Technician / Reception"}

# Pages anyone may open without logging in.
PUBLIC_ENDPOINTS = {"login", "setup", "static", "ping"}

# Pages only the doctor/owner (admin) may open: money, referrers, catalog, settings, data.
ADMIN_ENDPOINTS = {
    "doctors", "doctor_form", "hospitals", "hospital_form",
    "commissions", "commissions_mark", "commissions_csv",
    "test_form", "package_form",
    "settings_page", "settings_branding", "branding_delete",
    "backup_page", "backup_now", "backup_download", "backup_restore", "backup",
    "users", "user_form", "audit_page", "licence_page", "backup_page",
    "visit_delete", "visit_amend",
}

MIN_PASSWORD = 6
MAX_FAILED = 5
LOCK_MINUTES = 10


def hash_password(pw):
    return generate_password_hash(pw)


def password_problem(pw):
    if len(pw or "") < MIN_PASSWORD:
        return f"Password must be at least {MIN_PASSWORD} characters"
    return None


def current_user():
    return g.get("user")


def is_admin():
    u = current_user()
    return bool(u and u["role"] == "admin")


def audit(action, details=""):
    u = current_user()
    get_db().execute("INSERT INTO audit_log(ts, username, action, details) VALUES (?,?,?,?)",
                     (now(), u["username"] if u else None, action, details))


def attempt_login(username, password):
    """Returns (user_row, error_message)."""
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
    if not u or not u["active"]:
        return None, "Wrong username or password"
    if u["locked_until"] and u["locked_until"] > now():
        return None, f"Too many wrong attempts. Try again after {u['locked_until'][11:16]}."
    if not check_password_hash(u["password_hash"], password):
        failed = u["failed_logins"] + 1
        locked = None
        if failed >= MAX_FAILED:
            locked = (datetime.now() + timedelta(minutes=LOCK_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
            failed = 0
        db.execute("UPDATE users SET failed_logins=?, locked_until=? WHERE id=?", (failed, locked, u["id"]))
        db.execute("INSERT INTO audit_log(ts, username, action, details) VALUES (?,?,?,?)",
                   (now(), u["username"], "login_failed", request.remote_addr))
        db.commit()
        return None, "Wrong username or password"
    db.execute("UPDATE users SET failed_logins=0, locked_until=NULL, last_login=? WHERE id=?", (now(), u["id"]))
    db.commit()
    return u, None


def login_user(u):
    session.clear()
    session.permanent = True
    session["uid"] = u["id"]
    session["csrf"] = secrets.token_hex(16)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def guard():
    """before_request hook: first-run setup, login, roles and CSRF."""
    db = get_db()
    ep = request.endpoint or ""
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = db.execute("SELECT * FROM users WHERE id=? AND active=1", (uid,)).fetchone()
        if not g.user:
            session.clear()

    if request.method == "POST" and ep not in ("static", "ping"):
        sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not sent or not secrets.compare_digest(sent, session.get("csrf", "")):
            abort(400, "Form expired. Please go back, reload the page and try again.")

    if ep in PUBLIC_ENDPOINTS:
        return None
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        return redirect(url_for("setup"))
    if not g.user:
        return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
    if ep in ADMIN_ENDPOINTS and g.user["role"] != "admin":
        flash("Only the doctor / owner account can open that page.", "error")
        return redirect(url_for("dashboard"))
    return None
