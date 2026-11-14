"""Modern light/dark look for the operator windows, following the computer's setting.

Built on ttk's "clam" theme (the native aqua/vista themes cannot be recoloured),
with one palette per mode: flat surfaces, one accent colour, a red Live colour.
``system_mode()`` reads the OS setting; the operator window re-checks it every
few seconds and re-applies the theme when it changes.
"""

from __future__ import annotations

import subprocess
import sys
import tkinter.font as tkfont
from tkinter import ttk
from typing import Dict

DARK = {
    "bg": "#1b1c1f", "surface": "#24262b", "surface2": "#2d3036", "border": "#3a3d44", "text": "#e8e9eb",
    "muted": "#9aa0a8", "accent": "#5b8cff", "accent_hover": "#7aa2ff", "accent_text": "#ffffff",
    "live": "#ff5c5c", "ok": "#3ecf8e", "warn": "#f5a524", "error": "#ff6b6b", "select": "#36508a",
    "input": "#1f2125", "banner_bg": "#3b3215", "banner_fg": "#ffd98a", "meter_bg": "#141518",
    "button": "#30333a", "button_hover": "#3a3e46", "partial": "#7d838c",
}
LIGHT = {
    "bg": "#f3f4f6", "surface": "#ffffff", "surface2": "#eef0f3", "border": "#d6d9de", "text": "#1d2127",
    "muted": "#646b75", "accent": "#2f6feb", "accent_hover": "#1f5ad6", "accent_text": "#ffffff",
    "live": "#d93848", "ok": "#1a8f3a", "warn": "#b86e00", "error": "#c4252f", "select": "#cfe0ff",
    "input": "#ffffff", "banner_bg": "#fff3cd", "banner_fg": "#5c4400", "meter_bg": "#e4e6ea",
    "button": "#eef0f3", "button_hover": "#e2e5ea", "partial": "#8a919b",
}


