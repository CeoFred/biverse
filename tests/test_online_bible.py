"""Online Bible versions (YouVersion Platform API), with a fake API: no network."""

from __future__ import annotations

import json
import os

import pytest

from biverse import online_bible
from biverse.online_bible import OnlineBibles, parse_chapter

NIV_MAT17 = (
    '<div><div class="p"><span class="yv-v" v="1"></span><span class="yv-vlbl">1</span>After six days Jesus took '
    'with him Peter. </div><div class="p"><span class="yv-v" v="20"></span><span class="yv-vlbl">20</span>He '
    'replied, <span class="wj">“Because you have so little faith.”</span> <span class="yv-v" v="21">'
    '</span><span class="yv-vlbl">[21]</span></div><div class="p"><span class="yv-v" v="22"></span>'
    '<span class="yv-vlbl">22</span>When they came together in Galilee</div></div>')
PSALM3 = (
    '<div><div class="d">A Psalm of David. When he fled from Absalom his son.</div><div class="q1">'
    '<span class="yv-v" v="1"></span><span class="yv-vlbl">1</span>O L<span class="sc">ord</span>, how my foes '
    'have increased!</div><div class="q2">How many rise up against me!</div><div class="qr">Selah</div></div>')
CROSSREF = ('<div class="p"><span class="yv-v" v="21"></span><span class="yv-vlbl">21</span>They were told, '
            '‘Do not commit murder. <span class="rq">(Exodus 20:13)</span> Anyone who murders will be judged.'
            '’</div><div class="p"><span class="sig">From Paul</span></div>')


def test_parse_chapter_splits_verses_and_drops_labels():
    v = parse_chapter(NIV_MAT17)
    assert v[1] == "After six days Jesus took with him Peter."
    assert v[20] == "He replied, “Because you have so little faith.”"
    assert v[21] == ""  # left out by the NIV: empty, like every other translation
    assert v[22] == "When they came together in Galilee"


def test_parse_chapter_drops_titles_cross_references_and_signatures():
    v = parse_chapter(PSALM3)
    assert v[1] == "O Lord, how my foes have increased! How many rise up against me! Selah"
    v = parse_chapter(CROSSREF)
    assert v[21] == "They were told, ‘Do not commit murder. Anyone who murders will be judged.’"


def test_fit_grid_appends_extra_verses_to_the_last_grid_verse():
    assert online_bible._fit_grid({1: "a", 2: "b", 3: "c"}, 2) == {1: "a", 2: "b c"}


class FakeApi(object):
    """Answers like api.youversion.com for one licensed and one free version."""

    def __init__(self):
        self.calls = []
        self.down = False
        self.key_ok = True

    def __call__(self, url, key, timeout):
        self.calls.append(url)
        if self.down:
            raise OSError("network is unreachable")
        if not self.key_ok or key != "good-key":
            return 401, None
        path = url.split("/v1", 1)[1]
        if path.startswith("/licenses"):
            return 200, {"data": [{"id": 1, "bible_ids": [3034]}, {"id": 2, "bible_ids": [111]}]}
        if path.startswith("/bibles?"):
            assert "language_ranges%5B%5D=en" in path
            return 200, {"data": [
                {"id": 111, "abbreviation": "NIV11", "localized_abbreviation": "NIV",
                 "localized_title": "New International Version", "copyright": "Copyright Biblica",
                 "language_tag": "en", "books": ["MAT", "JHN"]},
                {"id": 3034, "abbreviation": "BSB", "localized_abbreviation": "BSB",
                 "localized_title": "Berean Standard Bible", "copyright": None, "language_tag": "en",
                 "books": ["PSA", "MAT"]},
                {"id": 12, "abbreviation": "ASV", "localized_abbreviation": "ASV",
                 "localized_title": "American Standard Version", "copyright": "x", "language_tag": "en"},
            ], "next_page_token": None}
        if path.startswith("/bibles/111/passages/MAT.17"):
            return 200, {"id": "MAT.17", "content": NIV_MAT17}
        if path.startswith("/bibles/3034/passages/PSA.3"):
            return 200, {"id": "PSA.3", "content": PSALM3}
        if path.startswith("/bibles/"):
            return 404, None
        raise AssertionError(url)


class Clock(object):
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def api():
    return FakeApi()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def online(api, clock, tmp_path):
    o = OnlineBibles("good-key", str(tmp_path / "cache"), "en", fetch=api, clock=clock)
    assert o.refresh_versions()
    yield o
    o.close()


@pytest.fixture
def fresh_bible():
    from biverse.bible import Bible
    from tests.conftest import DB_PATH
    if not os.path.exists(DB_PATH):
        pytest.skip("data/bible.db not built")
    b = Bible(DB_PATH)
    yield b
    b.close()


def test_no_key_means_no_online_versions(api, tmp_path):
    o = OnlineBibles("", str(tmp_path), fetch=api)
    assert o.state == online_bible.NO_KEY
    assert not o.refresh_versions()
    assert o.versions == {} and api.calls == []


