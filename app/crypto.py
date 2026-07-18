"""Symmetric encryption for secrets at rest (e.g. user-supplied API keys / BYOK).

Uses Fernet (AES-128-CBC + HMAC). The key is ENCRYPTION_KEY if set, otherwise
derived deterministically from SECRET_KEY so it works with zero config in dev.
For production set a dedicated ENCRYPTION_KEY:
    python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _derive_key() -> bytes:
    raw = settings.ENCRYPTION_KEY.strip()
    if raw:
        # Accept either a real Fernet key or arbitrary text (hash it to 32 bytes).
        try:
            Fernet(raw.encode())
            return raw.encode()
        except (ValueError, TypeError):
            digest = hashlib.sha256(raw.encode()).digest()
            return base64.urlsafe_b64encode(digest)
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_key())


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str | None:
    try:
        return _fernet.decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return None
