"""Admin notifications + Telegram file upload via the notify bot.

Uses the notify bot token (config ``bot.notify_token``) as a short-lived aiogram
client. All functions are best-effort and never raise to the caller.
"""

from __future__ import annotations

import os
from typing import Optional

from core import config_store
from core.logbus import bus


def _notify_token() -> str:
    return config_store.load_config().get("bot", {}).get("notify_token", "") or ""


def _target() -> str:
    return config_store.load_config().get("platform", {}).get("admin_notify_group", "") or ""


async def _bot():
    token = _notify_token()
    if not token:
        return None
    try:
        from aiogram import Bot
    except Exception:
        return None
    return Bot(token=token)


async def admin_notify(text: str, chat_id: Optional[str] = None) -> bool:
    target = chat_id or _target()
    if not target:
        bus.log(f"[notify bỏ qua: chưa cấu hình admin_notify_group] {text}", source="notify")
        return False
    bot = await _bot()
    if bot is None:
        bus.log("[notify bỏ qua: chưa có notify_token]", level="warning", source="notify")
        return False
    try:
        await bot.send_message(int(target) if target.lstrip("-").isdigit() else target, text)
        bus.log(f"Đã notify admin: {text[:60]}", source="notify")
        return True
    except Exception as exc:
        bus.log(f"Notify lỗi: {exc}", level="error", source="notify")
        return False
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass


async def send_document(path: str, caption: str = "", chat_id: Optional[str] = None) -> bool:
    target = chat_id or config_store.load_config().get("platform", {}).get("backup_channel", "") or _target()
    if not target or not os.path.isfile(path):
        return False
    bot = await _bot()
    if bot is None:
        return False
    try:
        from aiogram.types import FSInputFile
        await bot.send_document(
            int(target) if str(target).lstrip("-").isdigit() else target,
            FSInputFile(path),
            caption=caption,
        )
        bus.log(f"Đã gửi file lên Telegram: {os.path.basename(path)}", source="notify")
        return True
    except Exception as exc:
        bus.log(f"Gửi file lỗi: {exc}", level="error", source="notify")
        return False
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
