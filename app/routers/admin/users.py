"""Admin: user management (list, detail, toggle, credits, role assignment)."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.rbac import Role
from app.models.user import User
from app.pagination import csv_response, paginate, sort_stmt
from app.routers.auth import _establish_session
from app.security.deps import get_current_user, require_permission
from app.services import audit, credit_service
from app.templating import render

router = APIRouter(prefix="/users")


async def _get_user_with_roles(db: AsyncSession, user_id: str) -> User | None:
    return (
        await db.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user_id)
        )
    ).scalar_one_or_none()


SORTABLE = {"created_at", "email", "display_name", "last_login_at", "is_active"}


def _user_filter(stmt, q: str, status_filter: str):
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(User.email.ilike(like), User.display_name.ilike(like)))
    if status_filter == "active":
        stmt = stmt.where(User.is_active.is_(True))
    elif status_filter == "inactive":
        stmt = stmt.where(User.is_active.is_(False))
    elif status_filter == "unverified":
        stmt = stmt.where(User.email_verified.is_(False))
    elif status_filter == "deleting":
        stmt = stmt.where(User.deletion_requested_at.is_not(None))
    return stmt


@router.get("")
async def list_users(
    request: Request,
    q: str = "",
    status_filter: str = "",
    sort: str = "-created_at",
    page: int = 1,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Roles are read in the template, after the session closes -> eager-load them.
    base = select(User).options(selectinload(User.roles))
    stmt = sort_stmt(_user_filter(base, q, status_filter), User, sort, SORTABLE, "created_at")
    result = await paginate(db, stmt, page=page)
    return render(request, "admin/users.html",
                  {"page_obj": result, "users": result.items, "q": q, "sort": sort,
                   "status_filter": status_filter}, user=user)


@router.get("/export.csv", dependencies=[Depends(require_permission("users.manage"))])
async def export_users(
    q: str = "",
    status_filter: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = _user_filter(select(User).order_by(User.created_at.desc()), q, status_filter)
    rows = (await db.execute(stmt)).scalars().all()
    return csv_response(
        "users.csv",
        ["id", "email", "display_name", "is_active", "email_verified", "created_at",
         "last_login_at"],
        [
            [u.id, u.email, u.display_name, u.is_active, u.email_verified,
             u.created_at, u.last_login_at]
            for u in rows
        ],
    )


@router.post("/bulk", dependencies=[Depends(require_permission("users.manage"))])
async def bulk_users(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply one action to every checked row. Self is always skipped."""
    form = await request.form()
    action = form.get("action", "")
    ids = [i for i in form.getlist("ids") if i != user.id]
    if not ids or action not in {"activate", "deactivate", "verify"}:
        return RedirectResponse("/admin/users", status_code=status.HTTP_303_SEE_OTHER)

    targets = (await db.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    for t in targets:
        if action == "activate":
            t.is_active = True
        elif action == "deactivate":
            t.is_active = False
        elif action == "verify":
            t.email_verified = True
    await audit.record(db, "admin.users_bulk", actor=user, request=request,
                       detail=f"{action} x{len(targets)}")
    return RedirectResponse("/admin/users?bulk=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{user_id}")
async def user_detail(
    request: Request,
    user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await _get_user_with_roles(db, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    all_roles = (await db.execute(select(Role).order_by(Role.name))).scalars().all()
    return render(request, "admin/user_detail.html",
                  {"target": target, "all_roles": all_roles,
                   "history": await credit_service.history(db, target, 50)}, user=user)


@router.post("/{user_id}/toggle", dependencies=[Depends(require_permission("users.manage"))])
async def toggle_active(
    request: Request,
    user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    target.is_active = not target.is_active
    await audit.record(db, audit.ADMIN_USER_TOGGLE, actor=user, target=target, request=request,
                       detail=f"is_active={target.is_active}")
    return RedirectResponse(f"/admin/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{user_id}/credits", dependencies=[Depends(require_permission("billing.manage"))])
async def adjust_credits(
    request: Request,
    user_id: str,
    amount: str = Form(...),
    note: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    delta = Decimal(amount)
    if delta >= 0:
        await credit_service.add_credits(db, target, delta, kind="adjustment",
                                         description=note or "Admin grant")
    else:
        await credit_service.deduct_credits(db, target, -delta, description=note or "Admin debit",
                                            allow_negative=True)
    await audit.record(db, audit.ADMIN_CREDIT_ADJUST, actor=user, target=target, request=request,
                       detail=f"{delta:+} ({note})")
    return RedirectResponse(f"/admin/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{user_id}/impersonate",
             dependencies=[Depends(require_permission("users.impersonate"))])
async def impersonate(
    request: Request,
    user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a support session as another user.

    Issues a fresh session for the target that remembers who started it, so
    /impersonate/stop can hand control back to the admin.
    """
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if target.id == user.id:
        return RedirectResponse(f"/admin/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)

    resp = RedirectResponse("/account", status_code=status.HTTP_303_SEE_OTHER)
    await _establish_session(resp, request, db, target, impersonator_id=user.id)
    await audit.record(db, audit.ADMIN_IMPERSONATE_START, actor=user, target=target,
                       request=request)
    return resp


@router.post("/{user_id}/roles", dependencies=[Depends(require_permission("users.manage"))])
async def set_roles(
    request: Request,
    user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await _get_user_with_roles(db, user_id)
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    form = await request.form()
    selected = set(form.getlist("roles"))
    roles = (
        (await db.execute(select(Role).where(Role.id.in_(selected)))).scalars().all()
        if selected else []
    )
    before = sorted(target.role_names)
    target.roles = list(roles)
    await audit.record(db, audit.ADMIN_ROLE_CHANGE, actor=user, target=target, request=request,
                       detail=f"{before} -> {sorted(r.name for r in roles)}")
    return RedirectResponse(f"/admin/users/{user_id}", status_code=status.HTTP_303_SEE_OTHER)
