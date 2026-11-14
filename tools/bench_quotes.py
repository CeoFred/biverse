#!/usr/bin/env python3
"""Benchmark quoted-verse recognition (``biverse/quotes.py``) on sermon transcripts.

    python tools/bench_quotes.py                       # tests/data/quotes/*.txt
    python tools/bench_quotes.py my-sermon.txt --review review.tsv

Transcript format: one utterance per line (as the recogniser delivers final
text). A line containing a quote ends with ``=> John 3:16`` (or a range,
``=> John 3:16-17``); ``=> ~John 3:16`` marks a loose paraphrase that may be
suggested but need not be. ``#`` starts a comment line.

A file without any ``=>`` label is a raw transcript (for example one pasted
from a real service): long lines are cut into utterances of about 12 words,
and ``--review`` writes every suggestion with its context to a TSV file, so a
person can mark each one right or wrong. Add ``=> Ref`` to the lines that
really quote a verse and the file becomes part of the benchmark.

Measured per labelled file:

* found: quotes whose verse became the top suggestion while it was spoken
  (or one utterance later); top-5 likewise for the list
* false suggestions: top suggestions that no nearby label explains, per
  1,000 spoken words
* false go-lives: confirmed strong matches that no nearby label explains.
  These must be zero before ``quotes.AUTO_LIVE_ALLOWED`` may be set.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from typing import Dict, List, Optional, Set, Tuple  # noqa: F401 (type comments)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from biverse import quotes  # noqa: E402
from biverse.parser import parse_typed  # noqa: E402

DATA = os.path.join(ROOT, "tests", "data", "quotes")
SECONDS_PER_UTTERANCE = 4.0
Pos = Tuple[int, int, int]


class Line(object):
    __slots__ = ("text", "refs", "loose")

    def __init__(self, text: str, refs: Set[Pos], loose: Set[Pos]) -> None:
        self.text, self.refs, self.loose = text, refs, loose


def _verses(label: str, bible) -> Set[Pos]:
    out = set()  # type: Set[Pos]
    ref = parse_typed(label)
    if ref is not None and ref.verse_start:
        for v in range(ref.verse_start, (ref.verse_end or ref.verse_start) + 1):
            out.add((ref.book, ref.chapter, v))
    if not out:
        raise ValueError("cannot read the label %r" % label)
    return out


def read(path: str, bible) -> Tuple[List[Line], bool]:
    """The utterances of a transcript, and whether it carries labels."""
    lines = []  # type: List[Line]
    labelled = False
    with open(path, encoding="utf-8") as f:
        raw = [x.rstrip("\n") for x in f]
    for row in raw:
        if row.strip() == "#! labelled":  # a labelled file that happens to contain no quotes
            labelled = True
            continue
        if not row.strip() or row.lstrip().startswith("#"):
            continue
        refs, loose = set(), set()  # type: Set[Pos], Set[Pos]
        if "=>" in row:
            row, label = row.split("=>", 1)
            labelled = True
            for part in label.split(";"):
                part = part.strip()
                if part.startswith("~"):
                    loose |= _verses(part[1:], bible)
                elif part:
                    refs |= _verses(part, bible)
        lines.append(Line(row.strip(), refs, loose))
    if not labelled:  # raw transcript: cut prose into utterance-sized pieces
        cut = []
        for line in lines:
            ws = line.text.split()
            for i in range(0, len(ws), 12):
                cut.append(Line(" ".join(ws[i:i + 12]), set(), set()))
        lines = cut
    return lines, labelled


class Result(object):
    def __init__(self, name: str) -> None:
        self.name = name
        self.quotes = 0
        self.found = 0
        self.found5 = 0
        self.words = 0
        self.false = []  # type: List[Tuple[int, str, str]]
        self.false_live = []  # type: List[Tuple[int, str, str]]
        self.missed = []  # type: List[Tuple[int, str]]
        self.live = 0
        self.suggestions = []  # type: List[Tuple[int, str, float, bool, str, str]]

    def add(self, other: "Result") -> None:
        for k in ("quotes", "found", "found5", "words", "live"):
            setattr(self, k, getattr(self, k) + getattr(other, k))
        self.false += other.false
        self.false_live += other.false_live
        self.missed += other.missed

    @property
    def false_per_1000(self) -> float:
        return 1000.0 * len(self.false) / self.words if self.words else 0.0

    def summary(self) -> str:
        def pct(a, b):
            return 100.0 * a / b if b else 0.0

        return ("%-28s quotes %4d  found %5.1f%%  in top 5 %5.1f%%  false %3d (%.1f per 1000 words)  "
                "go-lives %3d, false %d" % (self.name, self.quotes, pct(self.found, self.quotes),
                                           pct(self.found5, self.quotes), len(self.false), self.false_per_1000,
                                           self.live, len(self.false_live)))


def _same_text(bible, pos: Pos, refs: Set[Pos]) -> bool:
    """Word for word the same verse elsewhere (Matthew 7:7 and Luke 11:9, Psalm 14 and 53)."""
    from biverse.quotes import keys
    mine = keys(bible.verse("KJV", *pos) or "")
    return bool(mine) and any(keys(bible.verse("KJV", *p) or "") == mine for p in refs)


def _label(pos: Pos) -> str:
    from biverse import books
    return "%s %d:%d" % (books.get(pos[0]).ref_name, pos[1], pos[2])


def run_file(path: str, bible, matcher: Optional[quotes.QuoteMatcher] = None) -> Result:
    lines, labelled = read(path, bible)
    matcher = matcher or quotes.QuoteMatcher(bible)
    matcher.reset()
    res = Result(os.path.basename(path))
    # each labelled quote is a run of consecutive lines with the same verses
    runs = []  # type: List[Tuple[int, int, Set[Pos]]]
    i = 0
    while i < len(lines):
        if lines[i].refs:
            j = i
            while j + 1 < len(lines) and lines[j + 1].refs == lines[i].refs:
                j += 1
            runs.append((i, j, lines[i].refs))
            i = j + 1
        else:
            i += 1
    top1 = {}  # type: Dict[int, Set[Pos]]   # line -> verses suggested first
    top5 = {}  # type: Dict[int, Set[Pos]]
    for n, line in enumerate(lines):
        res.words += len(line.text.split())
        found = matcher.feed(line.text, now=n * SECONDS_PER_UTTERANCE)
        if not found:
            continue
        best = found[0]
        top1.setdefault(n, set()).add(best.pos)
        top5.setdefault(n, set()).update(m.pos for m in found)
        res.suggestions.append((n, best.label(), best.strength, best.confirmed, best.heard, line.text))
        nearby = set()  # type: Set[Pos]
        for k in range(max(0, n - 2), n + 1):
            nearby |= lines[k].refs | lines[k].loose
        if best.confirmed:
            res.live += 1
        if labelled and best.pos not in nearby and not _same_text(bible, best.pos, nearby):
            res.false.append((n, best.label(), line.text))
            if best.confirmed:
                res.false_live.append((n, best.label(), line.text))
    def hit(found: Set[Pos], refs: Set[Pos]) -> bool:
        return bool(found & refs) or any(_same_text(bible, p, refs) for p in found)

    for a, b, refs in runs:
        res.quotes += 1
        span = range(a, min(len(lines), b + 2))
        if any(hit(top1.get(k, set()), refs) for k in span):
            res.found += 1
        else:
            res.missed.append((a, "/".join(sorted(_label(p) for p in refs))))
        if any(hit(top5.get(k, set()), refs) for k in span):
            res.found5 += 1
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", help="transcripts (default: tests/data/quotes/*.txt)")
    ap.add_argument("--review", default="", help="write every suggestion to this TSV file for review")
    ap.add_argument("--show", action="store_true", help="list misses and false suggestions")
    args = ap.parse_args(argv)
    from biverse.bible import open_default
    bible = open_default()
    if bible is None or not bible.has_ngram_index():
        print("data/bible.db has no quoted-verse index: run tools/build_bible_db.py", file=sys.stderr)
        return 2
    files = args.files or sorted(glob.glob(os.path.join(DATA, "*.txt")))
    matcher = quotes.QuoteMatcher(bible)
    total = Result("TOTAL")
    review = []
    for path in files:
        res = run_file(path, bible, matcher)
        total.add(res)
        print(res.summary())
        if args.show:
            for n, ref in res.missed:
                print("    missed  line %4d  %s" % (n + 1, ref))
            for n, ref, text in res.false:
                print("    FALSE   line %4d  %-18s %s" % (n + 1, ref, text))
        review += [(os.path.basename(path),) + s for s in res.suggestions]
    print(total.summary())
    if args.review:
        with open(args.review, "w", encoding="utf-8") as f:
            f.write("file\tline\tsuggested\tstrength\twould go live\tmatched words\tutterance\tcorrect? (y/n)\n")
            for name, n, ref, strength, live, heard, text in review:
                f.write("%s\t%d\t%s\t%.2f\t%s\t%s\t%s\t\n" % (name, n + 1, ref, strength, "yes" if live else "",
                                                              heard, re.sub(r"\s+", " ", text)))
        print("wrote %d suggestions to %s" % (len(review), args.review))
    return 1 if total.false_live else 0


if __name__ == "__main__":
    sys.exit(main())
