"""Admin-editable key/value settings & feature flags (no redeploy needed)."""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AppSetting(TimestampMixin, Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    # str | int | float | bool | json — used to coerce on read.
    value_type: Mapped[str] = mapped_column(String(10), default="str")
    description: Mapped[str] = mapped_column(String(255), default="")
