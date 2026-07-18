"""Admin: server error log viewer."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.errorlog import ErrorLog
from app.models.user import User
from app.pagination import csv_response, paginate
from app.security.deps import get_current_user, require_permission
from app.templating import render

router = APIRouter(prefix="/errors")


def _error_stmt(show: str):
    stmt = select(ErrorLog).order_by(ErrorLog.created_at.desc())
    if show == "unresolved":
        stmt = stmt.where(ErrorLog.resolved.is_(False))
    return stmt


@router.get("/export.csv")
async def export_errors(
    show: str = "unresolved",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(_error_stmt(show))).scalars().all()
    return csv_response(
        "errors.csv",
        ["created_at", "path", "method", "status_code", "message", "resolved"],
        [[e.created_at, e.path, e.method, e.status_code, e.message, e.resolved] for e in rows],
    )


@router.get("")
async def list_errors(
    request: Request,
    show: str = "unresolved",
    page: int = 1,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await paginate(db, _error_stmt(show), page=page)
    return render(request, "admin/errors.html",
                  {"errors": result.items, "show": show, "page_obj": result}, user=user)


@router.post("/{error_id}/resolve", dependencies=[Depends(require_permission("errors.manage"))])
async def resolve(error_id: str, db: AsyncSession = Depends(get_db)):
    err = await db.get(ErrorLog, error_id)
    if not err:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    err.resolved = not err.resolved
    return RedirectResponse("/admin/errors", status_code=status.HTTP_303_SEE_OTHER)
