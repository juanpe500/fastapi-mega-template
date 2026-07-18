"""Public pages: home + static legal/marketing pages.

Legal pages are server-rendered from templates/legal/*.html so you can drop in
your real copy later. `last_updated` is passed in one place so every page shows
a consistent date — replace the placeholder text with your actual policies.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.config import settings
from app.security.deps import get_current_user_optional
from app.services import referrals
from app.templating import render

router = APIRouter(tags=["pages"])

# Bump when you revise the policies.
LEGAL_LAST_UPDATED = "2026-01-01"


@router.get("/")
async def index(request: Request, ref: str = "", user=Depends(get_current_user_optional)):
    resp = render(request, "index.html", {}, user=user)
    # Remember a referral code so it survives browsing before signup.
    if ref and settings.REFERRALS_ENABLED and not user:
        resp.set_cookie(
            referrals.COOKIE_NAME, ref[:20], max_age=referrals.COOKIE_MAX_AGE,
            samesite="lax", path="/",
        )
    return resp


@router.get("/terms")
async def terms(request: Request, user=Depends(get_current_user_optional)):
    return render(request, "legal/terms.html", {"last_updated": LEGAL_LAST_UPDATED}, user=user)


@router.get("/privacy")
async def privacy(request: Request, user=Depends(get_current_user_optional)):
    return render(request, "legal/privacy.html", {"last_updated": LEGAL_LAST_UPDATED}, user=user)


@router.get("/refunds")
async def refunds(request: Request, user=Depends(get_current_user_optional)):
    return render(request, "legal/refunds.html", {"last_updated": LEGAL_LAST_UPDATED}, user=user)


@router.get("/contact")
async def contact(request: Request, user=Depends(get_current_user_optional)):
    return render(request, "legal/contact.html", {"support_email": settings.EMAIL_FROM}, user=user)
