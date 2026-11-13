"""Settings dialog: appearance, speech model and detection options."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog, messagebox, ttk

from . import recognizer


class SettingsDialog(object):
    def __init__(self, op) -> None:
        self.op = op
        s = op.settings
        a = s.appearance
        self.win = tk.Toplevel(op.root)
        self.win.title("Settings")
        self.win.transient(op.root)
        self.win.resizable(False, False)

        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # -- appearance
        ap = ttk.Frame(nb, padding=10)
        nb.add(ap, text="Appearance")
        self.bg = tk.StringVar(value=a.background)
        self.fg = tk.StringVar(value=a.foreground)
        self.family = tk.StringVar(value=a.font_family or op.renderer.family(a))
        self.bold = tk.BooleanVar(value=a.bold)
        self.shadow = tk.BooleanVar(value=a.shadow)
        self.refpos = tk.StringVar(value=a.reference_position)
        self.image = tk.StringVar(value=a.background_image)
        self.fit_range = tk.BooleanVar(value=s["fit_range"])

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
                  foreground="#666666").grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        ttk.Checkbutton(ap, text="Fit a whole verse range on one slide when it fits",
                        variable=self.fit_range).grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # -- speech
        sp = ttk.Frame(nb, padding=10)
        nb.add(sp, text="Speech")
        self.speech_model = tk.StringVar(value=s["speech_model"])
        self.model_path = tk.StringVar(value=s["model_path"])
        installed = {m.id for m in recognizer.discover_models()}
        ttk.Label(sp, text="In use: %s" % (op.engine.model_label or "(none)"), font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        choices = [
            ("auto", "Automatic (recommended)", "both models if the Parakeet pack is installed and this "
             "computer can run it, else Kroko"),
            ("both", "Kroko live + Parakeet confirming", "most detections; needs the pack, about 2 GB RAM"
             if "parakeet" in installed else "not installed \u2014 needs the model pack"),
            ("kroko", "Kroko \u2014 live, fast, light", "built in"),
            ("parakeet", "Parakeet \u2014 most accurate, best with accents",
             "installed" if "parakeet" in installed else "not installed \u2014 needs the model pack"),
            ("vosk-small", "Classic (Vosk small)", "for computers where the others will not run"
             if "vosk-small" in installed else "not installed"),
            ("custom", "A model folder I choose", ""),
        ]
        for row, (value, text, note) in enumerate(choices, 1):
            ttk.Radiobutton(sp, text=text, value=value, variable=self.speech_model).grid(
                row=row, column=0, sticky="w")
            ttk.Label(sp, text=note, foreground="#666666").grid(row=row, column=1, columnspan=2, sticky="w",
                                                                padx=(8, 0))
        row = len(choices) + 1
        folder = ttk.Frame(sp)
        folder.grid(row=row, column=0, columnspan=3, sticky="w", padx=(22, 0))
        ttk.Entry(folder, textvariable=self.model_path, width=38).pack(side="left")
        ttk.Button(folder, text="Choose\u2026", command=self._choose_model).pack(side="left", padx=4)
        row += 1
        ttk.Separator(sp).grid(row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        ttk.Button(sp, text="Install model pack\u2026", command=self._install_pack).grid(
            row=row, column=0, sticky="w")
        ttk.Label(sp, text="For the Parakeet pack zip from the Biverse download page. Needs a 64-bit computer "
                           "with about 6 GB of RAM or more.", wraplength=330, foreground="#666666").grid(
            row=row, column=1, columnspan=2, sticky="w", padx=(8, 0))

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
                  foreground="#666666", wraplength=420).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(dt, text="Follow the reading: move to the next verse as the preacher finishes each one",
                        variable=self.follow).grid(row=8, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Checkbutton(dt, text="Extra reference listener (classic engine only; about twice the CPU)",
                        variable=self.ref_rec).grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 2))
        ttk.Label(dt, text="Turn off on very slow computers. It only adds references that include both a "
                           "chapter and a verse.", foreground="#666666", wraplength=420).grid(
            row=5, column=0, columnspan=2, sticky="w")

        btns = ttk.Frame(self.win, padding=(8, 0, 8, 8))
        btns.pack(fill="x")
        ttk.Button(btns, text="Test output", command=self._test).pack(side="left")
        ttk.Button(btns, text="Close", command=self._ok).pack(side="right")
        ttk.Button(btns, text="Apply", command=self.apply).pack(side="right", padx=4)
        self.win.protocol("WM_DELETE_WINDOW", self._ok)
        self.win.bind("<Escape>", lambda e: (self._ok(), "break")[1])
        self.win.grab_set()

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
        a.font_family = self.family.get()
        a.bold = bool(self.bold.get())
        a.shadow = bool(self.shadow.get())
        a.reference_position = self.refpos.get()
        a.background_image = self.image.get().strip()
        s.appearance = a
        s["fit_range"] = bool(self.fit_range.get())
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
