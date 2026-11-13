"""Where things live, both when running from source and from a PyInstaller build."""

from __future__ import annotations

import os
import sys
from typing import List, Optional

APP_DIR_NAME = "BiVerse"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def source_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir() -> str:
    """Bundled read-only resources (``sys._MEIPASS`` in a PyInstaller build)."""
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return source_root()


def exe_dir() -> str:
    """Folder containing the executable (the repo root when running from source)."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return source_root()


def beside_app_dirs() -> List[str]:
    """Folders a user can drop things into next to the program.

    On macOS the executable is inside ``BiVerse.app/Contents/MacOS``; the folder
    that contains ``BiVerse.app`` counts as "next to the executable" too.
    """
    dirs = [exe_dir()]
    if is_frozen() and sys.platform == "darwin":
        parts = exe_dir().split(os.sep)
        for i in range(len(parts) - 1, 0, -1):
            if parts[i].endswith(".app"):
                dirs.append(os.sep.join(parts[:i]) or os.sep)
                break
    return dirs


def config_dir() -> str:
    """Per-user settings folder (created on demand)."""
    override = os.environ.get("BIVERSE_CONFIG_DIR")
    if override:
        path = override
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        path = os.path.join(base, APP_DIR_NAME)
    elif sys.platform == "darwin":
        path = os.path.expanduser("~/Library/Application Support/" + APP_DIR_NAME)
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        path = os.path.join(base, APP_DIR_NAME.lower())
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass
    return path


def log_dir() -> str:
    return config_dir()


def bible_db_path() -> Optional[str]:
    """The bundled Bible database."""
    candidates = [os.path.join(d, "data", "bible.db") for d in beside_app_dirs()]
    candidates.append(os.path.join(resource_dir(), "data", "bible.db"))
    candidates.append(os.path.join(source_root(), "data", "bible.db"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def user_bible_db_path() -> str:
    """Translations imported by the user (``tools/import_translation.py``)."""
    return os.path.join(config_dir(), "user_translations.db")


def model_search_dirs(user_choice: Optional[str] = None) -> List[str]:
    """Candidate speech-model locations in discovery order (spec §6)."""
    dirs = []
    if user_choice:
        dirs.append(user_choice)
    for d in beside_app_dirs():
        dirs.append(os.path.join(d, "models"))
    dirs.append(os.path.join(resource_dir(), "models"))
    dirs.append(os.path.join(source_root(), "models"))
    seen = set()
    out = []
    for d in dirs:
        key = os.path.normcase(os.path.abspath(d))
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def asset_path(name: str) -> str:
    for base in (resource_dir(), source_root()):
        for sub in ("assets", os.path.join("packaging", "icons")):
            path = os.path.join(base, sub, name)
            if os.path.exists(path):
                return path
    return os.path.join(resource_dir(), "assets", name)
