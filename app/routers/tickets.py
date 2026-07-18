"""Support tickets (user side). Admin side lives in routers/admin/tickets.py."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.base import utcnow
from app.models.ticket import Ticket, TicketMessage
from app.models.user import User
from app.security.deps import get_current_user
from app.security.ratelimit import RateLimiter
from app.services.storage import get_storage, read_upload, safe_filename
from app.templating import render

router = APIRouter(prefix="/account/tickets", tags=["tickets"])
# Per-user: a shared office IP shouldn't lock out a whole company.
create_limiter = RateLimiter(times=5, seconds=300, scope="ticket_create", per_user=True)


async def _store_attachment(
    ticket_id: str, upload: UploadFile | None
) -> tuple[str | None, str | None]:
    """Save an optional attachment privately; returns (storage_key, content_type)."""
    if not upload or not upload.filename:
        return None, None
    data = await read_upload(upload)
    key = f"tickets/{ticket_id}/{uuid.uuid4().hex}-{safe_filename(upload.filename)}"
    await get_storage().save_private(key, data, upload.content_type)
    return key, upload.content_type


async def _get_ticket_with_messages(db: AsyncSession, ticket_id: str) -> Ticket | None:
    return (
        await db.execute(
            select(Ticket)
            .options(selectinload(Ticket.messages))
            .where(Ticket.id == ticket_id)
        )
    ).scalar_one_or_none()


@router.get("")
async def list_tickets(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tickets = (
        await db.execute(
            select(Ticket)
            .where(Ticket.user_id == user.id, Ticket.deleted_at.is_(None))
            .order_by(Ticket.last_reply_at.desc())
        )
    ).scalars().all()
    return render(request, "account/tickets.html", {"tickets": tickets}, user=user)


@router.post("", dependencies=[Depends(create_limiter)])
async def create_ticket(
    request: Request,
    subject: str = Form(...),
    category: str = Form("general"),
    body: str = Form(...),
    attachment: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Assign the id up front so the attachment key can reference it without a
    # flush (flushing first would leave `messages` unloaded -> async lazy-load).
    ticket = Ticket(id=str(uuid.uuid4()), user_id=user.id,
                    subject=subject.strip()[:200], category=category)
    key, ctype = await _store_attachment(ticket.id, attachment)
    ticket.messages.append(
        TicketMessage(sender_id=user.id, is_staff=False, body=body.strip(),
                      attachment_url=key, attachment_type=ctype)
    )
    db.add(ticket)
    await db.flush()
    return RedirectResponse(f"/account/tickets/{ticket.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{ticket_id}")
async def ticket_detail(
    request: Request,
    ticket_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket_with_messages(db, ticket_id)
    if not ticket or ticket.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return render(request, "account/ticket_detail.html", {"ticket": ticket}, user=user)


@router.post("/{ticket_id}/reply")
async def reply_ticket(
    request: Request,
    ticket_id: str,
    body: str = Form(...),
    attachment: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket_with_messages(db, ticket_id)
    if not ticket or ticket.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    key, ctype = await _store_attachment(ticket_id, attachment)
    ticket.messages.append(TicketMessage(sender_id=user.id, is_staff=False, body=body.strip(),
                                         attachment_url=key, attachment_type=ctype))
    ticket.status = "open"
    ticket.last_reply_at = utcnow()
    return RedirectResponse(f"/account/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id}/close")
async def close_ticket(
    ticket_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Let the reporter close their own ticket once it's resolved."""
    ticket = await db.get(Ticket, ticket_id)
    if not ticket or ticket.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ticket.status = "closed"
    return RedirectResponse(f"/account/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{ticket_id}/attachments/{message_id}")
async def get_attachment(
    ticket_id: str,
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket or ticket.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    msg = await db.get(TicketMessage, message_id)
    if not msg or msg.ticket_id != ticket_id or not msg.attachment_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    url = await get_storage().presigned_get(msg.attachment_url)
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
