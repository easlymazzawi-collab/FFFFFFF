"""In-memory log bus used to stream logs to the dashboard via SSE.

Every log line is kept in a small ring buffer (so a freshly opened dashboard can
show recent history) and broadcast to all connected Server-Sent-Events clients.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import logging
from collections import deque
from typing import Deque, Dict, List, Set

_VN_TZ = _dt.timezone(_dt.timedelta(hours=7))  # Asia/Ho_Chi_Minh (C9 spec)


class LogBus:
    def __init__(self, history: int = 300) -> None:
        self._buffer: Deque[Dict[str, str]] = deque(maxlen=history)
        self._subscribers: Set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def history(self) -> List[Dict[str, str]]:
        return list(self._buffer)

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def _emit(self, record: Dict[str, str]) -> None:
        self._buffer.append(record)
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(record)
            except asyncio.QueueFull:
                pass

    def log(self, message: str, level: str = "info", source: str = "app") -> None:
        """Add a log line. Safe to call from any thread."""
        record = {
            "ts": _dt.datetime.now(_VN_TZ).strftime("%d-%m-%Y %H:%M:%S"),
            "level": level,
            "source": source,
            "message": message,
        }
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._emit, record)
        else:
            self._emit(record)


# Singleton bus shared across the app.
bus = LogBus()


class _BusHandler(logging.Handler):
    """Bridge the stdlib logging into the bus so library logs show on the web."""

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            bus.log(record.getMessage(), level=record.levelname.lower(), source=record.name)
        except Exception:  # pragma: no cover - logging must never crash app
            pass


def attach_stdlib_logging(level: int = logging.INFO) -> None:
    handler = _BusHandler()
    handler.setLevel(level)
    root = logging.getLogger()
    if not any(isinstance(h, _BusHandler) for h in root.handlers):
        root.addHandler(handler)
    root.setLevel(level)
