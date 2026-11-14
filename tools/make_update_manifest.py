#!/usr/bin/env python3
"""Write the signed update manifest for a release (run by the release job).

    UPDATE_SIGNING_KEY=<hex> python tools/make_update_manifest.py --version 1.5.0 \\
        --dir release --repo CeoFred/biverse

Reads ``Biverse-<version>-<flavour>.zip`` files from ``--dir`` and writes
``latest.json`` and ``latest.json.sig`` (base64 Ed25519 signature of the exact
bytes of latest.json) next to them. The app downloads both from the latest
release and installs only what the signature and checksums vouch for.

Without ``UPDATE_SIGNING_KEY`` it prints a warning and writes nothing, so a
fork without the secret still releases (its builds just get no update offer).
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from biverse import ed25519  # noqa: E402


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(version: str, folder: str, repo: str) -> dict:
    pattern = re.compile(r"^Biverse-%s-([a-z0-9-]+)\.zip$" % re.escape(version))
    builds = {}
    for name in sorted(os.listdir(folder)):
        m = pattern.match(name)
        if not m:
            continue
        path = os.path.join(folder, name)
        builds[m.group(1)] = {
            "url": "https://github.com/%s/releases/download/v%s/%s" % (repo, version, name),
            "size": os.path.getsize(path),
            "sha256": sha256(path),
        }
    if not builds:
        raise SystemExit("no Biverse-%s-*.zip in %s" % (version, folder))
    return {
        "version": version,
        "published": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "notes_url": "https://github.com/%s/releases/tag/v%s" % (repo, version),
        "builds": builds,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--version", required=True)
    ap.add_argument("--dir", required=True)
    ap.add_argument("--repo", required=True)
    args = ap.parse_args(argv)
    key = os.environ.get("UPDATE_SIGNING_KEY", "").strip()
    if not key:
        print("::warning::UPDATE_SIGNING_KEY is not set: no update manifest, the app will not offer this release")
        return 0
    secret = binascii.unhexlify(key)
    doc = manifest(args.version, args.dir, args.repo)
    data = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    sig = base64.b64encode(ed25519.sign(secret, data))
    ed25519.verify(ed25519.public_key(secret), data, base64.b64decode(sig))
    with open(os.path.join(args.dir, "latest.json"), "wb") as f:
        f.write(data)
    with open(os.path.join(args.dir, "latest.json.sig"), "wb") as f:
        f.write(sig + b"\n")
    print(data.decode())
    print("signed with public key %s" % binascii.hexlify(ed25519.public_key(secret)).decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
