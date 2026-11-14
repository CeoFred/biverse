from __future__ import annotations

import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "data", "bible.db")


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("BIVERSE_CONFIG_DIR", str(tmp_path / "config"))


@pytest.fixture(scope="session")
def bible():
    from biverse.bible import Bible
    if not os.path.exists(DB_PATH):
        if os.environ.get("BIVERSE_REQUIRE_DB"):
            pytest.fail("data/bible.db missing; run tools/build_bible_db.py")
        pytest.skip("data/bible.db not built (run tools/build_bible_db.py)")
    b = Bible(DB_PATH)
    yield b
    b.close()
