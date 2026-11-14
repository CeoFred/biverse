"""Slide rendering shared by the projector window and the operator thumbnails.

A slide is drawn onto a Tk Canvas:
  * verse text centred inside 6 % margins, word-wrapped, auto-fitted by a
    binary search over the font size (measured with ``create_text(width=...)``
    + ``bbox``), never smaller than ``min_size`` on the output;
  * the reference line ("John 3:16 · KJV") smaller, at the bottom or top;
  * optional text shadow and background image (PNG/GIF via PhotoImage).

Thumbnails are rendered by laying the slide out at the projector's real size
and scaling the result, so the operator sees what the congregation sees.
"""

from __future__ import annotations

import logging
import os
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

MARGIN = 0.06
MIN_OUTPUT_SIZE = 24
MAX_SIZE = 220

# Slide kinds
TEXT = "text"
BLANK = "blank"   # background only
BLACK = "black"   # fully black
EMPTY = "empty"   # nothing loaded yet (black)


class Appearance(object):
    __slots__ = ("background", "foreground", "font_family", "bold", "shadow", "reference_position",
                 "background_image", "reference_color", "highlight_color")

    def __init__(self, background="#000000", foreground="#FFFFFF", font_family="", bold=True, shadow=True,
                 reference_position="bottom", background_image="", reference_color="", highlight_color="#FFD54A"):
        self.highlight_color = highlight_color
        self.background = background
        self.foreground = foreground
        self.font_family = font_family
        self.bold = bold
        self.shadow = shadow
        self.reference_position = reference_position
        self.background_image = background_image
        self.reference_color = reference_color

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "Appearance":
        a = cls()
        for k in cls.__slots__:
            if d and k in d and isinstance(d[k], type(getattr(a, k))):
                setattr(a, k, d[k])
        if a.reference_position not in ("bottom", "top"):
            a.reference_position = "bottom"
        return a

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}

    def key(self) -> tuple:
        return tuple(getattr(self, k) for k in self.__slots__)


class Slide(object):
    """What to show: verse text plus its reference line, or a blank/black screen."""

    __slots__ = ("kind", "text", "reference", "verses", "marks", "translation")

    def __init__(self, kind: str = EMPTY, text: str = "", reference: str = "", verses=None, marks=None,
                 translation: str = "") -> None:
        self.kind = kind
        self.translation = translation  # the translation actually shown ("" when not set)
        self.text = text
        self.reference = reference
        self.verses = verses or []
        self.marks = marks or {}  # word index -> {"bold", "underline", "highlight"}

    def __eq__(self, other):
        return isinstance(other, Slide) and (self.kind, self.text, self.reference, self._mkey()) == (
            other.kind, other.text, other.reference, other._mkey())

    def _mkey(self):
        return tuple(sorted((i, tuple(sorted(s))) for i, s in self.marks.items()))

    def __repr__(self):  # pragma: no cover
        return "Slide(%s, %r)" % (self.kind, self.reference)


def default_family(root) -> str:
    try:
        import tkinter.font as tkfont
        fams = set(tkfont.families(root))
    except Exception:
        return "Helvetica"
    for name in ("Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans", "Liberation Sans", "Helvetica"):
        if name in fams:
            return name
    return "Helvetica"


class Layout(object):
    __slots__ = ("text_size", "ref_size", "box", "ref_y", "text_y", "width", "height")

    def __init__(self):
        self.text_size = 0
        self.ref_size = 0
        self.box = (0, 0, 0, 0)
        self.ref_y = 0
        self.text_y = 0
        self.width = 0
        self.height = 0


