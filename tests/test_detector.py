from __future__ import annotations

from biverse.detector import NEW, UPDATE, Detector


def labels(events):
    return [(kind, det.ref.label()) for kind, det in events]


def test_single_detection():
    d = Detector()
    assert labels(d.feed_final("turn to john three sixteen", now=0)) == [(NEW, "John 3:16")]


def test_dedupe_within_window():
    d = Detector()
    d.feed_final("john three sixteen", now=0)
    assert d.feed_final("as john three sixteen says", now=30) == []
    assert d.feed_final("again john three sixteen", now=59) == []


def test_dedupe_expires():
    d = Detector()
    d.feed_final("john three sixteen", now=0)
    d.feed_final("hello there friends welcome to church today we have a word", now=10)
    assert labels(d.feed_final("john three sixteen", now=75)) == [(NEW, "John 3:16")]


def test_range_extension():
    d = Detector()
    (kind, det), = d.feed_final("john three sixteen", now=0)
    events = d.feed_final("john three sixteen to eighteen", now=10)
    assert labels(events) == [(UPDATE, "John 3:16-18")]
    assert events[0][1].id == det.id
    assert len(d.detections) == 1


def test_range_extension_too_late_is_new():
    d = Detector()
    d.feed_final("john three sixteen", now=0)
    d.feed_final("one two three four five six seven eight nine ten eleven twelve", now=20)
    events = d.feed_final("john three sixteen to eighteen", now=45)
    assert labels(events) == [(NEW, "John 3:16-18")]


def test_chapter_then_verse_updates():
    d = Detector()
    assert labels(d.feed_final("open your bibles to john chapter three", now=0)) == [(NEW, "John 3")]
    assert labels(d.feed_final("verse sixteen", now=3)) == [(UPDATE, "John 3:16")]
    assert len(d.detections) == 1


def test_chapter_only_after_verse_is_ignored():
    d = Detector()
    d.feed_final("john three sixteen", now=0)
    d.feed_final("blah blah blah blah blah blah blah blah blah blah blah blah", now=1)
    assert d.feed_final("john chapter three", now=5) == []


def test_split_across_pause():
    d = Detector()
    assert d.feed_final("our text today is from romans chapter", now=0) == []
    assert labels(d.feed_final("eight verse twenty eight", now=2)) == [(NEW, "Romans 8:28")]


def test_context_refs_not_repeated():
    d = Detector(dedupe_window=0.5)
    d.feed_final("john three sixteen", now=0)
    # The previous words are context only; nothing new must be reported.
    assert d.feed_final("is a famous verse", now=10) == []


def test_relative_verse_uses_last_detection():
    d = Detector()
    d.feed_final("romans eight twenty eight", now=0)
    d.feed_final("and we know that all things work together for good to them", now=5)
    events = d.feed_final("now look at verse thirty one", now=20)
    assert labels(events) == [(NEW, "Romans 8:31")]
    assert events[0][1].ref.relative


def test_relative_range():
    d = Detector()
    d.feed_final("john three sixteen", now=0)
    d.feed_final("blah blah blah blah blah blah blah blah blah blah blah blah", now=1)
    events = d.feed_final("verses seventeen to eighteen", now=40)
    assert labels(events) == [(NEW, "John 3:17-18")]


def test_relative_expires_after_five_minutes():
    d = Detector()
    d.feed_final("john three sixteen", now=0)
    d.feed_final("blah blah blah blah blah blah blah blah blah blah blah blah", now=1)
    assert d.feed_final("verse seventeen", now=301) == []


def test_relative_without_context():
    d = Detector()
    assert d.feed_final("verse seventeen", now=0) == []


def test_relative_invalid_verse():
    d = Detector()
    d.feed_final("jude chapter one verse three", now=0)
    d.feed_final("blah blah blah blah blah blah blah blah blah blah blah blah", now=1)
    assert d.feed_final("verse ninety", now=5) == []


def test_relative_disabled():
    d = Detector(relative=False)
    d.feed_final("john three sixteen", now=0)
    assert d.feed_final("verse seventeen", now=5) == []


