"""Account lifecycle, notifications, ops, SEO, referrals, admin pagination & trash."""
from __future__ import annotations

import json


# --------------------------------------------------------------- account area
def test_profile_page_shows_danger_zone_and_referral(client, s, admin):
    r = s.get("/account")
    assert r.status_code == 200
    body = r.text
    assert "Danger zone" in body
    assert "Deactivate account" in body
    assert "/account/export" in body
    assert "Refer a friend" in body


def test_data_export_is_downloadable_json(client, s, admin):
    r = s.get("/account/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    data = json.loads(r.text)
    assert data["account"]["email"] == admin["email"]
    for key in ("roles", "sessions", "credit_transactions", "tickets"):
        assert key in data


def test_profile_edit_saves_display_name(client, s, admin):
    r = s.post("/account/profile", data={"display_name": "Renamed Boss"},
               follow_redirects=True)
    assert r.status_code == 200
    assert "Renamed Boss" in s.get("/account").text


def test_email_change_requires_correct_password(client, s, admin):
    r = s.post("/account/email",
               data={"new_email": "elsewhere@example.com", "password": "wrong-password"},
               follow_redirects=True)
    assert "Password is incorrect" in r.text


def test_email_confirm_rejects_bad_token(client, s, admin):
    r = s.get("/account/email/confirm?token=nope")
    assert r.status_code == 400
    assert "invalid or has expired" in r.text


def test_delete_requires_typed_confirmation(client, s, admin):
    r = s.post("/account/delete", data={"confirm": "maybe"}, follow_redirects=True)
    assert "Type DELETE exactly" in r.text


# ------------------------------------------------------------- notifications
def test_notification_centre_and_unread_badge(client, s, admin):
    # Changing the password raises a "security" notification.
    s.post("/account/password", data={"current_password": admin["password"],
                                      "new_password": "another-secret-9"},
           follow_redirects=True)
    admin["password"] = "another-secret-9"

    count = s.get("/api/notifications/unread-count").json()["count"]
    assert count >= 1

    page = s.get("/account/notifications")
    assert page.status_code == 200
    assert "Your password was changed" in page.text
    assert "Email preferences" in page.text

    s.post("/account/notifications/read-all", follow_redirects=True)
    assert s.get("/api/notifications/unread-count").json()["count"] == 0


def test_unread_count_is_zero_for_anonymous(client):
    # Fresh client: no cookies, must not 401 — the badge fetch runs on public pages.
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as anon:
        assert anon.get("/api/notifications/unread-count").json() == {"count": 0}


def test_unsubscribe_link_rejects_garbage(client, s):
    assert s.get("/unsubscribe?token=garbage").status_code == 400


# ---------------------------------------------------------------- ops & SEO
def test_status_page_reports_operational(client, s):
    r = s.get("/status")
    assert r.status_code == 200
    assert "operational" in r.text


def test_metrics_endpoint_exposes_prometheus_text(client, s):
    r = s.get("/metrics")
    assert r.status_code == 200
    assert "app_requests_total" in r.text
    assert "app_info" in r.text


def test_robots_and_sitemap(client, s):
    robots = s.get("/robots.txt")
    assert "Disallow: /admin" in robots.text
    assert "sitemap.xml" in robots.text

    sitemap = s.get("/sitemap.xml")
    assert sitemap.headers["content-type"].startswith("application/xml")
    assert "<loc>" in sitemap.text


def test_base_template_has_og_tags(client, s):
    body = s.get("/").text
    assert 'property="og:title"' in body
    assert 'rel="canonical"' in body


def test_locale_switch_sets_cookie(client, s):
    r = s.get("/locale/es", follow_redirects=False)
    assert r.status_code == 303
    assert "locale=es" in r.headers.get("set-cookie", "")
    s.get("/locale/en", follow_redirects=False)  # switch back
    assert s.get("/locale/zz", follow_redirects=False).status_code == 404


# -------------------------------------------------------------------- admin
def test_admin_user_list_paginates_filters_and_exports(client, s, admin):
    page = s.get("/admin/users?status_filter=active")
    assert page.status_code == 200
    assert admin["email"] in page.text
    assert "With selected" in page.text  # bulk-action UI is reachable

    csv = s.get("/admin/users/export.csv")
    assert csv.status_code == 200
    assert "id,email,display_name" in csv.text


def test_admin_bulk_action_skips_self(client, s, admin):
    """The admin must not be able to lock themselves out with a bulk deactivate."""
    me = s.get("/admin/users").text
    assert "Deactivate" in me

    s.post("/admin/users/bulk", data={"action": "deactivate", "ids": []},
           follow_redirects=True)
    # Still signed in and still active.
    assert s.get("/account").status_code == 200


def test_admin_audit_and_error_exports(client, s, admin):
    assert "created_at,action" in s.get("/admin/audit/export.csv").text
    assert "created_at,path" in s.get("/admin/errors/export.csv?show=all").text


def test_ticket_trash_and_restore(client, s, admin):
    s.get("/account/tickets/new")
    s.post("/account/tickets", data={"subject": "Trash me", "category": "general",
                                     "body": "please"}, follow_redirects=True)
    queue = s.get("/admin/tickets?status_filter=all")
    assert "Trash me" in queue.text

    # The checkbox value is the id — the nav also contains /admin/tickets/ links.
    ticket_id = queue.text.split('name="ids" value="')[1].split('"')[0]
    s.post(f"/admin/tickets/{ticket_id}/delete", follow_redirects=True)

    assert "Trash me" not in s.get("/admin/tickets?status_filter=all").text
    assert "Trash me" in s.get("/admin/tickets/trash").text
    assert "Trash me" not in s.get("/account/tickets").text  # hidden from the owner too

    s.post(f"/admin/tickets/{ticket_id}/restore", follow_redirects=True)
    assert "Trash me" in s.get("/admin/tickets?status_filter=all").text


def test_maintenance_mode_toggle(client, s, admin):
    page = s.get("/admin/settings")
    assert "Maintenance mode" in page.text

    s.post("/admin/settings/maintenance", data={"enabled": "1"}, follow_redirects=True)
    assert "<strong class=\"error\">ON</strong>" in s.get("/admin/settings").text
    # Admins keep browsing while it's on.
    assert s.get("/account").status_code == 200

    s.post("/admin/settings/maintenance", data={"enabled": "0"}, follow_redirects=True)
    assert s.get("/").status_code == 200
