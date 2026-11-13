"""Importing translations into a Biverse SQLite database.

Shared by ``tools/build_bible_db.py`` (bundled public-domain texts) and
``tools/import_translation.py`` (a translation a church holds a licence for).

Input rows are ``(book_number, chapter, verse, text)``. They are mapped onto
the KJV verse grid (``versification.py``): verses outside the grid are
appended to the last verse of their chapter, missing verses are stored empty.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .versification import VERSE_COUNTS

TOTAL_VERSES = sum(sum(chs) for chs in VERSE_COUNTS)  # 31,102 (KJV grid)

SCHEMA = """
CREATE TABLE IF NOT EXISTS translations(
    code TEXT PRIMARY KEY, name TEXT, license TEXT);
CREATE TABLE IF NOT EXISTS verses(
    translation TEXT, book INTEGER, chapter INTEGER, verse INTEGER, text TEXT,
    PRIMARY KEY(translation, book, chapter, verse));
CREATE TABLE IF NOT EXISTS chapters(
    book INTEGER, chapter INTEGER, verse_count INTEGER, PRIMARY KEY(book, chapter));
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

Row = Tuple[int, int, int, str]


def clean_text(text: str) -> str:
    """Strip markup, pilcrows and editorial brackets; normalise whitespace."""
    text = text.replace(u"¶", " ")
    text = re.sub(r"<[^>]*>", " ", text)          # stray HTML/XML tags
    text = re.sub(r"\{[^}]*\}", " ", text)         # {notes}
    text = text.replace("[", "").replace("]", "")  # KJV italics / ASV "[Selah"
    text = text.replace("***", u"…")          # BBE marks unclear text with ***
    text = text.replace("`", "'")                  # YLT opening quotes
    text = re.sub(r"(?<=\w)--(?=\w)", u"—", text)
    text = text.replace("--", u"—")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:?!])", r"\1", text)
    return text


def grid() -> Iterator[Tuple[int, int, int]]:
    for b, chapters in enumerate(VERSE_COUNTS, 1):
        for c, n in enumerate(chapters, 1):
            for v in range(1, n + 1):
                yield b, c, v


def fit_to_grid(rows: Iterable[Row]) -> Tuple[Dict[Tuple[int, int, int], str], List[str]]:
    """Map rows onto the KJV grid. Returns (texts, warnings)."""
    texts = {}
    warnings = []
    extras = []
    for b, c, v, t in rows:
        t = clean_text(t)
        if not 1 <= b <= 66:
            raise ValueError("book number out of range: %r" % b)
        chs = VERSE_COUNTS[b - 1]
        if 1 <= c <= len(chs) and 1 <= v <= chs[c - 1]:
            key = (b, c, v)
            texts[key] = (texts[key] + " " + t).strip() if key in texts else t
        else:
            extras.append((b, c, v, t))
    for b, c, v, t in extras:
        chs = VERSE_COUNTS[b - 1]
        if 1 <= c <= len(chs):
            key = (b, c, chs[c - 1])
            texts[key] = (texts.get(key, "") + " " + t).strip()
            warnings.append("%d %d:%d is outside the KJV verse grid; appended to %d:%d" % (b, c, v, c, chs[c - 1]))
        else:
            warnings.append("%d %d:%d dropped: chapter not in the KJV grid" % (b, c, v))
    missing = [k for k in grid() if k not in texts]
    if missing:
        warnings.append("%d verses missing; stored empty (first: %r)" % (len(missing), missing[:3]))
    return texts, warnings


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT OR REPLACE INTO chapters(book, chapter, verse_count) VALUES (?,?,?)",
        [(b, c, n) for b, chs in enumerate(VERSE_COUNTS, 1) for c, n in enumerate(chs, 1)],
    )


def write_translation(conn: sqlite3.Connection, code: str, name: str, license: str,
                      rows: Iterable[Row]) -> List[str]:
    code = code.upper()
    if not re.match(r"^[A-Z0-9_-]{1,16}$", code):
        raise ValueError("translation code must be 1-16 letters/digits, got %r" % code)
    texts, warnings = fit_to_grid(rows)
    if sum(1 for t in texts.values() if t) < 0.9 * TOTAL_VERSES:
        raise ValueError("%s: only %d verses with text, expected about %d" % (code, len(texts), TOTAL_VERSES))
    create_schema(conn)
    with conn:
        conn.execute("DELETE FROM verses WHERE translation=?", (code,))
        conn.execute("INSERT OR REPLACE INTO translations(code, name, license) VALUES (?,?,?)",
                     (code, name, license))
        conn.executemany(
            "INSERT INTO verses(translation, book, chapter, verse, text) VALUES (?,?,?,?,?)",
            ((code, b, c, v, texts.get((b, c, v), "")) for b, c, v in grid()),
        )
    n = conn.execute("SELECT COUNT(*) FROM verses WHERE translation=?", (code,)).fetchone()[0]
    assert n == TOTAL_VERSES, (code, n)
    return warnings


# -- input formats -------------------------------------------------------------

def rows_from_book_order_csv(data: str) -> List[Row]:
    """scrollmapper-style CSV: ``Book,Chapter,Verse,Text`` with book *names*.

    Books are numbered by order of first appearance (they appear in canonical
    order), not by name, because names vary ("I Samuel", "Revelation of John").
    """
    reader = csv.DictReader(io.StringIO(data))
    _require_columns(reader.fieldnames, ("Book", "Chapter", "Verse", "Text"))
    order = {}
    rows = []
    for rec in reader:
        name = rec["Book"].strip()
        if name not in order:
            order[name] = len(order) + 1
        rows.append((order[name], int(rec["Chapter"]), int(rec["Verse"]), rec["Text"] or ""))
    if len(order) != 66:
        raise ValueError("expected 66 books, found %d" % len(order))
    return rows


def _require_columns(fieldnames: Optional[List[str]], needed: Tuple[str, ...]) -> None:
    have = [f.strip() for f in (fieldnames or [])]
    for col in needed:
        if col not in have:
            raise ValueError("missing column %r (have %r)" % (col, have))


def rows_from_csv(data: str) -> List[Row]:
    """CSV with ``Book,Chapter,Verse,Text``; Book is 1-66 or a name in canonical order."""
    reader = csv.DictReader(io.StringIO(data))
    _require_columns(reader.fieldnames, ("Book", "Chapter", "Verse", "Text"))
    recs = list(reader)
    if recs and recs[0]["Book"].strip().isdigit():
        return [(int(r["Book"]), int(r["Chapter"]), int(r["Verse"]), r["Text"] or "") for r in recs]
    return rows_from_book_order_csv(data)


def rows_from_json(data: str) -> List[Row]:
    """JSON list of ``{"book": 1-66, "chapter": n, "verse": n, "text": "..."}``."""
    items = json.loads(data)
    if isinstance(items, dict):
        items = items.get("verses", [])
    return [(int(i["book"]), int(i["chapter"]), int(i["verse"]), str(i["text"])) for i in items]


def rows_from_vpl(data: str) -> List[Row]:
    """eBible.org "verse per line" text: ``GEN 1:1 In the beginning...``."""
    order = {}
    rows = []
    for line in data.splitlines():
        m = re.match(r"^(\S+) (\d+):(\d+) ?(.*)$", line.strip())
        if not m:
            continue
        code = m.group(1)
        if code not in order:
            order[code] = len(order) + 1
        rows.append((order[code], int(m.group(2)), int(m.group(3)), m.group(4)))
    if len(order) != 66:
        raise ValueError("expected 66 books, found %d" % len(order))
    return rows
