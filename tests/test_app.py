"""End-to-end test of the whole app.  Run:  python tests/test_app.py"""
import os, re, sys, shutil, io, json, tempfile
from datetime import date, timedelta
TMP = tempfile.mkdtemp(prefix="bethesda_test_")
D = os.path.join(TMP, "data")
os.environ["BETHESDA_DATA_DIR"] = D
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bethesda.db import init_db, connect
init_db()
from bethesda.app import app
from bethesda import licence as lic, backup as bk
app.config["TESTING"] = False
PASS = []
def check(cond, msg):
    assert cond, msg
    PASS.append(msg)

def tok(c, url="/login"):
    html = c.get(url).data.decode()
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1)

def post(c, url, data, page=None, **kw):
    data = dict(data); data["csrf_token"] = tok(c, page or url)
    return c.post(url, data=data, **kw)

adm = app.test_client()
# 1. first run setup
r = adm.get("/"); check(r.status_code == 302 and "/setup" in r.headers["Location"], "fresh install redirects to setup")
r = adm.post("/setup", data={"username":"doc"}); check(r.status_code == 400, "POST without CSRF token rejected")
r = post(adm, "/setup", {"lab_name":"Bethesda Labs","full_name":"Dr. Ravi","username":"doc","password":"short","password2":"short"})
check(b"at least 6" in r.data, "short password rejected")
r = post(adm, "/setup", {"lab_name":"Bethesda Labs","full_name":"Dr. Ravi","username":"doc","password":"secret123","password2":"secret123"})
check(r.status_code == 302, "admin created at setup")
check(adm.get("/setup").status_code == 302, "setup disabled after first account")
# 2. users
r = post(adm, "/users/new", {"full_name":"Tech Anu","username":"anu","role":"technician","password":"tech1234","active":"1"})
check(r.status_code == 302, "technician created")
r = post(adm, "/users/new", {"full_name":"Dup","username":"ANU","role":"technician","password":"tech1234","active":"1"})
check(b"already taken" in r.data, "duplicate username (case-insensitive) rejected")
# demoting last admin blocked
r = post(adm, "/users/1/edit", {"full_name":"Dr. Ravi","username":"doc","role":"technician","active":"1"})
check(b"at least one active" in r.data, "cannot demote the last admin")
# 3. referrers + branding
post(adm, "/hospitals/new", {"name":"City Care","commission_pct":"15","active":"1"})
post(adm, "/doctors/new", {"name":"Dr. Meera","commission_pct":"12","active":"1"})
from PIL import Image
for kind, size, col in [("logo",(400,200),(11,94,126)),("signature",(500,150),(20,20,120))]:
    b = io.BytesIO(); Image.new("RGB", size, col).save(b, "PNG"); b.seek(0)
    r = adm.post("/settings/branding", data={"csrf_token":tok(adm,"/settings"),"kind":kind,"image":(b, f"{kind}.png")}, content_type="multipart/form-data")
    check(os.path.exists(f"{D}/branding/{kind}.png"), f"{kind} uploaded")
b = io.BytesIO(b"not an image")
r = adm.post("/settings/branding", data={"csrf_token":tok(adm,"/settings"),"kind":"logo","image":(b,"x.png")}, content_type="multipart/form-data", follow_redirects=True)
check(b"not a readable image" in r.data, "invalid image rejected")

# 4. technician
tech = app.test_client()
r = post(tech, "/login", {"username":"anu","password":"wrong"}); check(b"Wrong username" in r.data, "wrong password rejected")
r = post(tech, "/login", {"username":"anu","password":"tech1234"}); check(r.status_code == 302, "technician logs in")
for url in ["/commissions","/doctors","/hospitals","/settings","/users","/backup","/audit","/settings/licence","/tests/1/edit","/commissions.csv"]:
    r = tech.get(url); check(r.status_code == 302 and r.headers["Location"].endswith("/"), f"technician blocked from {url}")
html = tech.get("/").data.decode(); check("Unpaid commission" not in html and "Commissions" not in html, "technician dashboard hides commissions")
r = post(tech, "/visits/new", {"name":"Priya","age":"34","gender":"Female","referral_type":"Doctor","doctor_id":"1",
      "doctor_commission_pct":"50","test_ids":["1","15"],"paid_amount":"500","payment_mode":"Cash"})
check(r.status_code == 302, "technician registers visit")
c = connect(); v = c.execute("select * from visits where id=1").fetchone()
check(v["doctor_commission_pct"] == 12 and v["created_by"] == "anu", "technician cannot override commission %; created_by recorded")
check(b"Commission" not in tech.get("/visits/1").data.replace(b"commission %",b""), "technician visit page hides commission")
params = c.execute("select p.id, p.ref_low, p.ref_high, p.options from visit_tests vt join parameters p on p.test_id=vt.test_id where vt.visit_id=1").fetchall()
form = {f"p_{p['id']}": (p["options"].split("|")[0] if p["options"] else (str(p["ref_high"]*1.5) if p["ref_high"] else str((p["ref_low"] or 1)*1.1))) for p in params}
form["remarks"] = "check"
r = post(tech, "/visits/1/results", dict(form, action="approve")); check(r.status_code == 403, "technician cannot approve")
r = post(tech, "/visits/1/results", dict(form, action="submit")); check(r.status_code == 302, "technician submits for approval")
check(connect().execute("select status from visits where id=1").fetchone()[0] == "Awaiting Approval", "status Awaiting Approval")
check(tech.get("/visits/1/edit").status_code == 302, "billing edit locked after submission")
pdf = tech.get("/visits/1/report.pdf"); check(pdf.data[:4] == b"%PDF" and "DRAFT" in pdf.headers["Content-Disposition"], "draft PDF before approval")
open(os.path.join(TMP, "draft.pdf"),"wb").write(pdf.data)

# 5. admin approves
r = post(adm, "/visits/1/results", dict(form, action="approve")); check(r.status_code == 302, "admin approves")
v = connect().execute("select * from visits where id=1").fetchone()
check(v["status"] == "Completed" and v["report_version"] == 1 and v["approved_by"] == "Dr. Ravi", "approved v1 recorded")
first_val = list(form.items())[0]
r = post(adm, "/visits/1/results", dict(form, action="draft"), page="/visits/1"); check(b"" == b"" and connect().execute("select status from visits where id=1").fetchone()[0]=="Completed", "approved report rejects edits")
check(post(adm, "/visits/1/delete", {}, page="/visits/1").status_code == 302 and connect().execute("select count(*) from visits").fetchone()[0]==1, "approved visit cannot be deleted")
pdf1 = adm.get("/visits/1/report.pdf"); check("DRAFT" not in pdf1.headers["Content-Disposition"], "final PDF after approval")
open(os.path.join(TMP, "final_v1.pdf"),"wb").write(pdf1.data)
# 6. amend
r = post(adm, "/visits/1/amend", {"reason":"no"}, page="/visits/1"); check(connect().execute("select status from visits where id=1").fetchone()[0]=="Completed", "amend needs a reason")
r = post(adm, "/visits/1/amend", {"reason":"Haemoglobin value typed wrongly"}, page="/visits/1")
check(connect().execute("select status from visits where id=1").fetchone()[0]=="Amending", "amend unlocks report")
k = list(form)[0]; form2 = dict(form); form2[k] = "13.5"
post(adm, "/visits/1/results", dict(form2, action="approve"), page="/visits/1/results")
vs = connect().execute("select version, amend_reason from report_versions where visit_id=1 order by version").fetchall()
check([tuple(x) for x in vs] == [(1,None),(2,"Haemoglobin value typed wrongly")], "version 2 stored with reason")
old = json.loads(connect().execute("select sections_json from report_versions where version=1").fetchone()[0])
check(old[0]["rows"][0]["value"] != "13.5", "version 1 snapshot unchanged")
pdf2 = adm.get("/visits/1/report.pdf"); open(os.path.join(TMP, "final_v2.pdf"),"wb").write(pdf2.data)
pdfold = adm.get("/visits/1/report.pdf?v=1"); open(os.path.join(TMP, "superseded_v1.pdf"),"wb").write(pdfold.data)
check("_v2" in pdf2.headers["Content-Disposition"], "current PDF is version 2")
rc = adm.get("/visits/1/receipt.pdf"); check(rc.data[:4]==b"%PDF", "receipt with logo")

# 7. backup + restore
ext = os.path.join(TMP, "usb", "BethesdaBackup"); os.makedirs(os.path.join(TMP, "usb"))
post(adm, "/backup", {"backup_dir": ext, "backup_keep":"5"})
r = post(adm, "/backup/now", {}, page="/backup", follow_redirects=True)
check(len(os.listdir(ext)) == 1 and len(os.listdir(f"{D}/backups")) == 1, "backup written to PC and external folder")
from bethesda.db import get_settings
with app.app_context():
    check(bk.status(get_settings())["ok"], "backup health OK")
