"""SQLite data layer for the research platform.

Single file DB at ``data/platform.db``. All access goes through short-lived
connections (``check_same_thread=False`` not needed) which keeps things simple
and safe across the async web handlers and the bot threads.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterable, List, Optional

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "platform.db")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS bots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    token TEXT,
    source_forum_id TEXT,
    source_topic_id TEXT,
    queue_order INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS days (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT UNIQUE NOT NULL,           -- DD-MM-YYYY (VN)
    title TEXT,
    status TEXT DEFAULT 'draft',          -- draft|indexed|published|closed
    created_at TEXT,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS day_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_id INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    src_chat_id TEXT,
    src_msg_id INTEGER,
    album_msg_ids TEXT,                    -- JSON list
    caption TEXT,
    created_at TEXT,
    FOREIGN KEY (day_id) REFERENCES days(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id TEXT UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    is_vip INTEGER DEFAULT 0,
    vip_until TEXT,
    joined_at TEXT,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS user_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id TEXT NOT NULL,
    day_id INTEGER NOT NULL,
    last_seq_sent INTEGER DEFAULT 0,
    updated_at TEXT,
    UNIQUE (tg_user_id, day_id)
);

CREATE TABLE IF NOT EXISTS vip_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    days INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS gift_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    vip_days INTEGER NOT NULL,
    max_uses INTEGER DEFAULT 1,
    used_count INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS gift_redemptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL,
    tg_user_id TEXT NOT NULL,
    redeemed_at TEXT
);

CREATE TABLE IF NOT EXISTS ads_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    advertiser TEXT NOT NULL,
    alias TEXT,
    content TEXT,
    start_label TEXT,
    end_label TEXT,
    active INTEGER DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS share_refs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT UNIQUE NOT NULL,
    owner_tg_user_id TEXT NOT NULL,
    clicks INTEGER DEFAULT 0,
    joined INTEGER DEFAULT 0,
    created_at TEXT
);
"""


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def _rows(cur) -> List[Dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]


# ----------------------------------------------------------------- days
def upsert_day(label: str, title: Optional[str] = None) -> int:
    with connect() as conn:
        row = conn.execute("SELECT id FROM days WHERE label=?", (label,)).fetchone()
        if row:
            if title is not None:
                conn.execute("UPDATE days SET title=? WHERE id=?", (title, row["id"]))
            return row["id"]
        cur = conn.execute(
            "INSERT INTO days (label, title, status, created_at) VALUES (?,?,?,?)",
            (label, title or label, "draft", _now()),
        )
        return cur.lastrowid


def set_day_status(day_id: int, status: str) -> None:
    published_at = _now() if status == "published" else None
    with connect() as conn:
        conn.execute(
            "UPDATE days SET status=?, published_at=COALESCE(?, published_at) WHERE id=?",
            (status, published_at, day_id),
        )


def list_days(limit: int = 60) -> List[Dict[str, Any]]:
    with connect() as conn:
        cur = conn.execute(
            """
            SELECT d.*, (SELECT COUNT(*) FROM day_items i WHERE i.day_id=d.id) AS item_count
            FROM days d ORDER BY d.id DESC LIMIT ?
            """,
            (limit,),
        )
        return _rows(cur)


def get_day_by_label(label: str) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM days WHERE label=?", (label,)).fetchone()
        return dict(row) if row else None


def get_day(day_id: int) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM days WHERE id=?", (day_id,)).fetchone()
        return dict(row) if row else None


def latest_published_day() -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM days WHERE status='published' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


# ------------------------------------------------------------- day_items
def add_day_item(
    day_id: int,
    src_chat_id: str,
    src_msg_id: int,
    album_msg_ids: str = "[]",
    caption: str = "",
) -> int:
    with connect() as conn:
        seq_row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 AS nxt FROM day_items WHERE day_id=?",
            (day_id,),
        ).fetchone()
        seq = seq_row["nxt"]
        cur = conn.execute(
            """INSERT INTO day_items (day_id, seq, src_chat_id, src_msg_id, album_msg_ids,
               caption, created_at) VALUES (?,?,?,?,?,?,?)""",
            (day_id, seq, src_chat_id, src_msg_id, album_msg_ids, caption, _now()),
        )
        return cur.lastrowid


def list_day_items(day_id: int) -> List[Dict[str, Any]]:
    with connect() as conn:
        cur = conn.execute(
            "SELECT * FROM day_items WHERE day_id=? ORDER BY seq ASC", (day_id,)
        )
        return _rows(cur)


