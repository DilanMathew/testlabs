"""
Licence check.

A licence is a small signed text file issued by the developer with tools/make_licence.py.
It is signed with the developer's PRIVATE key (kept only on the developer's computer) and
checked here with the PUBLIC key in bethesda/licence_pubkey.pem.

Rules (matching the support agreement):
  * valid             -> everything works
  * expired, in grace -> everything works, a reminder banner is shown
  * expired past grace, missing after the trial, invalid or for another PC
                      -> NEW visits cannot be registered. Everything else, including all old
                         records and reports, keeps working. Data is never locked or deleted.
If no public key is bundled (developer has not set up licensing), licensing is switched off.
"""
import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import date, datetime

from . import db as dbm

TRIAL_DAYS = 30
PUBKEY_PATH = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                           "bethesda", "licence_pubkey.pem")
LICENCE_PATH = os.path.join(dbm.DATA_DIR, "licence.lic")


def machine_id():
    """Stable ID of this computer, shown to the developer when issuing a licence."""
    raw = ""
    try:
        if os.name == "nt":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography",
                                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                raw = winreg.QueryValueEx(k, "MachineGuid")[0]
        elif sys.platform == "darwin":
            out = subprocess.run(["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                                 capture_output=True, text=True, timeout=5).stdout
            raw = next((ln.split('"')[-2] for ln in out.splitlines() if "IOPlatformUUID" in ln), "")
        else:
            for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                if os.path.exists(p):
                    raw = open(p).read().strip()
                    break
    except Exception:  # noqa: BLE001
        raw = ""
    raw = raw or platform.node()
    h = hashlib.sha256(("bethesda:" + raw).encode()).hexdigest()[:16].upper()
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def _public_key():
    if not os.path.exists(PUBKEY_PATH):
        return None
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    with open(PUBKEY_PATH, "rb") as f:
        return load_pem_public_key(f.read())


def decode(text):
    """Parse and verify licence text. Returns the payload dict or raises ValueError."""
    key = _public_key()
    try:
        blob = json.loads(base64.b64decode("".join(text.split())).decode())
        payload_b = base64.b64decode(blob["payload"])
        sig = base64.b64decode(blob["sig"])
    except Exception as e:  # noqa: BLE001
        raise ValueError("This is not a valid licence file.") from e
    if key is None:
        raise ValueError("Licensing is not set up in this build.")
    try:
        key.verify(sig, payload_b)
    except Exception as e:  # noqa: BLE001
        raise ValueError("Licence signature is not valid.") from e
    return json.loads(payload_b)


def install(text):
    payload = decode(text)
    os.makedirs(dbm.DATA_DIR, exist_ok=True)
    with open(LICENCE_PATH, "w") as f:
        f.write(text.strip())
    return payload


def status(settings=None):
    """Dict with: state, blocks_new_visits, message, payload, days_left."""
    if _public_key() is None:
        return dict(state="off", blocks_new_visits=False, message="", payload=None, days_left=None)
    today = date.today()
    if not os.path.exists(LICENCE_PATH):
        installed = (settings or {}).get("installed_on") or today.isoformat()
        used = (today - date.fromisoformat(installed)).days
        left = TRIAL_DAYS - used
        if left >= 0:
            return dict(state="trial", blocks_new_visits=False, payload=None, days_left=left,
                        message=f"Trial version: {left} day(s) left. Please contact the developer for a licence.")
        return dict(state="missing", blocks_new_visits=True, payload=None, days_left=left,
                    message="No licence installed. New visits cannot be registered. "
                            "All existing records and reports remain available.")
    try:
        with open(LICENCE_PATH) as f:
            p = decode(f.read())
    except ValueError as e:
        return dict(state="invalid", blocks_new_visits=True, payload=None, days_left=None,
                    message=f"{e} New visits cannot be registered until a valid licence is installed.")
    mid = p.get("machine", "*")
    if mid not in ("*", machine_id()):
        return dict(state="wrong_machine", blocks_new_visits=True, payload=p, days_left=None,
                    message="This licence was issued for a different computer. Please contact the developer.")
    expires = date.fromisoformat(p["expires"])
    grace = int(p.get("grace_days", 30))
    left = (expires - today).days
    if left >= 0:
        msg = f"Licence renews on {p['expires']}." if left <= 15 else ""
        return dict(state="valid", blocks_new_visits=False, payload=p, days_left=left, message=msg)
    if -left <= grace:
        return dict(state="grace", blocks_new_visits=False, payload=p, days_left=left,
                    message=f"Licence expired on {p['expires']}. Please renew within {grace + left} day(s) "
                            f"to keep registering new visits.")
    return dict(state="expired", blocks_new_visits=True, payload=p, days_left=left,
                message=f"Licence expired on {p['expires']}. New visits cannot be registered. "
                        f"All existing records and reports remain available.")


def sign(private_key, lab, expires, machine="*", grace_days=30):
    """Used by tools/make_licence.py."""
    payload = json.dumps({"lab": lab, "machine": machine, "expires": expires, "grace_days": int(grace_days),
                          "issued": datetime.now().strftime("%Y-%m-%d")}, sort_keys=True).encode()
    sig = private_key.sign(payload)
    blob = json.dumps({"payload": base64.b64encode(payload).decode(), "sig": base64.b64encode(sig).decode()})
    text = base64.b64encode(blob.encode()).decode()
    return "\n".join(text[i:i + 64] for i in range(0, len(text), 64))
