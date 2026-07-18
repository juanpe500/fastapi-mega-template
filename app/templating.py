"""Shared Jinja2 environment + a small render() helper.

`deploy_version` is injected as a global so templates can cache-bust static
assets:  <script src="/static/js/app.js?v={{ deploy_version }}"></script>
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app import i18n
from app.config import settings
from app.models.user import User

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals.update(
    APP_NAME=settings.APP_NAME,
    BASE_URL=settings.BASE_URL,
    deploy_version=settings.DEPLOY_VERSION,
    ENV=settings.ENV,
    stripe_enabled=settings.stripe_enabled,
    oauth_providers=settings.oauth_providers,
    any_oauth_enabled=settings.any_oauth_enabled,
    turnstile_enabled=settings.turnstile_enabled,
    turnstile_site_key=settings.TURNSTILE_SITE_KEY,
    # SEO defaults (override per page with the `meta_*` context keys)
    SITE_DESCRIPTION=settings.SITE_DESCRIPTION,
    SITE_IMAGE=settings.SITE_IMAGE,
    # Consent / analytics
    cookie_banner_enabled=settings.COOKIE_BANNER_ENABLED,
    analytics_enabled=settings.analytics_enabled,
    analytics_script_url=settings.ANALYTICS_SCRIPT_URL,
    analytics_site_id=settings.ANALYTICS_SITE_ID,
    # i18n
    available_locales=settings.locale_list,
    LOCALES=settings.locale_list,
    # Account / referrals
    REFERRALS_ENABLED=settings.REFERRALS_ENABLED,
    ACCOUNT_DELETION_GRACE_DAYS=settings.ACCOUNT_DELETION_GRACE_DAYS,
)


def render(
    request: Request,
    name: str,
    context: dict[str, Any] | None = None,
    *,
    user: User | None = None,
    status_code: int = 200,
):
    token = getattr(request.state, "csrf", "")
    locale = i18n.resolve_locale(request, user)
    ctx = {
        "request": request,
        "user": user,
        "impersonator_id": getattr(request.state, "impersonator_id", None),
        "csrf_token": token,
        # Drop `{{ csrf_field }}` inside any POST form to satisfy CSRF protection.
        "csrf_field": Markup(f'<input type="hidden" name="_csrf" value="{token}">'),
        # i18n: {{ t("some.key") }}
        "locale": locale,
        "t": lambda key, **kw: i18n.translate(key, locale, **kw),
        # Analytics only run once the visitor has consented.
        "cookies_accepted": request.cookies.get("cookie_consent") == "all",
    }
    if context:
        ctx.update(context)
    return templates.TemplateResponse(name, ctx, status_code=status_code)
