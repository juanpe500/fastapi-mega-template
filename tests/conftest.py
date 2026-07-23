"""Shared pytest fixtures.

Each test module gets a fresh SQLite database file so tests are isolated and
runnable in any order. The env vars are set before the app is imported so
settings pick them up.
"""
from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest

# Configure the app for testing *before* importing it.
_TMP = Path(tempfile.gettempdir()) / f"fastapi_template_test_{uuid.uuid4().hex}.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP.as_posix()}"
os.environ["SECRET_KEY"] = "test-secret-key"
os.environ["ENV"] = "dev"
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["RATE_LIMIT_ENABLED"] = "0"  # don't throttle the test suite
os.environ["STORAGE_BACKEND"] = "local"
os.environ["HIBP_ENABLED"] = "0"  # no network calls from the suite
os.environ["EMAIL_WEBHOOK_SECRET"] = "test-webhook-secret"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    """TestClient with lifespan run (creates tables + seeds RBAC)."""
    with TestClient(app) as c:
        yield c
    _TMP.unlink(missing_ok=True)


class Session:
    """Thin wrapper that attaches the CSRF token to writes."""

    def __init__(self, client):
        self.c = client

    @property
    def csrf(self) -> str:
        for cookie in self.c.cookies.jar:
            if cookie.name == "csrf" and "testserver" in (cookie.domain or ""):
                return cookie.value
        for cookie in self.c.cookies.jar:
            if cookie.name == "csrf":
                return cookie.value
        return ""

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, **kw):
        headers = kw.pop("headers", {}) or {}
        headers.setdefault("X-CSRF-Token", self.csrf)
        return self.c.post(url, headers=headers, **kw)


@pytest.fixture(scope="session")
def s(client):
    """Session helper (CSRF-aware)."""
    return Session(client)


@pytest.fixture(scope="session")
def admin(client, s):
    """Registers the first user, who becomes admin, and stays logged in."""
    s.get("/register")
    email = "admin@example.com"
    r = s.post("/register", data={"email": email, "password": "supersecret1",
                                  "display_name": "Boss"}, follow_redirects=True)
    assert r.status_code == 200, r.text[:500]
    return {"email": email, "password": "supersecret1"}
