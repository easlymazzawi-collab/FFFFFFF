"""Web-session auth helpers.

The web dashboard is protected by a single password that the operator sets on
first visit (stored only as a salted hash in ``auto_config.json`` — never the
plaintext, and never in a ``.env``). Sessions use a signed, timed cookie.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from core import config_store

COOKIE_NAME = "ub_session"
_MAX_AGE = 7 * 24 * 3600  # 7 days


def _serializer() -> URLSafeTimedSerializer:
    cfg = config_store.load_config()
    secret = cfg["web"]["secret_key"]
    return URLSafeTimedSerializer(secret, salt="ub-web-session")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return f"sha256${salt}${digest}"


def verify_password(password: str, stored: Optional[str]) -> bool:
    if not stored:
        return False
    try:
        algo, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    if algo != "sha256":
        return False
    check = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(check, digest)


def password_is_set() -> bool:
    return bool(config_store.load_config()["web"].get("password_hash"))


def set_password(password: str) -> None:
    config_store.update_section("web", {"password_hash": hash_password(password)})


def make_session_token() -> str:
    return _serializer().dumps({"auth": True})


def is_valid_session(token: Optional[str]) -> bool:
    if not token:
        return False
    try:
        data = _serializer().loads(token, max_age=_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return False
    return bool(isinstance(data, dict) and data.get("auth"))
