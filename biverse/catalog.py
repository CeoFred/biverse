"""Downloadable models: pinned sources and a verified, resumable installer.

Used by the app (Settings -> Models -> Download) and by ``tools/fetch_model.py``
at build time. Every file is checked against a pinned size and SHA-256 before
it is unpacked, archives may only contain regular files and folders (plus
symlinks inside llama.cpp's macOS archive), and a model is unpacked into a
staging folder and moved into place only when complete, so a cancelled or
failed download never leaves a half-installed model behind.

Downloads resume: an interrupted ``.part`` file is continued with an HTTP
Range request the next time.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import ssl
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from typing import Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
LLAMA = "https://github.com/ggml-org/llama.cpp/releases/download/b12366/"

MODELS = {
    "kroko": {
        "dir": "sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06",
        "url": SHERPA + "sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06.tar.bz2",
        "size": 57267600,
        "sha256": "c8676e5ff9ac2a85296e53ee0fd4d5fb1db6770e7a7647166eeafe349ade6834",
        "manifest": {"engine": "sherpa-online", "id": "kroko", "label": "Kroko (live)",
                     "encoder": "encoder.onnx", "decoder": "decoder.onnx", "joiner": "joiner.onnx",
                     "tokens": "tokens.txt", "licence": "CC-BY-SA (Banafo Kroko community model)"},
    },
    "parakeet": {
        "dir": "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8",
        "url": SHERPA + "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8.tar.bz2",
        "size": 482440461,
        "sha256": "6fc4426b54aa549a0019b8a75b8dea59164e71790a37ac56a045ad57f915f714",
        "extra": [{"url": SHERPA + "silero_vad.onnx", "name": "silero_vad.onnx", "size": 643854,
                   "sha256": "9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6"}],
        "manifest": {"engine": "sherpa-offline", "id": "parakeet", "label": "Parakeet (high accuracy)",
                     "model_type": "nemo_transducer", "encoder": "encoder.int8.onnx",
                     "decoder": "decoder.int8.onnx", "joiner": "joiner.int8.onnx", "tokens": "tokens.txt",
                     "vad": "silero_vad.onnx", "min_ram_gb": 6,
                     "licence": "CC-BY-4.0 (NVIDIA parakeet-tdt-0.6b-v2); Silero VAD MIT"},
    },
    "vosk-small": {
        "dir": "vosk-model-small-en-us-0.15",
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "size": 41205931,
        "sha256": "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498",
        "manifest": {"engine": "vosk", "id": "vosk-small", "label": "Vosk small (classic)",
                     "licence": "Apache-2.0"},
    },
}

AI_PACK = {
    "dir": "biverse-ai-summary-qwen2.5-1.5b",
    "model": {"url": "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/"
                     "qwen2.5-1.5b-instruct-q4_k_m.gguf",
              "name": "qwen2.5-1.5b-instruct-q4_k_m.gguf", "size": 1117320736,
              "sha256": "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"},
    # llama.cpp b12366 one-shot generator for each desktop platform
    "bins": {
        "macos-arm64": (LLAMA + "llama-b12366-bin-macos-arm64.tar.gz", 16914794,
                        "6263965248c6c17b942eee1d91d9f810566d2ed1a7ec884130deb2339baee842"),
        "macos-x64": (LLAMA + "llama-b12366-bin-macos-x64.tar.gz", 12664866,
                      "3f4ef9c548902b23661f1b3c4e9f2db8d81e4755932dd58422a83c8eaabe90b7"),
        "linux-x64": (LLAMA + "llama-b12366-bin-ubuntu-x64.tar.gz", 23332283,
                      "60c318605a52ad7b15640cae72d6cb6b84b9737d4322be84f4a8e4bde699c1d7"),
        "win-x64": (LLAMA + "llama-b12366-bin-win-cpu-x64.zip", 25116739,
                    "b6b83e46546c04af52a700ea09638201493448cf52de207b2efefc1cecab625e"),
    },
    "manifest": {"engine": "llm", "id": "ai-summary", "label": "AI summary (Qwen2.5 1.5B)",
                 "model": "qwen2.5-1.5b-instruct-q4_k_m.gguf", "min_ram_gb": 8,
                 "licence": "Qwen2.5-1.5B-Instruct Apache-2.0; llama.cpp MIT"},
}

NAMES = sorted(MODELS) + ["ai-summary"]

# progress(done_bytes, total_bytes, stage); stage is "download", "check", "unpack" or "done"
Progress = Callable[[int, int, str], None]

CHUNK = 1 << 16
TIMEOUT = 60  # seconds without data before a read gives up


class Cancelled(Exception):
    """The user cancelled the download."""


class DownloadError(Exception):
    """A download or install failed; the message is shown to the user."""


# -- what a model needs --------------------------------------------------------------------

def files_for(name: str, platforms: Optional[List[str]] = None) -> List[Tuple[str, int, str]]:
    """(url, size, sha256) of every file ``name`` needs."""
    if name == "ai-summary":
        m = AI_PACK["model"]
        files = [(m["url"], m["size"], m["sha256"])]
        for key, (url, size, sha) in sorted(AI_PACK["bins"].items()):
            if platforms is None or key in platforms:
                files.append((url, size, sha))
        return files
    spec = MODELS[name]
    return [(spec["url"], spec["size"], spec["sha256"])] + [
        (e["url"], e["size"], e["sha256"]) for e in spec.get("extra", [])]


def download_size(name: str, platforms: Optional[List[str]] = None) -> int:
    return sum(size for _u, size, _s in files_for(name, platforms))


def target_dir(name: str) -> str:
    return AI_PACK["dir"] if name == "ai-summary" else MODELS[name]["dir"]


# -- downloading ---------------------------------------------------------------------------

def sha256_file(path: str, cancel: Optional[threading.Event] = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            h.update(chunk)
    return h.hexdigest()


def _ssl_context() -> ssl.SSLContext:
    """System certificates plus certifi's (python.org's macOS Python has no system store)."""
    ctx = ssl.create_default_context()
    try:
        import certifi  # bundled with the app (a dependency of requests)
        ctx.load_verify_locations(certifi.where())
    except Exception:  # certifi missing or unreadable: system store only
        pass
    return ctx


def _user_agent() -> str:
    try:
        from . import __version__
        return "Biverse/%s" % __version__
    except Exception:
        return "Biverse"


class _Meter(object):
    """Adds per-file progress to the bytes already done and reports overall progress."""

    def __init__(self, progress: Optional[Progress], total: int) -> None:
        self.progress, self.total, self.base = progress, total, 0

    def report(self, done_in_file: int, stage: str) -> None:
        if self.progress is not None:
            self.progress(min(self.total, self.base + done_in_file), self.total, stage)


def _fetch(url: str, part: str, size: int, meter: _Meter, cancel: Optional[threading.Event]) -> None:
    """Download ``url`` into ``part`` (resuming), until it is ``size`` bytes long."""
    have = os.path.getsize(part) if os.path.exists(part) else 0
    if have > size:
        os.remove(part)
        have = 0
    if have == size:
        return
    headers = {"User-Agent": _user_agent()}
    if have:
        headers["Range"] = "bytes=%d-" % have
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as resp:
        if have and getattr(resp, "status", 200) != 206:
            have = 0  # the server ignored the Range header: start again
        with open(part, "ab" if have else "wb") as f:
            done = have
            meter.report(done, "download")
            last = time.monotonic()
            while True:
                if cancel is not None and cancel.is_set():
                    raise Cancelled()
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last >= 0.1:
                    meter.report(done, "download")
                    last = now
    if os.path.getsize(part) < size:
        raise OSError("the connection closed early")


def fetch_verified(url: str, size: int, sha: str, cache: str, progress: Optional[Progress] = None,
                   cancel: Optional[threading.Event] = None, meter: Optional[_Meter] = None,
                   attempts: int = 4) -> str:
    """The verified file for ``url`` in ``cache``, downloading (and resuming) when needed."""
    meter = meter or _Meter(progress, size)
    path = os.path.join(cache, os.path.basename(url))
    os.makedirs(cache, exist_ok=True)
    if os.path.exists(path) and os.path.getsize(path) == size:
        meter.report(size, "check")
        if sha256_file(path, cancel) == sha:
            return path
        os.remove(path)
    part = path + ".part"
    last_error = None  # type: Optional[Exception]
    for attempt in range(attempts):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        try:
            _fetch(url, part, size, meter, cancel)
            last_error = None
            break
        except Cancelled:
            raise
        except (OSError, urllib.error.URLError, ssl.SSLError) as exc:
            last_error = exc
            log.warning("download attempt %d of %s failed: %s", attempt + 1, url, exc)
            if attempt + 1 < attempts:
                for _ in range(int(2 ** attempt * 10)):  # back off, but stay cancellable
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    time.sleep(0.1)
    if last_error is not None:
        raise DownloadError(_explain(last_error))
    meter.report(size, "check")
    if sha256_file(part, cancel) != sha:
        os.remove(part)
        raise DownloadError("the downloaded file was damaged (checksum mismatch). Please try again.")
    os.replace(part, path)
    return path


def _explain(exc: Exception) -> str:
    reason = getattr(exc, "reason", exc)
    if isinstance(exc, urllib.error.HTTPError):
        return "the download server answered %d %s. Please try again later." % (exc.code, exc.reason)
    if isinstance(reason, ssl.SSLError) or "CERTIFICATE" in str(reason).upper():
        return ("a secure connection could not be made (%s). Check the computer's date and time, or "
                "download the model pack from the Biverse website instead." % reason)
    return ("the download did not complete (%s). Check the internet connection and press Download "
            "again; it continues where it stopped." % reason)


# -- unpacking -----------------------------------------------------------------------------

def _check_members(names: List[str], top: str) -> None:
    for name in names:
        norm = os.path.normpath(name)
        if norm.startswith("..") or os.path.isabs(norm) or not (norm == top or norm.startswith(top + os.sep)):
            raise DownloadError("unexpected path in archive: %r" % name)


def _unpack_model(archive: str, top: str, dest: str) -> None:
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            _check_members(zf.namelist(), top)
            zf.extractall(dest)
        return
    with tarfile.open(archive, "r:*") as tf:
        members = tf.getmembers()
        _check_members([m.name for m in members], top)
        for m in members:
            if not (m.isfile() or m.isdir()):
                raise DownloadError("unexpected entry type in archive: %r" % m.name)
        for m in members:
            target = os.path.join(dest, m.name)
            if m.isdir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with tf.extractfile(m) as src, open(target, "wb") as out:  # type: ignore[union-attr]
                shutil.copyfileobj(src, out, 1 << 20)


def _unpack_flat(archive: str, out: str) -> None:
    """llama.cpp release archives: every file, flattened into ``out``."""
    os.makedirs(out, exist_ok=True)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                name = member.filename
                if name.endswith("/") or ".." in name.split("/"):
                    continue
                with zf.open(member) as fsrc, open(os.path.join(out, os.path.basename(name)), "wb") as fdst:
                    shutil.copyfileobj(fsrc, fdst)
        return
    with tarfile.open(archive, "r:*") as tf:
        for member in tf.getmembers():
            if ".." in member.name.split("/"):
                raise DownloadError("unexpected path in archive: %r" % member.name)
            base = os.path.basename(member.name)
            if not base:
                continue
            if member.issym():
                # dylib version links; flattened, so they may only point at a sibling file
                link = os.path.join(out, base)
                if not os.path.lexists(link):
                    os.symlink(os.path.basename(member.linkname), link)
            elif member.isfile():
                with tf.extractfile(member) as fsrc, open(os.path.join(out, base), "wb") as fdst:  # type: ignore
                    shutil.copyfileobj(fsrc, fdst)
                if member.mode & 0o111:
                    os.chmod(os.path.join(out, base), 0o755)


# -- installing ----------------------------------------------------------------------------

def is_installed(name: str, dest: str) -> bool:
    return os.path.isfile(os.path.join(dest, target_dir(name), "biverse-model.json"))


def check_disk_space(name: str, dest: str, cache: str, platforms: Optional[List[str]] = None) -> None:
    """Raise DownloadError if there is clearly not enough free space."""
    need = download_size(name, platforms) * 2 + (200 << 20)
    probe = dest if os.path.isdir(dest) else os.path.dirname(os.path.abspath(dest))
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return
    if free < need:
        raise DownloadError("there is not enough free disk space: %.1f GB is needed and %.1f GB is free."
                            % (need / 1e9, free / 1e9))


def install(name: str, dest: str, cache: str, force: bool = False, archive: str = "",
            progress: Optional[Progress] = None, cancel: Optional[threading.Event] = None,
            platforms: Optional[List[str]] = None, keep_cache: bool = True) -> str:
    """Download (or use ``archive``), verify and install ``name`` under ``dest``; return its folder.

    ``platforms`` (AI summary only) limits the llama.cpp programs to those platform keys.
    ``keep_cache=False`` deletes the downloaded archives once installed (the app does this).
    """
    if name not in NAMES:
        raise DownloadError("unknown model %r" % name)
    top = target_dir(name)
    final = os.path.join(dest, top)
    if is_installed(name, dest) and not force:
        if progress is not None:
            progress(1, 1, "done")
        return final
    files = files_for(name, platforms)
    meter = _Meter(progress, sum(size for _u, size, _s in files))
    os.makedirs(dest, exist_ok=True)
    fetched = []  # type: List[str]

    def get(url: str, size: int, sha: str) -> str:
        path = fetch_verified(url, size, sha, cache, cancel=cancel, meter=meter)
        meter.base += size
        fetched.append(path)
        return path

    staging = tempfile.mkdtemp(prefix=".install-", dir=dest)
    try:
        target = os.path.join(staging, top)
        if name == "ai-summary":
            m = AI_PACK["model"]
            model = get(m["url"], m["size"], m["sha256"])
            bins = {}
            programs = []
            for key, (url, size, sha) in sorted(AI_PACK["bins"].items()):
                if platforms is not None and key not in platforms:
                    continue
                programs.append((key, get(url, size, sha)))
            meter.report(0, "unpack")
            os.makedirs(target)
            for key, arc in programs:
                out = os.path.join(target, "bin", key)
                _unpack_flat(arc, out)
                exe = "llama-completion.exe" if key.startswith("win") else "llama-completion"
                if not os.path.isfile(os.path.join(out, exe)):
                    raise DownloadError("%s is missing from the llama.cpp download for %s" % (exe, key))
                bins[key] = "bin/%s/%s" % (key, exe)
            if keep_cache:
                shutil.copyfile(model, os.path.join(target, m["name"]))
            else:
                os.replace(model, os.path.join(target, m["name"]))
            manifest = dict(AI_PACK["manifest"], bin=bins)
        else:
            spec = MODELS[name]
            if archive:
                if os.path.getsize(archive) != spec["size"] or sha256_file(archive, cancel) != spec["sha256"]:
                    raise DownloadError("checksum mismatch for %s" % archive)
                path = archive
                meter.base += spec["size"]
            else:
                path = get(spec["url"], spec["size"], spec["sha256"])
            extras = [(e["name"], get(e["url"], e["size"], e["sha256"])) for e in spec.get("extra", [])]
            meter.report(0, "unpack")
            _unpack_model(path, top, staging)
            shutil.rmtree(os.path.join(target, "test_wavs"), ignore_errors=True)
            for fname, src in extras:
                shutil.copyfile(src, os.path.join(target, fname))
            manifest = spec["manifest"]
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        with open(os.path.join(target, "biverse-model.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        if os.path.isdir(final):
            shutil.rmtree(final)
        os.replace(target, final)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    if not keep_cache:
        for path in fetched:
            try:
                os.remove(path)
            except OSError:
                pass
    if progress is not None:
        progress(meter.total, meter.total, "done")
    log.info("installed %s into %s", name, final)
    return final


def default_cache() -> str:
    from . import paths
    return os.path.join(paths.config_dir(), "downloads")


def manifests() -> Dict[str, dict]:
    out = {n: s["manifest"] for n, s in MODELS.items()}
    out["ai-summary"] = AI_PACK["manifest"]
    return out
