"""Admin: DB-backed settings / feature flags."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import User
from app.ops import reset_maintenance_cache
from app.security.deps import get_current_user, require_permission
from app.services import audit, settings_service
from app.templating import render

router = APIRouter(prefix="/settings")


@router.get("")
async def list_settings(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return render(request, "admin/settings.html",
                  {"settings_rows": await settings_service.all_settings(db),
                   "maintenance": bool(await settings_service.get(db, "maintenance_mode", False))},
                  user=user)


@router.post("/maintenance", dependencies=[Depends(require_permission("settings.manage"))])
async def toggle_maintenance(
    request: Request,
    enabled: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Close the site to everyone but admins. Takes effect within ~10s."""
    on = enabled == "1"
    await settings_service.set(db, "maintenance_mode", "1" if on else "0", value_type="bool",
                               description="Show the maintenance page to non-admins.")
    reset_maintenance_cache()
    await audit.record(db, audit.ADMIN_SETTING_CHANGE, actor=user, request=request,
                       target_type="AppSetting", target_id="maintenance_mode",
                       detail=f"maintenance_mode={on}")
    return RedirectResponse("/admin/settings?maintenance=1",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("", dependencies=[Depends(require_permission("settings.manage"))])
async def upsert_setting(
    request: Request,
    key: str = Form(...),
    value: str = Form(""),
    value_type: str = Form("str"),
    description: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    key = key.strip()
    await settings_service.set(db, key, value, value_type=value_type, description=description)
    await audit.record(db, audit.ADMIN_SETTING_CHANGE, actor=user, request=request,
                       target_type="AppSetting", target_id=key, detail=f"{key}={value}")
    return RedirectResponse("/admin/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{key}/delete", dependencies=[Depends(require_permission("settings.manage"))])
async def delete_setting(
    request: Request,
    key: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await settings_service.delete(db, key)
    await audit.record(db, audit.ADMIN_SETTING_CHANGE, actor=user, request=request,
                       target_type="AppSetting", target_id=key, detail="deleted")
    return RedirectResponse("/admin/settings", status_code=status.HTTP_303_SEE_OTHER)
