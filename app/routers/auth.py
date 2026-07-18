"""Authentication: register, login (+2FA), logout, email verification, password
reset, and JWT refresh. Pages are server-rendered; forms post to these routes.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.base import aware, utcnow
from app.models.rbac import Role
from app.models.user import User, UserSession
from app.security import turnstile
from app.security.breach_check import breach_count
from app.security.deps import get_current_user, get_current_user_optional
from app.security.passwords import hash_password, verify_password
from app.security.ratelimit import RateLimiter, client_ip
from app.security.tokens import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_url_token,
    hash_url_token,
    verify_totp,
)
from app.services import audit, notifications, referrals, twofactor
from app.services import email as email_service
from app.templating import render

router = APIRouter(tags=["auth"])

REFRESH_COOKIE = "refresh"
login_limiter = RateLimiter(times=10, seconds=60, scope="login")
register_limiter = RateLimiter(times=5, seconds=60, scope="register")
reset_limiter = RateLimiter(times=5, seconds=300, scope="reset")


# --------------------------------------------------------------- cookie utils
def _set_cookie(resp: Response, name: str, value: str, max_age: int) -> None:
    resp.set_cookie(
        key=name,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        domain=settings.COOKIE_DOMAIN or None,
        path="/",
    )


async def _establish_session(
    resp: Response,
    request: Request,
    db: AsyncSession,
    user: User,
    *,
    impersonator_id: str | None = None,
) -> None:
    session = UserSession(
        user_id=user.id,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:400],
        last_active_at=utcnow(),
        impersonator_id=impersonator_id,
    )
    db.add(session)
    await db.flush()
    user.last_login_at = utcnow()
    access = create_access_token(user.id, session.id)
    refresh = create_refresh_token(user.id, session.id)
    _set_cookie(
        resp, settings.SESSION_COOKIE_NAME, access,
        settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
    _set_cookie(resp, REFRESH_COOKIE, refresh, settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400)


def _clear_cookies(resp: Response) -> None:
    for name in (settings.SESSION_COOKIE_NAME, REFRESH_COOKIE):
        resp.delete_cookie(name, domain=settings.COOKIE_DOMAIN or None, path="/")


def _safe_next(raw: str | None) -> str:
    # Only allow same-site relative redirects.
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/account"


# ------------------------------------------------------------------ register
@router.get("/register")
async def register_page(request: Request, user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/account", status_code=302)
    return render(
        request,
        "auth/register.html",
        {"registration_enabled": settings.REGISTRATION_ENABLED},
    )


@router.post("/register", dependencies=[Depends(register_limiter)])
async def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(""),
    turnstile_token: str = Form("", alias="cf-turnstile-response"),
    db: AsyncSession = Depends(get_db),
):
    if not settings.REGISTRATION_ENABLED:
        return render(request, "auth/register.html", {"error": "Registration is disabled.",
                      "registration_enabled": False}, status_code=403)

    if not await turnstile.verify(turnstile_token, client_ip(request)):
        return render(request, "auth/register.html",
                      {"error": "Bot check failed. Please try again.",
                       "registration_enabled": True}, status_code=400)

    email = email.strip().lower()
    if len(password) < 8:
        return render(request, "auth/register.html",
                      {"error": "Password must be at least 8 characters.",
                       "registration_enabled": True, "email": email}, status_code=400)

    breaches = await breach_count(password)
    if breaches:
        return render(request, "auth/register.html",
                      {"error": f"That password has appeared in {breaches:,} known data "
                                f"breaches. Please choose a different one.",
                       "registration_enabled": True, "email": email}, status_code=400)

    exists = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if exists:
        return render(request, "auth/register.html",
                      {"error": "An account with that email already exists.",
                       "registration_enabled": True}, status_code=400)

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip(),
        email_verified=not settings.REQUIRE_EMAIL_VERIFICATION,
        # Record which terms version was agreed to at signup.
        terms_version_accepted=settings.TERMS_VERSION,
        referral_code=referrals.new_code(),
    )

    # Role assignment: first-ever user (or ADMIN_EMAILS) -> admin, else user.
    total = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    is_first_admin = (settings.FIRST_USER_IS_ADMIN and total == 0) or (
        email in settings.admin_email_set
    )
    role_name = "admin" if is_first_admin else "user"
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one_or_none()
    if role:
        user.roles.append(role)

    db.add(user)
    await db.flush()

    # Welcome credits
    if settings.WELCOME_CREDITS and settings.WELCOME_CREDITS > 0:
        from app.services import credit_service

        await credit_service.add_credits(
            db, user, settings.WELCOME_CREDITS, kind="welcome", description="Welcome bonus"
        )

    # Attribute the signup to a referrer, if they arrived via a referral link.
    await referrals.attribute_signup(db, user, request.cookies.get(referrals.COOKIE_NAME))

    if settings.REQUIRE_EMAIL_VERIFICATION:
        raw, hashed = generate_url_token()
        user.verification_code = hashed
        await db.flush()
        await email_service.send_verification_email(user.email, raw)
        return render(request, "auth/verify_sent.html", {"email": user.email})

    resp = RedirectResponse("/account", status_code=status.HTTP_303_SEE_OTHER)
    await _establish_session(resp, request, db, user)
    await audit.record(db, audit.REGISTER, actor=user, request=request)
    return resp


# --------------------------------------------------------------------- login
@router.get("/login")
async def login_page(request: Request, next: str = "", user=Depends(get_current_user_optional)):
    if user:
        return RedirectResponse("/account", status_code=302)
    return render(request, "auth/login.html", {"next": next})


@router.post("/login", dependencies=[Depends(login_limiter)])
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    totp_code: str = Form(""),
    next: str = Form(""),
    turnstile_token: str = Form("", alias="cf-turnstile-response"),
    db: AsyncSession = Depends(get_db),
):
    # Only challenge the first step; the 2FA follow-up post reuses the session.
    if not totp_code and not await turnstile.verify(turnstile_token, client_ip(request)):
        return render(request, "auth/login.html",
                      {"error": "Bot check failed. Please try again.", "next": next},
                      status_code=400)

    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        await audit.record(db, audit.LOGIN_FAILED, actor=user, request=request,
                           detail=f"email={email}")
        return render(request, "auth/login.html",
                      {"error": "Invalid email or password.", "email": email, "next": next},
                      status_code=401)
    if not user.is_active:
        # A self-deactivated (or pending-deletion) account comes back on sign-in;
        # an admin-disabled account does not.
        if user.deactivated_at or user.deletion_requested_at:
            user.is_active = True
            user.deactivated_at = None
        else:
            return render(request, "auth/login.html",
                          {"error": "This account is disabled.", "next": next}, status_code=403)
    if settings.REQUIRE_EMAIL_VERIFICATION and not user.email_verified:
        return render(request, "auth/login.html",
                      {"error": "Please verify your email first.", "next": next}, status_code=403)

    if user.totp_enabled:
        if not totp_code:
            return render(request, "auth/login.html",
                          {"needs_totp": True, "email": email, "password": password, "next": next})
        # Accept either a valid TOTP code or a one-time recovery code.
        ok = verify_totp(user.totp_secret or "", totp_code)
        if not ok:
            ok = await twofactor.consume_recovery_code(db, user, totp_code)
        if not ok:
            return render(request, "auth/login.html",
                          {"needs_totp": True, "email": email, "password": password,
                           "next": next, "error": "Invalid 2FA or recovery code."}, status_code=401)

    # Alert on sign-ins from a device/IP we haven't seen before.
    await _maybe_login_alert(db, request, user)

    target = _safe_next(next)
    # Force re-acceptance when the terms have been revised.
    if user.terms_version_accepted != settings.TERMS_VERSION:
        target = f"/terms/accept?next={target}"

    resp = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    await _establish_session(resp, request, db, user)
    await audit.record(db, audit.LOGIN, actor=user, request=request)
    return resp


async def _maybe_login_alert(db: AsyncSession, request: Request, user: User) -> None:
    """Notify the user when a sign-in comes from an unrecognised device."""
    if not settings.LOGIN_ALERTS_ENABLED:
        return
    ip = client_ip(request)
    agent = request.headers.get("user-agent", "")[:400]
    seen = (
        await db.execute(
            select(UserSession).where(
                UserSession.user_id == user.id,
                UserSession.ip_address == ip,
                UserSession.user_agent == agent,
            )
        )
    ).scalars().first()
    if seen:
        return
    await notifications.notify(
        db, user, "security", "New sign-in to your account",
        f"A new sign-in was detected from {ip} ({agent[:80] or 'unknown device'}). "
        f"If this wasn't you, change your password and revoke the session.",
        link="/account/sessions",
    )


# ------------------------------------------------------------ terms of service
@router.get("/terms/accept")
async def terms_accept_page(request: Request, next: str = "/account",
                            user=Depends(get_current_user_optional)):
    if user is None:
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "auth/terms_accept.html", {"next": next}, user=user)


@router.post("/terms/accept")
async def terms_accept(
    request: Request,
    next: str = Form("/account"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.terms_version_accepted = settings.TERMS_VERSION
    await audit.record(db, "user.terms_accepted", actor=user, request=request,
                       detail=f"version {settings.TERMS_VERSION}")
    return RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)


# -------------------------------------------------------------------- logout
@router.post("/logout")
@router.get("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if token:
        payload = decode_token(token, expected_type="access")
        if payload and payload.get("sid"):
            session = await db.get(UserSession, payload["sid"])
            if session:
                session.is_active = False
                await audit.record(db, audit.LOGOUT, actor_id=session.user_id, request=request)
    resp = RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
    _clear_cookies(resp)
    return resp


# ------------------------------------------------------- stop impersonation
@router.post("/impersonate/stop")
async def stop_impersonation(request: Request, db: AsyncSession = Depends(get_db)):
    """End an impersonation session and restore the admin's own session."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    payload = decode_token(token, expected_type="access") if token else None
    session = await db.get(UserSession, payload["sid"]) if payload and payload.get("sid") else None
    if not session or not session.impersonator_id:
        return RedirectResponse("/account", status_code=status.HTTP_303_SEE_OTHER)

    admin = await db.get(User, session.impersonator_id)
    impersonated_id = session.user_id
    session.is_active = False
    if not admin or not admin.is_active:
        resp = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
        _clear_cookies(resp)
        return resp

    resp = RedirectResponse(
        f"/admin/users/{impersonated_id}", status_code=status.HTTP_303_SEE_OTHER
    )
    await _establish_session(resp, request, db, admin)
    await audit.record(db, audit.ADMIN_IMPERSONATE_STOP, actor=admin, request=request,
                       target_type="User", target_id=impersonated_id)
    return resp


