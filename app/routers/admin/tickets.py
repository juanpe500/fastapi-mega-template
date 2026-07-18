"""Admin: support ticket queue + staff replies."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.base import utcnow
from app.models.ticket import Ticket, TicketMessage
from app.models.user import User
from app.pagination import csv_response, paginate
from app.security.deps import get_current_user, require_permission
from app.services import audit
from app.services import email as email_service
from app.templating import render

router = APIRouter(prefix="/tickets")


async def _get_ticket(db: AsyncSession, ticket_id: str) -> Ticket | None:
    return (
        await db.execute(
            select(Ticket).options(selectinload(Ticket.messages)).where(Ticket.id == ticket_id)
        )
    ).scalar_one_or_none()


def _queue_stmt(status_filter: str, q: str):
    # Trashed tickets live in /admin/tickets/trash, not the main queue.
    stmt = (
        select(Ticket)
        .where(Ticket.deleted_at.is_(None))
        .order_by(Ticket.last_reply_at.desc())
    )
    if status_filter and status_filter != "all":
        stmt = stmt.where(Ticket.status == status_filter)
    if q:
        stmt = stmt.where(Ticket.subject.ilike(f"%{q.strip()}%"))
    return stmt


@router.get("")
async def queue(
    request: Request,
    status_filter: str = "open",
    q: str = "",
    page: int = 1,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await paginate(db, _queue_stmt(status_filter, q), page=page)
    return render(request, "admin/tickets.html",
                  {"tickets": result.items, "status_filter": status_filter, "q": q,
                   "page_obj": result}, user=user)


@router.get("/export.csv")
async def export_tickets(
    status_filter: str = "all",
    q: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(_queue_stmt(status_filter, q))).scalars().all()
    return csv_response(
        "tickets.csv",
        ["id", "subject", "status", "category", "user_id", "created_at", "last_reply_at"],
        [
            [t.id, t.subject, t.status, t.category, t.user_id, t.created_at, t.last_reply_at]
            for t in rows
        ],
    )


@router.get("/trash", dependencies=[Depends(require_permission("tickets.manage"))])
async def trash(
    request: Request,
    page: int = 1,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-deleted tickets, restorable until purged."""
    stmt = (
        select(Ticket)
        .where(Ticket.deleted_at.is_not(None))
        .order_by(Ticket.deleted_at.desc())
    )
    result = await paginate(db, stmt, page=page)
    return render(request, "admin/trash.html",
                  {"tickets": result.items, "page_obj": result}, user=user)


@router.post("/bulk", dependencies=[Depends(require_permission("tickets.manage"))])
async def bulk_tickets(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    action = form.get("action", "")
    ids = form.getlist("ids")
    if not ids:
        return RedirectResponse("/admin/tickets", status_code=status.HTTP_303_SEE_OTHER)

    rows = (await db.execute(select(Ticket).where(Ticket.id.in_(ids)))).scalars().all()
    for t in rows:
        if action in ("open", "pending", "closed"):
            t.status = action
        elif action == "delete":
            t.deleted_at = utcnow()
        elif action == "restore":
            t.deleted_at = None
    await audit.record(db, "admin.tickets_bulk", actor=user, request=request,
                       detail=f"{action} x{len(rows)}")
    back = "/admin/tickets/trash" if action == "restore" else "/admin/tickets"
    return RedirectResponse(f"{back}?bulk=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id}/delete", dependencies=[Depends(require_permission("tickets.manage"))])
async def soft_delete(
    request: Request,
    ticket_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ticket.deleted_at = utcnow()
    await audit.record(db, "admin.ticket_deleted", actor=user, request=request,
                       target_type="Ticket", target_id=ticket_id)
    return RedirectResponse("/admin/tickets", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id}/restore", dependencies=[Depends(require_permission("tickets.manage"))])
async def restore(
    request: Request,
    ticket_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ticket.deleted_at = None
    await audit.record(db, "admin.ticket_restored", actor=user, request=request,
                       target_type="Ticket", target_id=ticket_id)
    return RedirectResponse("/admin/tickets/trash", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{ticket_id}")
async def detail(
    request: Request,
    ticket_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    owner = await db.get(User, ticket.user_id)
    return render(request, "admin/ticket_detail.html",
                  {"ticket": ticket, "owner": owner}, user=user)


@router.post("/{ticket_id}/reply", dependencies=[Depends(require_permission("tickets.manage"))])
async def reply(
    ticket_id: str,
    body: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ticket = await _get_ticket(db, ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    ticket.messages.append(TicketMessage(sender_id=user.id, is_staff=True, body=body.strip()))
    ticket.status = "pending"
    ticket.last_reply_at = utcnow()
    await db.flush()
    owner = await db.get(User, ticket.user_id)
    if owner:
        await email_service.send_ticket_notification(owner.email, ticket.id, ticket.subject)
    return RedirectResponse(f"/admin/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{ticket_id}/attachments/{message_id}")
async def get_attachment(
    ticket_id: str,
    message_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msg = await db.get(TicketMessage, message_id)
    if not msg or msg.ticket_id != ticket_id or not msg.attachment_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    from app.services.storage import get_storage

    url = await get_storage().presigned_get(msg.attachment_url)
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{ticket_id}/status", dependencies=[Depends(require_permission("tickets.manage"))])
async def set_status(
    ticket_id: str,
    new_status: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if new_status in ("open", "pending", "closed"):
        ticket.status = new_status
    return RedirectResponse(f"/admin/tickets/{ticket_id}", status_code=status.HTTP_303_SEE_OTHER)
