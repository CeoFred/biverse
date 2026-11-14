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
    from biverse.settings import Settings
    from biverse.ui_operator import OperatorWindow
    settings = Settings(str(tmp_path / "settings.json"))
    settings["output_visible"] = False
    settings["operator_fullscreen"] = False
    # Don't load real speech models (up to ~2 GB) in UI tests
    settings["speech_model"] = "custom"
    settings["model_path"] = str(tmp_path / "no-model")
    w = OperatorWindow(root, settings, bible)
    root.update()
    yield w
    if not w._closing:
        w.close()
    bible.set_online(None)  # the Bible fixture is shared by the whole session
    bible.fallback = ""


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
    from biverse.detector import Detector
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
    from biverse.ui_settings import SettingsDialog
    dlg = SettingsDialog(op)
    op.root.update()
    dlg.bold.set(False)
    dlg._ok()
    assert op.settings.appearance.bold is False


def test_settings_models_tab_shows_every_model(op):
    op.open_settings(tab="models")
    op.root.update()
    dlg = op.settings_dialog
    assert dlg is not None and dlg.nb.select() == str(dlg.models_tab)
    assert set(dlg.model_rows) == {"kroko", "parakeet", "vosk-small", "ai-summary"}
    for row in dlg.model_rows.values():
        assert row.button.cget("text") in ("Download", "Installed", "Not available")
    op.open_settings()  # a second open raises the same window
    assert op.settings_dialog is dlg
    dlg._ok()
    assert op.settings_dialog is None


def test_download_progress_shown_in_models_tab(op, monkeypatch):
    from biverse import downloads

    class FakeJob(downloads.Job):
        pass

    job = FakeJob(downloads.item("vosk-small"))
    job.update(10 * 10 ** 6, 41 * 10 ** 6, "download")
    monkeypatch.setattr(op.downloads, "job", lambda item_id: job if item_id == "vosk-small" else None)
    op.open_settings(tab="models")
    op.root.update()
    row = op.settings_dialog.model_rows["vosk-small"]
    row.tick()
    op.root.update()
    assert row.button.cget("text") == "Cancel"
    assert row.progress_text.cget("text").startswith("Downloading 10 MB of 41 MB (24%)")
    assert int(float(row.bar.cget("value"))) == 243
    job.state = "done"
    op.settings_dialog._ok()


def test_operator_full_screen_toggle_is_remembered(op):
    op.set_fullscreen(True)
    assert op.settings["operator_fullscreen"] is True and op.fullscreen_var.get() is True
    op.toggle_fullscreen()
    assert op.settings["operator_fullscreen"] is False and op.fullscreen_var.get() is False


def test_finished_download_reloads_when_automatic(op, monkeypatch):
    from biverse import downloads
    calls = []
    monkeypatch.setattr(op, "reload_model", lambda: calls.append("reload"))
    op.settings["speech_model"] = "auto"
    job = downloads.Job(downloads.item("vosk-small"))
    job.state = "done"
    op._on_download(job)
    assert calls == ["reload"]
    op.listening = True
    op._on_download(job)
    assert calls == ["reload"] and op._reload_after_listening  # waits until listening stops
    op.listening = False
    op._reload_after_listening = False


