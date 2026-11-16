import csv
import io
import os
import sqlite3
from datetime import date, datetime

from flask import (Flask, Response, abort, flash, redirect, render_template, request, send_file,
                   url_for)

from . import db as dbm
from .db import get_db, get_settings, next_number, now
from .pdf_report import build_receipt, build_report
from .ranges import FLAG_LABEL, compute_flag, limits_for, range_text

app = Flask(__name__)
app.secret_key = os.environ.get("BETHESDA_SECRET", "bethesda-local-only-secret")
app.teardown_appcontext(dbm.close_db)


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
    return {"settings": get_settings(), "today": date.today().isoformat(), "FLAG_LABEL": FLAG_LABEL}


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
    unpaid_comm = db.execute("""
        SELECT COALESCE(SUM(CASE WHEN doctor_commission_paid_on IS NULL THEN doctor_commission ELSE 0 END),0)
             + COALESCE(SUM(CASE WHEN hospital_commission_paid_on IS NULL THEN hospital_commission ELSE 0 END),0)
        FROM visits""").fetchone()[0]
    dues = db.execute("SELECT COALESCE(SUM(net_amount-paid_amount),0) FROM visits WHERE net_amount>paid_amount").fetchone()[0]
    recent = db.execute(VISIT_SELECT + " ORDER BY v.id DESC LIMIT 12").fetchall()
    return render_template("dashboard.html", stats=stats, mstats=mstats, pending=pending,
                           unpaid_comm=unpaid_comm, dues=dues, recent=recent)


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

    d_pct = h_pct = 0.0
    if doctor_id:
        d_pct = fnum(form.get("doctor_commission_pct"))
        if d_pct is None:
            d_pct = db.execute("SELECT commission_pct FROM doctors WHERE id=?", (doctor_id,)).fetchone()[0]
    if hospital_id:
        h_pct = fnum(form.get("hospital_commission_pct"))
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
                      status="Registered", created_at=now())
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
    db.commit()
    return visit_id


@app.route("/visits/new", methods=["GET", "POST"])
def visit_new():
    db = get_db()
    patient = None
    pid = fint(request.values.get("patient_id"))
    if pid:
        patient = db.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
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
    n_results = get_db().execute("SELECT COUNT(*) FROM results WHERE visit_id=? AND value IS NOT NULL AND value!=''",
                                 (vid,)).fetchone()[0]
    return render_template("visit_detail.html", v=visit, pkgs=pkgs, tests=tests, n_results=n_results)


@app.route("/visits/<int:vid>/status", methods=["POST"])
def visit_status(vid):
    db = get_db()
    status = request.form.get("status")
    if status == "Sample Collected":
        db.execute("UPDATE visits SET status=?, sample_collected_at=? WHERE id=?", (status, now(), vid))
    elif status in ("Registered", "Completed"):
        db.execute("UPDATE visits SET status=? WHERE id=?", (status, vid))
    db.commit()
    return redirect(url_for("visit_detail", vid=vid))


@app.route("/visits/<int:vid>/payment", methods=["POST"])
def visit_payment(vid):
    db = get_db()
    add = max(fnum(request.form.get("amount"), 0), 0)
    db.execute("UPDATE visits SET paid_amount=paid_amount+?, payment_mode=COALESCE(?, payment_mode) WHERE id=?",
               (add, request.form.get("payment_mode") or None, vid))
    db.commit()
    flash(f"Payment of {add:,.2f} recorded", "ok")
    return redirect(url_for("visit_detail", vid=vid))


@app.route("/visits/<int:vid>/delete", methods=["POST"])
def visit_delete(vid):
    db = get_db()
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


@app.route("/visits/<int:vid>/results", methods=["GET", "POST"])
def results(vid):
    db = get_db()
    v = load_visit(vid)
    if request.method == "POST":
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
        if request.form.get("action") == "complete":
            db.execute("UPDATE visits SET status='Completed', reported_at=?, "
                       "sample_collected_at=COALESCE(sample_collected_at, visit_date) WHERE id=?", (now(), vid))
            flash("Results saved and report marked as completed", "ok")
        else:
            if v["status"] == "Registered":
                db.execute("UPDATE visits SET status='Sample Collected', sample_collected_at=? WHERE id=?", (now(), vid))
            flash("Results saved (draft)", "ok")
        db.commit()
        return redirect(url_for("visit_detail", vid=vid))
    sections = report_sections(vid, v["gender"], live=True)
    saved = {r["parameter_id"]: r["value"] for r in db.execute("SELECT * FROM results WHERE visit_id=?", (vid,))}
    for s in sections:
        for r in s["rows"]:
            r["value"] = saved.get(r["pid"], "")
            r["range"] = range_text(r["low"], r["high"], r["ref_text"], r["normal_value"])
    return render_template("results_form.html", v=v, sections=sections)


def _pdf_response(data, filename, download):
    return Response(data, mimetype="application/pdf", headers={
        "Content-Disposition": f'{"attachment" if download else "inline"}; filename="{filename}"'})


@app.route("/visits/<int:vid>/report.pdf")
def report_pdf(vid):
    db = get_db()
    v = load_visit(vid)
    patient = db.execute("SELECT * FROM patients WHERE id=?", (v["patient_id"],)).fetchone()
    sections = report_sections(vid, v["gender"])
    pdf = build_report(get_settings(), v, patient, referred_by(v), sections)
    safe = "".join(c for c in patient["name"] if c.isalnum() or c in " -_").strip().replace(" ", "_")
    return _pdf_response(pdf, f"{v['visit_no']}_{safe}.pdf", request.args.get("download"))


@app.route("/visits/<int:vid>/receipt.pdf")
def receipt_pdf(vid):
    db = get_db()
    v = load_visit(vid)
    patient = db.execute("SELECT * FROM patients WHERE id=?", (v["patient_id"],)).fetchone()
    pkgs, tests = visit_items(vid)
    lines = [(f"Package: {p['name']}", p["price"]) for p in pkgs]
    lines += [(f"{t['name']} ({t['code']})", t["price"]) for t in tests if not t["visit_package_id"]]
    pdf = build_receipt(get_settings(), v, patient, referred_by(v), lines)
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
        db.commit()
        flash("Package saved", "ok")
        return redirect(url_for("packages"))
    sel = {r[0] for r in db.execute("SELECT test_id FROM package_tests WHERE package_id=?", (pkid,))} if pkid else set()
    all_tests = db.execute("SELECT * FROM tests WHERE active=1 ORDER BY category, name").fetchall()
    return render_template("package_form.html", pk=pk, sel=sel, tests=all_tests)


# --------------------------------------------------------------------------- settings & backup
@app.route("/settings", methods=["GET", "POST"])
def settings_page():
    db = get_db()
    if request.method == "POST":
        for k in dbm.DEFAULT_SETTINGS:
            if k in request.form:
                db.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                           (k, request.form[k].strip()))
        db.commit()
        flash("Settings saved", "ok")
        return redirect(url_for("settings_page"))
    return render_template("settings.html", db_path=dbm.DB_PATH)


@app.route("/backup")
def backup():
    backup_dir = os.path.join(dbm.DATA_DIR, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    path = os.path.join(backup_dir, f"bethesda_backup_{datetime.now():%Y%m%d_%H%M%S}.db")
    dest = sqlite3.connect(path)
    get_db().backup(dest)
    dest.close()
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@app.errorhandler(404)
def not_found(_e):
    return render_template("message.html", title="Not found", message="That record does not exist."), 404
