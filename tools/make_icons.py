#!/usr/bin/env python3
"""Draw the Biverse mark and write every icon file (standard library only).

    python tools/make_icons.py

The mark: a voice waveform rising from an open Bible, with a gold ribbon
bookmark. Speech becomes the verse. One geometry (below, in a 0..1 square,
y down) feeds both the PNG rasteriser and the SVG writer, so app icons and
the website always match.

Writes:
  assets/biverse.png                        window icon (128 px)
  packaging/icons/biverse.{ico,icns}        Windows / macOS app icons
  packaging/icons/biverse-512.png
  website/assets/logo.svg                   the mark (rounded tile)
  website/assets/mark.svg                   the mark without its tile
  website/favicon.svg, favicon.ico
  website/assets/icon-{192,512}.png         web manifest icons
  website/assets/apple-touch-icon.png       180 px, square (iOS rounds it)

ICO and ICNS embed PNG images, which Windows Vista+ and macOS 10.7+ support.
"""

from __future__ import annotations

import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Palette (shared with website/styles.css)
TOP = (31, 58, 138)       # royal navy, top of the tile
BOTTOM = (11, 22, 56)     # deep navy, bottom of the tile
PAGE = (255, 248, 236)    # warm paper
PAGE_SHADE = (231, 220, 198)
GOLD = (245, 184, 61)

RADIUS = 0.225            # tile corner radius


def _hex(c):
    return "#%02X%02X%02X" % c


# -- geometry ---------------------------------------------------------------------------

def _bezier(p0, p1, p2, n=24):
    """Quadratic Bezier sampled into points (p0 included, p2 included)."""
    pts = []
    for i in range(n + 1):
        t = i / float(n)
        a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        pts.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))
    return pts


class Page(object):
    """One page of the open book: straight outer edge, curved top and bottom."""

    def __init__(self, outer_top, top_ctrl, inner_top, inner_bottom, bottom_ctrl, outer_bottom):
        self.ot, self.tc, self.it = outer_top, top_ctrl, inner_top
        self.ib, self.bc, self.ob = inner_bottom, bottom_ctrl, outer_bottom
        self.poly = (_bezier(self.ot, self.tc, self.it) + _bezier(self.ib, self.bc, self.ob))

    def mirrored(self):
        m = lambda p: (1 - p[0], p[1])  # noqa: E731
        return Page(m(self.ot), m(self.tc), m(self.it), m(self.ib), m(self.bc), m(self.ob))

    def svg(self):
        f = lambda p: "%.2f %.2f" % (p[0] * 512, p[1] * 512)  # noqa: E731
        return "M%s Q%s %s L%s Q%s %s Z" % (f(self.ot), f(self.tc), f(self.it), f(self.ib), f(self.bc),
                                           f(self.ob))


GAP = 0.016  # half the gap between the pages at the spine
LEFT_PAGE = Page((0.15, 0.545), (0.33, 0.475), (0.5 - GAP, 0.585),
                 (0.5 - GAP, 0.83), (0.33, 0.75), (0.15, 0.80))
RIGHT_PAGE = LEFT_PAGE.mirrored()
# The pages darken near the spine, where they curve down into the binding.
SHADE_W = 0.085

# Ribbon bookmark: from the spine down past the bottom edge, with a V notch.
RIBBON = [(0.5 - 0.034, 0.70), (0.5 + 0.034, 0.70), (0.5 + 0.034, 0.915), (0.5, 0.885),
          (0.5 - 0.034, 0.915)]

# Voice waveform: rounded bars (centre x, half height), centred on WAVE_Y.
WAVE_Y = 0.29
BAR_W = 0.05
BARS = [(0.5 - 0.216, 0.032), (0.5 - 0.144, 0.072), (0.5 - 0.072, 0.118), (0.5, 0.16),
        (0.5 + 0.072, 0.118), (0.5 + 0.144, 0.072), (0.5 + 0.216, 0.032)]
# Small sizes: fewer, chunkier bars so the shape survives 16-32 px.
BARS_SMALL = [(0.5 - 0.17, 0.07), (0.5, 0.17), (0.5 + 0.17, 0.07)]
BAR_W_SMALL = 0.10


def _in_poly(x, y, pts):
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _in_round_rect(x, y, x0, y0, x1, y1, r):
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return False
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


_BOXES = {id(p): _bbox(p.poly) for p in (LEFT_PAGE, RIGHT_PAGE)}


def _in_page(x, y, page):
    x0, y0, x1, y1 = _BOXES[id(page)]
    return x0 <= x <= x1 and y0 <= y <= y1 and _in_poly(x, y, page.poly)


def colour_at(x, y, small=False, tile=True):
    """RGB at normalised (x, y) or None (transparent)."""
    if tile and not _in_round_rect(x, y, 0, 0, 1, 1, RADIUS):
        return None
    bars, w = (BARS_SMALL, BAR_W_SMALL) if small else (BARS, BAR_W)
    for cx, h in bars:
        if _in_round_rect(x, y, cx - w / 2, WAVE_Y - h, cx + w / 2, WAVE_Y + h, w / 2):
            return GOLD
    if _in_poly(x, y, RIBBON):
        return GOLD
    if _in_page(x, y, LEFT_PAGE) or _in_page(x, y, RIGHT_PAGE):
        d = abs(x - 0.5)
        if small or d >= SHADE_W:
            return PAGE
        t = (1 - d / SHADE_W) ** 1.6  # paper -> shade towards the spine
        return tuple(int(round(PAGE[i] + (PAGE_SHADE[i] - PAGE[i]) * t)) for i in range(3))
    if not tile:
        return None
    t = y
    return tuple(int(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t)) for i in range(3))


