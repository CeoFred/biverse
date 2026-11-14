#!/usr/bin/env python3
"""Generate README screenshots from the running app (Linux, under Xvfb, ImageMagick ``import``).

    xvfb-run -a -s "-screen 0 1024x600x24"  python tools/screenshots.py operator docs/screenshots/operator-1024x600.png
    xvfb-run -a -s "-screen 0 1920x1080x24" python tools/screenshots.py operator docs/screenshots/operator-1920x1080.png
    xvfb-run -a -s "-screen 0 1920x1080x24" python tools/screenshots.py output   docs/screenshots/output-1920x1080.png

The operator window is filled with a scripted demo (transcript, detections,
search) so the picture shows real behaviour; the layout is the real app's.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("BIVERSE_CONFIG_DIR", tempfile.mkdtemp(prefix="biverse-shot-"))

from biverse.app import _ttk_theme  # noqa: E402
from biverse.bible import open_default  # noqa: E402
from biverse.detector import Detector  # noqa: E402
from biverse.settings import Settings  # noqa: E402
from biverse.ui_operator import OperatorWindow  # noqa: E402

SPEECH = [
    "good morning church please open your bibles with me to romans chapter eight",
    "verse twenty eight and we know that all things work together for good",
    "the most famous verse is john three sixteen",
    "and first corinthians thirteen four through seven love is patient",
]


def main(kind: str, out: str) -> int:
    root = tk.Tk()
    _ttk_theme(root)
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    settings = Settings().load()
    settings["output_visible"] = kind == "output"
    settings["window_geometry"] = "%dx%d+0+0" % (sw, sh)
    op = OperatorWindow(root, settings, open_default())
    root.geometry("%dx%d+0+0" % (sw, sh))
    det = Detector()

    def demo():
        for i, text in enumerate(SPEECH):
            op._handle(("final", text))
            for kind_, d in det.feed_final(text, now=i * 4.0):
                op._handle(("detect", kind_, d))
        op.search_var.set("john 3:16")
        op.search()
        op.go_live()
        # show emphasis on the projector: highlight "so loved", underline "everlasting life"
        sel = op.live.selection
        op.emphasis.toggle("KJV", sel.book, sel.chapter, sel.cur, [2, 3], "highlight")
        op.emphasis.toggle("KJV", sel.book, sel.chapter, sel.cur, [23, 24], "underline")
        op._render_all()
        op.search_var.set("love is patient")
        op.search()
        op._handle(("partial", "for god so loved the world that he"))
        op.listening = True
        op._update_listen_ui()
        op._status("Listening")
        if kind == "output":
            op.output.place(op.displays[0], fullscreen=True)
            op.output.show()
        root.after(1500, shoot)

    def shoot():
        root.update()
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        subprocess.check_call(["import", "-window", "root", out])
        op.listening = False
        op.close()

    root.after(1500, demo)
    root.mainloop()
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
