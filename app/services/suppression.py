"""Email suppression: never mail an address that hard-bounced or complained.

`is_suppressed`/`suppress`/`unsuppress` are the storage primitives.
`parse_provider_payload` normalises the webhook bodies of the common ESPs
(Postmark, AWS SES via SNS, plus a generic {email, reason} shape) into
(email, reason, detail) tuples so routers/email_webhook.py stays tiny.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import logger
from app.models.suppression import SuppressedEmail


def _norm(email: str) -> str:
    return (email or "").strip().lower()


async def is_suppressed(db: AsyncSession, email: str) -> bool:
    email = _norm(email)
    if not email:
        return False
    return (
        await db.execute(select(SuppressedEmail.id).where(SuppressedEmail.email == email))
    ).first() is not None


async def is_suppressed_email(email: str) -> bool:
    """Convenience for callers with no session of their own (e.g. send_email)."""
    from app.database import SessionLocal

    async with SessionLocal() as db:
        return await is_suppressed(db, email)


async def suppress(
    db: AsyncSession, email: str, reason: str = "bounce", detail: str = ""
) -> SuppressedEmail | None:
    email = _norm(email)
    if not email:
        return None
    row = (
        await db.execute(select(SuppressedEmail).where(SuppressedEmail.email == email))
    ).scalar_one_or_none()
    if row is None:
        row = SuppressedEmail(email=email)
        db.add(row)
    row.reason = reason
    row.detail = (detail or "")[:500]
    await db.flush()
    logger.info("Email suppressed (%s): %s", reason, email)
    return row


async def unsuppress(db: AsyncSession, email: str) -> None:
    row = (
        await db.execute(select(SuppressedEmail).where(SuppressedEmail.email == _norm(email)))
    ).scalar_one_or_none()
    if row is not None:
        await db.delete(row)


def parse_provider_payload(payload) -> list[tuple[str, str, str]]:
    """Return a list of (email, reason, detail) from an ESP webhook body.
    Unknown shapes yield [] rather than raising — the endpoint just 200s."""
    out: list[tuple[str, str, str]] = []
    if isinstance(payload, list):
        for item in payload:
            out.extend(parse_provider_payload(item))
        return out
    if not isinstance(payload, dict):
        return out

    # Generic normalised shape: {"email": "...", "reason": "bounce", "detail": "..."}
    if payload.get("email"):
        out.append((payload["email"], payload.get("reason", "bounce"),
                    str(payload.get("detail") or "")))
        return out

    # Postmark: one object with a RecordType.
    rt = payload.get("RecordType")
    if rt in ("Bounce", "SpamComplaint"):
        email = payload.get("Email") or payload.get("Recipient")
        if email:
            reason = "complaint" if rt == "SpamComplaint" else "bounce"
            out.append((email, reason,
                        str(payload.get("Type") or payload.get("Description") or "")))
        return out

    # AWS SES via SNS: {"Type": "Notification", "Message": "<json string>"}.
    if payload.get("Type") == "Notification" and payload.get("Message"):
        try:
            msg = json.loads(payload["Message"])
        except (ValueError, TypeError):
            return out
        ntype = msg.get("notificationType") or msg.get("eventType")
        if ntype == "Bounce":
            info = msg.get("bounce") or {}
            for r in info.get("bouncedRecipients", []):
                if r.get("emailAddress"):
                    out.append((r["emailAddress"], "bounce", str(info.get("bounceType") or "")))
        elif ntype == "Complaint":
            info = msg.get("complaint") or {}
            for r in info.get("complainedRecipients", []):
                if r.get("emailAddress"):
                    out.append((r["emailAddress"], "complaint", ""))
        return out

    return out
