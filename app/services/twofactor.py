"""2FA helpers: QR rendering and one-time recovery codes.

The QR is rendered as inline SVG (no external service, no image files, CSP-safe).
Recovery codes are shown once at generation time and stored only as hashes.
"""
from __future__ import annotations

import hashlib
import io
import secrets

import segno
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recovery import RecoveryCode
from app.models.user import User

RECOVERY_CODE_COUNT = 10


def qr_svg(uri: str, scale: int = 4) -> str:
    """Render an otpauth:// URI as an inline <svg> string (segno writes bytes)."""
    buf = io.BytesIO()
    segno.make(uri, error="m").save(
        buf, kind="svg", scale=scale, border=2, xmldecl=False, svgns=True
    )
    return buf.getvalue().decode("utf-8")


def _hash(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").lower().encode()).hexdigest()


def _new_code() -> str:
    raw = secrets.token_hex(5)  # 10 hex chars
    return f"{raw[:5]}-{raw[5:]}"


async def generate_recovery_codes(
    db: AsyncSession, user: User, count: int = RECOVERY_CODE_COUNT
) -> list[str]:
    """Replace any existing codes with a fresh set. Returns the plaintext codes
    (the only time they are visible)."""
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
    codes = [_new_code() for _ in range(count)]
    for code in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=_hash(code)))
    await db.flush()
    return codes


async def consume_recovery_code(db: AsyncSession, user: User, code: str) -> bool:
    """Validate and burn a recovery code. Returns True if it was valid."""
    if not code:
        return False
    row = (
        await db.execute(
            select(RecoveryCode).where(
                RecoveryCode.user_id == user.id,
                RecoveryCode.code_hash == _hash(code),
                RecoveryCode.used == False,  # noqa: E712
            )
        )
    ).scalar_one_or_none()
    if not row:
        return False
    row.used = True
    await db.flush()
    return True


async def remaining_recovery_codes(db: AsyncSession, user: User) -> int:
    rows = await db.execute(
        select(RecoveryCode).where(
            RecoveryCode.user_id == user.id, RecoveryCode.used == False  # noqa: E712
        )
    )
    return len(rows.scalars().all())


async def clear_recovery_codes(db: AsyncSession, user: User) -> None:
    await db.execute(delete(RecoveryCode).where(RecoveryCode.user_id == user.id))
