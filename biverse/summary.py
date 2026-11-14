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
# Sentences that only move around the Bible are not points of the sermon.
NAVIGATION = re.compile(r"\b(turn (with me )?to|open (your )?bibles?|let us read|lets read|please stand|"
                        r"you may be seated|look at (verse|chapter)|next verse|go back)\b", re.I)


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

    def clear(self) -> None:
        """Forget everything heard so far (the operator cleared the transcript)."""
        self.lines = []
        self.refs = []
        self.ended = self.started

    def add_lines(self, lines: List[Tuple[float, str]], refs: Optional[List[Tuple[float, str]]] = None) -> None:
        """Append pasted or imported lines; their times are seconds from their own start
        and are placed after what is already recorded."""
        base = self.lines[-1][0] + 5.0 if self.lines else 0.0
        for t, text in lines:
            if text.strip():
                self.lines.append((base + t, text.strip()))
        for t, label in refs or []:
            self.refs.append((base + t, label))
        if self.lines:
            self.ended = max(self.ended, self.started + self.lines[-1][0])

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


# -- pasted / imported transcripts ---------------------------------------------------

#: What "Paste transcript" and "Import transcript" accept.
TRANSCRIPT_FORMATS = ("plain text (optionally with times like 00:12:05), SRT or WebVTT subtitles, "
                      "or a Biverse sermon record")
TRANSCRIPT_FILETYPES = [("Transcripts", "*.txt *.srt *.vtt *.json *.md"), ("Text", "*.txt"),
                        ("Subtitles", "*.srt *.vtt"), ("Sermon records", "*.json")]
MAX_TRANSCRIPT_CHARS = 2000000
WORDS_PER_SECOND = 2.5  # about 150 words a minute, for text without times

_CUE_TIME = re.compile(r"^\s*((?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?)")
_LINE_TIME = re.compile(r"^\s*[\[(]?((?:\d{1,2}:)?\d{1,2}:\d{2})(?:[.,]\d+)?[\])]?\s*[-\u2013:]?\s+(.*)$")
_TAG = re.compile(r"<[^>]{0,200}>")


class TranscriptError(ValueError):
    """The text is not a transcript Biverse accepts."""


def _secs(stamp: str) -> float:
    parts = stamp.replace(",", ".").split(":")
    out = 0.0
    for p in parts:
        out = out * 60 + float(p)
    return out


def _check_text(text: str) -> str:
    if text is None or not text.strip():
        raise TranscriptError("There is no text to add.")
    if len(text) > MAX_TRANSCRIPT_CHARS:
        raise TranscriptError("That is too long for one sermon (more than %d characters)." % MAX_TRANSCRIPT_CHARS)
    controls = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\r\n\f")
    if "\x00" in text or controls > len(text) // 100:
        raise TranscriptError("That looks like a binary file, not text.")
    head = text.lstrip()[:200].lower()
    if head.startswith("{\\rtf"):
        raise TranscriptError("Rich text (RTF) is not accepted. Save it as plain text (.txt) first.")
    if head.startswith(("<!doctype", "<html", "<?xml")) or re.search(r"<(div|p|span|body|table)\b", head):
        raise TranscriptError("HTML or XML is not accepted. Copy the plain text instead.")
    if not re.search(r"[^\W\d_]", text, re.UNICODE):
        raise TranscriptError("There are no words in that text.")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _subtitles(text: str) -> List[Tuple[float, str]]:
    out = []  # type: List[Tuple[float, str]]
    for block in re.split(r"\n\s*\n", text):
        rows = [r for r in block.split("\n") if r.strip()]
        for i, row in enumerate(rows):
            m = _CUE_TIME.match(row)
            if m:
                words = " ".join(_TAG.sub("", r).strip() for r in rows[i + 1:]).strip()
                if words:
                    out.append((_secs(m.group(1)), words))
                break
    # subtitles repeat a line while it scrolls; drop exact repeats
    deduped = []  # type: List[Tuple[float, str]]
    for t, w in out:
        if not deduped or deduped[-1][1] != w:
            deduped.append((t, w))
    return deduped


def _plain(text: str) -> List[Tuple[float, str]]:
    rows = [r.strip() for r in text.split("\n") if r.strip()]
    stamped = [_LINE_TIME.match(r) for r in rows]
    if rows and sum(1 for m in stamped if m) >= max(1, len(rows) // 2):
        out = []  # type: List[Tuple[float, str]]
        first = None
        for r, m in zip(rows, stamped):
            if m:
                t = _secs(m.group(1))
                first = t if first is None else first
                if t < first:  # clock times past midnight, or out of order
                    t += 24 * 3600
                out.append((t - first, m.group(2).strip()))
            elif out:
                out[-1] = (out[-1][0], out[-1][1] + " " + r)
        return [(t, w) for t, w in out if w]
    out = []
    t = 0.0
    for r in rows:
        if r.startswith("#") and len(r) < 120:  # markdown headings are not speech
            continue
        out.append((t, r))
        t += len(r.split()) / WORDS_PER_SECOND
    return out


def parse_transcript(text: str) -> List[Tuple[float, str]]:
    """``[(seconds from start, text), ...]`` from pasted or imported text.

    Accepts plain text (lines may start with a time such as ``00:12:05`` or
    ``[12:05]``, as Biverse's own transcript panel shows them), SRT and WebVTT
    subtitles, and Biverse sermon records (JSON). Anything else raises
    ``TranscriptError`` with a message for the operator.
    """
    text = _check_text(text)
    stripped = text.lstrip("\ufeff \t\n")
    if stripped.startswith(("{", "[")):
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if data is not None:
            if isinstance(data, dict) and isinstance(data.get("lines"), list):
                try:
                    lines = SermonLog.from_dict(data).lines
                except (TypeError, ValueError):
                    raise TranscriptError("That sermon record is damaged.")
                if lines:
                    return lines
                raise TranscriptError("That sermon record has no transcript.")
            raise TranscriptError("That JSON is not a Biverse sermon record.")
    if stripped.upper().startswith("WEBVTT") or any(_CUE_TIME.match(r) for r in stripped.split("\n")[:20]):
        lines = _subtitles(stripped)
        if lines:
            return lines
        raise TranscriptError("Those subtitles have no text.")
    lines = _plain(stripped)
    if not lines:
        raise TranscriptError("There is no text to add.")
    return lines


def references_in(lines: List[Tuple[float, str]], verse_count=None) -> List[Tuple[float, str]]:
    """Scripture references spoken in these lines, as ``[(seconds, "John 3:16"), ...]``,
    found the same way as while listening."""
    from .controller import Selection
    from .detector import NEW, Detector
    kw = {"verse_count": verse_count} if verse_count else {}
    det = Detector(**kw)
    out = []  # type: List[Tuple[float, str]]
    for t, text in lines:
        for kind, d in det.feed_final(text, now=t):
            if kind == NEW:
                label = Selection.from_reference(d.ref).passage_label()
                if not out or out[-1][1] != label:
                    out.append((t, label))
    return out


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
        if n < 7 or n > 60 or NAVIGATION.search(s):
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
