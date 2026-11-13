"""Spoken navigation commands: "next verse", "go back", "next chapter"...

Commands act on what is on screen (see ui_operator). "Move to verse 8" is not a
command: it is a relative reference, handled by the detector against the
current position.

Two kinds of phrases:

* explicit phrases ("next verse", "go back a verse", "previous chapter") are
  recognised anywhere in an utterance;
* the bare words "next", "back", "go back", "previous" are everyday words
  ("next week", "go back to Egypt"), so they only count when they are the whole
  utterance, give or take a few filler words ("okay next", "let's go back").
"""

from __future__ import annotations

import re
from typing import List, Optional

NEXT_VERSE = "next_verse"
PREV_VERSE = "prev_verse"
NEXT_CHAPTER = "next_chapter"
PREV_CHAPTER = "prev_chapter"

LABELS = {NEXT_VERSE: "next verse", PREV_VERSE: "previous verse",
          NEXT_CHAPTER: "next chapter", PREV_CHAPTER: "previous chapter"}

_PHRASES = [
    (NEXT_CHAPTER, ["next chapter", "following chapter", "chapter after", "move to the next chapter",
                    "on to the next chapter"]),
    (PREV_CHAPTER, ["previous chapter", "chapter before", "last chapter please", "go back a chapter",
                    "back a chapter", "back one chapter", "go back one chapter"]),
    (NEXT_VERSE, ["next verse", "following verse", "verse after", "one more verse", "next one please",
                  "next slide"]),
    (PREV_VERSE, ["previous verse", "verse before", "go back a verse", "back a verse", "back one verse",
                  "go back one verse", "previous slide", "last verse please"]),
]

# Words that may surround a bare command without making it part of a sentence.
_FILLER = {"ok", "okay", "alright", "right", "and", "now", "so", "please", "lets", "let", "us", "go", "the",
           "to", "uh", "um", "yes", "yeah", "then", "move", "just", "a", "one", "brother", "sister",
           "pastor", "operator", "media", "on"}
_BARE = {"next": NEXT_VERSE, "forward": NEXT_VERSE, "back": PREV_VERSE, "previous": PREV_VERSE,
         "backward": PREV_VERSE, "backwards": PREV_VERSE}
MAX_BARE_WORDS = 5


def _words(text: str) -> List[str]:
    text = (text or "").lower().replace(u"’", "'").replace("'", "")
    return re.sub(r"[^a-z0-9\s]", " ", text).split()


def parse_command(text: str) -> Optional[str]:
    """The navigation command in ``text``, or None."""
    words = _words(text)
    if not words:
        return None
    joined = " " + " ".join(words) + " "
    for cmd, phrases in _PHRASES:
        for p in phrases:
            if " %s " % p in joined:
                return cmd
    if len(words) <= MAX_BARE_WORDS:
        core = [w for w in words if w not in _FILLER]
        if len(core) == 1 and core[0] in _BARE:
            return _BARE[core[0]]
    return None
