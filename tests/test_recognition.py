"""Feed synthesised speech through the real Vosk model and the detector.

The WAV is generated at test time with espeak-ng (CI installs it) or, on
macOS, ``say`` + ``afconvert``. Set BIVERSE_REQUIRE_VOSK=1 to turn skips into
failures (CI does).
"""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import time
import wave

import pytest

from versecast import recognizer
from versecast.detector import NEW, Detector

SENTENCES = [
    "please turn in your bibles to john chapter three verse sixteen",
]


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


@pytest.fixture(scope="module")
def model():
    if recognizer.vosk is None:
        _skip("vosk not importable: %s" % recognizer.VOSK_ERROR)
    path = recognizer.find_model()
    if path is None:
        _skip("no Vosk model in models/ (run tools/fetch_model.py)")
    return recognizer.load_model(path)


def _read_wav(path):
    with wave.open(path, "rb") as w:
        assert w.getsampwidth() == 2
        rate, ch = w.getframerate(), w.getnchannels()
        data = w.readframes(w.getnframes())
    if ch > 1:
        from versecast.audio import downmix
        data = downmix(data, ch)
    return rate, data


@pytest.mark.vosk
def test_john_3_16_detected_from_audio(model, tmp_path):
    wav = str(tmp_path / "john316.wav")
    fixture = os.path.join(os.path.dirname(__file__), "data", "john316.wav")
    if os.path.exists(fixture):
        wav = fixture
    elif not _synthesise(SENTENCES[0], wav):
        _skip("no TTS (espeak-ng / say) available to make the test clip")
    rate, pcm = _read_wav(wav)
    texts = recognizer.transcribe_pcm(model, rate, pcm + b"\0\0" * rate)  # 1 s silence = pause
    print("transcript:", texts)
    det = Detector()
    found = []
    for t in texts:
        found += [d.ref.label() for kind, d in det.feed_final(t, now=0) if kind == NEW]
    assert "John 3:16" in found, texts


@pytest.mark.vosk
def test_speech_engine_threads(model, tmp_path):
    """The threaded engine emits a detection event and stops promptly."""
    wav = str(tmp_path / "e.wav")
    if not _synthesise(SENTENCES[0], wav):
        _skip("no TTS available")
    rate, pcm = _read_wav(wav)
    events = queue.Queue()
    engine = recognizer.SpeechEngine(events, Detector())
    engine.model = model
    engine.state = "ready"
    engine.start()
    block = int(rate * 0.2) * 2
    t0 = time.monotonic()
    for i in range(0, len(pcm) + rate * 2, block):  # audio then 1 s silence, real-time-ish
        chunk = pcm[i:i + block] or b"\0" * block
        engine.audio_queue.put((rate, chunk))
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
    engine.stop()
    assert time.monotonic() - t < 2.5
    assert detected == "John 3:16", "no detection after %.1fs" % (time.monotonic() - t0)
