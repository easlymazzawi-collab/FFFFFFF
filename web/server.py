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
from web import security

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app = FastAPI(title="UpBain Research Platform v2 — Phase 0")
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.on_event("startup")
async def _startup() -> None:
    config_store.load_config()
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


@app.post("/api/platform")
async def save_platform(_: None = Depends(require_login), enabled: str = Form("false")):
    config_store.update_section("platform", {"enabled": enabled.lower() == "true"})
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
