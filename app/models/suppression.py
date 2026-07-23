"""Email suppression list.

An address lands here after a hard bounce or a spam complaint (fed by your ESP's
webhook — see routers/email_webhook.py). send_email() checks it before every send
so you stop mailing dead/hostile addresses, which is what keeps your sender
reputation — and therefore your billing emails' deliverability — intact.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class SuppressedEmail(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "suppressed_emails"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # bounce | complaint | manual | unsubscribe
    reason: Mapped[str] = mapped_column(String(20), default="bounce", index=True)
    detail: Mapped[str] = mapped_column(String(500), default="")
