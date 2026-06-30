"""Archive indexing — records forwarded content into the platform DB.

In the live pipeline :func:`after_auto_forward` is called once per userbot
forward batch. It creates/updates the VN-labelled *day* and appends *day_items*
(seq, source ids, album ids). Layer L2 (``archive_index``) can switch it off.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core import config_store
from core.logbus import bus
from research_platform import db, dates


def _layer_on(name: str) -> bool:
    cfg = config_store.load_config().get("platform", {})
    return bool(cfg.get("enabled")) and bool(cfg.get(name, True))


def ensure_today_day() -> Dict[str, Any]:
    label = dates.topic_label_vn()
    day_id = db.upsert_day(label, title=f"Ngày {label}")
    return db.get_day(day_id)  # type: ignore[return-value]


def index_item(
    day_label: str,
    src_chat_id: str,
    src_msg_id: int,
    album_msg_ids: Optional[List[int]] = None,
    caption: str = "",
) -> Dict[str, Any]:
    """Append one item to a day (creating the day if needed)."""
    day_id = db.upsert_day(day_label, title=f"Ngày {day_label}")
    item_id = db.add_day_item(
        day_id,
        src_chat_id=str(src_chat_id),
        src_msg_id=int(src_msg_id),
        album_msg_ids=json.dumps(album_msg_ids or []),
        caption=caption,
    )
    db.set_day_status(day_id, "indexed")
    return {"day_id": day_id, "item_id": item_id}


def after_auto_forward(batch: Dict[str, Any]) -> None:
    """Hook called after a userbot auto-forward batch.

    ``batch`` shape: {src_chat_id, src_msg_id, album_msg_ids?, caption?}.
    """
    bus.log(f"after_auto_forward: {batch}", source="archive")
    if not _layer_on("archive_index"):
        bus.log("archive_index layer OFF — bỏ qua ghi DB.", level="warning", source="archive")
        return
    label = dates.topic_label_vn()
    res = index_item(
        label,
        src_chat_id=batch.get("src_chat_id", ""),
        src_msg_id=batch.get("src_msg_id", 0),
        album_msg_ids=batch.get("album_msg_ids"),
        caption=batch.get("caption", ""),
    )
    bus.log(f"Đã ghi index day={label} item={res['item_id']}", source="archive")
