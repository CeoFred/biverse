"""Read-only access to the Bible database(s).

The bundled ``data/bible.db`` holds the public-domain translations. A second,
optional database in the user's config folder holds translations imported
with ``tools/import_translation.py``; both are queried transparently. Online
versions from YouVersion (``online_bible.OnlineBibles``) are added with
``set_online``; ``resolve`` swaps one for the fallback translation when it cannot
be reached.

Phrase search uses word-wise ``LIKE`` matching (about 20-40 ms over 31k rows)
because FTS5/FTS4 are missing from some Python 3.8 SQLite builds.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
from typing import List, Optional, Tuple

from . import books
from .parser import Reference

if False:  # pragma: no cover - typing only
    from .online_bible import OnlineBibles

Pos = Tuple[int, int, int]  # book, chapter, verse

FIRST = (1, 1, 1)
LAST = (66, 22, 21)


class Verse(object):
    __slots__ = ("book", "chapter", "verse", "text")

    def __init__(self, book: int, chapter: int, verse: int, text: str) -> None:
        self.book = book
        self.chapter = chapter
        self.verse = verse
        self.text = text

    def pos(self) -> Pos:
        return (self.book, self.chapter, self.verse)

    def label(self) -> str:
        return "%s %d:%d" % (books.get(self.book).ref_name, self.chapter, self.verse)

    def __repr__(self) -> str:  # pragma: no cover
        return "Verse(%s)" % self.label()


def _connect_ro(path: str) -> sqlite3.Connection:
    uri = "file:%s?mode=ro" % path.replace("\\", "/").replace("?", "%3f").replace("#", "%23")
    if re.match(r"^[A-Za-z]:", path):  # Windows drive letter
        uri = "file:/%s?mode=ro" % path.replace("\\", "/")
    try:
        conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        conn.execute("SELECT 1 FROM verses LIMIT 1")
        return conn
    except sqlite3.Error:
        return sqlite3.connect(path, check_same_thread=False)


class Bible(object):
    def __init__(self, path: str, user_path: Optional[str] = None) -> None:
        if not path or not os.path.isfile(path):
            raise FileNotFoundError("Bible database not found: %r" % path)
        self.path = path
        self._lock = threading.Lock()
        self._conns = [_connect_ro(path)]
        if user_path and os.path.isfile(user_path):
            try:
                self._conns.append(_connect_ro(user_path))
            except sqlite3.Error:
                pass
        self._by_code = {}
        self._translations = []
        for conn in self._conns:
            for code, name, lic in conn.execute("SELECT code, name, license FROM translations"):
                if code not in self._by_code:
                    self._by_code[code] = conn
                    self._translations.append((code, name, lic))
        order = self._meta("order")
        if order:
            rank = {c: i for i, c in enumerate(order.split(","))}
            self._translations.sort(key=lambda t: rank.get(t[0], 999))
        self._counts = {}
        for b, c, n in self._conns[0].execute("SELECT book, chapter, verse_count FROM chapters"):
            self._counts[(b, c)] = n
        self._chapters = {}
        for (b, c) in self._counts:
            self._chapters[b] = max(self._chapters.get(b, 0), c)
        self.online = None  # type: Optional[OnlineBibles]
        self.fallback = ""  # local translation shown when an online one cannot be reached

    def set_online(self, online: Optional["OnlineBibles"]) -> None:
        """Use these online versions (None: none). Codes that clash with a local
        translation are left out; the local one wins."""
        old, self.online = self.online, online
        if old is not None and old is not online:
            old.close()

    def close(self) -> None:
        self.set_online(None)
        for conn in self._conns:
            conn.close()

    def _meta(self, key: str) -> Optional[str]:
        try:
            row = self._conns[0].execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        except sqlite3.Error:
            return None
        return row[0] if row else None

    # -- structure ----------------------------------------------------------
    def translations(self) -> List[Tuple[str, str, str]]:
        """``[(code, name, licence), ...]`` in display order: local ones, then online ones."""
        out = list(self._translations)
        if self.online is not None:
            out.extend((v.code, v.name, v.licence()) for v in list(self.online.versions.values())
                       if v.code not in self._by_code)
        return out

    def local_codes(self) -> List[str]:
        """Translations on this computer (no network needed)."""
        return [t[0] for t in self._translations]

    def is_online(self, code: str) -> bool:
        return code not in self._by_code and self.online is not None and self.online.has(code)

    def has_translation(self, code: str) -> bool:
        return code in self._by_code or self.is_online(code)

    def fallback_translation(self) -> str:
        return self.fallback if self.fallback in self._by_code else self.default_translation()

    def resolve(self, code: str, book: int, chapter: int) -> str:
        """The translation to show for this chapter: ``code``, or the fallback when
        ``code`` is an online version that cannot be had right now (or is unknown)."""
        if code in self._by_code:
            return code
        if self.is_online(code) and self._online_verses(code, book, chapter):
            return code
        return self.fallback_translation()

    def prefetch(self, code: str, book: int, chapter: int) -> None:
        """Start fetching an online chapter in the background."""
        if self.is_online(code) and 1 <= chapter <= self.chapter_count(book):
            self.online.prefetch(code, book, chapter)

    def default_translation(self) -> str:
        return "KJV" if "KJV" in self._by_code else self._translations[0][0]

    def verse_count(self, book: int, chapter: int) -> int:
        return self._counts.get((book, chapter), 0)

    def chapter_count(self, book: int) -> int:
        return self._chapters.get(book, 0)

    def total_verses(self, code: str) -> int:
        with self._lock:
            return self._conn(code).execute(
                "SELECT COUNT(*) FROM verses WHERE translation=?", (code,)).fetchone()[0]

    # -- lookup -------------------------------------------------------------
    def _conn(self, code: str) -> sqlite3.Connection:
        try:
            return self._by_code[code]
        except KeyError:
            raise KeyError("unknown translation %r" % code)

    def _online_verses(self, code: str, book: int, chapter: int) -> dict:
        """While the client is offline, never wait on the network: retry in the
        background and answer from the cache."""
        from .online_bible import OFFLINE
        online = self.online
        if online.state == OFFLINE:
            online.prefetch(code, book, chapter)
            return online.cached(code, book, chapter) or {}
        return online.chapter(code, book, chapter) or {}

    def verse(self, code: str, book: int, chapter: int, verse: int) -> Optional[str]:
        if self.is_online(code):
            return self._online_verses(code, book, chapter).get(verse) or None
        with self._lock:
            row = self._conn(code).execute(
                "SELECT text FROM verses WHERE translation=? AND book=? AND chapter=? AND verse=?",
                (code, book, chapter, verse)).fetchone()
        return row[0] if row else None

    def verses(self, code: str, book: int, chapter: int, start: int, end: int) -> List[Verse]:
        if self.is_online(code):
            got = self._online_verses(code, book, chapter)
            return [Verse(book, chapter, v, got[v]) for v in sorted(got) if start <= v <= end and got[v]]
        with self._lock:
            rows = self._conn(code).execute(
                "SELECT verse, text FROM verses WHERE translation=? AND book=? AND chapter=? "
                "AND verse BETWEEN ? AND ? ORDER BY verse", (code, book, chapter, start, end)).fetchall()
        return [Verse(book, chapter, v, t) for v, t in rows]

    def chapter(self, code: str, book: int, chapter: int) -> List[Verse]:
        return self.verses(code, book, chapter, 1, 999)

    def reference_verses(self, code: str, ref: Reference) -> List[Verse]:
        assert ref.book is not None and ref.chapter is not None
        return self.verses(code, ref.book, ref.chapter, ref.verse_start, ref.verse_end)

    # -- navigation ---------------------------------------------------------
    def next_pos(self, pos: Pos) -> Optional[Pos]:
        b, c, v = pos
        if v < self.verse_count(b, c):
            return (b, c, v + 1)
        if c < self.chapter_count(b):
            return (b, c + 1, 1)
        if b < 66:
            return (b + 1, 1, 1)
        return None

    def prev_pos(self, pos: Pos) -> Optional[Pos]:
        b, c, v = pos
        if v > 1:
            return (b, c, v - 1)
        if c > 1:
            return (b, c - 1, self.verse_count(b, c - 1))
        if b > 1:
            last = self.chapter_count(b - 1)
            return (b - 1, last, self.verse_count(b - 1, last))
        return None

    # -- search -------------------------------------------------------------
    def search(self, code: str, phrase: str, limit: int = 50) -> List[Verse]:
        """Phrase search: exact phrase matches first, then all-words matches.
        Online versions cannot be searched; search ``search_code(code)`` instead."""
        phrase = phrase.strip()
        words = [w for w in re.split(r"[^\w]+", phrase.lower(), flags=re.UNICODE) if w]
        if not words:
            return []
        conn = self._conn(code)
        results = []
        seen = set()

        def run(where: str, params: List[str]) -> None:
            if len(results) >= limit:
                return
            sql = ("SELECT book, chapter, verse, text FROM verses WHERE translation=? AND " + where +
                   " ORDER BY book, chapter, verse LIMIT ?")
            with self._lock:
                rows = conn.execute(sql, [code] + params + [limit * 2]).fetchall()
            for b, c, v, t in rows:
                if (b, c, v) in seen:
                    continue
                seen.add((b, c, v))
                results.append(Verse(b, c, v, t))
                if len(results) >= limit:
                    return

        # 1. the phrase as typed (ignoring punctuation between words)
        run("text LIKE ? ESCAPE '\\'", ["%" + "%".join(_escape(w) for w in words) + "%"])
        # 2. every word, anywhere in the verse
        run(" AND ".join(["text LIKE ? ESCAPE '\\'"] * len(words)), ["%" + _escape(w) + "%" for w in words])
        return results[:limit]


    # -- quoted verses (quotes.py) --------------------------------------------
    def has_ngram_index(self) -> bool:
        return bool(self._ngram_conns())

    def _ngram_conns(self) -> List[sqlite3.Connection]:
        conns = getattr(self, "_ngram_cache", None)
        if conns is None:
            conns = []
            for conn in self._conns:
                try:
                    with self._lock:
                        row = conn.execute("SELECT value FROM meta WHERE key='ngram_index'").fetchone()
                    if row:
                        from .quotes import INDEX_VERSION
                        row = row if row[0] == INDEX_VERSION else None
                except sqlite3.Error:
                    row = None
                if row:
                    conns.append(conn)
            self._ngram_cache = conns
        return conns

    def stem_counts(self) -> dict:
        """Verses containing each word stem (the larger count where two databases have it)."""
        out = {}  # type: dict
        for conn in self._ngram_conns():
            with self._lock:
                rows = conn.execute("SELECT key, df FROM stems").fetchall()
            for k, n in rows:
                if n > out.get(k, 0):
                    out[k] = n
        return out

    def ngram_postings(self, buckets: List[int], keep_order: bool = False):
        """Verse numbers (``quotes.Grid``) listed under each 3-gram bucket.

        With ``keep_order`` the result has one entry per bucket, in order (several
        databases merged); otherwise one entry per stored row.
        """
        from .quotes import unpack
        found = {}  # type: dict
        out = []
        for conn in self._ngram_conns():
            for start in range(0, len(buckets), 500):
                chunk = buckets[start:start + 500]
                sql = "SELECT bucket, refs FROM ngrams WHERE bucket IN (%s)" % ",".join("?" * len(chunk))
                with self._lock:
                    rows = conn.execute(sql, chunk).fetchall()
                for h, blob in rows:
                    refs = unpack(blob)
                    out.append(refs)
                    if keep_order:
                        found.setdefault(h, set()).update(refs)
        if keep_order:
            return [found.get(h, set()) for h in buckets]
        return out

    def search_code(self, code: str) -> str:
        """The translation a search in ``code`` runs in (online ones use the fallback)."""
        return code if code in self._by_code else self.fallback_translation()


def _escape(word: str) -> str:
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def open_default() -> Optional[Bible]:
    from . import paths
    path = paths.bible_db_path()
    if path is None:
        return None
    return Bible(path, paths.user_bible_db_path())
