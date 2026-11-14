"""Sermon summary window: built-in summary, optional AI summary, copy and save."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import APP_NAME, llm
from .summary import SermonLog, as_text, clock, summarise


class SummaryWindow(object):
    def __init__(self, op, log: SermonLog) -> None:
        self.op = op
        self.log = log
        self.summary = summarise(log)
        self.ai_text = ""
        self._gen = 0  # bumped when the transcript changes; older AI results are dropped
        self._results = queue.Queue()  # type: queue.Queue
        p = op.pal

        self.win = tk.Toplevel(op.root)
        self.win.title("%s — Sermon summary" % APP_NAME)
        self.win.configure(background=p["bg"])
        self.win.geometry("760x620")
        frame = ttk.Frame(self.win, padding=12)
        frame.pack(fill="both", expand=True)
        when = time.strftime("%A %d %B %Y, %H:%M", time.localtime(log.started))
        ttk.Label(frame, text="Sermon summary", style="Title.TLabel").pack(anchor="w")
        self._when = when
        self.header = ttk.Label(frame, text="", style="Muted.TLabel")
        self.header.pack(anchor="w", pady=(0, 8))
        self._set_header()

        bar = ttk.Frame(frame)
        bar.pack(fill="x", pady=(0, 8))
        self.pack = llm.find_pack()
        self.ai_btn = ttk.Button(bar, text="✨ Write AI summary", style="Accent.TButton", command=self.run_ai)
        self.ai_btn.pack(side="left")
        ok, note = llm.describe(self.pack)
        self._ai_ok = ok
        if not ok or self.log.empty():
            self.ai_btn.state(["disabled"])
        self.ai_note = ttk.Label(bar, text=note if ok else note, style="Muted.TLabel")
        self.ai_note.pack(side="left", padx=10)
        ttk.Button(bar, text="Close", command=self.win.destroy).pack(side="right")
        ttk.Button(bar, text="Save as…", command=self.save).pack(side="right", padx=6)
        ttk.Button(bar, text="Copy", command=self.copy).pack(side="right")

        body = ttk.Frame(frame)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, wrap="word", relief="flat", borderwidth=0, padx=12, pady=10,
                            background=p["surface"], foreground=p["text"], selectbackground=p["select"],
                            highlightthickness=1, highlightbackground=p["border"], font=("TkDefaultFont", 12))
        sb = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("h", font=("TkDefaultFont", 13, "bold"), spacing1=10, spacing3=4)
        self.text.tag_configure("time", foreground=p["muted"])
        self.text.tag_configure("ref", foreground=p["accent"])
        self.text.tag_configure("ai", lmargin1=4, lmargin2=4, spacing3=6)
        self.text.tag_configure("muted", foreground=p["muted"])
        self.render()

    # -- content ---------------------------------------------------------------------
    def _set_header(self) -> None:
        self.header.configure(text="%s  ·  %s  ·  %d words heard" % (
            self._when, clock(self.summary["duration"]), self.summary["words"]))

    def reload(self) -> None:
        """The transcript was cleared or text was pasted: rebuild the summary and drop
        any AI summary written from the old transcript."""
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return
        self._gen += 1
        self.summary = summarise(self.log)
        self.ai_text = ""
        self._set_header()
        self.ai_btn.state(["disabled"] if not self._ai_ok or self.log.empty() else ["!disabled"])
        self.ai_note.configure(text="Transcript changed" if not self.log.empty() else "The transcript is empty")
        self.render()

    def render(self) -> None:
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        s = self.summary
        if self.log.empty():
            t.insert("end", "Nothing was heard yet. Press Listen during the sermon, or paste or import a "
                             "transcript (Service menu), then open this again.", "muted")
            t.configure(state="disabled")
            return
        if self.ai_text:
            t.insert("end", "Summary\n", "h")
            t.insert("end", self.ai_text.strip() + "\n", "ai")
        t.insert("end", "Scriptures\n", "h")
        if s["scriptures"]:
            for when, ref in s["scriptures"]:
                t.insert("end", "%s  " % clock(when), "time")
                t.insert("end", ref + "\n", "ref")
        else:
            t.insert("end", "(none detected)\n", "muted")
        t.insert("end", "Main themes\n", "h")
        t.insert("end", (", ".join(s["themes"]) or "-") + "\n")
        t.insert("end", "Key points\n", "h")
        for when, sent in s["key_points"]:
            t.insert("end", "%s  " % clock(when), "time")
            t.insert("end", sent + "\n")
        if not s["key_points"]:
            t.insert("end", "(not enough speech yet)\n", "muted")
        t.insert("end", "Timeline\n", "h")
        for when, words, refs in s["timeline"]:
            t.insert("end", "%s  " % clock(when), "time")
            t.insert("end", ", ".join(words))
            if refs:
                t.insert("end", "   " + "; ".join(refs), "ref")
            t.insert("end", "\n")
        t.configure(state="disabled")

    def text_for_export(self) -> str:
        return as_text(self.log, self.summary, self.ai_text)

    # -- actions ---------------------------------------------------------------------
    def copy(self) -> None:
        self.win.clipboard_clear()
        self.win.clipboard_append(self.text_for_export())
        self.ai_note.configure(text="Copied to the clipboard")

    def save(self) -> None:
        default = time.strftime("sermon-%Y-%m-%d.txt", time.localtime(self.log.started))
        path = filedialog.asksaveasfilename(parent=self.win, title="Save the sermon summary", initialfile=default,
                                            defaultextension=".txt",
                                            filetypes=[("Text", "*.txt"), ("Markdown", "*.md"), ("All files", "*")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text_for_export())
            self.ai_note.configure(text="Saved")

    def run_ai(self) -> None:
        if self.pack is None:
            return
        self.ai_btn.state(["disabled"])
        self.ai_note.configure(text="Writing the summary on this computer… (can take a minute)")

        gen, summary = self._gen, self.summary

        def work():
            try:
                self._results.put((gen, True, llm.summarise_ai(self.pack, summary)))
            except Exception as exc:
                self._results.put((gen, False, str(exc)))

        threading.Thread(target=work, name="ai-summary", daemon=True).start()
        self.win.after(300, self._poll)

    def _poll(self) -> None:
        try:
            gen, ok, value = self._results.get_nowait()
        except queue.Empty:
            if self.win.winfo_exists():
                self.win.after(300, self._poll)
            return
        if not self.win.winfo_exists():
            return
        if gen != self._gen:  # written from a transcript that has since changed
            return
        self.ai_btn.state(["!disabled"])
        if ok:
            self.ai_text = value
            self.ai_note.configure(text="AI summary written on this computer")
            self.render()
        else:
            self.ai_note.configure(text="AI summary failed")
            messagebox.showerror(APP_NAME, value, parent=self.win)
