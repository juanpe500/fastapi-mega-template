"""Referral / affiliate codes.

Every user gets a short code and a shareable link (`{BASE_URL}/?ref=CODE`). The
code is stored in a cookie on landing and attributed at signup, so it survives
the visitor browsing around before registering.
"""
from __future__ import annotations

import secrets
import string

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.logging_config import logger
from app.models.user import User

COOKIE_NAME = "ref"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
_ALPHABET = string.ascii_lowercase + string.digits


def new_code(length: int = 8) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def referral_link(user: User) -> str | None:
    if not user.referral_code:
        return None
    return f"{settings.BASE_URL.rstrip('/')}/?ref={user.referral_code}"


async def ensure_code(db: AsyncSession, user: User) -> str:
    """Backfill a code for accounts created before referrals existed."""
    if not user.referral_code:
        user.referral_code = new_code()
        await db.flush()
    return user.referral_code


async def attribute_signup(db: AsyncSession, user: User, code: str | None) -> None:
    """Link a new signup to its referrer and pay the bonus, if configured."""
    if not settings.REFERRALS_ENABLED or not code:
        return
    referrer = (
        await db.execute(select(User).where(User.referral_code == code))
    ).scalar_one_or_none()
    if not referrer or referrer.id == user.id:
        return

    user.referred_by_id = referrer.id
    await db.flush()
    logger.info("Referral: %s attributed to %s", user.id, referrer.id)

    if settings.REFERRAL_BONUS_CREDITS > 0:
        from app.services import credit_service, notifications

        await credit_service.add_credits(
            db, referrer, settings.REFERRAL_BONUS_CREDITS,
            kind="bonus", description=f"Referral bonus ({user.email})",
            reference_id=f"referral:{user.id}",
        )
        await notifications.notify(
            db, referrer, "general", "You earned a referral bonus",
            f"{settings.REFERRAL_BONUS_CREDITS} credits were added for referring a new user.",
            link="/account/billing",
        )


async def referral_count(db: AsyncSession, user: User) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(User).where(User.referred_by_id == user.id)
        )
    ).scalar_one()
