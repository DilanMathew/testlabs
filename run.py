"""
Start Bethesda Labs locally.

    python run.py                 -> http://127.0.0.1:5000 (this computer only)
    python run.py --lan           -> also reachable from other PCs on the same network
    python run.py --port 8080     -> use a different port
"""
import argparse
import threading
import webbrowser

from bethesda.app import app
from bethesda.db import DB_PATH, init_db


def main():
    ap = argparse.ArgumentParser(description="Bethesda Labs - local lab management")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--lan", action="store_true", help="allow access from other computers on your network")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    init_db()
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    url = f"http://127.0.0.1:{args.port}"
    print("=" * 60)
    print(" Bethesda Labs is running")
    print(f" Open in your browser: {url}")
    if args.lan:
        print(f" Other computers on your network: http://<this-PC's-IP>:{args.port}")
    print(f" Data file: {DB_PATH}")
    print(" Keep this window open. Press Ctrl+C to stop.")
    print("=" * 60)
    if not args.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    try:
        from waitress import serve
        serve(app, host=host, port=args.port, threads=8)
    except ImportError:
        app.run(host=host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
