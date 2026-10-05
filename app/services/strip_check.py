"""POST /v1/strip-check: put a marked image through common real-world edits and report which layers survive.

Expect the two metadata layers (C2PA, IPTC) to vanish on every re-encode: social networks and
screenshots do the same. The watermark is the layer meant to survive, and this shows how well.
"""
import io
from collections.abc import Callable

from PIL import Image, ImageEnhance

from app.services import metadata
from app.services.c2pa_io import C2pa
from app.services.media import MARKABLE, open_image, sniff
from app.services.watermark import Watermarker
from app.errors import ApiError


def _save(im: Image.Image, fmt: str, **kw) -> bytes:
    b = io.BytesIO()
    im.save(b, fmt, **kw)
    return b.getvalue()


def _width(im: Image.Image, w: int) -> Image.Image:
    if im.width <= w:
        return im
    return im.resize((w, round(im.height * w / im.width)), Image.BICUBIC)


def _scale(im: Image.Image, f: float) -> Image.Image:
    return im.resize((max(1, round(im.width * f)), max(1, round(im.height * f))), Image.BICUBIC)


def _crop(im: Image.Image, f: float) -> Image.Image:
    dx, dy = round(im.width * f), round(im.height * f)
    return im.crop((dx, dy, im.width - dx, im.height - dy))


# name -> (what it simulates, transform producing new file bytes)
TRANSFORMS: dict[str, tuple[str, Callable[[Image.Image], bytes]]] = {
    "jpeg_q85": ("Re-saved as JPEG quality 85", lambda im: _save(im, "JPEG", quality=85)),
    "jpeg_q60": ("Heavy JPEG compression (quality 60)", lambda im: _save(im, "JPEG", quality=60)),
    "webp_q75": ("Converted to WebP quality 75", lambda im: _save(im, "WEBP", quality=75)),
    "social_1080": ("Social upload: resized to 1080 px wide, JPEG 80", lambda im: _save(_width(im, 1080), "JPEG", quality=80)),
    "thumbnail_25": ("Downscaled to 25%", lambda im: _save(_scale(im, 0.25), "PNG")),
    "screenshot": ("Screenshot-like: 75% scale, PNG, metadata gone", lambda im: _save(_scale(im, 0.75), "PNG")),
    "crop_5": ("Cropped 5% from every edge", lambda im: _save(_crop(im, 0.05), "JPEG", quality=90)),
    "brightness_15": ("Brightness +15%", lambda im: _save(ImageEnhance.Brightness(im).enhance(1.15), "JPEG", quality=90)),
    "grayscale": ("Converted to grayscale", lambda im: _save(im.convert("L").convert("RGB"), "JPEG", quality=90)),
}


def strip_check(data: bytes, *, wm: Watermarker, reader: C2pa, max_megapixels: float) -> dict:
    fmt = sniff(data)
    if fmt not in MARKABLE:
        raise ApiError(415, "unsupported_format", "strip-check accepts JPEG, PNG and WebP images.")
    rgb = open_image(data, max_megapixels).convert("RGB")

    rows = [{"edit": "original", "description": "The file as uploaded", **_layers(data, fmt, wm, reader)}]
    for name, (desc, fn) in TRANSFORMS.items():
        out = fn(rgb)
        rows.append({"edit": name, "description": desc, **_layers(out, sniff(out), wm, reader)})

    edits = rows[1:]
    survived = sum(r["watermark"] for r in edits)
    return {
        "original_layers": {k: rows[0][k] for k in ("c2pa", "iptc", "watermark")},
        "watermark_survival": f"{survived}/{len(edits)}",
        "results": rows,
        "note": "C2PA and IPTC metadata are expected to disappear on any re-encode. The watermark is the durable layer.",
    }


def _layers(data: bytes, fmt: str, wm: Watermarker, reader: C2pa) -> dict:
    c2pa_store = reader.read(data, MARKABLE[fmt])
    dst, _ = metadata.iptc_signals(data)
    found = wm.detect(Image.open(io.BytesIO(data)))
    return {
        "c2pa": bool(c2pa_store) and "error" not in c2pa_store,
        "iptc": dst is not None,
        "watermark": found is not None,
        "watermark_id": found.watermark_id if found else None,
    }
