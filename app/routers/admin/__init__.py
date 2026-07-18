"""Admin panel — all routes gated by the `admin` role (or the '*' permission).

Individual actions additionally declare a fine-grained permission so you can
create non-admin staff roles (e.g. a 'support' role with only tickets.manage).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.security.deps import require_role

from . import audit, billing, errors, roles, settings, tickets, users
from .dashboard import dashboard_view

router = APIRouter(prefix="/admin", dependencies=[Depends(require_role("admin"))])
# Dashboard is the /admin index (empty path is only valid with the prefix).
router.add_api_route("", dashboard_view, methods=["GET"], name="admin_dashboard")
router.include_router(audit.router)
router.include_router(settings.router)
router.include_router(users.router)
router.include_router(roles.router)
router.include_router(billing.router)
router.include_router(tickets.router)
router.include_router(errors.router)
