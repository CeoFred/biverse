from __future__ import annotations

import sqlite3
import time

import pytest

from versecast import bible_import
from versecast.parser import parse_typed

KJV_JOHN_3_16 = ("For God so loved the world, that he gave his only begotten Son, that whosoever "
                 "believeth in him should not perish, but have everlasting life.")


def test_translations_present(bible):
    codes = [c for c, _, _ in bible.translations()]
    for code in ("KJV", "ASV", "YLT", "BBE"):
        assert code in codes
    assert codes[0] == "KJV"
    assert bible.default_translation() == "KJV"


def test_every_translation_complete(bible):
    for code, _, lic in bible.translations():
        assert bible.total_verses(code) == 31102, code
        assert lic == "Public domain"


def test_john_3_16(bible):
    assert bible.verse("KJV", 43, 3, 16) == KJV_JOHN_3_16


def test_cleanup(bible):
    # KJV italics brackets, pilcrows and markup are gone
    conn = sqlite3.connect(bible.path)
    for pattern in ("%[%", "%]%", u"%¶%", "%<%", "%{%", "%`%"):
        n = conn.execute("SELECT COUNT(*) FROM verses WHERE text LIKE ?", (pattern,)).fetchone()[0]
        assert n == 0, pattern
    assert "[but]" not in bible.verse("KJV", 62, 2, 23)


def test_range(bible):
    vs = bible.reference_verses("KJV", parse_typed("1 cor 13:4-7"))
    assert [v.verse for v in vs] == [4, 5, 6, 7]
    assert vs[0].label() == "1 Corinthians 13:4"


def test_chapter(bible):
    assert len(bible.chapter("KJV", 19, 119)) == 176
    assert bible.verse_count(19, 119) == 176
    assert bible.chapter_count(19) == 150
    assert bible.verse_count(43, 30) == 0


@pytest.mark.parametrize("pos,nxt", [
    ((43, 3, 16), (43, 3, 17)),
    ((43, 3, 36), (43, 4, 1)),      # chapter boundary
    ((1, 50, 26), (2, 1, 1)),       # book boundary
    ((39, 4, 6), (40, 1, 1)),       # testament boundary
    ((66, 22, 21), None),           # end of the Bible
])
def test_next(bible, pos, nxt):
    assert bible.next_pos(pos) == nxt


@pytest.mark.parametrize("pos,prev", [
    ((43, 3, 16), (43, 3, 15)),
    ((43, 4, 1), (43, 3, 36)),
    ((2, 1, 1), (1, 50, 26)),
    ((40, 1, 1), (39, 4, 6)),
    ((1, 1, 1), None),
])
def test_prev(bible, pos, prev):
    assert bible.prev_pos(pos) == prev


def test_search_finds_john_3_16(bible):
    results = bible.search("KJV", "so loved the world")
    assert results and results[0].pos() == (43, 3, 16)


def test_search_words_any_order(bible):
    results = bible.search("KJV", "world loved")
    assert (43, 3, 16) in [r.pos() for r in results]


def test_search_limit_and_speed(bible):
    t = time.perf_counter()
    results = bible.search("KJV", "lord")
    elapsed = time.perf_counter() - t
    assert len(results) == 50
    assert elapsed < 1.0


def test_search_case_and_punctuation(bible):
    assert bible.search("KJV", "For God, SO loved!")[0].pos() == (43, 3, 16)
    assert bible.search("KJV", "%") == []
    assert bible.search("KJV", "   ") == []
    assert bible.search("KJV", "zzzqqq") == []


def test_unknown_translation(bible):
    with pytest.raises(KeyError):
        bible.verse("NIV", 1, 1, 1)


# -- importing -------------------------------------------------------------------

def _fake_rows(text="x"):
    return [(b, c, v, "%s %d %d %d" % (text, b, c, v)) for b, c, v in bible_import.grid()]


def test_import_translation_into_user_db(tmp_path):
    from versecast.bible import Bible
    main = str(tmp_path / "main.db")
    user = str(tmp_path / "user.db")
    conn = sqlite3.connect(main)
    bible_import.write_translation(conn, "AAA", "Main", "Public domain", _fake_rows("a"))
    conn.close()
    conn = sqlite3.connect(user)
    bible_import.write_translation(conn, "mine", "Licensed", "Licensed", _fake_rows("m"))
    conn.close()
    b = Bible(main, user)
    assert [c for c, _, _ in b.translations()] == ["AAA", "MINE"]
    assert b.verse("MINE", 43, 3, 16) == "m 43 3 16"
    b.close()


def test_import_tool_csv(tmp_path):
    import tools.import_translation as tool
    csv_path = tmp_path / "t.csv"
    lines = ["Book,Chapter,Verse,Text"] + ['%d,%d,%d,"Verse, %d"' % (b, c, v, v) for b, c, v in bible_import.grid()]
    csv_path.write_text("\n".join(lines), encoding="utf-8")
    db = str(tmp_path / "u.db")
    assert tool.run(["TST", "Test", str(csv_path), "--db", db]) == 0
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT text FROM verses WHERE translation='TST' AND book=1 AND chapter=1 AND verse=2"
                        ).fetchone()[0] == "Verse, 2"
    assert tool.run(["TST", "Test", str(csv_path), "--db", db, "--remove"]) == 0


def test_import_rejects_incomplete(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "x.db"))
    with pytest.raises(ValueError):
        bible_import.write_translation(conn, "BAD", "Bad", "", [(1, 1, 1, "only one")])


@pytest.mark.parametrize("raw,clean", [
    (u"¶ And it came to pass", "And it came to pass"),
    ("the Son [but] he that", "the Son but he that"),
    ("of his holy hill. [Selah", "of his holy hill. Selah"),
    ("saith, `Let light be;'", "saith, 'Let light be;'"),
    ("Son--the only begotten--He", u"Son—the only begotten—He"),
    ("<i>word</i>  here", "word here"),
    ("text {note} more", "text more"),
])
def test_clean_text(raw, clean):
    assert bible_import.clean_text(raw) == clean
