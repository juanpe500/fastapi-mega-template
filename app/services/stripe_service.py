"""Stripe integration: Checkout (credits + subscriptions), Customer Portal, and
an idempotent webhook dispatcher.

All Stripe network calls run in a worker thread (the SDK is synchronous). Every
webhook is recorded in `stripe_events` so a duplicate delivery is ignored.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging_config import logger
from app.models.billing import Plan, StripeEvent, Subscription
from app.models.user import User
from app.services import credit_service

try:
    import stripe as _stripe
except Exception:  # pragma: no cover
    _stripe = None


def get_stripe():
    if not settings.stripe_enabled or _stripe is None:
        return None
    _stripe.api_key = settings.STRIPE_SECRET_KEY
    return _stripe


async def ensure_customer(db: AsyncSession, user: User) -> str | None:
    """Return the user's Stripe customer id, creating the customer if needed."""
    stripe = get_stripe()
    if stripe is None:
        return None
    if user.stripe_customer_id:
        return user.stripe_customer_id
    customer = await asyncio.to_thread(
        stripe.Customer.create, email=user.email, metadata={"user_id": user.id}
    )
    user.stripe_customer_id = customer["id"]
    await db.flush()
    return customer["id"]


async def create_checkout_session(db: AsyncSession, user: User, plan: Plan) -> str:
    """Create a Checkout Session for a credit pack (one-time) or subscription.
    Returns the redirect URL."""
    stripe = get_stripe()
    if stripe is None:
        raise RuntimeError("Stripe is not configured")
    customer_id = await ensure_customer(db, user)

    is_subscription = plan.kind == "subscription"
    line_items = [{"price": plan.stripe_price_id, "quantity": 1}]
    metadata = {"user_id": user.id, "plan_id": plan.id, "plan_code": plan.code, "kind": plan.kind}

    kwargs: dict = {
        "mode": "subscription" if is_subscription else "payment",
        "customer": customer_id,
        "line_items": line_items,
        "metadata": metadata,
        "subscription_data": {"metadata": metadata} if is_subscription else None,
        "success_url": f"{settings.BASE_URL}/account/billing?success=1"
                       f"&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{settings.BASE_URL}/account/billing?canceled=1",
        "allow_promotion_codes": True,
    }
    if settings.STRIPE_TAX_ENABLED:
        # Requires Stripe Tax to be activated in the dashboard. Stripe then computes
        # VAT/sales tax per customer address and stores it on the invoice.
        kwargs["automatic_tax"] = {"enabled": True}
        kwargs["tax_id_collection"] = {"enabled": True}
        kwargs["customer_update"] = {"address": "auto", "name": "auto"}
        if is_subscription:
            kwargs["subscription_data"]["metadata"] = metadata

    session = await asyncio.to_thread(stripe.checkout.Session.create, **kwargs)
    return session["url"]


async def create_portal_session(db: AsyncSession, user: User) -> str:
    stripe = get_stripe()
    if stripe is None:
        raise RuntimeError("Stripe is not configured")
    customer_id = await ensure_customer(db, user)
    kwargs = {"customer": customer_id, "return_url": f"{settings.BASE_URL}/account/billing"}
    if settings.STRIPE_PORTAL_CONFIGURATION_ID:
        kwargs["configuration"] = settings.STRIPE_PORTAL_CONFIGURATION_ID
    session = await asyncio.to_thread(stripe.billing_portal.Session.create, **kwargs)
    return session["url"]


# ---------------------------------------------------------------- webhook ----
async def handle_webhook(db: AsyncSession, payload: bytes, sig_header: str) -> dict:
    stripe = get_stripe()
    if stripe is None:
        raise RuntimeError("Stripe is not configured")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as exc:
        raise ValueError("Invalid payload") from exc
    except stripe.error.SignatureVerificationError as exc:  # type: ignore[attr-defined]
        raise ValueError("Invalid signature") from exc

    event_id = event["id"]
    # Idempotency: skip if we've already processed this event.
    seen = (
        await db.execute(select(StripeEvent).where(StripeEvent.event_id == event_id))
    ).scalar_one_or_none()
    if seen:
        return {"received": True, "duplicate": True}

    record = StripeEvent(event_id=event_id, type=event["type"])
    db.add(record)

    try:
        await _dispatch(db, event)
    except Exception as exc:  # keep a record even on handler failure
        record.status = "error"
        record.note = str(exc)[:1000]
        logger.exception("Stripe handler failed for %s", event["type"])
        raise
    return {"received": True}


