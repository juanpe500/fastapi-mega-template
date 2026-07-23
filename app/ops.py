"""Operational middleware: maintenance mode and Prometheus metrics.

Maintenance mode is driven by the `maintenance_mode` app setting (admin-editable,
no redeploy). Admins and a small allowlist of paths still get through so you can
turn it back off. The flag is cached briefly so we don't hit the DB every request.

Metrics are collected in-process and rendered in Prometheus text format — no
extra dependency needed.
"""
from __future__ import annotations

import time
import uuid
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings
from app.logging_config import request_id_var


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign every request a correlation id (honouring an inbound X-Request-ID
    from a proxy), expose it via the contextvar for logs/errors, and echo it back
    on the response so a client can quote it in a bug report."""

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID", "").strip()[:64] or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

# --- maintenance flag cache -------------------------------------------------
_flag_value = False
_flag_checked_at = 0.0
_FLAG_TTL = 10.0  # seconds

# Reachable even during maintenance, so you can log in and switch it off.
_ALLOWED_PREFIXES = (
    "/health", "/metrics", "/status", "/static", "/login", "/logout", "/admin", "/favicon",
)


async def maintenance_enabled() -> bool:
    global _flag_value, _flag_checked_at
    now = time.time()
    if now - _flag_checked_at < _FLAG_TTL:
        return _flag_value
    _flag_checked_at = now
    try:
        from app.database import SessionLocal
        from app.services import settings_service

        async with SessionLocal() as db:
            _flag_value = bool(await settings_service.get(db, "maintenance_mode", False))
    except Exception:  # pragma: no cover — never let this take the site down
        _flag_value = False
    return _flag_value


def reset_maintenance_cache() -> None:
    """Force the next request to re-read the flag (called after an admin edit)."""
    global _flag_checked_at
    _flag_checked_at = 0.0


class MaintenanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(_ALLOWED_PREFIXES) or not await maintenance_enabled():
            return await call_next(request)

        # Admins keep full access while the site is closed to everyone else.
        from app.database import SessionLocal  # local imports: avoid an import cycle
        from app.security.deps import _extract_token, _user_from_token

        token = _extract_token(request)
        if token:
            async with SessionLocal() as db:
                user = await _user_from_token(token, db)
                if user and user.has_role("admin"):
                    return await call_next(request)

        from app.templating import render

        return render(request, "errors/maintenance.html", {}, status_code=503)


# --- metrics ----------------------------------------------------------------
_requests: dict[tuple[str, int], int] = defaultdict(int)
_duration_sum: dict[str, float] = defaultdict(float)
_duration_count: dict[str, int] = defaultdict(int)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - started
        # Group by route template (not raw path) to keep cardinality bounded.
        route = request.scope.get("route")
        label = getattr(route, "path", None) or "unmatched"
        _requests[(request.method, response.status_code)] += 1
        _duration_sum[label] += elapsed
        _duration_count[label] += 1
        return response


def render_metrics() -> str:
    lines = [
        "# HELP app_requests_total Total HTTP requests.",
        "# TYPE app_requests_total counter",
    ]
    for (method, code), count in sorted(_requests.items()):
        lines.append(f'app_requests_total{{method="{method}",status="{code}"}} {count}')

    lines += [
        "# HELP app_request_duration_seconds_sum Total request duration per route.",
        "# TYPE app_request_duration_seconds_sum counter",
    ]
    for label, total in sorted(_duration_sum.items()):
        lines.append(f'app_request_duration_seconds_sum{{route="{label}"}} {total:.6f}')

    lines += [
        "# HELP app_request_duration_seconds_count Request count per route.",
        "# TYPE app_request_duration_seconds_count counter",
    ]
    for label, count in sorted(_duration_count.items()):
        lines.append(f'app_request_duration_seconds_count{{route="{label}"}} {count}')

    lines += [
        "# HELP app_info Static build information.",
        "# TYPE app_info gauge",
        f'app_info{{version="{settings.DEPLOY_VERSION}",env="{settings.ENV}"}} 1',
    ]
    return "\n".join(lines) + "\n"
