"""Declarative base + shared mixins/helpers used by every model."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def gen_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


def aware(dt: datetime | None) -> datetime | None:
    """Coerce a possibly-naive datetime to UTC-aware.

    SQLite doesn't persist tz info, so DateTime(timezone=True) columns read back
    naive there but aware on Postgres. Normalise before any arithmetic/compare.
    """
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class Base(DeclarativeBase):
    pass


class SoftDeleteMixin:
    """Adds a `deleted_at` tombstone. Rows stay in the DB so they can be restored
    from the admin trash; filter them out in queries with `.where(X.deleted_at.is_(None))`."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class UUIDMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
