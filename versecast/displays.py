"""Enumerate connected monitors in the coordinate space Tk uses.

Windows: EnumDisplayMonitors + GetMonitorInfoW (physical pixels; the process
         is made per-monitor DPI aware before Tk starts, see app.py).
macOS:   CoreGraphics CGGetActiveDisplayList / CGDisplayBounds (points,
         top-left origin, the same as Tk).
Linux:   ``xrandr --listmonitors``.
Fallback on any OS: one display the size of Tk's screen.
"""

from __future__ import annotations

import ctypes
import logging
import re
import subprocess
import sys
from typing import List, Optional

log = logging.getLogger(__name__)


class Display(object):
    __slots__ = ("index", "name", "x", "y", "width", "height", "is_primary", "device")

    def __init__(self, index: int, name: str, x: int, y: int, width: int, height: int,
                 is_primary: bool, device: str = "") -> None:
        self.index = index
        self.name = name
        self.x = int(x)
        self.y = int(y)
        self.width = int(width)
        self.height = int(height)
        self.is_primary = bool(is_primary)
        self.device = device

    @property
    def geometry(self) -> str:
        """Tk geometry string; negative offsets are kept as ``+-1920+0``."""
        return "%dx%d+%d+%d" % (self.width, self.height, self.x, self.y)

    def label(self) -> str:
        text = u"Display %d — %d×%d" % (self.index + 1, self.width, self.height)
        if self.is_primary:
            text += " (primary)"
        return text

    def key(self) -> dict:
        return {"index": self.index, "x": self.x, "y": self.y, "width": self.width, "height": self.height,
                "device": self.device}

    def __eq__(self, other):
        return isinstance(other, Display) and self.key() == other.key()

    def __hash__(self):
        return hash((self.x, self.y, self.width, self.height))

    def __repr__(self) -> str:
        return "Display(%d, %s, primary=%s)" % (self.index, self.geometry, self.is_primary)


# -- Windows ---------------------------------------------------------------------

def _windows() -> List[Display]:
    from ctypes import wintypes

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    user32 = ctypes.windll.user32
    MONITORENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HMONITOR, wintypes.HDC,
                                         ctypes.POINTER(RECT), wintypes.LPARAM)
    found = []

    def callback(hmon, hdc, lprect, lparam):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(MONITORINFOEXW)
        if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            r = info.rcMonitor
            found.append((r.left, r.top, r.right - r.left, r.bottom - r.top,
                          bool(info.dwFlags & 1), info.szDevice))
        return 1

    cb = MONITORENUMPROC(callback)
    user32.EnumDisplayMonitors(None, None, cb, 0)
    return _finish(found)


# -- macOS -----------------------------------------------------------------------

def _macos() -> List[Display]:
    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    class CGSize(ctypes.Structure):
        _fields_ = [("width", ctypes.c_double), ("height", ctypes.c_double)]

    class CGRect(ctypes.Structure):
        _fields_ = [("origin", CGPoint), ("size", CGSize)]

    cg = None
    for path in ("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics",
                 "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"):
        try:
            cg = ctypes.cdll.LoadLibrary(path)
            break
        except OSError:
            continue
    if cg is None:
        return []
    cg.CGGetActiveDisplayList.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                          ctypes.POINTER(ctypes.c_uint32)]
    cg.CGGetActiveDisplayList.restype = ctypes.c_int32
    cg.CGDisplayBounds.argtypes = [ctypes.c_uint32]
    cg.CGDisplayBounds.restype = CGRect
    cg.CGDisplayIsMain.argtypes = [ctypes.c_uint32]
    cg.CGDisplayIsMain.restype = ctypes.c_uint32
    ids = (ctypes.c_uint32 * 32)()
    count = ctypes.c_uint32(0)
    if cg.CGGetActiveDisplayList(32, ids, ctypes.byref(count)) != 0:
        return []
    found = []
    for i in range(count.value):
        r = cg.CGDisplayBounds(ids[i])
        found.append((int(round(r.origin.x)), int(round(r.origin.y)), int(round(r.size.width)),
                      int(round(r.size.height)), bool(cg.CGDisplayIsMain(ids[i])), str(ids[i])))
    return _finish(found)


# -- Linux -----------------------------------------------------------------------

_XRANDR_RE = re.compile(r"^\s*\d+:\s+\+?(\*?)(\S+)\s+(\d+)/\d+x(\d+)/\d+\+?(-?\d+)\+?(-?\d+)")


def parse_xrandr(output: str) -> List[Display]:
    found = []
    for line in output.splitlines():
        m = _XRANDR_RE.match(line)
        if m:
            found.append((int(m.group(5)), int(m.group(6)), int(m.group(3)), int(m.group(4)),
                          m.group(1) == "*", m.group(2)))
    if found and not any(f[4] for f in found):
        first = found[0]
        found[0] = first[:4] + (True,) + first[5:]
    return _finish(found)


def _linux() -> List[Display]:
    try:
        out = subprocess.run(["xrandr", "--listmonitors"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             timeout=3, text=True).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_xrandr(out)


# -- common ----------------------------------------------------------------------

def _finish(found) -> List[Display]:
    """Order: primary first, then left-to-right, top-to-bottom; assign indices."""
    found = sorted(found, key=lambda f: (not f[4], f[0], f[1]))
    return [Display(i, "", x, y, w, h, primary, dev) for i, (x, y, w, h, primary, dev) in enumerate(found)]


def fallback(root=None) -> List[Display]:
    w, h = 1024, 768
    if root is not None:
        try:
            w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        except Exception:
            pass
    return [Display(0, "", 0, 0, w, h, True, "screen")]


def list_displays(root=None) -> List[Display]:
    displays = []  # type: List[Display]
    try:
        if sys.platform == "win32":
            displays = _windows()
        elif sys.platform == "darwin":
            displays = _macos()
        else:
            displays = _linux()
    except Exception:
        log.exception("display enumeration failed")
        displays = []
    displays = [d for d in displays if d.width > 0 and d.height > 0]
    return displays or fallback(root)


def default_display(displays: List[Display]) -> Display:
    for d in displays:
        if not d.is_primary:
            return d
    return displays[0]


def find_saved(displays: List[Display], saved: Optional[dict]) -> Optional[Display]:
    """Match a saved display: same geometry first, then same index."""
    if not saved or not displays:
        return None
    for d in displays:
        if (d.x, d.y, d.width, d.height) == (saved.get("x"), saved.get("y"), saved.get("width"),
                                              saved.get("height")):
            return d
    if saved.get("device"):
        for d in displays:
            if d.device and d.device == saved.get("device"):
                return d
    idx = saved.get("index")
    if isinstance(idx, int) and 0 <= idx < len(displays):
        return displays[idx]
    return None
