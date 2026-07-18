"""Stripe billing endpoints: Checkout, Customer Portal, and the webhook."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import logger
from app.models.billing import Plan
from app.models.user import User
from app.security.deps import get_current_user
from app.services import stripe_service

router = APIRouter(tags=["billing"])


@router.post("/billing/checkout/{plan_code}")
async def checkout(
    plan_code: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.stripe_enabled:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    plan = (
        await db.execute(select(Plan).where(Plan.code == plan_code, Plan.is_active == True))  # noqa: E712
    ).scalar_one_or_none()
    if not plan or not plan.stripe_price_id:
        raise HTTPException(status_code=404, detail="Plan not found")
    url = await stripe_service.create_checkout_session(db, user, plan)
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/billing/portal")
async def portal(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not settings.stripe_enabled:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    url = await stripe_service.create_portal_session(db, user)
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/billing/webhook")
async def webhook(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.stripe_enabled:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        result = await stripe_service.handle_webhook(db, payload, sig)
    except ValueError as exc:  # bad signature / payload
        logger.warning("Stripe webhook rejected: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(result)
