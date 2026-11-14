"""Recognise a verse from the preacher's words when no reference is spoken.

The preacher quotes "for God so loved the world that he gave his only
begotten son" without saying "John 3:16". This module finds it:

1. **Index.** Every verse of every local translation is cut into word
   3-grams (stemmed, so "loveth" / "loved" / "loves" agree, and "thee" is
   "you"). Each 3-gram is hashed into one of 2^20 buckets, and the ``ngrams``
   table of ``bible.db`` stores, per bucket, the verses (as 16-bit verse
   numbers on the KJV grid) whose text contains a 3-gram of that bucket.
   ``build_index`` writes it at build time (about 10 MB for five
   translations) and after a user import.
2. **Candidates.** The newest spoken words are cut into 3-grams the same way;
   verses hit by two or more of them are candidates.
3. **Ranking.** Each candidate is aligned word by word against the spoken
   words in every local translation (longest common subsequence of stems).
   The score rewards matched content words and a dense, in-order match, so a
   few common words ("and the Lord said unto Moses") never make a match.

``QuoteMatcher.feed`` returns the top suggestions. A match is *strong* when
it is long, dense and clearly better than the next verse, and *confirmed*
when it stays the best match for two utterances in a row. Only confirmed
strong matches may go live by themselves, and only when
``AUTO_LIVE_ALLOWED`` is set (after a benchmark on real sermon transcripts
shows no false go-lives; see ``tools/bench_quotes.py``).
"""

from __future__ import annotations

import array
import logging
import math
import sqlite3
import sys
import time
import zlib
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple  # noqa: F401 (Set: type comments)

from .follow import STOPWORDS, words

log = logging.getLogger(__name__)

INDEX_VERSION = "2"
BUCKET_BITS = 20
BUCKET_MASK = (1 << BUCKET_BITS) - 1

WINDOW_WORDS = 40        # newest spoken words searched
WINDOW_SECONDS = 25.0    # ...from at most this long ago
MAX_CANDIDATES = 16      # candidates aligned per utterance
MIN_GRAM_HITS = 2        # 3-grams a verse needs to become a candidate
MIN_MATCHED = 5          # aligned words a suggestion needs (4 when that is the whole verse)
MIN_DENSITY = 0.6        # matched words / spoken words they span
MAX_GAP = 4              # spoken words between two matched ones before they count as separate
MIN_EVIDENCE = 14.0      # sum of the matched words' rarity (log N/df): "and the Lord said unto" is ~4
FULL_EVIDENCE = 30.0     # evidence that counts as complete
AMBIGUOUS = 3            # verses matching the same words this closely: a stock phrase, not a quote
TIE = 0.1
SUGGEST = 0.55           # strength shown as a possible reference
STRONG = 0.85            # strength of a match that may go live by itself...
STRONG_MATCHED = 8       # ...with at least this many matched words...
STRONG_GAP = 0.2         # ...and this far ahead of the next verse
REPEAT_SECONDS = 120.0   # a verse is not suggested again within this time
TOP = 5

# Not until a benchmark on real sermon transcripts shows no false go-lives.
AUTO_LIVE_ALLOWED = False

# Spoken and older forms that should match each other.
_SAME = {
    "thee": "you", "thou": "you", "ye": "you", "thy": "your", "thine": "your", "yours": "your",
    "hath": "has", "doth": "does", "art": "are", "wilt": "will", "shalt": "shall", "unto": "to",
    "saith": "says", "spake": "spoke", "hast": "have", "didst": "did", "canst": "can", "dost": "do",
    "whatsoever": "whatever", "whosoever": "whoever", "lo": "behold", "o": "oh",
}
_SUFFIXES = ("eth", "est", "ing", "ed", "es", "s")
_STOP_STEMS = None  # type: Optional[frozenset]


def stem(word: str) -> str:
    """A rough stem: "believeth", "believes", "believed", "believing" -> "believ"."""
    w = _SAME.get(word, word)
    if w.isdigit():
        return w
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[:-len(suf)]
            break
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w


def _stop_stems() -> frozenset:
    global _STOP_STEMS
    if _STOP_STEMS is None:
        _STOP_STEMS = frozenset(stem(w) for w in STOPWORDS) | frozenset(_SAME.values())
    return _STOP_STEMS


def keys(text: str) -> List[str]:
    return [stem(w) for w in words(text)]


def is_content(key: str) -> bool:
    return key not in _stop_stems()


def grams(ks: Sequence[str]) -> List[str]:
    """Word 3-grams worth indexing (not all three common words)."""
    out = []
    for i in range(len(ks) - 2):
        g = ks[i:i + 3]
        if is_content(g[0]) or is_content(g[1]) or is_content(g[2]):
            out.append(" ".join(g))
    return out


