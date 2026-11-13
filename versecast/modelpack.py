"""Install a speech model pack (a zip made by tools/fetch_model.py --pack).

The pack holds one model folder with a ``biverse-model.json`` manifest. It is
checked before anything is extracted, unpacked into a temporary folder next to
the destination and then moved into place, so a half-copied pack never looks
like a usable model. Installed packs live in the user's settings folder and
survive app updates.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from typing import Optional

from . import paths
from .recognizer import ModelInfo, detect_model

MAX_PACK_BYTES = 4 * 1024 ** 3


class PackError(Exception):
    pass


def inspect(zip_path: str) -> str:
    """Validate a pack; return the name of its model folder."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackError("not a zip file: %s" % exc)
    with zf:
        names = zf.namelist()
        total = sum(i.file_size for i in zf.infolist())
        if total > MAX_PACK_BYTES:
            raise PackError("pack is unexpectedly large")
        tops = set()
        for n in names:
            norm = os.path.normpath(n)
            if norm.startswith("..") or os.path.isabs(norm) or n.startswith(("/", "\\")):
                raise PackError("unsafe path in pack: %r" % n)
            parts = n.replace("\\", "/").split("/")
            if len(parts) > 1:
                tops.add(parts[0])
        manifests = [n for n in names if n.count("/") == 1 and n.endswith("/biverse-model.json")]
        if len(manifests) != 1 or len(tops) != 1:
            raise PackError("this is not a BiVerse speech model pack (expected one model folder with "
                            "biverse-model.json)")
        try:
            manifest = json.loads(zf.read(manifests[0]).decode("utf-8"))
        except ValueError:
            raise PackError("the pack's manifest is damaged")
        if manifest.get("engine") not in ("sherpa-online", "sherpa-offline", "vosk"):
            raise PackError("unknown engine in pack: %r" % manifest.get("engine"))
        return manifests[0].split("/")[0]


def install(zip_path: str, dest: Optional[str] = None) -> ModelInfo:
    dest = dest or paths.user_models_dir()
    folder = inspect(zip_path)
    os.makedirs(dest, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix=".pack-", dir=dest)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = [n for n in zf.namelist() if n.startswith(folder + "/")]
            zf.extractall(tmp, members=members)
        info = detect_model(os.path.join(tmp, folder))
        if info is None:
            raise PackError("the pack's model files are incomplete")
        final = os.path.join(dest, folder)
        if os.path.isdir(final):
            shutil.rmtree(final)
        os.replace(os.path.join(tmp, folder), final)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    info = detect_model(final)
    assert info is not None
    return info
