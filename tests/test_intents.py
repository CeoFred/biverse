"""How preachers ask for the next verse, the previous one, another chapter, or to stop/continue.

Positives must produce exactly the intent; negatives (everyday sermon sentences)
must produce nothing. Add real phrasings from recordings here.
"""

from __future__ import annotations

import pytest

from biverse.commands import CHAPTER, GOTO, RESUME, STEP, STOP, VERSE, Intent, parse_intent

NEXT = Intent(STEP, VERSE, 1)
PREV = Intent(STEP, VERSE, -1)
NEXT_CH = Intent(STEP, CHAPTER, 1)
PREV_CH = Intent(STEP, CHAPTER, -1)


def back(n, unit=VERSE):
    return Intent(STEP, unit, -n)


def fwd(n, unit=VERSE):
    return Intent(STEP, unit, n)


def chap(c, v=None):
    return Intent(GOTO, CHAPTER, chapter=c, verse=v)


POSITIVE = [
    # next verse
    ("next verse", NEXT), ("Next verse, please.", NEXT), ("the next verse", NEXT),
    ("let us read the next verse together", NEXT), ("and the following verse says", NEXT),
    ("go to the next verse", NEXT), ("move to the next verse", NEXT), ("let's move to the next verse", NEXT),
    ("can we go to the next verse", NEXT), ("look at the verse after that", NEXT), ("the verse after", NEXT),
    ("next", NEXT), ("Next.", NEXT), ("okay next please", NEXT), ("next please", NEXT), ("Next one.", NEXT),
    ("the next one", NEXT), ("give me the next one", NEXT), ("let's see the next one", NEXT),
    ("go to the next one please", NEXT), ("show the next verse", NEXT), ("next slide", NEXT),
    ("one more verse", NEXT), ("read one more verse", NEXT), ("go forward one verse", NEXT),
    ("move forward", NEXT), ("forward", NEXT), ("Forward please.", NEXT), ("go on to the next verse", NEXT),
    ("brother next verse", NEXT), ("operator next", NEXT), ("media next please", NEXT),
    ("next verse pastor", NEXT), ("Let's go on to the next verse.", NEXT), ("and the next verse", NEXT),
    ("then the next verse says", NEXT), ("skip to the next verse", NEXT), ("now the following verse", NEXT),
    ("turn to the next verse", NEXT), ("put up the next verse", NEXT),
    # forward several
    ("go forward two verses", fwd(2)), ("skip two verses", fwd(2)) if False else ("skip ahead two verses", fwd(2)),
    ("move ahead three verses", fwd(3)), ("jump forward 4 verses", fwd(4)),
    # previous verse
    ("go back", PREV), ("Go back.", PREV), ("can we go back", PREV), ("can you go back", PREV),
    ("go back please", PREV), ("let's go back", PREV), ("okay go back", PREV), ("back", PREV), ("Back.", PREV),
    ("back up", PREV), ("go back a verse", PREV), ("go back one verse", PREV), ("back a verse", PREV),
    ("back one verse", PREV), ("previous verse", PREV), ("the previous verse", PREV),
    ("let us go back to the previous verse", PREV), ("back to the previous verse", PREV),
    ("back to the previous one", PREV), ("the previous one", PREV), ("go to the previous one", PREV),
    ("the verse before", PREV), ("the verse before that", PREV), ("go back to the verse before", PREV),
    ("look at the verse before this one", PREV), ("previous slide", PREV), ("previous", PREV),
    ("go back one more verse", PREV), ("go back once more", PREV), ("let's go back one verse", PREV),
    ("can we go back a little bit", PREV), ("go back quickly", PREV), ("media go back", PREV),
    ("brother back", PREV), ("the preceding verse", PREV), ("the prior verse", PREV),
    ("let me go back a verse", PREV), ("we go back one verse", PREV), ("move back one verse", PREV),
    ("move back", PREV), ("back please", PREV), ("one verse back", PREV),
    # back several
    ("go back two verses", back(2)), ("go back 2 verses", back(2)), ("back three verses", back(3)),
    ("let's go back a couple of verses", back(2)), ("go back a few verses", back(3)),
    ("two verses back", back(2)), ("move back five verses", back(5)),
    # chapters
    ("next chapter", NEXT_CH), ("move to the next chapter", NEXT_CH), ("go to the next chapter", NEXT_CH),
    ("on to the next chapter", NEXT_CH), ("the following chapter", NEXT_CH), ("the chapter after", NEXT_CH),
    ("previous chapter", PREV_CH), ("go back a chapter", PREV_CH), ("back one chapter", PREV_CH),
    ("the chapter before", PREV_CH), ("go back to the previous chapter", PREV_CH),
    ("go back two chapters", back(2, CHAPTER)), ("forward two chapters", fwd(2, CHAPTER)),
    # go to a chapter of the same book
    ("go back to chapter three", chap(3)), ("back to chapter 3", chap(3)), ("turn to chapter four", chap(4)),
    ("let's go to chapter five", chap(5)), ("move to chapter twelve", chap(12)),
    ("go to chapter 4 verse 2", chap(4, 2)), ("turn to chapter four verse two", chap(4, 2)),
    ("jump to chapter 10", chap(10)), ("go back to chapter one verse one", chap(1, 1)),
    ("let us look at chapter six", chap(6)), ("come to chapter two", chap(2)),
    ("take us to chapter seven", chap(7)), ("return to chapter 3", chap(3)),
    ("go to chapter twenty one", chap(21)), ("now read chapter 8 verse 28", chap(8, 28)),
    # start of chapter / passage
    ("go back to the beginning of the chapter", Intent(GOTO, where="chapter_start")),
    ("start of the chapter", Intent(GOTO, where="chapter_start")),
    ("back to verse one", Intent(GOTO, where="chapter_start")),
    ("go back to the first verse", Intent(GOTO, where="chapter_start")),
    ("back to where we started", Intent(GOTO, where="passage_start")),
    ("let's go back to where we started", Intent(GOTO, where="passage_start")),
    ("go back to where we were reading", Intent(GOTO, where="passage_start")),
    # stop / continue following
    ("stop there", Intent(STOP)), ("let's stop there", Intent(STOP)), ("we will stop there", Intent(STOP)),
    ("We'll stop there.", Intent(STOP)), ("let us stop there for now", Intent(STOP)), ("stop", Intent(STOP)),
    ("okay stop", Intent(STOP)), ("pause there", Intent(STOP)), ("hold it there", Intent(STOP)),
    ("that is where we stop", Intent(STOP)), ("stop reading", Intent(STOP)), ("Stop!", Intent(STOP)),
    ("continue", Intent(RESUME)), ("let's continue", Intent(RESUME)), ("let us continue", Intent(RESUME)),
    ("continue reading", Intent(RESUME)), ("keep reading", Intent(RESUME)), ("read on", Intent(RESUME)),
    ("let's read on", Intent(RESUME)), ("okay continue", Intent(RESUME)), ("continue please", Intent(RESUME)),
    ("we continue from where we stopped", Intent(RESUME)), ("let's carry on", Intent(RESUME)),
    ("resume", Intent(RESUME)), ("Continue.", Intent(RESUME)),
]