async def _dispatch(db: AsyncSession, event: dict) -> None:
    etype = event["type"]
    obj = event["data"]["object"]
    handlers = {
        "checkout.session.completed": _on_checkout_completed,
        "customer.subscription.created": _on_subscription_upsert,
        "customer.subscription.updated": _on_subscription_upsert,
        "customer.subscription.deleted": _on_subscription_deleted,
        "invoice.payment_succeeded": _on_invoice_paid,
        "charge.refunded": _on_charge_refunded,
        "charge.dispute.created": _on_dispute_created,
        "charge.dispute.closed": _on_dispute_closed,
    }
    handler = handlers.get(etype)
    if handler:
        await handler(db, obj)
    else:
        logger.info("Stripe event ignored: %s", etype)


async def _user_by_id(db: AsyncSession, user_id: str | None) -> User | None:
    if not user_id:
        return None
    return await db.get(User, user_id)


async def _user_by_customer(db: AsyncSession, customer_id: str | None) -> User | None:
    if not customer_id:
        return None
    return (
        await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    ).scalar_one_or_none()


async def _on_checkout_completed(db: AsyncSession, session: dict) -> None:
    meta = session.get("metadata") or {}
    user = await _user_by_id(db, meta.get("user_id")) or await _user_by_customer(
        db, session.get("customer")
    )
    if not user:
        logger.warning("checkout.session.completed: user not found")
        return

    if meta.get("kind") == "credit":
        plan = (
            await db.execute(select(Plan).where(Plan.id == meta.get("plan_id")))
        ).scalar_one_or_none()
        if plan and plan.credits_granted:
            await credit_service.add_credits(
                db,
                user,
                plan.credits_granted,
                kind="purchase",
                description=f"Purchased {plan.name}",
                reference_id=session.get("payment_intent") or session.get("id"),
            )
    # Subscriptions are reconciled by the customer.subscription.* events.


async def _on_subscription_upsert(db: AsyncSession, sub: dict) -> None:
    user = await _user_by_customer(db, sub.get("customer"))
    meta = sub.get("metadata") or {}
    if not user:
        user = await _user_by_id(db, meta.get("user_id"))
    if not user:
        return

    row = (
        await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub["id"])
        )
    ).scalar_one_or_none()
    if not row:
        row = Subscription(user_id=user.id, stripe_subscription_id=sub["id"])
        db.add(row)

    row.stripe_customer_id = sub.get("customer")
    row.status = sub.get("status", "active")
    row.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
    period_end = sub.get("current_period_end")
    if period_end:
        row.current_period_end = datetime.fromtimestamp(period_end, tz=UTC)

    price_id = None
    items = (sub.get("items") or {}).get("data") or []
    if items:
        price_id = (items[0].get("price") or {}).get("id")
    if price_id:
        plan = (
            await db.execute(select(Plan).where(Plan.stripe_price_id == price_id))
        ).scalar_one_or_none()
        if plan:
            row.plan_id = plan.id


async def _on_subscription_deleted(db: AsyncSession, sub: dict) -> None:
    row = (
        await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub["id"])
        )
    ).scalar_one_or_none()
    if row:
        row.status = "canceled"
        row.cancel_at_period_end = True


async def _on_invoice_paid(db: AsyncSession, invoice: dict) -> None:
    # Subscription renewal — the subscription.updated event carries the new
    # period end, so nothing extra is needed here for the base template.
    logger.info("Invoice paid: %s", invoice.get("id"))


async def _on_charge_refunded(db: AsyncSession, charge: dict) -> None:
    pi = charge.get("payment_intent")
    if not pi:
        return
    from app.models.billing import CreditTransaction

    original = (
        await db.execute(
            select(CreditTransaction).where(
                CreditTransaction.reference_id == pi, CreditTransaction.kind == "purchase"
            )
        )
    ).scalar_one_or_none()
    if not original:
        return
    user = await db.get(User, original.user_id)
    if not user:
        return
    await credit_service.deduct_credits(
        db,
        user,
        original.amount,  # positive value of the original grant
        description="Refund",
        reference_id=pi,
        allow_negative=True,
    )


async def _on_dispute_created(db: AsyncSession, dispute: dict) -> None:
    logger.warning("Stripe dispute opened: %s", dispute.get("id"))


async def _on_dispute_closed(db: AsyncSession, dispute: dict) -> None:
    logger.warning("Stripe dispute closed (%s): %s", dispute.get("status"), dispute.get("id"))
