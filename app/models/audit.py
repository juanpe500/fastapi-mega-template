"""Audit log of security- and admin-relevant actions."""
from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class AuditLog(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "audit_logs"

    # Who did it (null for anonymous/system events).
    actor_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )
    action: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(50), default=None)
    target_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    ip_address: Mapped[str | None] = mapped_column(String(64), default=None)
    detail: Mapped[str] = mapped_column(Text, default="")
