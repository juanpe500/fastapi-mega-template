"""2FA + recovery codes, storage uploads, tickets, credits, audit and settings."""
import io
import re

import pyotp


def test_2fa_qr_and_recovery_codes(s, admin):
    page = s.get("/account/2fa").text
    assert "<svg" in page  # QR renders inline, no external request
    secret = re.search(r"<pre>([A-Z2-7]{16,})</pre>", page).group(1)

    r = s.post("/account/2fa/enable", data={"code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200
    codes = re.findall(r"\b([0-9a-f]{5}-[0-9a-f]{5})\b", r.text)
    assert len(codes) == 10

    # A recovery code logs in, and only once.
    s.post("/logout", follow_redirects=False)
    s.get("/login")
    r = s.post("/login", data={"email": admin["email"], "password": admin["password"],
                               "totp_code": codes[0]}, follow_redirects=True)
    assert admin["email"] in r.text

    s.post("/logout", follow_redirects=False)
    s.get("/login")
    r = s.post("/login", data={"email": admin["email"], "password": admin["password"],
                               "totp_code": codes[0]}, follow_redirects=True)
    assert "Invalid 2FA or recovery code" in r.text

    # Log back in with a fresh code and turn 2FA off for later tests.
    r = s.post("/login", data={"email": admin["email"], "password": admin["password"],
                               "totp_code": codes[1]}, follow_redirects=True)
    assert admin["email"] in r.text
    s.post("/account/2fa/disable", follow_redirects=True)


def test_avatar_upload_to_public_storage(s, admin):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = s.post("/account/avatar",
               files={"file": ("a.png", io.BytesIO(png), "image/png")}, follow_redirects=True)
    assert r.status_code == 200
    assert "/static/uploads/avatars/" in r.text


def test_ticket_with_private_attachment(s, admin):
    r = s.post("/account/tickets",
               data={"subject": "Help", "category": "general", "body": "broken"},
               files={"attachment": ("note.txt", io.BytesIO(b"hello"), "text/plain")},
               follow_redirects=True)
    assert r.status_code == 200
    assert "Attachment" in r.text

    tid = re.search(r"/account/tickets/([0-9a-f-]{36})", s.get("/account/tickets").text).group(1)
    mid = re.search(rf"/account/tickets/{tid}/attachments/([0-9a-f-]{{36}})", r.text).group(1)

    # Private file is reachable only through the signed link.
    r = s.get(f"/account/tickets/{tid}/attachments/{mid}", follow_redirects=True)
    assert r.status_code == 200
    assert r.content == b"hello"


def test_admin_credit_adjustment_and_audit(s, admin):
    users_page = s.get("/admin/users").text
    uid = re.search(r"/admin/users/([0-9a-f-]{36})", users_page).group(1)

    s.post(f"/admin/users/{uid}/credits", data={"amount": "25", "note": "test grant"},
           follow_redirects=True)
    detail = s.get(f"/admin/users/{uid}").text
    assert "test grant" in detail

    audit_page = s.get("/admin/audit").text
    assert "admin.credit_adjust" in audit_page
    assert "user.login" in audit_page


def test_admin_settings_roundtrip(s, admin):
    # Match the table row specifically — the "add setting" form uses the same
    # key as placeholder text, so a bare substring check would always pass.
    row = "<code>signups_paused</code>"
    s.post("/admin/settings", data={"key": "signups_paused", "value": "true",
                                    "value_type": "bool", "description": "pause signups"},
           follow_redirects=True)
    assert row in s.get("/admin/settings").text
    s.post("/admin/settings/signups_paused/delete", follow_redirects=True)
    assert row not in s.get("/admin/settings").text


def test_staff_reply_to_ticket(s, admin):
    tid = re.search(r"/account/tickets/([0-9a-f-]{36})", s.get("/account/tickets").text).group(1)
    r = s.post(f"/admin/tickets/{tid}/reply", data={"body": "staff here"}, follow_redirects=True)
    assert "staff here" in r.text


def test_stripe_webhook_disabled_without_keys(s):
    assert s.post("/billing/webhook", content=b"{}").status_code == 503
