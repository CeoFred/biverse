"""Feed synthesised speech through the real speech engines and the detector.

The WAV is generated at test time with espeak-ng (CI installs it) or, on
macOS, ``say`` + ``afconvert``. Models come from tools/fetch_model.py. Set
BIVERSE_REQUIRE_VOSK=1 to turn "model/TTS missing" skips into failures (CI).
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import time
import wave

import pytest

from biverse import recognizer
from biverse.detector import NEW, Detector

SENTENCE = "please turn in your bibles to john chapter three verse sixteen"


def _skip(msg):
    if os.environ.get("BIVERSE_REQUIRE_VOSK"):
        pytest.fail(msg)
    pytest.skip(msg)


def _synthesise(text, out_wav):
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")
    if espeak:
        subprocess.check_call([espeak, "-v", "en-us", "-s", "140", "-w", out_wav, text])
        return True
    if sys.platform == "darwin" and shutil.which("say") and shutil.which("afconvert"):
        aiff = out_wav + ".aiff"
        subprocess.check_call(["say", "-o", aiff, text])
        subprocess.check_call(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", aiff, out_wav])
        return True
    return False


def _read_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getsampwidth() == 2
        rate, ch = w.getframerate(), w.getnchannels()
        data = w.readframes(w.getnframes())
    if ch > 1:
        from biverse.audio import downmix
        data = downmix(data, ch)
    return rate, data


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    wav = str(tmp_path_factory.mktemp("tts") / "john316.wav")
    fixture = os.path.join(os.path.dirname(__file__), "data", "john316.wav")
    if os.path.exists(fixture):
        wav = fixture
    elif not _synthesise(SENTENCE, wav):
        _skip("no TTS (espeak-ng / say) available to make the test clip")
    rate, pcm = _read_wav(wav)
    return rate, pcm + b"\0\0" * rate  # 1 s of silence = the speaker pauses


def _model(model_id):
    for m in recognizer.discover_models():
        if m.id == model_id:
            if not recognizer.engine_available(m.engine):
                _skip("engine for %s unavailable" % model_id)
            return m
    if model_id == "parakeet" and not os.environ.get("BIVERSE_REQUIRE_PARAKEET"):
        pytest.skip("Parakeet pack not installed (python tools/fetch_model.py --name parakeet)")
    _skip("model %s not installed (python tools/fetch_model.py --name %s)" % (model_id, model_id))


def _detect(texts):
    det = Detector()
    found = []
    for t in texts:
        found += [d.ref.label() for kind, d in det.feed_final(t, now=0) if kind == NEW]
    return found


@pytest.mark.vosk
@pytest.mark.parametrize("model_id", ["kroko", "vosk-small", "parakeet"])
def test_john_3_16_detected_from_audio(model_id, clip):
    info = _model(model_id)
    engine = recognizer.create_engine(info)
    rate, pcm = clip
    texts = recognizer.transcribe(engine, rate, pcm)
    print(model_id, "transcript:", texts)
    assert "John 3:16" in _detect(texts), texts


@pytest.mark.vosk
@pytest.mark.parametrize("rate", [44100, 48000])
def test_kroko_accepts_device_rates(rate, clip):
    """Devices run at 44.1/48 kHz; the engine resamples (sherpa aborts on rate changes)."""
    info = _model("kroko")
    engine = recognizer.create_engine(info)
    src_rate, pcm = clip
    from array import array
    a = array("h")
    a.frombytes(pcm)
    step = src_rate / float(rate)  # upsample with linear interpolation, like a real device clock
    out = array("h")
    for i in range(int((len(a) - 1) / step)):
        pos = i * step
        j = int(pos)
        frac = pos - j
        out.append(int(a[j] * (1 - frac) + a[j + 1] * frac))
    texts = recognizer.transcribe(engine, rate, out.tobytes())
    assert "John 3:16" in _detect(texts), texts
    # stopping and starting again at another rate must not crash
    recognizer.transcribe(engine, 16000, b"\0\0" * 8000)


@pytest.mark.vosk
def test_speech_engine_threads(clip):
    """The threaded service emits a detection event and stops promptly."""
    info = _model("kroko")
    events = queue.Queue()
    service = recognizer.SpeechEngine(events, Detector())
    service.set_engine(recognizer.create_engine(info), info)
    service.start()
    rate, pcm = clip
    block = int(rate * 0.2) * 2
    for i in range(0, len(pcm) + rate * 2, block):
        service.audio_queue.put((rate, pcm[i:i + block] or b"\0" * block))
    detected = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and detected is None:
        try:
            ev = events.get(timeout=0.5)
        except queue.Empty:
            continue
        if ev[0] == "detect":
            detected = ev[2].ref.label()
    t = time.monotonic()
    service.stop()
    assert time.monotonic() - t < 3.5
    while detected is None and not events.empty():  # flushed on stop
        ev = events.get_nowait()
        if ev[0] == "detect":
            detected = ev[2].ref.label()
    assert detected == "John 3:16"


@pytest.mark.vosk
def test_vosk_reference_listener_runs(clip):
    """Classic engine with the reference-only grammar recogniser still detects."""
    info = _model("vosk-small")
    assert recognizer.supports_grammar(info.path)
    engine = recognizer.create_engine(info)
    engine.use_reference = True
    rate, pcm = clip
    kinds = []
    block = int(rate * 0.2) * 2
    for i in range(0, len(pcm), block):
        kinds += engine.accept(rate, pcm[i:i + block])
    kinds += engine.finish()
    texts = [t for k, t in kinds if k in ("final", "final_ref")]
    assert "John 3:16" in _detect(texts), kinds


def test_reference_grammar_covers_books_and_numbers():
    words = set(json.loads(recognizer.reference_grammar()))
    for w in ("genesis", "john", "corinthians", "psalm", "chapter", "verse", "eighteen", "hundred", "[unk]"):
        assert w in words
    assert "marriage" not in words


# -- model discovery and choice (no models needed) ----------------------------------

def _mk(tmp_path, name, manifest=None, files=()):
    d = tmp_path / name
    d.mkdir()
    for f in files:
        p = d / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    if manifest is not None:
        (d / "biverse-model.json").write_text(json.dumps(manifest))
    return str(d)


def test_detect_model_kinds(tmp_path):
    kro = _mk(tmp_path, "k", {"engine": "sherpa-online", "id": "kroko", "label": "Kroko (live)"})
    par = _mk(tmp_path, "sherpa-onnx-nemo-parakeet-x", None,
              ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt", "silero_vad.onnx"])
    vos = _mk(tmp_path, "vosk-model-small-x", None, ["am/final.mdl", "graph/HCLr.fst", "graph/Gr.fst"])
    junk = _mk(tmp_path, "junk", None, ["readme.txt"])
    assert recognizer.detect_model(kro).engine == "sherpa-online"
    p = recognizer.detect_model(par)
    assert (p.engine, p.id, p.manifest["encoder"], p.manifest["vad"]) == (
        "sherpa-offline", "parakeet", "encoder.int8.onnx", "silero_vad.onnx")
    assert recognizer.detect_model(vos).engine == "vosk"
    assert recognizer.detect_model(junk) is None
    assert recognizer.detect_model(str(tmp_path / "missing")) is None


def _infos():
    M = recognizer.ModelInfo
    return [M("/m/vosk", "vosk", "vosk-small", "Vosk"), M("/m/kroko", "sherpa-online", "kroko", "Kroko"),
            M("/m/para", "sherpa-offline", "parakeet", "Parakeet", 6)]


def _all_engines(engine):
    return True


def test_choose_both_on_big_machine():
    m, _ = recognizer.choose_model(_infos(), "auto", ram_gb=16, is64=True, available=_all_engines)
    assert m.id == "both"
    m, _ = recognizer.choose_model(_infos(), "parakeet", ram_gb=16, is64=True, available=_all_engines)
    assert m.id == "parakeet"


@pytest.mark.parametrize("ram,is64", [(4, True), (16, False)])
def test_choose_kroko_on_small_or_32bit(ram, is64):
    m, reason = recognizer.choose_model(_infos(), "auto", ram_gb=ram, is64=is64, available=_all_engines)
    assert m.id == "kroko" and "Parakeet needs" in reason


def test_choose_vosk_when_sherpa_missing():
    m, _ = recognizer.choose_model(_infos(), "auto", ram_gb=16, is64=True, available=lambda e: e == "vosk")
    assert m.id == "vosk-small"


def test_choose_explicit_and_missing_preference():
    assert recognizer.choose_model(_infos(), "vosk-small", available=_all_engines)[0].id == "vosk-small"
    infos = [i for i in _infos() if i.id != "parakeet"]
    m, reason = recognizer.choose_model(infos, "parakeet", ram_gb=16, is64=True, available=_all_engines)
    assert m.id == "kroko" and "not installed" in reason
    assert recognizer.choose_model([], "auto", available=_all_engines)[0] is None


def test_resampler_lengths():
    r = recognizer.Resampler(48000)
    assert len(r([0.5] * 9600)) == 3200
    r = recognizer.Resampler(44100)
    total = sum(len(r([0.1] * 8820)) for _ in range(5))
    assert abs(total - 16000) <= 2
    assert recognizer.Resampler(16000)([1.0, 2.0]) == [1.0, 2.0]


@pytest.mark.vosk
def test_dual_engine_detects_once(clip):
    """Kroko and Parakeet both hear the reference; the detector reports it once."""
    kroko, parakeet = _model("kroko"), _model("parakeet")
    info = recognizer.combined(kroko, parakeet)
    events = queue.Queue()
    service = recognizer.SpeechEngine(events, Detector())
    service.set_engine(recognizer.create_engine(info), info)
    service.start()
    rate, pcm = clip
    block = int(rate * 0.2) * 2
    for i in range(0, len(pcm) + rate * 2, block):
        service.audio_queue.put((rate, pcm[i:i + block] or b"\0" * block))
    deadline = time.monotonic() + 30
    detections, finals = [], []
    while time.monotonic() < deadline:
        try:
            ev = events.get(timeout=1.5)
        except queue.Empty:
            if detections and finals:
                break
            continue
        if ev[0] == "detect":
            detections.append((ev[1], ev[2].ref.label()))
        elif ev[0] == "final":
            finals.append(ev[1])
    service.stop()
    assert [d for d in detections if d[0] == NEW] == [(NEW, "John 3:16")], detections
    assert finals, "Parakeet's transcript line should appear"


def test_combined_model_is_chosen_automatically_on_big_machines():
    M = recognizer.ModelInfo
    infos = [M("/m/kroko", "sherpa-online", "kroko", "Kroko"), M("/m/para", "sherpa-offline", "parakeet", "P", 6)]
    m, _ = recognizer.choose_model(infos, "auto", ram_gb=16, is64=True, available=lambda e: True)
    assert m.id == "both" and m.engine == "dual"
    m, _ = recognizer.choose_model(infos, "auto", ram_gb=4, is64=True, available=lambda e: True)
    assert m.id == "kroko"


def test_book_hotwords_files(tmp_path, monkeypatch):
    monkeypatch.setenv("BIVERSE_CONFIG_DIR", str(tmp_path / "cfg"))
    tokens = tmp_path / "model" / "tokens.txt"
    tokens.parent.mkdir()
    tokens.write_text("<blk> 0\n▁the 1\nss 2\n", encoding="utf-8")
    hot, vocab = recognizer.book_hotwords(str(tokens))
    words = open(hot, encoding="utf-8").read().split("\n")
    assert "habakkuk" in words and "thessalonians" in words and "song of solomon" in words
    assert open(vocab, encoding="utf-8").read() == "▁the\t0\nss\t0\n"


def test_online_engine_finalises_when_text_stalls():
    """If the decoder never raises an endpoint, unchanged text for 1.5 s becomes final."""
    class FakeRec(object):
        def __init__(self):
            self.text = "john three sixteen"

        def is_ready(self, s):
            return False

        def get_result(self, s):
            return self.text

        def is_endpoint(self, s):
            return False

        def reset(self, s):
            self.text = ""

    class FakeStream(object):
        def accept_waveform(self, rate, samples):
            pass

    eng = recognizer.SherpaOnlineEngine.__new__(recognizer.SherpaOnlineEngine)
    eng.rec, eng.stream = FakeRec(), FakeStream()
    eng._partial, eng._resampler, eng._rate, eng._still = "", None, None, 0
    block = b"\0\0" * 3200  # 0.2 s at 16 kHz
    kinds = []
    for _ in range(12):
        kinds += [k for k, _t in eng.accept(16000, block)]
    assert kinds[0] == "partial" and "final" in kinds
