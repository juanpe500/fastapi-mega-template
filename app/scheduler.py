"""Background jobs (APScheduler, in-process).

Enable with SCHEDULER_ENABLED=1. Runs inside the web process, which is fine for a
single-instance VPS. If you scale to multiple workers, run the scheduler in ONE
process only (e.g. a dedicated `SCHEDULER_ENABLED=1` worker, others 0) so jobs
don't execute N times.

Add your own jobs in `register_jobs()`.
"""
from __future__ import annotations

from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete, select, update

from app.config import settings
from app.database import SessionLocal
from app.logging_config import logger
from app.models.base import utcnow
from app.models.billing import Subscription
from app.models.user import User, UserSession

_scheduler: AsyncIOScheduler | None = None


# ----------------------------------------------------------------- jobs ----
async def purge_stale_sessions() -> None:
    """Delete sessions untouched for longer than SESSION_RETENTION_DAYS."""
    cutoff = utcnow() - timedelta(days=settings.SESSION_RETENTION_DAYS)
    async with SessionLocal() as db:
        result = await db.execute(
            delete(UserSession).where(
                UserSession.created_at < cutoff, UserSession.last_active_at < cutoff
            )
        )
        await db.commit()
        if result.rowcount:
            logger.info("Scheduler: purged %s stale sessions.", result.rowcount)


async def purge_expired_reset_tokens() -> None:
    """Clear password-reset tokens that have expired."""
    async with SessionLocal() as db:
        result = await db.execute(
            update(User)
            .where(User.reset_token.is_not(None), User.reset_token_expires < utcnow())
            .values(reset_token=None, reset_token_expires=None)
        )
        await db.commit()
        if result.rowcount:
            logger.info("Scheduler: cleared %s expired reset tokens.", result.rowcount)


async def purge_deleted_accounts() -> None:
    """Irreversibly remove accounts whose deletion grace period has elapsed."""
    from app.services import account_service

    async with SessionLocal() as db:
        count = await account_service.purge_due_accounts(db)
        await db.commit()
        if count:
            logger.info("Scheduler: purged %s deleted account(s).", count)


async def subscription_dunning() -> None:
    """Notify users whose subscription needs attention (past_due / unpaid)."""
    from app.services import email as email_service

    async with SessionLocal() as db:
        rows = await db.execute(
            select(Subscription).where(Subscription.status.in_(["past_due", "unpaid"]))
        )
        subs = list(rows.scalars().all())
        for sub in subs:
            user = await db.get(User, sub.user_id)
            if not user:
                continue
            await email_service.send_email(
                user.email,
                f"Action needed: your {settings.APP_NAME} subscription",
                f"Your subscription is {sub.status}. Update your payment method: "
                f"{settings.BASE_URL}/account/billing",
            )
        if subs:
            logger.info("Scheduler: dunning notices sent for %s subscriptions.", len(subs))


# ------------------------------------------------------------ lifecycle ----
def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register recurring jobs. Add your own here."""
    scheduler.add_job(
        purge_stale_sessions, CronTrigger(hour=3, minute=0), id="purge_stale_sessions",
        replace_existing=True,
    )
    scheduler.add_job(
        purge_expired_reset_tokens, CronTrigger(hour="*"), id="purge_expired_reset_tokens",
        replace_existing=True,
    )
    scheduler.add_job(
        subscription_dunning, CronTrigger(hour=9, minute=0), id="subscription_dunning",
        replace_existing=True,
    )
    scheduler.add_job(
        purge_deleted_accounts, CronTrigger(hour=4, minute=0), id="purge_deleted_accounts",
        replace_existing=True,
    )


def start_scheduler() -> AsyncIOScheduler | None:
    global _scheduler
    if not settings.SCHEDULER_ENABLED:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=0).")
        return None
    _scheduler = AsyncIOScheduler(timezone="UTC")
    register_jobs(_scheduler)
    _scheduler.start()
    logger.info("Scheduler started with %s job(s).", len(_scheduler.get_jobs()))
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
