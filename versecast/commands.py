"""Spoken navigation: what the preacher wants the screen to do.

``parse_intent(text)`` returns an :class:`Intent` or None. Intents act on what
is on screen (see ui_operator):

* ``step``  – move ``delta`` verses or chapters ("next verse", "go back two
  verses", "the verse before", "Next.", "can we go back")
* ``goto``  – a place in the same book ("back to chapter three", "the
  beginning of the chapter", "where we started"). "verse 8" and "chapter 4
  verse 2" without a book are relative references handled by the parser and
  detector, not here.
* ``stop`` / ``resume`` – pause or continue following the reading
  ("stop there", "let's continue").

Everyday words are the main risk ("next week", "go back to Egypt", "stop
complaining"), so every rule needs either a scripture unit (verse, chapter,
"the next one") or an utterance that is nothing but the command.
"""

from __future__ import annotations

import re
from typing import List, Optional

STEP = "step"
GOTO = "goto"
STOP = "stop"
RESUME = "resume"

VERSE = "verse"
CHAPTER = "chapter"

# legacy names (v1.2 API)
NEXT_VERSE = "next_verse"
PREV_VERSE = "prev_verse"
NEXT_CHAPTER = "next_chapter"
PREV_CHAPTER = "prev_chapter"
LABELS = {NEXT_VERSE: "next verse", PREV_VERSE: "previous verse",
          NEXT_CHAPTER: "next chapter", PREV_CHAPTER: "previous chapter"}


class Intent(object):
    __slots__ = ("kind", "unit", "delta", "chapter", "verse", "where")

    def __init__(self, kind: str, unit: str = VERSE, delta: int = 0, chapter: Optional[int] = None,
                 verse: Optional[int] = None, where: str = "") -> None:
        self.kind = kind
        self.unit = unit
        self.delta = delta
        self.chapter = chapter
        self.verse = verse
        self.where = where  # "chapter_start" | "passage_start" for goto

    def key(self):
        return (self.kind, self.unit, self.delta, self.chapter, self.verse, self.where)

    def __eq__(self, other):
        return isinstance(other, Intent) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())

    def label(self) -> str:
        if self.kind == STEP:
            n = abs(self.delta)
            word = self.unit + ("s" if n != 1 else "")
            return "%s %d %s" % ("forward" if self.delta > 0 else "back", n, word) if n != 1 else (
                "%s %s" % ("next" if self.delta > 0 else "previous", self.unit))
        if self.kind == GOTO:
            if self.where == "chapter_start":
                return "start of the chapter"
            if self.where == "passage_start":
                return "start of the passage"
            return "chapter %d" % self.chapter if self.verse is None else "chapter %d verse %d" % (
                self.chapter, self.verse)
        return {STOP: "stop following", RESUME: "continue following"}.get(self.kind, self.kind)

    def __repr__(self):  # pragma: no cover
        return "Intent(%s)" % self.label()


# ----------------------------------------------------------------------- words

_NUM = {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
        "nine": 9, "ten": 10, "couple": 2, "few": 3}
_FWD = {"next", "following", "forward", "ahead", "on", "onward", "onwards", "after"}
_BACK = {"previous", "prior", "preceding", "back", "backward", "backwards", "before", "earlier"}
_UNIT = {"verse": VERSE, "verses": VERSE, "chapter": CHAPTER, "chapters": CHAPTER, "slide": VERSE, "slides": VERSE,
         "scripture": VERSE, "passage": VERSE}
_MOVE = {"go", "move", "turn", "jump", "skip", "come", "take", "read", "look", "see", "show", "give", "put",
         "return", "flip", "head", "let", "lets", "can", "could", "may", "shall"}
# Words that may surround a bare command ("okay, next please", "can we go back?")
_FILLER = {"ok", "okay", "alright", "right", "and", "now", "so", "please", "lets", "let", "us", "go", "the", "to",
           "uh", "um", "yes", "yeah", "move", "once", "more", "just", "a", "one", "brother", "sister", "pastor",
           "operator", "media", "on", "can", "could", "we", "you", "i", "shall", "should", "will", "would",
           "quickly", "again", "little", "bit", "up", "screen", "there", "here", "come", "kindly", "sir", "ma"}
_BARE = {"next": 1, "forward": 1, "back": -1, "previous": -1, "backward": -1, "backwards": -1}
MAX_BARE_WORDS = 8

_STOP_PHRASES = ["stop there", "lets stop there", "we will stop there", "well stop there", "we stop there",
                 "let us stop there", "stop reading", "that is where we stop", "thats where we stop",
                 "pause there", "hold it there", "hold there", "lets pause there", "we will pause there"]
_RESUME_PHRASES = ["continue reading", "lets continue", "let us continue", "keep reading", "read on",
                   "lets read on", "let us read on", "we continue", "carry on reading", "lets carry on",
                   "resume reading", "continue from there", "where we stopped"]
_BARE_STOP = {"stop", "pause"}
_BARE_RESUME = {"continue", "resume", "proceed"}


def _words(text: str) -> List[str]:
    from .numbers import words_to_numbers
    text = (text or "").lower().replace(u"’", "'").replace("'", "")
    text = re.sub(r"(\d)\s*[:.]\s*(\d)", r"\1 \2", text)
    return words_to_numbers(re.sub(r"[^a-z0-9\s]", " ", text).split())


