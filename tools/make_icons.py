#!/usr/bin/env python3
"""Draw the Biverse icon and write PNG, ICO and ICNS files (stdlib only).

    python tools/make_icons.py

Writes assets/biverse.png (window icon) and packaging/icons/biverse.{ico,icns}.
ICO and ICNS embed PNG images, which Windows Vista+ and macOS 10.7+ support.
"""

from __future__ import annotations

import math
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BG = (36, 52, 107)
PAGE = (255, 255, 255)
WAVE = (244, 197, 66)


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


def _in_round_rect(x, y, r):
    cx = min(max(x, r), 1 - r)
    cy = min(max(y, r), 1 - r)
    return (x - cx) ** 2 + (y - cy) ** 2 <= r * r


LEFT = [(0.16, 0.44), (0.485, 0.50), (0.485, 0.84), (0.16, 0.78)]
RIGHT = [(1 - x, y) for x, y in LEFT]


def colour_at(x, y):
    """RGBA at normalised (x, y), y down."""
    if not _in_round_rect(x, y, 0.2):
        return None
    if _in_poly(x, y, LEFT) or _in_poly(x, y, RIGHT):
        return PAGE
    dx, dy = x - 0.5, y - 0.47
    d = math.hypot(dx, dy)
    ang = math.degrees(math.atan2(-dy, dx))  # 90 = straight up
    if 40 <= ang <= 140:
        for r in (0.13, 0.22, 0.31):
            if abs(d - r) <= 0.026:
                return WAVE
    return BG


def render(size, ss=3):
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(ss):
                for sx in range(ss):
                    c = colour_at((px + (sx + 0.5) / ss) / size, (py + (sy + 0.5) / ss) / size)
                    if c is not None:
                        acc[0] += c[0]
                        acc[1] += c[1]
                        acc[2] += c[2]
                        acc[3] += 255
            n = ss * ss
            a = acc[3] // n
            if a:
                cov = acc[3] / 255.0
                row += bytes([int(acc[0] / cov), int(acc[1] / cov), int(acc[2] / cov), a])
            else:
                row += b"\0\0\0\0"
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


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


def main():
    sizes = [16, 32, 48, 64, 128, 256, 512]
    pngs = [(s, render(s, ss=4 if s <= 64 else 2)) for s in sizes]
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "packaging", "icons"), exist_ok=True)
    with open(os.path.join(ROOT, "assets", "biverse.png"), "wb") as f:
        f.write(dict(pngs)[128])
    write_ico(os.path.join(ROOT, "packaging", "icons", "biverse.ico"), [p for p in pngs if p[0] in (16, 32, 48, 256)])
    write_icns(os.path.join(ROOT, "packaging", "icons", "biverse.icns"),
               [p for p in pngs if p[0] in (32, 64, 128, 256, 512)])
    with open(os.path.join(ROOT, "packaging", "icons", "biverse-512.png"), "wb") as f:
        f.write(dict(pngs)[512])
    print("icons written")


if __name__ == "__main__":
    main()
