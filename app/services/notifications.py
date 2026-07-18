"""In-app notifications with optional email delivery and per-kind opt-out.

Transactional kinds (password resets, security alerts, billing failures) ignore
preferences and always send — you can't unsubscribe from those. Everything else
respects the user's choice and carries a one-click unsubscribe link, which
CAN-SPAM requires and mailbox providers effectively demand.
"""
from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.base import utcnow
from app.models.notification import Notification, NotificationPreference
from app.models.user import User
from app.services import email as email_service

_unsub_signer = URLSafeSerializer(settings.SECRET_KEY, salt="unsubscribe")

# kind -> (label, transactional?)
KINDS: dict[str, tuple[str, bool]] = {
    "security": ("Security alerts (new sign-ins, password changes)", True),
    "billing": ("Billing and payment notices", True),
    "ticket": ("Support ticket replies", False),
    "product": ("Product updates and announcements", False),
    "marketing": ("Tips, offers and marketing", False),
    "general": ("General notifications", False),
}


def is_transactional(kind: str) -> bool:
    return KINDS.get(kind, ("", False))[1]


def unsubscribe_token(user_id: str, kind: str) -> str:
    return _unsub_signer.dumps({"uid": user_id, "kind": kind})


def parse_unsubscribe_token(token: str) -> tuple[str, str] | None:
    try:
        data = _unsub_signer.loads(token)
    except BadSignature:
        return None
    return data.get("uid"), data.get("kind")


async def email_enabled(db: AsyncSession, user: User, kind: str) -> bool:
    if is_transactional(kind):
        return True
    pref = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.kind == kind,
            )
        )
    ).scalar_one_or_none()
    return True if pref is None else pref.email_enabled


async def set_preference(db: AsyncSession, user: User, kind: str, enabled: bool) -> None:
    pref = (
        await db.execute(
            select(NotificationPreference).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if pref is None:
        pref = NotificationPreference(user_id=user.id, kind=kind)
        db.add(pref)
    pref.email_enabled = enabled
    await db.flush()


async def notify(
    db: AsyncSession,
    user: User,
    kind: str,
    title: str,
    body: str = "",
    link: str | None = None,
    *,
    send_email: bool = True,
) -> Notification:
    """Create an in-app notification and (if allowed) email it."""
    note = Notification(user_id=user.id, kind=kind, title=title, body=body, link=link)
    db.add(note)
    await db.flush()

    if send_email and await email_enabled(db, user, kind):
        html = email_service.render_email(
            "notification.html",
            title=title,
            body=body,
            link=f"{settings.BASE_URL}{link}" if link and link.startswith("/") else link,
            unsubscribe_url=(
                None if is_transactional(kind)
                else f"{settings.BASE_URL}/unsubscribe?token={unsubscribe_token(user.id, kind)}"
            ),
        )
        await email_service.send_email(user.email, title, body or title, html=html)
    return note


async def unread_count(db: AsyncSession, user: User) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        )
    ).scalar_one()


async def mark_all_read(db: AsyncSession, user: User) -> None:
    rows = await db.execute(
        select(Notification).where(
            Notification.user_id == user.id, Notification.read_at.is_(None)
        )
    )
    now = utcnow()
    for n in rows.scalars().all():
        n.read_at = now
