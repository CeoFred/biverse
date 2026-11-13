"""Small facts about the computer, used to pick a speech model (stdlib only)."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from typing import Optional


def is_64bit() -> bool:
    return sys.maxsize > 2 ** 32


def total_ram_gb() -> Optional[float]:
    """Installed RAM in GB, or None if it cannot be determined."""
    try:
        if sys.platform == "win32":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return stat.ullTotalPhys / 1e9
            return None
        if sys.platform == "darwin":
            out = subprocess.run(["sysctl", "-n", "hw.memsize"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 timeout=3, text=True).stdout.strip()
            return int(out) / 1e9 if out.isdigit() else None
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return pages * size / 1e9
    except Exception:
        return None
