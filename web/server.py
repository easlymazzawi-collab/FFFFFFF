"""FastAPI web application — Phase 0 dashboard.

Everything is operated from the browser: set api_id/api_hash, log in to Telegram
(phone -> code -> optional 2FA), start/stop the userbot and watch logs live via
Server-Sent-Events. No ``.env`` is used anywhere.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Optional

from fastapi import Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from core import config_store
from core.logbus import attach_stdlib_logging, bus
from core.userbot import UserbotError, manager
from research_platform import (
    archive_index,
    backup,
    bot_manager,
    db,
    dates,
    rollup,
    run_queue,
)
from web import security

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app = FastAPI(title="UpBain Research Platform v2 — Phase 0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.on_event("startup")
async def _startup() -> None:
    config_store.load_config()
    db.init_db()
    bus.bind_loop(asyncio.get_running_loop())
    attach_stdlib_logging()
    bus.log("Web server đã sẵn sàng tại http://127.0.0.1:8080", source="app")


# --------------------------------------------------------------------- auth
def require_login(request: Request) -> None:
    token = request.cookies.get(security.COOKIE_NAME)
    if not security.is_valid_session(token):
        raise HTTPException(status_code=401, detail="Chưa đăng nhập web.")


def _is_logged_in(request: Request) -> bool:
    return security.is_valid_session(request.cookies.get(security.COOKIE_NAME))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if not _is_logged_in(request):
        return RedirectResponse("/login", status_code=302)
    return TEMPLATES.TemplateResponse("dashboard.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if _is_logged_in(request):
        return RedirectResponse("/", status_code=302)
    return TEMPLATES.TemplateResponse(
        "login.html",
        {"request": request, "setup": not security.password_is_set()},
    )


@app.post("/login")
async def login_submit(request: Request, password: str = Form(...)):
    setup = not security.password_is_set()
    if setup:
        if len(password) < 4:
            return TEMPLATES.TemplateResponse(
                "login.html",
                {"request": request, "setup": True, "error": "Mật khẩu tối thiểu 4 ký tự."},
                status_code=400,
            )
        security.set_password(password)
        bus.log("Đã đặt mật khẩu web lần đầu.", source="app")
    elif not security.verify_password(password, config_store.load_config()["web"]["password_hash"]):
        return TEMPLATES.TemplateResponse(
            "login.html",
            {"request": request, "setup": False, "error": "Sai mật khẩu."},
            status_code=401,
        )

    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        security.COOKIE_NAME,
        security.make_session_token(),
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
    )
    return resp


@app.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(security.COOKIE_NAME)
    return resp


# ------------------------------------------------------------------- config
@app.get("/api/config")
async def get_config(_: None = Depends(require_login)):
    return JSONResponse(config_store.masked_config())


@app.post("/api/config/telegram")
async def save_telegram(
    _: None = Depends(require_login),
    api_id: str = Form(""),
    api_hash: str = Form(""),
):
    values = {}
    if api_id.strip():
        values["api_id"] = api_id.strip()
    if api_hash.strip():
        values["api_hash"] = api_hash.strip()
    if not values:
        raise HTTPException(status_code=400, detail="Không có gì để lưu.")
    config_store.update_section("telegram", values)
    bus.log("Đã lưu cấu hình Telegram (api_id / api_hash).", source="app")
    return JSONResponse(config_store.masked_config())


@app.post("/api/config/bot")
async def save_bot(_: None = Depends(require_login), notify_token: str = Form("")):
    if not notify_token.strip():
        raise HTTPException(status_code=400, detail="Token rỗng.")
    config_store.update_section("bot", {"notify_token": notify_token.strip()})
    bus.log("Đã lưu notify bot token.", source="app")
    return JSONResponse(config_store.masked_config())


def _b(v: str) -> bool:
    return str(v).lower() in ("true", "1", "on", "yes")


@app.post("/api/platform")
async def save_platform(
    _: None = Depends(require_login),
    enabled: str = Form("false"),
    publish_channels: str = Form("false"),
    archive_index_layer: str = Form("false"),
    bot_delivery: str = Form("false"),
    admin_forum_id: str = Form(""),
    admin_notify_group: str = Form(""),
    delivery_delay_sec: str = Form("2"),
    membership_channel_id: str = Form(""),
    force_join_check_sec: str = Form("600"),
    require_vip_for_archive: str = Form("false"),
):
    try:
        delay = int(float(delivery_delay_sec))
        recheck = int(float(force_join_check_sec))
    except ValueError:
        raise HTTPException(status_code=400, detail="Giá trị số không hợp lệ.")
    config_store.update_section("platform", {
        "enabled": _b(enabled),
        "publish_channels": _b(publish_channels),
        "archive_index": _b(archive_index_layer),
        "bot_delivery": _b(bot_delivery),
        "admin_forum_id": admin_forum_id.strip(),
        "admin_notify_group": admin_notify_group.strip(),
        "delivery_delay_sec": delay,
        "membership_channel_id": membership_channel_id.strip(),
        "force_join_check_sec": recheck,
        "require_vip_for_archive": _b(require_vip_for_archive),
    })
    bus.log("Đã lưu cấu hình Platform (3 lớp + delivery/membership).", source="app")
    return JSONResponse(config_store.masked_config())


# ----------------------------------------------------------- telegram login
def _ub_error(exc: UserbotError) -> JSONResponse:
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/telegram/send_code")
async def telegram_send_code(_: None = Depends(require_login), phone: str = Form(...)):
    try:
        result = await manager.send_code(phone)
    except UserbotError as exc:
        return _ub_error(exc)
    return JSONResponse({"ok": True, **result})


@app.post("/api/telegram/sign_in")
async def telegram_sign_in(_: None = Depends(require_login), code: str = Form(...)):
    try:
        result = await manager.sign_in(code)
    except UserbotError as exc:
        return _ub_error(exc)
    return JSONResponse({"ok": True, **result})


@app.post("/api/telegram/password")
async def telegram_password(_: None = Depends(require_login), password: str = Form(...)):
    try:
        result = await manager.check_password(password)
    except UserbotError as exc:
        return _ub_error(exc)
    return JSONResponse({"ok": True, **result})


# ------------------------------------------------------------- userbot ctrl
@app.get("/api/userbot/status")
async def userbot_status(_: None = Depends(require_login)):
    return JSONResponse(manager.snapshot())


@app.post("/api/userbot/start")
async def userbot_start(_: None = Depends(require_login)):
    try:
        snap = await manager.start()
    except UserbotError as exc:
        return _ub_error(exc)
    return JSONResponse({"ok": True, **snap})


@app.post("/api/userbot/stop")
async def userbot_stop(_: None = Depends(require_login)):
    snap = await manager.stop()
    return JSONResponse({"ok": True, **snap})


@app.post("/api/userbot/logout")
async def userbot_logout(_: None = Depends(require_login)):
    snap = await manager.logout()
    return JSONResponse({"ok": True, **snap})


# ----------------------------------------------------------------- logs SSE
@app.get("/api/logs")
async def logs_history(_: None = Depends(require_login)):
    return JSONResponse(bus.history())


@app.get("/api/logs/stream")
async def logs_stream(request: Request):
    if not _is_logged_in(request):
        raise HTTPException(status_code=401, detail="Chưa đăng nhập web.")

    queue = bus.subscribe()

    async def event_gen():
        try:
            # Replay recent history first.
            for record in bus.history()[-50:]:
                yield f"data: {json.dumps(record, ensure_ascii=False)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    record = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(record, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =====================================================================
# Platform features (Phases 1-5)
# =====================================================================

# ------------------------------------------------------------- overview
@app.get("/api/stats")
async def api_stats(_: None = Depends(require_login)):
    return JSONResponse({
        "stats": db.stats(),
        "today_label": dates.topic_label_vn(),
        "userbot": manager.snapshot(),
        "platform": config_store.masked_config()["platform"],
    })


# ------------------------------------------------------------- archive
@app.get("/api/archive/days")
async def archive_days(_: None = Depends(require_login)):
    return JSONResponse(db.list_days())


@app.get("/api/archive/day/{day_id}")
async def archive_day(day_id: int, _: None = Depends(require_login)):
    day = db.get_day(day_id)
    if not day:
        raise HTTPException(404, "Không tìm thấy ngày.")
    return JSONResponse({"day": day, "items": db.list_day_items(day_id)})


@app.post("/api/archive/ingest")
async def archive_ingest(
    _: None = Depends(require_login),
    src_chat_id: str = Form(...),
    src_msg_id: int = Form(...),
    caption: str = Form(""),
    day_label: str = Form(""),
):
    """Manually index one item (exercises the same path as after_auto_forward)."""
    label = day_label.strip() or dates.topic_label_vn()
    res = archive_index.index_item(label, src_chat_id.strip(), src_msg_id, caption=caption)
    bus.log(f"Ingest thủ công: day={label} item={res['item_id']}", source="archive")
    return JSONResponse({"ok": True, **res, "label": label})


@app.post("/api/archive/publish")
async def archive_publish(_: None = Depends(require_login), day_id: int = Form(...)):
    db.set_day_status(day_id, "published")
    bus.log(f"Publish ngày id={day_id}", source="archive")
    return JSONResponse({"ok": True})


@app.post("/api/archive/close")
async def archive_close(_: None = Depends(require_login), day_id: int = Form(...)):
    db.set_day_status(day_id, "closed")
    return JSONResponse({"ok": True})


# -------------------------------------------------------------- users
@app.get("/api/users")
async def api_users(_: None = Depends(require_login)):
    return JSONResponse(db.list_users())


@app.post("/api/users/vip/grant")
async def users_grant_vip(
    _: None = Depends(require_login),
    tg_user_id: str = Form(...),
    days: int = Form(30),
):
    db.grant_vip(tg_user_id.strip(), days)
    bus.log(f"Cấp VIP {days} ngày cho {tg_user_id}", source="vip")
    return JSONResponse({"ok": True})


@app.post("/api/users/vip/revoke")
async def users_revoke_vip(_: None = Depends(require_login), tg_user_id: str = Form(...)):
    db.revoke_vip(tg_user_id.strip())
    return JSONResponse({"ok": True})


# --------------------------------------------------------------- VIP
@app.get("/api/vip/plans")
async def vip_plans(_: None = Depends(require_login)):
    return JSONResponse(db.list_vip_plans())


@app.post("/api/vip/plans")
async def vip_add(
    _: None = Depends(require_login),
    name: str = Form(...),
    days: int = Form(...),
    stars: int = Form(...),
):
    pid = db.add_vip_plan(name.strip(), days, stars)
    return JSONResponse({"ok": True, "id": pid})


@app.post("/api/vip/plans/delete")
async def vip_del(_: None = Depends(require_login), plan_id: int = Form(...)):
    db.delete_vip_plan(plan_id)
    return JSONResponse({"ok": True})


# ----------------------------------------------------------- gift codes
@app.get("/api/gift")
async def gift_list(_: None = Depends(require_login)):
    return JSONResponse(db.list_gift_codes())


@app.post("/api/gift")
async def gift_add(
    _: None = Depends(require_login),
    code: str = Form(...),
    vip_days: int = Form(...),
    max_uses: int = Form(1),
):
    try:
        gid = db.add_gift_code(code.strip().upper(), vip_days, max_uses)
    except Exception:
        raise HTTPException(400, "Mã đã tồn tại.")
    return JSONResponse({"ok": True, "id": gid})


@app.post("/api/gift/redeem")
async def gift_redeem(
    _: None = Depends(require_login),
    code: str = Form(...),
    tg_user_id: str = Form(...),
):
    res = db.redeem_gift_code(code.strip().upper(), tg_user_id.strip())
    status = 200 if res["ok"] else 400
    return JSONResponse(res, status_code=status)


# ----------------------------------------------------------------- ads
@app.get("/api/ads")
async def ads_list(_: None = Depends(require_login)):
    return JSONResponse({"ads": db.list_ads(), "active_aliases": db.active_ad_aliases()})


@app.post("/api/ads")
async def ads_add(
    _: None = Depends(require_login),
    advertiser: str = Form(...),
    alias: str = Form(""),
    content: str = Form(""),
    start_label: str = Form(""),
    end_label: str = Form(""),
):
    aid = db.add_ads(advertiser.strip(), alias.strip(), content.strip(),
                     start_label.strip(), end_label.strip())
    bus.log(f"Thêm hợp đồng ads: {advertiser} (alias={alias})", source="ads")
    return JSONResponse({"ok": True, "id": aid})


@app.post("/api/ads/revoke")
async def ads_revoke(_: None = Depends(require_login), ad_id: int = Form(...)):
    db.revoke_ads(ad_id)
    bus.log(f"Revoke ads id={ad_id} (alias bị gỡ khi xem archive).", source="ads")
    return JSONResponse({"ok": True})


# --------------------------------------------------------------- share
@app.get("/api/share")
async def share_list(_: None = Depends(require_login)):
    return JSONResponse(db.share_leaderboard())


@app.post("/api/share")
async def share_add(_: None = Depends(require_login), owner: str = Form(...)):
    import random
    token = str(random.randint(10_000_000, 99_999_999))
    db.add_share_ref(token, owner.strip())
    return JSONResponse({"ok": True, "token": token})


@app.post("/api/share/click")
async def share_do_click(
    _: None = Depends(require_login),
    token: str = Form(...),
    joined: str = Form("false"),
):
    ok = db.share_click(token.strip(), joined=_b(joined))
    return JSONResponse({"ok": ok})


# ----------------------------------------------------------------- bots
@app.get("/api/bots")
async def bots_list(_: None = Depends(require_login)):
    return JSONResponse(bot_manager.manager.snapshot())


@app.post("/api/bots")
async def bots_save(
    _: None = Depends(require_login),
    slug: str = Form(...),
    token: str = Form(""),
    source_forum_id: str = Form(""),
    queue_order: int = Form(0),
    enabled: str = Form("true"),
):
    fields = {"source_forum_id": source_forum_id.strip(), "queue_order": queue_order,
              "enabled": 1 if _b(enabled) else 0}
    if token.strip():
        fields["token"] = token.strip()
    db.upsert_bot(slug.strip(), **fields)
    bus.log(f"Đã lưu bot {slug}.", source="bot")
    return JSONResponse(bot_manager.manager.snapshot())


@app.post("/api/bots/delete")
async def bots_delete(_: None = Depends(require_login), bot_id: int = Form(...)):
    db.delete_bot(bot_id)
    return JSONResponse(bot_manager.manager.snapshot())


@app.post("/api/bots/start")
async def bots_start(_: None = Depends(require_login), slug: str = Form("")):
    try:
        snap = await (bot_manager.manager.start_bot(slug) if slug
                      else bot_manager.manager.start_all())
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, **snap})


@app.post("/api/bots/stop")
async def bots_stop(_: None = Depends(require_login), slug: str = Form("")):
    snap = await (bot_manager.manager.stop_bot(slug) if slug
                  else bot_manager.manager.stop_all())
    return JSONResponse({"ok": True, **snap})


@app.post("/api/bots/broadcast")
async def bots_broadcast(_: None = Depends(require_login), day_label: str = Form("")):
    res = await run_queue.broadcast_published_day(day_label.strip() or None)
    status = 200 if res.get("ok") else 400
    return JSONResponse(res, status_code=status)


# --------------------------------------------------------------- rollup
@app.get("/api/rollup")
async def api_rollup(_: None = Depends(require_login)):
    return JSONResponse({"text": rollup.build_rollup()})


# --------------------------------------------------------------- backup
@app.get("/api/backup/list")
async def backup_list(_: None = Depends(require_login)):
    return JSONResponse(backup.list_backups())


@app.post("/api/backup/create")
async def backup_create(_: None = Depends(require_login)):
    path = backup.create_backup_file()
    bus.log(f"Đã tạo backup: {os.path.basename(path)}", source="backup")
    return JSONResponse({"ok": True, "name": os.path.basename(path)})


@app.get("/api/backup/download/{name}")
async def backup_download(name: str, request: Request):
    if not _is_logged_in(request):
        raise HTTPException(401, "Chưa đăng nhập web.")
    path = backup.backup_path(name)
    if not path:
        raise HTTPException(404, "Không tìm thấy backup.")
    from fastapi.responses import FileResponse
    return FileResponse(path, filename=name, media_type="application/zip")
