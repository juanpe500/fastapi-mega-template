"""Inbound bounce/complaint webhook from your email provider.

Point Postmark / AWS SES (SNS) / Mailgun etc. at:
    POST {BASE_URL}/webhooks/email?token=EMAIL_WEBHOOK_SECRET
Every reported address is added to the suppression list so we stop mailing it.
The path is CSRF-exempt (it authenticates by the shared token, not a cookie).
"""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logging_config import logger
from app.services import suppression

router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/email")
async def email_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    if not settings.EMAIL_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Email webhook not configured")

    provided = request.query_params.get("token") or request.headers.get("x-webhook-token", "")
    if not hmac.compare_digest(provided, settings.EMAIL_WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Invalid webhook token")

    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    events = suppression.parse_provider_payload(payload)
    for email, reason, detail in events:
        await suppression.suppress(db, email, reason=reason, detail=detail)
    if not events:
        logger.info("Email webhook: no actionable events in payload.")
    return {"suppressed": len(events)}
