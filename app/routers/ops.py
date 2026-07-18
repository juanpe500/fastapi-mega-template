"""Public ops & SEO endpoints: status page, metrics, sitemap, robots, locale switch."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
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


@router.get("/locale/{code}")
async def set_locale(code: str, next: str = "/"):
    """Switch language and remember it in a cookie."""
    if code not in settings.locale_list:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    target = next if next.startswith("/") and not next.startswith("//") else "/"
    resp = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie("locale", code, max_age=60 * 60 * 24 * 365, samesite="lax", path="/")
    return resp
