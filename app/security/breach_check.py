"""Have I Been Pwned password check via k-anonymity.

Only the first 5 characters of the SHA-1 hash ever leave this process; HIBP
returns every suffix in that bucket and we match locally. The password itself
is never transmitted. Fails OPEN (allows the password) if the API is
unreachable, so an outage can't lock users out of signing up.
"""
from __future__ import annotations

import hashlib

import httpx

from app.config import settings
from app.logging_config import logger

API = "https://api.pwnedpasswords.com/range/"


async def breach_count(password: str) -> int:
    """How many known breaches contain this password (0 = not found)."""
    if not settings.HIBP_ENABLED or not password:
        return 0
    digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
    prefix, suffix = digest[:5], digest[5:]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.get(
                f"{API}{prefix}", headers={"Add-Padding": "true"}
            )
        res.raise_for_status()
    except Exception as exc:  # pragma: no cover — never block signup on an outage
        logger.warning("HIBP lookup failed (allowing password): %s", exc)
        return 0

    for line in res.text.splitlines():
        candidate, _, count = line.partition(":")
        if candidate.strip() == suffix:
            return int(count or 0)
    return 0


async def is_breached(password: str) -> bool:
    return await breach_count(password) > 0
