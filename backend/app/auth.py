"""Console session cookies, email webhook signatures, and widget origins.

The demo password and webhook secret are defaults for a local portfolio.
Set KEEL_CONSOLE_PASSWORD, KEEL_SESSION_SECRET, and KEEL_EMAIL_WEBHOOK_SECRET
before exposing this process beyond localhost.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlparse

from fastapi import HTTPException, Request

COOKIE = "keel_console"
MAX_AGE = 60 * 60 * 12
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def sign_session(secret: str, now: int | None = None) -> str:
    expiry = int(now if now is not None else time.time()) + MAX_AGE
    mac = hmac.new(secret.encode(), str(expiry).encode(), hashlib.sha256).hexdigest()
    return f"{expiry}.{mac}"


def session_ok(token: str | None, secret: str, now: int | None = None) -> bool:
    if not token or "." not in token:
        return False
    expiry_text, mac = token.split(".", 1)
    if not expiry_text.isdigit():
        return False
    expected = hmac.new(secret.encode(), expiry_text.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, mac):
        return False
    current = int(now if now is not None else time.time())
    return current < int(expiry_text)


def require_console(request: Request) -> None:
    settings = request.app.state.settings
    token = request.cookies.get(COOKIE)
    if not session_ok(token, settings.session_secret):
        raise HTTPException(401, "Sign in to the console.")


def sign_webhook(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def require_webhook(secret: str, body: bytes, header: str | None) -> None:
    if not secret:
        raise HTTPException(401, "Email webhook secret is not configured.")
    if not header:
        raise HTTPException(401, "Missing email webhook signature.")
    expected = sign_webhook(secret, body)
    if not hmac.compare_digest(expected, header.strip()):
        raise HTTPException(401, "Email webhook signature does not match.")


def origin_allowed(origin: str | None, extra: str) -> bool:
    if origin is None or origin == "":
        return True
    parsed = urlparse(origin)
    host = (parsed.hostname or "").lower()
    if host in LOOPBACK:
        return True
    allowed = {item.strip().rstrip("/") for item in (extra or "").split(",") if item.strip()}
    return origin.rstrip("/") in allowed


def require_widget_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    settings = request.app.state.settings
    if origin_allowed(origin, settings.widget_origins):
        return
    raise HTTPException(403, "This origin is not allowed to call the widget.")
