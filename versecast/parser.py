"""Turn speech-recogniser output or typed text into Bible references.

    >>> [r.label() for r in parse("turn with me to john chapter three verse sixteen")]
    ['John 3:16']
    >>> [r.label() for r in parse("1 cor 13:4-7", mode="typed")]
    ['1 Corinthians 13:4-7']

The same grammar serves both modes; ``mode="typed"`` additionally accepts
abbreviations, ``:`` separators and dashes, and ignores the strict-book rule.
"""

from __future__ import annotations

from typing import Callable

from . import books as _books
from .numbers import normalise
from .versification import VERSE_COUNTS

CHAPTER_WORDS = frozenset(["chapter", "chapters", "chap", "ch"])
VERSE_WORDS = frozenset(["verse", "verses", "vs", "v", "vv", "ver"])
SEPARATORS = frozenset(["colon", ":"])
# What the small Vosk model hears for "verse" between two numbers, e.g.
# "john chapter three were sixteen". Only accepted inside a reference.
VERSE_MISHEARD = frozenset(["were", "versus", "vers", "worse"])
FILLER = frozenset(["of"])
# Number homophones the recogniser writes instead of digits ("genesis to
# eighteen" for "genesis two eighteen"). Only accepted as the *chapter*
# directly after a book name and only when a number follows, so "romans 8, for
# we know" and ranges ("16 to 18") are unaffected.
CHAPTER_HOMOPHONES = {"to": 2, "too": 2, "for": 4, "fore": 4, "ate": 8, "won": 1}
RANGE_WORDS = frozenset(["to", "through", "thru", "till", "til", "until"])

VerseCounter = Callable[[int, int], int]


def default_verse_count(book, chapter):
    """Number of verses in ``book`` ``chapter`` (0 if it does not exist)."""
    if not 1 <= book <= 66:
        return 0
    chapters = VERSE_COUNTS[book - 1]
    if 1 <= chapter <= len(chapters):
        return chapters[chapter - 1]
    return 0


def chapter_count(book):
    return len(VERSE_COUNTS[book - 1]) if 1 <= book <= 66 else 0


class Reference(object):
    """A parsed Bible reference. ``book`` is None for an unresolved relative one."""

    __slots__ = ("book", "chapter", "verse_start", "verse_end", "relative",
                 "source_text", "confidence", "explicit_verse", "span")

    def __init__(self, book, chapter, verse_start, verse_end, relative=False,
                 source_text="", confidence=1.0, explicit_verse=True, span=(0, 0)):
        self.book = book
        self.chapter = chapter
        self.verse_start = verse_start
        self.verse_end = verse_end
        self.relative = relative
        self.source_text = source_text
        self.confidence = confidence
        self.explicit_verse = explicit_verse
        self.span = span

    # -- helpers ---------------------------------------------------------
    def key(self):
        return (self.book, self.chapter, self.verse_start, self.verse_end)

    def contains(self, other):
        return (self.book == other.book and self.chapter == other.chapter
                and self.verse_start <= other.verse_start and other.verse_end <= self.verse_end)

    def label(self):
        if self.book is None:
            base = "verse"
        else:
            base = "%s %d" % (_books.get(self.book).ref_name, self.chapter)
        if not self.explicit_verse:
            return base
        sep = " " if self.book is None else ":"
        text = "%s%s%d" % (base, sep, self.verse_start)
        if self.verse_end != self.verse_start:
            text += "-%d" % self.verse_end
        return text

    def with_context(self, book, chapter, verse_count=default_verse_count):
        """Resolve a relative reference against ``book chapter``."""
        n = verse_count(book, chapter)
        if n == 0 or self.verse_start < 1 or self.verse_start > n:
            return None
        return Reference(book, chapter, self.verse_start, min(self.verse_end, n), True,
                         self.source_text, self.confidence, True, self.span)

    def __eq__(self, other):
        return isinstance(other, Reference) and self.key() == other.key() and self.relative == other.relative

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self.key())

    def __repr__(self):
        return "Reference(%r%s)" % (self.label(), ", relative" if self.relative else "")


