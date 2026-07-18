"""Social login (OAuth2 authorization-code flow), no extra SDK required.

Enabled providers appear automatically on the login page once their client id +
secret are set in .env. Register this callback URL with each provider:

    {BASE_URL}/auth/{provider}/callback

Apple Sign-In is deliberately not bundled: it needs a JWT client secret signed
with a downloaded .p8 key and a form_post callback. Add it as another PROVIDERS
entry plus a client-secret generator when you need it.
"""
from __future__ import annotations

import secrets

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import logger
from app.models.oauth import OAuthAccount
from app.models.rbac import Role
from app.models.user import User
from app.routers.auth import _establish_session
from app.services import audit

router = APIRouter(tags=["oauth"])

STATE_COOKIE = "oauth_state"
_state_signer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="oauth-state")

PROVIDERS: dict[str, dict] = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "client_id_key": "OAUTH_GOOGLE_CLIENT_ID",
        "client_secret_key": "OAUTH_GOOGLE_CLIENT_SECRET",
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": "read:user user:email",
        "client_id_key": "OAUTH_GITHUB_CLIENT_ID",
        "client_secret_key": "OAUTH_GITHUB_CLIENT_SECRET",
    },
}


def _conf(provider: str) -> dict:
    conf = PROVIDERS.get(provider)
    if not conf or not settings.oauth_providers.get(provider):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not enabled")
    return conf


def _client_id(conf: dict) -> str:
    return getattr(settings, conf["client_id_key"])


def _client_secret(conf: dict) -> str:
    return getattr(settings, conf["client_secret_key"])


def _redirect_uri(provider: str) -> str:
    return f"{settings.BASE_URL.rstrip('/')}/auth/{provider}/callback"


@router.get("/auth/{provider}/login")
async def oauth_login(provider: str, request: Request, next: str = ""):
    conf = _conf(provider)
    state = secrets.token_urlsafe(24)
    params = {
        "client_id": _client_id(conf),
        "redirect_uri": _redirect_uri(provider),
        "response_type": "code",
        "scope": conf["scope"],
        "state": state,
    }
    query = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
    resp = RedirectResponse(f"{conf['authorize_url']}?{query}", status_code=302)
    resp.set_cookie(
        STATE_COOKIE,
        _state_signer.dumps({"state": state, "next": next, "provider": provider}),
        max_age=600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return resp


async def _fetch_identity(provider: str, conf: dict, code: str) -> tuple[str, str | None]:
    """Exchange the code and return (provider_user_id, email)."""
    async with httpx.AsyncClient(timeout=15) as client:
        token_res = await client.post(
            conf["token_url"],
            data={
                "client_id": _client_id(conf),
                "client_secret": _client_secret(conf),
                "code": code,
                "redirect_uri": _redirect_uri(provider),
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
        token_res.raise_for_status()
        access_token = token_res.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="No access token returned")

        headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
        info = (await client.get(conf["userinfo_url"], headers=headers)).json()

        if provider == "google":
            return str(info["sub"]), info.get("email")

        # GitHub may hide the email on the profile; fall back to the emails endpoint.
        email = info.get("email")
        if not email:
            emails_res = await client.get(
                "https://api.github.com/user/emails", headers=headers
            )
            emails = emails_res.json()
            primary = next(
                (e for e in emails if e.get("primary") and e.get("verified")),
                next((e for e in emails if e.get("verified")), None),
            )
            email = primary.get("email") if primary else None
        return str(info["id"]), email


@router.get("/auth/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: str = "",
    state: str = "",
    db: AsyncSession = Depends(get_db),
):
    conf = _conf(provider)

    # Validate the anti-forgery state against the signed cookie.
    raw = request.cookies.get(STATE_COOKIE)
    if not raw or not code:
        raise HTTPException(status_code=400, detail="Invalid OAuth callback")
    try:
        payload = _state_signer.loads(raw, max_age=600)
    except BadSignature as exc:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state") from exc
    if payload.get("state") != state or payload.get("provider") != provider:
        raise HTTPException(status_code=400, detail="OAuth state mismatch")

    try:
        provider_user_id, email = await _fetch_identity(provider, conf, code)
    except httpx.HTTPError as exc:
        logger.warning("OAuth %s exchange failed: %s", provider, exc)
        raise HTTPException(status_code=400, detail="OAuth exchange failed") from exc

    # 1) Existing link  2) match by email  3) create a new account.
    link = (
        await db.execute(
            select(OAuthAccount).where(
                OAuthAccount.provider == provider,
                OAuthAccount.provider_user_id == provider_user_id,
            )
        )
    ).scalar_one_or_none()

    if link:
        user = await db.get(User, link.user_id)
    else:
        user = None
        if email:
            user = (
                await db.execute(select(User).where(User.email == email.lower()))
            ).scalar_one_or_none()
        if user is None:
            if not settings.REGISTRATION_ENABLED:
                raise HTTPException(status_code=403, detail="Registration is disabled")
            if not email:
                raise HTTPException(status_code=400, detail="Provider did not supply an email")
            user = User(email=email.lower(), email_verified=True, display_name="")
            role = (
                await db.execute(select(Role).where(Role.name == "user"))
            ).scalar_one_or_none()
            if role:
                user.roles.append(role)
            db.add(user)
            await db.flush()
        db.add(OAuthAccount(user_id=user.id, provider=provider,
                            provider_user_id=provider_user_id, email=email))
        await audit.record(db, audit.OAUTH_LINKED, actor=user, request=request, detail=provider)

    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="Account unavailable")

    next_url = payload.get("next") or "/account"
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/account"
    resp = RedirectResponse(next_url, status_code=status.HTTP_303_SEE_OTHER)
    await _establish_session(resp, request, db, user)
    await audit.record(db, audit.LOGIN, actor=user, request=request, detail=f"via {provider}")
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp
