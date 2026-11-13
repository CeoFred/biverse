"""Offline speech recognition with Vosk, off the UI thread.

``SpeechEngine`` loads the model in a background thread (it takes seconds)
and runs a recogniser thread while listening. Results and detections are
posted to the UI's event queue as tuples:

    ("model", "loading" | "ready" | "missing" | "error", detail)
    ("partial", text)
    ("final", text)
    ("detect", kind, Detection)        kind is detector.NEW or detector.UPDATE
    ("error", message)
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from typing import List, Optional

from . import paths
from .detector import Detector

log = logging.getLogger(__name__)

DEFAULT_MODEL = "vosk-model-small-en-us-0.15"

try:
    import vosk
    VOSK_ERROR = None  # type: Optional[str]
except Exception as exc:  # pragma: no cover - depends on the machine
    vosk = None
    VOSK_ERROR = str(exc)


def is_model_dir(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    has_am = os.path.isfile(os.path.join(path, "am", "final.mdl")) or os.path.isfile(
        os.path.join(path, "final.mdl"))
    has_graph = (os.path.isdir(os.path.join(path, "graph")) or os.path.isfile(os.path.join(path, "HCLG.fst"))
                 or os.path.isfile(os.path.join(path, "HCLr.fst")))
    return has_am and has_graph


def find_model(user_path: Optional[str] = None) -> Optional[str]:
    """First model found in discovery order (spec §6).

    Each candidate may be a model folder itself or a folder containing models;
    in the latter case the default small model is preferred.
    """
    for base in paths.model_search_dirs(user_path or None):
        if is_model_dir(base):
            return base
        if not os.path.isdir(base):
            continue
        try:
            children = sorted(os.listdir(base))
        except OSError:
            continue
        models = [os.path.join(base, c) for c in children if is_model_dir(os.path.join(base, c))]
        if models:
            for m in models:
                if os.path.basename(m) == DEFAULT_MODEL:
                    return m
            return models[0]
    return None


def load_model(path: str):
    if vosk is None:
        raise RuntimeError("Vosk is not available: %s" % VOSK_ERROR)
    vosk.SetLogLevel(-1)
    return vosk.Model(path)


def make_recognizer(model, samplerate: float):
    rec = vosk.KaldiRecognizer(model, float(samplerate))
    rec.SetWords(False)
    return rec


def transcribe_pcm(model, samplerate: int, pcm: bytes, chunk: int = 8000) -> List[str]:
    """Run raw mono int16 PCM through a recogniser; return the final texts (tests, self-test)."""
    rec = make_recognizer(model, samplerate)
    out = []
    for i in range(0, len(pcm), chunk):
        if rec.AcceptWaveform(pcm[i:i + chunk]):
            text = json.loads(rec.Result()).get("text", "")
            if text:
                out.append(text)
    text = json.loads(rec.FinalResult()).get("text", "")
    if text:
        out.append(text)
    return out


class SpeechEngine(object):
    def __init__(self, events: "queue.Queue", detector: Detector) -> None:
        self.events = events
        self.detector = detector
        self.audio_queue = queue.Queue(maxsize=50)  # ~10 s of 0.2 s blocks
        self.model = None
        self.model_path = None  # type: Optional[str]
        self.state = "none"  # none | loading | ready | missing | error
        self._loader = None  # type: Optional[threading.Thread]
        self._worker = None  # type: Optional[threading.Thread]
        self._stop = threading.Event()
        self._load_token = 0

    # -- model ------------------------------------------------------------------
    def load(self, user_path: Optional[str] = None) -> None:
        """Find and load the model in the background (replaces any loaded model)."""
        self._load_token += 1
        token = self._load_token
        path = find_model(user_path)
        if path is None:
            self.state = "missing"
            self.model = None
            self.events.put(("model", "missing", ""))
            return
        if vosk is None:
            self.state = "error"
            self.events.put(("model", "error", "Vosk could not be loaded: %s" % VOSK_ERROR))
            return
        self.state = "loading"
        self.events.put(("model", "loading", path))

        def work():
            t = time.monotonic()
            try:
                model = load_model(path)
            except Exception as exc:
                log.exception("model load failed")
                if token == self._load_token:
                    self.state = "error"
                    self.events.put(("model", "error", "%s: %s" % (path, exc)))
                return
            if token != self._load_token:
                return
            self.model = model
            self.model_path = path
            self.state = "ready"
            log.info("model %s loaded in %.1f s", path, time.monotonic() - t)
            self.events.put(("model", "ready", path))

        self._loader = threading.Thread(target=work, name="model-loader", daemon=True)
        self._loader.start()

    # -- recognition ---------------------------------------------------------------
    @property
    def running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._drain()
        self._worker = threading.Thread(target=self._run, name="recognizer", daemon=True)
        self._worker.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.join(timeout)
        self._drain()

    def _drain(self) -> None:
        try:
            while True:
                self.audio_queue.get_nowait()
        except queue.Empty:
            pass

    def _run(self) -> None:
        rec = None
        rate = None
        last_partial = ""
        while not self._stop.is_set():
            try:
                item = self.audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            model = self.model
            if model is None:
                continue  # model still loading: drop audio
            samplerate, data = item
            try:
                if rec is None or samplerate != rate:
                    rec = make_recognizer(model, samplerate)
                    rate = samplerate
                if rec.AcceptWaveform(data):
                    text = json.loads(rec.Result()).get("text", "")
                    last_partial = ""
                    if text:
                        self._final(text)
                else:
                    partial = json.loads(rec.PartialResult()).get("partial", "")
                    if partial != last_partial:
                        last_partial = partial
                        self.events.put(("partial", partial))
            except Exception as exc:
                log.exception("recogniser error")
                self.events.put(("error", "speech recognition error: %s" % exc))
                rec = None
        if rec is not None:
            try:
                text = json.loads(rec.FinalResult()).get("text", "")
                if text:
                    self._final(text)
            except Exception:
                pass

    def _final(self, text: str) -> None:
        self.events.put(("final", text))
        try:
            for kind, det in self.detector.feed_final(text):
                self.events.put(("detect", kind, det))
        except Exception:
            log.exception("detector error on %r", text)
