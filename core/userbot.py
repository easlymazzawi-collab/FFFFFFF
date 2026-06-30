"""Pyrogram userbot manager with a fully web-driven login flow.

There is no terminal interaction and no ``.env``: the phone number, the code
sent by Telegram and the optional 2FA password all arrive from the web UI. After
a successful login we export a Pyrogram *session string* and persist it via the
config store so the userbot can be brought online again without re-login.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from core import config_store
from core.logbus import bus

# Pyrofork exposes the same ``pyrogram`` import namespace.
from pyrogram import Client
from pyrogram.errors import (
    PasswordHashInvalid,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberInvalid,
    SessionPasswordNeeded,
)


class UserbotError(Exception):
    """Raised for user-facing login/start failures (message is safe to show)."""


class UserbotManager:
    def __init__(self) -> None:
        self.status: str = "stopped"  # stopped | starting | online | error
        self.username: Optional[str] = None
        self.error: Optional[str] = None

        self._client: Optional[Client] = None  # running userbot
        self._login_client: Optional[Client] = None  # transient during login
        self._login_phone: Optional[str] = None
        self._login_hash: Optional[str] = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ status
    def snapshot(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "username": self.username,
            "error": self.error,
            "login_pending": self._login_client is not None,
        }

    def _api_creds(self) -> tuple[int, str]:
        cfg = config_store.load_config()
        tg = cfg.get("telegram", {})
        api_id = tg.get("api_id")
        api_hash = tg.get("api_hash")
        if not api_id or not api_hash:
            raise UserbotError("Chưa cấu hình api_id / api_hash (tab Telegram).")
        try:
            api_id = int(api_id)
        except (TypeError, ValueError):
            raise UserbotError("api_id phải là số.")
        return api_id, api_hash

    # ------------------------------------------------------------ login flow
    async def send_code(self, phone: str) -> Dict[str, Any]:
        async with self._lock:
            phone = (phone or "").strip()
            if not phone:
                raise UserbotError("Vui lòng nhập số điện thoại.")
            api_id, api_hash = self._api_creds()

            # Drop any previous half-finished login attempt.
            await self._cleanup_login_client()

            client = Client(
                name="login",
                api_id=api_id,
                api_hash=api_hash,
                in_memory=True,
            )
            await client.connect()
            try:
                sent = await client.send_code(phone)
            except PhoneNumberInvalid:
                await self._safe_disconnect(client)
                raise UserbotError("Số điện thoại không hợp lệ.")
            except Exception as exc:  # network / api_id mismatch, etc.
                await self._safe_disconnect(client)
                raise UserbotError(f"Không gửi được mã: {exc}")

            self._login_client = client
            self._login_phone = phone
            self._login_hash = sent.phone_code_hash
            bus.log(f"Đã gửi mã đăng nhập tới {phone}", source="userbot")
            return {"sent": True}

    async def sign_in(self, code: str) -> Dict[str, Any]:
        async with self._lock:
            code = (code or "").strip()
            if not self._login_client:
                raise UserbotError("Chưa gửi mã. Hãy bấm 'Gửi mã' trước.")
            if not code:
                raise UserbotError("Vui lòng nhập mã xác nhận.")
            try:
                user = await self._login_client.sign_in(
                    self._login_phone, self._login_hash, code
                )
            except SessionPasswordNeeded:
                bus.log("Tài khoản bật 2FA — cần mật khẩu.", level="warning", source="userbot")
                return {"need_password": True}
            except (PhoneCodeInvalid, PhoneCodeExpired) as exc:
                raise UserbotError(f"Mã không đúng hoặc đã hết hạn: {exc.__class__.__name__}")
            except Exception as exc:
                raise UserbotError(f"Đăng nhập thất bại: {exc}")

            return await self._finish_login(user)

    async def check_password(self, password: str) -> Dict[str, Any]:
        async with self._lock:
            if not self._login_client:
                raise UserbotError("Phiên đăng nhập đã hết hạn, hãy gửi mã lại.")
            if not password:
                raise UserbotError("Vui lòng nhập mật khẩu 2FA.")
            try:
                user = await self._login_client.check_password(password)
            except PasswordHashInvalid:
                raise UserbotError("Mật khẩu 2FA không đúng.")
            except Exception as exc:
                raise UserbotError(f"Xác thực 2FA thất bại: {exc}")
            return await self._finish_login(user)

    async def _finish_login(self, user: Any) -> Dict[str, Any]:
        assert self._login_client is not None
        session_string = await self._login_client.export_session_string()
        username = user.username or user.first_name or str(user.id)
        config_store.update_section(
            "telegram",
            {"session_string": session_string, "logged_in_user": username},
        )
        await self._cleanup_login_client()
        bus.log(f"Đăng nhập Telegram thành công: {username}", source="userbot")
        # Bring the userbot online immediately after login.
        await self._start_locked()
        return {"logged_in": True, "username": username}

    # -------------------------------------------------------------- runtime
    async def start(self) -> Dict[str, Any]:
        async with self._lock:
            return await self._start_locked()

    async def _start_locked(self) -> Dict[str, Any]:
        if self.status == "online" and self._client is not None:
            return self.snapshot()
        api_id, api_hash = self._api_creds()
        cfg = config_store.load_config()
        session_string = cfg.get("telegram", {}).get("session_string")
        if not session_string:
            raise UserbotError("Chưa đăng nhập Telegram. Hãy đăng nhập ở tab Telegram.")

        self.status = "starting"
        self.error = None
        bus.log("Đang khởi động userbot…", source="userbot")
        client = Client(
            name="userbot",
            api_id=api_id,
            api_hash=api_hash,
            session_string=session_string,
            in_memory=True,
        )
        try:
            await client.start()
            me = await client.get_me()
        except Exception as exc:
            self.status = "error"
            self.error = str(exc)
            await self._safe_disconnect(client)
            bus.log(f"Userbot lỗi khi khởi động: {exc}", level="error", source="userbot")
            raise UserbotError(f"Không khởi động được userbot: {exc}")

        self._client = client
        self.username = me.username or me.first_name or str(me.id)
        self.status = "online"
        bus.log(f"Userbot ONLINE: @{self.username}", source="userbot")
        return self.snapshot()

    async def stop(self) -> Dict[str, Any]:
        async with self._lock:
            if self._client is not None:
                try:
                    await self._client.stop()
                except Exception:
                    pass
                self._client = None
            self.status = "stopped"
            bus.log("Userbot đã DỪNG.", level="warning", source="userbot")
            return self.snapshot()

    async def logout(self) -> Dict[str, Any]:
        """Stop the userbot and clear the saved session."""
        await self.stop()
        async with self._lock:
            config_store.update_section(
                "telegram", {"session_string": None, "logged_in_user": None}
            )
            self.username = None
            bus.log("Đã đăng xuất Telegram (xoá session).", level="warning", source="userbot")
            return self.snapshot()

    # -------------------------------------------------------------- helpers
    async def _cleanup_login_client(self) -> None:
        if self._login_client is not None:
            await self._safe_disconnect(self._login_client)
        self._login_client = None
        self._login_phone = None
        self._login_hash = None

    @staticmethod
    async def _safe_disconnect(client: Client) -> None:
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception:
            pass


# Singleton manager shared by the web layer.
manager = UserbotManager()
