"""Optional AI-written sermon summary, fully offline.

The AI pack (``tools/fetch_model.py --name ai-summary --pack``) holds a small
instruction model (Qwen2.5 1.5B Instruct, Apache-2.0, GGUF) and llama.cpp's
``llama-completion`` program for each desktop platform. Biverse runs it as a
separate process (no Python dependencies, nothing leaves the computer).

The model never sees the whole sermon: the built-in summary picks the key
sentences and the scriptures first, which keeps the prompt small (fast on
modest laptops) and grounds the summary in what was actually said.
"""

from __future__ import annotations

import logging
import os
import platform
import stat
import struct
import subprocess
import sys
import tempfile
from typing import List, Optional, Tuple

from . import paths

log = logging.getLogger(__name__)

TIMEOUT = 600  # seconds


def platform_key() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    if sys.platform == "darwin":
        return "macos-" + arch
    if sys.platform == "win32":
        return "win-" + arch
    return "linux-" + arch


# Platforms the AI pack ships a llama.cpp program for (tools/fetch_model.py).
SUPPORTED = ("macos-arm64", "macos-x64", "win-x64", "linux-x64")
MACOS_MIN = (13, 3)  # deployment target of llama.cpp's macOS release builds


def unsupported_reason() -> str:
    """Why this computer cannot run the AI summary, or "" if it can."""
    if struct.calcsize("P") * 8 < 64:
        return "The AI summary needs the 64-bit version of Biverse on a 64-bit computer."
    if sys.platform == "win32":
        try:
            major = sys.getwindowsversion().major  # type: ignore[attr-defined]
        except AttributeError:
            major = 10
        if major < 10:
            return "The AI summary needs Windows 10 or later."
    key = platform_key()
    if key not in SUPPORTED:
        return "The AI summary is not available for this computer (%s)." % key
    return ""


def platform_warning() -> str:
    """A caution for computers that may be too old, or "" (the summary is still offered)."""
    if sys.platform == "darwin":
        ver = tuple(int(p) for p in (platform.mac_ver()[0] or "0").split(".")[:2] if p.isdigit())
        if ver and ver < MACOS_MIN:
            return "may not run before macOS %d.%d" % MACOS_MIN
    return ""


class AIPack(object):
    __slots__ = ("path", "model", "binary", "label")

    def __init__(self, path: str, model: str, binary: str, label: str) -> None:
        self.path, self.model, self.binary, self.label = path, model, binary, label


def find_pack() -> Optional[AIPack]:
    """The installed AI pack for this platform, or None."""
    from .recognizer import detect_model  # manifests are shared with the speech models
    dirs = [paths.user_models_dir()] + paths.model_search_dirs()
    for base in dirs:
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            info = detect_model(os.path.join(base, name))
            if info is None or info.engine != "llm":
                continue
            binary = (info.manifest.get("bin") or {}).get(platform_key(), "")
            model = info.file("model")
            exe = os.path.join(info.path, binary) if binary else ""
            if exe and os.path.isfile(exe) and os.path.isfile(model):
                ensure_executable(exe)
                return AIPack(info.path, model, exe, info.label)
    return None


def ensure_executable(path: str) -> None:
    """Zip files do not keep the executable bit; restore it (POSIX only)."""
    if os.name != "posix":
        return
    try:
        mode = os.stat(path).st_mode
        if not mode & stat.S_IXUSR:
            os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass


def build_prompt(scriptures: List[str], points: List[str], themes: List[str]) -> str:
    """Chat-formatted prompt (Qwen ChatML) asking for a short, faithful summary."""
    system = ("You summarise church sermons for the congregation. Use only what is in the notes. "
              "Do not add Bible verses that are not listed. Write plainly and warmly.")
    notes = ["Scriptures read: " + ("; ".join(scriptures) if scriptures else "none detected"),
             "Main themes: " + (", ".join(themes) if themes else "-"), "", "Key sentences from the sermon, in order:"]
    notes += ["- " + p for p in points]
    user = ("\n".join(notes) + "\n\nSummarise the message in your own words (do not copy the sentences). "
            "Use exactly this format:\nMain message: <one sentence>\n- <point>\n- <point>\n- <point>\n"
            "Application: <one sentence>\nNo more than 120 words.")
    return ("<|im_start|>system\n%s<|im_end|>\n<|im_start|>user\n%s<|im_end|>\n<|im_start|>assistant\n"
            % (system, user))


def _clean(out: str) -> str:
    for marker in ("[end of text]", "<|im_end|>", "<|endoftext|>"):
        out = out.split(marker)[0]
    return out.strip()


def generate(pack: AIPack, prompt: str, max_tokens: int = 320, threads: int = 0) -> str:
    """Run llama.cpp once and return the generated text."""
    threads = threads or max(1, min(8, (os.cpu_count() or 2) - 1))
    fd, prompt_file = tempfile.mkstemp(prefix="biverse-prompt-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(prompt)
    base = [pack.binary, "-m", pack.model, "-f", prompt_file, "-n", str(max_tokens), "-c", "4096",
            "--temp", "0.3", "-t", str(threads)]
    attempts = [base + ["--no-display-prompt", "-no-cnv", "--simple-io"], base + ["--no-display-prompt"], base]
    env = dict(os.environ)
    try:
        last = ""
        for args in attempts:
            try:
                proc = subprocess.run(args, capture_output=True, timeout=TIMEOUT,
                                      cwd=os.path.dirname(pack.binary), env=env,
                                      **_no_window())
            except subprocess.TimeoutExpired:
                raise RuntimeError("the AI summary took too long (over %d s)" % TIMEOUT)
            out = proc.stdout.decode("utf-8", "replace")
            err = proc.stderr.decode("utf-8", "replace")
            if proc.returncode == 0 and _clean(out):
                text = _clean(out)
                return text[len(prompt):].strip() if text.startswith(prompt[:40]) else text
            last = (err or out)[-600:]
            log.warning("llama.cpp attempt failed (%s): %s", proc.returncode, last)
        tail = last.strip().splitlines()
        raise RuntimeError("the AI summary could not run: %s" % (tail[-1] if tail else "unknown error"))
    finally:
        try:
            os.remove(prompt_file)
        except OSError:
            pass


def _no_window() -> dict:
    """Do not flash a console window on Windows (the app itself has none)."""
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


def summarise_ai(pack: AIPack, summary: dict) -> str:
    scriptures = [r for _t, r in summary.get("scriptures", [])]
    points = [s for _t, s in summary.get("key_points", [])]
    themes = list(summary.get("themes", []))
    if not points:
        raise RuntimeError("not enough of the sermon was heard to summarise")
    return generate(pack, build_prompt(scriptures, points, themes))


def describe(pack: Optional[AIPack]) -> Tuple[bool, str]:
    """(can run, note for the summary window)."""
    reason = unsupported_reason()
    if reason:
        return False, reason
    if pack is None:
        return False, "Download the AI summary in Settings \u2192 Models"
    warning = platform_warning()
    return True, pack.label + (" (%s)" % warning if warning else "")