def _is_num(tok):
    return tok.isdigit()


class _Tail(object):
    __slots__ = ("chapter", "verse", "verse_end", "extra", "end", "extra_end",
                 "chapter_kw", "verse_kw")

    def __init__(self):
        self.chapter = None
        self.verse = None
        self.verse_end = None
        self.extra = None
        self.end = 0
        self.extra_end = 0
        self.chapter_kw = False
        self.verse_kw = False


def _number_follows(tokens, k):
    """A number at ``k``, optionally after a verse word ("to verse 18")."""
    n = len(tokens)
    while k < n and (tokens[k] in VERSE_WORDS or tokens[k] in SEPARATORS or tokens[k] in VERSE_MISHEARD):
        k += 1
    return k < n and _is_num(tokens[k])


def _parse_tail(tokens, j):
    """Parse ``[chapter] C [verse|:|colon] [V [to V2]]`` starting at ``j``."""
    n = len(tokens)
    tail = _Tail()
    while j < n and (tokens[j] in CHAPTER_WORDS or tokens[j] in FILLER):
        if tokens[j] in CHAPTER_WORDS:
            tail.chapter_kw = True
        j += 1
    if j < n and tokens[j] in CHAPTER_HOMOPHONES and _number_follows(tokens, j + 1):
        tail.chapter = CHAPTER_HOMOPHONES[tokens[j]]
    elif j >= n or not _is_num(tokens[j]):
        return None
    else:
        tail.chapter = int(tokens[j])
    j += 1
    tail.end = j

    # separator(s) between chapter and verse
    k = j
    verse_kw = False
    while k < n:
        t = tokens[k]
        if t in VERSE_WORDS or t in SEPARATORS:
            verse_kw = True
            k += 1
        elif t in VERSE_MISHEARD and k + 1 < n and _is_num(tokens[k + 1]):
            verse_kw = True
            k += 1
        elif t == "and" and k + 1 < n and tokens[k + 1] in VERSE_WORDS:
            k += 1  # "and verse"
        elif t in FILLER:
            k += 1
        else:
            break
    if k < n and _is_num(tokens[k]):
        tail.verse = int(tokens[k])
        tail.verse_kw = verse_kw
        j = k + 1
        tail.end = j
    else:
        return tail  # chapter only

    # range
    k = j
    if k < n and tokens[k] in RANGE_WORDS:
        k += 1
        while k < n and tokens[k] in VERSE_WORDS:
            k += 1
        if k < n and _is_num(tokens[k]):
            tail.verse_end = int(tokens[k])
            tail.end = k + 1
            return tail
    # a trailing number, only used by the Psalm 119 fallback ("psalm 1 19 105")
    k = j
    while k < n and (tokens[k] in VERSE_WORDS or tokens[k] in SEPARATORS):
        k += 1
    if k < n and _is_num(tokens[k]):
        tail.extra = int(tokens[k])
        tail.extra_end = k + 1
    return tail


