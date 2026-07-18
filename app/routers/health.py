"""Liveness + readiness endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import __version__
from app.config import settings
from app.database import get_db
from app.redis_client import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    """Liveness — cheap, no dependencies."""
    return {"status": "ok", "app": settings.APP_NAME, "version": __version__}


@router.get("/health/ready")
async def ready(db: AsyncSession = Depends(get_db)) -> dict:
    """Readiness — checks DB (and Redis if configured)."""
    checks: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # pragma: no cover
        checks["database"] = f"error: {exc}"

    redis = get_redis()
    if redis is not None:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # pragma: no cover
            checks["redis"] = f"error: {exc}"

    ok = all(v == "ok" for v in checks.values())
    return {"status": "ok" if ok else "degraded", "checks": checks}
