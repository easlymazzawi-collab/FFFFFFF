"""aiogram command handlers for the delivery bot.

Commands: /start, /today, /day DD-MM-YYYY, /vip, /redeem CODE, /myref, /find.
Membership gate + VIP gate (require_vip_for_archive) applied before delivery.
"""

from __future__ import annotations

import random

from core import config_store
from core.logbus import bus
from research_platform import bot_delivery, db, dates, membership, rollup


def build_router():
    from aiogram import Router
    from aiogram.filters import Command, CommandStart
    from aiogram.types import Message

    router = Router()

    def _cfg():
        return config_store.load_config().get("platform", {})

    async def _gate(message: "Message") -> bool:
        uid = str(message.from_user.id)
        db.upsert_user(uid, message.from_user.username or "", message.from_user.first_name or "")
        if not await membership.is_member(message.bot, uid):
            ch = membership.membership_channel()
            await message.answer(f"Bạn cần tham gia kênh {ch} rồi bấm /today lại.")
            return False
        if _cfg().get("require_vip_for_archive") and not db.is_user_vip(uid):
            await message.answer("Nội dung dành cho VIP. Dùng /vip để nâng cấp.")
            return False
        return True

    @router.message(CommandStart())
    async def start(message: "Message"):
        db.upsert_user(
            str(message.from_user.id),
            message.from_user.username or "",
            message.from_user.first_name or "",
        )
        await message.answer(
            "Chào mừng tới UpBain! Lệnh: /today, /day DD-MM-YYYY, /vip, /redeem MÃ, /myref"
        )

    @router.message(Command("today"))
    async def today(message: "Message"):
        if not _cfg().get("bot_delivery", True):
            await message.answer("Giao hàng đang tạm tắt.")
            return
        if not await _gate(message):
            return
        day = db.latest_published_day()
        if not day:
            await message.answer("Chưa có ngày nào được publish.")
            return
        await message.answer(f"Đang gửi ngày {day['label']}…")
        await bot_delivery.deliver_day_to_user(message.bot, str(message.from_user.id), day)

    @router.message(Command("day"))
    async def day_cmd(message: "Message"):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not dates.parse_day_label(parts[1]):
            await message.answer("Cú pháp: /day DD-MM-YYYY")
            return
        if not await _gate(message):
            return
        day = db.get_day_by_label(parts[1].strip())
        if not day or day["status"] not in ("published", "closed"):
            await message.answer("Ngày này chưa publish.")
            return
        await bot_delivery.deliver_day_to_user(message.bot, str(message.from_user.id), day)

    @router.message(Command("vip"))
    async def vip(message: "Message"):
        plans = db.list_vip_plans()
        if not plans:
            await message.answer("Chưa có gói VIP.")
            return
        lines = ["Gói VIP:"] + [f"/buy_{p['id']} — {p['name']}: {p['stars']}⭐ / {p['days']} ngày"
                                 for p in plans if p["enabled"]]
        await message.answer("\n".join(lines))

    @router.message(Command("redeem"))
    async def redeem(message: "Message"):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2:
            await message.answer("Cú pháp: /redeem MÃ")
            return
        res = db.redeem_gift_code(parts[1].strip(), str(message.from_user.id))
        if res["ok"]:
            await message.answer(f"Thành công! +{res['vip_days']} ngày VIP.")
        else:
            await message.answer(res["error"])

    @router.message(Command("myref"))
    async def myref(message: "Message"):
        uid = str(message.from_user.id)
        token = str(random.randint(10_000_000, 99_999_999))
        db.add_share_ref(token, uid)
        bot_user = (await message.bot.me()).username
        await message.answer(f"Link mời của bạn:\nhttps://t.me/{bot_user}?start=ref_{token}")

    @router.message(Command("catalog"))
    async def catalog(message: "Message"):
        await message.answer(rollup.build_rollup())

    bus.log("Bot handlers đã nạp.", source="bot")
    return router
