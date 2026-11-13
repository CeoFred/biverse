"""The projector window: a borderless, top-most Toplevel on the chosen display."""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from typing import Callable, Optional

from .displays import Display
from .render import EMPTY, Appearance, Renderer, Slide

log = logging.getLogger(__name__)


class OutputWindow(object):
    def __init__(self, root: tk.Tk, renderer: Renderer, appearance: Appearance,
                 on_visibility: Optional[Callable[[bool], None]] = None) -> None:
        self.root = root
        self.renderer = renderer
        self.appearance = appearance
        self.on_visibility = on_visibility
        self.slide = Slide(EMPTY)
        self.translation = ""
        self.display = None  # type: Optional[Display]
        self.fullscreen = True
        self.visible = False
        self._pending = None

        self.win = tk.Toplevel(root)
        self.win.title("BiVerse Output")
        self.win.configure(background="#000000")
        self.win.withdraw()
        self.win.protocol("WM_DELETE_WINDOW", self.hide)
        self.canvas = tk.Canvas(self.win, background="#000000", highlightthickness=0, borderwidth=0)
        self.canvas.pack(fill="both", expand=True)
        try:
            self.canvas.configure(cursor="none")
        except tk.TclError:
            pass
        self.canvas.bind("<Configure>", lambda e: self._schedule_redraw())
        self.win.bind("<F11>", lambda e: self.toggle_fullscreen())
        self.win.bind("<Escape>", lambda e: self.root.event_generate("<<OutputEscape>>"))

    # -- placement ----------------------------------------------------------
    @property
    def size(self):
        if self.display is None:
            return (1280, 720)
        return (self.display.width, self.display.height)

    def place(self, display: Display, fullscreen: Optional[bool] = None) -> None:
        """Move the window to ``display`` immediately."""
        self.display = display
        if fullscreen is not None:
            self.fullscreen = fullscreen
        self._apply_geometry()

    def _apply_geometry(self) -> None:
        d = self.display
        if d is None:
            return
        win = self.win
        if self.fullscreen:
            try:
                win.overrideredirect(True)
            except tk.TclError:
                pass
            win.geometry(d.geometry)
            try:
                win.attributes("-topmost", True)
            except tk.TclError:
                pass
        else:
            try:
                win.overrideredirect(False)
                win.attributes("-topmost", False)
            except tk.TclError:
                pass
            w = max(320, d.width // 2)
            h = max(180, d.height // 2)
            win.geometry("%dx%d+%d+%d" % (w, h, d.x + (d.width - w) // 2, d.y + (d.height - h) // 2))
        if self.visible:
            self._raise()
        self._schedule_redraw()

    def _raise(self) -> None:
        win = self.win
        win.update_idletasks()
        win.deiconify()
        win.lift()
        if sys.platform == "darwin" and self.fullscreen and self.display is not None:
            # macOS sometimes leaves an override-redirect window behind the menu bar
            # or on another Space; re-apply geometry, topmost and lift once mapped.
            def again():
                try:
                    win.geometry(self.display.geometry)
                    win.attributes("-topmost", True)
                    win.lift()
                except tk.TclError:
                    pass
            win.after(150, again)

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        self._apply_geometry()

    # -- visibility -----------------------------------------------------------
    def show(self) -> None:
        self.visible = True
        self._apply_geometry()
        self._raise()
        if self.on_visibility:
            self.on_visibility(True)

    def hide(self) -> None:
        self.visible = False
        self.win.withdraw()
        if self.on_visibility:
            self.on_visibility(False)

    def toggle(self) -> None:
        self.hide() if self.visible else self.show()

    # -- content ------------------------------------------------------------
    def set_slide(self, slide: Slide, translation: str = "") -> None:
        self.slide = slide
        self.translation = translation
        self.redraw()

    def set_appearance(self, appearance: Appearance) -> None:
        self.appearance = appearance
        self.redraw()

    def _schedule_redraw(self) -> None:
        if self._pending is None:
            self._pending = self.win.after_idle(self.redraw)

    def redraw(self) -> None:
        self._pending = None
        try:
            w = self.canvas.winfo_width()
            h = self.canvas.winfo_height()
            if w <= 1 or h <= 1:
                w, h = self.size
            self.renderer.draw(self.canvas, self.slide, self.appearance, w, h, translation=self.translation)
        except tk.TclError:
            log.exception("output redraw failed")

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except tk.TclError:
            pass
