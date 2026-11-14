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
from .controller import IdleTimer, LiveState, Selection, SlideBuilder, chapter_step, step
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
# operator window full screen: the platform's usual shortcut
FULLSCREEN_KEYS = ("<Control-Command-f>", "<F11>") if IS_MAC else ("<F11>",)
FULLSCREEN_LABEL = "Ctrl+Cmd+F" if IS_MAC else "F11"
POLL_MS = 50
TRANSCRIPT_PASTE_SHOWN = 300  # pasted lines shown in the panel (all of them go to the summary)
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
        self.idle = IdleTimer(settings["idle_action"], settings["idle_delay"])
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
        self.sermon = None  # SermonLog of the current service
        self._partials_seen = False
        self._passage_start = None  # (book, chapter, verse) of the passage last sent live
        self.following = True       # follow-the-reading on/off ("stop there" / "continue")
        self.settings_dialog = None  # the open SettingsDialog, if any
        self._reload_after_listening = False
        from .downloads import DownloadManager
        self.downloads = DownloadManager(on_finish=lambda job: self.events.put(("download", job)))
        from .ui_update import UpdateController
        self.updater = UpdateController(self)

        self._online_note = ""  # last "offline, showing KJV" status, so it is said once
        self.setup_online(refresh=True)
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
        codes = bible.local_codes()  # following never waits on the network
        from .quotes import QuoteMatcher
        self.quotes = QuoteMatcher(bible, codes)
        self._quotes = {}  # type: Dict[str, object]  # Possible references row -> Match
        self._preview_note = ""
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
        if settings["operator_fullscreen"]:
            root.after(200, lambda: self.set_fullscreen(True, remember=False))

        self.refresh_devices(initial=True)
        self.refresh_displays(initial=True)
        if settings["output_visible"]:
            self.output.show()
        self._render_all()
        self.engine.load(settings["speech_model"], settings["model_path"])
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(POLL_MS, self._poll)
        self.updater.start()

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
        viewm = tk.Menu(menubar, tearoff=False)
        self.fullscreen_var = tk.BooleanVar(value=False)
        viewm.add_checkbutton(label="Full screen", variable=self.fullscreen_var, accelerator=FULLSCREEN_LABEL,
                              command=lambda: self.set_fullscreen(self.fullscreen_var.get()))
        menubar.add_cascade(label="View", menu=viewm)
        servm = tk.Menu(menubar, tearoff=False)
        servm.add_command(label="Sermon summary\u2026", command=self.open_summary,
                          accelerator="%s+Shift+S" % MOD_LABEL)
        servm.add_command(label="Start a new sermon", command=self.new_sermon)
        servm.add_command(label="Open a previous sermon\u2026", command=self.open_previous_sermon)
        servm.add_separator()
        servm.add_command(label="Paste transcript", command=self.paste_transcript)
        servm.add_command(label="Import transcript\u2026", command=self.import_transcript)
        servm.add_command(label="Clear transcript", command=self.clear_transcript)
        menubar.add_cascade(label="Service", menu=servm)
        helpm = tk.Menu(menubar, tearoff=False)
        helpm.add_command(label="Keyboard shortcuts", command=self.show_shortcuts)
        helpm.add_command(label="Open log folder", command=self.open_log_folder)
        helpm.add_command(label="Check for updates\u2026", command=self.updater.check)
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
        tbar = ttk.Frame(tframe)
        tbar.pack(side="bottom", fill="x", pady=(4, 0))
        ttk.Button(tbar, text="Paste", command=self.paste_transcript, style="Small.TButton").pack(side="left")
        ttk.Button(tbar, text="Import\u2026", command=self.import_transcript, style="Small.TButton").pack(
            side="left", padx=4)
        ttk.Button(tbar, text="Clear", command=self.clear_transcript, style="Small.TButton").pack(side="right")
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

        # verses recognised from the preacher's words (no reference spoken). Clicked, never keyed:
        # the number keys belong to typing a search anywhere.
        qframe = ttk.LabelFrame(left, text="POSSIBLE REFERENCES  \u00b7  click = preview, double-click = go live",
                                padding=6)
        self.possible = ttk.Treeview(qframe, columns=("ref", "match", "heard"), show="headings",
                                     selectmode="browse", height=5)
        for col, title, width, stretch in (("ref", "Reference", 130, False), ("match", "Match", 80, False),
                                           ("heard", "Words heard", 200, True)):
            self.possible.heading(col, text=title, anchor="w")
            self.possible.column(col, width=width, stretch=stretch, anchor="w")
        self.possible.pack(fill="both", expand=True)
        self.possible.bind("<<TreeviewSelect>>", lambda e: self._on_possible_click())
        self.possible.bind("<Double-1>", lambda e: self._on_possible_double())
        left.add(qframe, weight=1)

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
        self.follow_btn = ttk.Button(buttons, text=u"\u23f8 Pause", command=self.toggle_following,
                                     style="Small.TButton")
        self.follow_btn.grid(row=2, column=0, sticky="ew", pady=(4, 0), padx=(0, 2))
        ttk.Button(buttons, text=u"\u270e Mark", command=self.open_emphasis, style="Small.TButton").grid(
            row=2, column=1, sticky="ew", pady=(4, 0), padx=(2, 2))
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
        r.bind_all("<%s-Shift-S>" % MOD, lambda e: self._key(self.open_summary))
        r.bind_all("<%s-Shift-s>" % MOD, lambda e: self._key(self.open_summary))
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
        for seq in FULLSCREEN_KEYS:
            r.bind(seq, lambda e: self._key(self.toggle_fullscreen))
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
    def is_fullscreen(self) -> bool:
        try:
            return bool(int(self.root.attributes("-fullscreen")))
        except (tk.TclError, ValueError):
            return False

    def set_fullscreen(self, on: bool, remember: bool = True) -> None:
        """Operator window full screen (View menu, F11 / Ctrl+Cmd+F). Remembered for next time."""
        try:
            self.root.attributes("-fullscreen", bool(on))
        except tk.TclError:
            log.warning("full screen is not available here")
            on = False
        self.fullscreen_var.set(bool(on))
        if remember:
            self.settings["operator_fullscreen"] = bool(on)

    def toggle_fullscreen(self) -> None:
        # our own state: on macOS Tk reports the change only after the animation
        self.set_fullscreen(not self.fullscreen_var.get())

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
        if self.sermon is None or time.time() - self.sermon.ended > 30 * 60:
            self.new_sermon(quiet=True)  # a new service: start a fresh sermon record
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
        self._save_sermon()
        self.listening = False
        self.capture.stop()
        self.engine.stop()
        self.audio_retry_at = 0.0
        self._clear_partial()
        self._update_listen_ui()
        if self._reload_after_listening:
            self._reload_after_listening = False
            self.reload_model()

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
            if self._tick % 20 == 10 and not self.listening:
                self._download_status()
            if self._tick % 20 == 15:
                self.updater.poll()
            if self._tick % 10 == 3:  # about twice a second
                self._idle_tick()
            if self._tick % 20 == 5 and self._online_note:  # about once a second
                self._online_back()
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
            self._match_quotes(ev[1])
            if not self._partials_seen:  # Parakeet alone: only phrase-level text to follow
                self._follow(ev[1], final=True)
        elif kind == "detect":
            self._on_detection(ev[1], ev[2])
        elif kind == "model":
            self._on_model(ev[1], ev[2])
        elif kind == "download":
            self._on_download(ev[1])
        elif kind == "pack":
            self._on_pack(ev[1], ev[2])
        elif kind == "command":
            self._on_command(ev[1], ev[2], ev[3], ev[4])
        elif kind == "audio":
            self._on_audio(ev[1], ev[2])
        elif kind == "error":
            self._status(ev[1], error=True)
        elif kind == "bibles":
            self._on_online_versions(ev[1])
        elif kind == "update":
            self.updater.on_event(ev[1], ev[2])

    def _on_model(self, state: str, detail: str) -> None:
        if state == "missing":
            self._set_banner(
                "No speech model could be used (%s), so listening is off. Manual search and projection still "
                "work.\nTo fix: re-extract the %s download, or download a model in Settings \u2192 Models "
                "(see the User Guide)." % (detail, APP_NAME))
        elif state == "error":
            self._set_banner("The speech model could not be loaded: %s\nChoose another model in "
                             "Settings \u2192 Speech, or download one in Settings \u2192 Models." % detail)
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

    # -- model downloads (Settings -> Models) -------------------------------------
    def _download_status(self) -> None:
        jobs = self.downloads.running()
        if jobs:
            j = jobs[0]
            self._status("%s: %s" % (j.item.label, j.describe()))
        elif self.updater.status_text():
            self._status(self.updater.status_text())

    def _on_download(self, job) -> None:
        if self.settings_dialog is not None:
            self.settings_dialog.refresh_models()
        label = job.item.label
        if job.state == "cancelled":
            self._status("%s download cancelled" % label)
            return
        if job.state == "failed":
            self._status("%s was not installed" % label, error=True)
            if self.settings_dialog is None:
                messagebox.showerror(APP_NAME, "%s could not be downloaded: %s" % (label, job.error),
                                     parent=self.root)
            return
        self._status("%s is installed" % label)
        if job.item.kind == "ai":
            if self.settings_dialog is None:
                messagebox.showinfo(APP_NAME, "The AI sermon summary is ready. Open Service \u2192 Sermon "
                                    "summary and press Write AI summary.", parent=self.root)
            return
        if self.settings["speech_model"] in ("auto", job.item.id):
            self.use_model(None)
        elif self.settings_dialog is None and messagebox.askyesno(
                APP_NAME, "%s is installed. Use it now?" % label, parent=self.root):
            self.use_model(job.item.id)

    def use_model(self, model_id) -> None:
        """Switch to a speech model (None: reload the current choice) now, or after listening stops."""
        if model_id is not None:
            self.settings["speech_model"] = model_id
            self.settings.save()
        if self.listening:
            self._reload_after_listening = True
            self._status("The new speech model will be used when you stop listening")
        else:
            self.reload_model()

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
        if self.sermon is not None:
            self.sermon.add_line(text)
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
        if self.sermon is not None:
            self.sermon.add_ref(sel.passage_label())
        from .parser import AUTO_MIN_CONFIDENCE
        auto_ok = (self.mode_var.get() == "auto" and ref.confidence >= AUTO_MIN_CONFIDENCE
                   and (ref.explicit_verse or not self.settings["auto_requires_verse"]))
        if auto_ok:
            self.set_preview(sel.copy())
            self.go_live()
        else:
            self.set_preview(sel.copy())

    # -- verses recognised from their words ---------------------------------------------------
    def _match_quotes(self, text: str) -> None:
        if not self.settings["quote_matching"]:
            return
        try:
            found = self.quotes.feed(text)
        except Exception:
            log.exception("quote matching")
            return
        if found:
            self._on_quotes(found)

    def _on_quotes(self, found) -> None:
        from .quotes import AUTO_LIVE_ALLOWED
        self.possible.delete(*self.possible.get_children())
        self._quotes.clear()
        for k, m in enumerate(found):
            iid = "q%d" % k
            self._quotes[iid] = m
            self.possible.insert("", "end", iid=iid, values=(m.label(), _strength_bar(m.strength), m.heard))
        top = found[0]
        log.info("possible reference %s (%.2f%s): %r", top.label(), top.strength,
                 ", confirmed" if top.confirmed else ", strong" if top.strong else "", top.heard)
        sel = Selection(top.book, top.chapter, top.verse, top.verse)
        self.set_preview(sel, note=_heard_note(top.heard))
        if (top.confirmed and AUTO_LIVE_ALLOWED and self.settings["quote_auto_live"]
                and self.mode_var.get() == "auto"):
            self.go_live()

    def _reset_quotes(self) -> None:
        self.quotes.reset()
        self._quotes.clear()
        self.possible.delete(*self.possible.get_children())

    def _on_possible_click(self) -> None:
        sel = self.possible.selection()
        m = self._quotes.get(sel[0]) if sel else None
        if m is not None:
            self.set_preview(Selection(m.book, m.chapter, m.verse, m.verse), note=_heard_note(m.heard))

    def _on_possible_double(self) -> None:
        self._on_possible_click()
        self.go_live()

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

    def set_preview(self, sel: Optional[Selection], note: str = "") -> None:
        self.preview = sel
        self._preview_note = note  # e.g. "Possible reference - heard ..."
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
        before = f.progress
        move = f.feed(text, time.monotonic(), final=final)
        if move is not None or f.progress > before:
            self._reading_heard()
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
        self.follow_btn.configure(text=u"\u23f8 Pause" if self.following else u"\u25b6 Resume")

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
        self._prefetch_next(self.preview, tr)
        self._preview_slide = slide
        label = self.preview.status_label() if self.preview else "—"
        if self._preview_note and self.preview is not None:
            label = "%s  \u00b7  %s" % (label, self._preview_note)
        self.preview_label.configure(text=label)
        self._draw_thumb(self.preview_canvas, slide)

    # -- idle screen ------------------------------------------------------------------------
    def _showing_verse(self) -> bool:
        return self.live.selection is not None and self.live.cover is None

    def _idle_tick(self) -> None:
        if self.idle.tick(time.monotonic(), self._showing_verse()):
            self._apply_idle()

    def _apply_idle(self) -> None:
        kind = self.idle.kind()
        if kind != self.live.idle:
            log.info("idle screen %s", "on (%s)" % kind if kind else "off")
            self.live.idle = kind
            self._render_live(touch=False)

    def _reading_heard(self) -> None:
        """The follower heard more of the live verse: keep it up, or bring it back."""
        if self.idle.touch(time.monotonic()):
            self._apply_idle()

    def _render_live(self, touch: bool = True) -> None:
        if touch:  # any live change resets the idle timer and shows the verse again
            self.idle.touch(time.monotonic())
            self.live.idle = ""
        tr = self.translation()
        slide = self.live.slide(self.builder, tr, self.settings["fit_range"], self._fits)
        self._live_slide = slide
        shown = slide.translation or tr
        self.output.set_slide(slide, shown)
        self._prefetch_next(self.live.selection, tr)
        self._note_fallback(tr, shown)
        sel_live = self.live.selection
        # the verses on screen are followed, not "quoted": never suggest them as possible references
        self.quotes.exclude = set() if sel_live is None else {
            (sel_live.book, sel_live.chapter, v) for v in range(sel_live.start, sel_live.end + 1)}
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
        elif self.live.idle and self.live.selection is not None:
            text = u"IDLE \u2014 %s returns when the reading resumes" % self.live.selection.verse_label()
        else:
            text = self.live.selection.status_label() if self.live.selection else "—"
        self.live_label.configure(text=text)
        self._draw_thumb(self.live_canvas, slide)

    def _render_all(self) -> None:
        """Redraw both (translation, appearance or online text changed): not a live change."""
        self._render_preview()
        self._render_live(touch=False)

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
                               w, h, design_size=self.output.size,
                               translation=slide.translation or self.translation())
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
            shown = self.bible.resolve(tr, sel.book, sel.chapter)  # the fallback while offline
            self._add_result(sel, self.bible.verse(shown, sel.book, sel.chapter, sel.cur) or "")
            self.set_preview(sel)
            self.search_info.configure(text="Reference %s loaded into Preview" % sel.passage_label())
            return
        t = time.perf_counter()
        online_only = self.bible.is_online(tr)
        tr = self.bible.search_code(tr)  # online versions cannot be searched; use the fallback
        found = self.bible.search(tr, text, limit=50)
        for v in found:
            self._add_result(Selection(v.book, v.chapter, v.verse, v.verse), v.text)
        self.search_info.configure(text="%d result%s in %s (%.0f ms)%s" % (
            len(found), "" if len(found) == 1 else "s", tr, (time.perf_counter() - t) * 1000,
            " — showing the first 50" if len(found) >= 50 else "")
            + (" (online versions cannot be searched)" if online_only else ""))
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
        code = self.translation()
        name = names.get(code, "")
        if self.bible.is_online(code):
            from . import online_bible
            state = self.bible.online.state
            name += " (online)" if state != online_bible.OFFLINE else \
                " (offline: showing %s)" % self.bible.fallback_translation()
        self.translation_name.configure(text=name)

    # ------------------------------------------------------------ online Bibles
    def setup_online(self, refresh: bool = True) -> None:
        """(Re)create the YouVersion client from the settings. Without a key there
        are no online versions."""
        from . import online_bible
        s = self.settings
        self.bible.fallback = s["offline_fallback"]
        key = s["youversion_key"].strip() if s["online_bibles"] else ""
        cur = self.bible.online
        if cur is not None and cur.key == key and cur.languages == online_bible.OnlineBibles(
                "", "", s["online_languages"]).languages:
            return
        if not key:
            self.bible.set_online(None)
        else:
            self.bible.set_online(online_bible.OnlineBibles(
                key, os.path.join(paths.config_dir(), "online_bibles"), s["online_languages"],
                verse_count=self.bible.verse_count))
            if refresh:
                self.refresh_online()
        if hasattr(self, "translation_combo"):
            self._on_online_versions(True)

    def refresh_online(self) -> None:
        """Fetch the version list in the background; the result arrives as a "bibles" event."""
        online = self.bible.online
        if online is None:
            return

        def run():
            ok = online.refresh_versions()
            if online is self.bible.online:
                self.events.put(("bibles", ok))
        threading.Thread(target=run, name="online-versions", daemon=True).start()

    def _on_online_versions(self, ok: bool) -> None:
        codes = [c for c, _, _ in self.bible.translations()]
        self.engine.translations = [(c, n) for c, n, _l in self.bible.translations()]
        if hasattr(self, "translation_combo"):
            self.translation_combo.configure(values=codes)
            if self.translation() not in codes:
                self.translation_var.set(self.bible.default_translation())
                self.settings["translation"] = self.translation()
            self._update_translation_name()
            self._render_all()
        if self.settings_dialog is not None:
            try:
                self.settings_dialog.refresh_bibles()
            except Exception:
                log.exception("settings refresh failed")

    def _online_back(self) -> None:
        """While the fallback is showing, retry the online version in the background and
        switch back as soon as its chapter arrives."""
        online, tr, sel = self.bible.online, self.translation(), self.live.selection or self.preview
        if online is None or not self.bible.is_online(tr):
            self._note_fallback(tr, tr)
            return
        if sel is not None and online.cached(tr, sel.book, sel.chapter) is not None:
            self._render_all()
        elif sel is not None:
            # Retry even when another request has already brought the client back
            # online; prefetch itself waits out the pause after a failure.
            self.bible.prefetch(tr, sel.book, sel.chapter)

    def _prefetch_next(self, sel: Optional[Selection], tr: str) -> None:
        if sel is not None and self.bible.is_online(tr):
            self.bible.prefetch(tr, sel.book, sel.chapter + 1)

    def _note_fallback(self, wanted: str, shown: str) -> None:
        note = "" if wanted == shown or not self.bible.is_online(wanted) else \
            "%s is not reachable right now, so the %s is showing. It switches back when the internet is back." % (
                wanted, shown)
        if note != self._online_note:
            self._online_note = note
            if note:
                self._status(note, error=True)
            self._update_translation_name()

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

    # -- sermon record and summary ----------------------------------------------------
    def new_sermon(self, quiet: bool = False) -> None:
        from .summary import SermonLog
        self._save_sermon()
        self.sermon = SermonLog()
        if hasattr(self, "possible"):
            self._reset_quotes()
        if not quiet:
            self._status("Started a new sermon record")

    def _save_sermon(self) -> None:
        if self.sermon is not None and not self.sermon.empty():
            try:
                self.sermon.save()
            except OSError:
                log.exception("could not save the sermon record")

    def open_summary(self, sermon=None) -> None:
        from .summary import SermonLog
        from .ui_summary import SummaryWindow
        if sermon is None and self.sermon is None:
            self.sermon = SermonLog()  # so a transcript pasted later reaches this window
        self.summary_window = SummaryWindow(self, sermon or self.sermon)

    def _summary_changed(self) -> None:
        """Rebuild an open summary window that shows the current sermon."""
        w = getattr(self, "summary_window", None)
        if w is not None and w.log is self.sermon:
            w.reload()

    # -- transcript: clear, paste, import ------------------------------------------------
    def clear_transcript(self, confirm: bool = True) -> None:
        """Empty the transcript panel and the sermon record the summary is built from."""
        has_text = bool(self.transcript.get("1.0", "end").strip()) or (
            self.sermon is not None and not self.sermon.empty())
        if not has_text:
            self._status("The transcript is already empty")
            return
        if confirm and not messagebox.askyesno(
                APP_NAME, "Clear the transcript?\n\nThis also removes it from the sermon summary.",
                parent=self.root):
            return
        self._clear_partial()
        self._reset_quotes()
        self._insert_transcript(lambda t: t.delete("1.0", "end"))
        self._transcript_lines = []
        if self.sermon is not None:
            self._delete_sermon_file(self.sermon)
            self.sermon.clear()
        self._summary_changed()
        self._status("Transcript cleared")

    def _delete_sermon_file(self, sermon) -> None:
        path = os.path.join(paths.config_dir(), "sermons",
                            time.strftime("%Y-%m-%d_%H%M", time.localtime(sermon.started)) + ".json")
        try:
            os.remove(path)
        except OSError:
            pass

    def paste_transcript(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            text = ""
        self.add_transcript_text(text, "the clipboard")

    def import_transcript(self) -> None:
        from tkinter import filedialog

        from .summary import TRANSCRIPT_FILETYPES
        path = filedialog.askopenfilename(parent=self.root, title="Import a transcript",
                                          filetypes=TRANSCRIPT_FILETYPES)
        if not path:
            return
        try:
            if os.path.getsize(path) > 8 * 1024 * 1024:
                raise ValueError("The file is too large for a transcript.")
            with open(path, encoding="utf-8-sig") as f:
                text = f.read()
        except UnicodeDecodeError:
            messagebox.showerror(APP_NAME, "That file is not plain text (UTF-8).", parent=self.root)
            return
        except (OSError, ValueError) as exc:
            messagebox.showerror(APP_NAME, "That file could not be read:\n%s" % exc, parent=self.root)
            return
        self.add_transcript_text(text, os.path.basename(path))

    def add_transcript_text(self, text: str, source: str, ask: bool = True) -> bool:
        """Add a pasted or imported transcript to the current sermon. Only accepted
        formats get in; anything else is refused with a message."""
        from .summary import TRANSCRIPT_FORMATS, SermonLog, TranscriptError, parse_transcript, references_in
        try:
            lines = parse_transcript(text)
        except TranscriptError as exc:
            messagebox.showerror(APP_NAME, "The text from %s was not added.\n\n%s\n\nAccepted: %s." % (
                source, exc, TRANSCRIPT_FORMATS), parent=self.root)
            return False
        if self.sermon is None:
            self.sermon = SermonLog()
        if ask and not self.sermon.empty():
            answer = messagebox.askyesnocancel(
                APP_NAME, "Add the %d lines to the current transcript?\n\nYes adds them at the end. No replaces "
                "the current transcript." % len(lines), parent=self.root)
            if answer is None:
                return False
            if answer is False:
                self.clear_transcript(confirm=False)
        refs = references_in(lines, self.bible.verse_count)
        self.sermon.add_lines(lines, refs)
        shown = lines[-TRANSCRIPT_PASTE_SHOWN:]

        def f(t):
            for secs, line in shown:
                t.insert("end", time.strftime("%H:%M:%S ", time.localtime(self.sermon.started + secs)), "time")
                t.insert("end", line + "\n")
        self._clear_partial()
        self._insert_transcript(f)
        now = time.monotonic()
        self._transcript_lines.extend([now] * len(shown))
        self._save_sermon()
        self._summary_changed()
        self._status("Added %d transcript line%s and %d scripture reference%s from %s" % (
            len(lines), "" if len(lines) == 1 else "s", len(refs), "" if len(refs) == 1 else "s", source))
        return True

    def open_previous_sermon(self) -> None:
        import json as _json
        from tkinter import filedialog

        from .summary import SermonLog
        path = filedialog.askopenfilename(parent=self.root, title="Open a sermon record",
                                          initialdir=os.path.join(paths.config_dir(), "sermons"),
                                          filetypes=[("Sermon records", "*.json")])
        if path:
            try:
                with open(path, encoding="utf-8") as f:
                    self.open_summary(SermonLog.from_dict(_json.load(f)))
            except (OSError, ValueError) as exc:
                messagebox.showerror(APP_NAME, "That file could not be opened:\n%s" % exc, parent=self.root)

    def open_emphasis(self) -> None:
        """Bold / underline / highlight words of the live verse (or the preview)."""
        from .ui_emphasis import EmphasisDialog
        sel = self.live.selection or self.preview
        if sel is None:
            self._status("Nothing to emphasise yet: show a verse first", error=True)
            return
        EmphasisDialog(self, sel.book, sel.chapter, sel.cur, self.bible.resolve(self.translation(), sel.book,
                                                                                 sel.chapter))

    def open_settings(self, tab: str = "") -> None:
        from .ui_settings import SettingsDialog
        if self.settings_dialog is not None:
            try:
                self.settings_dialog.win.lift()
                return
            except tk.TclError:
                self.settings_dialog = None
        self.settings_dialog = SettingsDialog(self, tab=tab)

    def apply_settings(self) -> None:
        """Called by the settings dialog after a change."""
        s = self.settings
        self.detector.strict = s["strict_books"]
        self.detector.relative = s["relative_verses"]
        self.detector.dedupe_window = float(s["dedupe_window"])
        self.engine.use_reference = s["reference_recognizer"]
        self.engine.commands = s["voice_commands"]
        self.output.set_appearance(s.appearance)
        self.idle.configure(s["idle_action"], s["idle_delay"], time.monotonic())
        self.live.idle = self.idle.kind()  # a settings change shows the verse again and restarts the timer
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
            "%s\t\tOperator window full screen" % FULLSCREEN_LABEL,
            "F11 (on output)\tOutput full screen / windowed",
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
        self.downloads.cancel_all()
        try:
            if self.is_fullscreen():
                self.root.attributes("-fullscreen", False)
        except tk.TclError:
            pass
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
        self._save_sermon()
        self.updater.on_close()
        self.output.destroy()
        self.root.destroy()


def _strength_bar(strength: float) -> str:
    """Match strength for the Possible references list: "\u25a0\u25a0\u25a0\u25a0\u25a1 84%"."""
    filled = max(0, min(5, int(round(strength * 5))))
    return u"%s%s %d%%" % (u"\u25a0" * filled, u"\u25a1" * (5 - filled), int(round(strength * 100)))


def _heard_note(heard: str, limit: int = 60) -> str:
    if len(heard) > limit:
        heard = heard[:limit].rsplit(" ", 1)[0] + u" \u2026"
    return u"Possible reference \u2014 heard \u201c%s\u201d" % heard