post(adm, "/backup", {"backup_dir": os.path.join(TMP, "no_such_drive", "Backup"), "backup_keep":"5"})
res = bk.run_backup("test"); check(any(e and "not found" in e for _,_,e in res), "missing USB drive reported")
post(adm, "/backup", {"backup_dir": ext, "backup_keep":"5"})
for i in range(7): bk.run_backup("test")
check(len(os.listdir(ext)) <= 5, "old backups pruned to keep count")
post(tech, "/visits/new", {"name":"After Backup","referral_type":"Self","test_ids":["2"]})
n_before = connect().execute("select count(*) from visits").fetchone()[0]
name = sorted(os.listdir(ext))[-1]
# a backup taken BEFORE the "After Backup" visit: use the earliest in local
lst = [b for b in bk.list_backups(connect()) if b["where"]=="This PC"]
target = lst[-1]  # oldest
r = post(adm, "/backup/restore", {"name": target["name"], "where": "This PC", "confirm":"nope"}, page="/backup", follow_redirects=True)
check(b"Type RESTORE" in r.data, "restore needs confirmation")
r = post(adm, "/backup/restore", {"name": target["name"], "where": "This PC", "confirm":"RESTORE"}, page="/backup")
n_after = connect().execute("select count(*) from visits").fetchone()[0]
check(n_before == 2 and n_after == 1, f"restore brought back old data ({n_before}->{n_after})")
check(adm.get("/").status_code == 302, "logged out after restore")
post(adm, "/login", {"username":"doc","password":"secret123"})
check(adm.get("/").status_code == 200, "admin logs in again after restore")
r = adm.get("/backup/download?name=../../etc/passwd&where=This PC"); check(r.status_code == 404, "backup download path traversal blocked")

# 8. licence
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
key = Ed25519PrivateKey.generate()
pub = os.path.join(TMP, "pub.pem")
open(pub,"wb").write(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
lic.PUBKEY_PATH = pub
c = connect()
def setinst(days):
    c.execute("update settings set value=? where key='installed_on'", ((date.today()-timedelta(days=days)).isoformat(),)); c.commit()
setinst(5); check(lic.status({"installed_on":(date.today()-timedelta(days=5)).isoformat()})["state"]=="trial", "trial state")
setinst(40)
r = adm.get("/visits/new"); check(b"New visits are paused" in r.data, "expired trial blocks new visits")
check(adm.get("/visits/1/report.pdf").data[:4]==b"%PDF" and adm.get("/patients/1").status_code==200, "old reports & patients still open when blocked")
def install(exp, machine="*", grace=30, k=key):
    t = lic.sign(k, "Bethesda Labs", exp, machine, grace)
    return post(adm, "/settings/licence", {"licence_text": t}, follow_redirects=True)
r = install((date.today()+timedelta(days=200)).isoformat(), machine="AAAA-BBBB-CCCC-DDDD")
check(lic.status()["state"]=="wrong_machine", "licence for another PC rejected")
r = install((date.today()+timedelta(days=200)).isoformat(), machine=lic.machine_id())
check(lic.status()["state"]=="valid" and adm.get("/visits/new").status_code==200, "valid licence allows new visits")
install((date.today()-timedelta(days=10)).isoformat())
check(lic.status()["state"]=="grace" and b"New visits are paused" not in adm.get("/visits/new").data, "grace period still allows visits")
install((date.today()-timedelta(days=45)).isoformat())
check(lic.status()["state"]=="expired" and b"New visits are paused" in adm.get("/visits/new").data, "expired past grace blocks new visits")
r = post(adm, "/settings/licence", {"licence_text": lic.sign(Ed25519PrivateKey.generate(), "Fake", "2099-01-01")}, follow_redirects=True)
check(b"signature is not valid" in r.data and lic.status()["state"]=="expired", "forged licence rejected")
install((date.today()+timedelta(days=365)).isoformat())

# 9. lockout
bad = app.test_client()
for i in range(5): post(bad, "/login", {"username":"anu","password":"x"})
r = post(bad, "/login", {"username":"anu","password":"tech1234"}); check(b"Too many wrong attempts" in r.data, "account locked after 5 wrong passwords")
# 10. audit + all admin pages
html = adm.get("/audit").data.decode()
for a in ["report approved","report amend started","visit created","backup restored","licence installed","login failed","payment"] :
    pass
check("report approved" in html and "backup restored" in html and "licence installed" in html, "audit log records key actions")
for url in ["/","/visits","/patients","/patients/1","/visits/1","/visits/1/results","/visits/new","/doctors","/hospitals","/commissions","/tests","/tests/1/edit","/packages","/packages/1/edit","/settings","/users","/users/2/edit","/backup","/settings/licence","/audit","/account","/branding/logo.png"]:
    r = adm.get(url); check(r.status_code == 200, f"admin GET {url}")
# technician can still view approved report & results read-only
check(b"Approved results" in tech.get("/visits/1/results").data, "technician sees approved results read-only")
# logout
post(adm, "/logout", {}, page="/"); check(adm.get("/visits").status_code == 302, "logout works")
print(f"ALL {len(PASS)} CHECKS PASSED")
shutil.rmtree(TMP, ignore_errors=True)