def test_render_thumbnail_matches_output_aspect(op):
    ow, oh = op.output.size
    th = int(op.preview_canvas.cget("height"))
    tw = op.preview_canvas.winfo_width() - 4
    if tw > 50:
        assert abs(tw / float(th) - ow / float(oh)) < 0.15 or th == max(80, op.root.winfo_height() // 3)


def test_poll_handles_events(op):
    from biverse.detector import Detector
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

    from biverse import audio
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


def _show(op, text):
    op.search_var.set(text)
    op.search()
    op.go_live()


def test_voice_next_verse_moves_live_in_auto_mode(op):
    op.mode_var.set("auto")
    op._on_mode()
    _show(op, "john 3:16")
    op._on_command("next_verse", "main", 1.0, "next verse")
    assert op.live.selection.verse_label() == "John 3:17"
    op._on_command("prev_verse", "main", 5.0, "go back")
    assert op.live.selection.verse_label() == "John 3:16"
    op._on_command("next_chapter", "main", 9.0, "next chapter")
    assert op.live.selection.verse_label() == "John 4:1"


def test_voice_command_goes_to_preview_in_manual_mode(op):
    _show(op, "john 3:16")
    op._on_command("next_verse", "main", 1.0, "next verse")
    assert op.live.selection.verse_label() == "John 3:16"
    assert op.preview.verse_label() == "John 3:17"


def test_voice_command_heard_by_both_models_counts_once(op):
    op.mode_var.set("auto")
    op._on_mode()
    _show(op, "john 3:16")
    op._on_command("next_verse", "live", 1.0, "next verse")
    op._on_command("next_verse", "main", 1.8, "Next verse.")  # Parakeet's copy of the same words
    assert op.live.selection.verse_label() == "John 3:17"
    op._on_command("next_verse", "main", 6.0, "next verse")  # a genuine second command
    assert op.live.selection.verse_label() == "John 3:18"


def test_move_to_verse_uses_live_chapter(op):
    op.mode_var.set("auto")
    op._on_mode()
    _show(op, "rom 8:28")
    op._on_command("next_chapter", "main", 1.0, "next chapter")  # now Romans 9:1
    events = op.detector.feed_final("move to verse eight")
    (kind, det), = events
    op._on_detection(kind, det)
    assert op.live.selection.verse_label() == "Romans 9:8"


# -- phase 1: intents -------------------------------------------------------------

def _say(op, text, t, channel="main"):
    from biverse.commands import parse_intent
    intent = parse_intent(text)
    assert intent is not None, text
    op._on_command(intent, channel, t, text)


def _auto(op):
    op.mode_var.set("auto")
    op._on_mode()


def test_intent_steps_with_counts(op):
    _auto(op)
    _show(op, "gen 10:3-10")
    _say(op, "go forward three verses", 1)
    assert op.live.selection.verse_label() == "Genesis 10:6"
    _say(op, "can we go back two verses", 5)
    assert op.live.selection.verse_label() == "Genesis 10:4"
    _say(op, "go back to where we started", 9)
    assert op.live.selection.verse_label() == "Genesis 10:3"


def test_intent_chapter_goto_same_book(op):
    _auto(op)
    _show(op, "gen 10:3")
    _say(op, "go back to chapter three", 1)
    assert op.live.selection.verse_label() == "Genesis 3:1"
    _say(op, "turn to chapter four verse two", 5)
    assert op.live.selection.verse_label() == "Genesis 4:2"
    _say(op, "go to the beginning of the chapter", 9)
    assert op.live.selection.verse_label() == "Genesis 4:1"


def test_intent_impossible_target_is_ignored(op):
    _auto(op)
    _show(op, "jude 1:3")
    _say(op, "go to chapter five", 1)
    assert op.live.selection.verse_label() == "Jude 1:3"
    assert "not possible" in op.status_var.get()


def test_stop_and_continue_toggle_following(op):
    _show(op, "gen 10:3-10")
    _say(op, "let's stop there", 1)
    assert op.following is False
    _say(op, "let's continue", 5)
    assert op.following is True


def test_book_less_chapter_and_verse_detection(op):
    _auto(op)
    _show(op, "gen 10:3")
    (kind, det), = op.detector.feed_final("now turn to chapter four verse two")
    op._on_detection(kind, det)
    assert op.live.selection.verse_label() == "Genesis 4:2"


# -- phase 2: following the reading ---------------------------------------------------

def _read_aloud(op, text):
    ws = text.split()
    for i in range(1, len(ws) + 1):
        op.follower._since = -10.0  # skip the dwell time in tests
        op._handle(("partial", " ".join(ws[:i])))


def test_follow_moves_live_verse_as_reading_ends(op, bible):
    _show(op, "john 3:16-18")  # Manual mode: following still moves the live slide
    _read_aloud(op, bible.verse("KJV", 43, 3, 16))
    assert op.live.selection.verse_label() == "John 3:17"
    assert op.live.selection.start == 16 and op.live.selection.end == 18  # still the same passage
    _read_aloud(op, bible.verse("KJV", 43, 3, 17))
    assert op.live.selection.verse_label() == "John 3:18"
    _read_aloud(op, bible.verse("KJV", 43, 3, 18))
    assert op.live.selection.verse_label() == "John 3:18"  # end of the range: stays


def test_stop_there_and_continue(op, bible):
    _show(op, "john 3:16-18")
    _say(op, "let's stop there", 1)
    _read_aloud(op, bible.verse("KJV", 43, 3, 16))
    assert op.live.selection.verse_label() == "John 3:16"
    assert "Paused" in op.follow_label.cget("text")
    _say(op, "let's continue", 5)
    _read_aloud(op, bible.verse("KJV", 43, 3, 16))
    assert op.live.selection.verse_label() == "John 3:17"


def test_follow_button_and_setting(op, bible):
    _show(op, "john 3:16-18")
    op.toggle_following()
    _read_aloud(op, bible.verse("KJV", 43, 3, 16))
    assert op.live.selection.verse_label() == "John 3:16"
    op.toggle_following()
    op.settings["follow_reading"] = False
    _read_aloud(op, bible.verse("KJV", 43, 3, 16))
    assert op.live.selection.verse_label() == "John 3:16"


def test_operator_move_restarts_following(op, bible):
    _show(op, "john 3:16-18")
    op.step(1)  # operator jumps to 17 by hand
    _read_aloud(op, bible.verse("KJV", 43, 3, 17))
    assert op.live.selection.verse_label() == "John 3:18"


def test_blank_screen_is_not_followed(op, bible):
    _show(op, "john 3:16-18")
    op.blank()
    _read_aloud(op, bible.verse("KJV", 43, 3, 16))
    op.blank()
    assert op.live.selection.verse_label() == "John 3:16"


def test_voice_switches_translation_until_changed(op, bible):
    _show(op, "gen 1:3")
    from biverse.commands import parse_intent
    intent = parse_intent("let's read this in Young's Literal", op.engine.translations)
    op._on_command(intent, "main", 1.0, "let's read this in Young's Literal")
    assert op.translation() == "YLT" and "Let light be" in op.output.slide.text
    op.step(1)  # stays switched for the next verse and chapter
    assert op.translation() == "YLT"
    intent = parse_intent("show it in the NIV", op.engine.translations)
    op._on_command(intent, "main", 5.0, "show it in the NIV")
    assert op.translation() == "YLT" and "not installed" in op.status_var.get()


# -- emphasis ----------------------------------------------------------------------

def test_emphasis_marks_live_verse(op, tmp_path):
    from biverse.emphasis import EmphasisStore
    from biverse.ui_emphasis import EmphasisDialog
    op.emphasis = EmphasisStore(str(tmp_path / "emph.json"))
    op.builder.emphasis = op.emphasis
    _show(op, "john 3:16")
    dlg = EmphasisDialog(op, 43, 3, 16, "KJV")
    op.root.update()
    dlg.select_words([2, 3])  # "so loved"
    assert dlg.selected_words() == [2, 3]
    dlg.apply("highlight")
    assert op.output.slide.marks == {2: {"highlight"}, 3: {"highlight"}}
    dlg.apply("highlight")  # toggles off
    assert op.output.slide.marks == {}
    dlg.select_words([5])
    dlg.apply("underline")
    dlg.apply("bold")
    assert op.output.slide.marks == {5: {"bold", "underline"}}
    # saved per translation + verse
    assert EmphasisStore(str(tmp_path / "emph.json")).get("KJV", 43, 3, 16) == {5: {"bold", "underline"}}
    assert op.emphasis.get("ASV", 43, 3, 16) == {}
    dlg.clear_all()
    assert op.output.slide.marks == {}
    dlg.win.destroy()


def test_marked_slide_draws_word_items(op):
    from biverse.render import TEXT, Slide
    c = tk.Canvas(op.root, width=640, height=360)
    slide = Slide(TEXT, "For God so loved the world", "John 3:16", marks={2: {"highlight"}, 3: {"bold"}})
    op.renderer.draw(c, slide, op.settings.appearance, 640, 360, translation="KJV")
    kinds = [c.type(i) for i in c.find_all()]
    assert kinds.count("rectangle") == 1  # one highlight box
    assert sum(1 for i in c.find_all() if c.type(i) == "text") >= 6  # word by word


def test_theme_switches_live(op):
    op.set_theme("dark")
    assert op.root.cget("background") == op.pal["bg"]
    assert op.transcript.cget("background") == op.pal["surface"]
    dark_bg = op.transcript.cget("background")
    op.set_theme("light")
    assert op.transcript.cget("background") != dark_bg
    op._status("problem", error=True)
    assert op.status_label.cget("foreground") == op.pal["error"]


def test_theme_setting_forces_mode(op, monkeypatch):
    monkeypatch.delenv("BIVERSE_THEME", raising=False)
    op.settings["ui_theme"] = "dark"
    op._check_theme()
    assert op.theme_mode == "dark"
    op.settings["ui_theme"] = "light"
    op._check_theme()
    assert op.theme_mode == "light"


def test_sermon_record_and_summary_window(op):
    op.new_sermon(quiet=True)
    for text in ["Turn with me to John chapter three verse sixteen.",
                 "The point is that the love of God is a gift we receive by faith alone today.",
                 "Remember this: grace means the love of God comes before our work and effort."]:
        op._add_final(text)
    from biverse.detector import Detector
    (kind, det), = Detector().feed_final("john three sixteen", now=0)
    op._on_detection(kind, det)
    assert op.sermon.refs[-1][1] == "John 3:16"
    from biverse.ui_summary import SummaryWindow
    w = SummaryWindow(op, op.sermon)
    op.root.update()
    body = w.text.get("1.0", "end")
    assert "John 3:16" in body and "Key points" in body
    assert "Scriptures" in w.text_for_export()
    w.win.destroy()


def test_online_versions_appear_and_fall_back(op, tmp_path):
    from biverse.online_bible import OnlineBibles
    from tests.test_online_bible import FakeApi
    api = FakeApi()
    online = OnlineBibles("good-key", str(tmp_path / "yv"), "en", fetch=api)
    assert online.refresh_versions()
    op.bible.set_online(online)
    op._on_online_versions(True)
    assert "NIV" in op.translation_combo.cget("values")
    op.search_var.set("matt 17:20")
    op.search()
    op.go_live()
    op.translation_var.set("NIV")
    op._on_translation()
    assert op.output.slide.text.startswith("He replied") and op.output.translation == "NIV"
    online._mem.clear()
    api.down = True
    op._render_all()
    assert op.output.translation == "KJV" and "unbelief" in op.output.slide.text
    assert "offline" in op.translation_name.cget("text")
    labels = [op.live_canvas.itemcget(i, "text") for i in op.live_canvas.find_all()
              if op.live_canvas.type(i) == "text"]
    assert any(t.endswith("\u00b7 KJV") for t in labels), labels  # the thumbnail names what it shows
    op.search_var.set("matt 17:19")
    op.search()
    assert op.results.item(op.results.get_children()[-1], "values")[1]  # offline search row has text


def test_settings_bibles_tab_saves_the_key(op):
    op.open_settings(tab="bibles")
    d = op.settings_dialog
    op.root.update()
    assert "No YouVersion key" in d.online_status.cget("text")
    d.yv_key.set("  my-key  ")
    d._apply_bibles(refresh=False)
    assert op.settings["youversion_key"] == "my-key"
    assert op.bible.online is not None and op.bible.online.key == "my-key"
    d.yv_key.set("")
    d._apply_bibles(refresh=False)
    assert op.bible.online is None
    d._ok()


def test_switches_back_when_another_request_came_back_first(op, tmp_path):
    """Regression: a prefetch of the next chapter brought the client online first, and the
    chapter on screen was never retried, so the fallback stayed up for good."""
    import time
    from biverse import online_bible
    from biverse.online_bible import OnlineBibles
    from tests.test_online_bible import FakeApi
    api = FakeApi()
    online = OnlineBibles("good-key", str(tmp_path / "yv"), "en", fetch=api)
    assert online.refresh_versions()
    op.bible.set_online(online)
    op._on_online_versions(True)
    op.search_var.set("matt 17:20")
    op.search()
    op.go_live()
    op.translation_var.set("NIV")
    api.down = True
    op._on_translation()
    assert op.output.translation == "KJV" and op._online_note
    api.down = False
    online._down_until = 0
    online.state = online_bible.ONLINE  # as if the next-chapter prefetch had succeeded
    end = time.time() + 5
    while op.output.translation != "NIV" and time.time() < end:
        op._online_back()
        op.root.update()
        time.sleep(0.05)
    assert op.output.translation == "NIV" and not op._online_note
