#!/usr/bin/env python3
"""Draw the website's social preview image (website/assets/og.png, 1200x630).

    python3 tools/make_og_image.py

Developer tool only: needs Pillow (``pip install pillow``), which Biverse itself does not use.
Fonts: the first one found from FONTS below; set BIVERSE_OG_FONT to a .ttf/.ttc to override.
"""

from __future__ import annotations

import io
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_icons  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1200, 630

FONTS = [
    os.environ.get("BIVERSE_OG_FONT", ""),
    "/System/Library/Fonts/Avenir Next.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
SERIF = ["/System/Library/Fonts/NewYork.ttf", "C:/Windows/Fonts/georgia.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"]


def font(paths, size, index=0):
    for p in paths:
        if p and os.path.isfile(p):
            for i in (index, 0):
                try:
                    return ImageFont.truetype(p, size, index=i)
                except OSError:
                    continue
    return ImageFont.load_default()


def main():
    top, bottom = make_icons.TOP, make_icons.BOTTOM
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        t = y / (H - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        for x in range(W):
            px[x, y] = c
    img = img.convert("RGBA")

    mark = Image.open(io.BytesIO(make_icons.render(256, ss=2, tile=False))).convert("RGBA")
    img.alpha_composite(mark, (88, 80))

    d = ImageDraw.Draw(img)
    # Face indexes inside Avenir Next.ttc: 0 Bold, 2 Demi Bold, 5 Medium (other fonts: index 0).
    d.text((370, 120), "Biverse", font=font(FONTS, 92, 0), fill=(255, 255, 255))
    d.text((372, 238), "Say the verse. See it on the screen.", font=font(FONTS, 40, 2), fill=make_icons.GOLD)

    verse = font(SERIF, 34)
    d.text((96, 400), "\u201cThy word is a lamp unto my feet,", font=verse, fill=make_icons.PAGE)
    d.text((96, 446), "and a light unto my path.\u201d  Psalm 119:105", font=verse, fill=make_icons.PAGE)
    d.text((96, 540), "Free  \u00b7  Offline  \u00b7  Windows & macOS  \u00b7  No account, no internet",
           font=font(FONTS, 28, 5), fill=(185, 193, 218))

    out = os.path.join(ROOT, "website", "assets", "og.png")
    img.convert("RGB").save(out, optimize=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
