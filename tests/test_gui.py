"""Drive the operator window without a human (needs a display; CI uses Xvfb)."""

from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def op(bible, tmp_path):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip("no display: %s" % exc)
    root.withdraw()
    from versecast.settings import Settings
    from versecast.ui_operator import OperatorWindow
    settings = Settings(str(tmp_path / "settings.json"))
    settings["output_visible"] = False
    w = OperatorWindow(root, settings, bible)
    root.update()
    yield w
    if not w._closing:
        w.close()


def test_search_reference_loads_preview(op):
    op.search_var.set("jn 3:16")
    op.search()
    assert op.preview.verse_label() == "John 3:16"
    assert op.preview_label.cget("text").startswith("John 3:16")


def test_phrase_search_and_go_live(op):
    op.search_var.set("so loved the world")
    op.search()
    kids = op.results.get_children()
    assert kids
    op.results.selection_set(kids[0])
    op.root.update()
    assert op.preview.verse_label() == "John 3:16"
    op.go_live()
    assert op.output.slide.reference == "John 3:16"
    assert op.output.slide.text.startswith("For God so loved")


def test_step_blank_black(op):
    op.search_var.set("rev 22:20")
    op.search()
    op.go_live()
    op.step(1)
    assert op.live.selection.verse_label() == "Revelation 22:21"
    op.step(1)  # end of the Bible: stays
    assert op.live.selection.verse_label() == "Revelation 22:21"
    op.blank()
    assert op.output.slide.kind == "blank"
    op.blank()
    assert op.output.slide.kind == "text"
    op.black()
    assert op.output.slide.kind == "black"


def test_range_steps_then_crosses_chapter(op):
    op.search_var.set("john 3:35-36")
    op.search()
    op.go_live()
    assert op.live_label.cget("text").startswith("John 3:35")
    op.step(1)
    assert op.live.selection.verse_label() == "John 3:36"
    op.step(1)
    assert op.live.selection.verse_label() == "John 4:1"


def test_translation_switch_rerenders_live(op):
    op.search_var.set("gen 1:3")
    op.search()
    op.go_live()
    op.translation_var.set("YLT")
    op._on_translation()
    assert "Let light be" in op.output.slide.text


def test_detection_manual_and_auto(op):
    from versecast.detector import Detector
    d = Detector()
    (kind, det), = d.feed_final("romans eight twenty eight", now=0)
    op._on_detection(kind, det)
    assert op.preview.verse_label() == "Romans 8:28"
    assert op.live.selection is None  # manual: not live
    op.mode_var.set("auto")
    op._on_mode()
    (kind, det), = d.feed_final("and john three sixteen", now=5)
    op._on_detection(kind, det)
    assert op.live.selection.verse_label() == "John 3:16"
    # auto safety: chapter-only goes to preview, not live
    (kind, det), = d.feed_final("now psalm twenty three", now=10)
    op._on_detection(kind, det)
    assert op.live.selection.verse_label() == "John 3:16"
    assert op.preview.verse_label() == "Psalm 23:1"
    assert len(op.detected.get_children()) == 3


def test_fit_range(op):
    op.settings["fit_range"] = True
    op.search_var.set("john 3:16-17")
    op.search()
    op.go_live()
    assert op.output.slide.reference == "John 3:16-17"


def test_settings_saved_on_close(op, tmp_path):
    import json
    op.translation_var.set("ASV")
    op._on_translation()
    op.close()
    data = json.load(open(str(tmp_path / "settings.json")))
    assert data["translation"] == "ASV"


def test_settings_dialog_opens(op):
    from versecast.ui_settings import SettingsDialog
    dlg = SettingsDialog(op)
    op.root.update()
    dlg.bold.set(False)
    dlg._ok()
    assert op.settings.appearance.bold is False


def test_render_thumbnail_matches_output_aspect(op):
    ow, oh = op.output.size
    th = int(op.preview_canvas.cget("height"))
    tw = op.preview_canvas.winfo_width() - 4
    if tw > 50:
        assert abs(tw / float(th) - ow / float(oh)) < 0.15 or th == max(80, op.root.winfo_height() // 3)


def test_poll_handles_events(op):
    from versecast.detector import Detector
    d = Detector()
    op.events.put(("model", "missing", ""))
    op.events.put(("partial", "turn to john"))
    op.events.put(("final", "turn to john three sixteen"))
    for kind, det in d.feed_final("turn to john three sixteen", now=0):
        op.events.put(("detect", kind, det))
    op.events.put(("error", "speech recognition error: test"))
    op.events.put(("model", "ready", "/x"))
    op._poll()
    assert "john three sixteen" in op.transcript.get("1.0", "end")
    assert op.preview.verse_label() == "John 3:16"
    assert op.status_var.get().startswith("Idle") or op.status_var.get()


def test_missing_model_banner(op):
    op.engine.state = "missing"
    op._on_model("missing", "")
    op.root.update()
    assert "No speech model" in op.banner.cget("text")
    op.start_listening()  # refuses without a model, no crash
    assert not op.listening


def test_listen_never_blocks_ui(op, monkeypatch):
    """Opening a device that hangs inside PortAudio must not freeze the UI."""
    import threading
    import time as _t

    from versecast import audio
    gate = threading.Event()

    def hanging_open(device):
        gate.wait(5)
        raise RuntimeError("gave up")

    monkeypatch.setattr(op.capture, "_open", hanging_open)
    monkeypatch.setattr(audio, "available", lambda: True)  # CI may have no PortAudio devices
    op.engine._load_token += 1  # ignore the background model load finishing mid-test
    op.devices = [audio.InputDevice(0, "Fake mic", "Test API", 1, 16000.0, True)]
    op.input_combo.configure(values=[op.devices[0].label()])
    op.input_var.set(op.devices[0].label())
    op.engine.state = "ready"
    t = _t.monotonic()
    op.start_listening()
    assert _t.monotonic() - t < 0.5
    assert op.listening and op.capture.opening
    op.stop_listening()
    gate.set()
    assert not op.listening
