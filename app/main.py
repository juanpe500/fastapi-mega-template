"""Application factory + wiring.

    uvicorn app.main:app --reload           # dev
    gunicorn -c gunicorn.conf.py app.main:app  # prod
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from app import __version__, i18n
from app.config import settings
from app.database import create_all
from app.errors import register_error_handlers
from app.logging_config import logger
from app.ops import MaintenanceMiddleware, MetricsMiddleware, RequestIDMiddleware
from app.redis_client import close_redis
from app.scheduler import shutdown_scheduler, start_scheduler
from app.security.csrf import CSRFMiddleware, csrf_protect
from app.security.headers import SecurityHeadersMiddleware

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Zero-config first boot: ensure tables exist even if Alembic hasn't run.
    # Alembic remains the source of truth for schema *changes*.
    await create_all()
    from app.seed import run_seed

    await run_seed()
    i18n.load_catalogues()
    start_scheduler()
    logger.info("%s starting (env=%s, version=%s)", settings.APP_NAME, settings.ENV, __version__)
    yield
    shutdown_scheduler()
    await close_redis()


def create_app() -> FastAPI:
    if settings.SENTRY_DSN:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.SENTRY_DSN, environment=settings.ENV)
        except Exception as exc:  # pragma: no cover
            logger.warning("Sentry init failed: %s", exc)

    app = FastAPI(
        title=settings.APP_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        # CSRF is enforced app-wide; safe methods and header-auth requests pass through.
        dependencies=[Depends(csrf_protect)],
    )

    # --- middleware (order matters: last added runs first) ---
    app.add_middleware(CSRFMiddleware)
    # Maintenance runs before CSRF so a paused site short-circuits early.
    app.add_middleware(MaintenanceMiddleware)
    if settings.METRICS_ENABLED:
        app.add_middleware(MetricsMiddleware)
    if settings.SECURITY_HEADERS_ENABLED:
        app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=512)
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )
    # Outermost: stamp a correlation id before anything else runs, so every log
    # line and error record for the request carries it.
    app.add_middleware(RequestIDMiddleware)

    # --- static ---
    static_dir = BASE_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # --- error handlers ---
    register_error_handlers(app)

    # --- routers ---
    from app.routers import (
        account,
        auth,
        billing,
        email_webhook,
        files,
        health,
        notifications,
        oauth,
        ops,
        pages,
        tickets,
    )
    from app.routers import admin as admin_router

    app.include_router(health.router)
    app.include_router(ops.router)
    app.include_router(pages.router)
    app.include_router(notifications.router)
    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(tickets.router)
    app.include_router(billing.router)
    app.include_router(email_webhook.router)
    app.include_router(files.router)
    app.include_router(oauth.router)
    app.include_router(admin_router.router)

    return app


app = create_app()
