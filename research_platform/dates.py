"""Vietnam-timezone date helpers (spec C9: label DD-MM-YYYY, Asia/Ho_Chi_Minh)."""

from __future__ import annotations

import datetime as _dt

VN_TZ = _dt.timezone(_dt.timedelta(hours=7))  # Asia/Ho_Chi_Minh


def now_vn() -> _dt.datetime:
    return _dt.datetime.now(VN_TZ)


def today_vn() -> _dt.date:
    return now_vn().date()


def topic_label_vn(d: _dt.date | None = None) -> str:
    """Return the canonical day label, e.g. ``30-06-2026``."""
    d = d or today_vn()
    return d.strftime("%d-%m-%Y")


def parse_day_label(label: str) -> _dt.date | None:
    try:
        return _dt.datetime.strptime(label.strip(), "%d-%m-%Y").date()
    except (ValueError, AttributeError):
        return None