# -- PNG -------------------------------------------------------------------------------

def _png(size, rows):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def render(size, ss=3, tile=True, square=False):
    """PNG bytes. ``square`` fills the corners (for apple-touch-icon)."""
    small = size <= 32
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) / size
                    y = (py + (sy + 0.5) / ss) / size
                    c = colour_at(x, y, small, tile)
                    if c is None and square:
                        c = colour_at(0.5, y, small, tile)  # extend the gradient into the corners
                    if c is not None:
                        acc[0] += c[0]
                        acc[1] += c[1]
                        acc[2] += c[2]
                        acc[3] += 255
            a = acc[3] // (ss * ss)
            if a:
                cov = acc[3] / 255.0
                row += bytes([int(acc[0] / cov), int(acc[1] / cov), int(acc[2] / cov), a])
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    return _png(size, rows)


def write_ico(path, pngs):
    entries = b""
    data = b""
    offset = 6 + 16 * len(pngs)
    for size, png in pngs:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(pngs)) + entries + data)


def write_icns(path, pngs):
    types = {128: b"ic07", 256: b"ic08", 512: b"ic09", 32: b"ic11", 64: b"ic12"}
    body = b""
    for size, png in pngs:
        if size in types:
            body += types[size] + struct.pack(">I", len(png) + 8) + png
    with open(path, "wb") as f:
        f.write(b"icns" + struct.pack(">I", len(body) + 8) + body)


# -- SVG -------------------------------------------------------------------------------

def svg(tile=True, small=False):
    """The mark as SVG (512 user units)."""
    s = 512
    bars, w = (BARS_SMALL, BAR_W_SMALL) if small else (BARS, BAR_W)
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Biverse">']
    x0, x1 = (0.5 - SHADE_W) * s, (0.5 + SHADE_W) * s
    shade =['<stop offset="%.3f" stop-color="%s"/>' % (
        k / 10.0, _hex(tuple(int(round(PAGE[i] + (PAGE_SHADE[i] - PAGE[i]) * (1 - abs(k / 5.0 - 1)) ** 1.6))
                             for i in range(3)))) for k in range(11)]
    parts.append('<defs><linearGradient id="bv-bg" x1="0" y1="0" x2="0" y2="1">'
                 '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>'
                 '<linearGradient id="bv-page" gradientUnits="userSpaceOnUse" x1="%.1f" y1="0" x2="%.1f" y2="0">'
                 '%s</linearGradient></defs>' % (_hex(TOP), _hex(BOTTOM), x0, x1, "".join(shade)))
    if tile:
        parts.append('<rect width="512" height="512" rx="%.1f" fill="url(#bv-bg)"/>' % (RADIUS * s))
    pages = '<path d="%s"/><path d="%s"/>' % (LEFT_PAGE.svg(), RIGHT_PAGE.svg())
    parts.append('<g fill="%s">%s</g>' % (_hex(PAGE), pages))
    if not small:
        parts.append('<clipPath id="bv-pages">%s</clipPath>' % pages)
        parts.append('<rect x="%.1f" y="0" width="%.1f" height="512" fill="url(#bv-page)" '
                     'clip-path="url(#bv-pages)"/>' % (x0, x1 - x0))
    parts.append('<g fill="%s">' % _hex(GOLD))
    parts.append('<path d="M%s Z"/>' % " L".join("%.2f %.2f" % (x * s, y * s) for x, y in RIBBON))
    for cx, h in bars:
        parts.append('<rect x="%.2f" y="%.2f" width="%.2f" height="%.2f" rx="%.2f"/>'
                     % ((cx - w / 2) * s, (WAVE_Y - h) * s, w * s, 2 * h * s, w / 2 * s))
    parts.append('</g></svg>')
    return "".join(parts) + "\n"


def main():
    icon_dir = os.path.join(ROOT, "packaging", "icons")
    web = os.path.join(ROOT, "website")
    web_assets = os.path.join(web, "assets")
    for d in (os.path.join(ROOT, "assets"), icon_dir, web_assets):
        os.makedirs(d, exist_ok=True)

    sizes = [16, 32, 48, 64, 128, 180, 192, 256, 512]
    pngs = dict((s, render(s, ss=4 if s <= 64 else 2)) for s in sizes)

    with open(os.path.join(ROOT, "assets", "biverse.png"), "wb") as f:
        f.write(pngs[128])
    with open(os.path.join(icon_dir, "biverse-512.png"), "wb") as f:
        f.write(pngs[512])
    write_ico(os.path.join(icon_dir, "biverse.ico"), [(s, pngs[s]) for s in (16, 32, 48, 256)])
    write_icns(os.path.join(icon_dir, "biverse.icns"), [(s, pngs[s]) for s in (32, 64, 128, 256, 512)])

    write_ico(os.path.join(web, "favicon.ico"), [(s, pngs[s]) for s in (16, 32, 48)])
    for s in (192, 512):
        with open(os.path.join(web_assets, "icon-%d.png" % s), "wb") as f:
            f.write(pngs[s])
    with open(os.path.join(web_assets, "apple-touch-icon.png"), "wb") as f:
        f.write(render(180, ss=2, square=True))
    for name, text in (("logo.svg", svg()), ("mark.svg", svg(tile=False))):
        with open(os.path.join(web_assets, name), "w", encoding="utf-8") as f:
            f.write(text)
    with open(os.path.join(web, "favicon.svg"), "w", encoding="utf-8") as f:
        f.write(svg(small=True))
    print("icons written")


if __name__ == "__main__":
    main()