def bucket(gram: str) -> int:
    return zlib.crc32(gram.encode("utf-8")) & BUCKET_MASK


# -- verse numbers on the KJV grid -------------------------------------------------------

class Grid(object):
    """Verse <-> 0..31101 (the KJV grid every translation is mapped onto)."""

    def __init__(self, chapters: Iterable[Tuple[int, int, int]]) -> None:
        self.pos = []  # type: List[Tuple[int, int, int]]
        self.ordinal = {}  # type: Dict[Tuple[int, int, int], int]
        for b, c, n in sorted(chapters):
            for v in range(1, n + 1):
                self.ordinal[(b, c, v)] = len(self.pos)
                self.pos.append((b, c, v))


# -- the index ---------------------------------------------------------------------------

def _pack(ordinals: Iterable[int]) -> bytes:
    a = array.array("H", sorted(ordinals))
    if sys.byteorder == "big":  # pragma: no cover - stored little-endian
        a.byteswap()
    return a.tobytes()


def unpack(blob: bytes) -> array.array:
    a = array.array("H")
    a.frombytes(blob)
    if sys.byteorder == "big":  # pragma: no cover
        a.byteswap()
    return a


def build_index(conn: sqlite3.Connection) -> int:
    """(Re)write the ``ngrams`` table for every translation in ``conn``; returns the bucket count."""
    grid = Grid(conn.execute("SELECT book, chapter, verse_count FROM chapters"))
    buckets = {}  # type: Dict[int, Set[int]]
    for b, c, v, text in conn.execute("SELECT book, chapter, verse, text FROM verses"):
        o = grid.ordinal.get((b, c, v))
        if o is None or not text:
            continue
        for g in grams(keys(text)):
            buckets.setdefault(bucket(g), set()).add(o)
    df = {}  # type: Dict[str, Set[int]]
    for b, c, v, text in conn.execute("SELECT book, chapter, verse, text FROM verses"):
        o = grid.ordinal.get((b, c, v))
        if o is not None and text:
            for k in set(keys(text)):
                df.setdefault(k, set()).add(o)
    with conn:
        conn.execute("DROP TABLE IF EXISTS stems")
        conn.execute("CREATE TABLE stems(key TEXT PRIMARY KEY, df INTEGER) WITHOUT ROWID")
        conn.executemany("INSERT INTO stems(key, df) VALUES (?,?)", ((k, len(s)) for k, s in df.items()))
        conn.execute("DROP TABLE IF EXISTS ngrams")
        conn.execute("CREATE TABLE ngrams(bucket INTEGER PRIMARY KEY, refs BLOB)")
        conn.executemany("INSERT INTO ngrams(bucket, refs) VALUES (?,?)",
                         ((h, _pack(s)) for h, s in buckets.items()))
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('ngram_index', ?)", (INDEX_VERSION,))
    return len(buckets)


# -- matching ----------------------------------------------------------------------------

class Match(object):
    __slots__ = ("book", "chapter", "verse", "strength", "matched", "heard", "translation", "strong",
                 "confirmed", "end")

    def __init__(self, book: int, chapter: int, verse: int, strength: float, matched: int, heard: str,
                 translation: str) -> None:
        self.book, self.chapter, self.verse = book, chapter, verse
        self.strength = strength
        self.matched = matched
        self.heard = heard          # the spoken words that matched, "…" where words were skipped
        self.translation = translation
        self.strong = False
        self.confirmed = False
        self.end = 0                # index of the last matched spoken word

    @property
    def pos(self) -> Tuple[int, int, int]:
        return (self.book, self.chapter, self.verse)

    def label(self) -> str:
        from . import books
        return "%s %d:%d" % (books.get(self.book).ref_name, self.chapter, self.verse)

    def __repr__(self):  # pragma: no cover
        return "Match(%s, %.2f, %d%s)" % (self.label(), self.strength, self.matched,
                                         ", confirmed" if self.confirmed else ", strong" if self.strong else "")


def lcs(a: Sequence[str], b: Sequence[str]) -> List[Tuple[int, int]]:
    """Longest common subsequence of two key lists: [(i, j)] in order."""
    n, m = len(a), len(b)
    if not n or not m:
        return []
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        row, nxt = dp[i], dp[i + 1]
        ai = a[i]
        for j in range(m - 1, -1, -1):
            row[j] = nxt[j + 1] + 1 if ai == b[j] else (nxt[j] if nxt[j] >= row[j + 1] else row[j + 1])
    pairs = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j] and dp[i][j] == dp[i + 1][j + 1] + 1:
            pairs.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