def _resolve(book, tail, verse_count, typed=False):
    """Validate; return (chapter, vs, ve, explicit_verse, end, fallback)."""
    chapter = tail.chapter
    verse = tail.verse
    verse_end = tail.verse_end
    end = tail.end
    fallback = False
    assert chapter is not None

    # Single-chapter books: "Jude 3" means verse 3.
    if verse is None and chapter_count(book) == 1 and chapter > 1 and verse_count(book, 1) >= chapter:
        return 1, chapter, chapter, True, end, False

    # Speech merges "one hundred fifty six" into 156: split off the unit digit
    # when the merged number is not a chapter ("psalm 150:6", "genesis 50:1").
    if (verse is None and not typed and chapter > 20 and chapter % 10
            and verse_count(book, chapter) == 0 and verse_count(book, chapter - chapter % 10) >= chapter % 10):
        return chapter - chapter % 10, chapter % 10, chapter % 10, True, end, True

    # Recognisers that write digits sometimes join chapter and verse: "Philippians 413",
    # "John 316". Split a number that is not a chapter where the pieces are valid.
    if verse is None and not typed and chapter >= 100 and verse_count(book, chapter) == 0:
        digits = str(chapter)
        for k in range(1, len(digits)):
            c, v = int(digits[:k]), digits[k:]
            if not v.startswith("0") and 1 <= int(v) <= verse_count(book, c):
                return c, int(v), int(v), True, end, True

    if verse is not None:
        vc = verse_count(book, chapter)
        if vc == 0 or verse < 1 or verse > vc:
            alt = chapter * 100 + verse
            if (chapter >= 1 and 20 < verse < 100 and verse % 10 and verse_count(book, alt) == 0
                    and tail.extra is None and verse_count(book, alt - verse % 10) >= verse % 10):
                # "psalm one fifty six" -> 150:6
                return alt - verse % 10, verse % 10, verse % 10, True, end, True
            if chapter >= 1 and 0 <= verse < 100 and verse_count(book, alt) > 0:
                # Psalm 119 fallback: "psalm one nineteen" -> 119
                fallback = True
                chapter = alt
                verse = None
                verse_end = None
                if tail.extra is not None and 1 <= tail.extra <= verse_count(book, alt):
                    verse = tail.extra
                    end = tail.extra_end
            else:
                return None

    vc = verse_count(book, chapter)
    if vc == 0:
        return None
    if verse is None:
        return chapter, 1, 1, False, end, fallback
    if verse < 1 or verse > vc:
        return None
    if verse_end is None or verse_end <= verse:
        verse_end = verse
    verse_end = min(verse_end, vc)
    return chapter, verse, verse_end, True, end, fallback


def parse_tokens(tokens, mode="speech", strict=True, relative=True, verse_count=default_verse_count):
    """Parse already-normalised tokens. ``Reference.span`` indexes ``tokens``."""
    typed = mode == "typed"
    out = []
    n = len(tokens)
    i = 0

    def text_of(a, b):
        return " ".join(tokens[a:b])

    while i < n:
        hit = _books.match_book(tokens, i, typed=typed)
        if hit is not None:
            book, length, strict_name = hit
            tail = _parse_tail(tokens, i + length)
            if tail is None:
                i += length
                continue
            if strict and strict_name and not typed and not (tail.verse is not None or tail.chapter_kw):
                i += length
                continue
            resolved = _resolve(book.number, tail, verse_count, typed)
            if resolved is None:
                i = max(i + length, tail.extra_end or tail.end)  # consume the invalid reference
                continue
            chapter, vs, ve, explicit, end, fallback = resolved
            conf = 1.0 if typed else 0.9
            if not typed and (tail.chapter_kw or tail.verse_kw):
                conf = 1.0
            if not explicit:
                conf -= 0.3
            if fallback:
                conf -= 0.1
            out.append(Reference(book.number, chapter, vs, ve, False, text_of(i, end),
                                 round(conf, 2), explicit, (i, end)))
            i = end
            continue

        tok = tokens[i]
        if relative and tok in ("verse", "verses") and i + 1 < n and _is_num(tokens[i + 1]):
            vs = int(tokens[i + 1])
            ve = vs
            end = i + 2
            if end + 1 < n and tokens[end] in RANGE_WORDS and _is_num(tokens[end + 1]):
                ve = max(vs, int(tokens[end + 1]))
                end += 2
            if vs >= 1:
                out.append(Reference(None, None, vs, ve, True, text_of(i, end), 0.7, True, (i, end)))
            i = end
            continue
        i += 1
    return out


def parse(text, mode="speech", strict=True, relative=True, verse_count=default_verse_count):
    """Find every reference in ``text``.

    ``mode`` is "speech" (Vosk output) or "typed" (operator search box).
    ``strict`` applies the strict-book rule in speech mode.
    ``relative`` enables bare "verse N" references (``book`` is None in the result).
    """
    tokens = normalise(text, mode)
    return parse_tokens(tokens, mode, strict, relative, verse_count)


def parse_typed(text, verse_count=default_verse_count):
    """The first absolute reference in typed text, or None (used by Search)."""
    for ref in parse(text, mode="typed", relative=False, verse_count=verse_count):
        if ref.book is not None:
            return ref
    return None
