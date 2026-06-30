"""Delivery logic for the aiogram bot.

Order (clender pattern): try ``copy_message`` -> fallback ``forward_message`` ->
skip on hard failure. FloodWait (``TelegramRetryAfter``) is retried up to 3
times. Progress is persisted per (user, day) so a restart resumes from
``last_seq_sent``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List

from core import config_store
from core.logbus import bus
from research_platform import db

try:  # aiogram is optional at import time (web can load without it)
    from aiogram.exceptions import TelegramRetryAfter
except Exception:  # pragma: no cover
    class TelegramRetryAfter(Exception):  # type: ignore
        retry_after = 1


def _delay() -> float:
    return float(config_store.load_config().get("platform", {}).get("delivery_delay_sec", 2))


async def _send_one(bot, chat_id: int, item: Dict[str, Any]) -> bool:
    """copy -> forward fallback, with FloodWait retries. Returns True if sent."""
    src_chat = int(item["src_chat_id"]) if item["src_chat_id"] else None
    if src_chat is None:
        return False
    msg_ids: List[int] = [item["src_msg_id"]]
    try:
        msg_ids = json.loads(item.get("album_msg_ids") or "[]") or [item["src_msg_id"]]
    except (ValueError, TypeError):
        msg_ids = [item["src_msg_id"]]

    for attempt in range(3):
        try:
            for mid in msg_ids:
                try:
                    await bot.copy_message(chat_id=chat_id, from_chat_id=src_chat, message_id=mid)
                except Exception:
                    await bot.forward_message(chat_id=chat_id, from_chat_id=src_chat, message_id=mid)
            return True
        except TelegramRetryAfter as exc:  # FloodWait
            wait = int(getattr(exc, "retry_after", 2))
            bus.log(f"FloodWait {wait}s (lần {attempt+1}/3)", level="warning", source="delivery")
            await asyncio.sleep(wait + 1)
        except Exception as exc:
            bus.log(f"Lỗi gửi item seq={item['seq']}: {exc}", level="error", source="delivery")
            return False
    return False


async def deliver_day_to_user(bot, tg_user_id: str, day: Dict[str, Any]) -> Dict[str, Any]:
    """Send all items of a day to a user, resuming from last_seq_sent."""
    items = db.list_day_items(day["id"])
    resume = db.get_last_seq(tg_user_id, day["id"])
    sent = 0
    for item in items:
        if item["seq"] <= resume:
            continue
        ok = await _send_one(bot, int(tg_user_id), item)
        if ok:
            db.set_last_seq(tg_user_id, day["id"], item["seq"])
            sent += 1
            await asyncio.sleep(_delay())
    bus.log(
        f"Đã gửi {sent} bài ngày {day['label']} cho user {tg_user_id}", source="delivery"
    )
    return {"sent": sent, "total": len(items), "resumed_from": resume}
