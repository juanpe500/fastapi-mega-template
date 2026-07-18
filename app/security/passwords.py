"""Password + API-key hashing.

Includes the bcrypt/passlib compatibility shim needed on bcrypt>=4.1 / Python
3.13 (passlib probes bcrypt.__about__.__version__ which was removed upstream).
"""
from __future__ import annotations

import hashlib
import secrets

# --- passlib <-> bcrypt 4.1+ compatibility shim (must run before CryptContext) ---
try:  # pragma: no cover
    import bcrypt

    if not hasattr(bcrypt, "__about__"):
        class _About:  # noqa: D401
            __version__ = getattr(bcrypt, "__version__", "4.x")

        bcrypt.__about__ = _About()  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    pass

from passlib.context import CryptContext  # noqa: E402

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


# --- API keys ---------------------------------------------------------------
API_KEY_PREFIX = "sk_"


def generate_api_key() -> tuple[str, str]:
    """Return (plaintext_key, sha256_hash). Store only the hash; show the key once."""
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    return raw, hash_api_key(raw)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
