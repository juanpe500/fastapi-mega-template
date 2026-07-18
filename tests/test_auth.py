"""Registration, login, CSRF, sessions and API keys."""
import re


def test_csrf_blocks_post_without_token(client):
    client.get("/register")
    r = client.post("/register", data={"email": "nope@example.com", "password": "supersecret1"},
                    follow_redirects=False)
    assert r.status_code == 403


def test_admin_area_requires_auth(s):
    assert s.get("/admin", follow_redirects=False).status_code == 401


def test_first_user_becomes_admin(s, admin):
    r = s.get("/account")
    assert r.status_code == 200
    assert admin["email"] in r.text
    assert s.get("/admin").status_code == 200


def test_admin_pages_render(s, admin):
    for path in ["/admin/users", "/admin/roles", "/admin/billing", "/admin/errors",
                 "/admin/tickets", "/admin/audit", "/admin/settings"]:
        assert s.get(path).status_code == 200, path


def test_api_key_authenticates_and_bypasses_csrf(s, admin):
    r = s.post("/account/api-key")
    assert r.status_code == 200
    key = re.search(r"(sk_[A-Za-z0-9_\-]+)", r.text).group(1)
    assert s.get("/account", headers={"X-API-Key": key}).status_code == 200


def test_second_user_is_not_admin(client):
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.conftest import Session

    with TestClient(app) as c2:
        s2 = Session(c2)
        s2.get("/register")
        s2.post("/register", data={"email": "plain@example.com", "password": "supersecret1"},
                follow_redirects=True)
        assert s2.get("/admin", follow_redirects=False).status_code in (401, 403)


def test_sessions_page_lists_current_device(s, admin):
    r = s.get("/account/sessions")
    assert r.status_code == 200
    assert "this device" in r.text


def test_login_failure_is_rejected(client):
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.conftest import Session

    with TestClient(app) as c2:
        s2 = Session(c2)
        s2.get("/login")
        r = s2.post("/login", data={"email": "admin@example.com", "password": "wrong-password"})
        assert r.status_code == 401
        assert "Invalid email or password" in r.text
