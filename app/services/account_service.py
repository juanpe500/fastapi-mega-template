"""Account lifecycle: deactivation, deletion with a grace period, and data export.

Deletion is a two-stage process so it's recoverable and GDPR-compliant:
  1. The user requests deletion -> account is deactivated and stamped.
  2. After ACCOUNT_DELETION_GRACE_DAYS the scheduler purges it irreversibly.
Signing in during the grace window restores access and surfaces a "Cancel
deletion" banner — the schedule stands until they actually press it.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.logging_config import logger
from app.models.audit import AuditLog
from app.models.base import utcnow
from app.models.billing import CreditTransaction, Subscription
from app.models.billing_profile import BillingProfile
from app.models.notification import Notification
from app.models.oauth import OAuthAccount
from app.models.ticket import Ticket
from app.models.user import User, UserSession


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _row_to_dict(obj, fields: list[str]) -> dict:
    return {f: _json_safe(getattr(obj, f, None)) for f in fields}


async def export_user_data(db: AsyncSession, user: User) -> dict:
    """Everything we hold about this user, as a JSON-serialisable dict."""
    tickets = (
        await db.execute(
            select(Ticket)
            .options(selectinload(Ticket.messages))
            .where(Ticket.user_id == user.id)
        )
    ).scalars().all()
    transactions = (
        await db.execute(select(CreditTransaction).where(CreditTransaction.user_id == user.id))
    ).scalars().all()
    subs = (
        await db.execute(select(Subscription).where(Subscription.user_id == user.id))
    ).scalars().all()
    sessions = (
        await db.execute(select(UserSession).where(UserSession.user_id == user.id))
    ).scalars().all()
    oauth = (
        await db.execute(select(OAuthAccount).where(OAuthAccount.user_id == user.id))
    ).scalars().all()
    notes = (
        await db.execute(select(Notification).where(Notification.user_id == user.id))
    ).scalars().all()
    audit = (
        await db.execute(select(AuditLog).where(AuditLog.actor_id == user.id))
    ).scalars().all()
    profile = (
        await db.execute(select(BillingProfile).where(BillingProfile.user_id == user.id))
    ).scalar_one_or_none()

    return {
        "exported_at": utcnow().isoformat(),
        "account": _row_to_dict(user, [
            "id", "email", "username", "display_name", "avatar_url", "is_active",
            "email_verified", "credits_balance", "locale", "created_at", "updated_at",
            "last_login_at", "deactivated_at", "deletion_requested_at",
            "terms_version_accepted", "referral_code", "referred_by_id",
        ]),
        "roles": sorted(user.role_names),
        "billing_profile": _row_to_dict(profile, [
            "company_name", "tax_id", "address_line1", "address_line2",
            "city", "postal_code", "state", "country",
        ]) if profile else None,
        "subscriptions": [_row_to_dict(s, [
            "id", "status", "current_period_end", "cancel_at_period_end",
            "stripe_subscription_id", "created_at",
        ]) for s in subs],
        "credit_transactions": [_row_to_dict(t, [
            "id", "amount", "balance_after", "kind", "description", "reference_id", "created_at",
        ]) for t in transactions],
        "tickets": [{
            **_row_to_dict(t, ["id", "subject", "category", "status", "created_at"]),
            "messages": [_row_to_dict(m, ["id", "body", "is_staff", "created_at"])
                         for m in t.messages],
        } for t in tickets],
        "notifications": [_row_to_dict(n, ["id", "kind", "title", "body", "created_at", "read_at"])
                          for n in notes],
        "linked_accounts": [_row_to_dict(o, ["provider", "email", "created_at"]) for o in oauth],
        "sessions": [_row_to_dict(s, ["id", "ip_address", "user_agent", "created_at",
                                      "last_active_at", "is_active"]) for s in sessions],
        "audit_log": [_row_to_dict(a, ["action", "target_type", "target_id", "ip_address",
                                       "detail", "created_at"]) for a in audit],
    }


async def deactivate(db: AsyncSession, user: User) -> None:
    """Temporarily disable the account; logging back in reactivates it."""
    user.is_active = False
    user.deactivated_at = utcnow()
    await _revoke_sessions(db, user)


async def reactivate(db: AsyncSession, user: User) -> None:
    user.is_active = True
    user.deactivated_at = None
    user.deletion_requested_at = None


async def request_deletion(db: AsyncSession, user: User) -> None:
    user.deletion_requested_at = utcnow()
    user.is_active = False
    user.deactivated_at = utcnow()
    await _revoke_sessions(db, user)


async def cancel_deletion(db: AsyncSession, user: User) -> None:
    user.deletion_requested_at = None
    user.is_active = True
    user.deactivated_at = None


async def _revoke_sessions(db: AsyncSession, user: User) -> None:
    rows = await db.execute(select(UserSession).where(UserSession.user_id == user.id))
    for s in rows.scalars().all():
        s.is_active = False


def deletion_due_at(user: User):
    if not user.deletion_requested_at:
        return None
    from app.models.base import aware

    return aware(user.deletion_requested_at) + timedelta(days=settings.ACCOUNT_DELETION_GRACE_DAYS)


async def purge_due_accounts(db: AsyncSession) -> int:
    """Irreversibly delete accounts whose grace period has elapsed.

    Related rows go with the user via ON DELETE CASCADE; audit entries keep a
    null actor so the security trail survives the account.
    """
    cutoff = utcnow() - timedelta(days=settings.ACCOUNT_DELETION_GRACE_DAYS)
    rows = await db.execute(
        select(User).where(
            User.deletion_requested_at.is_not(None), User.deletion_requested_at < cutoff
        )
    )
    users = list(rows.scalars().all())
    for user in users:
        logger.info("Purging account %s (grace period elapsed).", user.id)
        await db.delete(user)
    return len(users)
