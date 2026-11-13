#!/usr/bin/env python3
"""Download speech models into models/ (build time only; the app never downloads).

    python tools/fetch_model.py                     # Kroko (the default live model)
    python tools/fetch_model.py --name vosk-small   # classic Vosk model (Windows 7 fallback)
    python tools/fetch_model.py --name parakeet     # high-accuracy model (+ Silero VAD)
    python tools/fetch_model.py --name parakeet --pack dist/pack.zip   # build the model pack

Every download is verified against a pinned size and SHA-256. Each installed
model folder gets a ``biverse-model.json`` manifest that tells Biverse which
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
LLAMA = "https://github.com/ggml-org/llama.cpp/releases/download/b12366/"
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
DEFAULT = "kroko"
PACK_README = """Biverse high-accuracy speech model pack
=======================================

Contains NVIDIA Parakeet TDT 0.6B v2 (int8, CC-BY-4.0) and the Silero voice
activity detector (MIT), packaged for Biverse.

Install: in Biverse open Settings > Speech > "Install model pack..." and choose
this zip. It needs a 64-bit computer with about 6 GB of RAM or more.
"""


AI_PACK_README = """Biverse AI summary pack
=======================

Writes a short prose summary of the sermon on this computer (nothing is sent
anywhere). Contains Qwen2.5-1.5B-Instruct (Apache-2.0, GGUF q4_k_m) and the
llama.cpp b12366 program (MIT) for macOS (Apple Silicon and Intel), Windows
x64 and Linux x64.

Install: in Biverse open Settings > Speech > "Install model pack..." and choose
this zip. Then Service > Sermon summary > "Write AI summary". Needs a 64-bit
computer with about 8 GB of RAM; writing a summary takes up to a minute.
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


def install_ai_pack(dest: str, cache: str, force: bool = False, platforms=None) -> str:
    """Model + llama.cpp binaries (all platforms unless ``platforms`` given) into one folder."""
    spec = AI_PACK
    target = os.path.join(dest, spec["dir"])
    if os.path.isfile(os.path.join(target, "biverse-model.json")) and not force:
        print("%s already present" % target)
        return target
    os.makedirs(target, exist_ok=True)
    m = spec["model"]
    src = fetch_verified(m["url"], m["size"], m["sha256"], cache)
    shutil.copyfile(src, os.path.join(target, m["name"]))
    bins = {}
    for key, (url, size, sha) in spec["bins"].items():
        if platforms and key not in platforms:
            continue
        arc = fetch_verified(url, size, sha, cache)
        out = os.path.join(target, "bin", key)
        if os.path.isdir(out):
            shutil.rmtree(out)
        os.makedirs(out)
        if arc.endswith(".zip"):
            with zipfile.ZipFile(arc) as zf:
                for member in zf.infolist():
                    name = member.filename
                    if name.endswith("/") or ".." in name.split("/"):
                        continue
                    with zf.open(member) as fsrc, open(os.path.join(out, os.path.basename(name)), "wb") as fdst:
                        shutil.copyfileobj(fsrc, fdst)
        else:
            with tarfile.open(arc, "r:*") as tf:
                for member in tf.getmembers():
                    if ".." in member.name.split("/"):
                        raise SystemExit("unexpected path in archive: %r" % member.name)
                    base = os.path.basename(member.name)
                    if member.issym():
                        link = os.path.join(out, base)
                        if not os.path.lexists(link):
                            os.symlink(os.path.basename(member.linkname), link)
                    elif member.isfile():
                        with tf.extractfile(member) as fsrc, open(os.path.join(out, base), "wb") as fdst:
                            shutil.copyfileobj(fsrc, fdst)
                        if member.mode & 0o111:
                            os.chmod(os.path.join(out, base), 0o755)
        exe = "llama-completion.exe" if key.startswith("win") else "llama-completion"
        if not os.path.isfile(os.path.join(out, exe)):
            raise SystemExit("%s missing from %s" % (exe, url))
        bins[key] = "bin/%s/%s" % (key, exe)
    manifest = dict(spec["manifest"], bin=bins)
    with open(os.path.join(target, "biverse-model.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print("installed %s (%s)" % (target, ", ".join(sorted(bins))))
    return target


def build_pack(target: str, out: str) -> None:
    """Zip an installed model folder as a Biverse model pack."""
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    base = os.path.basename(target.rstrip(os.sep))
    with open(os.path.join(target, "biverse-model.json"), encoding="utf-8") as f:
        engine = json.load(f).get("engine")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("README.txt", AI_PACK_README if engine == "llm" else PACK_README)
        for dirpath, _dirs, files in os.walk(target):
            for name in sorted(files):
                full = os.path.join(dirpath, name)
                zf.write(full, os.path.join(base, os.path.relpath(full, target)))
    print("wrote pack %s (%.0f MB)" % (out, os.path.getsize(out) / 1e6))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=DEFAULT,
                    help="comma-separated: %s, ai-summary" % ", ".join(sorted(MODELS)))
    ap.add_argument("--dest", default=os.path.join(ROOT, "models"))
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--zip", default="", help="install from this local archive instead of downloading")
    ap.add_argument("--pack", default="", help="also write a model-pack zip of the (single) model")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--platforms", default="", help="ai-summary only: comma-separated subset of "
                                                   "macos-arm64,macos-x64,linux-x64,win-x64")
    args = ap.parse_args(argv)
    names = [n.strip() for n in args.name.split(",") if n.strip()]
    for n in names:
        if n not in MODELS and n != "ai-summary":
            ap.error("unknown model %r" % n)
    plats = [x.strip() for x in args.platforms.split(",") if x.strip()] or None
    targets = [install_ai_pack(args.dest, args.cache, args.force, plats) if n == "ai-summary" else
               install(n, args.dest, args.cache, args.force, args.zip if len(names) == 1 else "") for n in names]
    if args.pack:
        if len(targets) != 1:
            ap.error("--pack needs exactly one model")
        build_pack(targets[0], args.pack)
    return 0


if __name__ == "__main__":
    sys.exit(main())
