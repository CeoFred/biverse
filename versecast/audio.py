"""Audio input: device listing, capture, downmix to mono and level metering.

Uses sounddevice's ``RawInputStream`` (int16, ~0.2 s blocks) and the stdlib
``array`` module; no numpy. Blocks go to a bounded queue for the recogniser
thread; when that queue is full the oldest audio is dropped rather than
blocking PortAudio's callback.
"""

from __future__ import annotations

import logging
import math
import queue
import sys
import threading
import time
from array import array
from typing import List, Optional

log = logging.getLogger(__name__)

try:  # sounddevice needs PortAudio; on Linux that is the libportaudio2 package
    import sounddevice as sd
    SD_ERROR = None  # type: Optional[str]
except Exception as exc:  # pragma: no cover - depends on the machine
    sd = None
    SD_ERROR = str(exc)

BLOCK_SECONDS = 0.2
HIDDEN_HOSTAPIS_WINDOWS = ("Windows DirectSound", "Windows WDM-KS")


class InputDevice(object):
    __slots__ = ("index", "name", "hostapi", "channels", "samplerate", "is_default")

    def __init__(self, index: int, name: str, hostapi: str, channels: int, samplerate: float,
                 is_default: bool = False) -> None:
        self.index = index
        self.name = name
        self.hostapi = hostapi
        self.channels = channels
        self.samplerate = samplerate
        self.is_default = is_default

    def label(self) -> str:
        return u"%s — %s" % (self.name, self.hostapi)

    def key(self) -> dict:
        return {"name": self.name, "hostapi": self.hostapi}

    def __repr__(self):  # pragma: no cover
        return "InputDevice(%d, %r)" % (self.index, self.label())


def available() -> bool:
    return sd is not None


def refresh_portaudio() -> None:
    """Re-scan devices (sounddevice caches the list; hot-plugged USB mics need this)."""
    if sd is None:
        return
    try:
        sd._terminate()
    except Exception:
        pass
    try:
        sd._initialize()
    except Exception:
        log.exception("PortAudio re-initialise failed")


def list_input_devices(refresh: bool = False) -> List[InputDevice]:
    if sd is None:
        return []
    if refresh:
        refresh_portaudio()
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        log.exception("query_devices failed")
        return []
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = -1
    out = []
    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) <= 0:
            continue
        api = hostapis[dev["hostapi"]]["name"] if dev["hostapi"] < len(hostapis) else "?"
        if sys.platform == "win32" and api in HIDDEN_HOSTAPIS_WINDOWS:
            continue
        out.append(InputDevice(idx, dev["name"], api, int(dev["max_input_channels"]),
                               float(dev.get("default_samplerate") or 16000), idx == default_in))
    return out


def default_device(devices: List[InputDevice]) -> Optional[InputDevice]:
    for d in devices:
        if d.is_default:
            return d
    if sd is not None:
        # on Windows the default may be a hidden DirectSound device: match by name
        try:
            default_name = sd.query_devices(kind="input")["name"]
            for d in devices:
                if default_name.startswith(d.name) or d.name.startswith(default_name):
                    return d
        except Exception:
            pass
    return devices[0] if devices else None


def find_device(devices: List[InputDevice], saved: Optional[dict]) -> Optional[InputDevice]:
    if not saved or not saved.get("name"):
        return None
    for d in devices:
        if d.name == saved.get("name") and d.hostapi == saved.get("hostapi"):
            return d
    for d in devices:
        if d.name == saved.get("name"):
            return d
    return None


