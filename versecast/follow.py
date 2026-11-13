"""Follow the preacher reading the live passage, and move to the next verse in time.

The live recogniser text (Kroko partials, ~5 updates a second) is compared with
the verse on screen in every installed translation. Two triggers move on:

* **end trigger** - the reading has reached the last word or two of the verse
  (and enough of the verse was matched on the way): switch *as the verse ends*;
* **start trigger** - the newest words match the opening of the next verse (or
  one after it, when the preacher skips a verse): switch straight away.

Guards: a minimum dwell per verse, the end trigger never fires on the last
verse of a range (only reading the next verse aloud continues past it), and
nothing moves while paused ("stop there" ... "continue").

Pure logic, no Tk: the UI feeds recogniser text and applies the result.
"""

from __future__ import annotations

import difflib
import re
from typing import Callable, List, Optional, Sequence, Tuple

from .numbers import words_to_numbers

WINDOW = 12          # recent spoken words compared with the verse
RECENT = 4           # the reading position comes from the newest RECENT words
END_SLACK = 1        # fire when the reading is this many words from the verse end...
LONG_SLACK = 2       # ...or this many for long verses (LONG_VERSE words or more)
LONG_VERSE = 16
MIN_COVERAGE = 0.5   # share of the verse that must have been heard before the end trigger
MIN_MATCHED = 3      # ...and at least this many words
START_MATCH = 4      # words of the next verse's opening that must match, in order...
START_CONTENT = 2    # ...of which at least this many are content words (not "and the for God")
MIN_DWELL = 0.8      # seconds on a verse before moving on
LOOKAHEAD = 2        # verses after the next one checked for a start trigger (skipped verses)

# Very common words: they open many verses, so they cannot prove a new verse started.
STOPWORDS = frozenset("""a an and the of to in for that he she it they them his her their him i you we
my our your thy thee thou ye is was be are were shall will not but so as with by on unto upon all
god lord said say says saith which who whom this these those there then when what from at or nor
""".split())

TextsFor = Callable[[int, int, int], Sequence[str]]  # (book, chapter, verse) -> texts per translation


def words(text: str) -> List[str]:
    text = (text or "").lower().replace(u"’", "'").replace("'", "")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return words_to_numbers(text.split())


def same(a: str, b: str) -> bool:
    """Spoken word vs verse word, tolerant of recogniser spelling ("believeth"/"believe th")."""
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a[:4] == b[:4] or difflib.SequenceMatcher(None, a, b).ratio() >= 0.75):
        return True
    return False


def align(spoken: List[str], verse: List[str]) -> List[Tuple[int, int]]:
    """Longest in-order fuzzy match between spoken words and verse words: [(i_spoken, j_verse)]."""
    n, m = len(spoken), len(verse)
    if not n or not m:
        return []
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if same(spoken[i], verse[j]):
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    pairs = []
    i = j = 0
    while i < n and j < m:
        if same(spoken[i], verse[j]) and dp[i][j] == dp[i + 1][j + 1] + 1:
            pairs.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


class Move(object):
    __slots__ = ("verse", "reason")

    def __init__(self, verse: int, reason: str) -> None:
        self.verse = verse
        self.reason = reason  # "end" | "start" | "skip"

    def __repr__(self):  # pragma: no cover
        return "Move(%d, %s)" % (self.verse, self.reason)


