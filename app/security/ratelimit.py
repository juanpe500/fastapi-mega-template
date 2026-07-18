"""Proxy-aware rate limiting, used as a FastAPI dependency.

Backend auto-selects: Redis (shared across workers) when REDIS_URL is set,
otherwise an in-process fixed-window counter. Client IP is resolved from
cf-connecting-ip / x-forwarded-for / x-real-ip so it's correct behind a proxy.

    limiter = RateLimiter(times=5, seconds=60, scope="login")

    @router.post("/login", dependencies=[Depends(limiter)])
    async def login(...):
        ...
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

from app.config import settings
from app.redis_client import get_redis

# in-memory fallback: { key: [timestamps] }
_BUCKETS: dict[str, list[float]] = defaultdict(list)
_last_gc = 0.0


def client_ip(request: Request) -> str:
    hdr = request.headers
    cf = hdr.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = hdr.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = hdr.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "0.0.0.0"


def _gc(now: float) -> None:
    global _last_gc
    if now - _last_gc < 60 or len(_BUCKETS) < 1000:
        return
    _last_gc = now
    for key in list(_BUCKETS.keys()):
        if not _BUCKETS[key]:
            del _BUCKETS[key]


async def _allow_redis(key: str, times: int, seconds: int) -> bool:
    redis = get_redis()
    if redis is None:
        return await _allow_memory(key, times, seconds)
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, seconds)
        return count <= times
    except Exception:  # pragma: no cover — degrade to memory on Redis hiccup
        return await _allow_memory(key, times, seconds)


async def _allow_memory(key: str, times: int, seconds: int) -> bool:
    now = time.time()
    _gc(now)
    bucket = [t for t in _BUCKETS[key] if now - t < seconds]
    if len(bucket) >= times:
        _BUCKETS[key] = bucket
        return False
    bucket.append(now)
    _BUCKETS[key] = bucket
    return True


def _token_subject(request: Request) -> str | None:
    """User id straight from the JWT — no DB hit, and available even when the
    limiter runs before the auth dependency."""
    from app.security.tokens import decode_token

    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
    if not token:
        return None
    payload = decode_token(token, expected_type="access")
    return payload.get("sub") if payload else None


def rate_key(request: Request, scope: str, per_user: bool) -> str:
    """Bucket key. Per-user limits stop one abusive account hiding behind a shared
    office IP — and stop that one office IP throttling everybody else."""
    if per_user:
        uid = getattr(request.state, "user_id", None) or _token_subject(request)
        if uid:
            return f"rl:{scope}:u:{uid}"
    return f"rl:{scope}:{client_ip(request)}"


def RateLimiter(
    times: int | None = None,
    seconds: int | None = None,
    scope: str = "",
    per_user: bool = False,
):
    """Build a rate-limit dependency. Returned as a closure (a real function) so
    FastAPI resolves its `request: Request` parameter correctly even under
    `from __future__ import annotations`.

    `per_user=True` keys on the authenticated user when there is one, falling
    back to the client IP for anonymous requests.
    """
    limit = times if times is not None else settings.RATE_LIMIT_MAX
    window = seconds if seconds is not None else settings.RATE_LIMIT_WINDOW

    async def _dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        bucket_scope = scope or request.url.path
        key = rate_key(request, bucket_scope, per_user)
        allowed = (
            await _allow_redis(key, limit, window)
            if settings.redis_enabled
            else await _allow_memory(key, limit, window)
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests. Please slow down.",
                headers={"Retry-After": str(window)},
            )

    return _dependency