# ------------------------------------------------------------------- refresh
@router.post("/auth/refresh")
async def refresh(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    payload = decode_token(token, expected_type="refresh") if token else None
    if not payload:
        return Response("Invalid refresh token", status_code=401)
    session = await db.get(UserSession, payload.get("sid"))
    if not session or not session.is_active or session.user_id != payload.get("sub"):
        return Response("Session revoked", status_code=401)
    access = create_access_token(session.user_id, session.id)
    resp = Response(status_code=204)
    _set_cookie(resp, settings.SESSION_COOKIE_NAME, access,
                settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    return resp


# -------------------------------------------------------- email verification
@router.get("/verify")
async def verify_email(request: Request, token: str = "", db: AsyncSession = Depends(get_db)):
    hashed = hash_url_token(token) if token else ""
    user = (
        await db.execute(select(User).where(User.verification_code == hashed))
    ).scalar_one_or_none() if hashed else None
    if not user:
        return render(request, "auth/verify_result.html", {"ok": False}, status_code=400)
    user.email_verified = True
    user.verification_code = None
    return render(request, "auth/verify_result.html", {"ok": True})


@router.get("/verify/resend")
async def resend_verification_page(request: Request):
    return render(request, "auth/resend_verification.html", {})


@router.post("/verify/resend", dependencies=[Depends(reset_limiter)])
async def resend_verification(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """Re-send the verification email. Without this, a user who never received
    the first one has no way forward when REQUIRE_EMAIL_VERIFICATION is on."""
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user and not user.email_verified:
        raw, hashed = generate_url_token()
        user.verification_code = hashed
        await db.flush()
        await email_service.send_verification_email(user.email, raw)
    # Always report success so the form can't be used to probe for accounts.
    return render(request, "auth/resend_verification.html", {"sent": True})


# ----------------------------------------------------------- password reset
@router.get("/forgot")
async def forgot_page(request: Request):
    return render(request, "auth/forgot.html", {})


@router.post("/forgot", dependencies=[Depends(reset_limiter)])
async def forgot(
    request: Request,
    email: str = Form(...),
    turnstile_token: str = Form("", alias="cf-turnstile-response"),
    db: AsyncSession = Depends(get_db),
):
    if not await turnstile.verify(turnstile_token, client_ip(request)):
        return render(request, "auth/forgot.html",
                      {"error": "Bot check failed. Please try again."}, status_code=400)
    email = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user:
        raw, hashed = generate_url_token()
        user.reset_token = hashed
        user.reset_token_expires = utcnow() + timedelta(hours=1)
        await db.flush()
        await email_service.send_password_reset_email(user.email, raw)
    # Always show success (don't leak which emails exist).
    return render(request, "auth/forgot.html", {"sent": True})


@router.get("/reset")
async def reset_page(request: Request, token: str = ""):
    return render(request, "auth/reset.html", {"token": token})


@router.post("/reset", dependencies=[Depends(reset_limiter)])
async def reset(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    if len(password) < 8:
        return render(request, "auth/reset.html",
                      {"token": token, "error": "Password must be at least 8 characters."},
                      status_code=400)
    breaches = await breach_count(password)
    if breaches:
        return render(request, "auth/reset.html",
                      {"token": token,
                       "error": f"That password has appeared in {breaches:,} known data "
                                f"breaches. Please choose a different one."},
                      status_code=400)
    hashed = hash_url_token(token)
    user = (
        await db.execute(select(User).where(User.reset_token == hashed))
    ).scalar_one_or_none()
    if not user or not user.reset_token_expires or aware(user.reset_token_expires) < utcnow():
        return render(request, "auth/reset.html",
                      {"error": "This reset link is invalid or expired."}, status_code=400)
    user.password_hash = hash_password(password)
    user.reset_token = None
    user.reset_token_expires = None
    # Revoke all existing sessions for safety.
    for s in await db.execute(select(UserSession).where(UserSession.user_id == user.id)):
        s[0].is_active = False
    return render(request, "auth/reset.html", {"done": True})
