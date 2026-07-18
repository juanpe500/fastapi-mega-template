"""CSRF protection using the double-submit-cookie pattern.

A random token is stored in a readable `csrf` cookie. Server-rendered forms embed
the same value in a hidden `_csrf` field (see `csrf_field` injected by render()),
and JS clients may echo it in an `X-CSRF-Token` header. On unsafe methods the two
must match — an attacker on another origin can neither read the cookie nor guess it.

Exempt: safe methods, header-authenticated requests (Bearer / X-API-Key — those
carry no ambient cookie authority), and a small path allowlist.
"""
from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import settings

COOKIE_NAME = "csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
# Paths that authenticate by other means and must not require a CSRF token.
EXEMPT_PREFIXES = (
    "/billing/webhook",  # Stripe (signature-verified, JSON body)
    "/auth/refresh",     # guarded by the httpOnly refresh cookie
)


def new_token() -> str:
    return secrets.token_urlsafe(32)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Ensures every request has a CSRF token available at `request.state.csrf`
    and that the cookie is set on the way out. Does not read the body."""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        token = request.cookies.get(COOKIE_NAME)
        is_new = not token
        if is_new:
            token = new_token()
        request.state.csrf = token

        response = await call_next(request)
        if is_new:
            response.set_cookie(
                COOKIE_NAME,
                token,
                max_age=60 * 60 * 24 * 7,
                httponly=False,  # readable by JS so it can send X-CSRF-Token
                secure=settings.cookie_secure,
                samesite="lax",
                domain=settings.COOKIE_DOMAIN or None,
                path="/",
            )
        return response


async def csrf_protect(request: Request) -> None:
    """App-wide dependency validating the token on state-changing requests."""
    if request.method in SAFE_METHODS:
        return
    if request.url.path.startswith(EXEMPT_PREFIXES):
        return
    # Header-authenticated (non-cookie) clients aren't subject to CSRF.
    if request.headers.get("authorization") or request.headers.get("x-api-key"):
        return

    cookie_token = request.cookies.get(COOKIE_NAME)
    submitted = request.headers.get("x-csrf-token")
    if not submitted:
        try:
            # FastAPI caches the parsed form, so endpoint Form(...) params still work.
            form = await request.form()
            submitted = form.get("_csrf")
        except Exception:  # not a form body
            submitted = None

    if not cookie_token or not submitted or not hmac.compare_digest(
        str(cookie_token), str(submitted)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid. Reload the page and try again.",
        )
