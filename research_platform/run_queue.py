"""Phase 4a — sequential multi-bot queue orchestration helpers."""

from __future__ import annotations

from typing import Any, Dict, List

from core.logbus import bus
from research_platform import bot_delivery, bot_manager, db


def queue_order() -> List[Dict[str, Any]]:
    return sorted(db.list_bots(), key=lambda b: (b["queue_order"], b["id"]))


async def broadcast_published_day(day_label: str | None = None) -> Dict[str, Any]:
    """Send a published day to every known user using running bots in queue order.

    Bots are picked round-robin from the currently running set so load is spread
    sequentially across the queue.
    """
    day = db.get_day_by_label(day_label) if day_label else db.latest_published_day()
    if not day or day["status"] not in ("published", "closed"):
        return {"ok": False, "error": "Không có ngày publish hợp lệ."}

    running = bot_manager.manager._tasks  # noqa: SLF001 (internal use)
    bots = [b for b in queue_order() if b["slug"] in running and b.get("token")]
    if not bots:
        return {"ok": False, "error": "Chưa có bot nào đang chạy."}

    users = db.list_users(limit=100_000)
    sent_total = 0
    for i, user in enumerate(users):
        bot_row = bots[i % len(bots)]
        bot = bot_manager.manager._bots.get(bot_row["slug"])  # noqa: SLF001
        if not bot:
            continue
        res = await bot_delivery.deliver_day_to_user(bot, user["tg_user_id"], day)
        sent_total += res["sent"]
    bus.log(f"Broadcast ngày {day['label']}: {sent_total} bài tới {len(users)} user", source="queue")
    return {"ok": True, "users": len(users), "sent": sent_total, "day": day["label"]}
