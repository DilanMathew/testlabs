"""
Developer tool: create licences for labs.  Run on YOUR computer only.

One time - create your signing keys:
    python tools/make_licence.py init
      -> private key: ~/.bethesda/licence_private.pem   (KEEP SECRET, back it up, never share or commit)
      -> public key : bethesda/licence_pubkey.pem       (commit this; it is built into the app)

Each lab / renewal:
    python tools/make_licence.py issue --lab "Bethesda Labs" --expires 2027-01-31 --machine ABCD-1234-EF56-7890
      (--machine = the "Computer ID" shown in the app under Settings -> Licence; omit to allow any PC)
      -> prints the licence text and saves <lab>_<expiry>.lic. Send the file or text to the lab.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

PRIV = os.path.join(os.path.expanduser("~"), ".bethesda", "licence_private.pem")
PUB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bethesda", "licence_pubkey.pem")


def init(_args):
    if os.path.exists(PRIV):
        sys.exit(f"Key already exists at {PRIV}. Not overwriting - old licences would stop working.")
    key = Ed25519PrivateKey.generate()
    os.makedirs(os.path.dirname(PRIV), exist_ok=True)
    with open(PRIV, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                  serialization.NoEncryption()))
    os.chmod(PRIV, 0o600)
    with open(PUB, "wb") as f:
        f.write(key.public_key().public_bytes(serialization.Encoding.PEM,
                                              serialization.PublicFormat.SubjectPublicKeyInfo))
    print(f"Private key saved to {PRIV}\n  -> BACK IT UP (e.g. a USB drive). If lost, you cannot issue licences.")
    print(f"Public key saved to {PUB}\n  -> commit it and rebuild the installer.")


def issue(a):
    from bethesda.licence import sign
    if not os.path.exists(PRIV):
        sys.exit("No private key. Run:  python tools/make_licence.py init")
    with open(PRIV, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    text = sign(key, a.lab, a.expires, a.machine or "*", a.grace)
    name = "".join(c if c.isalnum() else "_" for c in a.lab) + f"_{a.expires}.lic"
    with open(name, "w") as f:
        f.write(text + "\n")
    print(text)
    print(f"\nSaved to {name}. In the app: Settings -> Licence -> paste the text or upload the file.")


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = ap.add_subparsers(dest="cmd", required=True)
sub.add_parser("init").set_defaults(fn=init)
p = sub.add_parser("issue")
p.add_argument("--lab", required=True)
p.add_argument("--expires", required=True, help="YYYY-MM-DD")
p.add_argument("--machine", help="Computer ID from the app; omit for any computer")
p.add_argument("--grace", type=int, default=30, help="days after expiry before new visits are blocked")
p.set_defaults(fn=issue)
args = ap.parse_args()
args.fn(args)
