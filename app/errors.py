"""Exception handlers: friendly error pages + persistence of 500s to the DB
(viewable at /admin/errors) with an optional Telegram alert.
"""
from __future__ import annotations

import traceback as tb

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import SessionLocal
from app.logging_config import logger
from app.security.tokens import decode_token
from app.templating import render


def _wants_json(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return request.url.path.startswith(("/api/", "/health")) or "application/json" in accept


async def _persist_error(request: Request, exc: Exception, status_code: int) -> None:
    from app.models.errorlog import ErrorLog  # local import to avoid cycles

    user_id = None
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        payload = decode_token(token, expected_type="access")
        if payload:
            user_id = payload.get("sub")
    try:
        async with SessionLocal() as db:
            db.add(ErrorLog(
                path=str(request.url.path)[:500],
                method=request.method,
                status_code=status_code,
                message=str(exc)[:2000],
                traceback="".join(tb.format_exception(type(exc), exc, exc.__traceback__))[:8000],
                user_id=user_id,
            ))
            await db.commit()
    except Exception:  # pragma: no cover — never let logging errors mask the original
        logger.exception("Failed to persist ErrorLog")


async def _telegram_alert(message: str) -> None:
    if not (settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID):
        return
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": message[:4000]},
            )
    except Exception:  # pragma: no cover
        pass


def register_error_handlers(app: FastAPI) -> None:
    from fastapi.responses import JSONResponse

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if exc.status_code == status.HTTP_404_NOT_FOUND and not _wants_json(request):
            return render(request, "errors/404.html", {}, status_code=404)
        if _wants_json(request):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        # Fall back to a generic page for other client errors on HTML routes.
        if exc.status_code >= 500:
            return render(request, "errors/500.html", {}, status_code=exc.status_code)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        if _wants_json(request):
            return JSONResponse({"detail": exc.errors()}, status_code=422)
        return render(request, "errors/422.html", {"errors": exc.errors()}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        await _persist_error(request, exc, 500)
        await _telegram_alert(f"[{settings.APP_NAME}] 500 on {request.url.path}: {exc}")
        if _wants_json(request):
            return JSONResponse({"detail": "Internal server error"}, status_code=500)
        return render(request, "errors/500.html", {}, status_code=500)
