"""Spike: false positives on unmarked photos and recovery on marked ones, with the confidence gate.

    python spike/fp_check.py <folder of unmarked jpgs>
"""
import io
import sys
from pathlib import Path

from PIL import Image, ImageEnhance

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.watermark import Watermarker, new_payload  # noqa: E402

wm = Watermarker(Path(__file__).resolve().parent.parent / "models")


def jpg(im, q):
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    return Image.open(b)


EDITS = {
    "as-is": lambda m: m, "jpeg50": lambda m: jpg(m, 50), "scale25": lambda m: m.resize((m.width // 4, m.height // 4)),
    "bright+20": lambda m: ImageEnhance.Brightness(m).enhance(1.2), "gray": lambda m: m.convert("L").convert("RGB"),
    "social": lambda m: jpg(m.resize((1080, round(m.height * 1080 / m.width))), 80),
}
paths = sorted(Path(sys.argv[1]).glob("*.jpg")) + sorted(Path("spike/images").glob("*.jpg"))
fp = checked = 0
hits = {k: 0 for k in EDITS}
for p in paths:
    im = Image.open(p).convert("RGB")
    for v in (im, jpg(im, 60), im.resize((im.width // 2, im.height // 2))):
        checked += 1
        fp += wm.detect(v) is not None
    bits, wid = new_payload("ai_generated")
    m = wm.embed(im, bits)
    for k, fn in EDITS.items():
        d = wm.detect(fn(m))
        hits[k] += bool(d and d.watermark_id == wid)
print(f"false positives: {fp}/{checked} unmarked variants")
for k, v in hits.items():
    print(f"  {k:10s} {v}/{len(paths)}")