class Rarity(object):
    """How much a matched word proves: log(verses / verses containing it)."""

    def __init__(self, df: Dict[str, int], total: int = 31102) -> None:
        self.df = df
        self.total = float(total)
        self.unknown = math.log(self.total)
        self._cache = {}  # type: Dict[str, float]

    def __call__(self, key: str) -> float:
        v = self._cache.get(key)
        if v is None:
            n = self.df.get(key)
            v = self._cache[key] = self.unknown if n is None else math.log(self.total / (1.0 + n))
        return v


def score(spoken: Sequence[str], verse: Sequence[str], rarity: Optional[Rarity] = None
          ) -> Tuple[float, List[Tuple[int, int]]]:
    """How well the spoken words quote this verse (0..1), and the aligned pairs."""
    pairs = lcs(spoken, verse)
    if len(pairs) < 4:
        return 0.0, pairs
    # the quote itself: split where more than MAX_GAP spoken words separate two matches and keep
    # the longest piece (stray "the ... and" matches in earlier talk are not part of it)
    pieces = [[pairs[0]]]
    for p in pairs[1:]:
        if p[0] - pieces[-1][-1][0] > MAX_GAP:
            pieces.append([p])
        else:
            pieces[-1].append(p)
    pairs = max(reversed(pieces), key=len)
    m = len(pairs)
    whole = m >= len(verse) - 1
    if m < (4 if whole else MIN_MATCHED):
        return 0.0, pairs
    span = pairs[-1][0] - pairs[0][0] + 1
    density = m / float(span)
    if density < MIN_DENSITY:
        return 0.0, pairs
    rarity = rarity or Rarity({})
    evidence = sum(rarity(verse[j]) if is_content(verse[j]) else min(1.0, rarity(verse[j])) for _i, j in pairs)
    if evidence < MIN_EVIDENCE:
        return 0.0, pairs
    # enough of the verse (or 12 words of a long one), rare words, said densely
    coverage = min(1.0, m / float(min(len(verse), 12)))
    return round(0.35 * coverage + 0.35 * min(1.0, evidence / FULL_EVIDENCE) + 0.3 * density, 3), pairs


