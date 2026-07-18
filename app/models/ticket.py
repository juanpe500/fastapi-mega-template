"""Support tickets: a two-party thread (user <-> staff) with optional attachments."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDMixin, utcnow


class Ticket(UUIDMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "tickets"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="general")
    # open | pending | closed
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    last_reply_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )

    messages: Mapped[list[TicketMessage]] = relationship(
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketMessage.created_at",
    )


class TicketMessage(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "ticket_messages"

    ticket_id: Mapped[str] = mapped_column(
        ForeignKey("tickets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sender_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    is_staff: Mapped[bool] = mapped_column(default=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_url: Mapped[str | None] = mapped_column(String(500), default=None)
    attachment_type: Mapped[str | None] = mapped_column(String(50), default=None)

    ticket: Mapped[Ticket] = relationship(back_populates="messages")
