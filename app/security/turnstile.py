"""Cloudflare Turnstile verification (bot protection).

No-ops (returns True) unless both TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY are
set, so development and tests run unimpeded.
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.logging_config import logger

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify(token: str, remote_ip: str | None = None) -> bool:
    if not settings.turnstile_enabled:
        return True
    if not token:
        return False
    data = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.post(VERIFY_URL, data=data)
        return bool(res.json().get("success"))
    except Exception as exc:  # pragma: no cover — fail closed on verification errors
        logger.warning("Turnstile verification error: %s", exc)
        return False
