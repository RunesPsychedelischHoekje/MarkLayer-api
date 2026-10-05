"""POST /v1/mark: add up to three machine-readable layers that say "AI made this".

Order matters: watermark the pixels first, then encode the file with IPTC XMP, then sign with C2PA
last, because the C2PA signature covers the final bytes (any change after signing invalidates it).
"""
import base64
import datetime as dt
import hashlib
import io
import uuid
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageOps

from app.errors import ApiError
from app.services import metadata
from app.services.c2pa_io import IPTC_DST, C2pa
from app.services.media import MARKABLE, open_image, sniff
from app.services.watermark import ALG, SCHEMA, Watermarker, new_payload

DST_FOR_KIND = {"ai_generated": "trainedAlgorithmicMedia", "ai_edited": "compositeWithTrainedAlgorithmicMedia"}
LAYERS = ("c2pa", "watermark", "iptc")


@dataclass
class MarkResult:
    data: bytes
    mime: str
    receipt: dict


def mark(
    data: bytes,
    *,
    wm: Watermarker,
    signer: C2pa,
    max_megapixels: float,
    kind: str,
    generator: str | None,
    layers: tuple[str, ...],
    output_format: str | None,
    quality: int,
    filename: str | None,
) -> MarkResult:
    fmt_in = sniff(data)
    if fmt_in not in MARKABLE:
        raise ApiError(415, "unsupported_format", "Marking supports JPEG, PNG and WebP images.")
    fmt_out = output_format or fmt_in
    had_c2pa = signer.read(data, MARKABLE[fmt_in]) is not None
    src = open_image(data, max_megapixels)
    width, height = src.size

    # Normalise orientation and colour mode. Keep alpha aside: the watermark lives in RGB.
    # exif_transpose also resets the EXIF orientation tag, so take metadata from its result.
    # (in_place and the mode checks avoid full-size copies: each one is 50 MB at 17 MP.)
    ImageOps.exif_transpose(src, in_place=True)
    im = src
    src_info = dict(im.info)
    alpha = None
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        alpha = im.getchannel("A")
    if im.mode != "RGB":
        im = im.convert("RGB")
    del src

    dst = DST_FOR_KIND[kind]
    receipt_layers: dict[str, dict] = {}
    watermark_id = None
    soft_binding = None
    if "watermark" in layers:
        bits, watermark_id = new_payload(kind)
        soft_binding = f"{SCHEMA}*{bits}"
        marked = wm.embed(im, bits)
        psnr = _psnr(im, marked)
        im = marked
        receipt_layers["watermark"] = {
            "applied": True, "algorithm": ALG, "watermark_id": watermark_id,
            "payload_bits": bits, "psnr_db": psnr,
        }
    else:
        receipt_layers["watermark"] = {"applied": False}

    if alpha is not None and fmt_out != "jpeg":
        im.putalpha(alpha)

    xmp = metadata.xmp_packet(dst, generator) if "iptc" in layers else None
    encoded = _encode(im, fmt_out, quality, xmp, src_info)
    receipt_layers["iptc"] = (
        {"applied": True, "field": "Iptc4xmpExt:DigitalSourceType", "value": IPTC_DST + dst}
        if xmp else {"applied": False}
    )

    if "c2pa" in layers:
        title = filename or f"image.{'jpg' if fmt_out == 'jpeg' else fmt_out}"
        encoded = signer.sign(encoded, MARKABLE[fmt_out], digital_source_type=dst, generator=generator,
                              soft_binding=soft_binding, title=title)
        receipt_layers["c2pa"] = {
            "applied": True,
            "signer": signer.identity.issuer,
            "signer_trust_list": signer.own_trust_list,
            "development_identity": signer.identity.ephemeral,
            "action": "c2pa.created",
            "digital_source_type": IPTC_DST + dst,
            "soft_binding": soft_binding,
        }
    else:
        receipt_layers["c2pa"] = {"applied": False}

    receipt = {
        "receipt_id": str(uuid.uuid4()),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "kind": kind,
        "generator": generator,
        "input": {
            "format": fmt_in, "width": width, "height": height,
            "sha256": hashlib.sha256(data).hexdigest(), "had_c2pa_manifest": had_c2pa,
        },
        "output": {
            "format": fmt_out, "mime": MARKABLE[fmt_out], "bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        },
        "layers": receipt_layers,
        "notes": _notes(had_c2pa, fmt_in, fmt_out, alpha is not None, signer),
    }
    return MarkResult(encoded, MARKABLE[fmt_out], receipt)


def _encode(im: Image.Image, fmt: str, quality: int, xmp: bytes | None, src_info: dict) -> bytes:
    buf = io.BytesIO()
    kw: dict = {}
    if icc := src_info.get("icc_profile"):
        kw["icc_profile"] = icc
    if exif := src_info.get("exif"):
        kw["exif"] = exif
    if fmt == "jpeg":
        if im.mode != "RGB":
            im = im.convert("RGB")
        im.save(buf, "JPEG", quality=quality, xmp=xmp or b"", **kw)
    elif fmt == "webp":
        im.save(buf, "WEBP", quality=quality, method=4, xmp=xmp or b"", **kw)
    else:
        im.save(buf, "PNG", pnginfo=metadata.png_info_with_xmp(src_info, xmp), compress_level=6, **kw)
    return buf.getvalue()


def _psnr(a: Image.Image, b: Image.Image) -> float:
    """PSNR in row strips, so a 17 MP image never needs a full-size float copy."""
    x, y = np.asarray(a), np.asarray(b)
    sse = 0.0
    for s in range(0, x.shape[0], 256):
        d = x[s:s + 256].astype(np.int16) - y[s:s + 256].astype(np.int16)
        sse += float(np.square(d, dtype=np.int64).sum())
    mse = sse / x.size
    return round(99.0 if mse == 0 else 10 * np.log10(255**2 / mse), 1)


def _notes(had_c2pa: bool, fmt_in: str, fmt_out: str, had_alpha: bool, signer: C2pa) -> list[str]:
    notes = []
    if had_c2pa:
        notes.append("The input carried a C2PA manifest; re-encoding replaced it with a new one.")
    if had_alpha and fmt_out == "jpeg":
        notes.append("JPEG has no transparency: the alpha channel was dropped.")
    if signer.identity.ephemeral:
        notes.append("Signed with a temporary development identity: configure SIGNING_CERT_PEM for production.")
    return notes


def receipt_json(result: MarkResult) -> dict:
    return {"image_base64": base64.b64encode(result.data).decode(), "mime": result.mime, "receipt": result.receipt}
