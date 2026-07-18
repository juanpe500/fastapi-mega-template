"""Admin: plans & subscriptions overview."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.billing import Plan, Subscription
from app.models.user import User
from app.pagination import csv_response, paginate
from app.security.deps import get_current_user, require_permission
from app.templating import render

router = APIRouter(prefix="/billing")


def _subs_stmt(status_filter: str):
    # `plan` is read in the template, after the session closes -> eager-load it.
    stmt = (
        select(Subscription)
        .options(selectinload(Subscription.plan))
        .order_by(Subscription.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(Subscription.status == status_filter)
    return stmt


@router.get("")
async def overview(
    request: Request,
    status_filter: str = "",
    page: int = 1,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    plans = (await db.execute(select(Plan).order_by(Plan.sort_order))).scalars().all()
    result = await paginate(db, _subs_stmt(status_filter), page=page)
    return render(request, "admin/billing.html",
                  {"plans": plans, "subs": result.items, "page_obj": result,
                   "status_filter": status_filter}, user=user)


@router.get("/subscriptions.csv")
async def export_subscriptions(
    status_filter: str = "",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (await db.execute(_subs_stmt(status_filter))).scalars().all()
    return csv_response(
        "subscriptions.csv",
        ["id", "user_id", "plan_id", "status", "created_at", "current_period_end"],
        [
            [s.id, s.user_id, s.plan_id, s.status, s.created_at, s.current_period_end]
            for s in rows
        ],
    )


@router.post("/plans/{plan_id}/toggle",
             dependencies=[Depends(require_permission("billing.manage"))])
async def toggle_plan(plan_id: str, db: AsyncSession = Depends(get_db)):
    """Retire or re-list a plan (hidden from the customer billing page when off)."""
    plan = await db.get(Plan, plan_id)
    if plan:
        plan.is_active = not plan.is_active
    return RedirectResponse("/admin/billing", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/plans", dependencies=[Depends(require_permission("billing.manage"))])
async def upsert_plan(
    code: str = Form(...),
    name: str = Form(...),
    kind: str = Form("subscription"),
    price_cents: int = Form(0),
    interval: str = Form(""),
    stripe_price_id: str = Form(""),
    credits_granted: str = Form("0"),
    db: AsyncSession = Depends(get_db),
):
    code = code.strip().lower()
    plan = (await db.execute(select(Plan).where(Plan.code == code))).scalar_one_or_none()
    if not plan:
        plan = Plan(code=code)
        db.add(plan)
    plan.name = name
    plan.kind = kind
    plan.price_cents = price_cents
    plan.interval = interval or None
    plan.stripe_price_id = stripe_price_id or None
    from decimal import Decimal

    plan.credits_granted = Decimal(credits_granted or "0")
    return RedirectResponse("/admin/billing", status_code=status.HTTP_303_SEE_OTHER)
