"""Notification centre: in-app list, unread badge, email preferences, unsubscribe."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.base import utcnow
from app.models.notification import Notification, NotificationPreference
from app.models.user import User
from app.pagination import paginate
from app.security.deps import get_current_user, get_current_user_optional
from app.services import notifications as notif
from app.templating import render

router = APIRouter(tags=["notifications"])


@router.get("/api/notifications/unread-count")
async def unread_count(
    user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Powers the nav badge; returns 0 for anonymous visitors rather than 401."""
    if user is None:
        return {"count": 0}
    return {"count": await notif.unread_count(db, user)}


@router.get("/account/notifications")
async def list_notifications(
    request: Request,
    page: int = 1,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
    )
    result = await paginate(db, stmt, page=page, per_page=25)
    prefs = {
        p.kind: p.email_enabled
        for p in (
            await db.execute(
                select(NotificationPreference).where(NotificationPreference.user_id == user.id)
            )
        ).scalars().all()
    }
    return render(request, "account/notifications.html",
                  {"page_obj": result, "kinds": notif.KINDS, "prefs": prefs}, user=user)


@router.post("/account/notifications/read-all")
async def read_all(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await notif.mark_all_read(db, user)
    return RedirectResponse("/account/notifications", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/account/notifications/{note_id}/read")
async def read_one(
    note_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    note = await db.get(Notification, note_id)
    if not note or note.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    note.read_at = utcnow()
    return RedirectResponse(note.link or "/account/notifications",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/account/notifications/preferences")
async def save_preferences(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Checkbox present = opted in. Transactional kinds are not user-configurable."""
    form = await request.form()
    for kind, (_label, transactional) in notif.KINDS.items():
        if transactional:
            continue
        await notif.set_preference(db, user, kind, form.get(f"email_{kind}") is not None)
    return RedirectResponse("/account/notifications?saved=1",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.get("/unsubscribe")
async def unsubscribe(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    """One-click unsubscribe from an email footer — no login required (CAN-SPAM)."""
    parsed = notif.parse_unsubscribe_token(token) if token else None
    if not parsed:
        return render(request, "unsubscribed.html", {"ok": False}, status_code=400)
    user_id, kind = parsed
    user = await db.get(User, user_id)
    if not user:
        return render(request, "unsubscribed.html", {"ok": False}, status_code=400)
    await notif.set_preference(db, user, kind, False)
    label = notif.KINDS.get(kind, (kind, False))[0]
    return render(request, "unsubscribed.html", {"ok": True, "label": label})
