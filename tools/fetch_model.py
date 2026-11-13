#!/usr/bin/env python3
"""Download speech models into models/ (build time only; the app never downloads).

    python tools/fetch_model.py                     # Kroko (the default live model)
    python tools/fetch_model.py --name vosk-small   # classic Vosk model (Windows 7 fallback)
    python tools/fetch_model.py --name parakeet     # high-accuracy model (+ Silero VAD)
    python tools/fetch_model.py --name parakeet --pack dist/pack.zip   # build the model pack

Every download is verified against a pinned size and SHA-256. Each installed
model folder gets a ``biverse-model.json`` manifest that tells BiVerse which
engine runs it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"

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
DEFAULT = "kroko"
PACK_README = """BiVerse high-accuracy speech model pack
=======================================

Contains NVIDIA Parakeet TDT 0.6B v2 (int8, CC-BY-4.0) and the Silero voice
activity detector (MIT), packaged for BiVerse.

Install: in BiVerse open Settings > Speech > "Install model pack..." and choose
this zip. It needs a 64-bit computer with about 6 GB of RAM or more.
"""


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: str) -> None:
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "biverse-build"})
            with urllib.request.urlopen(req, timeout=600) as resp, open(dest + ".part", "wb") as f:
                shutil.copyfileobj(resp, f, 1 << 20)
            os.replace(dest + ".part", dest)
            return
        except Exception as exc:
            last = exc
            print("  attempt %d failed: %s" % (attempt + 1, exc))
            time.sleep(2 ** attempt)
    raise SystemExit("download failed: %s (%s)" % (url, last))


def fetch_verified(url: str, size: int, sha: str, cache: str) -> str:
    path = os.path.join(cache, os.path.basename(url))
    if not os.path.exists(path):
        os.makedirs(cache, exist_ok=True)
        print("downloading %s" % url)
        download(url, path)
    if os.path.getsize(path) != size or sha256_file(path) != sha:
        os.remove(path)
        raise SystemExit("checksum mismatch for %s (deleted, run again)" % path)
    return path


def _safe_members(names, top):
    for name in names:
        norm = os.path.normpath(name)
        if norm.startswith("..") or os.path.isabs(norm) or not (norm == top or norm.startswith(top + os.sep)):
            raise SystemExit("unexpected path in archive: %r" % name)


def install(name: str, dest: str, cache: str, force: bool = False, archive: str = "") -> str:
    spec = MODELS[name]
    target = os.path.join(dest, spec["dir"])
    if os.path.isdir(target) and os.path.exists(os.path.join(target, "biverse-model.json")) and not force:
        print("%s already present" % target)
        return target
    path = archive or fetch_verified(spec["url"], spec["size"], spec["sha256"], cache)
    if archive and (os.path.getsize(path) != spec["size"] or sha256_file(path) != spec["sha256"]):
        raise SystemExit("checksum mismatch for %s" % path)
    os.makedirs(dest, exist_ok=True)
    if os.path.isdir(target):
        shutil.rmtree(target)
    if path.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            _safe_members(zf.namelist(), spec["dir"])
            zf.extractall(dest)
    else:
        with tarfile.open(path, "r:*") as tf:
            members = tf.getmembers()
            _safe_members([m.name for m in members], spec["dir"])
            for m in members:
                if not (m.isfile() or m.isdir()):
                    raise SystemExit("unexpected entry type in archive: %r" % m.name)
            tf.extractall(dest, members=members)
    shutil.rmtree(os.path.join(target, "test_wavs"), ignore_errors=True)
    for extra in spec.get("extra", []):
        src = fetch_verified(extra["url"], extra["size"], extra["sha256"], cache)
        shutil.copyfile(src, os.path.join(target, extra["name"]))
    with open(os.path.join(target, "biverse-model.json"), "w", encoding="utf-8") as f:
        json.dump(spec["manifest"], f, indent=2)
    print("installed %s" % target)
    return target


def build_pack(target: str, out: str) -> None:
    """Zip an installed model folder as a BiVerse model pack."""
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    base = os.path.basename(target.rstrip(os.sep))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:  # ONNX weights barely compress
        zf.writestr("README.txt", PACK_README)
        for dirpath, _dirs, files in os.walk(target):
            for name in sorted(files):
                full = os.path.join(dirpath, name)
                zf.write(full, os.path.join(base, os.path.relpath(full, target)))
    print("wrote pack %s (%.0f MB)" % (out, os.path.getsize(out) / 1e6))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=DEFAULT, help="comma-separated: %s" % ", ".join(sorted(MODELS)))
    ap.add_argument("--dest", default=os.path.join(ROOT, "models"))
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--zip", default="", help="install from this local archive instead of downloading")
    ap.add_argument("--pack", default="", help="also write a model-pack zip of the (single) model")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    names = [n.strip() for n in args.name.split(",") if n.strip()]
    for n in names:
        if n not in MODELS:
            ap.error("unknown model %r" % n)
    targets = [install(n, args.dest, args.cache, args.force, args.zip if len(names) == 1 else "") for n in names]
    if args.pack:
        if len(targets) != 1:
            ap.error("--pack needs exactly one model")
        build_pack(targets[0], args.pack)
    return 0


if __name__ == "__main__":
    sys.exit(main())