def test_multiple_in_one_result():
    d = Detector()
    events = d.feed_final("romans eight twenty eight and also john three sixteen", now=0)
    assert labels(events) == [(NEW, "Romans 8:28"), (NEW, "John 3:16")]


def test_strict_option_passes_through():
    d = Detector(strict=False)
    assert labels(d.feed_final("mark two", now=0)) == [(NEW, "Mark 2")]
    d2 = Detector()
    assert d2.feed_final("mark two", now=0) == []


def test_empty_text():
    assert Detector().feed_final("", now=0) == []


# -- reference-only recogniser channel ------------------------------------------------

def test_reference_channel_accepts_chapter_and_verse():
    from biverse.detector import REFERENCE
    d = Detector()
    events = d.feed_final("[unk] genesys two eighteen [unk]", now=0, channel=REFERENCE)
    assert labels(events) == [(NEW, "Genesis 2:18")]


def test_reference_channel_rejects_chapter_only_and_relative():
    from biverse.detector import REFERENCE
    d = Detector()
    assert d.feed_final("[unk] micah three", now=0, channel=REFERENCE) == []
    assert d.feed_final("[unk] mathew thirteen [unk]", now=1, channel=REFERENCE) == []
    d.feed_final("john three sixteen", now=2)
    assert d.feed_final("fourteen verses three", now=3, channel=REFERENCE) == []


def test_both_channels_dedupe_and_extend():
    from biverse.detector import REFERENCE
    d = Detector()
    assert labels(d.feed_final("genesis to a team", now=0)) == []
    assert labels(d.feed_final("genesys two eighteen", now=0.1, channel=REFERENCE)) == [(NEW, "Genesis 2:18")]
    assert d.feed_final("genesis two eighteen", now=0.2) == []  # same reference from the other channel
    events = d.feed_final("genesys two eighteen to twenty", now=5, channel=REFERENCE)
    assert labels(events) == [(UPDATE, "Genesis 2:18-20")]


def test_channels_keep_separate_context():
    from biverse.detector import REFERENCE
    d = Detector()
    d.feed_final("our text is romans chapter", now=0)
    d.feed_final("[unk] [unk]", now=0.1, channel=REFERENCE)
    assert labels(d.feed_final("eight verse twenty eight", now=1)) == [(NEW, "Romans 8:28")]


# -- on-screen position for relative verses ---------------------------------------

def test_relative_verse_uses_on_screen_position():
    d = Detector()
    d.feed_final("john three sixteen", now=0)
    d.feed_final("blah blah blah blah blah blah blah blah blah blah blah blah", now=1)
    d.set_position(43, 4, now=10)  # operator / voice moved to John 4
    assert labels(d.feed_final("move to verse eight", now=12)) == [(NEW, "John 4:8")]


def test_position_alone_is_enough_context():
    d = Detector()
    d.set_position(19, 23, now=0)
    assert labels(d.feed_final("go to verse four", now=5)) == [(NEW, "Psalm 23:4")]


def test_newer_detection_beats_older_position():
    d = Detector()
    d.set_position(19, 23, now=0)
    d.feed_final("romans eight twenty eight", now=5)
    d.feed_final("blah blah blah blah blah blah blah blah blah blah blah blah", now=6)
    assert labels(d.feed_final("verse thirty", now=8)) == [(NEW, "Romans 8:30")]


def test_old_position_expires():
    d = Detector()
    d.set_position(19, 23, now=0)
    assert d.feed_final("verse four", now=400) == []


def test_book_less_chapter_and_verse_uses_book_on_screen():
    d = Detector()
    d.set_position(1, 10, now=0)  # Genesis 10 on screen
    assert labels(d.feed_final("now turn to chapter four verse two", now=1)) == [(NEW, "Genesis 4:2")]
    assert labels(d.feed_final("and in chapter three verse fifteen", now=2)) == [(NEW, "Genesis 3:15")]


def test_book_less_chapter_rejected_after_unknown_word():
    d = Detector()
    d.set_position(1, 10, now=0)
    assert d.feed_final("Ruke chapter 3 verse 5", now=1) == []
