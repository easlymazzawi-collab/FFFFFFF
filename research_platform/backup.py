"""Local backup: safe SQLite copy + masked config + archive index -> ZIP.

A2/A1 spec: archive keeps link + metadata only (no media forwarded). Backups
never contain raw media — only the DB, the masked config and a JSON index.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import zipfile
from typing import Any, Dict, List

from core import config_store
from research_platform import db

BACKUP_DIR = os.path.join(db.DATA_DIR, "backups")
_KEEP = 10  # rotate: keep last N


def _safe_sqlite_copy(dest: str) -> None:
    """Copy the live DB consistently using the SQLite backup API."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    src = sqlite3.connect(db.DB_PATH)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _archive_index_json() -> Dict[str, Any]:
    out: Dict[str, Any] = {"days": []}
    for day in db.list_days(limit=10_000):
        items = db.list_day_items(day["id"])
        out["days"].append({**day, "items": items})
    return out


def create_backup_file() -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    db.init_db()
    ts = time.strftime("%Y%m%d-%H%M%S")
    zip_path = os.path.join(BACKUP_DIR, f"backup-{ts}.zip")
    tmp_db = os.path.join(BACKUP_DIR, f"platform-{ts}.db")
    _safe_sqlite_copy(tmp_db)

    masked = config_store.masked_config()
    index = _archive_index_json()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(tmp_db, arcname="platform.db")
        zf.writestr("auto_config.masked.json", json.dumps(masked, ensure_ascii=False, indent=2))
        zf.writestr("archive_index.json", json.dumps(index, ensure_ascii=False, indent=2))
    os.remove(tmp_db)
    _rotate()
    return zip_path


def list_backups() -> List[Dict[str, Any]]:
    if not os.path.isdir(BACKUP_DIR):
        return []
    out = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if name.endswith(".zip"):
            path = os.path.join(BACKUP_DIR, name)
            out.append({"name": name, "size": os.path.getsize(path)})
    return out


def backup_path(name: str) -> str | None:
    if "/" in name or "\\" in name or not name.endswith(".zip"):
        return None
    path = os.path.join(BACKUP_DIR, name)
    return path if os.path.isfile(path) else None


def _rotate() -> None:
    backups = [b["name"] for b in list_backups()]
    for stale in backups[_KEEP:]:
        try:
            os.remove(os.path.join(BACKUP_DIR, stale))
        except OSError:
            pass
