"""Model downloads started from Settings -> Models.

The operator window owns one ``DownloadManager``, so a download keeps going
when the Settings window is closed. Each download runs ``catalog.install`` on
its own thread; the UI polls ``Job`` for progress and gets ``on_finish(job)``
(called on the worker thread) when it ends.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, List, Optional

from . import catalog, paths, sysinfo

log = logging.getLogger(__name__)


class Item(object):
    """One downloadable model as the Models tab shows it."""

    __slots__ = ("id", "label", "kind", "about", "platforms")

    def __init__(self, id: str, label: str, kind: str, about: str, platforms: Optional[List[str]] = None) -> None:
        self.id, self.label, self.kind, self.about, self.platforms = id, label, kind, about, platforms

    def size(self) -> int:
        return catalog.download_size(self.id, self.platforms)


def items() -> List[Item]:
    from . import llm
    return [
        Item("kroko", "Kroko", "speech", "Live speech recognition. Fast and light. Built into Biverse."),
        Item("parakeet", "Parakeet", "speech", "The most accurate speech model, by far the best with African "
             "and other accents. Needs a 64-bit computer with about 6 GB of RAM."),
        Item("vosk-small", "Classic (Vosk small)", "speech", "For older computers where the others do not run."),
        Item("ai-summary", "AI sermon summary", "ai", "Writes a short summary of the sermon on this computer. "
             "Needs about 8 GB of RAM.", platforms=[llm.platform_key()]),
    ]


def item(item_id: str) -> Item:
    for it in items():
        if it.id == item_id:
            return it
    raise KeyError(item_id)


class Status(object):
    __slots__ = ("installed", "can_download", "note")

    def __init__(self, installed: bool, can_download: bool, note: str = "") -> None:
        self.installed, self.can_download, self.note = installed, can_download, note


def status(it: Item) -> Status:
    """Is ``it`` installed, and can this computer download and run it?"""
    from . import llm, recognizer
    if it.kind == "ai":
        reason = llm.unsupported_reason()
        if llm.find_pack() is not None:
            return Status(True, False, "" if not reason else reason)
        if reason:
            return Status(False, False, reason)
        return Status(False, True, llm.platform_warning())
    installed = any(m.id == it.id for m in recognizer.discover_models())
    engine = catalog.MODELS[it.id]["manifest"]["engine"]
    if not recognizer.engine_available(engine):
        return Status(installed, False, "this copy of Biverse cannot run it")
    if it.id == "parakeet":
        if not sysinfo.is_64bit():
            return Status(installed, False, "needs the 64-bit version of Biverse")
        ram = sysinfo.total_ram_gb()
        if ram is not None and ram < recognizer.PARAKEET_MIN_RAM_GB:
            return Status(installed, True, "this computer has %.0f GB of RAM; Parakeet needs about %d GB"
                          % (ram, recognizer.PARAKEET_MIN_RAM_GB))
    return Status(installed, True)


class Job(object):
    """A running or finished download. Fields are read by the UI thread."""

    def __init__(self, it: Item) -> None:
        self.item = it
        self.done = 0
        self.total = it.size()
        self.stage = "starting"
        self.state = "running"  # running | done | failed | cancelled
        self.error = ""
        self.path = ""
        self.cancel_event = threading.Event()
        self._samples = []  # type: List[tuple]

    def update(self, done: int, total: int, stage: str) -> None:
        self.done, self.total, self.stage = done, total or self.total, stage
        now = time.monotonic()
        self._samples.append((now, done))
        while len(self._samples) > 2 and now - self._samples[0][0] > 5:
            self._samples.pop(0)

    def fraction(self) -> float:
        return min(1.0, self.done / float(self.total)) if self.total else 0.0

    def speed(self) -> float:
        """Bytes per second over the last few seconds (0 if unknown)."""
        if self.stage != "download" or len(self._samples) < 2:
            return 0.0
        (t0, d0), (t1, d1) = self._samples[0], self._samples[-1]
        return (d1 - d0) / (t1 - t0) if t1 > t0 and d1 > d0 else 0.0

    def describe(self) -> str:
        """One line for the UI, e.g. "Downloading 120 of 483 MB (25%) - 3.1 MB/s, about 2 min left"."""
        if self.state == "done":
            return "Installed"
        if self.state == "cancelled":
            return "Cancelled. Press Download to continue where it stopped."
        if self.state == "failed":
            return "Failed: %s" % self.error
        if self.stage == "check":
            return "Checking the download…"
        if self.stage == "unpack":
            return "Installing…"
        if self.stage != "download":
            return "Starting…"
        text = "Downloading %s of %s (%d%%)" % (mb(self.done), mb(self.total), int(self.fraction() * 100))
        rate = self.speed()
        if rate > 0:
            left = (self.total - self.done) / rate
            text += " · %.1f MB/s, %s left" % (rate / 1e6, _duration(left))
        return text


def mb(n: int) -> str:
    return "%.1f GB" % (n / 1e9) if n >= 1e9 else "%.0f MB" % (n / 1e6)


def _duration(seconds: float) -> str:
    if seconds < 60:
        return "under a minute"
    if seconds < 3600:
        return "about %d min" % round(seconds / 60.0)
    return "about %.1f h" % (seconds / 3600.0)


class DownloadManager(object):
    def __init__(self, on_finish: Optional[Callable[[Job], None]] = None,
                 dest: Optional[str] = None, cache: Optional[str] = None) -> None:
        self.on_finish = on_finish
        self.dest = dest
        self.cache = cache
        self.jobs = {}  # type: dict

    def job(self, item_id: str) -> Optional[Job]:
        return self.jobs.get(item_id)

    def running(self) -> List[Job]:
        return [j for j in self.jobs.values() if j.state == "running"]

    def start(self, item_id: str) -> Job:
        old = self.jobs.get(item_id)
        if old is not None and old.state == "running":
            return old
        job = Job(item(item_id))
        self.jobs[item_id] = job
        threading.Thread(target=self._run, args=(job,), name="download-" + item_id, daemon=True).start()
        return job

    def cancel(self, item_id: str) -> None:
        job = self.jobs.get(item_id)
        if job is not None and job.state == "running":
            job.cancel_event.set()

    def cancel_all(self) -> None:
        for job in self.running():
            job.cancel_event.set()

    def _run(self, job: Job) -> None:
        dest = self.dest or paths.user_models_dir()
        cache = self.cache or catalog.default_cache()
        it = job.item
        try:
            catalog.check_disk_space(it.id, dest, cache, it.platforms)
            job.path = catalog.install(it.id, dest, cache, force=True, progress=job.update,
                                       cancel=job.cancel_event, platforms=it.platforms, keep_cache=False)
            job.state = "done"
            log.info("downloaded %s", it.id)
        except catalog.Cancelled:
            job.state = "cancelled"
            log.info("download of %s cancelled", it.id)
        except catalog.DownloadError as exc:
            job.state, job.error = "failed", str(exc)
            log.warning("download of %s failed: %s", it.id, exc)
        except Exception as exc:
            job.state, job.error = "failed", str(exc) or exc.__class__.__name__
            log.exception("download of %s failed", it.id)
        if self.on_finish is not None:
            try:
                self.on_finish(job)
            except Exception:
                log.exception("download callback")
