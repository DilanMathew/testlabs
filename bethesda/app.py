import csv
import io
import json
import os
import sqlite3
from datetime import date, datetime, timedelta

from flask import (Flask, Response, abort, flash, g, redirect, render_template, request, send_file,
                   session, url_for)

from . import __version__
from . import backup as bk
from . import db as dbm
from . import licence as lic
from .db import get_db, get_settings, next_number, now
from .pdf_report import build_receipt, build_report
from .ranges import FLAG_LABEL, compute_flag, limits_for, range_text
from .security import (ROLES, attempt_login, audit, csrf_token, current_user, guard, hash_password,
                       is_admin, login_user, password_problem)

app = Flask(__name__)
app.secret_key = os.environ.get("BETHESDA_SECRET") or dbm.secret_key()
app.config.update(PERMANENT_SESSION_LIFETIME=timedelta(hours=12), SESSION_COOKIE_HTTPONLY=True,
                  SESSION_COOKIE_SAMESITE="Lax", MAX_CONTENT_LENGTH=8 * 1024 * 1024)
app.teardown_appcontext(dbm.close_db)
app.before_request(guard)

STATUSES = ["Registered", "Sample Collected", "Awaiting Approval", "Amending", "Completed"]


def branding_file(kind):
    path = os.path.join(dbm.BRANDING_DIR, f"{kind}.png")
    return path if os.path.exists(path) else None


