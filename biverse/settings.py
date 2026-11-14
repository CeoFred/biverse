"""Settings stored as JSON in the per-user config folder.

* Loaded with defaults merged in; values of the wrong type are ignored.
* A corrupt file is backed up (``settings.json.corrupt-<time>``) and Biverse
  starts fresh.
* Writes are atomic (temp file + ``os.replace``).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import time
from typing import Any, Dict

from . import paths
from .render import Appearance

log = logging.getLogger(__name__)

FILENAME = "settings.json"

DEFAULTS = {
    "version": 1,
    # input device, matched by name + host API (indices change between runs)
    "input_device": {"name": "", "hostapi": ""},
    # output display, matched by geometry then index
    "output_display": {},
    "output_visible": True,
    "translation": "KJV",
    "mode": "manual",               # "manual" | "auto"
    "appearance": Appearance().to_dict(),
    "fit_range": False,             # fit a whole range on one slide when it fits
    "window_geometry": "",
    "operator_fullscreen": True,    # open the operator window full screen
    "ui_theme": "system",           # operator window look: system | dark | light
    "speech_model": "auto",          # auto | kroko | parakeet | vosk-small | custom
    "model_path": "",               # folder used when speech_model == "custom"
    "strict_books": True,
    "relative_verses": True,
    "dedupe_window": 60,
    "auto_requires_verse": True,    # auto mode only sends chapter AND verse live
    "voice_commands": True,         # spoken "next verse", "go back", "next chapter"
    "follow_reading": True,         # follow the preacher reading and move to the next verse
    # verses recognised from their words (quotes.py): suggest them under Possible references
    "quote_matching": True,
    "quote_auto_live": False,       # Auto mode: confirmed strong matches go live (needs AUTO_LIVE_ALLOWED)
    "reference_recognizer": True,   # second, reference-only recogniser (more detections, ~2x CPU)
    # online Bible versions (YouVersion Platform API); each user enters their own app key
    "online_bibles": True,
    "youversion_key": "",
    "online_languages": "en",       # language tags, comma separated ("en, fr, yo")
    "offline_fallback": "KJV",      # shown when an online version cannot be reached
    # in-app updates (biverse/updates.py): checked at most twice a day, never while listening
    "update_check": True,
    "update_skipped": "",           # "Skip this version": not offered again until a newer one
    "update_last_check": 0.0,       # time.time() of the last automatic check
}  # type: Dict[str, Any]


def _merge(defaults: Dict[str, Any], loaded: Any) -> Dict[str, Any]:
    out = copy.deepcopy(defaults)
    if not isinstance(loaded, dict):
        return out
    for key, default in defaults.items():
        if key not in loaded:
            continue
        value = loaded[key]
        if isinstance(default, dict):
            if isinstance(value, dict):
                out[key] = _merge(default, value) if default else dict(value)
        elif isinstance(default, bool):
            if isinstance(value, bool):
                out[key] = value
        elif isinstance(default, (int, float)):
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[key] = value
        elif isinstance(default, str):
            if isinstance(value, str):
                out[key] = value
    return out


def _validate(data: Dict[str, Any]) -> Dict[str, Any]:
    if data["mode"] not in ("manual", "auto"):
        data["mode"] = "manual"
    if data["ui_theme"] not in ("system", "dark", "light"):
        data["ui_theme"] = "system"
    if data["speech_model"] not in ("auto", "both", "kroko", "parakeet", "vosk-small", "custom"):
        data["speech_model"] = "auto"
    if not 0 <= data["dedupe_window"] <= 3600:
        data["dedupe_window"] = DEFAULTS["dedupe_window"]
    return data


class Settings(object):
    def __init__(self, path: str = "") -> None:
        self.path = path or os.path.join(paths.config_dir(), FILENAME)
        self.data = copy.deepcopy(DEFAULTS)

    def load(self) -> "Settings":
        if not os.path.exists(self.path):
            return self
        try:
            with open(self.path, encoding="utf-8") as f:
                loaded = json.load(f)
            if not isinstance(loaded, dict):
                raise ValueError("settings root is not an object")
        except (OSError, ValueError) as exc:
            backup = "%s.corrupt-%d" % (self.path, int(time.time()))
            log.warning("settings file unreadable (%s); backing up to %s", exc, backup)
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            return self
        self.data = _validate(_merge(DEFAULTS, loaded))
        if "speech_model" not in loaded and self.data["model_path"]:
            self.data["speech_model"] = "custom"  # 1.0 settings that chose a model folder
        return self

    def save(self) -> None:
        tmp = self.path + ".tmp"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, sort_keys=True)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            os.replace(tmp, self.path)
        except OSError:
            log.exception("could not save settings to %s", self.path)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    @property
    def appearance(self) -> Appearance:
        return Appearance.from_dict(self.data.get("appearance"))

    @appearance.setter
    def appearance(self, value: Appearance) -> None:
        self.data["appearance"] = value.to_dict()