def test_bad_key_is_reported(api, tmp_path):
    o = OnlineBibles("wrong", str(tmp_path), fetch=api)
    assert not o.refresh_versions()
    assert o.state == online_bible.BAD_KEY


def test_version_list_is_saved_for_offline_starts(online, api, clock, tmp_path):
    assert set(online.versions) == {"NIV", "BSB", "ASV"}
    assert online.versions["BSB"].free and not online.versions["NIV"].free
    api.down = True
    again = OnlineBibles("good-key", str(tmp_path / "cache"), "en", fetch=api, clock=clock)
    assert set(again.versions) == {"NIV", "BSB", "ASV"}
    other_key = OnlineBibles("other-key", str(tmp_path / "cache"), "en", fetch=api, clock=clock)
    assert other_key.versions == {}  # the list belongs to the key it was fetched with


def test_licensed_text_is_kept_in_memory_only_for_an_hour(online, api, clock, tmp_path):
    assert online.chapter("NIV", 40, 17)[20].startswith("He replied")
    n = len(api.calls)
    assert online.chapter("NIV", 40, 17)  # from memory
    assert len(api.calls) == n
    assert not os.path.exists(str(tmp_path / "cache" / "online_free.db")) or \
        online._store().execute("SELECT COUNT(*) FROM chapters").fetchone()[0] == 0
    clock.t += online_bible.MEMORY_TTL + 1
    assert online.cached("NIV", 40, 17) is None


def test_free_text_is_stored_on_disk(online, api, clock, tmp_path):
    assert online.chapter("BSB", 19, 3)[1].startswith("O Lord")
    online.close()
    api.down = True
    again = OnlineBibles("good-key", str(tmp_path / "cache"), "en", fetch=api, clock=clock)
    clock.t += 10 * online_bible.MEMORY_TTL
    assert again.chapter("BSB", 19, 3)[1].startswith("O Lord")
    again.clear_cache()
    assert again.cached("BSB", 19, 3) is None
    again.close()


def test_a_failure_pauses_requests(online, api, clock):
    api.down = True
    assert online.chapter("NIV", 40, 17) is None
    assert online.state == online_bible.OFFLINE
    n = len(api.calls)
    assert online.chapter("NIV", 40, 17) is None
    assert len(api.calls) == n  # no second timeout while offline
    api.down = False
    clock.t += online_bible.RETRY_AFTER + 1
    assert online.chapter("NIV", 40, 17) is not None
    assert online.state == online_bible.ONLINE


def test_books_a_version_lacks_are_not_requested(online, api):
    n = len(api.calls)
    assert online.chapter("NIV", 1, 1) is None  # the fake NIV has only MAT and JHN
    assert len(api.calls) == n


def test_bible_lists_online_versions_after_local_ones(fresh_bible, online):
    fresh_bible.set_online(online)
    codes = [c for c, _n, _l in fresh_bible.translations()]
    assert codes[:len(fresh_bible.local_codes())] == fresh_bible.local_codes()
    assert "NIV" in codes and "BSB" in codes
    assert codes.count("ASV") == 1  # the local ASV wins
    assert fresh_bible.is_online("NIV") and not fresh_bible.is_online("ASV")
    assert fresh_bible.verse("NIV", 40, 17, 20).startswith("He replied")
    assert [v.verse for v in fresh_bible.verses("NIV", 40, 17, 19, 22)] == [20, 22]
    assert fresh_bible.search_code("NIV") == "KJV"


def test_bible_falls_back_when_offline(fresh_bible, online, api):
    fresh_bible.set_online(online)
    fresh_bible.fallback = "WEB"
    api.down = True
    assert fresh_bible.resolve("NIV", 40, 17) == "WEB"
    assert fresh_bible.resolve("KJV", 40, 17) == "KJV"
    assert fresh_bible.resolve("NOPE", 40, 17) == "WEB"
    fresh_bible.fallback = "missing"
    assert fresh_bible.resolve("NIV", 40, 17) == "KJV"


def test_slide_shows_the_fallback_translation(fresh_bible, online, api):
    from biverse.controller import Selection, SlideBuilder
    fresh_bible.set_online(online)
    b = SlideBuilder(fresh_bible)
    slide = b.slide(Selection(40, 17, 20, 20), "NIV")
    assert slide.translation == "NIV" and slide.text.startswith("He replied")
    missing = b.slide(Selection(40, 17, 21, 21), "NIV")
    assert "not included in the NIV" in missing.text
    online._mem.clear()
    api.down = True
    slide = b.slide(Selection(40, 17, 20, 20), "NIV")
    assert slide.translation == "KJV" and "unbelief" in slide.text


def test_versions_file_has_no_bible_text(online, tmp_path):
    online.chapter("NIV", 40, 17)
    with open(str(tmp_path / "cache" / "online_versions.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert "little faith" not in json.dumps(data)
    assert "good-key" not in json.dumps(data)