class Renderer(object):
    """Lays out and draws slides. One instance per Tk root (caches fonts/images)."""

    def __init__(self, root) -> None:
        self.root = root
        self._fit_cache = {}  # type: Dict[tuple, int]
        self._image_cache = {}  # type: Dict[tuple, object]
        self._measure = None
        self._family = None  # type: Optional[str]
        self._fonts = {}  # Tk font objects for word-by-word drawing

    # -- measuring ----------------------------------------------------------
    def _canvas(self):
        if self._measure is None:
            import tkinter as tk
            self._measure = tk.Canvas(self.root, width=10, height=10)
        return self._measure

    def family(self, appearance: Appearance) -> str:
        if appearance.font_family:
            return appearance.font_family
        if self._family is None:
            self._family = default_family(self.root)
        return self._family

    def font(self, appearance: Appearance, size: int, bold: Optional[bool] = None):
        weight = "bold" if (appearance.bold if bold is None else bold) else "normal"
        return (self.family(appearance), -max(1, int(size)), weight)  # negative = pixels

    def measure(self, text: str, font, width: int) -> Tuple[int, int]:
        c = self._canvas()
        item = c.create_text(0, 0, text=text, font=font, width=width, anchor="nw")
        bbox = c.bbox(item)
        c.delete(item)
        if not bbox:
            return 0, 0
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def fit(self, text: str, appearance: Appearance, box_w: int, box_h: int, min_size: int = MIN_OUTPUT_SIZE,
            max_size: int = MAX_SIZE) -> int:
        """Largest pixel font size whose wrapped text fits ``box_w`` x ``box_h``."""
        key = (text, self.family(appearance), appearance.bold, box_w, box_h, min_size, max_size)
        hit = self._fit_cache.get(key)
        if hit is not None:
            return hit
        lo, hi = min_size, max(min_size, max_size)
        best = min_size
        while lo <= hi:
            mid = (lo + hi) // 2
            w, h = self.measure(text, self.font(appearance, mid), box_w)
            if h <= box_h and w <= box_w:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if len(self._fit_cache) > 2000:
            self._fit_cache.clear()
        self._fit_cache[key] = best
        return best

    def fits(self, text: str, appearance: Appearance, width: int, height: int,
             min_size: int = MIN_OUTPUT_SIZE) -> bool:
        lay = self.layout(text, appearance, width, height, min_size)
        _, h = self.measure(text, self.font(appearance, lay.text_size), lay.box[2] - lay.box[0])
        return h <= lay.box[3] - lay.box[1]

    def layout(self, text: str, appearance: Appearance, width: int, height: int,
               min_size: int = MIN_OUTPUT_SIZE) -> Layout:
        lay = Layout()
        lay.width, lay.height = width, height
        mx = int(width * MARGIN)
        my = int(height * MARGIN)
        lay.ref_size = max(12, int(height * 0.045))
        ref_band = int(lay.ref_size * 2.2)
        if appearance.reference_position == "top":
            box = (mx, my + ref_band, width - mx, height - my)
            lay.ref_y = my + lay.ref_size // 2
        else:
            box = (mx, my, width - mx, height - my - ref_band)
            lay.ref_y = height - my - lay.ref_size // 2
        lay.box = box
        box_w = max(10, box[2] - box[0])
        box_h = max(10, box[3] - box[1])
        lay.text_size = self.fit(text, appearance, box_w, box_h, min_size=min_size,
                                 max_size=max(min_size, min(MAX_SIZE, int(height * 0.16))))
        lay.text_y = (box[1] + box[3]) // 2
        return lay

    def _draw_marked(self, canvas, slide, appearance, px, box_w, cx, cy):
        """Word-by-word drawing for verses with bold / underline / highlight marks."""
        family = self.family(appearance)
        words = slide.text.split()
        fonts = []
        for i in range(len(words)):
            st = slide.marks.get(i, ())
            fonts.append(_tk_font(self.root, self._fonts, family, px, appearance.bold or "bold" in st,
                                  "underline" in st))
        base = _tk_font(self.root, self._fonts, family, px, appearance.bold, False)
        space = base.measure(" ")
        widths = [fonts[i].measure(w) for i, w in enumerate(words)]
        lines = layout_words(words, widths, space, box_w)
        lh = base.metrics("linespace")
        y = cy - lh * len(lines) / 2.0
        off = max(1, px // 18)
        pad = max(1, px // 10)
        for line in lines:
            line_w = sum(widths[i] for i in line) + space * (len(line) - 1)
            x = cx - line_w / 2.0
            for i in line:
                st = slide.marks.get(i, ())
                fill = appearance.foreground
                if "highlight" in st:
                    canvas.create_rectangle(x - pad, y + pad // 2, x + widths[i] + pad, y + lh - pad // 2,
                                            fill=appearance.highlight_color, outline="")
                    fill = "#111111"
                elif appearance.shadow:
                    canvas.create_text(x + off, y + off, text=words[i], font=fonts[i], anchor="nw", fill="#000000")
                canvas.create_text(x, y, text=words[i], font=fonts[i], anchor="nw", fill=fill)
                x += widths[i] + space
            y += lh

    # -- drawing ------------------------------------------------------------
    def _background_image(self, path: str, width: int, height: int):
        if not path or not os.path.isfile(path):
            return None
        key = (path, width, height)
        img = self._image_cache.get(key)
        if img is not None:
            return img
        try:
            import tkinter as tk
            src = tk.PhotoImage(master=self.root, file=path)
        except Exception:
            log.warning("cannot load background image %s", path, exc_info=True)
            return None
        iw, ih = src.width(), src.height()
        img = src
        # integer zoom/subsample only (no Pillow): cover the area as well as possible
        if iw > 0 and ih > 0:
            if iw < width and ih < height:
                factor = max(1, min(width // iw, height // ih) + (1 if (width % iw or height % ih) else 0))
                img = src.zoom(factor, factor)
            elif iw > width * 2 and ih > height * 2:
                factor = max(1, min(iw // width, ih // height))
                img = src.subsample(factor, factor)
        if len(self._image_cache) > 8:
            self._image_cache.clear()
        self._image_cache[key] = img
        return img

    def draw(self, canvas, slide: Slide, appearance: Appearance, width: int, height: int,
             design_size: Optional[Tuple[int, int]] = None, translation: str = "") -> None:
        """Draw ``slide`` on ``canvas`` (``width`` x ``height`` pixels).

        ``design_size`` is the projector resolution for thumbnails: the slide is
        laid out at that size and scaled down, so line breaks match.
        """
        canvas.delete("all")
        if width < 4 or height < 4:
            return
        if slide.kind in (BLACK, EMPTY):
            canvas.configure(background="#000000")
            return
        canvas.configure(background=appearance.background)
        if appearance.background_image:
            img = self._background_image(appearance.background_image, width, height)
            if img is not None:
                canvas.create_image(width // 2, height // 2, image=img, anchor="center")
                canvas._bg_image = img  # keep a reference
        if slide.kind == BLANK or not slide.text:
            return

        dw, dh = design_size or (width, height)
        scale = float(width) / dw if dw else 1.0
        min_size = MIN_OUTPUT_SIZE if design_size is None else MIN_OUTPUT_SIZE
        lay = self.layout(slide.text, appearance, dw, dh, min_size=min_size)

        def s(v):
            return int(round(v * scale))

        text_size = max(4, s(lay.text_size))
        if design_size is not None and scale < 0.5:
            # tiny fonts render slightly taller than their nominal size: keep thumbnails inside the frame
            text_size = max(4, int(text_size * 0.9))
        ref_size = max(4, s(lay.ref_size))
        box_w = s(lay.box[2] - lay.box[0])
        cx = width // 2
        font = self.font(appearance, text_size)
        if slide.marks:
            self._draw_marked(canvas, slide, appearance, text_size, box_w, cx, s(lay.text_y))
        else:
            if appearance.shadow:
                off = max(1, text_size // 18)
                canvas.create_text(cx + off, s(lay.text_y) + off, text=slide.text, font=font, width=box_w,
                                   justify="center", anchor="center", fill="#000000")
            canvas.create_text(cx, s(lay.text_y), text=slide.text, font=font, width=box_w, justify="center",
                               anchor="center", fill=appearance.foreground)
        label = slide.reference
        if translation and label:
            label = u"%s · %s" % (label, translation)
        if label:
            ref_font = self.font(appearance, ref_size, bold=False)
            color = appearance.reference_color or _muted(appearance.foreground, appearance.background)
            if appearance.shadow:
                off = max(1, ref_size // 18)
                canvas.create_text(cx + off, s(lay.ref_y) + off, text=label, font=ref_font, anchor="center",
                                   fill="#000000")
            canvas.create_text(cx, s(lay.ref_y), text=label, font=ref_font, anchor="center", fill=color)


def _tk_font(root, cache, family, px, bold, underline):
    key = (family, px, bold, underline)
    f = cache.get(key)
    if f is None:
        import tkinter.font as tkfont
        f = tkfont.Font(root=root, family=family, size=-max(1, px), weight="bold" if bold else "normal",
                        underline=1 if underline else 0)
        if len(cache) > 200:
            cache.clear()
        cache[key] = f
    return f


def layout_words(words, widths, space, box_w):
    """Greedy word wrap (the same rule Tk uses): [[word index, ...], ...] per line."""
    lines, cur, width = [], [], 0
    for i, w in enumerate(widths):
        need = w if not cur else width + space + w
        if cur and need > box_w:
            lines.append(cur)
            cur, width = [i], w
        else:
            cur.append(i)
            width = need
    if cur:
        lines.append(cur)
    return lines




def _hex(c: str) -> Tuple[int, int, int]:
    c = c.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, IndexError):
        return 255, 255, 255


def _muted(fg: str, bg: str) -> str:
    """Reference colour: the text colour blended 30 % toward the background."""
    f, b = _hex(fg), _hex(bg)
    return "#%02x%02x%02x" % tuple(int(f[i] * 0.7 + b[i] * 0.3) for i in range(3))


def verse_text(verses: List) -> str:
    """Join several verses for "fit whole range on one slide"."""
    if len(verses) == 1:
        return verses[0].text
    return " ".join(u"%d %s" % (v.verse, v.text) for v in verses)
