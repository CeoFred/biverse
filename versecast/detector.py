"""Detection pipeline on top of the parser.

* Each final recogniser result is parsed together with the last ~12 words of
  the previous final result, so a reference split by a pause is still caught.
  Only references that end in the *new* words are reported.
* The same reference seen again within ``dedupe_window`` seconds is ignored.
* A detection that extends a recent one (John 3:16 -> John 3:16-18, or
  John 3 -> John 3:16) within ``extend_window`` seconds updates it instead of
  adding a new one.
* "verse N" with no book uses the book and chapter of the latest detection if
  it is younger than ``relative_window`` seconds.
"""

from __future__ import annotations

import itertools
import time

from .numbers import normalise
from .parser import default_verse_count, parse_tokens

CONTEXT_WORDS = 12


class Detection(object):
    __slots__ = ("id", "ref", "time", "wall_time", "snippet")

    def __init__(self, id, ref, t, wall_time, snippet):
        self.id = id
        self.ref = ref
        self.time = t
        self.wall_time = wall_time
        self.snippet = snippet

    def __repr__(self):  # pragma: no cover
        return "Detection(%d, %r)" % (self.id, self.ref)


NEW = "new"
UPDATE = "update"


class Detector(object):
    def __init__(self, strict=True, relative=True, dedupe_window=60.0, extend_window=30.0,
                 relative_window=300.0, verse_count=default_verse_count, clock=time.monotonic):
        self.strict = strict
        self.relative = relative
        self.dedupe_window = dedupe_window
        self.extend_window = extend_window
        self.relative_window = relative_window
        self.verse_count = verse_count
        self.clock = clock
        self.detections = []
        self._prev_words = []
        self._ids = itertools.count(1)

    def reset(self):
        self.detections = []
        self._prev_words = []

    def _last_absolute(self, now):
        if self.detections and now - self.detections[-1].time <= self.relative_window:
            return self.detections[-1]
        return None

    def feed_final(self, text, now=None):
        """Process one final result. Returns ``[(NEW|UPDATE, detection), ...]``."""
        if now is None:
            now = self.clock()
        words = (text or "").split()
        if not words:
            return []
        ctx_tokens = normalise(" ".join(self._prev_words), "speech")
        new_tokens = normalise(" ".join(words), "speech")
        self._prev_words = (self._prev_words + words)[-CONTEXT_WORDS:]
        tokens = ctx_tokens + new_tokens
        boundary = len(ctx_tokens)
        refs = parse_tokens(tokens, "speech", self.strict, self.relative, self.verse_count)
        events = []
        for ref in refs:
            if ref.span[1] <= boundary:
                continue  # entirely inside the context we already processed
            if ref.book is None:
                last = self._last_absolute(now)
                if last is None:
                    continue
                resolved = ref.with_context(last.ref.book, last.ref.chapter, self.verse_count)
                if resolved is None:
                    continue
                ref = resolved
            ev = self._add(ref, now)
            if ev is not None:
                events.append(ev)
        return events

    def add_reference(self, ref, now=None):
        """Feed an already-parsed absolute reference (used by tests and tools)."""
        return self._add(ref, self.clock() if now is None else now)

    def _add(self, ref, now):
        # 1. extension of a recent detection
        for det in reversed(self.detections):
            if now - det.time > self.extend_window:
                break
            old = det.ref
            if old.book != ref.book or old.chapter != ref.chapter or old.key() == ref.key():
                continue
            chapter_only = not old.explicit_verse and ref.explicit_verse
            if chapter_only or (old.explicit_verse and ref.contains(old)):
                det.ref = ref
                det.time = now
                det.wall_time = time.time()
                det.snippet = ref.source_text
                # keep newest-last ordering
                self.detections.remove(det)
                self.detections.append(det)
                return (UPDATE, det)
        # 2. de-duplication
        for det in reversed(self.detections):
            if now - det.time > self.dedupe_window:
                break
            same_chapter = det.ref.book == ref.book and det.ref.chapter == ref.chapter
            if det.ref.key() == ref.key() or (same_chapter and not ref.explicit_verse):
                return None
        det = Detection(next(self._ids), ref, now, time.time(), ref.source_text)
        self.detections.append(det)
        return (NEW, det)
