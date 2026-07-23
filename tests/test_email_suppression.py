"""Email suppression: provider payload parsing, storage, and the webhook."""
from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path


# --------------------------------------------------------- payload parsing ----
def test_parse_postmark_bounce_and_complaint():
    from app.services import suppression

    bounce = suppression.parse_provider_payload(
        {"RecordType": "Bounce", "Email": "Dead@Example.com", "Type": "HardBounce"}
    )
    assert bounce == [("Dead@Example.com", "bounce", "HardBounce")]

    complaint = suppression.parse_provider_payload(
        {"RecordType": "SpamComplaint", "Email": "angry@example.com"}
    )
    assert complaint[0][1] == "complaint"


def test_parse_ses_sns_complaint():
    from app.services import suppression

    message = json.dumps({
        "notificationType": "Complaint",
        "complaint": {"complainedRecipients": [{"emailAddress": "x@example.com"}]},
    })
    events = suppression.parse_provider_payload({"Type": "Notification", "Message": message})
    assert events == [("x@example.com", "complaint", "")]


def test_parse_generic_and_unknown_shapes():
    from app.services import suppression

    assert suppression.parse_provider_payload({"email": "a@b.com", "reason": "manual"}) == [
        ("a@b.com", "manual", "")
    ]
    assert suppression.parse_provider_payload({"nonsense": True}) == []
    assert suppression.parse_provider_payload("garbage") == []


# --------------------------------------------------------------- storage ------
def test_suppress_is_idempotent_and_case_insensitive():
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import app.models  # noqa: F401
    from app.models.base import Base
    from app.services import suppression

    tmp = Path(tempfile.gettempdir()) / f"suppress_{uuid.uuid4().hex}.db"

    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp.as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as db:
            await suppression.suppress(db, "Foo@Example.com", reason="bounce")
            await suppression.suppress(db, "foo@example.com", reason="complaint")  # upsert
            await db.commit()
            assert await suppression.is_suppressed(db, "FOO@example.com") is True
            assert await suppression.is_suppressed(db, "other@example.com") is False
            await suppression.unsuppress(db, "foo@example.com")
            await db.commit()
            assert await suppression.is_suppressed(db, "foo@example.com") is False
        await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        tmp.unlink(missing_ok=True)


# --------------------------------------------------------------- webhook ------
def test_webhook_rejects_bad_token(client, s):
    r = s.c.post("/webhooks/email?token=wrong",
                 json={"RecordType": "Bounce", "Email": "x@example.com"})
    assert r.status_code == 403


def test_webhook_accepts_valid_token_and_reports_count(client, s):
    r = s.c.post("/webhooks/email?token=test-webhook-secret",
                 json={"RecordType": "Bounce", "Email": "bounced@example.com",
                       "Type": "HardBounce"})
    assert r.status_code == 200
    assert r.json() == {"suppressed": 1}
