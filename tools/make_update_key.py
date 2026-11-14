#!/usr/bin/env python3
"""Create the Ed25519 key pair that signs update manifests.

    python tools/make_update_key.py ~/biverse-update-key.txt

Writes the private key (64 hex characters) to the file given, readable only by
you, and prints the public key. Then:

1. store the private key as the repository secret ``UPDATE_SIGNING_KEY``:
   ``gh secret set UPDATE_SIGNING_KEY < ~/biverse-update-key.txt``
2. paste the public key into ``PUBLIC_KEY`` in ``biverse/updates.py``
3. keep the file somewhere safe (a password manager) and off this computer's
   synced folders. Losing it means shipping a release with a new public key
   before the next update can be signed; leaking it lets someone else sign
   updates, so rotate it the same way.
"""

from __future__ import annotations

import argparse
import binascii
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from biverse import ed25519  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("private_key_file", help="where to write the private key (must not exist)")
    args = ap.parse_args(argv)
    if os.path.exists(args.private_key_file):
        ap.error("%s exists; not overwriting a key" % args.private_key_file)
    secret = os.urandom(32)
    fd = os.open(args.private_key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(binascii.hexlify(secret).decode() + "\n")
    print("private key written to %s" % args.private_key_file)
    print("PUBLIC_KEY = \"%s\"" % binascii.hexlify(ed25519.public_key(secret)).decode())
    return 0


if __name__ == "__main__":
    sys.exit(main())
