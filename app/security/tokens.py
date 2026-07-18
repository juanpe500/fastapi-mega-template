"""JWT access/refresh tokens + TOTP (2FA) helpers.

The access token carries a `sid` claim referencing a UserSession row so sessions
remain individually revocable despite the token being stateless.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pyotp

from app.config import settings


def _encode(payload: dict[str, Any], expires: timedelta, token_type: str) -> str:
    now = datetime.now(UTC)
    to_encode = {**payload, "iat": now, "exp": now + expires, "type": token_type}
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: str, session_id: str, extra: dict | None = None) -> str:
    payload = {"sub": user_id, "sid": session_id, **(extra or {})}
    return _encode(payload, timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES), "access")


def create_refresh_token(user_id: str, session_id: str) -> str:
    return _encode(
        {"sub": user_id, "sid": session_id},
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        "refresh",
    )


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any] | None:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    if expected_type and payload.get("type") != expected_type:
        return None
    return payload


# --- short-lived opaque tokens (email verify / password reset) ---------------
def generate_url_token() -> tuple[str, str]:
    """Return (plaintext, sha256_hash). Email the plaintext, store the hash."""
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode()).hexdigest()


def hash_url_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# --- TOTP / 2FA --------------------------------------------------------------
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.APP_NAME)


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
