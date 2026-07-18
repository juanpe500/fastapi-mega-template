"""Auth dependencies: resolve the current user and gate routes by role/permission.

Token sources accepted, in order:
  1. httpOnly cookie  (browser / server-rendered pages)
  2. Authorization: Bearer <jwt>   (API clients / SPAs)
  3. X-API-Key: <key>              (programmatic access)
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models.base import aware, utcnow
from app.models.rbac import Role
from app.models.user import User, UserSession
from app.security.passwords import hash_api_key
from app.security.tokens import decode_token


def _user_query():
    # Eager-load roles (+their permissions) so templates can read them after the
    # request session closes, without triggering a detached lazy-load.
    return select(User).options(selectinload(User.roles).selectinload(Role.permissions))


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        return token
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


async def _user_from_token(
    token: str, db: AsyncSession, request: Request | None = None
) -> User | None:
    payload = decode_token(token, expected_type="access")
    if not payload:
        return None
    user_id, sid = payload.get("sub"), payload.get("sid")
    if not user_id or not sid:
        return None
    session = await db.get(UserSession, sid)
    if not session or not session.is_active or session.user_id != user_id:
        return None
    # Surface impersonation to templates (banner) without another query.
    if request is not None:
        request.state.impersonator_id = session.impersonator_id
    user = (
        await db.execute(_user_query().where(User.id == user_id))
    ).scalar_one_or_none()
    if not user or not user.is_active:
        return None
    # Throttled last-active bookkeeping (at most once / 5 min).
    now = utcnow()
    last = aware(session.last_active_at)
    if not last or (now - last) > timedelta(minutes=5):
        session.last_active_at = now
    return user


async def _user_from_api_key(api_key: str, db: AsyncSession) -> User | None:
    key_hash = hash_api_key(api_key)
    user = (
        await db.execute(_user_query().where(User.api_key_hash == key_hash))
    ).scalar_one_or_none()
    if user and user.is_active:
        return user
    return None


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_api_key: str | None = Header(default=None),
) -> User | None:
    """Return the authenticated User or None (never raises). Good for pages."""
    if x_api_key:
        user = await _user_from_api_key(x_api_key, db)
        if user:
            return user
    token = _extract_token(request)
    if token:
        return await _user_from_token(token, db, request)
    return None


async def get_current_user(
    user: User | None = Depends(get_current_user_optional),
) -> User:
    """Require an authenticated user (401 otherwise)."""
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


class require_role:  # noqa: N801 — used as a dependency factory
    """Dependency: user must hold one of the given roles.

        @router.get("/admin", dependencies=[Depends(require_role("admin"))])
    """

    def __init__(self, *roles: str):
        self.roles = set(roles)

    async def __call__(self, user: User = Depends(get_current_user)) -> User:
        if user.has_permission("*") or (self.roles & user.role_names):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")


class require_permission:  # noqa: N801
    """Dependency: user must hold the given permission (or the '*' wildcard).

        @router.post("/billing/refund",
                     dependencies=[Depends(require_permission("billing.manage"))])
    """

    def __init__(self, permission: str):
        self.permission = permission

    async def __call__(self, user: User = Depends(get_current_user)) -> User:
        if user.has_permission(self.permission):
            return user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied")


def current_session_id(request: Request) -> str | None:
    """The UserSession id backing the current request's token, if any."""
    token = _extract_token(request)
    if not token:
        return None
    payload = decode_token(token, expected_type="access")
    return payload.get("sid") if payload else None


def is_admin(user: User) -> bool:
    return user.has_role("admin") or user.email.lower() in settings.admin_email_set