class QuoteMatcher(object):
    """Feed it the recogniser's final text; it returns the best possible references."""

    def __init__(self, bible, codes: Optional[Sequence[str]] = None) -> None:
        self.bible = bible
        self.codes = list(codes) if codes is not None else bible.local_codes()
        self.grid = Grid((b, c, n) for (b, c), n in bible._counts.items())
        self.available = bible.has_ngram_index()
        self.rarity = Rarity(bible.stem_counts() if self.available else {}, len(self.grid.pos) or 31102)
        self._words = []  # type: List[Tuple[float, str, str]]  # (time, spoken word, key)
        self._last = {}  # type: Dict[Tuple[int, int, int], float]  # verse -> last suggested
        self._best = None  # type: Optional[Tuple[Tuple[int, int, int], int]]  # last strong match, words
        self._sent_live = {}  # type: Dict[Tuple[int, int, int], float]
        self._texts = {}  # type: Dict[Tuple[int, int, int], List[Tuple[str, List[str]]]]
        self.exclude = set()  # type: Set[Tuple[int, int, int]]  # verses on screen (followed, not quoted)
        self._postings = {}  # type: Dict[int, Set[int]]  # bucket -> verses, from the last candidates()

    def reset(self) -> None:
        self._words = []
        self._best = None
        self._last.clear()
        self._sent_live.clear()

    def _verse_keys(self, pos: Tuple[int, int, int]) -> List[Tuple[str, List[str]]]:
        got = self._texts.get(pos)
        if got is None:
            got = []
            seen = set()
            for code in self.codes:
                text = self.bible.verse(code, *pos)
                ks = keys(text or "")
                if ks and tuple(ks) not in seen:
                    seen.add(tuple(ks))
                    got.append((code, ks))
            if len(self._texts) > 2000:
                self._texts.clear()
            self._texts[pos] = got
        return got

    def candidates(self, ks: Sequence[str], first_new: int = 0) -> List[int]:
        """Verses hit by 3-grams that touch the newest words, ranked by hits over all of ``ks``."""
        old = set(bucket(g) for g in grams(ks[:max(0, first_new)]))
        new = set(bucket(g) for g in grams(ks[max(0, first_new - 2):])) - old
        if not new:
            return []
        hits = {}  # type: Dict[int, int]
        fresh = set()  # type: Set[int]
        buckets = sorted(old | new)
        self._postings = {}
        for h, refs in zip(buckets, self.bible.ngram_postings(buckets, keep_order=True)):
            self._postings[h] = refs
            for o in refs:
                hits[o] = hits.get(o, 0) + 1
            if h in new:
                fresh.update(refs)
        ranked = sorted((o for o in fresh if hits[o] >= MIN_GRAM_HITS), key=lambda o: -hits[o])
        return ranked[:MAX_CANDIDATES]

    def shared_by(self, verse: Sequence[str], pairs: Sequence[Tuple[int, int]]) -> int:
        """How many verses contain the matched words as well (1: only this one).

        The matched words fall into runs of consecutive verse words; a run is only as
        telling as the number of verses that contain all its 3-grams. The match is as
        common as its rarest run: "and the Lord said unto Moses" + "speak unto the
        children of Israel" is two stock phrases, however rare the pair is.
        """
        runs, run = [], [pairs[0][1]] if pairs else []  # type: List[List[int]], List[int]
        for _i, j in pairs[1:]:
            if j == run[-1] + 1:
                run.append(j)
            else:
                runs.append(run)
                run = [j]
        if run:
            runs.append(run)
        rarest = None  # type: Optional[int]
        for r in runs:
            common = None  # type: Optional[Set[int]]
            for g in grams([verse[j] for j in r]):
                refs = self._postings.get(bucket(g))
                if refs is not None:
                    common = set(refs) if common is None else common & set(refs)
            if common is not None:
                rarest = len(common) if rarest is None else min(rarest, len(common))
        return rarest if rarest is not None else 1

    def match(self, spoken: Sequence[str], ks: Sequence[str], first_new: int = 0) -> List[Match]:
        """Every candidate scored, best first (no history, no thresholds beyond the score)."""
        out = []
        for o in self.candidates(ks, first_new):
            pos = self.grid.pos[o]
            best = (0.0, [], "")  # type: Tuple[float, list, str]
            for code, verse in self._verse_keys(pos):
                s, pairs = score(ks, verse, self.rarity)
                if s > best[0]:
                    best = (s, pairs, code)
            s, pairs, code = best
            if s <= 0:
                continue
            verse = dict(self._verse_keys(pos))[code]
            if self.shared_by(verse, pairs) >= AMBIGUOUS:  # "a mighty man of valour": a stock phrase
                continue
            heard = []
            for k, (i, _j) in enumerate(pairs):
                if k and i - pairs[k - 1][0] > 1:
                    heard.append(u"…")
                heard.append(spoken[i])
            m = Match(pos[0], pos[1], pos[2], s, len(pairs), " ".join(heard), code)
            m.end = pairs[-1][0]
            out.append(m)
        out.sort(key=lambda m: (-m.strength, -m.matched, m.pos))
        # a stock phrase found in many verses ("and the Lord spake unto Moses, saying", "a mighty
        # man of valour") is no quote
        if out:
            same = [m for m in out if m.heard == out[0].heard and m.strength >= out[0].strength - TIE]
            if len(same) >= AMBIGUOUS:
                return []
        # the same words in two verses (Psalm 14 and 53, the Gospels) make neither one strong
        if out:
            top = out[0]
            runner = out[1].strength if len(out) > 1 else 0.0
            top.strong = (top.strength >= STRONG and top.matched >= STRONG_MATCHED
                          and top.strength - runner >= STRONG_GAP)
        return out

    def feed(self, text: str, now: Optional[float] = None) -> List[Match]:
        """A final utterance. Returns new possible references (best first), or [] when none."""
        if not self.available:
            return []
        now = time.monotonic() if now is None else now
        new = words(text)
        if not new:
            return []
        for w in new:
            self._words.append((now, w, stem(w)))
        self._words = [x for x in self._words[-WINDOW_WORDS:] if now - x[0] <= WINDOW_SECONDS]
        spoken = [w for _t, w, _k in self._words]
        ks = [k for _t, _w, k in self._words]
        first_new = len(spoken) - len(new)
        # only matches the newest words take part in: older words alone are old news
        found = [m for m in self.match(spoken, ks, first_new)
                 if m.strength >= SUGGEST and m.pos not in self.exclude and m.end >= first_new]
        if not found:
            return []  # (an "amen" in the middle of a quote does not end it)
        top = found[0]
        prev, self._best = self._best, ((top.pos, top.matched) if top.strong else None)
        # confirmed: strong last time too, and the newest words made the match longer
        top.confirmed = top.strong and prev is not None and prev[0] == top.pos and top.matched > prev[1]
        if top.confirmed:
            if now - self._sent_live.get(top.pos, -1e9) < REPEAT_SECONDS:
                return []
            self._sent_live[top.pos] = self._last[top.pos] = now
            return found[:TOP]
        if now - self._last.get(top.pos, -1e9) < REPEAT_SECONDS:
            return []
        self._last[top.pos] = now
        return found[:TOP]
