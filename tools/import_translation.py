#!/usr/bin/env python3
"""Import a translation you hold a licence for. See biverse/import_cli.py or
USER_GUIDE.md ("Adding a licensed translation").

    python tools/import_translation.py CODE "Full name" file.csv
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from biverse.import_cli import run  # noqa: E402,F401

if __name__ == "__main__":
    sys.exit(run())
