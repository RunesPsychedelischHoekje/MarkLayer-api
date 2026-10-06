"""The free checker page (GET /) and its endpoint (POST /public/check).

Public on purpose: no RapidAPI key, so anyone can try MarkLayer's inspection on one image at a
time. Kept out of the OpenAPI schema so it doesn't show up as an endpoint in the RapidAPI listing,
and rate-limited per IP so scripts can't use it as a free API. Uploads only: no URL fetching here.
"""
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import HTMLResponse

from app.engine import Engine, get_engine
from app.ratelimit import RateLimiter
from app.routers.v1 import _inspect, _read_upload

router = APIRouter(include_in_schema=False)
PAGE = Path(__file__).resolve().parent.parent / "static" / "check.html"


def get_limiter(request: Request) -> RateLimiter:
    return request.app.state.public_limiter


@router.get("/", response_class=HTMLResponse)
def checker_page() -> HTMLResponse:
    return HTMLResponse(PAGE.read_text(encoding="utf-8"), headers={"Cache-Control": "public, max-age=300"})


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
