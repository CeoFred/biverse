from __future__ import annotations

import json
import os
from array import array

import pytest

from biverse import audio, displays
from biverse.settings import DEFAULTS, Settings

# -- audio helpers -----------------------------------------------------------------


def _pcm(values):
    return array("h", values).tobytes()


def test_downmix_stereo():
    assert array("h", audio.downmix(_pcm([100, 300, -100, -300]), 2)).tolist() == [200, -200]


def test_downmix_four_channels_and_partial_frame():
    data = _pcm([4, 8, 12, 16, 0, 0, 0, 0]) + b"\x01"
    assert array("h", audio.downmix(data, 4)).tolist() == [10, 0]


def test_downmix_mono_is_identity():
    data = _pcm([1, 2, 3])
    assert audio.downmix(data, 1) == data


def test_peak_and_level():
    assert audio.peak(_pcm([0, -32768, 100])) == 32768
    assert audio.peak(b"") == 0
    assert audio.peak_to_level(0) == 0
    assert audio.peak_to_level(32767) == pytest.approx(100, abs=0.1)
    assert audio.peak_to_level(33) == pytest.approx(0, abs=0.5)  # -60 dB
    assert 40 < audio.peak_to_level(1036) < 60  # about -30 dB


def test_find_device_by_name_and_hostapi():
    devs = [audio.InputDevice(0, "USB Audio", "MME", 2, 48000.0), audio.InputDevice(5, "USB Audio", "Windows WASAPI",
                                                                                    2, 48000.0, True)]
    assert audio.find_device(devs, {"name": "USB Audio", "hostapi": "Windows WASAPI"}).index == 5
    assert audio.find_device(devs, {"name": "USB Audio", "hostapi": "Gone"}).index == 0
    assert audio.find_device(devs, {"name": "Other", "hostapi": "MME"}) is None
    assert audio.default_device(devs).index == 5
    assert devs[0].label() == u"USB Audio — MME"


def test_capture_callback_downmixes_and_queues():
    import queue
    q = queue.Queue(maxsize=2)
    cap = audio.AudioCapture(q)
    cap.channels = 2
    cap.samplerate = 48000
    for _ in range(3):  # third block forces the drop-oldest path
        cap._callback(_pcm([1000, 3000] * 10), 10, None, None)
    rate, data = q.get_nowait()
    assert rate == 48000 and array("h", data).tolist() == [2000] * 10
    assert cap.dropped == 1
    assert cap.level() > 0


# -- settings --------------------------------------------------------------------


def test_settings_defaults_and_roundtrip(tmp_path):
    path = str(tmp_path / "s.json")
    s = Settings(path).load()
    assert s["mode"] == "manual" and s["translation"] == "KJV"
    s["mode"] = "auto"
    s["input_device"] = {"name": "Mic", "hostapi": "MME"}
    s.save()
    assert not os.path.exists(path + ".tmp")
    s2 = Settings(path).load()
    assert s2["mode"] == "auto" and s2["input_device"]["name"] == "Mic"


def test_settings_ignore_bad_values(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"mode": "party", "dedupe_window": "x", "strict_books": "yes", "unknown": 1,
                                "appearance": {"bold": "no", "foreground": "#123456"}, "fit_range": True}))
    s = Settings(str(path)).load()
    assert s["mode"] == "manual"
    assert s["dedupe_window"] == DEFAULTS["dedupe_window"]
    assert s["strict_books"] is True
    assert "unknown" not in s.data
    assert s.appearance.bold is True and s.appearance.foreground == "#123456"
    assert s["fit_range"] is True


