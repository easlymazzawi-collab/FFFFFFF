"""Rollup: build a 30-day catalog (mục lục) text. Never deletes old days."""

from __future__ import annotations

from research_platform import db


def build_rollup(limit: int = 30) -> str:
    days = db.list_days(limit=limit)
    if not days:
        return "Chưa có ngày nào trong kho lưu trữ."
    lines = ["📚 MỤC LỤC KHO LƯU TRỮ (UpBain)", ""]
    for day in days:
        status = day.get("status", "draft")
        mark = {"published": "✅", "indexed": "🟡", "draft": "⚪", "closed": "🔒"}.get(status, "•")
        lines.append(f"{mark} {day['label']} — {day.get('item_count', 0)} bài ({status})")
    lines.append("")
    lines.append(f"Tổng: {len(days)} ngày.")
    return "\n".join(lines)
