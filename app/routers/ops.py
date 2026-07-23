"""Public ops & SEO endpoints: status page, metrics, sitemap, robots, locale switch,
plus the PWA manifest + service worker."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.ops import render_metrics
from app.redis_client import get_redis
from app.security.deps import get_current_user_optional
from app.templating import render

router = APIRouter(tags=["ops"])

# Pages listed in sitemap.xml. Add your own public routes here.
PUBLIC_PATHS = ["/", "/terms", "/privacy", "/refunds", "/contact", "/login", "/register"]

_SW_PATH = Path(__file__).resolve().parent.parent / "static" / "js" / "sw.js"


@router.get("/status")
async def status_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user_optional),
):
    """Human-readable status page (the machine version is /health/ready)."""
    checks: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["Database"] = "operational"
    except Exception:
        checks["Database"] = "degraded"

    redis = get_redis()
    if redis is not None:
        try:
            await redis.ping()
            checks["Cache"] = "operational"
        except Exception:
            checks["Cache"] = "degraded"

    checks["Application"] = "operational"
    all_ok = all(v == "operational" for v in checks.values())
    return render(request, "status.html", {"checks": checks, "all_ok": all_ok}, user=user)


@router.get("/metrics")
async def metrics(request: Request):
    """Prometheus scrape endpoint. Protect with METRICS_TOKEN or your firewall."""
    if not settings.METRICS_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if settings.METRICS_TOKEN:
        supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if supplied != settings.METRICS_TOKEN:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return PlainTextResponse(render_metrics(), media_type="text/plain; version=0.0.4")


@router.get("/robots.txt")
async def robots() -> Response:
    body = "\n".join([
        "User-agent: *",
        "Disallow: /admin",
        "Disallow: /account",
        "Disallow: /files",
        "",
        f"Sitemap: {settings.BASE_URL.rstrip('/')}/sitemap.xml",
        "",
    ])
    return PlainTextResponse(body)


@router.get("/sitemap.xml")
async def sitemap() -> Response:
    base = settings.BASE_URL.rstrip("/")
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in PUBLIC_PATHS)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{urls}</urlset>"
    )
    return Response(content=xml, media_type="application/xml")


@router.get("/manifest.webmanifest")
async def manifest() -> Response:
    """Web app manifest — makes the site installable to the home screen."""
    if not settings.PWA_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    icons = [
        {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png",
         "purpose": "any"},
        {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png",
         "purpose": "any"},
        {"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512",
         "type": "image/png", "purpose": "maskable"},
        {"src": "/static/icons/icon.svg", "sizes": "any", "type": "image/svg+xml"},
    ]
    data = {
        "name": settings.APP_NAME,
        "short_name": settings.PWA_SHORT_NAME or settings.APP_NAME,
        "description": settings.SITE_DESCRIPTION or settings.APP_NAME,
        "start_url": "/?utm_source=pwa",
        "scope": "/",
        "display": settings.PWA_DISPLAY,
        "theme_color": settings.PWA_THEME_COLOR,
        "background_color": settings.PWA_BACKGROUND_COLOR,
        "icons": icons,
    }
    return JSONResponse(data, media_type="application/manifest+json")


@router.get("/sw.js")
async def service_worker() -> Response:
    """Serve the service worker from the root so its scope covers the whole site."""
    if not settings.PWA_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    js = _SW_PATH.read_text(encoding="utf-8").replace(
        "__CACHE_VERSION__", str(settings.DEPLOY_VERSION)
    )
    return Response(
        content=js,
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@router.get("/offline")
async def offline(request: Request, user=Depends(get_current_user_optional)) -> Response:
    """Shown by the service worker when a navigation happens with no network."""
    return render(request, "offline.html", {}, user=user)


@router.get("/locale/{code}")
async def set_locale(code: str, next: str = "/"):
    """Switch language and remember it in a cookie."""
    if code not in settings.locale_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    resp = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie("locale", code, max_age=60 * 60 * 24 * 365, samesite="lax", path="/")
    return resp