# --------------------------------------------------------------------------- helpers
def fnum(v, default=None):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def fint(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@app.context_processor
def inject_globals():
    settings = get_settings()
    ctx = {"settings": settings, "today": date.today().isoformat(), "FLAG_LABEL": FLAG_LABEL,
           "current_user": current_user(), "is_admin": is_admin(), "csrf_token": csrf_token,
           "version": __version__, "has_logo": bool(branding_file("logo")), "STATUSES": STATUSES}
    if current_user():
        ctx["licence"] = lic.status(settings)
        ctx["backup_health"] = bk.status(settings) if is_admin() else None
    return ctx


@app.template_filter("money")
def money(v):
    return f"{(v or 0):,.2f}"


@app.template_filter("num")
def num(v):
    return "" if v is None else f"{v:g}"


def referred_by(v):
    """Human readable referral string for a visit row that has doctor_name / hospital_name joined."""
    if v["referral_type"] == "Self" or (not v["doctor_name"] and not v["hospital_name"]):
        return "Self"
    parts = []
    if v["doctor_name"]:
        parts.append(f"Dr. {v['doctor_name']}" if not v["doctor_name"].lower().startswith("dr") else v["doctor_name"])
    if v["hospital_name"]:
        parts.append(v["hospital_name"])
    return ", ".join(parts)


app.jinja_env.globals["referred_by"] = referred_by

VISIT_SELECT = """
SELECT v.*, p.name AS patient_name, p.patient_no, p.phone AS patient_phone, p.gender, p.age, p.age_unit,
       d.name AS doctor_name, h.name AS hospital_name
FROM visits v
JOIN patients p ON p.id = v.patient_id
LEFT JOIN doctors d ON d.id = v.doctor_id
LEFT JOIN hospitals h ON h.id = v.hospital_id
"""


def load_visit(visit_id):
    v = get_db().execute(VISIT_SELECT + " WHERE v.id=?", (visit_id,)).fetchone()
    if not v:
        abort(404)
    return v


# --------------------------------------------------------------------------- dashboard
@app.route("/")
def dashboard():
    db = get_db()
    today = date.today().isoformat()
    month = today[:7]
    stats = db.execute("""
        SELECT COUNT(*) AS visits, COALESCE(SUM(net_amount),0) AS billed, COALESCE(SUM(paid_amount),0) AS collected
        FROM visits WHERE substr(visit_date,1,10)=?""", (today,)).fetchone()
    mstats = db.execute("""
        SELECT COUNT(*) AS visits, COALESCE(SUM(net_amount),0) AS billed,
               SUM(referral_type='Self') AS self_n, SUM(referral_type='Doctor') AS doc_n,
               SUM(referral_type='Hospital') AS hosp_n
        FROM visits WHERE substr(visit_date,1,7)=?""", (month,)).fetchone()
    pending = db.execute("SELECT COUNT(*) FROM visits WHERE status!='Completed'").fetchone()[0]
    awaiting = db.execute("SELECT COUNT(*) FROM visits WHERE status IN ('Awaiting Approval','Amending')").fetchone()[0]
    unpaid_comm = db.execute("""
        SELECT COALESCE(SUM(CASE WHEN doctor_commission_paid_on IS NULL THEN doctor_commission ELSE 0 END),0)
             + COALESCE(SUM(CASE WHEN hospital_commission_paid_on IS NULL THEN hospital_commission ELSE 0 END),0)
        FROM visits""").fetchone()[0]
    dues = db.execute("SELECT COALESCE(SUM(net_amount-paid_amount),0) FROM visits WHERE net_amount>paid_amount").fetchone()[0]
    recent = db.execute(VISIT_SELECT + " ORDER BY v.id DESC LIMIT 12").fetchall()
    return render_template("dashboard.html", stats=stats, mstats=mstats, pending=pending,
                           unpaid_comm=unpaid_comm, dues=dues, recent=recent, awaiting=awaiting)


# --------------------------------------------------------------------------- patients
@app.route("/patients")
def patients():
    q = request.args.get("q", "").strip()
    sql = """SELECT p.*, (SELECT COUNT(*) FROM visits v WHERE v.patient_id=p.id) AS visit_count,
                    (SELECT MAX(visit_date) FROM visits v WHERE v.patient_id=p.id) AS last_visit
             FROM patients p"""
    args = []
    if q:
        sql += " WHERE p.name LIKE ? OR p.phone LIKE ? OR p.patient_no LIKE ?"
        args = [f"%{q}%"] * 3
    rows = get_db().execute(sql + " ORDER BY p.id DESC LIMIT 300", args).fetchall()
    return render_template("patients.html", rows=rows, q=q)


def patient_fields(form):
    return (form.get("name", "").strip(), fint(form.get("age")), form.get("age_unit") or "Years",
            form.get("gender") or None, form.get("phone", "").strip(), form.get("email", "").strip(),
            form.get("address", "").strip())


def create_patient(form):
    f = patient_fields(form)
    if not f[0]:
        raise ValueError("Patient name is required")
    cur = get_db().execute(
        """INSERT INTO patients(patient_no, name, age, age_unit, gender, phone, email, address, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""", (next_number("P", "patients", "patient_no"), *f, now()))
    return cur.lastrowid


@app.route("/patients/new", methods=["GET", "POST"])
def patient_new():
    if request.method == "POST":
        try:
            pid = create_patient(request.form)
        except ValueError as e:
            flash(str(e), "error")
            return render_template("patient_form.html", p=request.form)
        get_db().commit()
        flash("Patient registered", "ok")
        return redirect(url_for("patient_detail", pid=pid))
    return render_template("patient_form.html", p={})


@app.route("/patients/<int:pid>/edit", methods=["GET", "POST"])
def patient_edit(pid):
    db = get_db()
    p = db.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone() or abort(404)
    if request.method == "POST":
        f = patient_fields(request.form)
        db.execute("UPDATE patients SET name=?, age=?, age_unit=?, gender=?, phone=?, email=?, address=? WHERE id=?",
                   (*f, pid))
        db.commit()
        flash("Patient updated", "ok")
        return redirect(url_for("patient_detail", pid=pid))
    return render_template("patient_form.html", p=p)


@app.route("/patients/<int:pid>")
def patient_detail(pid):
    db = get_db()
    p = db.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone() or abort(404)
    visits = db.execute(VISIT_SELECT + " WHERE v.patient_id=? ORDER BY v.id DESC", (pid,)).fetchall()
    return render_template("patient_detail.html", p=p, visits=visits)


# --------------------------------------------------------------------------- visits (registration + billing)
def form_lookups():
    db = get_db()
    return dict(
        doctors=db.execute("""SELECT d.*, h.name AS hospital_name FROM doctors d
                              LEFT JOIN hospitals h ON h.id=d.hospital_id WHERE d.active=1 ORDER BY d.name""").fetchall(),
        hospitals=db.execute("SELECT * FROM hospitals WHERE active=1 ORDER BY name").fetchall(),
        tests=db.execute("SELECT * FROM tests WHERE active=1 ORDER BY category, name").fetchall(),
        packages=db.execute("""SELECT pk.*, GROUP_CONCAT(pt.test_id) AS test_ids,
                                      (SELECT GROUP_CONCAT(t.code, ', ') FROM package_tests x JOIN tests t ON t.id=x.test_id
                                       WHERE x.package_id=pk.id) AS test_codes
                               FROM packages pk LEFT JOIN package_tests pt ON pt.package_id=pk.id
                               WHERE pk.active=1 GROUP BY pk.id ORDER BY pk.name""").fetchall(),
    )


def save_visit(form, visit_id=None):
    db = get_db()
    patient_id = fint(form.get("patient_id"))
    if not patient_id:
        patient_id = create_patient(form)

    ref = form.get("referral_type", "Self")
    doctor_id = fint(form.get("doctor_id")) if ref in ("Doctor", "Hospital") else None
    hospital_id = fint(form.get("hospital_id")) if ref == "Hospital" else None
    if ref == "Doctor" and not doctor_id:
        raise ValueError("Please select the referring doctor")
    if ref == "Hospital" and not hospital_id:
        raise ValueError("Please select the referring hospital")

    pkg_ids = [fint(x) for x in form.getlist("package_ids") if fint(x)]
    test_ids = [fint(x) for x in form.getlist("test_ids") if fint(x)]
    if not pkg_ids and not test_ids:
        raise ValueError("Select at least one test or package")

    # Build billing lines
    lines_pkg, lines_test, covered = [], [], set()
    for pk in pkg_ids:
        row = db.execute("SELECT * FROM packages WHERE id=?", (pk,)).fetchone()
        if not row:
            continue
        tids = [r[0] for r in db.execute("SELECT test_id FROM package_tests WHERE package_id=?", (pk,))]
        lines_pkg.append((row, tids))
        covered.update(tids)
    for tid in dict.fromkeys(test_ids):
        if tid in covered:
            continue
        row = db.execute("SELECT * FROM tests WHERE id=?", (tid,)).fetchone()
        if row:
            lines_test.append(row)

    gross = sum(p["price"] for p, _ in lines_pkg) + sum(t["price"] for t in lines_test)
    discount = min(max(fnum(form.get("discount"), 0), 0), gross)
    net = gross - discount
    paid = max(fnum(form.get("paid_amount"), 0), 0)

    # Commission %: the admin may override per visit; technicians always get the stored rate
    # (or the visit's existing rate when editing a visit for the same referrer).
    old = db.execute("SELECT * FROM visits WHERE id=?", (visit_id,)).fetchone() if visit_id else None
    d_pct = h_pct = 0.0
    if doctor_id:
        d_pct = fnum(form.get("doctor_commission_pct")) if is_admin() else None
        if d_pct is None and old is not None and old["doctor_id"] == doctor_id:
            d_pct = old["doctor_commission_pct"]
        if d_pct is None:
            d_pct = db.execute("SELECT commission_pct FROM doctors WHERE id=?", (doctor_id,)).fetchone()[0]
    if hospital_id:
        h_pct = fnum(form.get("hospital_commission_pct")) if is_admin() else None
        if h_pct is None and old is not None and old["hospital_id"] == hospital_id:
            h_pct = old["hospital_commission_pct"]
        if h_pct is None:
            h_pct = db.execute("SELECT commission_pct FROM hospitals WHERE id=?", (hospital_id,)).fetchone()[0]
    d_comm = round(net * d_pct / 100, 2)
    h_comm = round(net * h_pct / 100, 2)

    values = dict(patient_id=patient_id, referral_type=ref, doctor_id=doctor_id, hospital_id=hospital_id,
                  gross_amount=gross, discount=discount, net_amount=net, paid_amount=paid,
                  payment_mode=form.get("payment_mode") or None,
                  doctor_commission_pct=d_pct, doctor_commission=d_comm,
                  hospital_commission_pct=h_pct, hospital_commission=h_comm,
                  clinical_notes=form.get("clinical_notes", "").strip())
    if visit_id is None:
        values.update(visit_no=next_number("BL", "visits", "visit_no"),
                      visit_date=(form.get("visit_date") or now()).replace("T", " "),
                      status="Registered", created_at=now(), created_by=current_user()["username"])
        cols = ", ".join(values)
        cur = db.execute(f"INSERT INTO visits({cols}) VALUES ({', '.join('?' * len(values))})",
                         list(values.values()))
        visit_id = cur.lastrowid
    else:
        if form.get("visit_date"):
            values["visit_date"] = form["visit_date"].replace("T", " ")
        sets = ", ".join(f"{k}=?" for k in values)
        db.execute(f"UPDATE visits SET {sets} WHERE id=?", [*values.values(), visit_id])
        db.execute("DELETE FROM visit_tests WHERE visit_id=?", (visit_id,))
        db.execute("DELETE FROM visit_packages WHERE visit_id=?", (visit_id,))

    for pkg, tids in lines_pkg:
        cur = db.execute("INSERT INTO visit_packages(visit_id, package_id, name, price) VALUES (?,?,?,?)",
                         (visit_id, pkg["id"], pkg["name"], pkg["price"]))
        for tid in tids:
            db.execute("INSERT INTO visit_tests(visit_id, test_id, visit_package_id, price) VALUES (?,?,?,0)",
                       (visit_id, tid, cur.lastrowid))
    for t in lines_test:
        db.execute("INSERT INTO visit_tests(visit_id, test_id, price) VALUES (?,?,?)", (visit_id, t["id"], t["price"]))
    vno = db.execute("SELECT visit_no FROM visits WHERE id=?", (visit_id,)).fetchone()[0]
    audit("visit_updated" if old is not None else "visit_created",
          f"{vno}: net {net:.2f}, paid {paid:.2f}, referral {ref}")
    db.commit()
    return visit_id


@app.route("/visits/new", methods=["GET", "POST"])
def visit_new():
    db = get_db()
    patient = None
    pid = fint(request.values.get("patient_id"))
    if pid:
        patient = db.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    licence = lic.status(get_settings())
    if licence["blocks_new_visits"]:
        return render_template("message.html", title="New visits are paused",
                               message=licence["message"] + " Contact the developer to renew the licence. "
                               "You can still open, print and share all existing patients, visits and reports.")
    if request.method == "POST":
        try:
            vid = save_visit(request.form)
            flash("Visit registered. Collect the sample and enter results when ready.", "ok")
            return redirect(url_for("visit_detail", vid=vid))
        except ValueError as e:
            db.rollback()
            flash(str(e), "error")
    return render_template("visit_form.html", patient=patient, visit=None, sel_tests=set(), sel_pkgs=set(),
                           **form_lookups())


@app.route("/visits/<int:vid>/edit", methods=["GET", "POST"])
def visit_edit(vid):
    db = get_db()
    visit = load_visit(vid)
    if visit["status"] in ("Completed", "Amending", "Awaiting Approval"):
        flash("Tests and billing cannot be changed once results are submitted or the report is approved. "
              "Use 'Collect' for payments.", "error")
        return redirect(url_for("visit_detail", vid=vid))
    if request.method == "POST":
        try:
            save_visit(request.form, visit_id=vid)
            flash("Visit updated", "ok")
            return redirect(url_for("visit_detail", vid=vid))
        except ValueError as e:
            db.rollback()
            flash(str(e), "error")
    patient = db.execute("SELECT * FROM patients WHERE id=?", (visit["patient_id"],)).fetchone()
    sel_pkgs = {r[0] for r in db.execute("SELECT package_id FROM visit_packages WHERE visit_id=?", (vid,))}
    sel_tests = {r[0] for r in db.execute("SELECT test_id FROM visit_tests WHERE visit_id=? AND visit_package_id IS NULL", (vid,))}
    return render_template("visit_form.html", patient=patient, visit=visit, sel_tests=sel_tests,
                           sel_pkgs=sel_pkgs, **form_lookups())


@app.route("/visits")
def visits():
    a = request.args
    sql, args = VISIT_SELECT + " WHERE 1=1", []
    if a.get("from"):
        sql += " AND substr(v.visit_date,1,10)>=?"; args.append(a["from"])
    if a.get("to"):
        sql += " AND substr(v.visit_date,1,10)<=?"; args.append(a["to"])
    if a.get("status"):
        sql += " AND v.status=?"; args.append(a["status"])
    if a.get("referral_type"):
        sql += " AND v.referral_type=?"; args.append(a["referral_type"])
    if a.get("q"):
        sql += " AND (p.name LIKE ? OR p.phone LIKE ? OR v.visit_no LIKE ? OR p.patient_no LIKE ?)"
        args += [f"%{a['q']}%"] * 4
    rows = get_db().execute(sql + " ORDER BY v.id DESC LIMIT 500", args).fetchall()
    totals = {k: sum(r[k] for r in rows) for k in ("net_amount", "paid_amount")}
    return render_template("visits.html", rows=rows, a=a, totals=totals)


def visit_items(vid):
    db = get_db()
    pkgs = db.execute("SELECT * FROM visit_packages WHERE visit_id=?", (vid,)).fetchall()
    tests = db.execute("""SELECT vt.*, t.code, t.name, t.category, t.sample_type, vp.name AS package_name
                          FROM visit_tests vt JOIN tests t ON t.id=vt.test_id
                          LEFT JOIN visit_packages vp ON vp.id=vt.visit_package_id
                          WHERE vt.visit_id=? ORDER BY t.category, t.name""", (vid,)).fetchall()
    return pkgs, tests


@app.route("/visits/<int:vid>")
def visit_detail(vid):
    visit = load_visit(vid)
    pkgs, tests = visit_items(vid)
    db = get_db()
    n_results = db.execute("SELECT COUNT(*) FROM results WHERE visit_id=? AND value IS NOT NULL AND value!=''",
                           (vid,)).fetchone()[0]
    versions = db.execute("SELECT version, approved_by, approved_at, amend_reason FROM report_versions "
                          "WHERE visit_id=? ORDER BY version DESC", (vid,)).fetchall()
    return render_template("visit_detail.html", v=visit, pkgs=pkgs, tests=tests, n_results=n_results,
                           versions=versions)


@app.route("/visits/<int:vid>/status", methods=["POST"])
def visit_status(vid):
    db = get_db()
    v = load_visit(vid)
    if request.form.get("status") == "Sample Collected" and v["status"] == "Registered":
        db.execute("UPDATE visits SET status='Sample Collected', sample_collected_at=? WHERE id=?", (now(), vid))
        audit("sample_collected", v["visit_no"])
        db.commit()
    return redirect(url_for("visit_detail", vid=vid))


@app.route("/visits/<int:vid>/payment", methods=["POST"])
def visit_payment(vid):
    db = get_db()
    v = load_visit(vid)
    add = max(fnum(request.form.get("amount"), 0), 0)
    db.execute("UPDATE visits SET paid_amount=paid_amount+?, payment_mode=COALESCE(?, payment_mode) WHERE id=?",
               (add, request.form.get("payment_mode") or None, vid))
    audit("payment", f"{v['visit_no']}: {add:.2f} by {request.form.get('payment_mode') or '-'}")
    db.commit()
    flash(f"Payment of {add:,.2f} recorded", "ok")
    return redirect(url_for("visit_detail", vid=vid))


@app.route("/visits/<int:vid>/delete", methods=["POST"])
def visit_delete(vid):
    db = get_db()
    v = load_visit(vid)
    if v["status"] == "Completed":
        flash("An approved report cannot be deleted. Use 'Amend report' to correct it.", "error")
        return redirect(url_for("visit_detail", vid=vid))
    audit("visit_deleted", f"{v['visit_no']} ({v['patient_name']}), net {v['net_amount']:.2f}")
    db.execute("DELETE FROM report_versions WHERE visit_id=?", (vid,))
    db.execute("DELETE FROM results WHERE visit_id=?", (vid,))
    db.execute("DELETE FROM visit_tests WHERE visit_id=?", (vid,))
    db.execute("DELETE FROM visit_packages WHERE visit_id=?", (vid,))
    db.execute("DELETE FROM visits WHERE id=?", (vid,))
    db.commit()
    flash("Visit deleted", "ok")
    return redirect(url_for("visits"))


# --------------------------------------------------------------------------- results
def report_sections(vid, gender, live=False):
    """Tests of a visit with their parameters and saved results."""
    db = get_db()
    _, tests = visit_items(vid)
    saved = {r["parameter_id"]: r for r in db.execute("SELECT * FROM results WHERE visit_id=?", (vid,))}
    sections = []
    for t in tests:
        params = db.execute("""SELECT * FROM parameters WHERE test_id=? AND
                                 (active=1 OR id IN (SELECT parameter_id FROM results WHERE visit_id=?))
                               ORDER BY sort_order, id""", (t["test_id"], vid)).fetchall()
        rows = []
        for p in params:
            r = saved.get(p["id"])
            if r is not None and not live:
                low, high, text, normal, unit = r["ref_low"], r["ref_high"], r["ref_text"], r["normal_value"], r["unit"]
            else:
                low, high = limits_for(p, gender)
                text, normal, unit = p["ref_text"], p["normal_value"], p["unit"]
            rows.append(dict(pid=p["id"], name=p["name"], unit=unit or "", low=low, high=high,
                             ref_text=text or "", normal_value=normal or "", options=p["options"] or "",
                             value=r["value"] if r else "", flag=r["flag"] if r else ""))
        sections.append(dict(test_id=t["test_id"], code=t["code"], name=t["name"], category=t["category"],
                             sample_type=t["sample_type"], rows=rows))
    return sections


def _save_results(vid, v):
    db = get_db()
    for s in report_sections(vid, v["gender"], live=True):
        for r in s["rows"]:
            key = f"p_{r['pid']}"
            if key not in request.form:
                continue
            val = request.form[key].strip()
            flag = compute_flag(val, r["low"], r["high"], r["normal_value"])
            db.execute("""INSERT INTO results(visit_id, parameter_id, value, unit, ref_low, ref_high, ref_text,
                                              normal_value, flag)
                          VALUES (?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(visit_id, parameter_id) DO UPDATE SET value=excluded.value,
                            unit=excluded.unit, ref_low=excluded.ref_low, ref_high=excluded.ref_high,
                            ref_text=excluded.ref_text, normal_value=excluded.normal_value, flag=excluded.flag""",
                       (vid, r["pid"], val, r["unit"], r["low"], r["high"], r["ref_text"], r["normal_value"], flag))
    db.execute("UPDATE visits SET remarks=? WHERE id=?", (request.form.get("remarks", "").strip(), vid))


def _approve(vid, v):
    """Freeze the current results as a new report version."""
    db = get_db()
    sections = report_sections(vid, v["gender"])
    remarks = db.execute("SELECT remarks FROM visits WHERE id=?", (vid,)).fetchone()[0]
    version = (v["report_version"] or 0) + 1
    who = current_user()["full_name"]
    ts = now()
    reason = v["amend_reason"] if version > 1 else None
    db.execute("""INSERT INTO report_versions(visit_id, version, sections_json, remarks, approved_by, approved_at,
                                              amend_reason) VALUES (?,?,?,?,?,?,?)""",
               (vid, version, json.dumps(sections), remarks, who, ts, reason))
    db.execute("""UPDATE visits SET status='Completed', report_version=?, approved_by=?, approved_at=?,
                  reported_at=?, sample_collected_at=COALESCE(sample_collected_at, visit_date)
                  WHERE id=?""", (version, who, ts, ts, vid))
    audit("report_approved", f"{v['visit_no']} version {version}" + (f" (amended: {reason})" if reason else ""))


@app.route("/visits/<int:vid>/results", methods=["GET", "POST"])
def results(vid):
    db = get_db()
    v = load_visit(vid)
    locked = v["status"] == "Completed"
    if request.method == "POST":
        if locked:
            flash("This report is approved and locked. Use 'Amend report' to correct it.", "error")
            return redirect(url_for("visit_detail", vid=vid))
        action = request.form.get("action")
        if action == "approve" and not is_admin():
            abort(403)
        _save_results(vid, v)
        if action == "approve":
            _approve(vid, v)
            flash("Report approved and locked. The PDF is ready.", "ok")
        elif action == "submit":
            db.execute("UPDATE visits SET status='Awaiting Approval', "
                       "sample_collected_at=COALESCE(sample_collected_at, ?) WHERE id=?", (now(), vid))
            audit("results_submitted", v["visit_no"])
            flash("Results saved and sent to the doctor for approval.", "ok")
        else:
            if v["status"] == "Registered":
                db.execute("UPDATE visits SET status='Sample Collected', sample_collected_at=? WHERE id=?",
                           (now(), vid))
            audit("results_saved", v["visit_no"])
            flash("Results saved (draft)", "ok")
        db.commit()
        return redirect(url_for("visit_detail", vid=vid))
    sections = report_sections(vid, v["gender"], live=not locked)
    if not locked:
        saved = {r["parameter_id"]: r["value"] for r in db.execute("SELECT * FROM results WHERE visit_id=?", (vid,))}
        for s in sections:
            for r in s["rows"]:
                r["value"] = saved.get(r["pid"], "")
    for s in sections:
        for r in s["rows"]:
            r["range"] = range_text(r["low"], r["high"], r["ref_text"], r["normal_value"])
    return render_template("results_form.html", v=v, sections=sections, locked=locked)


@app.route("/visits/<int:vid>/amend", methods=["POST"])
def visit_amend(vid):
    db = get_db()
    v = load_visit(vid)
    reason = request.form.get("reason", "").strip()
    if v["status"] != "Completed":
        return redirect(url_for("visit_detail", vid=vid))
    if len(reason) < 5:
        flash("Please give the reason for amending the report.", "error")
        return redirect(url_for("visit_detail", vid=vid))
    db.execute("UPDATE visits SET status='Amending', amend_reason=? WHERE id=?", (reason, vid))
    audit("report_amend_started", f"{v['visit_no']}: {reason}")
    db.commit()
    flash("Report unlocked for correction. Approve it again to issue the amended version.", "ok")
    return redirect(url_for("results", vid=vid))


def _pdf_response(data, filename, download):
    return Response(data, mimetype="application/pdf", headers={
        "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{filename}"'})


def _branding():
    return dict(logo_path=branding_file("logo"), signature_path=branding_file("signature"))


@app.route("/visits/<int:vid>/report.pdf")
def report_pdf(vid):
    db = get_db()
    v = load_visit(vid)
    patient = db.execute("SELECT * FROM patients WHERE id=?", (v["patient_id"],)).fetchone()
    want = fint(request.args.get("v"))
    snap = None
    if want:
        snap = db.execute("SELECT * FROM report_versions WHERE visit_id=? AND version=?", (vid, want)).fetchone()
        if not snap:
            abort(404)
    elif v["status"] == "Completed":
        snap = db.execute("SELECT * FROM report_versions WHERE visit_id=? ORDER BY version DESC LIMIT 1",
                          (vid,)).fetchone()
    if snap:
        sections = json.loads(snap["sections_json"])
        approval = dict(version=snap["version"], approved_by=snap["approved_by"], approved_at=snap["approved_at"],
                        amend_reason=snap["amend_reason"], remarks=snap["remarks"],
                        superseded=snap["version"] < (v["report_version"] or 0))
        draft = False
    else:
        # Not yet approved -> DRAFT. (Reports completed before versioning existed have no snapshot:
        # they print from the saved results, which already hold the ranges used at the time.)
        sections = report_sections(vid, v["gender"])
        approval, draft = None, v["status"] != "Completed"
    pdf = build_report(get_settings(), v, patient, referred_by(v), sections, draft=draft, approval=approval,
                       **_branding())
    safe = "".join(c for c in patient["name"] if c.isalnum() or c in " -_").strip().replace(" ", "_")
    suffix = f"_v{snap['version']}" if snap and snap["version"] > 1 else ("_DRAFT" if draft else "")
    return _pdf_response(pdf, f"{v['visit_no']}_{safe}{suffix}.pdf", request.args.get("download"))


@app.route("/visits/<int:vid>/receipt.pdf")
def receipt_pdf(vid):
    db = get_db()
    v = load_visit(vid)
    patient = db.execute("SELECT * FROM patients WHERE id=?", (v["patient_id"],)).fetchone()
    pkgs, tests = visit_items(vid)
    lines = [(f"Package: {p['name']}", p["price"]) for p in pkgs]
    lines += [(f"{t['name']} ({t['code']})", t["price"]) for t in tests if not t["visit_package_id"]]
    pdf = build_receipt(get_settings(), v, patient, referred_by(v), lines, logo_path=branding_file("logo"))
    return _pdf_response(pdf, f"Receipt_{v['visit_no']}.pdf", request.args.get("download"))


# --------------------------------------------------------------------------- doctors & hospitals
@app.route("/doctors")
def doctors():
    rows = get_db().execute("""
        SELECT d.*, h.name AS hospital_name,
               COUNT(v.id) AS referrals, COALESCE(SUM(v.net_amount),0) AS business,
               COALESCE(SUM(v.doctor_commission),0) AS commission,
               COALESCE(SUM(CASE WHEN v.doctor_commission_paid_on IS NULL THEN v.doctor_commission END),0) AS unpaid
        FROM doctors d LEFT JOIN hospitals h ON h.id=d.hospital_id
        LEFT JOIN visits v ON v.doctor_id=d.id
        GROUP BY d.id ORDER BY d.active DESC, d.name""").fetchall()
    return render_template("doctors.html", rows=rows)


@app.route("/doctors/new", methods=["GET", "POST"])
@app.route("/doctors/<int:did>/edit", methods=["GET", "POST"])
def doctor_form(did=None):
    db = get_db()
    d = db.execute("SELECT * FROM doctors WHERE id=?", (did,)).fetchone() if did else None
    if did and not d:
        abort(404)
    if request.method == "POST":
        f = request.form
        vals = (f.get("name", "").strip(), f.get("qualification"), f.get("specialization"), f.get("registration_no"),
                f.get("phone"), f.get("email"), fint(f.get("hospital_id")), fnum(f.get("commission_pct"), 0),
                1 if f.get("active") else 0)
        if not vals[0]:
            flash("Name is required", "error")
        else:
            if did:
                db.execute("""UPDATE doctors SET name=?, qualification=?, specialization=?, registration_no=?, phone=?,
                              email=?, hospital_id=?, commission_pct=?, active=? WHERE id=?""", (*vals, did))
            else:
                db.execute("""INSERT INTO doctors(name, qualification, specialization, registration_no, phone, email,
                              hospital_id, commission_pct, active, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                           (*vals, now()))
            audit("doctor_saved", f"{vals[0]} commission {vals[7]}%")
            db.commit()
            flash("Doctor saved", "ok")
            return redirect(url_for("doctors"))
    hospitals = db.execute("SELECT * FROM hospitals WHERE active=1 ORDER BY name").fetchall()
    return render_template("doctor_form.html", d=d, hospitals=hospitals)


@app.route("/hospitals")
def hospitals():
    rows = get_db().execute("""
        SELECT h.*, (SELECT COUNT(*) FROM doctors d WHERE d.hospital_id=h.id) AS n_doctors,
               COUNT(v.id) AS referrals, COALESCE(SUM(v.net_amount),0) AS business,
               COALESCE(SUM(v.hospital_commission),0) AS commission,
               COALESCE(SUM(CASE WHEN v.hospital_commission_paid_on IS NULL THEN v.hospital_commission END),0) AS unpaid
        FROM hospitals h LEFT JOIN visits v ON v.hospital_id=h.id
        GROUP BY h.id ORDER BY h.active DESC, h.name""").fetchall()
    return render_template("hospitals.html", rows=rows)


@app.route("/hospitals/new", methods=["GET", "POST"])
@app.route("/hospitals/<int:hid>/edit", methods=["GET", "POST"])
def hospital_form(hid=None):
    db = get_db()
    h = db.execute("SELECT * FROM hospitals WHERE id=?", (hid,)).fetchone() if hid else None
    if hid and not h:
        abort(404)
    if request.method == "POST":
        f = request.form
        vals = (f.get("name", "").strip(), f.get("address"), f.get("phone"), f.get("email"), f.get("contact_person"),
                fnum(f.get("commission_pct"), 0), 1 if f.get("active") else 0)
        if not vals[0]:
            flash("Name is required", "error")
        else:
            if hid:
                db.execute("""UPDATE hospitals SET name=?, address=?, phone=?, email=?, contact_person=?,
                              commission_pct=?, active=? WHERE id=?""", (*vals, hid))
            else:
                db.execute("""INSERT INTO hospitals(name, address, phone, email, contact_person, commission_pct, active,
                              created_at) VALUES (?,?,?,?,?,?,?,?)""", (*vals, now()))
            audit("hospital_saved", f"{vals[0]} commission {vals[5]}%")
            db.commit()
            flash("Hospital saved", "ok")
            return redirect(url_for("hospitals"))
    return render_template("hospital_form.html", h=h)


# --------------------------------------------------------------------------- commissions
def commission_rows(a):
    """One row per (visit, party) that earned commission."""
    base = """
      SELECT v.id AS visit_id, v.visit_no, v.visit_date, v.net_amount, p.name AS patient_name, {cols}
      FROM visits v JOIN patients p ON p.id=v.patient_id {join}
      WHERE {amount} > 0"""
    parts, args = [], []
    for party in ("doctor", "hospital"):
        if a.get("party") and a["party"] != party:
            continue
        tbl = "doctors" if party == "doctor" else "hospitals"
        sql = base.format(
            cols=f"'{party}' AS party, x.id AS party_id, x.name AS party_name, v.{party}_commission_pct AS pct, "
                 f"v.{party}_commission AS amount, v.{party}_commission_paid_on AS paid_on",
            join=f"JOIN {tbl} x ON x.id=v.{party}_id", amount=f"v.{party}_commission")
        if a.get("from"):
            sql += " AND substr(v.visit_date,1,10)>=?"; args.append(a["from"])
        if a.get("to"):
            sql += " AND substr(v.visit_date,1,10)<=?"; args.append(a["to"])
        if a.get("status") == "unpaid":
            sql += f" AND v.{party}_commission_paid_on IS NULL"
        elif a.get("status") == "paid":
            sql += f" AND v.{party}_commission_paid_on IS NOT NULL"
        pid = fint(a.get(f"{party}_id"))
        if pid:
            sql += " AND x.id=?"; args.append(pid)
        elif a.get(f"{'hospital' if party == 'doctor' else 'doctor'}_id"):
            continue  # filtering on the other party only
        parts.append(sql)
    if not parts:
        return []
    return get_db().execute(" UNION ALL ".join(parts) + " ORDER BY party_name, visit_date", args).fetchall()


@app.route("/commissions")
def commissions():
    a = request.args
    rows = commission_rows(a)
    summary = {}
    for r in rows:
        k = (r["party"], r["party_id"])
        s = summary.setdefault(k, dict(party=r["party"], party_id=r["party_id"], name=r["party_name"],
                                       visits=0, business=0.0, total=0.0, paid=0.0, unpaid=0.0))
        s["visits"] += 1
        s["business"] += r["net_amount"]
        s["total"] += r["amount"]
        s["paid" if r["paid_on"] else "unpaid"] += r["amount"]
    db = get_db()
    return render_template("commissions.html", rows=rows, summary=list(summary.values()), a=a,
                           doctors=db.execute("SELECT id, name FROM doctors ORDER BY name").fetchall(),
                           hospitals=db.execute("SELECT id, name FROM hospitals ORDER BY name").fetchall())


@app.route("/commissions/mark", methods=["POST"])
def commissions_mark():
    db = get_db()
    paid_on = request.form.get("paid_on") or date.today().isoformat()
    unmark = request.form.get("action") == "unpaid"
    n = 0
    for item in request.form.getlist("items"):
        party, _, vid = item.partition(":")
        if party not in ("doctor", "hospital") or not fint(vid):
            continue
        db.execute(f"UPDATE visits SET {party}_commission_paid_on=? WHERE id=?", (None if unmark else paid_on, int(vid)))
        n += 1
    audit("commissions_marked_" + ("unpaid" if unmark else "paid"),
          f"{n} entries, paid on {paid_on}: {', '.join(request.form.getlist('items'))[:500]}")
    db.commit()
    flash(f"{n} commission entr{'y' if n == 1 else 'ies'} marked as {'unpaid' if unmark else 'paid on ' + paid_on}", "ok")
    return redirect(request.form.get("back") or url_for("commissions"))


@app.route("/commissions.csv")
def commissions_csv():
    rows = commission_rows(request.args)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Party Type", "Name", "Visit No", "Visit Date", "Patient", "Bill Amount", "Commission %",
                "Commission", "Paid On"])
    for r in rows:
        w.writerow([r["party"].title(), r["party_name"], r["visit_no"], r["visit_date"], r["patient_name"],
                    f"{r['net_amount']:.2f}", f"{r['pct']:g}", f"{r['amount']:.2f}", r["paid_on"] or "UNPAID"])
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=commissions.csv"})


# --------------------------------------------------------------------------- test catalog
@app.route("/tests")
def tests():
    q = request.args.get("q", "").strip()
    sql = """SELECT t.*, (SELECT COUNT(*) FROM parameters p WHERE p.test_id=t.id AND p.active=1) AS n_params
             FROM tests t"""
    args = []
    if q:
        sql += " WHERE t.name LIKE ? OR t.code LIKE ? OR t.category LIKE ?"
        args = [f"%{q}%"] * 3
    rows = get_db().execute(sql + " ORDER BY t.category, t.name", args).fetchall()
    return render_template("tests.html", rows=rows, q=q)


@app.route("/tests/new", methods=["GET", "POST"])
@app.route("/tests/<int:tid>/edit", methods=["GET", "POST"])
def test_form(tid=None):
    db = get_db()
    t = db.execute("SELECT * FROM tests WHERE id=?", (tid,)).fetchone() if tid else None
    if tid and not t:
        abort(404)
    if request.method == "POST":
        f = request.form
        vals = (f.get("code", "").strip().upper(), f.get("name", "").strip(), f.get("category", "").strip() or "General",
                f.get("sample_type"), fnum(f.get("price"), 0), 1 if f.get("fasting") else 0, f.get("notes"),
                1 if f.get("active") else 0)
        if not vals[0] or not vals[1]:
            flash("Code and name are required", "error")
            return redirect(request.url)
        try:
            if tid:
                db.execute("""UPDATE tests SET code=?, name=?, category=?, sample_type=?, price=?, fasting=?, notes=?,
                              active=? WHERE id=?""", (*vals, tid))
            else:
                tid = db.execute("""INSERT INTO tests(code, name, category, sample_type, price, fasting, notes, active)
                                    VALUES (?,?,?,?,?,?,?,?)""", vals).lastrowid
        except sqlite3.IntegrityError:
            flash(f"Test code {vals[0]} already exists", "error")
            return redirect(request.url)
        keep = []
        cols = ["pid", "pname", "unit", "low", "high", "lowf", "highf", "text", "normal", "options"]
        lists = {c: f.getlist(c) for c in cols}
        for i, name in enumerate(lists["pname"]):
            name = name.strip()
            if not name:
                continue
            row = (name, lists["unit"][i], fnum(lists["low"][i]), fnum(lists["high"][i]), fnum(lists["lowf"][i]),
                   fnum(lists["highf"][i]), lists["text"][i], lists["normal"][i], lists["options"][i], i)
            pid = fint(lists["pid"][i])
            if pid:
                db.execute("""UPDATE parameters SET name=?, unit=?, ref_low=?, ref_high=?, ref_low_f=?, ref_high_f=?,
                              ref_text=?, normal_value=?, options=?, sort_order=?, active=1 WHERE id=? AND test_id=?""",
                           (*row, pid, tid))
            else:
                pid = db.execute("""INSERT INTO parameters(name, unit, ref_low, ref_high, ref_low_f, ref_high_f,
                                    ref_text, normal_value, options, sort_order, test_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                                 (*row, tid)).lastrowid
            keep.append(pid)
        # Remove dropped parameters (deactivate if already used in results, so old reports stay intact)
        for (pid,) in db.execute("SELECT id FROM parameters WHERE test_id=?", (tid,)).fetchall():
            if pid in keep:
                continue
            used = db.execute("SELECT 1 FROM results WHERE parameter_id=? LIMIT 1", (pid,)).fetchone()
            if used:
                db.execute("UPDATE parameters SET active=0 WHERE id=?", (pid,))
            else:
                db.execute("DELETE FROM parameters WHERE id=?", (pid,))
        audit("test_saved", f"{vals[0]} {vals[1]} price {vals[4]}")
        db.commit()
        flash("Test saved", "ok")
        return redirect(url_for("tests"))
    params = db.execute("SELECT * FROM parameters WHERE test_id=? AND active=1 ORDER BY sort_order, id",
                        (tid,)).fetchall() if tid else []
    categories = [r[0] for r in db.execute("SELECT DISTINCT category FROM tests ORDER BY category")]
    return render_template("test_form.html", t=t, params=params, categories=categories)


@app.route("/packages")
def packages():
    rows = get_db().execute("""SELECT pk.*, GROUP_CONCAT(t.code, ', ') AS codes, COALESCE(SUM(t.price),0) AS mrp
                               FROM packages pk LEFT JOIN package_tests pt ON pt.package_id=pk.id
                               LEFT JOIN tests t ON t.id=pt.test_id GROUP BY pk.id ORDER BY pk.name""").fetchall()
    return render_template("packages.html", rows=rows)


@app.route("/packages/new", methods=["GET", "POST"])
@app.route("/packages/<int:pkid>/edit", methods=["GET", "POST"])
def package_form(pkid=None):
    db = get_db()
    pk = db.execute("SELECT * FROM packages WHERE id=?", (pkid,)).fetchone() if pkid else None
    if pkid and not pk:
        abort(404)
    if request.method == "POST":
        f = request.form
        vals = (f.get("code", "").strip().upper(), f.get("name", "").strip(), fnum(f.get("price"), 0),
                1 if f.get("active") else 0)
        if not vals[0] or not vals[1]:
            flash("Code and name are required", "error")
            return redirect(request.url)
        try:
            if pkid:
                db.execute("UPDATE packages SET code=?, name=?, price=?, active=? WHERE id=?", (*vals, pkid))
            else:
                pkid = db.execute("INSERT INTO packages(code, name, price, active) VALUES (?,?,?,?)", vals).lastrowid
        except sqlite3.IntegrityError:
            flash(f"Package code {vals[0]} already exists", "error")
            return redirect(request.url)
        db.execute("DELETE FROM package_tests WHERE package_id=?", (pkid,))
        for tid in {fint(x) for x in f.getlist("test_ids") if fint(x)}:
            db.execute("INSERT INTO package_tests VALUES (?,?)", (pkid, tid))
        audit("package_saved", f"{vals[0]} {vals[1]} price {vals[2]}")
        db.commit()
        flash("Package saved", "ok")
        return redirect(url_for("packages"))
    sel = {r[0] for r in db.execute("SELECT test_id FROM package_tests WHERE package_id=?", (pkid,))} if pkid else set()
    all_tests = db.execute("SELECT * FROM tests WHERE active=1 ORDER BY category, name").fetchall()
    return render_template("package_form.html", pk=pk, sel=sel, tests=all_tests)


# --------------------------------------------------------------------------- login & users
@app.route("/ping")
def ping():
    return "balaji-xrays"


@app.route("/setup", methods=["GET", "POST"])
def setup():
    """First run only: create the doctor / owner account."""
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return redirect(url_for("login"))
    if request.method == "POST":
        f = request.form
        err = password_problem(f.get("password")) or (
            "Passwords do not match" if f.get("password") != f.get("password2") else None) or (
            "Username and full name are required" if not f.get("username", "").strip() or not f.get("full_name", "").strip() else None)
        if err:
            flash(err, "error")
        else:
            db.execute("INSERT INTO users(username, full_name, role, password_hash, created_at) VALUES (?,?,?,?,?)",
                       (f["username"].strip(), f["full_name"].strip(), "admin", hash_password(f["password"]), now()))
            if f.get("lab_name", "").strip():
                dbm.set_setting("lab_name", f["lab_name"].strip())
            db.commit()
            u = db.execute("SELECT * FROM users WHERE username=?", (f["username"].strip(),)).fetchone()
            login_user(u)
            g.user = u
            audit("first_setup", f"admin account {u['username']} created")
            db.commit()
            flash("Welcome! Next: fill in Settings, upload your logo, and set the backup folder.", "ok")
            return redirect(url_for("settings_page"))
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u, err = attempt_login(request.form.get("username", ""), request.form.get("password", ""))
        if err:
            flash(err, "error")
        else:
            login_user(u)
            g.user = u
            audit("login", request.remote_addr or "")
            get_db().commit()
            nxt = request.args.get("next") or ""
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    if current_user():
        audit("logout")
        get_db().commit()
    session.clear()
    return redirect(url_for("login"))


@app.route("/account", methods=["GET", "POST"])
def account():
    db = get_db()
    if request.method == "POST":
        f = request.form
        from werkzeug.security import check_password_hash
        if not check_password_hash(current_user()["password_hash"], f.get("current", "")):
            flash("Current password is wrong", "error")
        elif password_problem(f.get("new")) or f.get("new") != f.get("new2"):
            flash(password_problem(f.get("new")) or "New passwords do not match", "error")
        else:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(f["new"]), current_user()["id"]))
            audit("password_changed")
            db.commit()
            flash("Password changed", "ok")
            return redirect(url_for("dashboard"))
    return render_template("account.html")


@app.route("/users")
def users():
    rows = get_db().execute("SELECT * FROM users ORDER BY active DESC, role, full_name").fetchall()
    return render_template("users.html", rows=rows, ROLES=ROLES)


@app.route("/users/new", methods=["GET", "POST"])
@app.route("/users/<int:uid>/edit", methods=["GET", "POST"])
def user_form(uid=None):
    db = get_db()
    u = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if uid and not u:
        abort(404)
    if request.method == "POST":
        f = request.form
        username, full_name = f.get("username", "").strip(), f.get("full_name", "").strip()
        role = f.get("role") if f.get("role") in ROLES else "technician"
        active = 1 if f.get("active") else 0
        pw = f.get("password", "")
        admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1 AND id!=?",
                            (uid or 0,)).fetchone()[0]
        if not username or not full_name:
            flash("Username and full name are required", "error")
        elif (not u or pw) and password_problem(pw):
            flash(password_problem(pw), "error")
        elif u and u["role"] == "admin" and (role != "admin" or not active) and admins == 0:
            flash("There must always be at least one active doctor/owner account.", "error")
        else:
            try:
                if u:
                    db.execute("UPDATE users SET username=?, full_name=?, role=?, active=? WHERE id=?",
                               (username, full_name, role, active, uid))
                    if pw:
                        db.execute("UPDATE users SET password_hash=?, failed_logins=0, locked_until=NULL WHERE id=?",
                                   (hash_password(pw), uid))
                else:
                    db.execute("""INSERT INTO users(username, full_name, role, password_hash, active, created_at)
                                  VALUES (?,?,?,?,?,?)""", (username, full_name, role, hash_password(pw), active, now()))
            except sqlite3.IntegrityError:
                flash(f"Username '{username}' is already taken", "error")
                return render_template("user_form.html", u=u, ROLES=ROLES)
            audit("user_saved", f"{username} role={role} active={active}" + (" password reset" if u and pw else ""))
            db.commit()
            flash("User saved", "ok")
            return redirect(url_for("users"))
    return render_template("user_form.html", u=u, ROLES=ROLES)


@app.route("/audit")
def audit_page():
    q = request.args.get("q", "").strip()
    sql, args = "SELECT * FROM audit_log", []
    if q:
        sql += " WHERE action LIKE ? OR details LIKE ? OR username LIKE ?"
        args = [f"%{q}%"] * 3
    rows = get_db().execute(sql + " ORDER BY id DESC LIMIT 500", args).fetchall()
    return render_template("audit.html", rows=rows, q=q)


# --------------------------------------------------------------------------- settings, branding, licence
@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    db = get_db()
    if request.method == "POST":
        for k in dbm.DEFAULT_SETTINGS:
            if k in request.form and k not in ("backup_dir", "backup_keep"):
                dbm.set_setting(k, request.form[k].strip())
        if "allow_lan_present" in request.form:
            dbm.set_setting("allow_lan", "1" if request.form.get("allow_lan") else "0")
        audit("settings_saved")
        db.commit()
        flash("Settings saved", "ok")
        return redirect(url_for("settings_page"))
    return render_template("settings.html", logo=branding_file("logo"), signature=branding_file("signature"))


@app.route("/settings/branding", methods=["POST"])
def settings_branding():
    from PIL import Image
    kind = request.form.get("kind")
    file = request.files.get("image")
    if kind not in ("logo", "signature") or not file or not file.filename:
        flash("Choose an image file first", "error")
        return redirect(url_for("settings_page"))
    try:
        img = Image.open(file.stream)
        img.load()
    except Exception:  # noqa: BLE001
        flash("That file is not a readable image (use PNG or JPG).", "error")
        return redirect(url_for("settings_page"))
    img = img.convert("RGBA")
    img.thumbnail((800, 400))
    os.makedirs(dbm.BRANDING_DIR, exist_ok=True)
    img.save(os.path.join(dbm.BRANDING_DIR, f"{kind}.png"), "PNG")
    audit("branding_uploaded", kind)
    get_db().commit()
    flash(f"{kind.title()} uploaded. It will appear on all new PDFs.", "ok")
    return redirect(url_for("settings_page"))


@app.route("/settings/branding/<kind>/delete", methods=["POST"])
def branding_delete(kind):
    path = branding_file(kind) if kind in ("logo", "signature") else None
    if path:
        os.remove(path)
        audit("branding_removed", kind)
        get_db().commit()
    return redirect(url_for("settings_page"))


@app.route("/branding/<kind>.png")
def branding_image(kind):
    path = branding_file(kind) if kind in ("logo", "signature") else None
    if not path:
        abort(404)
    return send_file(path, mimetype="image/png", max_age=0)


@app.route("/settings/licence", methods=["GET", "POST"])
def licence_page():
    if request.method == "POST":
        text = request.form.get("licence_text", "").strip()
        upload = request.files.get("licence_file")
        if upload and upload.filename:
            text = upload.read().decode("utf-8", "ignore").strip()
        try:
            p = lic.install(text)
            audit("licence_installed", f"{p.get('lab')} until {p.get('expires')}")
            get_db().commit()
            flash(f"Licence installed: valid until {p['expires']}", "ok")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("licence_page"))
    return render_template("licence.html", st=lic.status(get_settings()), machine_id=lic.machine_id())


