"""Spike: does our ONNX TrustMark survive real-world edits, and does official TrustMark decode it?

Run: .venv/Scripts/python spike/robustness.py
"""
import io
import secrets
import sys
import time
from pathlib import Path

import numpy as np
import psutil
from PIL import Image, ImageEnhance

sys.path.insert(0, str(Path(__file__).parent))
from tm_onnx import TrustMarkOnnx  # noqa: E402

proc = psutil.Process()
rss0 = proc.memory_info().rss
tm = TrustMarkOnnx()
rss_loaded = proc.memory_info().rss


def jpeg(im, q):
    b = io.BytesIO()
    im.save(b, "JPEG", quality=q)
    return Image.open(io.BytesIO(b.getvalue()))


def webp(im, q):
    b = io.BytesIO()
    im.save(b, "WEBP", quality=q)
    return Image.open(io.BytesIO(b.getvalue()))


def scale(im, f):
    return im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.BICUBIC)


def width(im, w):
    return im.resize((w, round(im.height * w / im.width)), Image.BICUBIC)


def crop(im, f):
    dx, dy = int(im.width * f), int(im.height * f)
    return im.crop((dx, dy, im.width - dx, im.height - dy))


TRANSFORMS = {
    "none": lambda im: im,
    "jpeg90": lambda im: jpeg(im, 90),
    "jpeg75": lambda im: jpeg(im, 75),
    "jpeg50": lambda im: jpeg(im, 50),
    "webp80": lambda im: webp(im, 80),
    "scale50%": lambda im: scale(im, 0.5),
    "scale25%": lambda im: scale(im, 0.25),
    "social(1080w+jpeg80)": lambda im: jpeg(width(im, 1080), 80),
    "crop5%": lambda im: crop(im, 0.05),
    "crop15%": lambda im: crop(im, 0.15),
    "bright+20%": lambda im: ImageEnhance.Brightness(im).enhance(1.2),
    "contrast+20%": lambda im: ImageEnhance.Contrast(im).enhance(1.2),
    "grayscale": lambda im: im.convert("L").convert("RGB"),
    "screenshot(scale75%+png)": lambda im: scale(im, 0.75),
}

results = {k: 0 for k in TRANSFORMS}
false_pos = 0
psnrs, enc_ms, dec_ms = [], [], []
imgs = sorted((Path(__file__).parent / "images").glob("*.jpg"))
peak = rss_loaded
for p in imgs:
    orig = Image.open(p).convert("RGB")
    if tm.decode(orig)[1]:
        false_pos += 1
    bits = format(secrets.randbits(61), "061b")
    t = time.perf_counter()
    marked = tm.encode(orig, bits)
    enc_ms.append((time.perf_counter() - t) * 1000)
    peak = max(peak, proc.memory_info().rss)
    mse = np.mean((np.asarray(orig, dtype=np.float64) - np.asarray(marked, dtype=np.float64)) ** 2)
    psnrs.append(10 * np.log10(255**2 / mse))
    for name, fn in TRANSFORMS.items():
        t = time.perf_counter()
        payload, ok, _ = tm.decode(fn(marked))
        dec_ms.append((time.perf_counter() - t) * 1000)
        if ok and payload == bits:
            results[name] += 1
    marked.save(Path(__file__).parent / "out" / f"marked_{p.stem}.png")

n = len(imgs)
print(f"images: {n}   false positives on unmarked originals: {false_pos}/{n}")
print(f"PSNR mean {np.mean(psnrs):.1f} dB (min {np.min(psnrs):.1f})")
print(f"encode {np.mean(enc_ms):.0f} ms/img, decode {np.mean(dec_ms):.0f} ms/img")
print(f"RSS: base {rss0/2**20:.0f} MB, models loaded {rss_loaded/2**20:.0f} MB, peak {peak/2**20:.0f} MB")
for k, v in results.items():
    print(f"  {k:28s} {v}/{n}")
