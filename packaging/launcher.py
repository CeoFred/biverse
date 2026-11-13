"""PyInstaller entry point (a script, so that ``versecast`` is imported as a package)."""

from __future__ import annotations

import sys

from versecast.app import main

if __name__ == "__main__":
    sys.exit(main())