NEGATIVE = [
    "next week we will have a retreat", "go back to Egypt and see", "the next thing I want to tell you",
    "who is next in line for the choir", "he looked back at the city", "back in the days of Noah",
    "next Sunday is communion", "they went back home", "do not look back", "Lot's wife looked back",
    "go back to your first love", "I want you to go back home and pray", "the next time you face trouble",
    "the next generation must know", "we are moving forward as a church", "forward ever backward never",
    "I will come back to that", "God brought them back", "when you go back to your office",
    "stop complaining", "stop doubting and believe", "you must not stop praying", "nothing can stop God",
    "continue in prayer", "they continued steadfastly", "if you continue in my word", "the work continues",
    "keep reading your bible every day", "she went on to say", "and so on", "later on",
    "before you were born I knew you", "after this I looked", "the chapter of your life", "a new chapter",
    "this chapter of the church", "the verse says love is patient", "that verse changed my life",
    "my favourite verse", "the previous pastor built this church", "the previous year was hard",
    "in the previous service", "the following people should come forward", "the following week",
    "next to the altar", "come forward for prayer", "step forward", "bring the offering forward",
    "the one who is next", "back then", "pay back", "give back to God", "go back to sleep",
    "stop the music", "hold on", "hold your neighbour's hand", "we will continue next week",
    "let's continue to worship", "I want to continue in this series next week", "read on your own",
    "", "amen", "John 3:16", "turn with me to Romans chapter eight", "Romans chapter eight verse twenty eight",
    "for God so loved the world", "chapter and verse", "in chapter three we saw grace",
    "the verses before and after", "verses are numbered", "back to back", "next of kin",
    "the next one hundred days of fasting", "two verses later Paul says", "a couple of verses",
    "skip breakfast and pray", "turn your neighbour", "turn around", "move your car please",
    "take us higher Lord", "give me Jesus", "show me your glory", "put on the full armour",
]


@pytest.mark.parametrize("text,intent", POSITIVE)
def test_positive(text, intent):
    assert parse_intent(text) == intent


@pytest.mark.parametrize("text", NEGATIVE)
def test_negative(text):
    assert parse_intent(text) is None


def test_corpus_size():
    assert len(POSITIVE) + len(NEGATIVE) >= 200
