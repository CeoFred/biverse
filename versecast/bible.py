"""Read-only access to the Bible database(s).

The bundled ``data/bible.db`` holds the public-domain translations. A second,
optional database in the user's config folder holds translations imported
with ``tools/import_translation.py``; both are queried transparently.

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

    def close(self) -> None:
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
        """``[(code, name, licence), ...]`` in display order."""
        return list(self._translations)

    def has_translation(self, code: str) -> bool:
        return code in self._by_code

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

    def verse(self, code: str, book: int, chapter: int, verse: int) -> Optional[str]:
        with self._lock:
            row = self._conn(code).execute(
                "SELECT text FROM verses WHERE translation=? AND book=? AND chapter=? AND verse=?",
                (code, book, chapter, verse)).fetchone()
        return row[0] if row else None

    def verses(self, code: str, book: int, chapter: int, start: int, end: int) -> List[Verse]:
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
        """Phrase search: exact phrase matches first, then all-words matches."""
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


def _escape(word: str) -> str:
    return word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def open_default() -> Optional[Bible]:
    from . import paths
    path = paths.bible_db_path()
    if path is None:
        return None
    return Bible(path, paths.user_bible_db_path())
