"""
Starts Bethesda Labs like a desktop application:
  * runs the web server quietly in the background (only one copy at a time)
  * opens the app in its own window (Edge/Chrome "app mode": no address bar or tabs)
  * puts an icon in the system tray: Open / Back up now / Quit
  * runs the daily automatic backup

    BethesdaLabs.exe              normal start (opens the window)
    BethesdaLabs.exe --background start without opening a window (used at Windows start-up)
    BethesdaLabs.exe --lan        also allow other PCs on the lab network
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

from . import db as dbm

APP_ID = b"bethesda-labs"


def _log_to_file():
    """A windowed .exe has no console; send output to a log file for support."""
    if sys.stdout is None or sys.stderr is None:
        logdir = os.path.join(dbm.DATA_DIR, "logs")
        os.makedirs(logdir, exist_ok=True)
        f = open(os.path.join(logdir, "app.log"), "a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stdout or f
        sys.stderr = sys.stderr or f


def is_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1.5) as r:
            return r.read() == APP_ID
    except Exception:  # noqa: BLE001
        return False


def _app_browser():
    if os.name == "nt":
        roots = [os.environ.get(k, "") for k in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA")]
        for rel in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            for root in roots:
                p = os.path.join(root, rel)
                if root and os.path.exists(p):
                    return p
    elif sys.platform == "darwin":
        for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
            if os.path.exists(p):
                return p
    else:
        for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser"):
            p = shutil.which(name)
            if p:
                return p
    return None


def open_window(port):
    url = f"http://127.0.0.1:{port}/"
    exe = _app_browser()
    if exe:
        profile = os.path.join(dbm.DATA_DIR, "window-profile")
        try:
            subprocess.Popen([exe, f"--app={url}", "--window-size=1400,900", f"--user-data-dir={profile}",
                              "--no-first-run", "--no-default-browser-check"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)


def _tray(port):
    """System-tray icon. Returns False if no tray is available (e.g. a server without a desktop)."""
    try:
        import pystray
        from PIL import Image
    except Exception:  # noqa: BLE001 - pystray raises various errors when no desktop exists
        return False
    from . import backup as bk
    here = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    image = Image.open(os.path.join(here, "bethesda", "static", "icon.png"))

    def do_backup(icon, _item):
        res = bk.run_backup("manual")
        bad = [f"{label}: {err}" for label, _, err in res if err]
        try:
            icon.notify("Backup failed - " + "; ".join(bad) if bad else "Backup completed", "Bethesda Labs")
        except Exception:  # noqa: BLE001
            pass

    def quit_app(icon, _item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(pystray.MenuItem("Open Bethesda Labs", lambda i, _: open_window(port), default=True),
                        pystray.MenuItem("Back up now", do_backup),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem("Quit (stop the software)", quit_app))
    try:
        pystray.Icon("BethesdaLabs", image, "Bethesda Labs", menu).run()
        return True
    except Exception:  # noqa: BLE001
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bethesda Labs")
    ap.add_argument("--port", type=int, default=int(os.environ.get("BETHESDA_PORT", 5000)))
    ap.add_argument("--lan", action="store_true", help="allow other computers on the lab network")
    ap.add_argument("--background", "--no-browser", dest="background", action="store_true",
                    help="start without opening a window")
    ap.add_argument("--no-tray", action="store_true", help="run in this console instead of the system tray")
    args = ap.parse_args(argv)
    _log_to_file()

    if is_running(args.port):          # already running: just bring up a window
        if not args.background:
            open_window(args.port)
        return

    from waitress import serve

    from . import backup as bk
    from .app import app
    dbm.init_db()
    conn = dbm.connect()
    lan = args.lan or dbm.get_settings(conn).get("allow_lan") == "1"
    conn.close()
    host = "0.0.0.0" if lan else "127.0.0.1"

    server = threading.Thread(target=serve, kwargs=dict(app=app, host=host, port=args.port, threads=8),
                              name="web-server", daemon=True)
    server.start()
    for _ in range(50):
        if is_running(args.port):
            break
        time.sleep(0.2)
    else:
        print(f"Could not start on port {args.port}. Is another program using it?")
        sys.exit(1)
    bk.start_scheduler()

    print("=" * 60)
    print(f" Bethesda Labs is running: http://127.0.0.1:{args.port}")
    if lan:
        print(f" Other PCs on the lab network: http://<this-PC's-IP>:{args.port}")
    print(f" Data folder: {dbm.DATA_DIR}")
    print("=" * 60)
    if not args.background:
        open_window(args.port)
    if args.no_tray or not _tray(args.port):
        print(" Keep this window open. Press Ctrl+C to stop.")
        try:
            while server.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
