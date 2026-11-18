# PyInstaller build recipe.  Run from the repository root:
#     pyinstaller packaging/BalajiXRays.spec --noconfirm
import os

root = os.path.abspath(os.path.join(SPECPATH, ".."))
datas = [
    (os.path.join(root, "bethesda", "templates"), "bethesda/templates"),
    (os.path.join(root, "bethesda", "static"), "bethesda/static"),
]
pub = os.path.join(root, "bethesda", "licence_pubkey.pem")
if os.path.exists(pub):
    datas.append((pub, "bethesda"))
else:
    print("WARNING: bethesda/licence_pubkey.pem not found - this build will have licensing switched OFF.")

a = Analysis(
    [os.path.join(SPECPATH, "BalajiXRays.py")],
    pathex=[root],
    datas=datas,
    hiddenimports=["pystray._win32", "waitress", "PIL.ImageDraw"],
    excludes=["tkinter", "unittest", "pydoc_data"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="BalajiXRays",
    icon=os.path.join(SPECPATH, "icon.ico"),
    console=False,          # no black console window
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="BalajiXRays", upx=False)