# ----------------------------------------------------------------- users
def upsert_user(tg_user_id: str, username: str = "", first_name: str = "") -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE tg_user_id=?", (tg_user_id,)
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET username=?, first_name=?, last_seen=? WHERE id=?",
                (username, first_name, _now(), row["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO users (tg_user_id, username, first_name, joined_at, last_seen)
                   VALUES (?,?,?,?,?)""",
                (tg_user_id, username, first_name, _now(), _now()),
            )


def list_users(limit: int = 200) -> List[Dict[str, Any]]:
    with connect() as conn:
        cur = conn.execute("SELECT * FROM users ORDER BY id DESC LIMIT ?", (limit,))
        return _rows(cur)


def grant_vip(tg_user_id: str, days: int) -> None:
    until = time.strftime("%Y-%m-%d", time.localtime(time.time() + days * 86400))
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE tg_user_id=?", (tg_user_id,)
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO users (tg_user_id, joined_at, last_seen) VALUES (?,?,?)",
                (tg_user_id, _now(), _now()),
            )
        conn.execute(
            "UPDATE users SET is_vip=1, vip_until=? WHERE tg_user_id=?",
            (until, tg_user_id),
        )


def revoke_vip(tg_user_id: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE users SET is_vip=0, vip_until=NULL WHERE tg_user_id=?", (tg_user_id,)
        )


def is_user_vip(tg_user_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT is_vip, vip_until FROM users WHERE tg_user_id=?", (tg_user_id,)
        ).fetchone()
    if not row or not row["is_vip"]:
        return False
    if row["vip_until"] and row["vip_until"] < time.strftime("%Y-%m-%d"):
        return False
    return True


# ------------------------------------------------------- user_deliveries
def get_last_seq(tg_user_id: str, day_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT last_seq_sent FROM user_deliveries WHERE tg_user_id=? AND day_id=?",
            (tg_user_id, day_id),
        ).fetchone()
        return row["last_seq_sent"] if row else 0


def set_last_seq(tg_user_id: str, day_id: int, seq: int) -> None:
    with connect() as conn:
        conn.execute(
            """INSERT INTO user_deliveries (tg_user_id, day_id, last_seq_sent, updated_at)
               VALUES (?,?,?,?)
               ON CONFLICT(tg_user_id, day_id)
               DO UPDATE SET last_seq_sent=excluded.last_seq_sent, updated_at=excluded.updated_at""",
            (tg_user_id, day_id, seq, _now()),
        )


# ------------------------------------------------------------------ bots
def upsert_bot(slug: str, **fields: Any) -> int:
    cols = {k: v for k, v in fields.items() if k in (
        "token", "source_forum_id", "source_topic_id", "queue_order", "enabled")}
    with connect() as conn:
        row = conn.execute("SELECT id FROM bots WHERE slug=?", (slug,)).fetchone()
        if row:
            if cols:
                sets = ", ".join(f"{k}=?" for k in cols)
                conn.execute(f"UPDATE bots SET {sets} WHERE id=?", (*cols.values(), row["id"]))
            return row["id"]
        cur = conn.execute(
            """INSERT INTO bots (slug, token, source_forum_id, source_topic_id,
               queue_order, enabled, created_at) VALUES (?,?,?,?,?,?,?)""",
            (
                slug,
                cols.get("token"),
                cols.get("source_forum_id"),
                cols.get("source_topic_id"),
                cols.get("queue_order", 0),
                cols.get("enabled", 1),
                _now(),
            ),
        )
        return cur.lastrowid


def list_bots() -> List[Dict[str, Any]]:
    with connect() as conn:
        cur = conn.execute("SELECT * FROM bots ORDER BY queue_order ASC, id ASC")
        return _rows(cur)


def delete_bot(bot_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM bots WHERE id=?", (bot_id,))


# ------------------------------------------------------------- vip_plans
def add_vip_plan(name: str, days: int, stars: int) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO vip_plans (name, days, stars, created_at) VALUES (?,?,?,?)",
            (name, days, stars, _now()),
        )
        return cur.lastrowid


def list_vip_plans() -> List[Dict[str, Any]]:
    with connect() as conn:
        return _rows(conn.execute("SELECT * FROM vip_plans ORDER BY stars ASC"))


def delete_vip_plan(plan_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM vip_plans WHERE id=?", (plan_id,))


# ------------------------------------------------------------ gift_codes
def add_gift_code(code: str, vip_days: int, max_uses: int) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO gift_codes (code, vip_days, max_uses, created_at) VALUES (?,?,?,?)",
            (code, vip_days, max_uses, _now()),
        )
        return cur.lastrowid


def list_gift_codes() -> List[Dict[str, Any]]:
    with connect() as conn:
        return _rows(conn.execute("SELECT * FROM gift_codes ORDER BY id DESC"))


def redeem_gift_code(code: str, tg_user_id: str) -> Dict[str, Any]:
    """Returns {'ok': bool, 'error'|'vip_days'}."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM gift_codes WHERE code=? AND active=1", (code,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "Mã không tồn tại hoặc đã khoá."}
        if row["used_count"] >= row["max_uses"]:
            return {"ok": False, "error": "Mã đã hết lượt dùng."}
        already = conn.execute(
            "SELECT 1 FROM gift_redemptions WHERE code=? AND tg_user_id=?",
            (code, tg_user_id),
        ).fetchone()
        if already:
            return {"ok": False, "error": "Bạn đã dùng mã này rồi."}
        conn.execute(
            "UPDATE gift_codes SET used_count=used_count+1 WHERE id=?", (row["id"],)
        )
        conn.execute(
            "INSERT INTO gift_redemptions (code, tg_user_id, redeemed_at) VALUES (?,?,?)",
            (code, tg_user_id, _now()),
        )
    grant_vip(tg_user_id, row["vip_days"])
    return {"ok": True, "vip_days": row["vip_days"]}


# --------------------------------------------------------- ads_contracts
def add_ads(advertiser: str, alias: str, content: str, start_label: str, end_label: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO ads_contracts (advertiser, alias, content, start_label,
               end_label, created_at) VALUES (?,?,?,?,?,?)""",
            (advertiser, alias, content, start_label, end_label, _now()),
        )
        return cur.lastrowid


def list_ads() -> List[Dict[str, Any]]:
    with connect() as conn:
        return _rows(conn.execute("SELECT * FROM ads_contracts ORDER BY id DESC"))


def revoke_ads(ad_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE ads_contracts SET active=0 WHERE id=?", (ad_id,))


def recheck_ads() -> int:
    """Deactivate contracts whose end_label (DD-MM-YYYY) is in the past. Returns count."""
    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=7))).date()
    changed = 0
    with connect() as conn:
        rows = conn.execute("SELECT id, end_label FROM ads_contracts WHERE active=1").fetchall()
        for r in rows:
            try:
                end = _dt.datetime.strptime(r["end_label"], "%d-%m-%Y").date()
            except (ValueError, TypeError):
                continue
            if end < today:
                conn.execute("UPDATE ads_contracts SET active=0 WHERE id=?", (r["id"],))
                changed += 1
    return changed


def active_ad_aliases() -> List[str]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT alias FROM ads_contracts WHERE active=1 AND alias<>''"
        ).fetchall()
    return [r["alias"] for r in rows]


# ----------------------------------------------------------- share_refs
def add_share_ref(token: str, owner: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO share_refs (token, owner_tg_user_id, created_at) VALUES (?,?,?)",
            (token, owner, _now()),
        )
        return cur.lastrowid


def share_click(token: str, joined: bool = False) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT id FROM share_refs WHERE token=?", (token,)).fetchone()
        if not row:
            return False
        if joined:
            conn.execute(
                "UPDATE share_refs SET clicks=clicks+1, joined=joined+1 WHERE id=?",
                (row["id"],),
            )
        else:
            conn.execute("UPDATE share_refs SET clicks=clicks+1 WHERE id=?", (row["id"],))
        return True


def share_leaderboard(limit: int = 20) -> List[Dict[str, Any]]:
    with connect() as conn:
        cur = conn.execute(
            "SELECT * FROM share_refs ORDER BY joined DESC, clicks DESC LIMIT ?", (limit,)
        )
        return _rows(cur)


def search_items(keyword: str, limit: int = 20) -> List[Dict[str, Any]]:
    like = f"%{keyword}%"
    with connect() as conn:
        cur = conn.execute(
            """SELECT i.*, d.label AS day_label, d.status AS day_status
               FROM day_items i JOIN days d ON d.id = i.day_id
               WHERE i.caption LIKE ? ORDER BY i.id DESC LIMIT ?""",
            (like, limit),
        )
        return _rows(cur)


# ----------------------------------------------------------------- stats
def stats() -> Dict[str, int]:
    with connect() as conn:
        def count(tbl: str, where: str = "") -> int:
            q = f"SELECT COUNT(*) AS c FROM {tbl} {where}"
            return conn.execute(q).fetchone()["c"]

        return {
            "days": count("days"),
            "published_days": count("days", "WHERE status='published'"),
            "items": count("day_items"),
            "users": count("users"),
            "vip_users": count("users", "WHERE is_vip=1"),
            "bots": count("bots"),
            "gift_codes": count("gift_codes"),
            "active_ads": count("ads_contracts", "WHERE active=1"),
            "share_refs": count("share_refs"),
        }
