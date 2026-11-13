"""Entry point: logging, DPI awareness, Tk start-up, ``--self-test``."""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import platform
import sys
import threading
import time
import traceback

from . import APP_NAME, __version__, paths

log = logging.getLogger("versecast")

SELF_TEST_SENTENCES = [
    ("turn with me to john chapter three verse sixteen", ["John 3:16"]),
    ("romans eight twenty eight", ["Romans 8:28"]),
    ("first corinthians thirteen four through seven", ["1 Corinthians 13:4-7"]),
    ("psalm one nineteen one hundred and five", ["Psalm 119:105"]),
    ("i lost my job three years ago", []),
    ("mark two people came early", []),
    ("the book of revelation chapter twenty two verse twenty one", ["Revelation 22:21"]),
    ("second timothy three sixteen", ["2 Timothy 3:16"]),
    ("philippines four thirteen", ["Philippians 4:13"]),
    ("genesis one one and john one one", ["Genesis 1:1", "John 1:1"]),
]


def setup_logging(console: bool = True) -> str:
    path = os.path.join(paths.log_dir(), "biverse.log")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(name)s: %(message)s")
    try:
        fh = logging.handlers.RotatingFileHandler(path, maxBytes=1000000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    if console and sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        sh.setLevel(logging.WARNING)
        root.addHandler(sh)

    def thread_hook(args):
        log.error("uncaught exception in thread %s", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    threading.excepthook = thread_hook
    return path


def set_dpi_awareness() -> None:
    """Windows: real pixels for display coordinates (per-monitor v1, Win 7 fallback)."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _ttk_theme(root) -> None:
    from tkinter import ttk
    style = ttk.Style(root)
    names = style.theme_names()
    for theme in (("vista", "xpnative") if sys.platform == "win32" else
                  ("aqua",) if sys.platform == "darwin" else ("clam",)):
        if theme in names:
            style.theme_use(theme)
            break


def run_gui(args) -> int:
    import tkinter as tk
    from tkinter import messagebox

    from .bible import open_default
    from .settings import Settings
    from .ui_operator import OperatorWindow

    set_dpi_awareness()
    root = tk.Tk(className=APP_NAME)
    _ttk_theme(root)
    try:
        icon = paths.asset_path("biverse.png")
        if os.path.exists(icon):
            root.iconphoto(True, tk.PhotoImage(file=icon))
    except Exception:
        pass

    def report_callback_exception(exc, val, tb):
        log.error("callback error", exc_info=(exc, val, tb))
        try:
            messagebox.showerror(APP_NAME, "Something went wrong (it has been logged):\n\n%s" % val, parent=root)
        except Exception:
            pass

    root.report_callback_exception = report_callback_exception

    bible = open_default()
    if bible is None:
        messagebox.showerror(APP_NAME, "The Bible database (data/bible.db) is missing.\n\nIf you are running from "
                             "source, run: python tools/build_bible_db.py")
        root.destroy()
        return 2
    settings = Settings().load()
    op = OperatorWindow(root, settings, bible)
    if args.screenshot:
        root.after(int(args.screenshot_delay * 1000), lambda: _screenshot_and_quit(op, args.screenshot))
    root.mainloop()
    bible.close()
    return 0


def _screenshot_and_quit(op, path):  # pragma: no cover - docs tooling under Xvfb (ImageMagick)
    import subprocess
    op.root.update()
    try:
        subprocess.call(["import", "-window", "root", path])
    finally:
        op.close()


# ----------------------------------------------------------------- self-test

def self_test(report_path: str = "") -> int:
    """Exercise the packaged build without user interaction; print a JSON report."""
    report = {"app": APP_NAME, "version": __version__, "python": sys.version.split()[0],
              "platform": platform.platform(), "machine": platform.machine(),
              "frozen": paths.is_frozen(), "checks": {}}
    ok = True

    def check(name, fn, critical=True):
        nonlocal ok
        t = time.perf_counter()
        try:
            result = fn()
            report["checks"][name] = {"ok": True, "result": result, "ms": round((time.perf_counter() - t) * 1000)}
        except Exception as exc:
            report["checks"][name] = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc),
                                      "trace": traceback.format_exc()[-2000:], "critical": critical}
            if critical:
                ok = False

    def db():
        from .bible import open_default
        b = open_default()
        assert b is not None, "bible.db not found"
        out = {"path": b.path, "translations": {}}
        for code, _, _ in b.translations():
            n = b.total_verses(code)
            assert n == 31102, (code, n)
            out["translations"][code] = n
        jn = b.verse("KJV", 43, 3, 16)
        assert jn and jn.startswith("For God so loved the world"), jn
        assert b.search("KJV", "so loved the world")[0].pos() == (43, 3, 16)
        b.close()
        return out

    def model():
        from . import recognizer
        path = recognizer.find_model()
        assert path, "no speech model found"
        m = recognizer.load_model(path)
        silence = b"\0\0" * 16000
        texts = recognizer.transcribe_pcm(m, 16000, silence)
        lib = None
        import vosk
        vdir = os.path.dirname(vosk.__file__)
        for name in os.listdir(vdir):
            if name.startswith("libvosk"):
                lib = name
        return {"path": path, "vosk_lib": lib, "silence_text": texts}

    def parser():
        from .parser import parse
        results = []
        for text, expected in SELF_TEST_SENTENCES:
            got = [r.label() for r in parse(text)]
            assert got == expected, (text, got, expected)
            results.append(got)
        return {"sentences": len(results)}

    def displays_():
        from . import displays
        return [d.label() + " @ " + d.geometry for d in displays.list_displays(None)]

    def audio_():
        from . import audio
        assert audio.available(), "sounddevice/PortAudio failed to load: %s" % audio.SD_ERROR
        import sounddevice as sd
        devs = audio.list_input_devices()
        return {"portaudio": sd.get_portaudio_version()[1], "input_devices": [d.label() for d in devs]}

    def tk_():
        import tkinter as tk
        r = tk.Tk()
        r.withdraw()
        v = r.tk.call("info", "patchlevel")
        r.destroy()
        return {"tk": v}

    check("database", db)
    check("speech_model", model)
    check("parser", parser)
    check("displays", displays_)
    check("audio", audio_)
    check("tk", tk_, critical=False)
    report["ok"] = ok
    text = json.dumps(report, indent=2, default=str)
    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(text)
    if sys.stdout is not None:
        try:
            print(text)
        except Exception:
            pass
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=APP_NAME, description="Live Bible verse projection from speech.")
    ap.add_argument("--version", action="version", version="%s %s" % (APP_NAME, __version__))
    ap.add_argument("--self-test", action="store_true", help="run start-up checks, print JSON and exit")
    ap.add_argument("--report", default="", help="also write the self-test JSON to this file")
    ap.add_argument("--import-translation", nargs=3, metavar=("CODE", "NAME", "FILE"),
                    help="import a CSV/JSON translation you hold a licence for, then exit")
    ap.add_argument("--screenshot", default="", help=argparse.SUPPRESS)
    ap.add_argument("--screenshot-delay", type=float, default=3.0, help=argparse.SUPPRESS)
    # macOS passes -psn_... when launched from Finder on old systems
    args, _unknown = ap.parse_known_args(argv)

    setup_logging(console=not args.self_test)
    log.info("%s %s starting (python %s, %s)", APP_NAME, __version__, sys.version.split()[0], platform.platform())
    if args.self_test:
        return self_test(args.report)
    if args.import_translation:
        from .import_cli import run_import
        return run_import(list(args.import_translation))
    return run_gui(args)


if __name__ == "__main__":
    sys.exit(main())
