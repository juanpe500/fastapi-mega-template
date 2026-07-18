"""One-time 2FA recovery codes (stored hashed)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class RecoveryCode(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "recovery_codes"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    used: Mapped[bool] = mapped_column(default=False)
