"""Recognise uploaded files by their first bytes (never trust the filename or Content-Type)."""
import io
import warnings

from PIL import Image

from app.errors import ApiError

# Formats we can watermark and re-encode.
MARKABLE = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

# Everything /v1/inspect understands: images get every check, the rest get the C2PA check only.
MIME = {
    **MARKABLE,
    "gif": "image/gif",
    "tiff": "image/tiff",
    "avif": "image/avif",
    "heic": "image/heic",
    "mp4": "video/mp4",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "pdf": "application/pdf",
}


def sniff(data: bytes) -> str | None:
    h = data[:32]
    if h.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if h.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if h[:4] == b"RIFF" and h[8:12] == b"WEBP":
        return "webp"
    if h[:4] == b"RIFF" and h[8:12] == b"WAVE":
        return "wav"
    if h[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if h[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if h[:4] == b"%PDF":
        return "pdf"
    if h[:3] == b"ID3" or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0):
        return "mp3"
    if h[4:8] == b"ftyp":
        brand = h[8:12]
        if brand in (b"avif", b"avis"):
            return "avif"
        if brand in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
            return "heic"
        if brand == b"qt  ":
            return "mov"
        return "mp4"
    return None


def open_image(data: bytes, max_megapixels: float) -> Image.Image:
    """Decode an image, refusing pixel bombs before any pixels are decoded."""
    try:
        im = Image.open(io.BytesIO(data))
    except Exception as exc:
        raise ApiError(422, "unreadable_image", "The file could not be decoded as an image.") from exc
    mp = im.width * im.height / 1e6
    if mp > max_megapixels:
        raise ApiError(
            413,
            "image_too_large",
            f"Image is {im.width}x{im.height} ({mp:.1f} MP); the limit is {max_megapixels:g} MP.",
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            im.load()
    except Exception as exc:
        raise ApiError(422, "unreadable_image", "The image data is corrupt or truncated.") from exc
    return im
