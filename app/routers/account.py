"""Authenticated account area: profile, password, API key, 2FA, billing view."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.base import aware, utcnow
from app.models.billing import CreditTransaction, Plan, Subscription
from app.models.billing_profile import BillingProfile
from app.models.user import User, UserSession
from app.security.breach_check import breach_count
from app.security.deps import current_session_id, get_current_user
from app.security.passwords import generate_api_key, hash_password, verify_password
from app.security.ratelimit import RateLimiter
from app.security.tokens import (
    generate_url_token,
    hash_url_token,
    new_totp_secret,
    totp_provisioning_uri,
    verify_totp,
)
from app.services import (
    account_service,
    audit,
    credit_service,
    notifications,
    referrals,
    twofactor,
)
from app.services import email as email_service
from app.services.storage import get_storage, read_upload, safe_filename
from app.templating import render

router = APIRouter(prefix="/account", tags=["account"])

# Per-user limits on the endpoints that cost money or send mail.
export_limiter = RateLimiter(times=3, seconds=3600, scope="export", per_user=True)
email_change_limiter = RateLimiter(times=5, seconds=3600, scope="email_change", per_user=True)


@router.get("")
async def profile(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    sub = (
        await db.execute(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .order_by(Subscription.created_at.desc())
        )
    ).scalars().first()
    if settings.REFERRALS_ENABLED:
        await referrals.ensure_code(db, user)
    return render(request, "account/profile.html",
                  {"balance": await credit_service.get_balance(db, user), "subscription": sub,
                   "referral_link": referrals.referral_link(user),
                   "referral_count": await referrals.referral_count(db, user),
                   "deletion_due_at": account_service.deletion_due_at(user)},
                  user=user)


@router.post("/password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(current_password, user.password_hash):
        return render(request, "account/profile.html",
                      {"error": "Current password is incorrect.",
                       "balance": await credit_service.get_balance(db, user)},
                      user=user, status_code=400)
    if len(new_password) < 8:
        return render(request, "account/profile.html",
                      {"error": "New password must be at least 8 characters.",
                       "balance": await credit_service.get_balance(db, user)},
                      user=user, status_code=400)
    breaches = await breach_count(new_password)
    if breaches:
        return render(request, "account/profile.html",
                      {"error": f"That password has appeared in {breaches:,} known data "
                                f"breaches. Please choose a different one.",
                       "balance": await credit_service.get_balance(db, user)},
                      user=user, status_code=400)
    user.password_hash = hash_password(new_password)
    await notifications.notify(
        db, user, "security", "Your password was changed",
        "If this wasn't you, reset your password and contact support immediately.",
    )
    await audit.record(db, audit.PASSWORD_CHANGED, actor=user, request=request)
    return RedirectResponse("/account?changed=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile")
async def update_profile(
    request: Request,
    display_name: str = Form(""),
    locale: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.display_name = display_name.strip()[:120]
    if locale and locale in settings.locale_list:
        user.locale = locale
    await audit.record(db, "user.profile_updated", actor=user, request=request)
    return RedirectResponse("/account?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/email", dependencies=[Depends(email_change_limiter)])
async def request_email_change(
    request: Request,
    new_email: str = Form(...),
    password: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start an email change. The address only swaps once the NEW one is confirmed,
    and the OLD address is notified so a hijacked session can't silently move it."""
    new_email = new_email.strip().lower()
    if not verify_password(password, user.password_hash):
        return RedirectResponse("/account?email_error=password",
                                status_code=status.HTTP_303_SEE_OTHER)
    if new_email == user.email:
        return RedirectResponse("/account?email_error=same",
                                status_code=status.HTTP_303_SEE_OTHER)
    taken = (
        await db.execute(select(User).where(User.email == new_email))
    ).scalar_one_or_none()
    if taken:
        # Don't confirm the address exists — report the generic "check your inbox".
        return RedirectResponse("/account?email_pending=1",
                                status_code=status.HTTP_303_SEE_OTHER)

    raw, hashed = generate_url_token()
    user.pending_email = new_email
    user.pending_email_token = hashed
    user.pending_email_expires = utcnow() + timedelta(hours=24)
    await db.flush()

    link = f"{settings.BASE_URL}/account/email/confirm?token={raw}"
    await email_service.send_email(
        new_email,
        f"Confirm your new {settings.APP_NAME} email",
        f"Confirm this address: {link}",
        html=email_service.render_email("email_change.html", link=link, new_email=new_email),
    )
    await audit.record(db, "user.email_change_requested", actor=user, request=request,
                       detail=new_email)
    return RedirectResponse("/account?email_pending=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/email/confirm")