# --------------------------------------------------------------------------- backup & restore
@app.route("/backup", methods=["GET", "POST"])
def backup_page():
    db = get_db()
    if request.method == "POST":
        dbm.set_setting("backup_dir", request.form.get("backup_dir", "").strip())
        keep = fint(request.form.get("backup_keep"), 30)
        dbm.set_setting("backup_keep", str(min(max(keep, 3), 365)))
        audit("backup_settings_saved", request.form.get("backup_dir", ""))
        db.commit()
        flash("Backup settings saved. Click 'Back up now' to test the folder.", "ok")
        return redirect(url_for("backup_page"))
    s = get_settings()
    month = date.today().strftime("%Y-%m")
    m = db.execute("SELECT COUNT(*) AS visits, COUNT(DISTINCT patient_id) AS patients, "
                   "SUM(status='Completed') AS reports FROM visits WHERE substr(visit_date,1,7)=?", (month,)).fetchone()
    health = bk.status(s)
    summary = (f"{s['lab_name']} - monthly software check ({date.today():%d %b %Y})\n"
               f"Visits this month: {m['visits']}, patients: {m['patients']}, reports approved: {m['reports'] or 0}\n"
               f"Last backup on this PC: {health['local_last'] or 'never'}\n"
               f"Last external backup: {health['external_last'] or 'never'}\n"
               f"Backup status: {'OK' if health['ok'] else 'ATTENTION - ' + ' '.join(health['problems'])}\n"
               f"Database size: {os.path.getsize(dbm.DB_PATH) // 1024} KB, software version {__version__}")
    return render_template("backup.html", backups=bk.list_backups(db), health=health, summary=summary,
                           db_path=dbm.DB_PATH)


