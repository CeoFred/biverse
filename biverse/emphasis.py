"""Bold, underline and highlight for words of a verse, saved per translation and verse.

Marks are word indices into ``text.split()`` of that translation's verse, so
they come back the next time the verse is shown. Stored as JSON in the
settings folder (``emphasis.json``), written atomically.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, Iterable, Set

from . import paths

log = logging.getLogger(__name__)

BOLD = "bold"
UNDERLINE = "underline"
HIGHLIGHT = "highlight"
STYLES = (BOLD, UNDERLINE, HIGHLIGHT)

Marks = Dict[int, Set[str]]


def _key(code: str, book: int, chapter: int, verse: int) -> str:
    return "%s %d:%d:%d" % (code.upper(), book, chapter, verse)


class EmphasisStore(object):
    def __init__(self, path: str = "") -> None:
        self.path = path or os.path.join(paths.config_dir(), "emphasis.json")
        self._data = {}  # type: Dict[str, Dict[str, list]]
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                self._data = {k: v for k, v in raw.items() if isinstance(v, dict)}
        except (OSError, ValueError):
            pass

    def get(self, code: str, book: int, chapter: int, verse: int) -> Marks:
        raw = self._data.get(_key(code, book, chapter, verse), {})
        out = {}  # type: Marks
        for idx, styles in raw.items():
            try:
                s = {x for x in styles if x in STYLES}
                if s:
                    out[int(idx)] = s
            except (TypeError, ValueError):
                continue
        return out

    def toggle(self, code: str, book: int, chapter: int, verse: int, indices: Iterable[int], style: str) -> Marks:
        """Apply ``style`` to the words, or remove it if they all have it already."""
        if style not in STYLES:
            raise ValueError(style)
        marks = self.get(code, book, chapter, verse)
        idx = sorted(set(indices))
        if not idx:
            return marks
        remove = all(style in marks.get(i, ()) for i in idx)
        for i in idx:
            s = set(marks.get(i, ()))
            if remove:
                s.discard(style)
            else:
                s.add(style)
            if s:
                marks[i] = s
            else:
                marks.pop(i, None)
        self._put(code, book, chapter, verse, marks)
        return marks

    def clear(self, code: str, book: int, chapter: int, verse: int, indices: Iterable[int] = ()) -> Marks:
        """Remove all marks from the words (from the whole verse if no indices given)."""
        marks = self.get(code, book, chapter, verse)
        idx = list(indices)
        if not idx:
            marks = {}
        for i in idx:
            marks.pop(i, None)
        self._put(code, book, chapter, verse, marks)
        return marks

    def _put(self, code, book, chapter, verse, marks: Marks) -> None:
        key = _key(code, book, chapter, verse)
        if marks:
            self._data[key] = {str(i): sorted(s) for i, s in sorted(marks.items())}
        else:
            self._data.pop(key, None)
        self.save()

    def save(self) -> None:
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            log.exception("could not save emphasis to %s", self.path)
