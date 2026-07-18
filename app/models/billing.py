"""Billing: plans, subscriptions, a credit ledger, and a Stripe-event dedup table.

Two economies are supported side by side (turn either off by not using it):
  * Credits  — one-time top-ups via Stripe Checkout, tracked as a ledger.
  * Subscriptions — recurring plans via Stripe, synced from webhooks.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Plan(UUIDMixin, TimestampMixin, Base):
    """A purchasable plan. Subscription plans carry Stripe price ids; credit
    packs carry a `credits_granted` amount. `kind` distinguishes them."""

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(20), default="subscription")  # subscription | credit

    price_cents: Mapped[int] = mapped_column(default=0)
    currency: Mapped[str] = mapped_column(String(10), default="usd")
    interval: Mapped[str | None] = mapped_column(String(10), default=None)  # month | year | None

    # Stripe price id for subscription/one-time; blank for a free plan.
    stripe_price_id: Mapped[str | None] = mapped_column(String(64), default=None)
    # For credit packs: how many credits this grants.
    credits_granted: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))

    is_active: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(default=0)


class Subscription(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), default=None)

    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, default=None
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(64), index=True, default=None)

    # active | trialing | past_due | canceled | incomplete | unpaid
    status: Mapped[str] = mapped_column(String(30), default="incomplete", index=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(default=False)

    plan: Mapped[Plan | None] = relationship(lazy="selectin")

    @property
    def is_active(self) -> bool:
        return self.status in ("active", "trialing")


class CreditTransaction(UUIDMixin, TimestampMixin, Base):
    """Append-only ledger. Positive amount = grant, negative = spend."""

    __tablename__ = "credit_transactions"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    # purchase | spend | refund | dispute | bonus | welcome | adjustment
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), default="")

    # External reference (Stripe payment_intent / session id, etc.) for idempotency & tracing.
    reference_id: Mapped[str | None] = mapped_column(String(120), index=True, default=None)


class StripeEvent(UUIDMixin, TimestampMixin, Base):
    """Dedup table so a webhook delivered more than once is processed exactly once."""

    __tablename__ = "stripe_events"

    event_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="processed")  # processed | error
    note: Mapped[str] = mapped_column(Text, default="")
