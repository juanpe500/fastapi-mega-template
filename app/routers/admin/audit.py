"""Admin: audit-log viewer."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.audit import AuditLog
from app.models.user import User
from app.pagination import csv_response, paginate
from app.security.deps import get_current_user
from app.templating import render

router = APIRouter(prefix="/audit")


def _audit_stmt(action: str, q: str):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if q:
        stmt = stmt.where(AuditLog.detail.ilike(f"%{q.strip()}%"))
    return stmt


@router.get("/export.csv")
async def export_audit(
    action: str = "",
    q: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(_audit_stmt(action, q))).scalars().all()
    return csv_response(
        "audit.csv",
        ["created_at", "action", "actor_id", "target_type", "target_id", "ip_address", "detail"],
        [
            [e.created_at, e.action, e.actor_id, e.target_type, e.target_id,
             e.ip_address, e.detail]
            for e in rows
        ],
    )


@router.get("")
async def list_audit(
    request: Request,
    action: str = "",
    q: str = "",
    page: int = 1,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await paginate(db, _audit_stmt(action, q), page=page)
    entries = result.items

    # Resolve actor emails for display in one pass.
    actor_ids = {e.actor_id for e in entries if e.actor_id}
    actors: dict[str, str] = {}
    if actor_ids:
        rows = await db.execute(select(User).where(User.id.in_(actor_ids)))
        actors = {u.id: u.email for u in rows.scalars().all()}

    return render(request, "admin/audit.html",
                  {"entries": entries, "actors": actors, "action": action, "q": q,
                   "page_obj": result}, user=user)