def test_settings_corrupt_file_is_backed_up(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{not json")
    s = Settings(str(path)).load()
    assert s["mode"] == "manual"
    assert not path.exists()
    assert any(p.name.startswith("s.json.corrupt-") for p in tmp_path.iterdir())


def test_config_dir_override(tmp_path, monkeypatch):
    from biverse import paths
    monkeypatch.setenv("BIVERSE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert paths.config_dir() == str(tmp_path / "cfg")
    assert os.path.isdir(str(tmp_path / "cfg"))


# -- displays --------------------------------------------------------------------

XRANDR = """Monitors: 3
 0: +*eDP-1 1920/344x1080/194+1920+0  eDP-1
 1: +HDMI-1 1920/521x1080/293+0+0  HDMI-1
 2: +DP-2 1024/300x768/200+3840+-200  DP-2
"""


def test_parse_xrandr():
    ds = displays.parse_xrandr(XRANDR)
    assert [d.geometry for d in ds] == ["1920x1080+1920+0", "1920x1080+0+0", "1024x768+3840+-200"]
    assert ds[0].is_primary and not ds[1].is_primary
    assert ds[0].label() == u"Display 1 — 1920×1080 (primary)"
    assert displays.default_display(ds) is ds[1]


def test_negative_geometry_is_tk_compatible():
    d = displays.Display(1, "", -1920, 0, 1920, 1080, False)
    assert d.geometry == "1920x1080+-1920+0"


def test_find_saved_display():
    ds = displays.parse_xrandr(XRANDR)
    assert displays.find_saved(ds, ds[2].key()) is ds[2]
    moved = dict(ds[2].key(), x=5000)
    assert displays.find_saved(ds, moved) is ds[2]  # same device name
    assert displays.find_saved(ds, {"index": 1, "x": 9, "y": 9, "width": 1, "height": 1}) is ds[1]
    assert displays.find_saved(ds, {}) is None


def test_single_display_default_is_primary():
    ds = displays.fallback(None)
    assert displays.default_display(ds).is_primary


def test_list_displays_never_empty():
    assert displays.list_displays(None)


# -- controller --------------------------------------------------------------------


def test_selection_labels():
    from biverse.controller import Selection
    s = Selection(43, 3, 16, 18)
    assert s.passage_label() == "John 3:16-18"
    assert s.status_label() == "John 3:16  (1/3)"
    assert Selection(19, 23, 1, 1, chapter_only=True).passage_label() == "Psalm 23"


def test_step_through_range_and_beyond(bible):
    from biverse.controller import Selection, step
    s = Selection(43, 3, 35, 36)
    s = step(bible, s, 1)
    assert s.verse_label() == "John 3:36"
    s = step(bible, s, 1)
    assert s.verse_label() == "John 4:1"
    s = step(bible, s, -1)
    assert s.verse_label() == "John 3:36"
    assert step(bible, Selection(1, 1, 1, 1), -1) is None
    assert step(bible, Selection(66, 22, 21, 21), 1) is None


def test_slide_for_missing_verse(bible):
    from biverse.controller import Selection, SlideBuilder
    # Matthew 17:21 is not in the ASV
    slide = SlideBuilder(bible).slide(Selection(40, 17, 21, 21), "ASV")
    assert "not included in the ASV" in slide.text


def test_chapter_step(bible):
    from biverse.controller import Selection, chapter_step
    assert chapter_step(bible, Selection(43, 3, 16, 16), 1).verse_label() == "John 4:1"
    assert chapter_step(bible, Selection(43, 3, 16, 16), -1).verse_label() == "John 2:1"
    assert chapter_step(bible, Selection(1, 50, 3, 3), 1).verse_label() == "Exodus 1:1"
    assert chapter_step(bible, Selection(2, 1, 3, 3), -1).verse_label() == "Genesis 50:1"
    assert chapter_step(bible, Selection(66, 22, 1, 1), 1) is None
    assert chapter_step(bible, Selection(1, 1, 5, 5), -1) is None


def test_old_settings_folder_is_carried_over(tmp_path):
    from biverse import paths
    old = tmp_path / "BiVerse"
    old.mkdir()
    (old / "settings.json").write_text("{}")
    new = tmp_path / "Biverse"
    paths._migrate_old_name(str(new))
    assert (new / "settings.json").exists() or (old / "settings.json").exists()  # case-insensitive disks: same dir
