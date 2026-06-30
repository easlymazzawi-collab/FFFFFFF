"""Persistent configuration store.

Phase 0 rule: there is NO `.env` file. Every setting is entered through the web
UI and persisted to ``data/auto_config.json``. Secrets (api_hash, bot token,
session string, web password) are never echoed back to the browser in clear
text — see :func:`masked_config`.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from typing import Any, Dict

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")
CONFIG_PATH = os.path.join(DATA_DIR, "auto_config.json")

_LOCK = threading.RLock()


def _default_config() -> Dict[str, Any]:
    return {
        "web": {
            # bcrypt-free: we use a salted sha256 hash (see web.security).
            "password_hash": None,
            "secret_key": secrets.token_hex(32),
        },
        "telegram": {
            "api_id": None,
            "api_hash": None,
            # Pyrogram session string produced after a successful web login.
            "session_string": None,
            "logged_in_user": None,
        },
        "bot": {
            # "notify bot" token used later to push alerts to the admin.
            "notify_token": None,
        },
        # Platform runtime config (3-layer ON/OFF + delivery/membership).
        "platform": {
            "enabled": False,
            "publish_channels": True,   # L1 — userbot up kênh
            "archive_index": True,      # L2 — ghi index DB
            "bot_delivery": True,       # L3 — bot gửi cho user
            "admin_forum_id": "",
            "admin_notify_group": "",
            "delivery_delay_sec": 2,
            "membership_channel_id": "",
            "force_join_check_sec": 600,
            "require_vip_for_archive": False,
            # Forward pipeline + scheduler.
            "publish_channel": "",      # đích userbot up kênh
            "catalog_channel": "",      # nơi post rollup mục lục
            "backup_channel": "",       # nơi gửi ZIP backup
            "schedule_enabled": False,
            "schedule_interval_sec": 3600,
            "backup_interval_hours": 24,
            # topic_map: [{source_chat, source_topic, limit, label}]
            "topic_map": [],
        },
    }


def ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``override`` into ``base`` (used to add new keys)."""
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config() -> Dict[str, Any]:
    """Load config from disk, creating defaults on first run."""
    with _LOCK:
        ensure_data_dir()
        if not os.path.exists(CONFIG_PATH):
            cfg = _default_config()
            _write(cfg)
            return cfg
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            data = {}
        # Merge defaults so newly introduced keys always exist.
        cfg = _deep_merge(_default_config(), data if isinstance(data, dict) else {})
        # Keep an existing secret_key stable across restarts.
        if not cfg["web"].get("secret_key"):
            cfg["web"]["secret_key"] = secrets.token_hex(32)
        _write(cfg)
        return cfg


def _write(cfg: Dict[str, Any]) -> None:
    ensure_data_dir()
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, CONFIG_PATH)


def save_config(cfg: Dict[str, Any]) -> None:
    with _LOCK:
        _write(cfg)


def update_section(section: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Patch a top-level section and persist. Returns the full updated config."""
    with _LOCK:
        cfg = load_config()
        if section not in cfg or not isinstance(cfg[section], dict):
            cfg[section] = {}
        for key, value in values.items():
            cfg[section][key] = value
        _write(cfg)
        return cfg


def _mask(value: Any) -> Any:
    if not value:
        return ""
    text = str(value)
    if len(text) <= 4:
        return "••••"
    return "••••" + text[-4:]


def masked_config() -> Dict[str, Any]:
    """Return a browser-safe view: secrets are masked, never raw."""
    cfg = load_config()
    tg = cfg.get("telegram", {})
    bot = cfg.get("bot", {})
    return {
        "telegram": {
            "api_id": tg.get("api_id") or "",
            "api_hash_masked": _mask(tg.get("api_hash")),
            "has_api_hash": bool(tg.get("api_hash")),
            "logged_in_user": tg.get("logged_in_user"),
            "has_session": bool(tg.get("session_string")),
        },
        "bot": {
            "notify_token_masked": _mask(bot.get("notify_token")),
            "has_notify_token": bool(bot.get("notify_token")),
        },
        "platform": {
            "enabled": bool(cfg.get("platform", {}).get("enabled")),
            "publish_channels": bool(cfg.get("platform", {}).get("publish_channels")),
            "archive_index": bool(cfg.get("platform", {}).get("archive_index")),
            "bot_delivery": bool(cfg.get("platform", {}).get("bot_delivery")),
            "admin_forum_id": cfg.get("platform", {}).get("admin_forum_id", ""),
            "admin_notify_group": cfg.get("platform", {}).get("admin_notify_group", ""),
            "delivery_delay_sec": cfg.get("platform", {}).get("delivery_delay_sec", 2),
            "membership_channel_id": cfg.get("platform", {}).get("membership_channel_id", ""),
            "force_join_check_sec": cfg.get("platform", {}).get("force_join_check_sec", 600),
            "require_vip_for_archive": bool(
                cfg.get("platform", {}).get("require_vip_for_archive")
            ),
            "publish_channel": cfg.get("platform", {}).get("publish_channel", ""),
            "catalog_channel": cfg.get("platform", {}).get("catalog_channel", ""),
            "backup_channel": cfg.get("platform", {}).get("backup_channel", ""),
            "schedule_enabled": bool(cfg.get("platform", {}).get("schedule_enabled")),
            "schedule_interval_sec": cfg.get("platform", {}).get("schedule_interval_sec", 3600),
            "backup_interval_hours": cfg.get("platform", {}).get("backup_interval_hours", 24),
            "topic_map": cfg.get("platform", {}).get("topic_map", []),
        },
        "web": {
            "password_set": bool(cfg.get("web", {}).get("password_hash")),
        },
    }
