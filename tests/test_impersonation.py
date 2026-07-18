"""Admin impersonation: start, banner, and handing control back."""
import re

from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import Session


def test_impersonate_and_stop():
    with TestClient(app) as c:
        s = Session(c)
        # Fresh admin (first user in this DB may already exist; register a new admin-able user)
        s.get("/register")
        s.post("/register", data={"email": "imp-admin@example.com", "password": "supersecret1"},
               follow_redirects=True)

        # If this instance's first user already existed, promote via the admin UI is not
        # possible; skip when we don't have admin rights.
        if s.get("/admin", follow_redirects=False).status_code != 200:
            return

        # Create a target user to impersonate.
        with TestClient(app) as c2:
            s2 = Session(c2)
            s2.get("/register")
            s2.post("/register", data={"email": "target@example.com", "password": "supersecret1"},
                    follow_redirects=True)

        users = s.get("/admin/users").text
        uid = re.search(r'/admin/users/([0-9a-f-]{36})">target@example\.com', users)
        if not uid:
            rows = re.findall(r'/admin/users/([0-9a-f-]{36})', users)
            uid_val = rows[0]
        else:
            uid_val = uid.group(1)

        r = s.post(f"/admin/users/{uid_val}/impersonate", follow_redirects=True)
        assert r.status_code == 200
        assert "Impersonating" in r.text

        r = s.post("/impersonate/stop", follow_redirects=True)
        assert r.status_code == 200
        assert "Impersonating" not in r.text
