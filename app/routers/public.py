"""The free checker page (GET /), its endpoint (POST /public/check), and what search engines need.

Public on purpose: no RapidAPI key, so anyone can try MarkLayer's inspection on one image at a
time. Kept out of the OpenAPI schema so it doesn't show up as an endpoint in the RapidAPI listing,
and rate-limited per IP so scripts can't use it as a free API. Uploads only: no URL fetching here.
"""
import html
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from app.config import Settings, get_settings
from app.engine import Engine, get_engine
from app.ratelimit import RateLimiter
from app.routers.v1 import _inspect, _read_upload

router = APIRouter(include_in_schema=False)
STATIC = Path(__file__).resolve().parent.parent / "static"
PAGE_UPDATED = "2026-10-07"  # sitemap <lastmod>: bump when the page content changes
CACHE = {"Cache-Control": "public, max-age=300"}
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_limiter(request: Request) -> RateLimiter:
    return request.app.state.public_limiter


@lru_cache
def _page(base_url: str, google: str, bing: str) -> str:
    tags = "".join(
        f'<meta name="{name}" content="{html.escape(value, quote=True)}">\n'
        for name, value in (("google-site-verification", google), ("msvalidate.01", bing)) if value
    )
    page = (STATIC / "check.html").read_text(encoding="utf-8")
    return page.replace("{{VERIFY_TAGS}}", tags).replace("{{BASE_URL}}", base_url)


# HEAD too: link checkers and uptime monitors often use it, and a 405 there looks like a broken site.
@router.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def checker_page(settings: SettingsDep) -> HTMLResponse:
    page = _page(settings.public_base_url.rstrip("/"), settings.google_site_verification.strip(),
                 settings.bing_site_verification.strip())
    return HTMLResponse(page, headers=CACHE)


@router.api_route("/robots.txt", methods=["GET", "HEAD"], response_class=PlainTextResponse)
def robots(settings: SettingsDep) -> PlainTextResponse:
    base = settings.public_base_url.rstrip("/")
    # The API and the check endpoint are machine interfaces, not pages: keep crawlers on the site.
    body = (
        "User-agent: *\n"
        "Allow: /$\n"
        "Disallow: /v1/\n"
        "Disallow: /public/\n"
        "Disallow: /docs\n"
        "Disallow: /redoc\n"
        "Disallow: /openapi.json\n"
        f"\nSitemap: {base}/sitemap.xml\n"
    )
    return PlainTextResponse(body, headers=CACHE)


@router.api_route("/sitemap.xml", methods=["GET", "HEAD"])
def sitemap(settings: SettingsDep) -> Response:
    base = settings.public_base_url.rstrip("/")
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{base}/</loc><lastmod>{PAGE_UPDATED}</lastmod></url>\n"
        "</urlset>\n"
    )
    return Response(body, media_type="application/xml", headers=CACHE)


@router.api_route("/og.png", methods=["GET", "HEAD"])
def share_image() -> FileResponse:
    return FileResponse(STATIC / "og.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/public/check")
def public_check(
    request: Request,
    engine: Annotated[Engine, Depends(get_engine)],
    limiter: Annotated[RateLimiter, Depends(get_limiter)],
    file: Annotated[UploadFile, File()],
) -> dict:
    # Behind Render's proxy, uvicorn --proxy-headers puts the visitor's IP in request.client.
    limiter.check(request.client.host if request.client else "unknown")
    data = _read_upload(file, engine.settings.public_max_upload_mb)
    return _inspect(engine, data)
