from __future__ import annotations

import json
import os
import stat
import sys

import pytest

from biverse import llm
from biverse.summary import SermonLog, as_text, sentences, summarise

SERMON = [
    (0, "Good morning church, it is a blessing to be here today."),
    (20, "Please turn with me to John chapter three verse sixteen."),
    (40, "For God so loved the world that he gave his only begotten son."),
    (70, "The point is that the love of God is not earned, it is a gift we receive by faith."),
    (100, "Many of us try to earn the love of God by working harder and harder."),
    (130, "But grace means the love of God comes before our work, not after it."),
    (200, "Now look at Romans chapter eight verse twenty eight."),
    (230, "And we know that all things work together for good to them that love God."),
    (260, "Remember this: the love of God holds us when life falls apart."),
    (300, "Number one, receive the gift. Number two, rest in his love. Number three, share it with others."),
    (400, "Okay. Amen."),
    (420, "In conclusion, the love of God is a gift, grace is enough, and we are called to share it this week."),
]


@pytest.fixture
def log():
    s = SermonLog(started=1_700_000_000)
    for t, text in SERMON:
        s.add_line(text, when=s.started + t)
    s.add_ref("John 3:16", when=s.started + 25)
    s.add_ref("John 3:16", when=s.started + 26)  # repeats are not listed twice in a row
    s.add_ref("Romans 8:28", when=s.started + 205)
    return s


def test_summary_contents(log):
    s = summarise(log, max_points=4)
    assert [r for _t, r in s["scriptures"]] == ["John 3:16", "Romans 8:28"]
    assert "love" in s["themes"] and "god" in s["themes"]
    points = [p for _t, p in s["key_points"]]
    assert len(points) == 4
    assert [t for t, _p in s["key_points"]] == sorted(t for t, _p in s["key_points"])  # chronological
    assert any(p.startswith("The point is") for p in points) or any(p.startswith("In conclusion") for p in points)
    assert "Okay." not in points and "Amen." not in points
    assert s["duration"] == 420 and s["words"] > 100


def test_sentences_split_punctuated_lines(log):
    sents = [x for _t, x in sentences(log)]
    assert "Number one, receive the gift." in sents and "Number two, rest in his love." in sents


def test_empty_log():
    s = summarise(SermonLog())
    assert s["key_points"] == [] and s["scriptures"] == []


def test_save_and_reload(log, tmp_path):
    path = log.save(str(tmp_path))
    back = SermonLog.from_dict(json.load(open(path)))
    assert back.lines[2][1] == SERMON[2][1] and back.refs == log.refs


def test_text_export(log):
    text = as_text(log, summarise(log), ai_text="God's love is a gift.")
    assert "Scriptures" in text and "John 3:16" in text and "God's love is a gift." in text
    assert "Transcript" in text and "Good morning church" in text


# -- AI summary (with a stand-in for llama.cpp) -----------------------------------------

def _fake_pack(tmp_path, script):
    folder = tmp_path / "biverse-ai-summary"
    (folder / "bin" / llm.platform_key()).mkdir(parents=True)
    exe = folder / "bin" / llm.platform_key() / ("llama-completion.exe" if sys.platform == "win32" else
                                                   "llama-completion")
    exe.write_text(script)
    exe.chmod(0o644)  # zip extraction loses the executable bit; find_pack must restore it
    (folder / "model.gguf").write_bytes(b"GGUF")
    (folder / "biverse-model.json").write_text(json.dumps({
        "engine": "llm", "id": "ai-summary", "label": "AI summary (test)", "model": "model.gguf",
        "bin": {llm.platform_key(): str(exe.relative_to(folder)).replace(os.sep, "/")}}))
    return folder


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell stand-in")
def test_ai_summary_with_stand_in(tmp_path, monkeypatch, log):
    monkeypatch.setenv("BIVERSE_CONFIG_DIR", str(tmp_path / "cfg"))
    from biverse import paths
    import shutil
    folder = _fake_pack(tmp_path, "#!/bin/sh\necho 'God loves us freely.'\necho '- Receive the gift'\n"
                                  "echo '[end of text]'\n")
    shutil.move(str(folder), os.path.join(paths.user_models_dir(), folder.name))
    pack = llm.find_pack()
    assert pack is not None and os.stat(pack.binary).st_mode & stat.S_IXUSR
    text = llm.summarise_ai(pack, summarise(log))
    assert text.startswith("God loves us freely.") and "[end of text]" not in text


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell stand-in")
def test_ai_summary_failure_is_reported(tmp_path, monkeypatch, log):
    monkeypatch.setenv("BIVERSE_CONFIG_DIR", str(tmp_path / "cfg"))
    from biverse import paths
    import shutil
    folder = _fake_pack(tmp_path, "#!/bin/sh\necho 'error: model file is damaged' >&2\nexit 1\n")
    shutil.move(str(folder), os.path.join(paths.user_models_dir(), folder.name))
    with pytest.raises(RuntimeError, match="damaged"):
        llm.summarise_ai(llm.find_pack(), summarise(log))


def test_ai_pack_is_not_a_speech_model(tmp_path, monkeypatch):
    monkeypatch.setenv("BIVERSE_CONFIG_DIR", str(tmp_path / "cfg"))
    from biverse import paths, recognizer
    import shutil
    folder = _fake_pack(tmp_path, "#!/bin/sh\n")
    shutil.move(str(folder), os.path.join(paths.user_models_dir(), folder.name))
    models = [m for m in recognizer.discover_models() if m.engine == "llm"]
    assert models  # it is discovered...
    m, _r = recognizer.choose_model(models, "auto")
    assert m is None  # ...but never chosen for speech


def test_prompt_is_grounded():
    p = llm.build_prompt(["John 3:16"], ["God loves the world."], ["love"])
    assert "John 3:16" in p and "God loves the world." in p and "Do not add Bible verses" in p
    assert p.endswith("<|im_start|>assistant\n")
