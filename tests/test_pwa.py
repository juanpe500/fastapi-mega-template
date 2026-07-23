"""PWA: manifest, service worker, offline page, and the install meta tags."""
from __future__ import annotations


def test_manifest_is_served_and_valid(client, s):
    r = s.get("/manifest.webmanifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/manifest+json")
    data = r.json()
    assert data["name"]
    assert data["start_url"].startswith("/")
    assert data["display"] in ("standalone", "minimal-ui", "browser")
    sizes = {icon["sizes"] for icon in data["icons"]}
    assert {"192x192", "512x512"} <= sizes
    assert any(i.get("purpose") == "maskable" for i in data["icons"])


def test_service_worker_served_at_root_scope(client, s):
    r = s.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
    # Root scope so it can control the whole origin.
    assert r.headers.get("service-worker-allowed") == "/"
    # The version placeholder must be substituted server-side.
    assert "__CACHE_VERSION__" not in r.text
    assert "addEventListener" in r.text


def test_offline_page_renders(client, s):
    r = s.get("/offline")
    assert r.status_code == 200
    assert "offline" in r.text.lower()


def test_base_html_advertises_pwa(client, s):
    r = s.get("/")
    body = r.text
    assert '<link rel="manifest" href="/manifest.webmanifest">' in body
    assert 'name="theme-color"' in body
    assert 'rel="apple-touch-icon"' in body


def test_icons_are_served(client, s):
    for path in ("/static/icons/icon-192.png", "/static/icons/icon-512.png",
                 "/static/icons/apple-touch-icon.png", "/static/icons/icon.svg"):
        r = s.get(path)
        assert r.status_code == 200, path
