"""Admin: role & permission management."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.rbac import Permission, Role
from app.models.user import User
from app.security.deps import get_current_user, require_permission
from app.templating import render

router = APIRouter(prefix="/roles")


@router.get("")
async def list_roles(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    roles = (await db.execute(select(Role).order_by(Role.name))).scalars().all()
    permissions = (await db.execute(select(Permission).order_by(Permission.name))).scalars().all()
    return render(request, "admin/roles.html",
                  {"roles": roles, "permissions": permissions}, user=user)


@router.post("", dependencies=[Depends(require_permission("roles.manage"))])
async def create_role(
    name: str = Form(...),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
):
    name = name.strip().lower()
    exists = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
    if not exists:
        db.add(Role(name=name, description=description))
    return RedirectResponse("/admin/roles", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{role_id}/permissions", dependencies=[Depends(require_permission("roles.manage"))])
async def set_permissions(
    request: Request,
    role_id: str,
    db: AsyncSession = Depends(get_db),
):
    role = (
        await db.execute(
            select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
        )
    ).scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    form = await request.form()
    selected = set(form.getlist("permissions"))
    perms = (
        await db.execute(select(Permission).where(Permission.id.in_(selected)))
    ).scalars().all() if selected else []
    role.permissions = list(perms)
    return RedirectResponse("/admin/roles", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{role_id}/delete", dependencies=[Depends(require_permission("roles.manage"))])
async def delete_role(role_id: str, db: AsyncSession = Depends(get_db)):
    role = await db.get(Role, role_id)
    if role and not role.is_system:
        await db.delete(role)
    return RedirectResponse("/admin/roles", status_code=status.HTTP_303_SEE_OTHER)