def _tail_ok(words: List[str], phrase: str, allowed: int = 1) -> bool:
    """``phrase`` occurs and at most ``allowed`` non-filler words follow it
    ("let's continue" yes, "let's continue to worship" no)."""
    p = phrase.split()
    for i in range(len(words) - len(p) + 1):
        if words[i:i + len(p)] == p:
            rest = [x for x in words[i + len(p):] if x not in _FILLER and x not in ("now", "for", "today")]
            if len(rest) <= allowed:
                return True
    return False


def _count(word: str) -> Optional[int]:
    if word.isdigit():
        return int(word)
    return _NUM.get(word)


def _has(joined: str, phrases) -> bool:
    return any(" %s " % p in joined for p in phrases)


def parse_intent(text: str) -> Optional[Intent]:
    """The navigation intent in ``text``, or None."""
    w = _words(text)
    if not w:
        return None
    joined = " " + " ".join(w) + " "

    # stop / continue following ---------------------------------------------------
    if any(_tail_ok(w, p, 1) for p in _STOP_PHRASES):
        return Intent(STOP)
    if any(_tail_ok(w, p, 0) for p in _RESUME_PHRASES) or _has(joined, ["where we stopped"]):
        return Intent(RESUME)
    core = [x for x in w if x not in _FILLER]
    if len(w) <= MAX_BARE_WORDS and len(core) == 1:
        if core[0] in _BARE_STOP:
            return Intent(STOP)
        if core[0] in _BARE_RESUME:
            return Intent(RESUME)

    # goto: start of chapter / passage ------------------------------------------------
    if re.search(r" (beginning|start|top|first verse) of (the |this )?chapter ", joined) or re.search(
            r" (back|go|return|move) to (verse 1|the first verse) ", joined):
        return Intent(GOTO, where="chapter_start")
    if re.search(r" (back )?to where we (started|began|were reading|read from) ", joined) or re.search(
            r" (start|beginning) of (the |our )?(passage|reading|text) ", joined):
        return Intent(GOTO, where="passage_start")

    # goto chapter N (same book), needs a movement word: "back to chapter three"
    m = re.search(r" (?:%s|back|to) (?:(?:back|over|now) )?(?:to |into |at )?chapter (\d+|[a-z]+)"
                  r"(?: (?:verse|vs|v) (\d+|[a-z]+))? " % "|".join(sorted(_MOVE)), joined)
    if m and not re.search(r" (?:next|previous|following) chapter ", joined):
        c = _count(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))
        v = None
        if m.group(2):
            v = int(m.group(2)) if m.group(2).isdigit() else _count(m.group(2))
        if c:
            return Intent(GOTO, unit=CHAPTER, chapter=c, verse=v)

    # step with a count: "go back two verses", "forward 3 verses", "back one more verse"
    for i, word in enumerate(w):
        unit = _UNIT.get(word)
        if unit is None:
            continue
        before = w[max(0, i - 5):i]
        after = w[i + 1:i + 3]
        direction = 0
        for x in before + after:
            if x in _BACK:
                direction = -1
            elif x in _FWD and direction == 0:
                direction = 1
        if direction == 0:
            continue
        if word.endswith("s") and not any(_count(x) for x in before):
            continue  # "the verses before and after": a plural needs a count
        n = 1
        for x in reversed(before):
            c = _count(x)
            if c is not None:
                n = c
                break
        # "verse 8" / "chapter 3" with a direction word is a goto, not a step
        if after and after[0].isdigit() and not before:
            continue
        if before and before[-1] in ("the", "this", "that", "a", "one", "more", "next", "previous",
                                     "following", "prior", "preceding") or any(_count(x) for x in before) or any(
                x in _BACK or x in _FWD for x in after):
            return Intent(STEP, unit=unit, delta=direction * max(1, min(n, 20)))

    # "one more verse" / "read one more verse"
    if re.search(r" (?:1|a|one) more (?:verse|slide) ", joined) and not any(x in _BACK for x in w):
        return Intent(STEP, delta=1)

    # "the next one", "the previous one": needs a movement word or a short utterance
    m = re.search(r" (next|following|previous|prior|preceding) (?:one|1) ", joined)
    if m and (len(w) <= MAX_BARE_WORDS or any(x in _MOVE for x in w)):
        return Intent(STEP, delta=1 if m.group(1) in ("next", "following") else -1)

    # bare commands: "Next.", "okay next please", "can we go back?"
    if len(w) <= MAX_BARE_WORDS and len(core) == 1 and core[0] in _BARE:
        return Intent(STEP, delta=_BARE[core[0]])
    if len(w) <= MAX_BARE_WORDS and core in (["back", "up"], ["go", "back"]):
        return Intent(STEP, delta=-1)
    return None


# ------------------------------------------------------------- v1.2 compatibility

def parse_command(text: str) -> Optional[str]:
    """Legacy single-step commands (next/previous verse or chapter)."""
    it = parse_intent(text)
    if it is None or it.kind != STEP or abs(it.delta) != 1:
        return None
    if it.unit == CHAPTER:
        return NEXT_CHAPTER if it.delta > 0 else PREV_CHAPTER
    return NEXT_VERSE if it.delta > 0 else PREV_VERSE
