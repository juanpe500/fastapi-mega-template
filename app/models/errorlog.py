"""Persisted server errors, surfaced in the admin panel (/admin/errors)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class ErrorLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "error_logs"

    path: Mapped[str] = mapped_column(String(500), default="")
    method: Mapped[str] = mapped_column(String(10), default="")
    status_code: Mapped[int] = mapped_column(default=500)
    # Correlation id shared with logs / Sentry for this same request.
    request_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    traceback: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    resolved: Mapped[bool] = mapped_column(default=False, index=True)
