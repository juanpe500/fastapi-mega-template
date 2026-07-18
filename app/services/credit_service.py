"""Credit wallet: an append-only ledger kept in sync with User.credits_balance.

Every grant/spend writes a CreditTransaction row recording the resulting
balance, so the ledger is auditable and the balance is always reconstructable.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import CreditTransaction
from app.models.user import User


class InsufficientCredits(Exception):
    pass


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


async def get_balance(db: AsyncSession, user: User) -> Decimal:
    return _dec(user.credits_balance or 0)


async def add_credits(
    db: AsyncSession,
    user: User,
    amount,
    *,
    kind: str = "purchase",
    description: str = "",
    reference_id: str | None = None,
) -> CreditTransaction:
    """Grant credits. If reference_id is given and already recorded, this is a
    no-op (idempotent) — important for Stripe webhook retries."""
    amount = _dec(amount)
    if reference_id:
        existing = (
            await db.execute(
                select(CreditTransaction).where(
                    CreditTransaction.reference_id == reference_id,
                    CreditTransaction.kind == kind,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing

    user.credits_balance = _dec(user.credits_balance or 0) + amount
    tx = CreditTransaction(
        user_id=user.id,
        amount=amount,
        balance_after=user.credits_balance,
        kind=kind,
        description=description,
        reference_id=reference_id,
    )
    db.add(tx)
    await db.flush()
    return tx


async def deduct_credits(
    db: AsyncSession,
    user: User,
    amount,
    *,
    description: str = "",
    reference_id: str | None = None,
    allow_negative: bool = False,
) -> CreditTransaction:
    """Spend credits. Raises InsufficientCredits unless allow_negative."""
    amount = _dec(amount)
    balance = _dec(user.credits_balance or 0)
    if not allow_negative and balance < amount:
        raise InsufficientCredits(f"Need {amount}, have {balance}")

    user.credits_balance = balance - amount
    tx = CreditTransaction(
        user_id=user.id,
        amount=-amount,
        balance_after=user.credits_balance,
        kind="spend",
        description=description,
        reference_id=reference_id,
    )
    db.add(tx)
    await db.flush()
    return tx


async def history(db: AsyncSession, user: User, limit: int = 100) -> list[CreditTransaction]:
    rows = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )
    return list(rows.scalars().all())