class ReadingFollower(object):
    def __init__(self, texts_for: TextsFor, verse_count: Callable[[int, int], int]) -> None:
        self.texts_for = texts_for
        self.verse_count = verse_count
        self.paused = False
        self.book = 0
        self.chapter = 0
        self.verse = 0
        self.range_end = None  # type: Optional[int]
        self._since = 0.0
        self._versions = []  # type: List[List[str]]
        self._covered = {}  # type: Dict[int, set]   # version index -> matched verse word indices
        self._done = []  # type: List[str]          # finished utterances (recent words)
        self._utt = []  # type: List[str]           # current utterance (latest partial)
        self._consumed = 0  # words of the current utterance used up by earlier verses
        self.progress = 0.0

    # -- state ----------------------------------------------------------------------
    @property
    def active(self) -> bool:
        return self.book > 0 and not self.paused

    def start(self, book: int, chapter: int, verse: int, range_end: Optional[int] = None, now: float = 0.0,
              keep_words: bool = False) -> None:
        """Follow from this verse (operator or voice moved, or we advanced)."""
        self.book, self.chapter, self.verse = book, chapter, verse
        self.range_end = range_end
        self._since = now
        self._versions = [w for w in (words(t) for t in self.texts_for(book, chapter, verse)) if w]
        self._covered = {k: set() for k in range(len(self._versions))}
        if not keep_words:
            self._done = []
            self._consumed = len(self._utt)
        self.progress = 0.0

    def stop(self) -> None:
        self.book = 0

    # -- feeding ------------------------------------------------------------------------
    def _window(self) -> List[str]:
        return (self._done + self._utt[self._consumed:])[-WINDOW:]

    def feed(self, text: str, now: float, final: bool = False) -> Optional[Move]:
        """Latest recogniser text (a partial grows; a final ends the utterance)."""
        new = words(text)
        if self._utt and new[:2] != self._utt[:2] and len(new) <= max(2, len(self._utt) // 2):
            self._finish_utterance()  # a new utterance started without a final
        self._utt = new
        if self._consumed > len(self._utt):
            self._consumed = 0
        move = self._decide(now) if self.active else None
        if final:
            self._finish_utterance()
        return move

    def _finish_utterance(self) -> None:
        self._done = (self._done + self._utt[self._consumed:])[-WINDOW:]
        self._utt = []
        self._consumed = 0

    def _consume(self, keep_last: int = 0) -> None:
        """Forget words already used, optionally keeping the newest few (they belong to the next verse)."""
        win = self._window()
        self._done = win[len(win) - keep_last:] if keep_last else []
        self._consumed = len(self._utt)  # later growth of this utterance is new speech

    # -- the decision -------------------------------------------------------------------------
    def _decide(self, now: float) -> Optional[Move]:
        if not self._versions:
            return None
        win = self._window()
        if not win:
            return None
        dwell_ok = now - self._since >= MIN_DWELL

        need = START_MATCH
        # 1. start trigger: the newest words open the next verse (or a later one)
        last_verse = self.verse_count(self.book, self.chapter)
        recent = win[-8:]
        for ahead in range(1, LOOKAHEAD + 2):
            v = self.verse + ahead
            if v > last_verse:
                break
            for t in self.texts_for(self.book, self.chapter, v):
                opening = words(t)[:8]
                pairs = align(recent, opening)
                if len(pairs) < need or pairs[0][1] > 1 or pairs[-1][0] < len(recent) - 2:
                    continue
                content = sum(1 for _i, j in pairs if opening[j] not in STOPWORDS)
                spread = pairs[-1][0] - pairs[0][0] + 1
                # Words that the current verse explains just as well are still the current
                # verse (Romans 8:29 "...he also did predestinate" vs 8:30 "whom he did predestinate").
                here = max([len(align(recent[pairs[0][0]:], cur)) for cur in self._versions] or [0])
                if content >= START_CONTENT and spread <= len(pairs) + 1 and dwell_ok and here < len(pairs):
                    keep = len(recent) - pairs[0][0]
                    self._consume(keep_last=keep)
                    self._advance(v, now)
                    return Move(v, "start" if ahead == 1 else "skip")
        # 2. where are we in the current verse? (each translation on its own terms)
        at_range_end = self.range_end is not None and self.verse >= self.range_end
        finished = False
        best = 0.0
        for k, verse_words in enumerate(self._versions):
            pairs = align(win, verse_words)
            if not pairs:
                continue
            self._covered[k].update(j for _i, j in pairs)
            recent_pairs = [p for p in pairs if p[0] >= len(win) - RECENT]
            pos = recent_pairs[-1][1] if recent_pairs else -1
            n = len(verse_words)
            matched = len(self._covered[k])
            best = max(best, (pos + 1) / float(n))
            # 3. end trigger: reading is at the last word or two, and the verse was really read
            slack = LONG_SLACK if n >= LONG_VERSE else END_SLACK
            if (pos >= n - 1 - slack and matched >= MIN_COVERAGE * n and matched >= min(MIN_MATCHED, n)):
                finished = True
        self.progress = max(self.progress, best)
        if finished and dwell_ok and not at_range_end and self.verse < last_verse:
            self._consume()
            self._advance(self.verse + 1, now)
            return Move(self.verse, "end")
        return None

    def _advance(self, verse: int, now: float) -> None:
        """Follow the new verse, keeping the words already heard of it."""
        self.start(self.book, self.chapter, verse, self.range_end, now, keep_words=True)
