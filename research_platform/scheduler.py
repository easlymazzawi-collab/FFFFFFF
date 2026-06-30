"""Background scheduler: periodic auto-forward rounds + periodic backups.

A single asyncio task wakes on a short tick and decides whether it is time to
run another forward round (``schedule_interval_sec``) or a backup
(``backup_interval_hours``). Toggled live from the web (no restart needed).
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from core import config_store
from core.logbus import bus

_task: Optional[asyncio.Task] = None
_last_round: float = 0.0
_last_backup: float = 0.0


def status() -> dict:
    cfg = config_store.load_config().get("platform", {})
    return {
        "running": _task is not None and not _task.done(),
        "schedule_enabled": bool(cfg.get("schedule_enabled")),
        "interval_sec": cfg.get("schedule_interval_sec", 3600),
        "backup_interval_hours": cfg.get("backup_interval_hours", 24),
        "last_round_ago_sec": int(time.time() - _last_round) if _last_round else None,
    }


async def _loop() -> None:
    global _last_round, _last_backup
    bus.log("Scheduler đã khởi động.", source="scheduler")
    while True:
        try:
            cfg = config_store.load_config().get("platform", {})
            now = time.time()

            if cfg.get("schedule_enabled") and cfg.get("enabled"):
                interval = max(60, int(cfg.get("schedule_interval_sec", 3600)))
                if now - _last_round >= interval:
                    _last_round = now
                    await _safe_round()

            backup_every = max(1, int(cfg.get("backup_interval_hours", 24))) * 3600
            if now - _last_backup >= backup_every:
                _last_backup = now
                if _last_backup and cfg.get("enabled"):
                    await _safe_backup()
        except Exception as exc:  # pragma: no cover
            bus.log(f"Scheduler vòng lặp lỗi: {exc}", level="error", source="scheduler")
        await asyncio.sleep(30)


async def _safe_round() -> None:
    try:
        from core.userbot import manager
        if manager.is_online():
            bus.log("Scheduler: chạy auto round…", source="scheduler")
            await manager.run_all_topics()
    except Exception as exc:
        bus.log(f"Scheduler round lỗi: {exc}", level="error", source="scheduler")


async def _safe_backup() -> None:
    try:
        from research_platform import backup, notify
        path = backup.create_backup_file()
        bus.log("Scheduler: đã tạo backup định kỳ.", source="scheduler")
        await notify.send_document(path, caption="Backup định kỳ UpBain")
    except Exception as exc:
        bus.log(f"Scheduler backup lỗi: {exc}", level="error", source="scheduler")


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())
