"""Admin dashboard: high-level counts. Registered as the /admin index."""
from __future__ import annotations

from fastapi import Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.billing import Subscription
from app.models.errorlog import ErrorLog
from app.models.ticket import Ticket
from app.models.user import User
from app.security.deps import get_current_user
from app.templating import render


async def _count(db: AsyncSession, model, *where) -> int:
    stmt = select(func.count()).select_from(model)
    for w in where:
        stmt = stmt.where(w)
    return (await db.execute(stmt)).scalar_one()


async def dashboard_view(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stats = {
        "users": await _count(db, User),
        "active_subs": await _count(
            db, Subscription, Subscription.status.in_(["active", "trialing"])
        ),
        "open_tickets": await _count(db, Ticket, Ticket.status != "closed"),
        "unresolved_errors": await _count(db, ErrorLog, ErrorLog.resolved == False),  # noqa: E712
    }
    return render(request, "admin/dashboard.html", {"stats": stats}, user=user)
