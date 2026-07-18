"""Optional Redis client.

Returns a live async Redis connection when REDIS_URL is set, otherwise None.
Callers must handle the None case and fall back to in-memory behaviour, so the
template runs with zero external dependencies out of the box.
"""
from __future__ import annotations

import contextlib

from app.config import settings
from app.logging_config import logger

_redis = None
_initialised = False


def get_redis():
    """Lazily create (once) and return the async Redis client, or None."""
    global _redis, _initialised
    if _initialised:
        return _redis
    _initialised = True
    if not settings.redis_enabled:
        return None
    try:
        import redis.asyncio as aioredis

        _redis = aioredis.from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
        logger.info("Redis enabled (%s).", settings.REDIS_URL.split("@")[-1])
    except Exception as exc:  # pragma: no cover
        logger.warning("Redis unavailable, falling back to in-memory: %s", exc)
        _redis = None
    return _redis


async def close_redis() -> None:
    global _redis, _initialised
    if _redis is not None:
        with contextlib.suppress(Exception):  # pragma: no cover
            await _redis.aclose()
    _redis = None
    _initialised = False
