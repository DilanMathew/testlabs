"""Automatic daily backups to the lab PC and to an external folder (USB drive / cloud-synced folder)."""
import glob
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from . import db as dbm

PREFIX = "bethesda_backup_"
_lock = threading.Lock()


def _keep(conn):
    try:
        return max(int(dbm.get_settings(conn).get("backup_keep") or 30), 3)
    except ValueError:
        return 30


def folders(conn):
    """[(label, path)] the backup is written to. The external folder may be missing (USB unplugged)."""
    out = [("This PC", dbm.LOCAL_BACKUP_DIR)]
    ext = (dbm.get_settings(conn).get("backup_dir") or "").strip()
    if ext:
        out.append(("External", ext))
    return out


def _verify(path):
    c = sqlite3.connect(path)
    try:
        ok = c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        c.execute("SELECT COUNT(*) FROM visits").fetchone()
        return ok
    finally:
        c.close()


def _prune(folder, keep):
    files = sorted(glob.glob(os.path.join(folder, PREFIX + "*.db")))
    for f in files[:-keep]:
        try:
            os.remove(f)
        except OSError:
            pass


def run_backup(reason="auto"):
    """Back up to every configured folder. Returns a list of (label, path_or_None, error_or_None)."""
    with _lock:
        conn = dbm.connect()
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            keep = _keep(conn)
            results = []
            for label, folder in folders(conn):
                try:
                    parent = os.path.dirname(os.path.normpath(folder)) or folder
                    if label == "External" and not os.path.isdir(folder) and not os.path.isdir(parent):
                        raise OSError("Backup drive/folder not found - is the USB drive plugged in?")
                    os.makedirs(folder, exist_ok=True)
                    path = os.path.join(folder, f"{PREFIX}{stamp}.db")
                    n = 1
                    while os.path.exists(path):          # never overwrite an existing backup
                        n += 1
                        path = os.path.join(folder, f"{PREFIX}{stamp}_{n}.db")
                    dest = sqlite3.connect(path)
                    conn.backup(dest)
                    dest.close()
                    if not _verify(path):
                        raise OSError("Backup file failed its integrity check")
                    _prune(folder, keep)
                    results.append((label, path, None))
                except Exception as e:  # noqa: BLE001 - report any failure to the user
                    results.append((label, None, str(e)))
            ts = dbm.now()
            for label, path, err in results:
                key = "local" if label == "This PC" else "external"
                if err:
                    dbm.set_setting(f"backup_{key}_error", f"{ts}: {err}", conn)
                else:
                    dbm.set_setting(f"backup_{key}_last", ts, conn)
                    dbm.set_setting(f"backup_{key}_error", "", conn)
            conn.execute("INSERT INTO audit_log(ts, username, action, details) VALUES (?,?,?,?)",
                         (ts, None, "backup_" + reason,
                          "; ".join(f"{l}: {'OK' if not e else e}" for l, _, e in results)))
            conn.commit()
            return results
        finally:
            conn.close()


def list_backups(conn):
    out = []
    for label, folder in folders(conn):
        for f in sorted(glob.glob(os.path.join(folder, PREFIX + "*.db")), reverse=True):
            try:
                st = os.stat(f)
            except OSError:
                continue
            out.append(dict(where=label, path=f, name=os.path.basename(f), size_kb=round(st.st_size / 1024),
                            when=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")))
    return out


def restore(path):
    """Replace the live database with a backup (after taking a safety backup of the current data)."""
    if not _verify(path):
        raise ValueError("That backup file is damaged and cannot be restored.")
    # Load the chosen backup into memory first, so the safety backup below (which may prune
    # old files) can never touch the copy being restored.
    mem = sqlite3.connect(":memory:")
    src = sqlite3.connect(path)
    src.backup(mem)
    src.close()
    run_backup("before_restore")
    with _lock:
        live = dbm.connect()
        try:
            mem.backup(live)
        finally:
            mem.close()
            live.close()
    conn = dbm.connect()
    dbm.migrate(conn)
    conn.commit()
    conn.close()


def status(settings):
    """Health summary used on the dashboard and backup page."""
    def age_hours(ts):
        if not ts:
            return None
        return (datetime.now() - datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600

    local_age = age_hours(settings.get("backup_local_last"))
    ext_age = age_hours(settings.get("backup_external_last"))
    problems = []
    if local_age is None or local_age > 48:
        problems.append("No backup on this PC in the last 2 days.")
    if not settings.get("backup_dir"):
        problems.append("No external backup folder set (USB drive or cloud folder). "
                        "If this PC's disk fails, all data is lost.")
    elif ext_age is None or ext_age > 48:
        problems.append("External backup has not succeeded in the last 2 days. "
                        + (settings.get("backup_external_error") or ""))
    return dict(ok=not problems, problems=problems,
                local_last=settings.get("backup_local_last"), external_last=settings.get("backup_external_last"))


def _due(conn):
    last = dbm.get_settings(conn).get("backup_local_last")
    if not last:
        return True
    return datetime.now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S") > timedelta(hours=23)


def start_scheduler(check_every_seconds=1800):
    """Background thread: backup at start-up if due, then once a day while the app runs."""
    def loop():
        time.sleep(20)
        while True:
            try:
                conn = dbm.connect()
                due = _due(conn)
                conn.close()
                if due:
                    run_backup("auto")
            except Exception as e:  # noqa: BLE001
                print("Backup error:", e)
            time.sleep(check_every_seconds)
    t = threading.Thread(target=loop, name="backup-scheduler", daemon=True)
    t.start()
    return t
