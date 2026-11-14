"""Preview/Live state, independent of Tk widgets (so it can be unit-tested).

A ``Selection`` is a passage (book, chapter, verse range) plus the verse that
is currently shown. Prev/Next step verse by verse through the range and then
on through the Bible, crossing chapter and book boundaries, stopping at
Genesis 1:1 and Revelation 22:21.
"""

from __future__ import annotations

from typing import Optional

from . import books
from .bible import Bible
from .parser import Reference
from .render import BLACK, BLANK, EMPTY, TEXT, Slide, verse_text


class Selection(object):
    __slots__ = ("book", "chapter", "start", "end", "cur", "chapter_only", "relative", "whole")

    def __init__(self, book: int, chapter: int, start: int, end: int, cur: Optional[int] = None,
                 chapter_only: bool = False, relative: bool = False, whole: bool = False) -> None:
        self.book = book
        self.chapter = chapter
        self.start = start
        self.end = max(start, end)
        self.cur = start if cur is None else cur
        self.chapter_only = chapter_only
        self.relative = relative
        self.whole = whole  # showing the whole range on one slide

    @classmethod
    def from_reference(cls, ref: Reference) -> "Selection":
        assert ref.book is not None and ref.chapter is not None
        return cls(ref.book, ref.chapter, ref.verse_start, ref.verse_end,
                   chapter_only=not ref.explicit_verse, relative=ref.relative)

    def copy(self) -> "Selection":
        return Selection(self.book, self.chapter, self.start, self.end, self.cur, self.chapter_only,
                         self.relative, self.whole)

    @property
    def is_range(self) -> bool:
        return self.end > self.start

    def passage_label(self) -> str:
        name = books.get(self.book).ref_name
        if self.chapter_only:
            return "%s %d" % (name, self.chapter)
        if self.is_range:
            return "%s %d:%d-%d" % (name, self.chapter, self.start, self.end)
        return "%s %d:%d" % (name, self.chapter, self.start)

    def verse_label(self) -> str:
        if self.whole and self.is_range:
            return "%s %d:%d-%d" % (books.get(self.book).ref_name, self.chapter, self.start, self.end)
        return "%s %d:%d" % (books.get(self.book).ref_name, self.chapter, self.cur)

    def status_label(self) -> str:
        """Label under the operator thumbnails."""
        text = self.verse_label()
        if self.is_range and not self.whole:
            text += "  (%d/%d)" % (self.cur - self.start + 1, self.end - self.start + 1)
        if self.relative:
            text += "  rel."
        return text

    def __eq__(self, other):
        return isinstance(other, Selection) and (self.book, self.chapter, self.start, self.end, self.cur) == (
            other.book, other.chapter, other.start, other.end, other.cur)

    def __repr__(self):  # pragma: no cover
        return "Selection(%s)" % self.status_label()


def step(bible: Bible, sel: Selection, delta: int) -> Optional[Selection]:
    """Next (+1) or previous (-1) verse; None at the ends of the Bible."""
    if sel.whole and sel.is_range:
        pos = (sel.book, sel.chapter, sel.end if delta > 0 else sel.start)
    else:
        if sel.start <= sel.cur + delta <= sel.end:
            out = sel.copy()
            out.cur += delta
            return out
        pos = (sel.book, sel.chapter, sel.cur)
    nxt = bible.next_pos(pos) if delta > 0 else bible.prev_pos(pos)
    if nxt is None:
        return None
    b, c, v = nxt
    return Selection(b, c, v, v)


def chapter_step(bible: Bible, sel: Selection, delta: int) -> Optional[Selection]:
    """Verse 1 of the next (+1) or previous (-1) chapter, crossing books; None at the ends."""
    b, c = sel.book, sel.chapter + delta
    if c < 1:
        b -= 1
        if b < 1:
            return None
        c = bible.chapter_count(b)
    elif c > bible.chapter_count(b):
        b += 1
        if b > 66:
            return None
        c = 1
    return Selection(b, c, 1, 1)


class SlideBuilder(object):
    """Turns selections into slides in the current translation."""

    def __init__(self, bible: Bible, emphasis=None) -> None:
        self.bible = bible
        self.emphasis = emphasis  # EmphasisStore or None

    def slide(self, sel: Optional[Selection], translation: str, fit_range: bool = False,
              fits=None) -> Slide:
        if sel is None:
            return Slide(EMPTY)
        # an online version that cannot be reached right now shows the fallback instead
        translation = self.bible.resolve(translation, sel.book, sel.chapter)
        slide = self._slide(sel, translation, fit_range, fits)
        slide.translation = translation
        return slide

    def _slide(self, sel: Selection, translation: str, fit_range: bool, fits) -> Slide:
        if fit_range and sel.is_range:
            verses = self.bible.verses(translation, sel.book, sel.chapter, sel.start, sel.end)
            text = verse_text(verses)
            if verses and (fits is None or fits(text)):
                sel.whole = True
                return Slide(TEXT, text, sel.verse_label(), verses)
        sel.whole = False
        text = self.bible.verse(translation, sel.book, sel.chapter, sel.cur)
        if not text:
            text = u"(%s %d:%d is not included in the %s.)" % (
                books.get(sel.book).ref_name, sel.chapter, sel.cur, translation)
            return Slide(TEXT, text, sel.verse_label())
        marks = self.emphasis.get(translation, sel.book, sel.chapter, sel.cur) if self.emphasis else {}
        return Slide(TEXT, text, sel.verse_label(), marks=marks)


class LiveState(object):
    """What the projector shows: a selection, or blank/black over it."""

    def __init__(self) -> None:
        self.selection = None  # type: Optional[Selection]
        self.cover = None  # type: Optional[str]  # None | BLANK | BLACK

    def slide(self, builder: SlideBuilder, translation: str, fit_range: bool = False, fits=None) -> Slide:
        if self.cover == BLACK:
            return Slide(BLACK)
        if self.cover == BLANK:
            return Slide(BLANK)
        return builder.slide(self.selection, translation, fit_range, fits)

    def toggle_cover(self, kind: str) -> None:
        self.cover = None if self.cover == kind else kind
