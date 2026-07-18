"""Security-headers middleware: CSP, HSTS, framing, MIME, plus a cache-control
split (immutable for /static, no-cache elsewhere) that pairs with the
?v=DEPLOY_VERSION asset versioning.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from app.config import settings

TURNSTILE_HOST = "https://challenges.cloudflare.com"


def _build_csp() -> str:
    script_extra = settings.CSP_EXTRA_SCRIPT_SRC.strip()
    style_extra = settings.CSP_EXTRA_STYLE_SRC.strip()
    connect_extra = settings.CSP_EXTRA_CONNECT_SRC.strip()
    frame_src = "'self'"
    if settings.turnstile_enabled:
        # Turnstile loads a script and renders its challenge inside an iframe.
        script_extra = f"{script_extra} {TURNSTILE_HOST}".strip()
        connect_extra = f"{connect_extra} {TURNSTILE_HOST}".strip()
        frame_src = f"'self' {TURNSTILE_HOST}"
    directives = [
        "default-src 'self'",
        f"script-src 'self' 'unsafe-inline' {script_extra}".strip(),
        f"style-src 'self' 'unsafe-inline' {style_extra}".strip(),
        "img-src 'self' data: blob: https:",
        "font-src 'self' data:",
        f"connect-src 'self' {connect_extra}".strip(),
        f"frame-src {frame_src}",
        "frame-ancestors 'self'",
        "form-action 'self'",
        "base-uri 'self'",
        "object-src 'none'",
    ]
    if settings.is_prod:
        directives.append("upgrade-insecure-requests")
    return "; ".join(directives)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.csp = _build_csp()

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", self.csp)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if settings.HSTS_ENABLED:
            h.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains; preload"
            )
        # Cache split: versioned static assets are immutable; dynamic pages aren't cached.
        if request.url.path.startswith("/static/"):
            h["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            h.setdefault("Cache-Control", "no-cache")
        return response
