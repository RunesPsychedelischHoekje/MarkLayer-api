"""Application entry point: `fastapi dev app/main.py`."""
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from app.config import get_settings
from app.engine import Engine
from app.errors import ApiError, api_error_handler, validation_error_handler
from app.routers import v1

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not hasattr(app.state, "engine"):  # tests may install their own
        app.state.engine = Engine(settings)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    lifespan=lifespan,
    description=(
        "**MarkLayer**: machine-readable marking for AI-generated images, built for the EU AI Act "
        "(Article 50(2)) and California's AI Transparency Act.\n\n"
        "- `POST /v1/mark` adds three open-standard layers in one call: a signed **C2PA** manifest, an invisible "
        "**TrustMark** watermark that survives compression and resizing, and the **IPTC** `DigitalSourceType` "
        "that platforms read for \"AI info\" labels. You get a compliance receipt back.\n"
        "- `POST /v1/inspect` reports the provenance evidence in any image, video, audio file or PDF: C2PA "
        "validity and signer, watermarks, IPTC fields and generator traces (Stable Diffusion, ComfyUI, "
        "Midjourney...), with a verdict and label text in 10 EU languages.\n"
        "- `POST /v1/strip-check` shows which layers survive real-world edits.\n\n"
        "Technical marking only: not legal advice or a certificate of compliance."
    ),
)
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.include_router(v1.router)


@app.middleware("http")
async def add_process_time(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-Ms"] = f"{(time.perf_counter() - start) * 1000:.2f}"
    return response


@app.get("/health", tags=["Meta"], summary="Liveness check")
def health() -> dict:
    # Not behind the RapidAPI check, so your host's health checks can reach it.
    engine: Engine | None = getattr(app.state, "engine", None)
    return {
        "status": "ok",
        "version": settings.version,
        "trust_lists": engine.c2pa.trust_lists_loaded if engine else [],
        "signer_trust_list": engine.c2pa.own_trust_list if engine else None,
        "limits": {"max_upload_mb": settings.max_upload_mb, "max_megapixels": settings.max_megapixels},
    }