def downmix(data: bytes, channels: int) -> bytes:
    """Interleaved int16 -> mono int16 by averaging channels (stdlib only)."""
    if channels <= 1:
        return data
    a = array("h")
    a.frombytes(data[: len(data) - len(data) % (2 * channels)])
    if channels == 2:
        mono = array("h", [(x + y) >> 1 for x, y in zip(a[0::2], a[1::2])])
    else:
        cols = [a[i::channels] for i in range(channels)]
        mono = array("h", [sum(s) // channels for s in zip(*cols)])
    return mono.tobytes()


def peak(data: bytes) -> int:
    a = array("h")
    a.frombytes(data[: len(data) - len(data) % 2])
    if not a:
        return 0
    return max(max(a), -min(a))


def peak_to_level(p: int) -> float:
    """Peak sample (0..32768) to a 0..100 meter value on a 60 dB scale."""
    if p <= 0:
        return 0.0
    db = 20.0 * math.log10(min(p, 32768) / 32768.0)
    return max(0.0, min(100.0, (db + 60.0) / 60.0 * 100.0))


class AudioCapture(object):
    """Captures from one device; puts ``(samplerate, mono_int16_bytes)`` on ``out_queue``."""

    def __init__(self, out_queue: "queue.Queue") -> None:
        self.out_queue = out_queue
        self.stream = None
        self.device = None  # type: Optional[InputDevice]
        self.channels = 1
        self.samplerate = 16000
        self.error = None  # type: Optional[str]
        self._peak = 0
        self._level = 0.0
        self._last_data = 0.0
        self._lock = threading.Lock()
        self._token = 0
        self.opening = False
        self.dropped = 0

    @property
    def running(self) -> bool:
        return self.stream is not None

    def _open(self, device: InputDevice):
        """Open and start a stream; returns (stream, channels, rate). May block (see start_async)."""
        if sd is None:
            raise RuntimeError("audio unavailable: %s" % SD_ERROR)
        rate = int(device.samplerate) or 16000
        block = max(256, int(rate * BLOCK_SECONDS))
        last_exc = None
        for channels in _channel_options(device.channels):
            try:
                stream = sd.RawInputStream(device=device.index, samplerate=rate, channels=channels,
                                           dtype="int16", blocksize=block, callback=self._callback,
                                           finished_callback=self._finished)
            except Exception as exc:
                last_exc = exc
                log.info("open %s with %d channel(s) failed: %s", device.label(), channels, exc)
                continue
            # set before start(): the callback needs to know the channel count
            self.channels = channels
            self.samplerate = rate
            try:
                stream.start()
            except Exception as exc:
                last_exc = exc
                _close(stream)
                continue
            return stream, channels, rate
        raise RuntimeError("cannot open %s: %s" % (device.label(), last_exc))

    def start(self, device: InputDevice) -> None:
        """Open synchronously (tests, tools). The UI uses start_async."""
        self.stop()
        self._token += 1
        self.device = device
        self.error = None
        stream, channels, rate = self._open(device)
        self._attach(stream, channels, rate, self._token)

    def _attach(self, stream, channels: int, rate: int, token: int) -> bool:
        with self._lock:
            if token != self._token:
                stale = True
            else:
                stale = False
                self.stream = stream
                self.channels = channels
                self.samplerate = rate
                self._last_data = time.monotonic()
        if stale:
            _close(stream)
            return False
        log.info("capturing %s at %d Hz, %d channel(s)", self.device.label() if self.device else "?", rate,
                 channels)
        return True

    def start_async(self, device: InputDevice, notify, timeout: float = 8.0) -> None:
        """Open ``device`` in a worker thread so the UI never blocks.

        PortAudio's open can block for a long time (macOS waiting for microphone
        permission, a Bluetooth headset switching profile, a wedged driver).
        ``notify(ok, message)`` is called from a worker thread: once on success
        or failure, and also with ``ok=False`` if opening takes longer than
        ``timeout`` (a late success is still attached and reported).
        """
        self.stop()
        with self._lock:
            self._token += 1
            token = self._token
        self.device = device
        self.error = None
        self.opening = True
        state = {"done": False}

        def on_timeout():
            if not state["done"] and token == self._token:
                hint = (" On macOS, check System Settings \u2192 Privacy & Security \u2192 Microphone."
                        if sys.platform == "darwin" else "")
                notify(False, "%s is not responding.%s" % (device.name, hint))

        timer = threading.Timer(timeout, on_timeout)
        timer.daemon = True

        def work():
            try:
                stream, channels, rate = self._open(device)
            except Exception as exc:
                state["done"] = True
                timer.cancel()
                if token == self._token:
                    self.opening = False
                    notify(False, str(exc))
                return
            state["done"] = True
            timer.cancel()
            attached = self._attach(stream, channels, rate, token)
            if attached:
                self.opening = False
                notify(True, device.label())

        timer.start()
        threading.Thread(target=work, name="audio-open", daemon=True).start()

    def _callback(self, indata, frames, time_info, status) -> None:
        try:
            data = bytes(indata)
            if self.channels > 1:
                data = downmix(data, self.channels)
            p = peak(data)
            with self._lock:
                self._peak = max(self._peak, p)
            self._last_data = time.monotonic()
            try:
                self.out_queue.put_nowait((self.samplerate, data))
            except queue.Full:
                try:
                    self.out_queue.get_nowait()
                except queue.Empty:
                    pass
                self.dropped += 1
                try:
                    self.out_queue.put_nowait((self.samplerate, data))
                except queue.Full:
                    pass
        except Exception:  # never let an exception escape into PortAudio
            log.exception("audio callback error")

    def _finished(self) -> None:
        if self.stream is not None and self.error is None:
            self.error = "the audio stream stopped (device unplugged?)"

    def level(self) -> float:
        """Smoothed level 0..100: fast attack, slow release. Call ~20x a second."""
        with self._lock:
            p = self._peak
            self._peak = 0
        target = peak_to_level(p)
        if target > self._level:
            self._level = target
        else:
            self._level = self._level * 0.8 + target * 0.2
        return self._level

    def healthy(self) -> bool:
        if self.stream is None:
            return True
        if self.error:
            return False
        try:
            if not self.stream.active:
                self.error = self.error or "the audio stream is no longer active"
                return False
        except Exception:
            self.error = "the audio stream failed"
            return False
        if time.monotonic() - self._last_data > 3.0:
            self.error = "no audio received for 3 seconds (device unplugged?)"
            return False
        return True

    def stop(self) -> None:
        with self._lock:
            self._token += 1  # cancels an open in progress
            stream, self.stream = self.stream, None
        self.opening = False
        if stream is not None:
            _close(stream)
        self._level = 0.0
        self._peak = 0


def _close(stream) -> None:
    try:
        stream.abort()
    except Exception:
        pass
    try:
        stream.close()
    except Exception:
        pass


def _channel_options(max_channels: int) -> List[int]:
    opts = [1]
    if max_channels >= 2:
        opts.append(2)
    if max_channels > 2:
        opts.append(max_channels)
    return opts
