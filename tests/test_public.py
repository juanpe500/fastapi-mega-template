"""Public pages, health checks and error handling."""


def test_health(s):
    r = s.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_reports_database(s):
    r = s.get("/health/ready")
    assert r.status_code == 200
    assert r.json()["checks"]["database"] == "ok"


def test_public_pages_render(s):
    for path in ["/", "/login", "/register", "/terms", "/privacy", "/refunds", "/contact"]:
        assert s.get(path).status_code == 200, path


def test_unknown_path_returns_404_page(s):
    r = s.get("/definitely-not-a-page")
    assert r.status_code == 404
    assert "404" in r.text


def test_security_headers_present(s):
    r = s.get("/")
    assert "Content-Security-Policy" in r.headers
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_static_assets_are_immutably_cached(s):
    r = s.get("/static/css/app.css")
    assert r.status_code == 200
    assert "immutable" in r.headers.get("Cache-Control", "")
