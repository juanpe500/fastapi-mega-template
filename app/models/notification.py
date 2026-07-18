"""In-app notifications + per-type email preferences."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class Notification(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Matches a key in app.services.notifications.KINDS
    kind: Mapped[str] = mapped_column(String(50), default="general", index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(500), default=None)
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None, index=True
    )


class NotificationPreference(UUIDMixin, TimestampMixin, Base):
    """Opt-out record per (user, kind). Absent row = provider default."""

    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "kind", name="uq_user_kind"),)

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    email_enabled: Mapped[bool] = mapped_column(default=True)