async def confirm_email_change(
    request: Request,
    token: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    hashed = hash_url_token(token) if token else ""
    valid = (
        hashed
        and user.pending_email_token == hashed
        and user.pending_email
        and user.pending_email_expires
        and aware(user.pending_email_expires) > utcnow()
    )
    if not valid:
        return render(request, "account/email_changed.html", {"ok": False}, user=user,
                      status_code=400)

    old_email, new_email = user.email, user.pending_email
    user.email = new_email
    user.email_verified = True
    user.pending_email = None
    user.pending_email_token = None
    user.pending_email_expires = None
    await db.flush()

    # Tell the previous address, so an unauthorised change is noticed.
    await email_service.send_email(
        old_email,
        f"Your {settings.APP_NAME} email address was changed",
        f"The email on your account was changed to {new_email}. "
        f"If this wasn't you, contact support immediately.",
    )
    await audit.record(db, "user.email_changed", actor=user, request=request,
                       detail=f"{old_email} -> {new_email}")
    return render(request, "account/email_changed.html", {"ok": True, "email": new_email},
                  user=user)


# -------------------------------------------------------- account lifecycle
@router.get("/export", dependencies=[Depends(export_limiter)])
async def export_data(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One-click download of everything we hold about this account (GDPR)."""
    data = await account_service.export_user_data(db, user)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    filename = f"{settings.APP_NAME.lower().replace(' ', '-')}-export-{user.id[:8]}.json"
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/deactivate")
async def deactivate_account(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reversible: signing in again reactivates the account."""
    await account_service.deactivate(db, user)
    await audit.record(db, "user.deactivated", actor=user, request=request)
    resp = RedirectResponse("/?deactivated=1", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    resp.delete_cookie("refresh", path="/")
    return resp


@router.post("/delete")
async def delete_account(
    request: Request,
    confirm: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Schedules irreversible deletion after the grace period."""
    if confirm.strip().upper() != "DELETE":
        return RedirectResponse("/account?delete_error=1",
                                status_code=status.HTTP_303_SEE_OTHER)
    await account_service.request_deletion(db, user)
    await audit.record(db, "user.deletion_requested", actor=user, request=request)
    await email_service.send_email(
        user.email,
        f"Your {settings.APP_NAME} account is scheduled for deletion",
        f"Your account will be permanently deleted in "
        f"{settings.ACCOUNT_DELETION_GRACE_DAYS} days. Changed your mind? Sign in and "
        f"press \"Cancel deletion\" on your account page before then.",
    )
    resp = RedirectResponse("/?deletion_scheduled=1", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    resp.delete_cookie("refresh", path="/")
    return resp


@router.post("/delete/cancel")
async def cancel_account_deletion(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await account_service.cancel_deletion(db, user)
    await audit.record(db, "user.deletion_cancelled", actor=user, request=request)
    return RedirectResponse("/account?deletion_cancelled=1",
                            status_code=status.HTTP_303_SEE_OTHER)


@router.post("/avatar")
async def upload_avatar(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not (file.content_type or "").startswith("image/"):
        return RedirectResponse("/account?avatar_error=1", status_code=status.HTTP_303_SEE_OTHER)
    try:
        data = await read_upload(file, settings.UPLOAD_MAX_MB)
    except ValueError:
        return RedirectResponse("/account?avatar_error=1", status_code=status.HTTP_303_SEE_OTHER)
    name = safe_filename(file.filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else "png"
    key = f"avatars/{user.id}/{uuid.uuid4().hex}.{ext}"
    user.avatar_url = await get_storage().save_public(key, data, file.content_type)
    return RedirectResponse("/account", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/api-key")
async def create_api_key(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    raw, key_hash = generate_api_key()
    user.api_key_hash = key_hash
    await audit.record(db, audit.API_KEY_CREATED, actor=user, request=request)
    # Show the plaintext key exactly once.
    return render(request, "account/api_key.html", {"api_key": raw}, user=user)


# ------------------------------------------------------------------------ 2FA
@router.get("/2fa")
async def two_factor_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.totp_enabled:
        return render(request, "account/twofactor.html",
                      {"enabled": True,
                       "remaining_codes": await twofactor.remaining_recovery_codes(db, user)},
                      user=user)
    secret = user.totp_secret or new_totp_secret()
    user.totp_secret = secret  # persisted on commit; confirmed by /2fa/enable
    uri = totp_provisioning_uri(secret, user.email)
    return render(request, "account/twofactor.html",
                  {"enabled": False, "secret": secret, "uri": uri,
                   "qr_svg": twofactor.qr_svg(uri)}, user=user)


@router.post("/2fa/enable")
async def two_factor_enable(
    request: Request,
    code: str = Form(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_totp(user.totp_secret or "", code):
        secret = user.totp_secret or new_totp_secret()
        uri = totp_provisioning_uri(secret, user.email)
        return render(request, "account/twofactor.html",
                      {"enabled": False, "secret": secret, "uri": uri,
                       "qr_svg": twofactor.qr_svg(uri), "error": "Invalid code, try again."},
                      user=user, status_code=400)
    user.totp_enabled = True
    await audit.record(db, audit.TWOFA_ENABLED, actor=user, request=request)
    codes = await twofactor.generate_recovery_codes(db, user)
    # Codes are displayed exactly once, here.
    return render(request, "account/twofactor.html",
                  {"enabled": True, "recovery_codes": codes,
                   "remaining_codes": len(codes)}, user=user)


@router.post("/2fa/recovery-codes")
async def regenerate_recovery_codes(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.totp_enabled:
        return RedirectResponse("/account/2fa", status_code=status.HTTP_303_SEE_OTHER)
    codes = await twofactor.generate_recovery_codes(db, user)
    return render(request, "account/twofactor.html",
                  {"enabled": True, "recovery_codes": codes, "remaining_codes": len(codes),
                   "regenerated": True}, user=user)


@router.post("/2fa/disable")
async def two_factor_disable(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.totp_enabled = False
    user.totp_secret = None
    await twofactor.clear_recovery_codes(db, user)
    await audit.record(db, audit.TWOFA_DISABLED, actor=user, request=request)
    return RedirectResponse("/account/2fa", status_code=status.HTTP_303_SEE_OTHER)


# ------------------------------------------------------------------ sessions
@router.get("/sessions")
async def sessions_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(UserSession)
        .where(UserSession.user_id == user.id, UserSession.is_active == True)  # noqa: E712
        .order_by(UserSession.last_active_at.desc().nullslast())
    )
    return render(request, "account/sessions.html",
                  {"sessions": rows.scalars().all(),
                   "current_sid": current_session_id(request)}, user=user)


@router.post("/sessions/{session_id}/revoke")
async def revoke_session(
    request: Request,
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    target = await db.get(UserSession, session_id)
    if target and target.user_id == user.id:
        target.is_active = False
        await audit.record(db, audit.SESSION_REVOKED, actor=user, request=request,
                           target_type="UserSession", target_id=session_id)
    # Revoking the session you're using logs you out.
    if session_id == current_session_id(request):
        return RedirectResponse("/logout", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/account/sessions", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/sessions/revoke-all")
async def revoke_all_sessions(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sign out everywhere except the device making this request."""
    keep = current_session_id(request)
    rows = await db.execute(
        select(UserSession).where(
            UserSession.user_id == user.id, UserSession.is_active == True  # noqa: E712
        )
    )
    revoked = 0
    for s in rows.scalars().all():
        if s.id != keep:
            s.is_active = False
            revoked += 1
    await audit.record(db, audit.SESSION_REVOKED, actor=user, request=request,
                       detail=f"signed out everywhere ({revoked} sessions)")
    return RedirectResponse("/account/sessions", status_code=status.HTTP_303_SEE_OTHER)


# -------------------------------------------------------------------- billing
@router.get("/billing")
async def billing_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plans = (
        await db.execute(
            select(Plan).where(Plan.is_active == True).order_by(Plan.sort_order)  # noqa: E712
        )
    ).scalars().all()
    sub = (
        await db.execute(
            select(Subscription)
            .where(Subscription.user_id == user.id)
            .order_by(Subscription.created_at.desc())
        )
    ).scalars().first()
    profile = (
        await db.execute(select(BillingProfile).where(BillingProfile.user_id == user.id))
    ).scalar_one_or_none()
    return render(request, "account/billing.html",
                  {"plans": plans, "subscription": sub, "billing_profile": profile,
                   "balance": await credit_service.get_balance(db, user),
                   "history": await credit_service.history(db, user, limit=25)},
                  user=user)


@router.post("/billing/profile")
async def save_billing_profile(
    request: Request,
    company_name: str = Form(""),
    tax_id: str = Form(""),
    address_line1: str = Form(""),
    address_line2: str = Form(""),
    city: str = Form(""),
    postal_code: str = Form(""),
    state: str = Form(""),
    country: str = Form(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Details printed on receipts and passed to Stripe for tax calculation."""
    profile = (
        await db.execute(select(BillingProfile).where(BillingProfile.user_id == user.id))
    ).scalar_one_or_none()
    if profile is None:
        profile = BillingProfile(user_id=user.id)
        db.add(profile)
    profile.company_name = company_name.strip()[:200]
    profile.tax_id = tax_id.strip()[:60]
    profile.address_line1 = address_line1.strip()[:200]
    profile.address_line2 = address_line2.strip()[:200]
    profile.city = city.strip()[:100]
    profile.postal_code = postal_code.strip()[:30]
    profile.state = state.strip()[:100]
    profile.country = country.strip().upper()[:2]
    return RedirectResponse("/account/billing?saved=1", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/billing/receipt/{tx_id}")
async def receipt(
    request: Request,
    tx_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Printable receipt for a purchase (browser -> Save as PDF)."""
    tx = await db.get(CreditTransaction, tx_id)
    if not tx or tx.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    profile = (
        await db.execute(select(BillingProfile).where(BillingProfile.user_id == user.id))
    ).scalar_one_or_none()
    return render(request, "account/receipt.html", {"tx": tx, "billing_profile": profile},
                  user=user)
