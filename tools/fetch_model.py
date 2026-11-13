#!/usr/bin/env python3
"""Download the Vosk speech model into models/ (build time only).

    python tools/fetch_model.py                 # default small English model
    python tools/fetch_model.py --zip model.zip # install from a local zip (offline)

The download is verified against a pinned size and SHA-256 before unzipping.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODELS = {
    "vosk-model-small-en-us-0.15": {
        "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip",
        "size": 41205931,
        "sha256": "30f26242c4eb449f948e42cb302dd7a686cb29a3423a8367f99ff41780942498",
    },
}
DEFAULT = "vosk-model-small-en-us-0.15"


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
            with urllib.request.urlopen(req, timeout=300) as resp, open(dest + ".part", "wb") as f:
                shutil.copyfileobj(resp, f, 1 << 20)
            os.replace(dest + ".part", dest)
            return
        except Exception as exc:
            last = exc
            print("  attempt %d failed: %s" % (attempt + 1, exc))
            time.sleep(2 ** attempt)
    raise SystemExit("download failed: %s (%s)" % (url, last))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=DEFAULT, choices=sorted(MODELS))
    ap.add_argument("--dest", default=os.path.join(ROOT, "models"))
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--zip", help="use this local zip instead of downloading")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    spec = MODELS[args.name]
    target = os.path.join(args.dest, args.name)
    if os.path.isdir(target) and not args.force:
        print("%s already present" % target)
        return 0
    zpath = args.zip or os.path.join(args.cache, args.name + ".zip")
    if not args.zip and not os.path.exists(zpath):
        os.makedirs(args.cache, exist_ok=True)
        print("downloading %s" % spec["url"])
        download(spec["url"], zpath)
    size = os.path.getsize(zpath)
    digest = sha256_file(zpath)
    if size != spec["size"] or digest != spec["sha256"]:
        raise SystemExit("checksum mismatch for %s: size %d sha256 %s" % (zpath, size, digest))
    os.makedirs(args.dest, exist_ok=True)
    with zipfile.ZipFile(zpath) as zf:
        for member in zf.namelist():
            norm = os.path.normpath(member)
            if norm.startswith("..") or os.path.isabs(norm) or not norm.startswith(args.name):
                raise SystemExit("unexpected path in zip: %r" % member)
        if os.path.isdir(target):
            shutil.rmtree(target)
        zf.extractall(args.dest)
    print("installed %s" % target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
