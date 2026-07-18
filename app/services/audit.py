"""Audit logging for security- and admin-relevant actions.

Usage:
    from app.services import audit
    await audit.record(db, "user.login", actor=user, request=request)
    await audit.record(db, "admin.role_change", actor=admin, target=target_user,
                       detail="added: support")
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.security.ratelimit import client_ip

# Well-known action names (free-form strings are fine too).
LOGIN = "user.login"
LOGIN_FAILED = "user.login_failed"
LOGOUT = "user.logout"
REGISTER = "user.register"
PASSWORD_CHANGED = "user.password_changed"
PASSWORD_RESET = "user.password_reset"
TWOFA_ENABLED = "user.2fa_enabled"
TWOFA_DISABLED = "user.2fa_disabled"
API_KEY_CREATED = "user.api_key_created"
SESSION_REVOKED = "user.session_revoked"
OAUTH_LINKED = "user.oauth_linked"

ADMIN_ROLE_CHANGE = "admin.role_change"
ADMIN_CREDIT_ADJUST = "admin.credit_adjust"
ADMIN_USER_TOGGLE = "admin.user_toggle"
ADMIN_IMPERSONATE_START = "admin.impersonate_start"
ADMIN_IMPERSONATE_STOP = "admin.impersonate_stop"
ADMIN_SETTING_CHANGE = "admin.setting_change"


async def record(
    db: AsyncSession,
    action: str,
    *,
    actor=None,
    actor_id: str | None = None,
    target=None,
    target_type: str | None = None,
    target_id: str | None = None,
    request=None,
    detail: str = "",
) -> AuditLog:
    if target is not None:
        target_type = target_type or type(target).__name__
        target_id = target_id or getattr(target, "id", None)
    entry = AuditLog(
        actor_id=actor_id or (getattr(actor, "id", None) if actor is not None else None),
        action=action,
        target_type=target_type,
        target_id=target_id,
        ip_address=client_ip(request) if request is not None else None,
        detail=detail[:4000],
    )
    db.add(entry)
    await db.flush()
    return entry
