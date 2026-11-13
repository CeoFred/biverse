from __future__ import annotations

import pytest

from biverse.follow import ReadingFollower, align, words


@pytest.fixture
def follower(bible):
    codes = [c for c, _n, _l in bible.translations()]

    def texts_for(b, c, v):
        return [t for t in (bible.verse(code, b, c, v) for code in codes) if t]

    return ReadingFollower(texts_for, bible.verse_count)


def read(follower, text, t0, per_word=0.3, utterance_words=None, final_at_end=True):
    """Stream ``text`` as growing partials (one word per step). Returns [(time, move)] and end time."""
    ws = text.split()
    moves = []
    t = t0
    utt = []
    for i, w in enumerate(ws):
        utt.append(w)
        t += per_word
        last = i == len(ws) - 1
        m = follower.feed(" ".join(utt), t, final=last and final_at_end)
        if m is not None:
            moves.append((t, i, m))
        if utterance_words and len(utt) >= utterance_words and not last:
            follower.feed(" ".join(utt), t, final=True)
            utt = []
    return moves, t


def test_align_basic():
    pairs = align(words("so loved the world that he gave"), words("For God so loved the world, that he gave"))
    assert [j for _i, j in pairs] == [2, 3, 4, 5, 6, 7, 8]


def test_advances_as_each_verse_ends(follower, bible):
    follower.start(43, 3, 16, range_end=18)
    v16, v17 = bible.verse("KJV", 43, 3, 16), bible.verse("KJV", 43, 3, 17)
    moves, t = read(follower, v16, 0.0)
    assert [m.verse for _t, _i, m in moves] == [17]
    # it switched within the last three words of verse 16 (long verse: one word early, to
    # offset the recogniser's ~0.4 s delay) and not before
    assert len(v16.split()) - 3 <= moves[0][1]
    assert follower.verse == 17  # the follower moved itself
    moves, t = read(follower, v17, t)
    assert [m.verse for _t, _i, m in moves] == [18]


def test_stays_on_last_verse_of_range(follower, bible):
    follower.start(43, 3, 18, range_end=18)
    moves, _t = read(follower, bible.verse("KJV", 43, 3, 18), 0.0)
    assert moves == []


def test_reading_the_next_verse_aloud_moves_past_the_range(follower, bible):
    follower.start(43, 3, 18, range_end=18)
    _m, t = read(follower, bible.verse("KJV", 43, 3, 18), 0.0)
    moves, _t = read(follower, " ".join(bible.verse("KJV", 43, 3, 19).split()[:8]), t + 1.0)
    assert moves and moves[0][2].verse == 19 and moves[0][2].reason == "start"


def test_commentary_does_not_advance(follower):
    follower.start(43, 3, 16)
    moves, _t = read(follower, "now church I want you to notice how much God loves you today amen", 0.0)
    assert moves == []


def test_half_read_verse_does_not_advance(follower, bible):
    follower.start(43, 3, 16)
    v16 = bible.verse("KJV", 43, 3, 16).split()
    moves, _t = read(follower, " ".join(v16[:8]), 0.0)
    assert moves == []


def test_skipped_verse_is_followed(follower, bible):
    follower.start(19, 23, 1)
    moves, _t = read(follower, " ".join(bible.verse("KJV", 19, 23, 3).split()[:6]), 0.0)
    assert moves and moves[0][2].verse == 3 and moves[0][2].reason == "skip"


def test_other_translation_is_followed(follower, bible):
    follower.start(43, 3, 16)
    moves, _t = read(follower, bible.verse("BBE", 43, 3, 16), 0.0)
    assert [m.verse for _t, _i, m in moves] == [17]


def test_paused_does_nothing(follower, bible):
    follower.start(43, 3, 16)
    follower.paused = True
    moves, _t = read(follower, bible.verse("KJV", 43, 3, 16), 0.0)
    assert moves == []


def test_split_utterances_still_followed(follower, bible):
    """The recogniser cuts the reading at short pauses: finals every few words."""
    follower.start(43, 3, 16)
    moves, _t = read(follower, bible.verse("KJV", 43, 3, 16), 0.0, utterance_words=6)
    assert [m.verse for _t, _i, m in moves] == [17]


def test_recogniser_errors_tolerated(follower):
    follower.start(43, 3, 16)
    noisy = ("for god so love the world that he give his only begotten son that whosoever believe in him "
             "should not perish but have ever lasting life")
    moves, _t = read(follower, noisy, 0.0)
    assert [m.verse for _t, _i, m in moves] == [17]
