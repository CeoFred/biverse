"""Offline speech recognition, off the UI thread.

Three engines share one interface (``accept(rate, pcm) -> [(kind, text)]``):

* **Kroko** (sherpa-onnx streaming zipformer): live, light. The default.
* **Parakeet** (sherpa-onnx NeMo transducer + Silero VAD): the most accurate,
  needs a 64-bit computer with plenty of RAM. Installed from a model pack.
  Speech is cut into phrases at pauses by the VAD and each phrase is decoded.
* **Vosk** (classic): kept as a fallback for computers where sherpa-onnx's
  ONNX Runtime does not load (e.g. Windows 7). Runs the optional
  reference-only grammar recogniser alongside.

``SpeechEngine`` picks and loads a model in the background and runs the
recogniser thread while listening. It posts to the UI's event queue:

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
from array import array
from typing import List, Optional, Tuple

from . import paths, sysinfo
from .commands import parse_command
from .detector import REFERENCE, Detector

log = logging.getLogger(__name__)

try:
    import vosk
    VOSK_ERROR = None  # type: Optional[str]
except Exception as exc:  # pragma: no cover - depends on the machine
    vosk = None
    VOSK_ERROR = str(exc)

_sherpa = None
SHERPA_ERROR = None  # type: Optional[str]


def sherpa():
    """Import sherpa-onnx lazily; it can fail where ONNX Runtime cannot load (Windows 7)."""
    global _sherpa, SHERPA_ERROR
    if _sherpa is None and SHERPA_ERROR is None:
        try:
            import sherpa_onnx
            _sherpa = sherpa_onnx
        except Exception as exc:  # pragma: no cover - depends on the machine
            SHERPA_ERROR = "%s: %s" % (type(exc).__name__, exc)
            log.warning("sherpa-onnx unavailable: %s", SHERPA_ERROR)
    return _sherpa


# Model ids in order of preference for "automatic"
AUTO_ORDER = ("both", "parakeet", "kroko", "vosk-small")
PARAKEET_MIN_RAM_GB = 6.0
LABELS = {"kroko": "Kroko (live)", "parakeet": "Parakeet (high accuracy)", "vosk-small": "Vosk small (classic)",
          "both": "Kroko live + Parakeet"}


def combined(live: "ModelInfo", confirm: "ModelInfo") -> "ModelInfo":
    """Virtual model: Kroko for live words, Parakeet to confirm at each pause."""
    return ModelInfo(confirm.path, "dual", "both", LABELS["both"], max(live.min_ram_gb, confirm.min_ram_gb),
                     {"parts": (live, confirm)})


# ----------------------------------------------------------------- discovery

class ModelInfo(object):
    __slots__ = ("path", "engine", "id", "label", "min_ram_gb", "manifest")

    def __init__(self, path: str, engine: str, id: str, label: str, min_ram_gb: float = 0.0,
                 manifest: Optional[dict] = None) -> None:
        self.path = path
        self.engine = engine
        self.id = id
        self.label = label
        self.min_ram_gb = min_ram_gb
        self.manifest = manifest or {}

    def file(self, key: str, default: str = "") -> str:
        name = self.manifest.get(key, default)
        return os.path.join(self.path, name) if name else ""

    def __repr__(self):  # pragma: no cover
        return "ModelInfo(%s, %s)" % (self.id, self.path)


def _is_vosk_dir(path: str) -> bool:
    has_am = os.path.isfile(os.path.join(path, "am", "final.mdl")) or os.path.isfile(os.path.join(path, "final.mdl"))
    has_graph = (os.path.isdir(os.path.join(path, "graph")) or os.path.isfile(os.path.join(path, "HCLG.fst"))
                 or os.path.isfile(os.path.join(path, "HCLr.fst")))
    return has_am and has_graph


def is_model_dir(path: str) -> bool:
    return detect_model(path) is not None


def detect_model(path: str) -> Optional[ModelInfo]:
    """What kind of model (if any) is in ``path``."""
    if not path or not os.path.isdir(path):
        return None
    manifest_path = os.path.join(path, "biverse-model.json")
    if os.path.isfile(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                m = json.load(f)
            mid = m.get("id", os.path.basename(path))
            return ModelInfo(path, m["engine"], mid, m.get("label", LABELS.get(mid, mid)),
                             float(m.get("min_ram_gb", 0)), m)
        except (OSError, ValueError, KeyError):
            log.warning("bad model manifest in %s", path)
    if _is_vosk_dir(path):
        return ModelInfo(path, "vosk", "vosk-small" if "small" in path.lower() else "vosk",
                         "Vosk (%s)" % os.path.basename(path))
    # A sherpa-onnx transducer folder copied by hand (no manifest): guess from the name.
    try:
        files = os.listdir(path)
    except OSError:
        return None
    pick = {}  # type: Dict[str, str]
    for key in ("encoder", "decoder", "joiner"):
        cands = sorted(f for f in files if f.startswith(key) and f.endswith(".onnx"))
        if cands:
            int8 = [c for c in cands if "int8" in c]
            pick[key] = int8[0] if int8 else cands[0]
    if len(pick) == 3 and "tokens.txt" in files:
        base = os.path.basename(path).lower()
        pick["tokens"] = "tokens.txt"
        if "parakeet" in base or "nemo" in base:
            vad = [f for f in files if f.startswith("silero_vad") and f.endswith(".onnx")]
            if vad:
                pick["vad"] = vad[0]
                pick["model_type"] = "nemo_transducer"
                return ModelInfo(path, "sherpa-offline", "parakeet", LABELS["parakeet"], PARAKEET_MIN_RAM_GB, pick)
        elif "streaming" in base or "kroko" in base:
            mid = "kroko" if "kroko" in base else base
            return ModelInfo(path, "sherpa-online", mid, LABELS.get(mid, os.path.basename(path)), 0, pick)
    return None


def discover_models(custom_path: Optional[str] = None) -> List[ModelInfo]:
    """Every usable model in the search folders (spec §6 order), installed packs last."""
    found = []  # type: List[ModelInfo]
    seen = set()
    dirs = paths.model_search_dirs(custom_path or None) + [paths.user_models_dir()]
    for base in dirs:
        candidates = [base]
        if os.path.isdir(base):
            try:
                candidates += [os.path.join(base, c) for c in sorted(os.listdir(base))]
            except OSError:
                pass
        for c in candidates:
            info = detect_model(c)
            if info is None:
                continue
            key = os.path.normcase(os.path.realpath(c))
            if key not in seen:
                seen.add(key)
                found.append(info)
    return found


def engine_available(engine: str) -> bool:
    if engine == "vosk":
        return vosk is not None
    return sherpa() is not None


def choose_model(models: List[ModelInfo], preference: str = "auto", custom_path: str = "",
                 ram_gb: Optional[float] = None, is64: Optional[bool] = None,
                 available=engine_available) -> Tuple[Optional[ModelInfo], str]:
    """Pick a model. Returns ``(model, reason)``; ``model`` is None if nothing fits."""
    usable = [m for m in models if available(m.engine)]
    if preference == "custom" and custom_path:
        target = os.path.normcase(os.path.abspath(custom_path))
        for m in usable:
            if os.path.normcase(os.path.abspath(m.path)) == target:
                return m, "chosen folder"
        info = detect_model(custom_path)
        if info is not None and available(info.engine):
            return info, "chosen folder"
        return None, "the chosen folder is not a supported speech model"
    by_id = {}  # type: Dict[str, ModelInfo]
    for m in usable:
        by_id.setdefault(m.id, m)
    if "kroko" in by_id and "parakeet" in by_id and by_id["kroko"].engine == "sherpa-online":
        by_id["both"] = combined(by_id["kroko"], by_id["parakeet"])
    if preference in by_id:
        return by_id[preference], "chosen in Settings"
    ram = sysinfo.total_ram_gb() if ram_gb is None else ram_gb
    big_ok = (sysinfo.is_64bit() if is64 is None else is64) and (ram is None or ram >= PARAKEET_MIN_RAM_GB)
    note = ""
    if preference not in ("auto", "", "custom"):
        note = "%s is not installed; " % LABELS.get(preference, preference)
    for mid in AUTO_ORDER:
        m = by_id.get(mid)
        if m is None:
            continue
        if mid in ("parakeet", "both") and not big_ok:
            if mid == "parakeet":
                note += "Parakeet needs a 64-bit computer with %d GB+ RAM; " % PARAKEET_MIN_RAM_GB
            continue
        return m, note + "automatic"
    if usable:
        return usable[0], note + "automatic"
    return None, "no speech model found"


# ------------------------------------------------------------------- audio helpers

def pcm_to_floats(pcm: bytes) -> List[float]:
    a = array("h")
    a.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    return [x / 32768.0 for x in a]


class Resampler(object):
    """Streaming resampler to 16 kHz (box-filtered decimation for exact ratios, else linear)."""

    def __init__(self, in_rate: int, out_rate: int = 16000) -> None:
        self.in_rate = int(in_rate)
        self.out_rate = int(out_rate)
        self.step = self.in_rate / float(self.out_rate)
        self.pos = 0.0
        self.last = 0.0
        self._carry = []  # type: List[float]

    def __call__(self, samples: List[float]) -> List[float]:
        if self.in_rate == self.out_rate:
            return samples
        ratio = self.in_rate // self.out_rate
        if ratio * self.out_rate == self.in_rate:  # 48k, 32k: average groups (cheap anti-alias)
            buf = self._carry + samples
            n = len(buf) - len(buf) % ratio
            self._carry = buf[n:]
            return [sum(buf[i:i + ratio]) / ratio for i in range(0, n, ratio)]
        if not samples:
            return []
        out = []
        buf = [self.last] + samples  # index 0 is the previous block's last sample
        pos = self.pos
        limit = len(samples)
        while pos < limit:
            i = int(pos)
            frac = pos - i
            out.append(buf[i] * (1.0 - frac) + buf[i + 1] * frac)
            pos += self.step
        self.pos = pos - limit
        self.last = samples[-1]
        return out


# ------------------------------------------------------------------------- engines

def load_model(path: str):
    """Load a Vosk model (classic engine)."""
    if vosk is None:
        raise RuntimeError("Vosk is not available: %s" % VOSK_ERROR)
    vosk.SetLogLevel(-1)
    return vosk.Model(path)


def make_recognizer(model, samplerate: float, grammar: Optional[str] = None):
    if grammar:
        # Vosk warns once per grammar word missing from the model's vocabulary. Expected.
        vosk.SetLogLevel(-2)
        try:
            rec = vosk.KaldiRecognizer(model, float(samplerate), grammar)
        finally:
            vosk.SetLogLevel(-1)
    else:
        rec = vosk.KaldiRecognizer(model, float(samplerate))
    rec.SetWords(False)
    return rec


def supports_grammar(model_path: Optional[str]) -> bool:
    """Vosk models with a dynamic graph (small and "lgraph") accept a runtime grammar."""
    if not model_path:
        return False
    graph = os.path.join(model_path, "graph")
    return os.path.isfile(os.path.join(graph, "HCLr.fst")) and os.path.isfile(os.path.join(graph, "Gr.fst"))


def reference_grammar() -> str:
    """Vosk grammar (JSON word list) for the reference-only recogniser."""
    from . import books
    from .numbers import TEENS, TENS, UNITS

    words = set()
    for book in books.BOOKS:
        for name in book.spoken + (book.name.lower(),):
            for w in name.replace("'", "").split():
                if not w.isdigit():
                    words.add(w)
    words |= set(UNITS) | set(TEENS) | {w for w in TENS if w != "fourty"}
    words |= {"hundred", "a", "and", "chapter", "chapters", "verse", "verses", "colon", "to", "through",
              "first", "second", "third", "the", "book", "of"}
    return json.dumps(sorted(words) + ["[unk]"])


class VoskEngine(object):
    """Classic Vosk recogniser, plus the optional reference-only grammar recogniser."""

    def __init__(self, info: ModelInfo) -> None:
        self.info = info
        self.model = load_model(info.path)
        self.use_reference = True
        self._grammar = reference_grammar()
        self._rec = None
        self._ref = None
        self._rate = None
        self._partial = ""

    def accept(self, rate: int, pcm: bytes) -> List[Tuple[str, str]]:
        out = []
        if self._rec is None or rate != self._rate:
            self._rec = make_recognizer(self.model, rate)
            self._ref = None
            self._rate = rate
        want_ref = self.use_reference and supports_grammar(self.info.path)
        if want_ref and self._ref is None:
            self._ref = make_recognizer(self.model, rate, self._grammar)
        elif not want_ref:
            self._ref = None
        if self._rec.AcceptWaveform(pcm):
            text = json.loads(self._rec.Result()).get("text", "")
            self._partial = ""
            if text:
                out.append(("final", text))
        else:
            partial = json.loads(self._rec.PartialResult()).get("partial", "")
            if partial != self._partial:
                self._partial = partial
                out.append(("partial", partial))
        if self._ref is not None and self._ref.AcceptWaveform(pcm):
            text = json.loads(self._ref.Result()).get("text", "")
            if text.replace("[unk]", "").strip():
                out.append(("final_ref", text))
        return out

    def finish(self) -> List[Tuple[str, str]]:
        out = []
        if self._rec is not None:
            text = json.loads(self._rec.FinalResult()).get("text", "")
            if text:
                out.append(("final", text))
        if self._ref is not None:
            text = json.loads(self._ref.FinalResult()).get("text", "")
            if text.replace("[unk]", "").strip():
                out.append(("final_ref", text))
        self._rec = self._ref = None
        return out


def book_hotwords(tokens_path: str) -> Tuple[str, str]:
    """Write a hotwords file of book names and a BPE vocab for a sherpa-onnx model.

    Measured on 528 clips (66 books x 4 voices): +1.5 points for Kroko, -0.6
    for Parakeet, no false alarms either way; so only Kroko uses it (DECISIONS.md).
    Returns ``(hotwords_path, bpe_vocab_path)`` in the settings folder.
    """
    from . import books
    toks = []
    with open(tokens_path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if parts:
                toks.append(parts[0])
    lower = sum(t.islower() for t in toks) >= sum(t.isupper() for t in toks)
    names = set()
    for b in books.BOOKS:
        for n in (b.name,) + b.spoken:
            n = n.replace("'", "")
            if n[:1].isdigit():
                n = n[2:]
            if len(n) > 3:
                names.add(n.lower() if lower else n.upper())
    folder = os.path.join(paths.config_dir(), "hotwords")
    os.makedirs(folder, exist_ok=True)
    tag = os.path.basename(os.path.dirname(os.path.abspath(tokens_path)))
    vocab = os.path.join(folder, tag + ".vocab")
    hotwords = os.path.join(folder, tag + ".hotwords.txt")
    with open(vocab, "w", encoding="utf-8") as f:
        for t in toks:
            if not t.startswith("<"):
                f.write("%s\t0\n" % t)
    with open(hotwords, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(names)) + "\n")
    return hotwords, vocab


class SherpaOnlineEngine(object):
    """Streaming transducer (Kroko): partial results while speaking, final at each pause."""

    def __init__(self, info: ModelInfo, num_threads: int = 2) -> None:
        so = sherpa()
        if so is None:
            raise RuntimeError("sherpa-onnx is not available: %s" % SHERPA_ERROR)
        self.info = info
        kwargs = dict(
            tokens=info.file("tokens", "tokens.txt"), encoder=info.file("encoder", "encoder.onnx"),
            decoder=info.file("decoder", "decoder.onnx"), joiner=info.file("joiner", "joiner.onnx"),
            num_threads=num_threads, enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4, rule2_min_trailing_silence=0.8, rule3_min_utterance_length=20.0)
        hot = None
        if info.manifest.get("hotwords", info.id == "kroko"):
            try:
                hot = book_hotwords(info.file("tokens", "tokens.txt"))
            except Exception:
                log.warning("could not prepare hotwords for %s", info.label, exc_info=True)
        if hot is not None:
            try:
                self.rec = so.OnlineRecognizer.from_transducer(
                    decoding_method="modified_beam_search", max_active_paths=4, hotwords_file=hot[0],
                    hotwords_score=1.5, modeling_unit="bpe", bpe_vocab=hot[1], **kwargs)
            except Exception:
                log.warning("hotwords rejected by %s; using plain decoding", info.label, exc_info=True)
                hot = None
        if hot is None:
            self.rec = so.OnlineRecognizer.from_transducer(**kwargs)
        self.stream = self.rec.create_stream()
        self._partial = ""
        self._resampler = None  # type: Optional[Resampler]
        self._rate = None

    def accept(self, rate: int, pcm: bytes) -> List[Tuple[str, str]]:
        # Always feed 16 kHz: sherpa-onnx aborts the process if a stream's rate changes,
        # and it would log every time it creates its own resampler.
        if rate != self._rate or self._resampler is None:
            self._resampler = Resampler(rate, 16000)
            self._rate = rate
        self.stream.accept_waveform(16000, self._resampler(pcm_to_floats(pcm)))
        out = []
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
        text = _result_text(self.rec.get_result(self.stream))
        if self.rec.is_endpoint(self.stream):
            if text:
                out.append(("final", text))
            self.rec.reset(self.stream)
            self._partial = ""
        elif text != self._partial:
            self._partial = text
            out.append(("partial", text))
        return out

    def finish(self) -> List[Tuple[str, str]]:
        # 1.5 s of silence: the streaming model looks ahead before committing the last word
        self.stream.accept_waveform(16000, [0.0] * 24000)
        self.stream.input_finished()
        while self.rec.is_ready(self.stream):
            self.rec.decode_stream(self.stream)
        text = _result_text(self.rec.get_result(self.stream))
        self.stream = self.rec.create_stream()
        self._partial = ""
        return [("final", text)] if text else []


class SherpaOfflineEngine(object):
    """Whole-phrase model (Parakeet): the VAD cuts speech at pauses, each phrase is decoded."""

    WINDOW = 512

    def __init__(self, info: ModelInfo, num_threads: int = 2) -> None:
        so = sherpa()
        if so is None:
            raise RuntimeError("sherpa-onnx is not available: %s" % SHERPA_ERROR)
        self.info = info
        self.rec = so.OfflineRecognizer.from_transducer(
            encoder=info.file("encoder"), decoder=info.file("decoder"), joiner=info.file("joiner"),
            tokens=info.file("tokens", "tokens.txt"), num_threads=num_threads,
            model_type=info.manifest.get("model_type", "nemo_transducer"))
        cfg = so.VadModelConfig()
        cfg.silero_vad.model = info.file("vad", "silero_vad.onnx")
        cfg.silero_vad.min_silence_duration = 0.45
        cfg.silero_vad.min_speech_duration = 0.25
        cfg.silero_vad.max_speech_duration = 12.0
        cfg.silero_vad.threshold = 0.5
        cfg.silero_vad.window_size = self.WINDOW
        cfg.sample_rate = 16000
        cfg.num_threads = 1
        self.vad = so.VoiceActivityDetector(cfg, buffer_size_in_seconds=60)
        self._resampler = None  # type: Optional[Resampler]
        self._rate = None
        self._buf = []  # type: List[float]
        self._speaking = False

    def accept(self, rate: int, pcm: bytes) -> List[Tuple[str, str]]:
        if rate != self._rate or self._resampler is None:
            self._resampler = Resampler(rate, 16000)
            self._rate = rate
        self._buf.extend(self._resampler(pcm_to_floats(pcm)))
        out = []
        n = len(self._buf) - len(self._buf) % self.WINDOW
        for i in range(0, n, self.WINDOW):
            self.vad.accept_waveform(self._buf[i:i + self.WINDOW])
        self._buf = self._buf[n:]
        speaking = self.vad.is_speech_detected()
        if speaking and not self._speaking:
            out.append(("partial", u"…"))
        self._speaking = speaking
        out.extend(self._segments())
        return out

    def _segments(self) -> List[Tuple[str, str]]:
        out = []
        while not self.vad.empty():
            samples = self.vad.front.samples
            self.vad.pop()
            stream = self.rec.create_stream()
            stream.accept_waveform(16000, samples)
            self.rec.decode_stream(stream)
            text = _result_text(stream.result)
            if text:
                out.append(("final", text))
        return out

    def finish(self) -> List[Tuple[str, str]]:
        self.vad.flush()
        out = self._segments()
        self.vad.reset()
        self._buf = []
        self._speaking = False
        return out


def _result_text(result) -> str:
    text = result if isinstance(result, str) else getattr(result, "text", "")
    return (text or "").strip()


class DualEngine(object):
    """Kroko gives live words and fast detections; Parakeet re-hears each phrase at the
    pause and confirms (or catches what Kroko missed). The detector merges both:
    duplicates are dropped and a fuller reference updates the earlier one."""

    def __init__(self, info: ModelInfo, num_threads: int = 2) -> None:
        live, confirm = info.manifest["parts"]
        self.info = info
        self.live = SherpaOnlineEngine(live, num_threads)
        self.confirm = SherpaOfflineEngine(confirm, num_threads)

    @staticmethod
    def _merge(live_events, confirm_events) -> List[Tuple[str, str]]:
        out = []
        for kind, text in live_events:
            if kind == "partial":
                out.append(("partial", text))
            elif kind == "final":
                out.append(("partial", text))      # stays grey until Parakeet's version arrives
                out.append(("final_live", text))
        for kind, text in confirm_events:
            if kind == "final":
                out.append(("final", text))
        return out

    def accept(self, rate: int, pcm: bytes) -> List[Tuple[str, str]]:
        return self._merge(self.live.accept(rate, pcm), self.confirm.accept(rate, pcm))

    def finish(self) -> List[Tuple[str, str]]:
        return self._merge(self.live.finish(), self.confirm.finish())


def create_engine(info: ModelInfo, num_threads: int = 2):
    if info.engine == "dual":
        return DualEngine(info, num_threads)
    if info.engine == "vosk":
        return VoskEngine(info)
    if info.engine == "sherpa-online":
        return SherpaOnlineEngine(info, num_threads)
    if info.engine == "sherpa-offline":
        return SherpaOfflineEngine(info, num_threads)
    raise ValueError("unknown engine %r" % info.engine)


def transcribe(engine, rate: int, pcm: bytes, block_seconds: float = 0.2) -> List[str]:
    """Feed raw mono int16 PCM through an engine; return the final texts (tests, self-test)."""
    block = max(2, int(rate * block_seconds)) * 2
    finals = []
    for i in range(0, len(pcm), block):
        finals += [t for k, t in engine.accept(rate, pcm[i:i + block]) if k == "final"]
    finals += [t for k, t in engine.finish() if k == "final"]
    return finals


def transcribe_pcm(model, samplerate: int, pcm: bytes, chunk: int = 8000) -> List[str]:
    """Vosk-only helper (classic engine tests)."""
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


def find_model(user_path: Optional[str] = None, engine: Optional[str] = None) -> Optional[str]:
    """Path of a model: the one "automatic" would choose, or the first of ``engine``."""
    models = discover_models(user_path)
    if engine:
        for m in models:
            if m.engine == engine:
                return m.path
        return None
    info, _ = choose_model(models, "custom" if user_path else "auto", user_path or "")
    return info.path if info else None


# ------------------------------------------------------------------- the service

class SpeechEngine(object):
    def __init__(self, events: "queue.Queue", detector: Detector) -> None:
        self.events = events
        self.detector = detector
        self.audio_queue = queue.Queue(maxsize=50)  # ~10 s of 0.2 s blocks
        self.engine = None
        self.info = None  # type: Optional[ModelInfo]
        self.state = "none"  # none | loading | ready | missing | error
        self.reason = ""
        self._loader = None  # type: Optional[threading.Thread]
        self._worker = None  # type: Optional[threading.Thread]
        self._stop = threading.Event()
        self._load_token = 0
        self._use_reference = True
        self.commands = True  # spoken "next verse", "go back"...

    @property
    def model_path(self) -> Optional[str]:
        return self.info.path if self.info else None

    @property
    def model_label(self) -> str:
        return self.info.label if self.info else ""

    @property
    def use_reference(self) -> bool:
        return self._use_reference

    @use_reference.setter
    def use_reference(self, value: bool) -> None:
        self._use_reference = bool(value)
        if isinstance(self.engine, VoskEngine):
            self.engine.use_reference = self._use_reference

    def set_engine(self, engine, info: Optional[ModelInfo] = None) -> None:
        """Use an already-created engine (tests, tools)."""
        self.engine = engine
        self.info = info or getattr(engine, "info", None)
        self.state = "ready"

    # model ---------------------------------------------------------------------------
    def load(self, preference: str = "auto", custom_path: str = "") -> None:
        """Choose and load a model in the background (replaces any loaded model)."""
        self._load_token += 1
        token = self._load_token
        info, reason = choose_model(discover_models(custom_path or None), preference, custom_path)
        self.reason = reason
        if info is None:
            self.state = "missing"
            self.engine = None
            self.info = None
            detail = reason
            if SHERPA_ERROR:
                detail += " (sherpa-onnx could not load: %s)" % SHERPA_ERROR
            self.events.put(("model", "missing", detail))
            return
        self.state = "loading"
        self.events.put(("model", "loading", info.label))

        def work():
            t = time.monotonic()
            try:
                engine = create_engine(info)
            except Exception as exc:
                log.exception("model load failed")
                if token == self._load_token:
                    self.state = "error"
                    self.events.put(("model", "error", "%s: %s" % (info.label, exc)))
                return
            if token != self._load_token:
                return
            if isinstance(engine, VoskEngine):
                engine.use_reference = self._use_reference
            self.engine = engine
            self.info = info
            self.state = "ready"
            log.info("speech model %s (%s) loaded in %.1f s [%s]", info.label, info.path,
                     time.monotonic() - t, reason)
            self.events.put(("model", "ready", info.label))

        self._loader = threading.Thread(target=work, name="model-loader", daemon=True)
        self._loader.start()

    # recognition -----------------------------------------------------------------------
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

    def stop(self, timeout: float = 3.0) -> None:
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
        engine = None
        while not self._stop.is_set():
            try:
                rate, data = self.audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            engine = self.engine
            if engine is None:
                continue  # model still loading: drop audio
            try:
                for kind, text in engine.accept(rate, data):
                    self._emit(kind, text)
            except Exception as exc:
                log.exception("recogniser error")
                self.events.put(("error", "speech recognition error: %s" % exc))
        if engine is not None:
            try:
                for kind, text in engine.finish():
                    self._emit(kind, text)
            except Exception:
                log.exception("recogniser flush failed")

    def _emit(self, kind: str, text: str) -> None:
        if kind == "partial":
            self.events.put(("partial", text))
            return
        if kind == "final_ref":  # Vosk reference listener: detections only
            events = self.detector.feed_final(text, channel=REFERENCE)
        elif kind == "final_live":  # Kroko inside the dual engine: not shown, Parakeet's line is
            events = self.detector.feed_final(text, channel="live")
            self._command(text, "live")
        else:
            self.events.put(("final", text))
            events = self.detector.feed_final(text)
            self._command(text, "main")
        try:
            for k, det in events:
                self.events.put(("detect", k, det))
        except Exception:
            log.exception("detector error on %r", text)

    def _command(self, text: str, channel: str) -> None:
        if not self.commands:
            return
        cmd = parse_command(text)
        if cmd is not None:
            self.events.put(("command", cmd, channel, time.monotonic(), text))
