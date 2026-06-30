"""aiogram command handlers for the delivery bot.

Commands: /start [ref_x], /today, /day DD-MM-YYYY, /vip, /buy_<id> (Stars/XTR),
/redeem CODE, /invite, /myref, /find KW, /recheck, /catalog. Plus a contribution
catch-all (user sends content -> forwarded to admin). Membership + VIP gates run
before delivery.
"""

from __future__ import annotations

import random

from core import config_store
from core.logbus import bus
from research_platform import bot_delivery, db, dates, membership, rollup


def build_router():
    from aiogram import F, Router
    from aiogram.filters import Command, CommandObject, CommandStart
    from aiogram.types import LabeledPrice, Message, PreCheckoutQuery

    router = Router()

    def _cfg():
        return config_store.load_config().get("platform", {})

    async def _gate(message: "Message") -> bool:
        uid = str(message.from_user.id)
        db.upsert_user(uid, message.from_user.username or "", message.from_user.first_name or "")
        if not await membership.is_member(message.bot, uid):
            ch = membership.membership_channel()
            await message.answer(f"Bạn cần tham gia kênh {ch} rồi bấm /recheck.")
            return False
        if _cfg().get("require_vip_for_archive") and not db.is_user_vip(uid):
            await message.answer("Nội dung dành cho VIP. Dùng /vip để nâng cấp.")
            return False
        return True

    # --------------------------------------------------------- start + ref
    @router.message(CommandStart())
    async def start(message: "Message", command: "CommandObject"):
        uid = str(message.from_user.id)
        db.upsert_user(uid, message.from_user.username or "", message.from_user.first_name or "")
        payload = (command.args or "").strip()
        if payload.startswith("ref_"):
            token = payload[4:]
            if db.share_click(token, joined=True):
                bus.log(f"Ref {token} +1 join từ {uid}", source="share")
                await message.answer("Cảm ơn bạn đã tham gia qua link mời! 🎉")
        await message.answer(
            "Chào mừng tới UpBain!\n"
            "/today · /day DD-MM-YYYY · /vip · /redeem MÃ · /invite · /find TỪ KHOÁ · /catalog"
        )

    # ------------------------------------------------------------ delivery
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
    async def day_cmd(message: "Message", command: "CommandObject"):
        label = (command.args or "").strip()
        if not dates.parse_day_label(label):
            await message.answer("Cú pháp: /day DD-MM-YYYY")
            return
        if not await _gate(message):
            return
        day = db.get_day_by_label(label)
        if not day or day["status"] not in ("published", "closed"):
            await message.answer("Ngày này chưa publish.")
            return
        await bot_delivery.deliver_day_to_user(message.bot, str(message.from_user.id), day)

    @router.message(Command("recheck"))
    async def recheck(message: "Message"):
        membership.invalidate(str(message.from_user.id))
        if await _gate(message):
            await message.answer("Đã kiểm tra lại — bạn đủ điều kiện. Dùng /today.")

    @router.message(Command("find"))
    async def find(message: "Message", command: "CommandObject"):
        kw = (command.args or "").strip()
        if not kw:
            await message.answer("Cú pháp: /find TỪ KHOÁ")
            return
        rows = db.search_items(kw)
        if not rows:
            await message.answer("Không tìm thấy.")
            return
        lines = [f"Kết quả cho '{kw}':"] + [
            f"• {r['day_label']} #{r['seq']}: {(r['caption'] or '')[:50]}" for r in rows[:15]
        ]
        await message.answer("\n".join(lines))

    @router.message(Command("catalog"))
    async def catalog(message: "Message"):
        await message.answer(rollup.build_rollup())

    # ---------------------------------------------------------- monetization
    @router.message(Command("vip"))
    async def vip(message: "Message"):
        plans = [p for p in db.list_vip_plans() if p["enabled"]]
        if not plans:
            await message.answer("Chưa có gói VIP.")
            return
        lines = ["Gói VIP (mua bằng ⭐ Telegram Stars):"]
        lines += [f"/buy_{p['id']} — {p['name']}: {p['stars']}⭐ / {p['days']} ngày" for p in plans]
        await message.answer("\n".join(lines))

    @router.message(F.text.regexp(r"^/buy_(\d+)"))
    async def buy(message: "Message"):
        try:
            plan_id = int(message.text.split("_", 1)[1].split()[0])
        except (ValueError, IndexError):
            return
        plans = {p["id"]: p for p in db.list_vip_plans()}
        plan = plans.get(plan_id)
        if not plan or not plan["enabled"]:
            await message.answer("Gói không tồn tại.")
            return
        # Telegram Stars: currency XTR, provider_token empty.
        await message.answer_invoice(
            title=plan["name"],
            description=f"VIP {plan['days']} ngày",
            payload=f"vip:{plan_id}",
            currency="XTR",
            prices=[LabeledPrice(label=plan["name"], amount=int(plan["stars"]))],
        )

    @router.pre_checkout_query()
    async def pre_checkout(query: "PreCheckoutQuery"):
        await query.answer(ok=True)

    @router.message(F.successful_payment)
    async def paid(message: "Message"):
        payload = message.successful_payment.invoice_payload
        if payload.startswith("vip:"):
            plan_id = int(payload.split(":")[1])
            plan = {p["id"]: p for p in db.list_vip_plans()}.get(plan_id)
            days = plan["days"] if plan else 30
            db.grant_vip(str(message.from_user.id), days)
            bus.log(f"Thanh toán Stars OK → VIP {days} ngày cho {message.from_user.id}", source="vip")
            await message.answer(f"Thanh toán thành công! +{days} ngày VIP 🎉")

    @router.message(Command("redeem"))
    async def redeem(message: "Message", command: "CommandObject"):
        code = (command.args or "").strip()
        if not code:
            await message.answer("Cú pháp: /redeem MÃ")
            return
        res = db.redeem_gift_code(code.upper(), str(message.from_user.id))
        await message.answer(f"Thành công! +{res['vip_days']} ngày VIP." if res["ok"] else res["error"])

    # ---------------------------------------------------------------- share
    @router.message(Command(commands=["invite", "myref"]))
    async def invite(message: "Message"):
        uid = str(message.from_user.id)
        token = str(random.randint(10_000_000, 99_999_999))
        db.add_share_ref(token, uid)
        bot_user = (await message.bot.me()).username
        await message.answer(
            f"Link mời của bạn:\nhttps://t.me/{bot_user}?start=ref_{token}\n"
            "Mỗi người tham gia qua link sẽ được tính cho bạn."
        )

    # ----------------------------------------------------- contribution
    @router.message(F.content_type.in_({"photo", "video", "document", "text"}))
    async def contribution(message: "Message"):
        """Catch-all: user-submitted content is forwarded to the admin forum."""
        admin = _cfg().get("admin_forum_id", "")
        if not admin:
            return
        try:
            await message.forward(int(admin) if str(admin).lstrip("-").isdigit() else admin)
            await message.answer("Đã nhận đóng góp của bạn, cảm ơn! 🙏")
        except Exception:
            pass

    bus.log("Bot handlers đã nạp (đầy đủ lệnh + payment + ref + find).", source="bot")
    return router