def system_mode() -> str:
    """"dark" or "light" from the operating system (light if unknown)."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, timeout=2, text=True).stdout
            return "dark" if "dark" in out.lower() else "light"
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _t = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value else "dark"
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2,
                             text=True).stdout
        return "dark" if "dark" in out.lower() else "light"
    except Exception:
        return "light"


def palette(mode: str) -> Dict[str, str]:
    return DARK if mode == "dark" else LIGHT


def _family(root) -> str:
    fams = set(tkfont.families(root))
    for name in ("Segoe UI", "SF Pro Text", ".AppleSystemUIFont", "Helvetica Neue", "Inter", "Ubuntu",
                 "Cantarell", "DejaVu Sans", "Helvetica"):
        if name in fams:
            return name
    return tkfont.nametofont("TkDefaultFont", root).actual()["family"]


def apply(root, mode: str) -> Dict[str, str]:
    """Style every ttk widget for ``mode`` and return its palette (for tk widgets)."""
    p = palette(mode)
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")
    fam = _family(root)
    size = 10 if sys.platform == "win32" else 12 if sys.platform == "darwin" else 10
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name, root).configure(family=fam, size=size)
        except Exception:
            pass
    root.configure(background=p["bg"])
    root.option_add("*Menu.background", p["surface"])
    root.option_add("*Menu.foreground", p["text"])
    root.option_add("*Menu.activeBackground", p["select"])
    root.option_add("*TCombobox*Listbox.background", p["input"])
    root.option_add("*TCombobox*Listbox.foreground", p["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["select"])
    root.option_add("*TCombobox*Listbox.selectForeground", p["text"])

    style.configure(".", background=p["bg"], foreground=p["text"], fieldbackground=p["input"],
                    bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"], troughcolor=p["surface2"],
                    selectbackground=p["select"], selectforeground=p["text"], insertcolor=p["text"],
                    focuscolor=p["accent"], font=(fam, size))
    style.configure("TFrame", background=p["bg"])
    style.configure("Card.TFrame", background=p["surface"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Card.TLabel", background=p["surface"], foreground=p["text"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
    style.configure("CardMuted.TLabel", background=p["surface"], foreground=p["muted"])
    style.configure("Title.TLabel", background=p["bg"], foreground=p["text"], font=(fam, size + 6, "bold"))
    style.configure("Section.TLabel", background=p["surface"], foreground=p["muted"], font=(fam, size - 1, "bold"))
    style.configure("Live.TLabel", background=p["surface"], foreground=p["live"], font=(fam, size - 1, "bold"))
    style.configure("Preview.TLabel", background=p["surface"], foreground=p["accent"], font=(fam, size - 1, "bold"))
    style.configure("TLabelframe", background=p["surface"], bordercolor=p["border"], relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=p["surface"], foreground=p["muted"], font=(fam, size - 1, "bold"))

    style.configure("TButton", background=p["button"], foreground=p["text"], bordercolor=p["border"],
                    lightcolor=p["button"], darkcolor=p["button"], focusthickness=0, padding=(10, 5), relief="flat")
    style.map("TButton", background=[("pressed", p["border"]), ("active", p["button_hover"])],
              lightcolor=[("active", p["button_hover"])], darkcolor=[("active", p["button_hover"])],
              foreground=[("disabled", p["muted"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_text"], bordercolor=p["accent"],
                    lightcolor=p["accent"], darkcolor=p["accent"], font=(fam, size, "bold"), padding=(14, 7))
    style.map("Accent.TButton", background=[("pressed", p["accent_hover"]), ("active", p["accent_hover"])],
              lightcolor=[("active", p["accent_hover"])], darkcolor=[("active", p["accent_hover"])])
    style.configure("Live.TButton", background=p["live"], foreground="#ffffff", bordercolor=p["live"],
                    lightcolor=p["live"], darkcolor=p["live"], font=(fam, size, "bold"))
    style.map("Live.TButton", background=[("active", p["live"])])

    style.configure("TEntry", fieldbackground=p["input"], foreground=p["text"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"], padding=6, insertcolor=p["text"])
    style.map("TEntry", bordercolor=[("focus", p["accent"])], lightcolor=[("focus", p["accent"])])
    style.configure("TCombobox", fieldbackground=p["input"], background=p["button"], foreground=p["text"],
                    arrowcolor=p["text"], bordercolor=p["border"], lightcolor=p["border"], darkcolor=p["border"],
                    padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", p["input"])], foreground=[("readonly", p["text"])],
              selectbackground=[("readonly", p["input"])], selectforeground=[("readonly", p["text"])],
              bordercolor=[("focus", p["accent"])])
    style.configure("TSpinbox", fieldbackground=p["input"], foreground=p["text"], arrowcolor=p["text"],
                    background=p["button"])
    for w in ("TRadiobutton", "TCheckbutton"):
        style.configure(w, background=p["bg"], foreground=p["text"], indicatorbackground=p["input"],
                        indicatorforeground=p["accent"], upperbordercolor=p["border"], lowerbordercolor=p["border"])
        style.map(w, background=[("active", p["bg"])], indicatorbackground=[("selected", p["accent"])],
                  indicatorforeground=[("selected", p["accent_text"])])
    style.configure("Treeview", background=p["surface"], fieldbackground=p["surface"], foreground=p["text"],
                    bordercolor=p["border"], rowheight=int(size * 2.4))
    style.map("Treeview", background=[("selected", p["select"])], foreground=[("selected", p["text"])])
    style.configure("Treeview.Heading", background=p["surface2"], foreground=p["muted"], relief="flat",
                    font=(fam, size - 1, "bold"), bordercolor=p["border"], lightcolor=p["surface2"],
                    darkcolor=p["surface2"], padding=(6, 4))
    style.map("Treeview.Heading", background=[("active", p["surface2"])])
    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"], tabmargins=(0, 4, 0, 0))
    style.configure("TNotebook.Tab", background=p["surface2"], foreground=p["muted"], padding=(14, 6),
                    bordercolor=p["border"], lightcolor=p["surface2"])
    style.map("TNotebook.Tab", background=[("selected", p["surface"])], foreground=[("selected", p["text"])])
    for w in ("TScrollbar", "Vertical.TScrollbar", "Horizontal.TScrollbar"):
        style.configure(w, background=p["surface2"], troughcolor=p["surface"], bordercolor=p["surface"],
                        lightcolor=p["surface2"], darkcolor=p["surface2"], arrowcolor=p["muted"], gripcount=0)
        style.map(w, background=[("active", p["border"]), ("pressed", p["border"])],
                  lightcolor=[("active", p["border"])], darkcolor=[("active", p["border"])])
    style.configure("TPanedwindow", background=p["bg"])
    style.configure("Sash", sashthickness=6, gripcount=0, background=p["bg"])
    style.configure("TSeparator", background=p["border"])
    return p
