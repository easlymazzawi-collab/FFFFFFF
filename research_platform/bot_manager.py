"""aiogram bot manager — start/stop delivery bots (max 10, queue order).

Each enabled bot runs its own polling task sharing the same handlers. Tokens
come from the DB (entered on the web). Designed to be import-safe: the web app
loads even if aiogram is missing or no token is configured.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from core.logbus import bus
from research_platform import bot_handlers, db

MAX_BOTS = 10


class BotManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}
        self._bots: Dict[str, Any] = {}
        self._status: Dict[str, str] = {}  # slug -> stopped|online|error
        self._errors: Dict[str, str] = {}
        self._lock = asyncio.Lock()

    def snapshot(self) -> Dict[str, Any]:
        rows = db.list_bots()
        out = []
        for row in rows:
            slug = row["slug"]
            out.append({
                "slug": slug,
                "queue_order": row["queue_order"],
                "enabled": bool(row["enabled"]),
                "has_token": bool(row["token"]),
                "source_forum_id": row["source_forum_id"],
                "status": self._status.get(slug, "stopped"),
                "error": self._errors.get(slug),
            })
        return {"bots": out, "running": list(self._tasks.keys()), "max": MAX_BOTS}

    async def start_bot(self, slug: str) -> Dict[str, Any]:
        async with self._lock:
            return await self._start_locked(slug)

    async def _start_locked(self, slug: str) -> Dict[str, Any]:
        if slug in self._tasks and not self._tasks[slug].done():
            return self.snapshot()
        bots = {b["slug"]: b for b in db.list_bots()}
        row = bots.get(slug)
        if not row or not row.get("token"):
            raise RuntimeError(f"Bot {slug} chưa có token.")
        if len(self._tasks) >= MAX_BOTS:
            raise RuntimeError("Đã đạt tối đa 10 bot.")

        try:
            from aiogram import Bot, Dispatcher
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"aiogram chưa cài: {exc}")

        bot = Bot(token=row["token"])
        dp = Dispatcher()
        dp.include_router(bot_handlers.build_router())

        async def _run():
            try:
                me = await bot.get_me()
                self._status[slug] = "online"
                self._errors.pop(slug, None)
                bus.log(f"Bot {slug} ONLINE: @{me.username}", source="bot")
                await dp.start_polling(bot, handle_signals=False)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._status[slug] = "error"
                self._errors[slug] = str(exc)
                bus.log(f"Bot {slug} lỗi: {exc}", level="error", source="bot")
            finally:
                try:
                    await bot.session.close()
                except Exception:
                    pass

        self._bots[slug] = bot
        self._status[slug] = "starting"
        self._tasks[slug] = asyncio.create_task(_run())
        return self.snapshot()

    async def stop_bot(self, slug: str) -> Dict[str, Any]:
        async with self._lock:
            task = self._tasks.pop(slug, None)
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            self._bots.pop(slug, None)
            self._status[slug] = "stopped"
            bus.log(f"Bot {slug} đã dừng.", level="warning", source="bot")
            return self.snapshot()

    async def start_all(self) -> Dict[str, Any]:
        for row in db.list_bots():
            if row.get("enabled") and row.get("token"):
                try:
                    await self.start_bot(row["slug"])
                except Exception as exc:
                    bus.log(f"Không start {row['slug']}: {exc}", level="error", source="bot")
        return self.snapshot()

    async def stop_all(self) -> Dict[str, Any]:
        for slug in list(self._tasks.keys()):
            await self.stop_bot(slug)
        return self.snapshot()


manager = BotManager()
