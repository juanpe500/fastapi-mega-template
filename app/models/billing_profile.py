"""Customer billing details used on receipts/invoices (and sent to Stripe Tax)."""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin


class BillingProfile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "billing_profiles"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True, nullable=False
    )
    company_name: Mapped[str] = mapped_column(String(200), default="")
    # VAT / GST / ABN — printed on the receipt and used for reverse-charge rules.
    tax_id: Mapped[str] = mapped_column(String(60), default="")
    address_line1: Mapped[str] = mapped_column(String(200), default="")
    address_line2: Mapped[str] = mapped_column(String(200), default="")
    city: Mapped[str] = mapped_column(String(100), default="")
    postal_code: Mapped[str] = mapped_column(String(30), default="")
    state: Mapped[str] = mapped_column(String(100), default="")
    country: Mapped[str] = mapped_column(String(2), default="")  # ISO-3166 alpha-2
