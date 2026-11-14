"""Idle screen: the timer, what the live screen shows, settings and pictures."""

from __future__ import annotations

import builtins

import pytest

from biverse import render, settings
from biverse.controller import IdleTimer, LiveState, Selection
from biverse.render import BLACK, BLANK, EMPTY, IDLE, TEXT, Appearance, Slide


class _Builder(object):
    def slide(self, sel, translation, fit_range=False, fits=None):
        return Slide(EMPTY) if sel is None else Slide(TEXT, "text", sel.verse_label())


# -- timer ----------------------------------------------------------------------------

def test_goes_idle_after_delay_and_comes_back_on_touch():
    t = IdleTimer("background", 30)
    t.touch(100.0)
    assert not t.tick(129.0, showing=True) and t.kind() == ""
    assert t.tick(130.0, showing=True) and t.kind() == IDLE
    assert not t.tick(131.0, showing=True)  # already idle: nothing to redraw
    assert t.touch(140.0) and t.kind() == ""  # the reading resumed
    assert not t.touch(141.0)
    assert not t.tick(170.0, showing=True) and t.tick(171.0, showing=True)


def test_reading_keeps_the_verse_up():
    t = IdleTimer("blank", 10)
    t.touch(0.0)
    for now in range(5, 60, 5):  # the follower hears more of the verse every 5 s
        t.touch(float(now))
        assert not t.tick(float(now) + 1, showing=True)
    assert t.tick(70.0, showing=True) and t.kind() == BLANK


def test_none_never_goes_idle():
    t = IdleTimer("none", 30)
    t.touch(0.0)
    assert not t.tick(1e6, showing=True) and t.kind() == ""
    assert IdleTimer("nonsense", 30).action == "none"


def test_nothing_live_or_covered_is_never_idle():
    t = IdleTimer("background", 30)
    t.touch(0.0)
    assert not t.tick(100.0, showing=False)
    # blank/black lifted at 100 s: the timer counts from then
    assert not t.tick(120.0, showing=True)
    assert t.tick(130.0, showing=True)
    assert t.tick(131.0, showing=False) and t.kind() == ""  # covered while idle: idle ends


def test_configure_restarts_the_timer():
    t = IdleTimer("background", 30)
    t.touch(0.0)
    assert t.tick(30.0, showing=True)
    assert t.configure("blank", 60, 31.0) and t.kind() == ""
    assert not t.tick(90.0, showing=True) and t.tick(91.0, showing=True) and t.kind() == BLANK


# -- live state -----------------------------------------------------------------------

def test_live_state_shows_idle_only_over_a_verse():
    live = LiveState()
    live.idle = IDLE
    assert live.slide(_Builder(), "KJV").kind != IDLE  # nothing live
    live.selection = Selection(43, 3, 16, 16)
    assert live.slide(_Builder(), "KJV").kind == IDLE
    live.idle = BLANK
    assert live.slide(_Builder(), "KJV").kind == BLANK
    live.cover = BLACK  # the operator's black screen wins
    assert live.slide(_Builder(), "KJV").kind == BLACK
    live.cover, live.idle = None, ""
    assert live.slide(_Builder(), "KJV").kind == TEXT


# -- settings -------------------------------------------------------------------------

def test_settings_defaults_and_validation(tmp_path):
    path = tmp_path / "s.json"
    s = settings.Settings(str(path)).load()
    assert s["idle_action"] == "none" and s["idle_delay"] == 30
    assert s.appearance.idle_background == "#000000" and s.appearance.idle_image == ""
    path.write_text('{"idle_action": "fireworks", "idle_delay": 1}')
    s = settings.Settings(str(path)).load()
    assert s["idle_action"] == "none" and s["idle_delay"] == 30


def test_appearance_round_trips_idle_fields():
    a = Appearance(idle_background="#123456", idle_image="/x.jpg")
    b = Appearance.from_dict(a.to_dict())
    assert (b.idle_background, b.idle_image) == ("#123456", "/x.jpg")
    assert Appearance.from_dict({"background": "#111111"}).idle_background == "#000000"  # older settings


# -- pictures -------------------------------------------------------------------------

PIL = pytest.importorskip("PIL.Image")


@pytest.mark.parametrize("fmt,ext", [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("GIF", "gif")])
def test_load_picture_formats(tmp_path, fmt, ext):
    path = str(tmp_path / ("p." + ext))
    PIL.new("RGB", (40, 20), (10, 200, 30)).save(path, fmt)
    im = render.load_picture(path)
    assert im.size == (40, 20) and im.mode == "RGB"


def test_cover_fills_and_crops_centre(tmp_path):
    im = PIL.new("RGB", (400, 100))
    im.paste((255, 0, 0), (150, 0, 250, 100))  # red band in the middle
    out = render.cover(im, 160, 90)
    assert out.size == (160, 90)
    assert out.getpixel((80, 45))[0] > 200  # the centre is kept
    assert out.getpixel((2, 45))[0] < 50


def test_huge_picture_is_shrunk_on_load(tmp_path):
    path = str(tmp_path / "big.jpg")
    PIL.new("RGB", (8000, 2000), (1, 2, 3)).save(path, "JPEG")
    im = render.load_picture(path)
    assert max(im.size) <= render.MAX_PICTURE_SIDE


def test_exif_rotation_is_applied(tmp_path):
    path = str(tmp_path / "rot.jpg")
    img = PIL.new("RGB", (40, 20))
    exif = img.getexif()
    exif[0x0112] = 6  # rotate 90 degrees when shown
    img.save(path, "JPEG", exif=exif)
    assert render.load_picture(path).size == (20, 40)


def test_unreadable_picture_is_none(tmp_path):
    path = tmp_path / "bad.jpg"
    path.write_bytes(b"not a picture")
    assert render.load_picture(str(path)) is None


def test_load_picture_caches_by_path_and_time(tmp_path):
    path = str(tmp_path / "p.png")
    PIL.new("RGB", (4, 4)).save(path)
    cache = {}
    a = render.load_picture(path, 1.0, cache)
    assert render.load_picture(path, 1.0, cache) is a
    assert render.load_picture(path, 2.0, cache) is not a  # the file changed


def test_without_pillow_falls_back(monkeypatch):
    real = builtins.__import__

    def no_pil(name, *args, **kwargs):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no Pillow")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pil)
    assert render.have_pillow() is False
    assert render.load_picture("/any.jpg") is None
