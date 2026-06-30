"""Force-join membership gate (Phase 3 pattern, fail-open with TTL cache)."""

from __future__ import annotations

import time
from typing import Dict, Tuple

from core import config_store

# tg_user_id -> (is_member, checked_at)
_CACHE: Dict[str, Tuple[bool, float]] = {}


def _ttl() -> int:
    return int(config_store.load_config().get("platform", {}).get("force_join_check_sec", 600))


def membership_channel() -> str:
    return config_store.load_config().get("platform", {}).get("membership_channel_id", "") or ""


async def is_member(client, tg_user_id: str) -> bool:
    """Check membership with caching. Fail-open: any error -> treated as allowed.

    ``client`` is a Pyrogram/aiogram-like client exposing ``get_chat_member``.
    """
    channel = membership_channel()
    if not channel:
        return True  # gate disabled

    cached = _CACHE.get(tg_user_id)
    if cached and (time.time() - cached[1]) < _ttl():
        return cached[0]

    ok = True
    try:
        member = await client.get_chat_member(channel, int(tg_user_id))
        status = getattr(member, "status", None)
        status = getattr(status, "value", status)
        ok = str(status) not in ("left", "kicked", "banned", "ChatMemberStatus.LEFT")
    except Exception:
        ok = True  # fail-open: never block users on transient errors
    _CACHE[tg_user_id] = (ok, time.time())
    return ok


def invalidate(tg_user_id: str) -> None:
    _CACHE.pop(tg_user_id, None)
