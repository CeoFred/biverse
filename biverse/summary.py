"""Sermon record and the built-in (extractive) summary.

``SermonLog`` collects what was heard while listening: final transcript lines
with times, the scriptures detected, and when it started/stopped. It is saved
as JSON in the settings folder (``sermons/``) so a summary survives restarts.

``summarise(log)`` builds a summary from the transcript itself, with no extra
download: the scriptures referenced (in order, with times), the key sentences,
and a timeline of the main themes. An optional AI pack can add a prose
summary on top (see ``llm.py``).
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections import Counter
from typing import Dict, List, Optional, Tuple

from . import books, paths

STOPWORDS = frozenset("""a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having he
her here hers herself him himself his how i if in into is it its itself just let lets like me more most my myself no
nor not now of off on once only or other our ours ourselves out over own same say says said shall she should so some
such than that the their theirs them themselves then there these they this those through to too under until up very
was we were what when where which while who whom why will with would you your yours yourself yourselves amen yes
okay ok uh um oh yeah gonna wanna going go goes went get got come came know knew think thing things really today
church people somebody someone everybody everyone something anything one two three four five six seven eight nine ten
also even every many much may might must us thee thou thy ye unto saith hath doth verse verses chapter""".split())
CUES = ("the point is", "remember", "i want you to", "listen", "number one", "number two", "number three",
        "first", "secondly", "thirdly", "finally", "in conclusion", "the lesson", "this means", "god wants",
        "the bible says", "scripture says", "key", "important", "notice", "never forget", "the truth is")


class SermonLog(object):
    def __init__(self, started: Optional[float] = None) -> None:
        self.started = started if started is not None else time.time()
        self.ended = self.started
        self.lines = []  # type: List[Tuple[float, str]]       # (seconds from start, text)
        self.refs = []  # type: List[Tuple[float, str]]        # (seconds from start, "John 3:16")
        self.title = ""

    def add_line(self, text: str, when: Optional[float] = None) -> None:
        text = (text or "").strip()
        if text:
            t = (when if when is not None else time.time()) - self.started
            self.lines.append((t, text))
            self.ended = self.started + t

    def add_ref(self, label: str, when: Optional[float] = None) -> None:
        t = (when if when is not None else time.time()) - self.started
        if not self.refs or self.refs[-1][1] != label:
            self.refs.append((t, label))

    @property
    def duration(self) -> float:
        return max(0.0, self.ended - self.started)

    def empty(self) -> bool:
        return not self.lines

    def text(self) -> str:
        return " ".join(t for _s, t in self.lines)

    # -- persistence -----------------------------------------------------------
    def to_dict(self) -> dict:
        return {"started": self.started, "ended": self.ended, "title": self.title,
                "lines": [[round(s, 1), t] for s, t in self.lines], "refs": [[round(s, 1), r] for s, r in self.refs]}

    @classmethod
    def from_dict(cls, d: dict) -> "SermonLog":
        log = cls(float(d.get("started", 0)))
        log.ended = float(d.get("ended", log.started))
        log.title = str(d.get("title", ""))
        log.lines = [(float(s), str(t)) for s, t in d.get("lines", [])]
        log.refs = [(float(s), str(r)) for s, r in d.get("refs", [])]
        return log

    def save(self, folder: Optional[str] = None) -> str:
        folder = folder or os.path.join(paths.config_dir(), "sermons")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("%Y-%m-%d_%H%M", time.localtime(self.started)) + ".json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=1)
        os.replace(tmp, path)
        return path


def recent_sermons(folder: Optional[str] = None, limit: int = 20) -> List[str]:
    folder = folder or os.path.join(paths.config_dir(), "sermons")
    try:
        names = sorted((n for n in os.listdir(folder) if n.endswith(".json")), reverse=True)
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names[:limit]]


# -- the built-in summary ------------------------------------------------------------

def _words(text: str) -> List[str]:
    return re.findall(r"[a-z']+", text.lower())


def _content(text: str) -> List[str]:
    return [w.strip("'") for w in _words(text) if len(w) > 2 and w.strip("'") not in STOPWORDS]


def sentences(log: SermonLog) -> List[Tuple[float, str]]:
    """Split the transcript into sentences (punctuation if the recogniser gave it, else each line)."""
    out = []
    for t, line in log.lines:
        parts = re.split(r"(?<=[.!?])\s+", line) if re.search(r"[.!?]", line) else [line]
        for p in parts:
            p = p.strip()
            if p:
                out.append((t, p[0].upper() + p[1:]))
    return out


def clock(seconds: float) -> str:
    seconds = int(max(0, seconds))
    return "%d:%02d" % (seconds // 60, seconds % 60) if seconds < 3600 else "%d:%02d:%02d" % (
        seconds // 3600, seconds % 3600 // 60, seconds % 60)


def summarise(log: SermonLog, max_points: int = 7) -> Dict[str, object]:
    sents = sentences(log)
    freq = Counter(w for _t, s in sents for w in _content(s))
    top = [w for w, _c in freq.most_common(12)]
    ref_times = [t for t, _r in log.refs]
    scored = []
    for k, (t, s) in enumerate(sents):
        n = len(_words(s))
        if n < 7 or n > 60:
            continue
        cw = _content(s)
        if not cw:
            continue
        score = sum(math.log(1 + freq[w]) for w in set(cw)) / math.sqrt(len(cw) + 4)
        low = s.lower()
        if any(c in low for c in CUES):
            score *= 1.4
        if any(0 <= t - rt <= 60 for rt in ref_times):
            score *= 1.2  # explaining a scripture just read
        scored.append((score, k, t, s))
    picked = sorted(sorted(scored, reverse=True)[:max_points], key=lambda x: x[1])
    # timeline: main words per ~5 minute section
    timeline = []
    span = max(300.0, log.duration / 6.0) if log.duration else 300.0
    if sents:
        sec = 0
        while sec * span <= sents[-1][0]:
            words = Counter(w for t, s in sents if sec * span <= t < (sec + 1) * span for w in _content(s))
            refs = [r for t, r in log.refs if sec * span <= t < (sec + 1) * span]
            if words or refs:
                timeline.append((sec * span, [w for w, _c in words.most_common(4)], refs))
            sec += 1
    return {
        "duration": log.duration,
        "words": sum(len(_words(s)) for _t, s in sents),
        "scriptures": list(log.refs),
        "themes": top[:8],
        "key_points": [(t, s) for _sc, _k, t, s in picked],
        "timeline": timeline,
    }


def as_text(log: SermonLog, summary: Dict[str, object], ai_text: str = "") -> str:
    """Plain-text summary for copying or saving."""
    when = time.strftime("%A %d %B %Y, %H:%M", time.localtime(log.started))
    lines = ["Sermon summary - %s" % when, "Length: %s   Words heard: %d" % (clock(summary["duration"]),
                                                                       summary["words"]), ""]
    if ai_text:
        lines += ["Summary", "-------", ai_text.strip(), ""]
    lines += ["Scriptures", "----------"]
    lines += ["  %s  %s" % (clock(t), r) for t, r in summary["scriptures"]] or ["  (none detected)"]
    lines += ["", "Main themes: " + (", ".join(summary["themes"]) or "-"), "", "Key points", "----------"]
    lines += ["  %s  %s" % (clock(t), s) for t, s in summary["key_points"]] or ["  (not enough speech)"]
    lines += ["", "Timeline", "--------"]
    for t, words, refs in summary["timeline"]:
        bits = ", ".join(words)
        if refs:
            bits += ("  [" + "; ".join(refs) + "]")
        lines.append("  %s  %s" % (clock(t), bits))
    lines += ["", "Transcript", "----------"]
    lines += ["  %s  %s" % (clock(t), s) for t, s in log.lines]
    return "\n".join(lines) + "\n"


def book_of(label: str) -> str:
    """"1 Corinthians 13:4" -> "1 Corinthians" (for grouping)."""
    name = label.rsplit(" ", 1)[0]
    return name if any(b.ref_name == name or b.name == name for b in books.BOOKS) else label
