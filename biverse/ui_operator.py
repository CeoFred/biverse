"""The operator's control window."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from . import APP_NAME, __version__, audio, displays, paths
from .bible import Bible
from . import commands
from .controller import LiveState, Selection, SlideBuilder, chapter_step, step
from .detector import NEW, Detector
from .parser import parse_typed
from .recognizer import SpeechEngine
from .render import BLACK, BLANK, EMPTY, Renderer, Slide
from .settings import Settings
from .ui_output import OutputWindow

log = logging.getLogger(__name__)

IS_MAC = sys.platform == "darwin"
MOD = "Command" if IS_MAC else "Control"
MOD_LABEL = "Cmd" if IS_MAC else "Ctrl"
POLL_MS = 50
TRANSCRIPT_SECONDS = 120
SAMPLE = Selection(19, 23, 1, 1)


class OperatorWindow(object):
    def __init__(self, root: tk.Tk, settings: Settings, bible: Bible) -> None:
        self.root = root
        self.settings = settings
        self.bible = bible
        self.events = queue.Queue()  # type: queue.Queue
        self.renderer = Renderer(root)
        from .emphasis import EmphasisStore
        self.emphasis = EmphasisStore()
        self.builder = SlideBuilder(bible, self.emphasis)
        self.preview = None  # type: Optional[Selection]
        self.live = LiveState()
        self.devices = []  # type: List[audio.InputDevice]
        self.displays = []  # type: List[displays.Display]
        self.display = None  # type: Optional[displays.Display]
        self.listening = False
        self.audio_retry_at = 0.0
        self._tick = 0
        self._transcript_lines = []  # type: List[float]
        self._detections = {}  # type: Dict[str, object]
        self._results = {}  # type: Dict[str, Selection]
        self._closing = False
        self._last_command = None
        self._partials_seen = False
        self._passage_start = None  # (book, chapter, verse) of the passage last sent live
        self.following = True       # follow-the-reading on/off ("stop there" / "continue")

        if not bible.has_translation(settings["translation"]):
            settings["translation"] = bible.default_translation()

        self.detector = Detector(strict=settings["strict_books"], relative=settings["relative_verses"],
                                 dedupe_window=float(settings["dedupe_window"]),
                                 verse_count=bible.verse_count)
        self.engine = SpeechEngine(self.events, self.detector)
        self.engine.use_reference = settings["reference_recognizer"]
        self.engine.commands = settings["voice_commands"]
        self.engine.translations = [(c, n) for c, n, _l in bible.translations()]
        self.capture = audio.AudioCapture(self.engine.audio_queue)

        from .follow import ReadingFollower
        codes = [c for c, _n, _l in bible.translations()]
        self.follower = ReadingFollower(
            lambda b, c, v: [t for t in (bible.verse(code, b, c, v) for code in codes) if t], bible.verse_count)
        self.output = OutputWindow(root, self.renderer, settings.appearance, on_visibility=self._on_output_visible)

        from . import theme as _theme
        self._theme = _theme
        self.theme_mode = self._wanted_theme()
        self.pal = _theme.apply(root, self.theme_mode)
        root.title("%s %s" % (APP_NAME, __version__))
        root.minsize(900, 560)
        self._build_menu()
        self._build()
        self._bind_keys()
        self._restore_geometry()

        self.refresh_devices(initial=True)
        self.refresh_displays(initial=True)
        if settings["output_visible"]:
            self.output.show()
        self._render_all()
        self.engine.load(settings["speech_model"], settings["model_path"])
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(POLL_MS, self._poll)

    # ------------------------------------------------------------------ build
    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        filem = tk.Menu(menubar, tearoff=False)
        filem.add_command(label="Settings…", command=self.open_settings)
        filem.add_separator()
        filem.add_command(label="Quit", command=self.close, accelerator="%s+Q" % MOD_LABEL)
        menubar.add_cascade(label="File", menu=filem)
        outm = tk.Menu(menubar, tearoff=False)
        outm.add_command(label="Show / hide output", command=self.toggle_output)
        outm.add_command(label="Toggle output full screen (F11)", command=self.output.toggle_fullscreen)
        outm.add_command(label="Test output", command=self.test_output)
        outm.add_command(label="Refresh displays", command=self.refresh_displays)
        menubar.add_cascade(label="Output", menu=outm)
        helpm = tk.Menu(menubar, tearoff=False)
        helpm.add_command(label="Keyboard shortcuts", command=self.show_shortcuts)
        helpm.add_command(label="Open log folder", command=self.open_log_folder)
        helpm.add_command(label="About %s" % APP_NAME, command=self.show_about)
        menubar.add_cascade(label="Help", menu=helpm)
        self.root.configure(menu=menubar)

    def _build(self) -> None:
        root = self.root
        outer = ttk.Frame(root, padding=(10, 8, 10, 10))
        outer.pack(fill="both", expand=True)

        # banner (missing model / errors)
        self.banner = tk.Label(outer, text="", anchor="w", justify="left", padx=10, pady=6, wraplength=900)

        # row 1: input
        r1 = ttk.Frame(outer)
        r1.pack(fill="x", pady=(0, 4))
        ttk.Label(r1, text=APP_NAME, style="Title.TLabel").pack(side="left", padx=(0, 14))
        ttk.Label(r1, text="Input", style="Muted.TLabel").pack(side="left")
        self.input_var = tk.StringVar()
        self.input_combo = ttk.Combobox(r1, textvariable=self.input_var, state="readonly", width=38)
        self.input_combo.pack(side="left", padx=(4, 2))
        self.input_combo.bind("<<ComboboxSelected>>", lambda e: self._on_device_selected())
        ttk.Button(r1, text="⟳", width=3, command=self.refresh_devices).pack(side="left")
        self.meter = tk.Canvas(r1, width=110, height=12, highlightthickness=0, borderwidth=0)
        self.meter.pack(side="left", padx=8)
        self.listen_dot = tk.Label(r1, text="●", font=("TkDefaultFont", 14))
        self.listen_dot.pack(side="left")
        self.listen_btn = ttk.Button(r1, text="Listen", width=10, command=self.toggle_listen)
        self.listen_btn.pack(side="left", padx=(2, 10))
        self.status_var = tk.StringVar(value="Starting…")
        self.status_label = tk.Label(r1, textvariable=self.status_var, anchor="w")
        self.status_label.pack(side="left", fill="x", expand=True, padx=4)
        self._status_error = False

        # row 2: output + translation
        r2 = ttk.Frame(outer)
        r2.pack(fill="x", pady=4)
        ttk.Label(r2, text="Output", style="Muted.TLabel").pack(side="left")
        self.display_var = tk.StringVar()
        self.display_combo = ttk.Combobox(r2, textvariable=self.display_var, state="readonly", width=30)
        self.display_combo.pack(side="left", padx=(4, 2))
        self.display_combo.bind("<<ComboboxSelected>>", lambda e: self._on_display_selected())
        ttk.Button(r2, text="⟳", width=3, command=self.refresh_displays).pack(side="left")
        self.output_btn = ttk.Button(r2, text="Show output", width=12, command=self.toggle_output)
        self.output_btn.pack(side="left", padx=6)
        ttk.Label(r2, text="Bible", style="Muted.TLabel").pack(side="left", padx=(10, 0))
        self.translation_var = tk.StringVar(value=self.settings["translation"])
        codes = [c for c, _, _ in self.bible.translations()]
        self.translation_combo = ttk.Combobox(r2, textvariable=self.translation_var, values=codes,
                                              state="readonly", width=8)
        self.translation_combo.pack(side="left", padx=4)
        self.translation_combo.bind("<<ComboboxSelected>>", lambda e: self._on_translation())
        self.translation_name = ttk.Label(r2, text="", style="Muted.TLabel")
        self.translation_name.pack(side="left")

        # row 3: mode + settings
        r3 = ttk.Frame(outer)
        r3.pack(fill="x", pady=(4, 8))
        ttk.Label(r3, text="Mode", style="Muted.TLabel").pack(side="left")
        self.mode_var = tk.StringVar(value=self.settings["mode"])
        ttk.Radiobutton(r3, text="Manual", value="manual", variable=self.mode_var,
                        command=self._on_mode).pack(side="left", padx=4)
        ttk.Radiobutton(r3, text="Auto", value="auto", variable=self.mode_var,
                        command=self._on_mode).pack(side="left", padx=4)
        self.mode_hint = ttk.Label(r3, text="", style="Muted.TLabel")
        self.mode_hint.pack(side="left", padx=8)
        ttk.Button(r3, text="⚙ Settings", command=self.open_settings).pack(side="right")
        self.banner_anchor = r1

        # main area
        main = ttk.PanedWindow(outer, orient="horizontal")
        main.pack(fill="both", expand=True)
        left = ttk.PanedWindow(main, orient="vertical")
        right = ttk.Frame(main)
        main.add(left, weight=2)
        main.add(right, weight=3)

        tframe = ttk.LabelFrame(left, text="TRANSCRIPT", padding=6)
        self.transcript = tk.Text(tframe, height=8, wrap="word", state="disabled", relief="flat", borderwidth=0,
                                  highlightthickness=0, padx=6, pady=4, font=("TkDefaultFont", 12))
        tscroll = ttk.Scrollbar(tframe, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=tscroll.set)
        tscroll.pack(side="right", fill="y")
        self.transcript.pack(fill="both", expand=True)

        left.add(tframe, weight=1)

        dframe = ttk.LabelFrame(left, text="DETECTED  \u00b7  click = preview, double-click = go live", padding=6)
        self.detected = ttk.Treeview(dframe, columns=("time", "ref", "snippet"), show="headings",
                                     selectmode="browse", height=6)
        for col, title, width, stretch in (("time", "Time", 70, False), ("ref", "Reference", 140, False),
                                           ("snippet", "Heard", 200, True)):
            self.detected.heading(col, text=title, anchor="w")
            self.detected.column(col, width=width, stretch=stretch, anchor="w")
        dscroll = ttk.Scrollbar(dframe, command=self.detected.yview)
        self.detected.configure(yscrollcommand=dscroll.set)
        dscroll.pack(side="right", fill="y")
        self.detected.pack(fill="both", expand=True)
        self.detected.bind("<<TreeviewSelect>>", lambda e: self._on_detection_click())
        self.detected.bind("<Double-1>", lambda e: self._on_detection_double())
        self.detected.bind("<Return>", lambda e: self._on_detection_double())
        left.add(dframe, weight=1)

        # right: thumbnails
        thumbs = ttk.Frame(right)
        thumbs.pack(fill="x", padx=(6, 0))
        thumbs.columnconfigure(0, weight=1, uniform="t")
        thumbs.columnconfigure(1, weight=1, uniform="t")
        ttk.Label(thumbs, text="PREVIEW", style="PreviewHead.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(thumbs, text=u"\u25cf LIVE", style="LiveHead.TLabel").grid(
            row=0, column=1, sticky="w", padx=(6, 0))
        self.preview_canvas = tk.Canvas(thumbs, background="#000000", highlightthickness=2, height=120)
        self.live_canvas = tk.Canvas(thumbs, background="#000000", highlightthickness=2, height=120)
        self.preview_canvas.grid(row=1, column=0, sticky="ew")
        self.live_canvas.grid(row=1, column=1, sticky="ew", padx=(6, 0))
        self.preview_label = ttk.Label(thumbs, text="—")
        self.live_label = ttk.Label(thumbs, text="—")
        self.preview_label.grid(row=2, column=0, sticky="w")
        self.live_label.grid(row=2, column=1, sticky="w", padx=(6, 0))
        ttk.Button(thumbs, text=u"\u270e Emphasis", width=10, command=self.open_emphasis).grid(
            row=2, column=1, sticky="e")
        thumbs.bind("<Configure>", lambda e: self._resize_thumbs(e.width))
        self.preview_canvas.bind("<Double-1>", lambda e: self.go_live())

        buttons = ttk.Frame(right)
        buttons.pack(fill="x", padx=(6, 0), pady=4)
        for col in range(4):
            buttons.columnconfigure(col, weight=1, uniform="b")
        ttk.Button(buttons, text="◀ Prev", command=lambda: self.step(-1)).grid(row=0, column=0, sticky="ew")
        self.golive_btn = ttk.Button(buttons, text="GO LIVE ▶", command=self.go_live, style="Accent.TButton")
        self.golive_btn.grid(row=0, column=1, columnspan=2, sticky="ew", padx=4)
        ttk.Button(buttons, text="Next ▶", command=lambda: self.step(1)).grid(row=0, column=3, sticky="ew")
        ttk.Button(buttons, text="BLANK (Esc)", command=self.blank).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0), padx=(0, 2))
        ttk.Button(buttons, text="BLACK (Shift+Esc)", command=self.black).grid(
            row=1, column=2, columnspan=2, sticky="ew", pady=(4, 0), padx=(2, 0))
        self.follow_btn = ttk.Button(buttons, text="Pause following (F6)", command=self.toggle_following)
        self.follow_btn.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 0), padx=(0, 2))
        self.follow_label = tk.Label(buttons, text="", anchor="w")
        self.follow_label.grid(row=2, column=2, columnspan=2, sticky="ew", pady=(4, 0), padx=(4, 0))

        sframe = ttk.LabelFrame(right, text="SEARCH", padding=6)
        sframe.pack(fill="both", expand=True, padx=(6, 0))
        srow = ttk.Frame(sframe)
        srow.pack(fill="x")
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(srow, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<Return>", lambda e: self.search())
        self.search_entry.bind("<KP_Enter>", lambda e: self.search())
        ttk.Button(srow, text="Find", command=self.search).pack(side="left", padx=(4, 0))
        self.search_info = ttk.Label(sframe, text="Type a reference (jn 3:16, 1 cor 13 4-7) or words "
                                                  "(for god so loved)", style="CardMuted.TLabel")
        self.search_info.pack(fill="x", pady=(2, 2))
        rframe = ttk.Frame(sframe)
        rframe.pack(fill="both", expand=True)
        self.results = ttk.Treeview(rframe, columns=("ref", "text"), show="headings", selectmode="browse",
                                    height=5)
        self.results.heading("ref", text="Reference", anchor="w")
        self.results.heading("text", text="Text", anchor="w")
        self.results.column("ref", width=130, stretch=False)
        self.results.column("text", width=300, stretch=True)
        rscroll = ttk.Scrollbar(rframe, command=self.results.yview)
        self.results.configure(yscrollcommand=rscroll.set)
        rscroll.pack(side="right", fill="y")
        self.results.pack(fill="both", expand=True)
        self.results.bind("<<TreeviewSelect>>", lambda e: self._on_result_click())
        self.results.bind("<Double-1>", lambda e: self.go_live())
        self.results.bind("<Return>", lambda e: self.go_live())

        self._update_translation_name()
        self._update_mode_hint()
        self._apply_theme_to_tk()

    def _bind_keys(self) -> None:
        r = self.root
        r.bind_all("<F6>", lambda e: self._key(self.toggle_following))
        r.bind_all("<%s-e>" % MOD, lambda e: self._key(self.open_emphasis))
        for seq in ("<%s-Return>" % MOD, "<%s-KP_Enter>" % MOD, "<F5>"):
            r.bind_all(seq, lambda e: self._key(self.go_live))
        r.bind_all("<Escape>", lambda e: self._key(self.blank))
        r.bind_all("<Shift-Escape>", lambda e: self._key(self.black))
        r.bind("<<OutputEscape>>", lambda e: self.blank())
        r.bind_all("<Left>", lambda e: self._arrow(-1, e))
        r.bind_all("<Right>", lambda e: self._arrow(1, e))
        r.bind_all("<%s-f>" % MOD, lambda e: self._key(self.focus_search))
        r.bind_all("<%s-l>" % MOD, lambda e: self._key(self.toggle_listen))
        r.bind_all("<%s-m>" % MOD, lambda e: self._key(self.toggle_mode))
        r.bind_all("<%s-q>" % MOD, lambda e: self._key(self.close))
        if IS_MAC:
            r.createcommand("tk::mac::Quit", self.close)
            r.createcommand("tk::mac::ShowPreferences", self.open_settings)

    def _key(self, fn) -> str:
        fn()
        return "break"

    def _arrow(self, delta: int, event) -> Optional[str]:
        w = event.widget
        if isinstance(w, (tk.Entry, ttk.Entry, tk.Text, ttk.Combobox, tk.Spinbox)):
            return None
        if isinstance(w, str):
            return None
        self.step(delta, live=True)
        return "break"

    # ------------------------------------------------------------ geometry
    def _restore_geometry(self) -> None:
        geo = self.settings["window_geometry"]
        if geo:
            try:
                size, _, _ = geo.partition("+")
                w, h = [int(x) for x in size.split("x")]
                sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
                if w <= sw * 2 and h <= sh * 2:
                    self.root.geometry(geo)
                    return
            except ValueError:
                pass
        self.root.geometry("1100x680")

    def _resize_thumbs(self, width: int) -> None:
        if width < 50:
            return
        tw = max(80, (width - 6) // 2 - 4)
        ow, oh = self.output.size
        th = int(tw * oh / float(ow)) if ow else int(tw * 9 / 16)
        avail = max(80, self.root.winfo_height() // 3)
        if th > avail:
            th = avail
        for c in (self.preview_canvas, self.live_canvas):
            if int(c.cget("height")) != th:
                c.configure(height=th)
        self.root.after_idle(self._render_thumbs)

    # -------------------------------------------------------------- devices
    def refresh_devices(self, initial: bool = False) -> None:
        if not audio.available():
            self.input_combo.configure(values=["(audio unavailable)"])
            self.input_var.set("(audio unavailable)")
            self._set_banner("Audio is unavailable: %s" % audio.SD_ERROR)
            return
        was_listening = self.listening
        if was_listening and not initial:
            self.capture.stop()
        self.devices = audio.list_input_devices(refresh=not initial)
        labels = [d.label() for d in self.devices] or ["(no input devices)"]
        self.input_combo.configure(values=labels)
        dev = audio.find_device(self.devices, self.settings["input_device"]) or audio.default_device(self.devices)
        self.input_var.set(dev.label() if dev else labels[0])
        if was_listening and not initial:
            self._start_capture()

    def current_device(self) -> Optional[audio.InputDevice]:
        label = self.input_var.get()
        for d in self.devices:
            if d.label() == label:
                return d
        return None

    def _on_device_selected(self) -> None:
        dev = self.current_device()
        if dev is None:
            return
        self.settings["input_device"] = dev.key()
        if self.listening:
            self._start_capture()

    def refresh_displays(self, initial: bool = False) -> None:
        self.displays = displays.list_displays(self.root)
        self.display_combo.configure(values=[d.label() for d in self.displays])
        current = None
        if initial:
            current = displays.find_saved(self.displays, self.settings["output_display"])
        elif self.display is not None:
            current = displays.find_saved(self.displays, self.display.key())
        if current is None:
            current = displays.default_display(self.displays)
        self._use_display(current)

    def _use_display(self, d: displays.Display) -> None:
        self.display = d
        self.display_var.set(d.label())
        self.settings["output_display"] = d.key()
        only_one = len(self.displays) == 1
        # one screen: a windowed preview instead of covering the operator window
        self.output.place(d, fullscreen=not only_one)
        self._resize_thumbs(self.preview_canvas.master.winfo_width())

    def _on_display_selected(self) -> None:
        label = self.display_var.get()
        for d in self.displays:
            if d.label() == label:
                self._use_display(d)
                return

    def _displays_changed(self) -> bool:
        """Cheap periodic check (Windows/macOS) for plugged/unplugged screens."""
        if sys.platform not in ("win32", "darwin"):
            return False
        now = displays.list_displays(self.root)
        return [d.key() for d in now] != [d.key() for d in self.displays]

    # --------------------------------------------------------------- listen
    def toggle_listen(self) -> None:
        if self.listening:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self) -> None:
        if self.engine.state in ("missing", "error"):
            self._status("No speech model — see the yellow banner", error=True)
            return
        if not audio.available():
            self._status("Audio unavailable", error=True)
            return
        self.listening = True
        self.engine.start()
        self._start_capture()
        self._update_listen_ui()

    def _start_capture(self) -> bool:
        """Open the selected device in the background; the result arrives as an "audio" event."""
        dev = self.current_device()
        if dev is None:
            self._status("No input device selected", error=True)
            self.audio_retry_at = time.monotonic() + 3
            return False
        self.audio_retry_at = 0.0
        self._status("Opening %s\u2026" % dev.name)
        self.capture.start_async(dev, lambda ok, msg: self.events.put(("audio", ok, msg)))
        return True

    def _on_audio(self, ok: bool, msg: str) -> None:
        if not self.listening:
            if ok:
                self.capture.stop()
            return
        if ok:
            dev = self.current_device()
            if dev is not None:
                self.settings["input_device"] = dev.key()
            self.audio_retry_at = 0.0
            self._update_listen_ui()
            return
        log.warning("audio: %s", msg)
        if self.capture.opening:
            # still blocked inside PortAudio: keep waiting rather than piling up threads
            self._status(msg, error=True)
        else:
            self._status("Cannot open audio: %s \u2014 retrying\u2026" % msg, error=True)
            self.audio_retry_at = time.monotonic() + 3

    def stop_listening(self) -> None:
        self.listening = False
        self.capture.stop()
        self.engine.stop()
        self.audio_retry_at = 0.0
        self._clear_partial()
        self._update_listen_ui()

    def _update_listen_ui(self) -> None:
        if self.listening:
            self.listen_dot.configure(foreground=self.pal["live"])
            self.listen_btn.configure(text="Stop")
            if self.engine.state == "loading":
                self._status("Loading speech model…")
            elif self.capture.running:
                self._status("Listening \u2014 %s" % self.engine.model_label if self.engine.model_label
                             else "Listening")
            elif self.capture.opening:
                self._status("Opening audio device\u2026")
        else:
            self.listen_dot.configure(foreground=self.pal["muted"])
            self.listen_btn.configure(text="Listen")
            idle = "Idle \u2014 %s" % self.engine.model_label if self.engine.model_label else "Idle"
            self._status({"loading": "Loading speech model…", "missing": "No speech model",
                          "error": "Speech model failed to load"}.get(self.engine.state, idle),
                         error=self.engine.state in ("missing", "error"))

    def _audio_watchdog(self) -> None:
        if not self.listening:
            return
        if self.capture.running and not self.capture.healthy():
            msg = self.capture.error or "audio stopped"
            log.warning("audio problem: %s", msg)
            self.capture.stop()
            self._status("Audio lost: %s — retrying…" % msg, error=True)
            self.audio_retry_at = time.monotonic() + 3
        elif (not self.capture.running and not self.capture.opening and self.audio_retry_at
              and time.monotonic() >= self.audio_retry_at):
            # re-scan (hot-plug) and reopen the same device by name + host API
            saved = self.settings["input_device"]
            self.devices = audio.list_input_devices(refresh=True)
            self.input_combo.configure(values=[d.label() for d in self.devices] or ["(no input devices)"])
            dev = audio.find_device(self.devices, saved)
            if dev is not None:
                self.input_var.set(dev.label())
                self._start_capture()
            else:
                self.audio_retry_at = time.monotonic() + 3

    # ----------------------------------------------------------- events
    def _poll(self) -> None:
        if self._closing:
            return
        try:
            for _ in range(200):
                try:
                    ev = self.events.get_nowait()
                except queue.Empty:
                    break
                self._handle(ev)
            self._draw_meter()
            self._tick += 1
            if self._tick % 20 == 0:
                self._audio_watchdog()
                self._prune_transcript()
            if self._tick % 100 == 50 and self.settings["ui_theme"] == "system":
                self._check_theme()
            if self._tick % 100 == 0 and self._displays_changed():
                log.info("display configuration changed")
                self.refresh_displays()
        except Exception:
            log.exception("poll error")
        self.root.after(POLL_MS, self._poll)

    def _handle(self, ev) -> None:
        kind = ev[0]
        if kind == "partial":
            self._set_partial(ev[1])
            if ev[1] and ev[1] != u"\u2026":
                self._partials_seen = True
                self._follow(ev[1], final=False)
        elif kind == "final":
            self._add_final(ev[1])
            if not self._partials_seen:  # Parakeet alone: only phrase-level text to follow
                self._follow(ev[1], final=True)
        elif kind == "detect":
            self._on_detection(ev[1], ev[2])
        elif kind == "model":
            self._on_model(ev[1], ev[2])
        elif kind == "pack":
            self._on_pack(ev[1], ev[2])
        elif kind == "command":
            self._on_command(ev[1], ev[2], ev[3], ev[4])
        elif kind == "audio":
            self._on_audio(ev[1], ev[2])
        elif kind == "error":
            self._status(ev[1], error=True)

    def _on_model(self, state: str, detail: str) -> None:
        if state == "missing":
            self._set_banner(
                "No speech model could be used (%s), so listening is off. Manual search and projection still "
                "work.\nTo fix: re-extract the %s download, or use Settings \u2192 Speech to choose or install a "
                "model (see the User Guide)." % (detail, APP_NAME))
        elif state == "error":
            self._set_banner("The speech model could not be loaded: %s\nChoose another model in "
                             "Settings \u2192 Speech." % detail)
        else:
            self._set_banner("")
        if state == "ready":
            log.info("speech model ready: %s", detail)
        self._update_listen_ui()

    def install_pack(self, zip_path: str) -> None:
        """Install a model pack in the background; result arrives as a "pack" event."""
        from . import modelpack
        self._status("Installing speech model pack\u2026 (this can take a minute)")

        def work():
            try:
                info = modelpack.install(zip_path)
                self.events.put(("pack", True, info.label))
            except Exception as exc:
                log.exception("model pack install failed")
                self.events.put(("pack", False, str(exc)))

        threading.Thread(target=work, name="pack-install", daemon=True).start()

    def _on_pack(self, ok: bool, detail: str) -> None:
        if ok:
            self._status("Installed %s" % detail)
            messagebox.showinfo(APP_NAME, "%s is installed. %s will use it when the speech model is set to "
                                "Automatic (on a 64-bit computer with enough memory) or when you choose it "
                                "in Settings \u2192 Speech." % (detail, APP_NAME), parent=self.root)
            self.reload_model()
        else:
            self._status("Model pack not installed", error=True)
            messagebox.showerror(APP_NAME, "The model pack could not be installed:\n\n%s" % detail,
                                 parent=self.root)

    # -- look ------------------------------------------------------------------------
    def _wanted_theme(self) -> str:
        forced = os.environ.get("BIVERSE_THEME") or self.settings["ui_theme"]
        return forced if forced in ("dark", "light") else self._theme.system_mode()

    def _check_theme(self) -> None:
        mode = self._wanted_theme()
        if mode != self.theme_mode:
            self.set_theme(mode)

    def set_theme(self, mode: str) -> None:
        self.theme_mode = mode
        self.pal = self._theme.apply(self.root, mode)
        self._apply_theme_to_tk()
        self._update_listen_ui()
        self._update_mode_hint()
        self._update_follow_ui()

    def _apply_theme_to_tk(self) -> None:
        """Colours for plain tk widgets (ttk ones follow the style)."""
        p = self.pal
        self.banner.configure(background=p["banner_bg"], foreground=p["banner_fg"])
        self.meter.configure(background=p["meter_bg"])
        for w in (self.listen_dot, self.status_label, self.follow_label):
            w.configure(background=p["bg"])
        self.status_label.configure(foreground=p["error"] if self._status_error else p["text"])
        self.transcript.configure(background=p["surface"], foreground=p["text"], insertbackground=p["text"],
                                  selectbackground=p["select"])
        self.transcript.tag_configure("partial", foreground=p["partial"])
        self.transcript.tag_configure("time", foreground=p["muted"])
        self.preview_canvas.configure(highlightbackground=p["accent"])
        self.live_canvas.configure(highlightbackground=p["live"])
        style = ttk.Style(self.root)
        style.configure("PreviewHead.TLabel", background=p["bg"], foreground=p["accent"],
                        font=("TkDefaultFont", 10, "bold"))
        style.configure("LiveHead.TLabel", background=p["bg"], foreground=p["live"], font=("TkDefaultFont", 10, "bold"))
        style.configure("Live.TLabel", background=p["bg"], foreground=p["live"])

    def _set_banner(self, text: str) -> None:
        if text:
            self.banner.configure(text=text)
            if not self.banner.winfo_ismapped():
                self.banner.pack(fill="x", pady=(0, 4), before=self.banner_anchor)
        else:
            self.banner.pack_forget()

    def _status(self, text: str, error: bool = False) -> None:
        self.status_var.set(text)
        self._status_error = error
        self.status_label.configure(foreground=self.pal["error"] if error else self.pal["text"])

    # transcript
    def _insert_transcript(self, fn) -> None:
        t = self.transcript
        at_end = t.yview()[1] >= 0.999
        t.configure(state="normal")
        fn(t)
        t.configure(state="disabled")
        if at_end:
            t.see("end")

    def _clear_partial(self) -> None:
        def f(t):
            ranges = t.tag_ranges("partial")
            if ranges:
                t.delete(ranges[0], ranges[-1])
        self._insert_transcript(f)

    def _set_partial(self, text: str) -> None:
        def f(t):
            ranges = t.tag_ranges("partial")
            if ranges:
                t.delete(ranges[0], ranges[-1])
            if text:
                t.insert("end", text, "partial")
        self._insert_transcript(f)

    def _add_final(self, text: str) -> None:
        def f(t):
            ranges = t.tag_ranges("partial")
            if ranges:
                t.delete(ranges[0], ranges[-1])
            t.insert("end", time.strftime("%H:%M:%S "), "time")
            t.insert("end", text + "\n")
        self._insert_transcript(f)
        self._transcript_lines.append(time.monotonic())

    def _prune_transcript(self) -> None:
        cutoff = time.monotonic() - TRANSCRIPT_SECONDS
        n = 0
        while self._transcript_lines and self._transcript_lines[0] < cutoff:
            self._transcript_lines.pop(0)
            n += 1
        if n:
            def f(t):
                t.delete("1.0", "%d.0" % (n + 1))
            self._insert_transcript(f)

    # detections
    def _on_detection(self, kind: str, det) -> None:
        ref = det.ref
        sel = Selection.from_reference(ref)
        label = sel.passage_label() + ("  (relative)" if ref.relative else "")
        iid = str(det.id)
        values = (time.strftime("%H:%M:%S", time.localtime(det.wall_time)), label, det.snippet)
        if kind == NEW or not self.detected.exists(iid):
            self.detected.insert("", 0, iid=iid, values=values)
            children = self.detected.get_children()
            for old in children[200:]:
                self.detected.delete(old)
                self._detections.pop(old, None)
        else:
            self.detected.item(iid, values=values)
            self.detected.move(iid, "", 0)
        self._detections[iid] = sel
        log.info("detected %s (%s): %r", label, kind, det.snippet)
        from .parser import AUTO_MIN_CONFIDENCE
        auto_ok = (self.mode_var.get() == "auto" and ref.confidence >= AUTO_MIN_CONFIDENCE
                   and (ref.explicit_verse or not self.settings["auto_requires_verse"]))
        if auto_ok:
            self.set_preview(sel.copy())
            self.go_live()
        else:
            self.set_preview(sel.copy())

    def _on_detection_click(self) -> None:
        sel = self.detected.selection()
        if sel and sel[0] in self._detections:
            self.set_preview(self._detections[sel[0]].copy())

    def _on_detection_double(self) -> None:
        self._on_detection_click()
        self.go_live()

    # ----------------------------------------------------------- preview / live
    def translation(self) -> str:
        return self.translation_var.get() or self.bible.default_translation()

    def _fits(self, text: str) -> bool:
        w, h = self.output.size
        return self.renderer.fits(text, self.settings.appearance, w, h)

    def _on_command(self, intent, channel: str, t: float, heard: str) -> None:
        """A spoken navigation intent ("next verse", "go back two verses", "chapter 4",
        "stop there", "let's continue")."""
        if isinstance(intent, str):  # v1.2 command names
            intent = {commands.NEXT_VERSE: commands.Intent(commands.STEP, commands.VERSE, 1),
                      commands.PREV_VERSE: commands.Intent(commands.STEP, commands.VERSE, -1),
                      commands.NEXT_CHAPTER: commands.Intent(commands.STEP, commands.CHAPTER, 1),
                      commands.PREV_CHAPTER: commands.Intent(commands.STEP, commands.CHAPTER, -1)}[intent]
        last = self._last_command
        # With both models running, Kroko and Parakeet each hear the same words.
        if last and last[0] == intent and last[1] != channel and t - last[2] < 3.0:
            return
        self._last_command = (intent, channel, t)
        label = intent.label()
        log.info("voice intent %s (%s): %r", label, channel, heard)
        if intent.kind == commands.TRANSLATION:
            self._voice_translation(intent)
            return
        if intent.kind in (commands.STOP, commands.RESUME):
            self.set_following(intent.kind == commands.RESUME, source="voice")
            return
        base = self.live.selection or self.preview
        if base is None:
            self._status("Heard \"%s\" but nothing is on screen" % label)
            return
        new = self._navigate(base, intent)
        if new is None:
            self._status("Heard \"%s\" \u2014 not possible from %s" % (label, base.verse_label()))
            return
        if self.mode_var.get() == "auto":
            self.live.selection = new
            self.live.cover = None
            self._render_live()
            self._status("Voice: %s \u2192 %s (live)" % (label, new.verse_label()))
        else:
            self.set_preview(new)
            self._status("Voice: %s \u2192 %s in Preview (press Go Live)" % (label, new.verse_label()))

    def _voice_translation(self, intent) -> None:
        """"Let's read this in the ASV": switch the Bible version (stays until changed)."""
        if not intent.code:
            have = ", ".join(c for c, _n, _l in self.bible.translations())
            self._status("Heard a request for the %s, which is not installed (installed: %s)" % (intent.where, have),
                         error=True)
            return
        if intent.code == self.translation():
            self._status("Already showing the %s" % intent.code)
            return
        self.translation_var.set(intent.code)
        self._on_translation()
        self._status("Voice: switched to %s" % intent.code)

    def _navigate(self, base: Selection, intent) -> Optional[Selection]:
        if intent.kind == commands.STEP:
            sel = base
            for _ in range(abs(intent.delta)):
                d = 1 if intent.delta > 0 else -1
                nxt = step(self.bible, sel, d) if intent.unit == commands.VERSE else chapter_step(self.bible, sel, d)
                if nxt is None:
                    break
                sel = nxt
            return None if sel is base else sel
        if intent.kind == commands.GOTO:
            if intent.where == "chapter_start":
                return Selection(base.book, base.chapter, 1, 1)
            if intent.where == "passage_start":
                start = self._passage_start or (base.book, base.chapter, base.start)
                return Selection(start[0], start[1], start[2], start[2])
            c, v = intent.chapter, intent.verse or 1
            if self.bible.verse_count(base.book, c) >= v:
                return Selection(base.book, c, v, v)
        return None

    def set_preview(self, sel: Optional[Selection]) -> None:
        self.preview = sel
        self._render_preview()

    def set_following(self, on: bool, source: str = "") -> None:
        self.following = bool(on)
        self.follower.paused = not self.following
        if self.following:
            self._restart_follower()
        self._status("Following the reading %s%s" % ("resumed" if on else "paused \u2014 say \"continue\" to resume",
                                                      " (voice)" if source else ""))
        self._update_follow_ui()

    def toggle_following(self) -> None:
        self.set_following(not self.following)

    def _follow_enabled(self) -> bool:
        return (self.settings["follow_reading"] and self.following and self.live.selection is not None
                and self.live.cover is None)

    def _restart_follower(self) -> None:
        sel = self.live.selection
        if sel is None:
            self.follower.stop()
            return
        end = sel.end if sel.is_range else None
        self.follower.start(sel.book, sel.chapter, sel.cur, end, time.monotonic())

    def _follow(self, text: str, final: bool) -> None:
        """Feed recogniser text to the reading follower; move the live verse when it says so."""
        if not self._follow_enabled():
            return
        sel = self.live.selection
        f = self.follower
        if (f.book, f.chapter, f.verse) != (sel.book, sel.chapter, sel.cur):
            self._restart_follower()
        move = f.feed(text, time.monotonic(), final=final)
        if move is None:
            self._update_follow_ui()
            return
        if sel.start <= move.verse <= sel.end:
            new = sel.copy()
            new.cur = move.verse
            new.whole = False
        else:
            new = Selection(sel.book, sel.chapter, move.verse, move.verse)
        log.info("following: %s -> verse %d (%s)", sel.verse_label(), move.verse, move.reason)
        self.live.selection = new
        self._render_live()
        self._status("Following: %s" % new.verse_label())

    def _update_follow_ui(self) -> None:
        if not self.settings["follow_reading"]:
            text, color = "Following off (Settings)", self.pal["muted"]
        elif not self.following:
            text, color = u"\u2016 Paused \u2014 say \"continue\"", self.pal["warn"]
        elif self.live.selection is None or self.live.cover is not None:
            text, color = u"\u25cf Following (waiting for a verse)", self.pal["muted"]
        else:
            text, color = u"\u25cf Following  %d%%" % int(100 * self.follower.progress), self.pal["ok"]
        self.follow_label.configure(text=text, foreground=color)
        self.follow_btn.configure(text="Pause following (F6)" if self.following else "Resume following (F6)")

    def go_live(self) -> None:
        if self.preview is None:
            return
        self._passage_start = (self.preview.book, self.preview.chapter, self.preview.start)
        self.live.selection = self.preview.copy()
        self.live.cover = None
        self._render_live()

    def blank(self) -> None:
        self.live.toggle_cover(BLANK)
        self._render_live()

    def black(self) -> None:
        self.live.toggle_cover(BLACK)
        self._render_live()

    def step(self, delta: int, live: Optional[bool] = None) -> None:
        """Prev/Next: the live verse when something is live, otherwise the preview."""
        use_live = live if live is not None else self.live.selection is not None
        if use_live and self.live.selection is not None:
            nxt = step(self.bible, self.live.selection, delta)
            if nxt is not None:
                self.live.selection = nxt
                self.live.cover = None
                self._render_live()
        elif self.preview is not None:
            nxt = step(self.bible, self.preview, delta)
            if nxt is not None:
                self.set_preview(nxt)

    def _render_preview(self) -> None:
        tr = self.translation()
        slide = self.builder.slide(self.preview, tr, self.settings["fit_range"], self._fits)
        self._preview_slide = slide
        self.preview_label.configure(text=self.preview.status_label() if self.preview else "—")
        self._draw_thumb(self.preview_canvas, slide)

    def _render_live(self) -> None:
        tr = self.translation()
        slide = self.live.slide(self.builder, tr, self.settings["fit_range"], self._fits)
        self._live_slide = slide
        self.output.set_slide(slide, tr)
        if self.live.selection is not None:
            # "move to verse 8" now means verse 8 of what is on screen
            self.detector.set_position(self.live.selection.book, self.live.selection.chapter)
            f = self.follower
            sel = self.live.selection
            if (f.book, f.chapter, f.verse) != (sel.book, sel.chapter, sel.cur) or (
                    f.range_end != (sel.end if sel.is_range else None)):
                self._restart_follower()  # the operator, a command or a detection moved the slide
        self._update_follow_ui()
        if self.live.cover == BLACK:
            text = "BLACK"
        elif self.live.cover == BLANK:
            text = "BLANK"
        else:
            text = self.live.selection.status_label() if self.live.selection else "—"
        self.live_label.configure(text=text)
        self._draw_thumb(self.live_canvas, slide)

    def _render_all(self) -> None:
        self._render_preview()
        self._render_live()

    def _render_thumbs(self) -> None:
        if hasattr(self, "_preview_slide"):
            self._draw_thumb(self.preview_canvas, self._preview_slide)
        if hasattr(self, "_live_slide"):
            self._draw_thumb(self.live_canvas, self._live_slide)

    def _draw_thumb(self, canvas: tk.Canvas, slide: Slide) -> None:
        try:
            w = int(canvas.winfo_width()) - 4
            h = int(canvas.cget("height"))
            if w < 10:
                w = 200
            self.renderer.draw(canvas, slide if slide.kind != EMPTY else Slide(EMPTY), self.settings.appearance,
                               w, h, design_size=self.output.size, translation=self.translation())
            canvas.configure(scrollregion=(0, 0, w, h))
        except tk.TclError:
            log.exception("thumbnail draw failed")

    # --------------------------------------------------------------- search
    def focus_search(self) -> None:
        self.search_entry.focus_set()
        self.search_entry.select_range(0, "end")

    def search(self) -> None:
        text = self.search_var.get().strip()
        self.results.delete(*self.results.get_children())
        self._results = {}
        if not text:
            return
        tr = self.translation()
        ref = parse_typed(text, verse_count=self.bible.verse_count)
        if ref is not None:
            sel = Selection.from_reference(ref)
            self._add_result(sel, self.bible.verse(tr, sel.book, sel.chapter, sel.cur) or "")
            self.set_preview(sel)
            self.search_info.configure(text="Reference %s loaded into Preview" % sel.passage_label())
            return
        t = time.perf_counter()
        found = self.bible.search(tr, text, limit=50)
        for v in found:
            self._add_result(Selection(v.book, v.chapter, v.verse, v.verse), v.text)
        self.search_info.configure(text="%d result%s in %s (%.0f ms)%s" % (
            len(found), "" if len(found) == 1 else "s", tr, (time.perf_counter() - t) * 1000,
            " — showing the first 50" if len(found) >= 50 else ""))
        kids = self.results.get_children()
        if kids:
            self.results.selection_set(kids[0])

    def _add_result(self, sel: Selection, text: str) -> None:
        iid = self.results.insert("", "end", values=(sel.passage_label(), text))
        self._results[iid] = sel

    def _on_result_click(self) -> None:
        sel = self.results.selection()
        if sel and sel[0] in self._results:
            self.set_preview(self._results[sel[0]].copy())

    # --------------------------------------------------------------- misc ui
    def _on_translation(self) -> None:
        self.settings["translation"] = self.translation()
        self._update_translation_name()
        self._render_all()

    def _update_translation_name(self) -> None:
        names = {c: n for c, n, _ in self.bible.translations()}
        self.translation_name.configure(text=names.get(self.translation(), ""))

    def _on_mode(self) -> None:
        self.settings["mode"] = self.mode_var.get()
        self._update_mode_hint()

    def toggle_mode(self) -> None:
        self.mode_var.set("auto" if self.mode_var.get() == "manual" else "manual")
        self._on_mode()

    def _update_mode_hint(self) -> None:
        if self.mode_var.get() == "auto":
            self.mode_hint.configure(text="Auto: detected verses go straight to Live", style="Live.TLabel")
        else:
            self.mode_hint.configure(text="Manual: detected verses go to Preview; press Go Live (%s+Enter / F5)"
                                     % MOD_LABEL, style="Muted.TLabel")

    def toggle_output(self) -> None:
        self.output.toggle()

    def _on_output_visible(self, visible: bool) -> None:
        self.settings["output_visible"] = visible
        self.output_btn.configure(text="Hide output" if visible else "Show output")

    def test_output(self) -> None:
        if not self.output.visible:
            self.output.show()
        self.set_preview(SAMPLE.copy())
        self.go_live()

    def _draw_meter(self) -> None:
        level = self.capture.level() if self.capture.running else 0.0
        c = self.meter
        w = int(c.cget("width"))
        h = int(c.cget("height"))
        c.delete("bar")
        fill = int(w * level / 100.0)
        if fill > 0:
            color = self.pal["ok"] if level < 75 else (self.pal["warn"] if level < 92 else self.pal["error"])
            c.create_rectangle(0, 0, fill, h, fill=color, width=0, tags="bar")

    def open_emphasis(self) -> None:
        """Bold / underline / highlight words of the live verse (or the preview)."""
        from .ui_emphasis import EmphasisDialog
        sel = self.live.selection or self.preview
        if sel is None:
            self._status("Nothing to emphasise yet: show a verse first", error=True)
            return
        EmphasisDialog(self, sel.book, sel.chapter, sel.cur, self.translation())

    def open_settings(self) -> None:
        from .ui_settings import SettingsDialog
        SettingsDialog(self)

    def apply_settings(self) -> None:
        """Called by the settings dialog after a change."""
        s = self.settings
        self.detector.strict = s["strict_books"]
        self.detector.relative = s["relative_verses"]
        self.detector.dedupe_window = float(s["dedupe_window"])
        self.engine.use_reference = s["reference_recognizer"]
        self.engine.commands = s["voice_commands"]
        self.output.set_appearance(s.appearance)
        self._render_all()
        s.save()

    def reload_model(self) -> None:
        if self.listening:
            self.stop_listening()
        self.engine.engine = None
        self.engine.load(self.settings["speech_model"], self.settings["model_path"])

    def show_shortcuts(self) -> None:
        messagebox.showinfo("Keyboard shortcuts", "\n".join([
            "%s+Enter or F5\tGo Live" % MOD_LABEL,
            "Esc\t\tBlank (again to restore)",
            "Shift+Esc\tBlack (again to restore)",
            "← / →\t\tPrev / Next on the live slide",
            "%s+F\t\tFocus search" % MOD_LABEL,
            "%s+L\t\tListen on/off" % MOD_LABEL,
            "%s+M\t\tManual / Auto" % MOD_LABEL,
            "F11 (on output)\tFull screen / windowed",
        ]), parent=self.root)

    def show_about(self) -> None:
        names = ", ".join(c for c, _, _ in self.bible.translations())
        messagebox.showinfo("About %s" % APP_NAME, "%s %s\n\nFree, offline Bible verse projection from live "
                            "speech.\n\nTranslations: %s\nSpeech model: %s\n\nMIT licence. See "
                            "THIRD_PARTY_NOTICES.md for components and licences." % (
                                APP_NAME, __version__, names, self.engine.model_label or "none"),
                            parent=self.root)

    def open_log_folder(self) -> None:
        folder = paths.log_dir()
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            messagebox.showinfo("Log folder", folder, parent=self.root)

    # --------------------------------------------------------------- close
    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        log.info("closing")
        try:
            if self.root.state() == "normal":
                self.settings["window_geometry"] = self.root.geometry()
        except tk.TclError:
            pass
        self.settings["mode"] = self.mode_var.get()
        self.settings["translation"] = self.translation()
        try:
            self.capture.stop()
            self.engine.stop()
        except Exception:
            log.exception("stopping audio")
        self.settings.save()
        self.output.destroy()
        self.root.destroy()
