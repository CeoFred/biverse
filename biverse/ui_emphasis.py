"""Small editor: select words of a verse and make them bold, underlined or highlighted."""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import List

from . import books
from .emphasis import BOLD, HIGHLIGHT, UNDERLINE

MOD = "Command" if sys.platform == "darwin" else "Control"


class EmphasisDialog(object):
    def __init__(self, op, book: int, chapter: int, verse: int, code: str) -> None:
        self.op = op
        self.book, self.chapter, self.verse, self.code = book, chapter, verse, code
        self.text = op.bible.verse(code, book, chapter, verse) or ""
        self.words = self.text.split()
        self.spans = []  # type: List[Tuple[int, int]]  # char offsets of each word in the Text widget
        pos = 0
        for w in self.words:
            start = self.text.index(w, pos)
            self.spans.append((start, start + len(w)))
            pos = start + len(w)

        self.win = tk.Toplevel(op.root)
        self.win.title(u"Emphasis — %s %d:%d (%s)" % (books.get(book).ref_name, chapter, verse, code))
        self.win.transient(op.root)
        frame = ttk.Frame(self.win, padding=10)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Select words, then choose a style. The projector updates straight away.").pack(
            anchor="w")
        base = tkfont.nametofont("TkTextFont").actual()
        size = max(14, int(base.get("size", 12)) + 4)
        self.box = tk.Text(frame, wrap="word", height=6, width=56, font=(base["family"], size), padx=8, pady=8,
                           relief="flat", undo=False, cursor="xterm")
        self.box.pack(fill="both", expand=True, pady=8)
        self.box.insert("1.0", self.text)
        self.box.configure(state="disabled")  # selectable, not editable
        self.box.tag_configure(BOLD, font=(base["family"], size, "bold"))
        self.box.tag_configure(UNDERLINE, underline=True)
        self.box.tag_configure(HIGHLIGHT, background=op.settings.appearance.highlight_color, foreground="#111111")
        self.box.tag_raise("sel")
        btns = ttk.Frame(frame)
        btns.pack(fill="x")
        for label, style, key in (("Bold", BOLD, "b"), ("Underline", UNDERLINE, "u"), ("Highlight", HIGHLIGHT, "h")):
            ttk.Button(btns, text="%s (%s+%s)" % (label, "Cmd" if MOD == "Command" else "Ctrl", key.upper()),
                       command=lambda st=style: self.apply(st)).pack(side="left", padx=(0, 6))
            self.win.bind("<%s-%s>" % (MOD, key), lambda e, st=style: (self.apply(st), "break")[1])
        ttk.Button(btns, text="Clear selection", command=self.clear_selection).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Clear all", command=self.clear_all).pack(side="left")
        ttk.Button(btns, text="Close", command=self.win.destroy).pack(side="right")
        self.win.bind("<Escape>", lambda e: (self.win.destroy(), "break")[1])
        self._show_marks()
        self.box.focus_set()

    # -- selection <-> word indices -------------------------------------------------
    def selected_words(self) -> List[int]:
        try:
            a = int(self.box.count("1.0", "sel.first", "chars")[0] or 0)
            b = int(self.box.count("1.0", "sel.last", "chars")[0] or 0)
        except (tk.TclError, TypeError):
            return []
        return [i for i, (s, e) in enumerate(self.spans) if s < b and e > a]

    def select_words(self, indices) -> None:
        """Select whole words by index (used by tests and keyboard helpers)."""
        idx = sorted(indices)
        if not idx:
            return
        self.box.tag_remove("sel", "1.0", "end")
        self.box.tag_add("sel", "1.0 + %d chars" % self.spans[idx[0]][0], "1.0 + %d chars" % self.spans[idx[-1]][1])

    # -- actions ------------------------------------------------------------------------
    def apply(self, style: str) -> None:
        idx = self.selected_words()
        if not idx:
            self.op._status("Select some words first", error=True)
            return
        self.op.emphasis.toggle(self.code, self.book, self.chapter, self.verse, idx, style)
        self._changed()

    def clear_selection(self) -> None:
        self.op.emphasis.clear(self.code, self.book, self.chapter, self.verse, self.selected_words())
        self._changed()

    def clear_all(self) -> None:
        self.op.emphasis.clear(self.code, self.book, self.chapter, self.verse)
        self._changed()

    def _changed(self) -> None:
        self._show_marks()
        self.op._render_all()

    def _show_marks(self) -> None:
        marks = self.op.emphasis.get(self.code, self.book, self.chapter, self.verse)
        for st in (BOLD, UNDERLINE, HIGHLIGHT):
            self.box.tag_remove(st, "1.0", "end")
        for i, styles in marks.items():
            if 0 <= i < len(self.spans):
                s, e = self.spans[i]
                for st in styles:
                    self.box.tag_add(st, "1.0 + %d chars" % s, "1.0 + %d chars" % e)
