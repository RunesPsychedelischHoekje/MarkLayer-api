"""Render the 1200x630 share image (og:image) for the checker page into app/static/og.png.

    python scripts/make_og_image.py

Needs a bold sans-serif TTF; defaults to Segoe UI on Windows, override with OG_FONT_DIR.
"""
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = Path(os.environ.get("OG_FONT_DIR", r"C:\Windows\Fonts"))
W, H = 1200, 630
BG, INDIGO, LAVENDER, TEXT, MUTED, AMBER = "#11132a", "#4f46e5", "#94a3f8", "#f3f4ff", "#b4b9d8", "#f2b54a"


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / name), size)


def main() -> None:
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    # Logo: two stacked rounded squares with a check, as on the page.
    d.rounded_rectangle((72, 92, 72 + 54, 92 + 54), 12, fill=LAVENDER)
    d.rounded_rectangle((90, 74, 90 + 54, 74 + 54), 12, fill=INDIGO)
    d.line([(104, 101), (113, 110), (131, 92)], fill="white", width=7, joint="curve")
    d.text((166, 82), "MarkLayer", font=font("segoeuib.ttf", 40), fill=TEXT)

    title = font("segoeuib.ttf", 70)
    d.text((72, 190), "Is your AI image marked", font=title, fill=TEXT)
    d.text((72, 275), "for the EU AI Act?", font=title, fill=TEXT)
    d.text((72, 392), "Free check: C2PA Content Credentials · invisible watermark · IPTC",
           font=font("segoeui.ttf", 32), fill=MUTED)

    chip = font("seguisb.ttf", 28)
    label = "Article 50 · applies to existing AI systems from 2 Dec 2026"
    x0, y0 = 72, 490
    w = d.textlength(label, font=chip)
    d.rounded_rectangle((x0, y0, x0 + w + 48, y0 + 56), 28, fill="#33270f")
    d.text((x0 + 24, y0 + 9), label, font=chip, fill=AMBER)

    out = ROOT / "app" / "static" / "og.png"
    im.save(out, optimize=True)
    print(f"wrote {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
