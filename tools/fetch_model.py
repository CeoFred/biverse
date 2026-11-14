#!/usr/bin/env python3
"""Download speech models into models/ at build time, and build model packs.

    python tools/fetch_model.py                     # Kroko (the default live model)
    python tools/fetch_model.py --name vosk-small   # classic Vosk model (Windows 7 fallback)
    python tools/fetch_model.py --name parakeet     # high-accuracy model (+ Silero VAD)
    python tools/fetch_model.py --name parakeet --pack dist/pack.zip   # build the model pack

The sources, checksums and installer live in ``biverse/catalog.py``, shared
with the app's Settings -> Models downloads. Every download is verified against
a pinned size and SHA-256. Each installed model folder gets a
``biverse-model.json`` manifest that tells Biverse which engine runs it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from biverse.catalog import AI_PACK, MODELS, Cancelled, DownloadError  # noqa: E402,F401
from biverse import catalog  # noqa: E402

DEFAULT = "kroko"
PACK_README = """Biverse high-accuracy speech model pack
=======================================

Contains NVIDIA Parakeet TDT 0.6B v2 (int8, CC-BY-4.0) and the Silero voice
activity detector (MIT), packaged for Biverse.

Install: in Biverse open Settings > Models > "Install from a file..." and choose
this zip. It needs a 64-bit computer with about 6 GB of RAM or more.
"""


AI_PACK_README = """Biverse AI summary pack
=======================

Writes a short prose summary of the sermon on this computer (nothing is sent
anywhere). Contains Qwen2.5-1.5B-Instruct (Apache-2.0, GGUF q4_k_m) and the
llama.cpp b12366 program (MIT) for macOS (Apple Silicon and Intel), Windows
x64 and Linux x64.

Install: in Biverse open Settings > Models > "Install from a file..." and choose
this zip. Then Service > Sermon summary > "Write AI summary". Writing a summary
takes up to a minute and needs about 8 GB of RAM.

Works on: Windows 10/11 64-bit, macOS (Apple Silicon or Intel; 13.3+
recommended) and Linux x64. Does NOT work on Windows 7/8, 32-bit Windows or
ARM Windows/Linux.
"""


def _printer():
    state = {"pct": -1, "stage": ""}

    def progress(done, total, stage):
        pct = int(done * 100 / total) if total else 100
        if stage != state["stage"] or pct >= state["pct"] + 10 or stage == "done":
            print("  %-8s %3d%%  (%.0f / %.0f MB)" % (stage, pct, done / 1e6, total / 1e6))
            state["pct"], state["stage"] = pct, stage
    return progress


def install(name: str, dest: str, cache: str, force: bool = False, archive: str = "") -> str:
    try:
        target = catalog.install(name, dest, cache, force=force, archive=archive, progress=_printer())
    except DownloadError as exc:
        raise SystemExit("%s: %s" % (name, exc))
    print("installed %s" % target)
    return target


def install_ai_pack(dest: str, cache: str, force: bool = False, platforms=None) -> str:
    """Model + llama.cpp binaries (all platforms unless ``platforms`` given) into one folder."""
    try:
        target = catalog.install("ai-summary", dest, cache, force=force, progress=_printer(),
                                 platforms=platforms)
    except DownloadError as exc:
        raise SystemExit("ai-summary: %s" % exc)
    print("installed %s" % target)
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
