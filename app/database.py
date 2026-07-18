"""Async SQLAlchemy 2.0 engine + session, dual-backend (SQLite / Postgres).

The backend is chosen entirely by DATABASE_URL:
    sqlite+aiosqlite:///./app.db
    postgresql+asyncpg://user:pass@host:5432/db

Optional read/write splitting: set DATABASE_READ_URL to a replica and reads are
routed there while writes go to DATABASE_URL. Leave it blank for a single DB.
"""
from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.logging_config import logger


def _make_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    kwargs = {
        "echo": settings.SQL_ECHO,
        "future": True,
        "pool_pre_ping": True,
        "connect_args": connect_args,
    }
    # SQLite's async pool doesn't take size args; Postgres benefits from them.
    if not url.startswith("sqlite"):
        kwargs.update(pool_size=5, max_overflow=10, pool_recycle=1800, pool_timeout=30)
    return create_async_engine(url, **kwargs)


# Primary (writes + reads unless a replica is configured)
engine = _make_engine(settings.DATABASE_URL)

# Optional read replica
read_engine = _make_engine(settings.DATABASE_READ_URL) if settings.DATABASE_READ_URL else engine

SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
ReadSessionLocal = (
    async_sessionmaker(bind=read_engine, class_=AsyncSession, expire_on_commit=False)
    if read_engine is not engine
    else SessionLocal
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Request-scoped read/write session. Commits on success, rolls back on error."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_read_db() -> AsyncGenerator[AsyncSession, None]:
    """Read-only session (routes to the replica when DATABASE_READ_URL is set)."""
    async with ReadSessionLocal() as session:
        yield session


async def create_all() -> None:
    """Create any missing tables from the ORM metadata.

    Used as a zero-config fallback so a fresh clone boots without running Alembic.
    Alembic remains the source of truth for schema *changes*.
    """
    from app.models.base import Base  # imported here to avoid a circular import

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured (create_all).")
