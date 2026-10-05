"""HTTP layer: parse the request, call a service, shape the response. No image logic lives here.

LESSON: these endpoints are plain `def`, not `async def`. FastAPI runs plain functions in a thread
pool, which is what we want for CPU-heavy work (ONNX, image encoding): an `async def` doing that
work would block the event loop and stall every other request.
"""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, Response

from app.engine import Engine, get_engine
from app.errors import ApiError
from app.security import verify_rapidapi
from app.services import fetch as fetch_mod
from app.services.inspect import inspect
from app.services.mark import LAYERS, mark, receipt_json
from app.services.media import MIME, sniff
from app.services.strip_check import strip_check

router = APIRouter(prefix="/v1", dependencies=[Depends(verify_rapidapi)])
EngineDep = Annotated[Engine, Depends(get_engine)]
ERRORS = {
    413: {"description": "File or image too large"},
    415: {"description": "Unsupported file format"},
    422: {"description": "Invalid input"},
    503: {"description": "Busy, retry shortly"},
}


def _read_upload(file: UploadFile, max_mb: int) -> bytes:
    data = file.file.read(max_mb * 2**20 + 1)
    if len(data) > max_mb * 2**20:
        raise ApiError(413, "file_too_large", f"Uploads are limited to {max_mb} MB.")
    if not data:
        raise ApiError(422, "empty_file", "The uploaded file is empty.")
    return data


def _layers(raw: str) -> tuple[str, ...]:
    layers = tuple(dict.fromkeys(x.strip().lower() for x in raw.split(",") if x.strip()))
    bad = [x for x in layers if x not in LAYERS]
    if bad or not layers:
        raise ApiError(422, "invalid_layers", f"layers must be a comma list of: {', '.join(LAYERS)}.")
    return layers


@router.post(
    "/mark",
    tags=["Mark"],
    summary="Mark an AI-generated image (C2PA + invisible watermark + IPTC)",
    response_class=Response,
    responses={
        200: {
            "content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}, "application/json": {}},
            "description": "The marked image (default), or JSON with the image in base64 plus the full receipt "
                           "when `response=json`. Image responses carry `X-Watermark-Id` and `X-Receipt-Id` headers.",
        },
        **ERRORS,
    },
)
def mark_endpoint(
    engine: EngineDep,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP image, up to 25 MB. The megapixel limit is shown by `/health`.")],
    kind: Annotated[Literal["ai_generated", "ai_edited"], Form(
        description="`ai_generated`: wholly made by AI (IPTC trainedAlgorithmicMedia). "
                    "`ai_edited`: a real image changed with AI (IPTC compositeWithTrainedAlgorithmicMedia).")] = "ai_generated",
    generator: Annotated[str | None, Form(max_length=100, description="Name of your AI system, e.g. `MyApp Image v2`. "
                                          "Recorded as the C2PA software agent and XMP CreatorTool.")] = None,
    layers: Annotated[str, Form(description="Comma list: `c2pa`, `watermark`, `iptc`. Default all three. "
                                "The EU Code of Practice expects at least two.")] = "c2pa,watermark,iptc",
    format: Annotated[Literal["jpeg", "png", "webp"] | None, Form(description="Output format. Default: same as input.")] = None,
    quality: Annotated[int, Form(ge=50, le=100, description="JPEG/WebP quality.")] = 92,
    response: Annotated[Literal["image", "json"], Form(description="`image` returns the file; `json` returns base64 + receipt.")] = "image",
):
    data = _read_upload(file, engine.settings.max_upload_mb)
    with engine.slot():
        result = mark(
            data, wm=engine.wm, signer=engine.c2pa, max_megapixels=engine.settings.max_megapixels,
            kind=kind, generator=(generator or "").strip() or None, layers=_layers(layers),
            output_format=format, quality=quality, filename=file.filename,
        )
    if response == "json":
        return JSONResponse(receipt_json(result))
    r = result.receipt
    ext = "jpg" if r["output"]["format"] == "jpeg" else r["output"]["format"]
    headers = {
        "X-Receipt-Id": r["receipt_id"],
        "X-Layers": ",".join(k for k, v in r["layers"].items() if v["applied"]),
        "Content-Disposition": f'inline; filename="marked.{ext}"',
    }
    if wid := r["layers"]["watermark"].get("watermark_id"):
        headers["X-Watermark-Id"] = wid
    return Response(content=result.data, media_type=result.mime, headers=headers)


def _inspect(engine: Engine, data: bytes) -> dict:
    fmt = sniff(data)
    if fmt not in MIME:
        raise ApiError(415, "unsupported_format",
                       "Supported: JPEG, PNG, WebP, GIF, TIFF, AVIF, HEIC, MP4, MOV, MP3, WAV, PDF.")
    with engine.slot():
        return inspect(data, fmt, wm=engine.wm, reader=engine.c2pa, max_megapixels=engine.settings.max_megapixels)


def _fetch(engine: Engine, url: str) -> bytes:
    s = engine.settings
    return fetch_mod.fetch(url, s.max_upload_mb * 2**20, s.fetch_timeout_s, f"MarkLayerInspect/{s.version}")


@router.post(
    "/inspect",
    tags=["Inspect"],
    summary="Report the provenance signals in a file (upload or URL)",
    responses=ERRORS,
)
def inspect_upload(
    engine: EngineDep,
    file: Annotated[UploadFile | None, File(description="The file to inspect (images: all checks; video, audio, PDF: C2PA only).")] = None,
    url: Annotated[str | None, Form(max_length=2048, description="Or a public http(s) URL to download and inspect.")] = None,
) -> dict:
    if (file is None) == (url is None):
        raise ApiError(422, "file_or_url", "Send exactly one of `file` or `url`.")
    data = _read_upload(file, engine.settings.max_upload_mb) if file is not None else _fetch(engine, url)
    return _inspect(engine, data)


@router.get(
    "/inspect",
    tags=["Inspect"],
    summary="Report the provenance signals of a file at a public URL",
    responses=ERRORS,
)
def inspect_url(
    engine: EngineDep,
    url: Annotated[str, Query(max_length=2048, description="Public http(s) URL of an image, video, audio file or PDF.")],
) -> dict:
    return _inspect(engine, _fetch(engine, url))


@router.post(
    "/strip-check",
    tags=["Mark"],
    summary="Test which marking layers survive common edits (compression, resizing, screenshots)",
    responses=ERRORS,
)
def strip_check_endpoint(
    engine: EngineDep,
    file: Annotated[UploadFile, File(description="A marked JPEG, PNG or WebP image.")],
) -> dict:
    data = _read_upload(file, engine.settings.max_upload_mb)
    with engine.slot():
        return strip_check(data, wm=engine.wm, reader=engine.c2pa, max_megapixels=engine.settings.max_megapixels)
