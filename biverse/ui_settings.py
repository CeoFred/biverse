"""Settings dialog: appearance, speech model, online Bibles and detection options."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog, messagebox, ttk

from . import APP_NAME, __version__, downloads, recognizer


class SettingsDialog(object):
    def __init__(self, op, tab: str = "") -> None:
        self.op = op
        self.model_rows = {}  # type: dict
        s = op.settings
        a = s.appearance
        self.win = tk.Toplevel(op.root)
        self.win.title("Settings")
        self.win.configure(background=op.pal["bg"])
        self.win.transient(op.root)
        self.win.resizable(False, False)

        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=8, pady=8)
        self.nb = nb

        # -- appearance
        ap = ttk.Frame(nb, padding=10)
        nb.add(ap, text="Appearance")
        self.bg = tk.StringVar(value=a.background)
        self.fg = tk.StringVar(value=a.foreground)
        self.hl = tk.StringVar(value=a.highlight_color)
        self.family = tk.StringVar(value=a.font_family or op.renderer.family(a))
        self.bold = tk.BooleanVar(value=a.bold)
        self.shadow = tk.BooleanVar(value=a.shadow)
        self.refpos = tk.StringVar(value=a.reference_position)
        self.image = tk.StringVar(value=a.background_image)
        self.fit_range = tk.BooleanVar(value=s["fit_range"])
        self.op_fullscreen = tk.BooleanVar(value=s["operator_fullscreen"])
        self.ui_theme = tk.StringVar(value={"system": "Follow the computer", "dark": "Dark",
                                            "light": "Light"}[s["ui_theme"]])

        row = 0
        ttk.Label(ap, text="Background colour").grid(row=row, column=0, sticky="w", pady=2)
        self.bg_swatch = tk.Label(ap, width=4, background=self.bg.get(), relief="solid", borderwidth=1)
        self.bg_swatch.grid(row=row, column=1, sticky="w")
        ttk.Button(ap, text="Choose…", command=lambda: self._color(self.bg, self.bg_swatch)).grid(
            row=row, column=2, sticky="w")
        row += 1
        ttk.Label(ap, text="Text colour").grid(row=row, column=0, sticky="w", pady=2)
        self.fg_swatch = tk.Label(ap, width=4, background=self.fg.get(), relief="solid", borderwidth=1)
        self.fg_swatch.grid(row=row, column=1, sticky="w")
        ttk.Button(ap, text="Choose…", command=lambda: self._color(self.fg, self.fg_swatch)).grid(
            row=row, column=2, sticky="w")
        row += 1
        ttk.Label(ap, text="Highlight colour").grid(row=row, column=0, sticky="w", pady=2)
        self.hl_swatch = tk.Label(ap, width=4, background=self.hl.get(), relief="solid", borderwidth=1)
        self.hl_swatch.grid(row=row, column=1, sticky="w")
        ttk.Button(ap, text="Choose\u2026", command=lambda: self._color(self.hl, self.hl_swatch)).grid(
            row=row, column=2, sticky="w")
        row += 1
        ttk.Label(ap, text="Font").grid(row=row, column=0, sticky="w", pady=2)
        families = sorted({f for f in tkfont.families(op.root) if not f.startswith("@")})
        ttk.Combobox(ap, textvariable=self.family, values=families, width=28).grid(
            row=row, column=1, columnspan=2, sticky="w")
        row += 1
        ttk.Checkbutton(ap, text="Bold", variable=self.bold).grid(row=row, column=0, sticky="w")
        ttk.Checkbutton(ap, text="Text shadow", variable=self.shadow).grid(row=row, column=1, columnspan=2,
                                                                           sticky="w")
        row += 1
        ttk.Label(ap, text="Reference line").grid(row=row, column=0, sticky="w", pady=2)
        rp = ttk.Frame(ap)
        rp.grid(row=row, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(rp, text="Bottom", value="bottom", variable=self.refpos).pack(side="left")
        ttk.Radiobutton(rp, text="Top", value="top", variable=self.refpos).pack(side="left", padx=6)
        row += 1
        ttk.Label(ap, text="Background image").grid(row=row, column=0, sticky="w", pady=2)
        ttk.Entry(ap, textvariable=self.image, width=28).grid(row=row, column=1, sticky="w")
        bi = ttk.Frame(ap)
        bi.grid(row=row, column=2, sticky="w")
        ttk.Button(bi, text="…", width=3, command=self._choose_image).pack(side="left")
        ttk.Button(bi, text="Clear", command=lambda: self.image.set("")).pack(side="left")
        row += 1
        ttk.Label(ap, text="PNG or GIF. Use an image the size of the projector for best results.",
                  style="Muted.TLabel").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Checkbutton(ap, text="Fit a whole verse range on one slide when it fits",
                        variable=self.fit_range).grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))
        row += 1
        ttk.Label(ap, text="Operator window look").grid(row=row, column=0, sticky="w", pady=(10, 2))
        ttk.Combobox(ap, textvariable=self.ui_theme, state="readonly", width=20,
                     values=["Follow the computer", "Dark", "Light"]).grid(row=row, column=1, columnspan=2,
                                                                           sticky="w", pady=(10, 2))
        row += 1
        ttk.Checkbutton(ap, text="Open the operator window full screen (%s switches)" % _fullscreen_label(),
                        variable=self.op_fullscreen).grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # -- speech
        sp = ttk.Frame(nb, padding=10)
        nb.add(sp, text="Speech")
        self.speech_model = tk.StringVar(value=s["speech_model"])
        self.model_path = tk.StringVar(value=s["model_path"])
        installed = {m.id for m in recognizer.discover_models()}
        ttk.Label(sp, text="In use: %s" % (op.engine.model_label or "(none)"), font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self.speech_tab = sp
        self.speech_notes = {}  # type: dict
        self.speech_radios = {}  # type: dict
        for row, (value, text) in enumerate(SPEECH_CHOICES, 1):
            rb = ttk.Radiobutton(sp, text=text, value=value, variable=self.speech_model)
            rb.grid(row=row, column=0, sticky="w")
            note = ttk.Label(sp, text="", style="Muted.TLabel")
            note.grid(row=row, column=1, columnspan=2, sticky="w", padx=(8, 0))
            self.speech_notes[value] = note
            self.speech_radios[value] = rb
        self._speech_notes(installed)
        row = len(SPEECH_CHOICES) + 1
        folder = ttk.Frame(sp)
        folder.grid(row=row, column=0, columnspan=3, sticky="w", padx=(22, 0))
        ttk.Entry(folder, textvariable=self.model_path, width=38).pack(side="left")
        ttk.Button(folder, text="Choose\u2026", command=self._choose_model).pack(side="left", padx=4)
        row += 1
        ttk.Label(sp, text="Models that are not installed can be downloaded in the Models tab.",
                  style="Muted.TLabel").grid(row=row, column=0, columnspan=3, sticky="w", pady=(10, 0))

        # -- models (download / install)
        md = ttk.Frame(nb, padding=10)
        nb.add(md, text="Models")
        self.models_tab = md
        ttk.Label(md, text="Biverse downloads and installs the model for you. Downloads keep going if you "
                           "close this window.", style="Muted.TLabel", wraplength=640).grid(
            row=0, column=0, columnspan=3, sticky="w")
        for i, it in enumerate(downloads.items()):
            self.model_rows[it.id] = ModelRow(self, md, it, row=1 + i)
        foot = len(self.model_rows) + 1
        ttk.Separator(md).grid(row=foot, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Button(md, text="Install from a file\u2026", command=self._install_pack).grid(
            row=foot + 1, column=0, sticky="w")
        ttk.Label(md, text="No internet here? Get the model pack zip from the Biverse website on another "
                           "computer and install it from the file.", wraplength=520,
                  style="Muted.TLabel").grid(row=foot + 1, column=1, columnspan=2, sticky="w", padx=(8, 0))
        md.columnconfigure(1, weight=1)

        # -- online Bibles (YouVersion)
        self._build_bibles(nb, s)

        # -- detection
        dt = ttk.Frame(nb, padding=10)
        nb.add(dt, text="Detection")
        self.strict = tk.BooleanVar(value=s["strict_books"])
        self.relative = tk.BooleanVar(value=s["relative_verses"])
        self.dedupe = tk.IntVar(value=int(s["dedupe_window"]))
        self.auto_verse = tk.BooleanVar(value=s["auto_requires_verse"])
        self.ref_rec = tk.BooleanVar(value=s["reference_recognizer"])
        self.voice_cmds = tk.BooleanVar(value=s["voice_commands"])
        self.follow = tk.BooleanVar(value=s["follow_reading"])
        ttk.Checkbutton(dt, text="Strict book names (Mark, John, Job, Acts… need chapter and verse)",
                        variable=self.strict).grid(row=0, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(dt, text="Relative verses (\"verse 17\" uses the last book and chapter)",
                        variable=self.relative).grid(row=1, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(dt, text="Ignore repeats within (seconds)").grid(row=2, column=0, sticky="w", pady=2)
        tk.Spinbox(dt, from_=0, to=600, increment=10, textvariable=self.dedupe, width=6).grid(
            row=2, column=1, sticky="w")
        ttk.Checkbutton(dt, text="Auto mode: only send references with chapter AND verse live",
                        variable=self.auto_verse).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Checkbutton(dt, text="Voice commands: \"next verse\", \"go back\", \"next chapter\"\u2026",
                        variable=self.voice_cmds).grid(row=6, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Label(dt, text="Auto mode moves the live verse; Manual mode puts it in Preview. \"Next\" and "
                           "\"go back\" on their own only count as a short command, not inside a sentence.",
                  style="Muted.TLabel", wraplength=420).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(dt, text="Follow the reading: move to the next verse as the preacher finishes each one",
                        variable=self.follow).grid(row=8, column=0, columnspan=2, sticky="w", pady=(10, 2))
        from .quotes import AUTO_LIVE_ALLOWED
        self.quote_matching = tk.BooleanVar(value=s["quote_matching"])
        self.quote_auto = tk.BooleanVar(value=s["quote_auto_live"] and AUTO_LIVE_ALLOWED)
        ttk.Checkbutton(dt, text="Recognise verses the preacher quotes without saying the reference",
                        variable=self.quote_matching).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 2))
        auto = ttk.Checkbutton(dt, text="Auto mode: send strong matches live automatically", variable=self.quote_auto)
        auto.grid(row=10, column=0, columnspan=2, sticky="w", padx=(20, 0))
        if not AUTO_LIVE_ALLOWED:
            auto.state(["disabled"])
        note = ("Matches appear under Possible references and in Preview; click one to check it, double-click "
                "to send it live.")
        if not AUTO_LIVE_ALLOWED:
            note += " Sending them live automatically becomes available once it has been tested on real sermons."
        ttk.Label(dt, text=note, style="Muted.TLabel", wraplength=420).grid(row=11, column=0, columnspan=2,
                                                                            sticky="w")
        ttk.Checkbutton(dt, text="Extra reference listener (classic engine only; about twice the CPU)",
                        variable=self.ref_rec).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Label(dt, text="Turn off on very slow computers. It only adds references that include both a "
                           "chapter and a verse.", style="Muted.TLabel", wraplength=420).grid(
            row=5, column=0, columnspan=2, sticky="w")

        self._build_updates(nb, s)

        if tab == "models":
            nb.select(md)
        elif tab == "bibles":
            nb.select(self.bibles_tab)

        btns = ttk.Frame(self.win, padding=(8, 0, 8, 8))
        btns.pack(fill="x")
        ttk.Button(btns, text="Test output", command=self._test).pack(side="left")
        ttk.Button(btns, text="Close", command=self._ok).pack(side="right")
        ttk.Button(btns, text="Apply", command=self.apply).pack(side="right", padx=4)
        self.win.protocol("WM_DELETE_WINDOW", self._ok)
        self.win.bind("<Escape>", lambda e: (self._ok(), "break")[1])
        self.win.grab_set()
        self._tick()

    # -- updates ------------------------------------------------------------------------
    def _build_updates(self, nb, s) -> None:
        from . import updates
        up = ttk.Frame(nb, padding=10)
        nb.add(up, text="Updates")
        self.update_check = tk.BooleanVar(value=s["update_check"])
        ttk.Label(up, text="This is %s %s." % (APP_NAME, __version__)).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(up, text="Check for new versions by myself (about twice a day, never while listening)",
                        variable=self.update_check).grid(row=1, column=0, sticky="w", pady=(8, 2))
        note = ("Biverse asks before it downloads anything, and installs only when you restart it. A check "
                "sends nothing about you or your church; it reads one small file from GitHub.")
        problem = updates.install_problem() if updates.flavour() else ""
        if not updates.flavour():
            note += "\n\nThis copy is not a downloaded release, so it is never offered updates."
        elif problem:
            note += "\n\nThis copy cannot replace itself (%s). Updates will be offered as a zip to unpack." % problem
        ttk.Label(up, text=note, style="Muted.TLabel", wraplength=440, justify="left").grid(
            row=2, column=0, sticky="w")
        ttk.Button(up, text="Check now", command=self._check_updates).grid(row=3, column=0, sticky="w", pady=(10, 0))

    def _check_updates(self) -> None:
        self.apply()
        self._ok()
        self.op.updater.check(manual=True)

    # -- online Bibles ----------------------------------------------------------------
    def _build_bibles(self, nb, s) -> None:
        bt = ttk.Frame(nb, padding=10)
        nb.add(bt, text="Bibles")
        self.bibles_tab = bt
        self.online_on = tk.BooleanVar(value=s["online_bibles"])
        self.yv_key = tk.StringVar(value=s["youversion_key"])
        self.yv_langs = tk.StringVar(value=s["online_languages"])
        self.fallback = tk.StringVar(value=self.op.bible.fallback_translation())
        ttk.Label(bt, text="With a YouVersion app key, Biverse adds the Bible versions your key allows (NIV, NASB, "
                           "AMP and others) while this computer is online. Without internet it shows the fallback "
                           "version below instead.", style="Muted.TLabel", wraplength=640).grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Checkbutton(bt, text="Use online Bible versions", variable=self.online_on).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(8, 2))
        ttk.Label(bt, text="YouVersion app key").grid(row=2, column=0, sticky="w", pady=2)
        self.key_entry = ttk.Entry(bt, textvariable=self.yv_key, width=46, show="\u2022")
        self.key_entry.grid(row=2, column=1, sticky="w", pady=2)
        self.show_key = tk.BooleanVar(value=False)
        ttk.Checkbutton(bt, text="Show", variable=self.show_key, command=lambda: self.key_entry.configure(
            show="" if self.show_key.get() else "\u2022")).grid(row=2, column=2, sticky="w", padx=4)
        ttk.Label(bt, text="Get a free key at platform.youversion.com. The key stays on this computer.",
                  style="Muted.TLabel").grid(row=3, column=1, columnspan=2, sticky="w")
        ttk.Label(bt, text="Languages").grid(row=4, column=0, sticky="w", pady=(6, 2))
        ttk.Entry(bt, textvariable=self.yv_langs, width=20).grid(row=4, column=1, sticky="w", pady=(6, 2))
        ttk.Label(bt, text="Language codes, comma separated, for example: en, fr, yo",
                  style="Muted.TLabel").grid(row=5, column=1, columnspan=2, sticky="w")
        ttk.Label(bt, text="When offline, show").grid(row=6, column=0, sticky="w", pady=(6, 2))
        ttk.Combobox(bt, textvariable=self.fallback, values=self.op.bible.local_codes(), state="readonly",
                     width=8).grid(row=6, column=1, sticky="w", pady=(6, 2))
        row = ttk.Frame(bt)
        row.grid(row=7, column=0, columnspan=3, sticky="w", pady=(10, 4))
        ttk.Button(row, text="Connect and refresh list", command=self._connect).pack(side="left")
        ttk.Button(row, text="Clear saved text", command=self._clear_online).pack(side="left", padx=6)
        self.online_status = ttk.Label(bt, text="", style="Muted.TLabel", wraplength=640)
        self.online_status.grid(row=8, column=0, columnspan=3, sticky="w")
        self.versions_tree = ttk.Treeview(bt, columns=("code", "name", "licence"), show="headings", height=8)
        for col, title, width in (("code", "Code", 90), ("name", "Version", 240), ("licence", "Licence", 320)):
            self.versions_tree.heading(col, text=title)
            self.versions_tree.column(col, width=width, anchor="w")
        self.versions_tree.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Label(bt, text="Licensed versions are never stored on this computer. Public-domain and Creative "
                           "Commons versions are kept, so they also work offline.", style="Muted.TLabel",
                  wraplength=640).grid(row=10, column=0, columnspan=3, sticky="w", pady=(4, 0))
        bt.columnconfigure(1, weight=1)
        self.refresh_bibles()

    def refresh_bibles(self) -> None:
        """Show the connection state and the online versions."""
        from . import online_bible
        try:
            online = self.op.bible.online
            if online is None:
                text = online_bible.STATE_TEXT[online_bible.NO_KEY] if self.online_on.get() else \
                    "Online Bible versions are off."
                versions = []
            else:
                text = online_bible.STATE_TEXT.get(online.state, "")
                versions = sorted(online.versions.values(), key=lambda v: v.code.lower())
                if online.state == online_bible.ONLINE or versions:
                    text += " %d online version%s." % (len(versions), "" if len(versions) == 1 else "s")
            self.online_status.configure(text=text)
            self.versions_tree.delete(*self.versions_tree.get_children())
            local = set(self.op.bible.local_codes())
            for v in versions:
                lic = v.licence().replace(" (YouVersion, online)", "")
                if v.code in local:
                    lic = "Installed on this computer already; the local copy is used"
                self.versions_tree.insert("", "end", values=(v.code, v.name, lic))
        except tk.TclError:
            pass

    def _apply_bibles(self, refresh: bool = True) -> None:
        s = self.op.settings
        s["online_bibles"] = bool(self.online_on.get())
        s["youversion_key"] = self.yv_key.get().strip()
        s["online_languages"] = self.yv_langs.get().strip() or "en"
        s["offline_fallback"] = self.fallback.get()
        self.op.setup_online(refresh=refresh)

    def _connect(self) -> None:
        if not self.yv_key.get().strip():
            messagebox.showinfo("Online Bibles", "Enter your YouVersion app key first. You can get a free key at "
                                "platform.youversion.com.", parent=self.win)
            return
        self.online_on.set(True)
        self._apply_bibles(refresh=False)
        self.op.refresh_online()
        self.online_status.configure(text="Connecting\u2026")

    def _clear_online(self) -> None:
        if self.op.bible.online is not None:
            self.op.bible.online.clear_cache()
        self.online_status.configure(text="Saved Bible text cleared.")

    # -- models ------------------------------------------------------------------------
    def _speech_notes(self, installed) -> None:
        notes = {
            "auto": "both models if Parakeet is installed and this computer can run it, else Kroko",
            "both": "most detections; about 2 GB RAM" if "parakeet" in installed else
                    "needs Parakeet \u2014 download it in the Models tab",
            "kroko": "built in" if "kroko" in installed else "not installed \u2014 see the Models tab",
            "parakeet": "installed" if "parakeet" in installed else
                        "not installed \u2014 download it in the Models tab",
            "vosk-small": "for computers where the others will not run" if "vosk-small" in installed else
                          "not installed \u2014 see the Models tab",
            "custom": "",
        }
        for value, label in self.speech_notes.items():
            label.configure(text=notes.get(value, ""))

    def refresh_models(self) -> None:
        """Re-read what is installed (after a download finishes)."""
        try:
            installed = {m.id for m in recognizer.discover_models()}
            self._speech_notes(installed)
            for row in self.model_rows.values():
                row.refresh()
        except tk.TclError:
            pass

    def _tick(self) -> None:
        """Update download progress while the window is open."""
        try:
            if not self.win.winfo_exists():
                return
        except tk.TclError:
            return
        for row in self.model_rows.values():
            row.tick()
        self.win.after(250, self._tick)

    def use_model(self, model_id: str) -> None:
        self.speech_model.set(model_id)
        self.op.use_model(model_id)
        self.op._status("Using %s" % downloads.item(model_id).label)

    def _color(self, var, swatch) -> None:
        _, hexval = colorchooser.askcolor(color=var.get(), parent=self.win)
        if hexval:
            var.set(hexval)
            swatch.configure(background=hexval)

    def _choose_image(self) -> None:
        path = filedialog.askopenfilename(parent=self.win, title="Background image",
                                          filetypes=[("Images", "*.png *.gif"), ("All files", "*")])
        if path:
            self.image.set(path)

    def _choose_model(self) -> None:
        path = filedialog.askdirectory(parent=self.win, title="Choose speech model folder")
        if path:
            self.model_path.set(path)
            self.speech_model.set("custom")
            if recognizer.detect_model(path) is None:
                messagebox.showwarning("Speech model", "That folder does not look like a speech model Biverse "
                                       "can use (a Vosk model, or a sherpa-onnx model with biverse-model.json).",
                                       parent=self.win)

    def _install_pack(self) -> None:
        path = filedialog.askopenfilename(parent=self.win, title="Choose the Biverse model pack",
                                          filetypes=[("Model pack", "*.zip"), ("All files", "*")])
        if path:
            self._ok()
            self.op.install_pack(path)

    def apply(self) -> None:
        s = self.op.settings
        a = s.appearance
        a.background = self.bg.get()
        a.foreground = self.fg.get()
        a.highlight_color = self.hl.get()
        a.font_family = self.family.get()
        a.bold = bool(self.bold.get())
        a.shadow = bool(self.shadow.get())
        a.reference_position = self.refpos.get()
        a.background_image = self.image.get().strip()
        s.appearance = a
        s["fit_range"] = bool(self.fit_range.get())
        if bool(self.op_fullscreen.get()) != s["operator_fullscreen"]:
            self.op.set_fullscreen(bool(self.op_fullscreen.get()))
        s["ui_theme"] = {"Follow the computer": "system", "Dark": "dark", "Light": "light"}[self.ui_theme.get()]
        self.op._check_theme()
        s["strict_books"] = bool(self.strict.get())
        s["relative_verses"] = bool(self.relative.get())
        try:
            s["dedupe_window"] = max(0, min(600, int(self.dedupe.get())))
        except (tk.TclError, ValueError):
            pass
        s["auto_requires_verse"] = bool(self.auto_verse.get())
        s["reference_recognizer"] = bool(self.ref_rec.get())
        s["voice_commands"] = bool(self.voice_cmds.get())
        s["follow_reading"] = bool(self.follow.get())
        s["quote_matching"] = bool(self.quote_matching.get())
        s["quote_auto_live"] = bool(self.quote_auto.get())
        s["update_check"] = bool(self.update_check.get())
        self._apply_bibles()
        model_changed = (self.model_path.get().strip() != s["model_path"]
                         or self.speech_model.get() != s["speech_model"])
        s["model_path"] = self.model_path.get().strip()
        s["speech_model"] = self.speech_model.get()
        self.op.apply_settings()
        if model_changed:
            self.op.reload_model()

    def _test(self) -> None:
        self.apply()
        self.op.test_output()

    def _ok(self) -> None:
        self.apply()
        self.win.grab_release()
        self.win.destroy()
        if self.op.settings_dialog is self:
            self.op.settings_dialog = None


SPEECH_CHOICES = [
    ("auto", "Automatic (recommended)"),
    ("both", "Kroko live + Parakeet confirming"),
    ("kroko", "Kroko \u2014 live, fast, light"),
    ("parakeet", "Parakeet \u2014 most accurate, best with accents"),
    ("vosk-small", "Classic (Vosk small)"),
    ("custom", "A model folder I choose"),
]


def _fullscreen_label() -> str:
    import sys
    return "Ctrl+Cmd+F" if sys.platform == "darwin" else "F11"


class ModelRow(object):
    """One model in the Models tab: name, status, and Download / Cancel / Use."""

    def __init__(self, dlg: SettingsDialog, parent, it: "downloads.Item", row: int) -> None:
        self.dlg, self.it = dlg, it
        self.manager = dlg.op.downloads
        box = ttk.Frame(parent)
        box.grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        box.columnconfigure(0, weight=1)
        head = ttk.Frame(box)
        head.grid(row=0, column=0, sticky="ew")
        ttk.Label(head, text=it.label, font=("TkDefaultFont", 11, "bold")).pack(side="left")
        self.badge = ttk.Label(head, text="", style="Muted.TLabel")
        self.badge.pack(side="left", padx=(8, 0))
        ttk.Label(box, text=it.about, style="Muted.TLabel", wraplength=560).grid(row=1, column=0, sticky="w")
        self.bar = ttk.Progressbar(box, orient="horizontal", mode="determinate", maximum=1000, length=560)
        self.progress_text = ttk.Label(box, text="", style="Muted.TLabel", wraplength=560)
        btns = ttk.Frame(box)
        btns.grid(row=0, column=1, rowspan=2, sticky="ne", padx=(12, 0))
        self.use_button = ttk.Button(btns, text="Use it", width=10, command=self.on_use)
        self.button = ttk.Button(btns, text="Download", width=12, command=self.on_button)
        self.button.pack(side="right")
        self.state = ""
        self.refresh()

    def refresh(self) -> None:
        st = downloads.status(self.it)
        job = self.manager.job(self.it.id)
        size = downloads.mb(self.it.size())
        running = job is not None and job.state == "running"
        if running:
            self._show_progress(True)
            self.badge.configure(text="downloading")
            self.button.configure(text="Cancel", state="normal")
        elif st.installed:
            self._show_progress(False)
            self.badge.configure(text="\u2713 installed" + (" \u00b7 " + st.note if st.note else ""))
            self.button.configure(text="Installed", state="disabled")
        else:
            self._show_progress(job is not None and job.state in ("failed", "cancelled"))
            self.badge.configure(text="not installed \u00b7 %s%s" % (size, " \u00b7 " + st.note if st.note else ""))
            self.button.configure(text="Download" if st.can_download else "Not available",
                                  state="normal" if st.can_download else "disabled")
            if job is not None and job.state in ("failed", "cancelled"):
                self.progress_text.configure(text=job.describe())
        speech = self.it.kind == "speech"
        current = self.dlg.op.settings["speech_model"]
        if speech and st.installed and not running and current not in ("auto", self.it.id) and st.can_download:
            self.use_button.pack(side="right", padx=(0, 6))
        else:
            self.use_button.pack_forget()

    def _show_progress(self, on: bool) -> None:
        if on:
            self.bar.grid(row=2, column=0, sticky="w", pady=(4, 0))
            self.progress_text.grid(row=3, column=0, sticky="w")
        else:
            self.bar.grid_remove()
            self.progress_text.grid_remove()

    def tick(self) -> None:
        job = self.manager.job(self.it.id)
        if job is None or job.state != "running":
            if self.state == "running":
                self.refresh()
            self.state = job.state if job is not None else ""
            return
        if self.state != "running":
            self.state = "running"
            self.refresh()
        self.bar.configure(value=int(job.fraction() * 1000))
        self.progress_text.configure(text=job.describe())

    def on_button(self) -> None:
        job = self.manager.job(self.it.id)
        if job is not None and job.state == "running":
            self.manager.cancel(self.it.id)
            self.progress_text.configure(text="Stopping\u2026")
            return
        if self.it.size() > 300e6 and not messagebox.askokcancel(
                "Download %s" % self.it.label,
                "%s is a %s download. Start it now?\n\nOn a slow or metered connection, you can also download the "
                "model pack from the Biverse website on another computer." % (self.it.label, downloads.mb(
                    self.it.size())), parent=self.dlg.win):
            return
        self.manager.start(self.it.id)
        self.state = ""
        self.tick()

    def on_use(self) -> None:
        self.dlg.use_model(self.it.id)
        self.refresh()
