"""Verses recognised from the preacher's words (biverse/quotes.py)."""

from __future__ import annotations

import os
import sqlite3
import sys

import pytest

from biverse import bible_import, quotes
from biverse.quotes import QuoteMatcher, keys, lcs, stem

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# -- words ----------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [("believeth", "believes"), ("loved", "loves"), ("thee", "you"),
                                 ("thy", "your"), ("hath", "has"), ("saith", "says"), ("unto", "to")])
def test_stem_joins_old_and_spoken_forms(a, b):
    assert stem(a) == stem(b)


def test_keys_lowercase_punctuation_and_numbers():
    assert keys("Jesus wept.") == keys("jesus wept") == [stem("jesus"), "wept"]
    assert keys("John chapter three") == ["john", "chapter", "3"]


def test_lcs():
    assert lcs(list("abcde"), list("xbydz")) == [(1, 1), (3, 3)]
    assert lcs([], ["a"]) == []


# -- the index ------------------------------------------------------------------------

def test_build_index_on_a_small_database(tmp_path):
    from biverse.bible import Bible
    path = str(tmp_path / "t.db")
    conn = sqlite3.connect(path)
    bible_import.create_schema(conn)
    rows = [(b, c, v, "filler words number %d" % v) for b, c, v in bible_import.grid()]
    rows[0] = (1, 1, 1, "In the beginning God created the heaven and the earth.")
    bible_import.write_translation(conn, "TST", "Test", "", rows)
    assert quotes.build_index(conn) > 0
    conn.close()
    b = Bible(path)
    try:
        assert b.has_ngram_index()
        q = QuoteMatcher(b)
        found = q.feed("in the beginning god created the heaven and the earth", now=1.0)
        assert found and found[0].label() == "Genesis 1:1"
        assert found[0].heard == "in the beginning god created the heaven and the earth"
    finally:
        b.close()


def test_without_index_nothing_is_matched(tmp_path):
    from biverse.bible import Bible
    path = str(tmp_path / "t.db")
    conn = sqlite3.connect(path)
    bible_import.create_schema(conn)
    bible_import.write_translation(conn, "TST", "Test", "", [(b, c, v, "x y z") for b, c, v in bible_import.grid()])
    conn.close()
    b = Bible(path)
    try:
        assert not b.has_ngram_index()
        assert QuoteMatcher(b).feed("in the beginning god created the heaven", now=1.0) == []
    finally:
        b.close()


# -- matching the bundled Bible -------------------------------------------------------

@pytest.fixture
def matcher(bible):
    if not bible.has_ngram_index():
        pytest.skip("data/bible.db has no quoted-verse index (rebuild it)")
    return QuoteMatcher(bible)


@pytest.mark.parametrize("spoken,ref", [
    ("for god so loved the world that he gave his only begotten son", "John 3:16"),
    ("the lord is my shepherd i shall not want", "Psalm 23:1"),
    ("trust in the lord with all your heart and lean not on your own understanding", "Proverbs 3:5"),
    ("be still and know that i am god", "Psalm 46:10"),
    ("i can do all things through christ which strengthens me", "Philippians 4:13"),   # modern "-s"
    ("for all have sinned and come short of the glory of god", "Romans 3:23"),
    ("god is faithful and he will never leave you nor forsake you", "Hebrews 13:5"),   # paraphrase
])
def test_famous_quotes_are_found(matcher, spoken, ref):
    found = matcher.feed(spoken, now=1.0)
    assert found and found[0].label() == ref


@pytest.mark.parametrize("spoken", [
    "this morning we are going to talk about the children of israel and the land of promise",
    "my brothers and sisters the lord will make a way where there seems to be no way",
    "gideon was hiding in a winepress when the angel called him a mighty man of valour",   # stock phrase
    "the house of israel and the house of judah were divided",                              # stock phrase
    "and the lord said unto moses speak unto the children of israel",                      # stock phrase
    "jesus wept",                                                                           # too short
])
def test_sermon_talk_is_not_a_quote(matcher, spoken):
    assert matcher.feed(spoken, now=1.0) == []


def test_quote_split_over_two_utterances(matcher):
    assert matcher.feed("the bible says the thief cometh not but for to", now=1.0) == []
    found = matcher.feed("steal and to kill and to destroy", now=4.0)
    assert found[0].label() == "John 10:10"


def test_old_words_alone_do_not_suggest_again_later(matcher):
    assert matcher.feed("for god so loved the world that he gave his only begotten son", now=1.0)
    assert matcher.feed("nineteen years old", now=5.0) == []


def test_not_repeated_within_two_minutes(matcher):
    text = "rejoice in the lord always and again i say rejoice"
    assert matcher.feed(text, now=1.0)
    assert matcher.feed(text, now=60.0) == []
    assert matcher.feed(text, now=200.0)


def test_verses_on_screen_are_not_suggested(matcher):
    matcher.exclude = {(43, 3, 16)}
    found = matcher.feed("for god so loved the world that he gave his only begotten son", now=1.0)
    assert all(m.label() != "John 3:16" for m in found)


def test_confirmed_only_when_the_quote_grows(matcher):
    first = matcher.feed("and we know that all things work together for good to them that love god", now=1.0)
    assert first[0].label() == "Romans 8:28" and first[0].strong and not first[0].confirmed
    assert matcher.feed("amen", now=4.0) == []  # nothing new, and the quote is not over
    more = matcher.feed("to them who are the called according to his purpose", now=8.0)
    assert more[0].label() == "Romans 8:28" and more[0].confirmed
    assert matcher.feed("according to his purpose", now=12.0) == []  # confirmed once is enough


def test_auto_live_is_locked_until_tested_on_real_sermons():
    assert quotes.AUTO_LIVE_ALLOWED is False


# -- the benchmark --------------------------------------------------------------------

def test_benchmark_on_generated_transcripts(bible):
    if not bible.has_ngram_index():
        pytest.skip("data/bible.db has no quoted-verse index (rebuild it)")
    sys.path.insert(0, ROOT)
    from tools import bench_quotes
    total = bench_quotes.Result("total")
    for name in ("generated-famous.txt", "generated-random.txt", "generated-talk.txt"):
        total.add(bench_quotes.run_file(os.path.join(bench_quotes.DATA, name), bible))
    assert total.quotes == 191
    assert total.found / float(total.quotes) >= 0.90, total.summary()
    assert total.false_per_1000 <= 1.0, total.summary()
    assert total.false_live == [], total.summary()


def test_benchmark_reads_labels(bible, tmp_path):
    sys.path.insert(0, ROOT)
    from tools import bench_quotes
    path = tmp_path / "t.txt"
    path.write_text("# comment\nhello there\nfor god so loved the world   => John 3:16-17\nok   => ~Psalm 23:1\n")
    lines, labelled = bench_quotes.read(str(path), bible)
    assert labelled and [len(x.refs) for x in lines] == [0, 2, 0] and lines[2].loose == {(19, 23, 1)}
    raw = tmp_path / "raw.txt"
    raw.write_text(" ".join(["word"] * 30) + "\n")
    lines, labelled = bench_quotes.read(str(raw), bible)
    assert not labelled and [len(x.text.split()) for x in lines] == [12, 12, 6]
