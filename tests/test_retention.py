"""GDPR erasure must honour legal retention: personal data is anonymised, but
financial/tax records (invoices, credit ledger, subscriptions) are kept.

Uses a dedicated throwaway engine so the async work runs on a single event loop,
independent of the session-scoped TestClient.
"""
from __future__ import annotations

import asyncio
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path


def test_anonymize_scrubs_pii_but_keeps_financial_records():
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import app.models  # noqa: F401  (register every table on the metadata)
    from app.models.base import Base
    from app.models.billing import CreditTransaction, Subscription
    from app.models.billing_profile import BillingProfile
    from app.models.notification import Notification
    from app.models.user import User, UserSession
    from app.services import account_service

    tmp = Path(tempfile.gettempdir()) / f"retention_{uuid.uuid4().hex}.db"

    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with Session() as db:
            user = User(
                email="erase-me@example.com", display_name="Erase Me",
                avatar_url="http://x/a.png", api_key_hash="secret", totp_enabled=True,
            )
            db.add(user)
            await db.flush()
            uid = user.id

            db.add(CreditTransaction(
                user_id=uid, amount=Decimal("10"), balance_after=Decimal("10"),
                kind="purchase", reference_id="pi_test",
            ))
            db.add(Subscription(user_id=uid, status="active"))
            db.add(BillingProfile(user_id=uid, company_name="ACME", tax_id="ES123",
                                  address_line1="Main 1"))
            db.add(Notification(user_id=uid, title="hi there"))
            db.add(UserSession(user_id=uid, ip_address="1.2.3.4"))
            await db.commit()

            await account_service.anonymize(db, user)
            await db.commit()

            fresh = await db.get(User, uid)
            # Tombstone kept, every identifier scrubbed.
            assert fresh is not None
            assert fresh.purged_at is not None
            assert fresh.email == f"deleted-{account_service._pseudonym(uid)}@deleted.invalid"
            assert fresh.display_name == ""
            assert fresh.avatar_url is None
            assert fresh.api_key_hash is None
            assert fresh.totp_enabled is False
            assert fresh.is_active is False

            async def count(model):
                return (await db.execute(
                    select(func.count()).select_from(model).where(model.user_id == uid)
                )).scalar_one()

            # Financial/tax records retained.
            assert await count(CreditTransaction) == 1
            assert await count(Subscription) == 1
            assert await count(BillingProfile) == 1
            # Personal data with no retention duty is gone.
            assert await count(Notification) == 0
            assert await count(UserSession) == 0

        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        tmp.unlink(missing_ok=True)


def test_purge_due_accounts_only_touches_elapsed_grace():
    """purge_due_accounts anonymises past-grace requests and skips fresh ones and
    already-anonymised rows."""
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import app.models  # noqa: F401
    from app.config import settings
    from app.models.base import Base, utcnow
    from app.models.user import User
    from app.services import account_service

    tmp = Path(tempfile.gettempdir()) / f"retention_{uuid.uuid4().hex}.db"

    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        grace = settings.ACCOUNT_DELETION_GRACE_DAYS
        async with Session() as db:
            due = User(email="due@example.com",
                       deletion_requested_at=utcnow() - timedelta(days=grace + 1))
            fresh = User(email="fresh@example.com",
                         deletion_requested_at=utcnow() - timedelta(days=1))
            db.add_all([due, fresh])
            await db.commit()
            due_id, fresh_id = due.id, fresh.id

            n = await account_service.purge_due_accounts(db)
            await db.commit()
            assert n == 1

            assert (await db.get(User, due_id)).purged_at is not None
            assert (await db.get(User, fresh_id)).purged_at is None

            # Running again is a no-op (already anonymised is skipped).
            assert await account_service.purge_due_accounts(db) == 0

        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        tmp.unlink(missing_ok=True)