@app.route("/backup/now", methods=["POST"])
def backup_now():
    res = bk.run_backup("manual")
    for label, path, err in res:
        flash(f"{label}: {'saved ' + os.path.basename(path) if not err else 'FAILED - ' + err}",
              "error" if err else "ok")
    return redirect(url_for("backup_page"))


def _backup_path(name):
    for b in bk.list_backups(get_db()):
        if b["name"] == name and b["where"] == request.values.get("where"):
            return b["path"]
    abort(404)


@app.route("/backup/download")
def backup_download():
    path = _backup_path(request.args.get("name", ""))
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.route("/backup/restore", methods=["POST"])
def backup_restore():
    path = _backup_path(request.form.get("name", ""))
    if request.form.get("confirm") != "RESTORE":
        flash("Type RESTORE in capitals to confirm.", "error")
        return redirect(url_for("backup_page"))
    dbm.close_db()
    try:
        bk.restore(path)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("backup_page"))
    conn = dbm.connect()
    conn.execute("INSERT INTO audit_log(ts, username, action, details) VALUES (?,?,?,?)",
                 (now(), current_user()["username"], "backup_restored", os.path.basename(path)))
    conn.commit()
    conn.close()
    session.clear()
    flash("Data restored from backup. A safety copy of the previous data was saved first. Please log in again.", "ok")
    return redirect(url_for("login"))


@app.errorhandler(404)
def not_found(_e):
    return render_template("message.html", title="Not found", message="That record does not exist."), 404


@app.errorhandler(400)
def bad_request(e):
    return render_template("message.html", title="Please try again", message=e.description), 400


@app.errorhandler(403)
def forbidden(_e):
    return render_template("message.html", title="Not allowed",
                           message="Your account does not have permission for this action."), 403
