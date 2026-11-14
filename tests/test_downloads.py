"""Model downloads (Settings -> Models), against a local HTTP server."""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import os
import tarfile
import threading

import pytest

from biverse import catalog, downloads


class _Handler(http.server.BaseHTTPRequestHandler):
    files = {}  # type: dict
    hits = []  # type: list

    def log_message(self, *args):
        pass

    def do_GET(self):
        data = self.files.get(self.path)
        rng = self.headers.get("Range")
        self.hits.append((self.path, rng))
        if data is None:
            self.send_response(404)
            self.end_headers()
            return
        start = 0
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, len(data) - 1, len(data)))
        else:
            self.send_response(200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    _Handler.files = {}
    _Handler.hits = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def _tar(top, files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo("%s/%s" % (top, name))
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def fake_model(server, monkeypatch):
    """A 'vosk-small' spec served from the local server."""
    top = "fake-model"
    payload = os.urandom(300000)
    data = _tar(top, {"am/final.mdl": payload, "conf/model.conf": b"x", "test_wavs/a.wav": b"w"})
    _Handler.files["/fake.tar.bz2"] = data
    spec = {"dir": top, "url": server + "/fake.tar.bz2", "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "manifest": {"engine": "vosk", "id": "vosk-small", "label": "Fake"}}
    monkeypatch.setitem(catalog.MODELS, "vosk-small", spec)
    return spec


def test_install_downloads_verifies_and_reports_progress(tmp_path, fake_model):
    seen = []
    path = catalog.install("vosk-small", str(tmp_path / "models"), str(tmp_path / "cache"),
                           progress=lambda d, t, s: seen.append((d, t, s)), keep_cache=False)
    assert json.load(open(os.path.join(path, "biverse-model.json")))["engine"] == "vosk"
    assert os.path.isfile(os.path.join(path, "am", "final.mdl"))
    assert not os.path.exists(os.path.join(path, "test_wavs"))
    assert seen[-1] == (fake_model["size"], fake_model["size"], "done")
    assert {s for _d, _t, s in seen} >= {"download", "check", "unpack", "done"}
    assert [d for d, _t, _s in seen] == sorted(d for d, _t, _s in seen)
    assert os.listdir(str(tmp_path / "cache")) == []  # archive removed after install
    assert [n for n in os.listdir(str(tmp_path / "models")) if n.startswith(".install-")] == []


def test_download_resumes_from_part_file(tmp_path, fake_model):
    data = _Handler.files["/fake.tar.bz2"]
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "fake.tar.bz2.part").write_bytes(data[:1000])
    catalog.install("vosk-small", str(tmp_path / "models"), str(cache))
    assert _Handler.hits == [("/fake.tar.bz2", "bytes=1000-")]


def test_checksum_mismatch_installs_nothing(tmp_path, fake_model, monkeypatch):
    monkeypatch.setitem(fake_model, "sha256", "0" * 64)
    with pytest.raises(catalog.DownloadError, match="damaged"):
        catalog.install("vosk-small", str(tmp_path / "models"), str(tmp_path / "cache"))
    assert not os.path.exists(str(tmp_path / "models" / "fake-model"))
    assert os.listdir(str(tmp_path / "cache")) == []


def test_cancel_keeps_part_file_for_later(tmp_path, fake_model):
    cancel = threading.Event()

    def progress(done, total, stage):
        if stage == "download":
            cancel.set()

    with pytest.raises(catalog.Cancelled):
        catalog.install("vosk-small", str(tmp_path / "models"), str(tmp_path / "cache"),
                        progress=progress, cancel=cancel)
    assert not os.path.exists(str(tmp_path / "models" / "fake-model"))
    assert os.path.exists(str(tmp_path / "cache" / "fake.tar.bz2.part"))


def test_archive_escaping_its_folder_is_refused(tmp_path, server, monkeypatch):
    data = _tar("fake-model", {"../../evil.txt": b"x"})
    _Handler.files["/evil.tar.bz2"] = data
    monkeypatch.setitem(catalog.MODELS, "vosk-small", {
        "dir": "fake-model", "url": server + "/evil.tar.bz2", "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "manifest": {"engine": "vosk", "id": "vosk-small"}})
    with pytest.raises(catalog.DownloadError, match="unexpected path"):
        catalog.install("vosk-small", str(tmp_path / "models"), str(tmp_path / "cache"))
    assert not os.path.exists(str(tmp_path / "evil.txt"))


def test_unreachable_server_explains(tmp_path, monkeypatch):
    monkeypatch.setitem(catalog.MODELS, "vosk-small", {
        "dir": "x", "url": "http://127.0.0.1:9/none.zip", "size": 10, "sha256": "0" * 64,
        "manifest": {"engine": "vosk", "id": "vosk-small"}})
    with pytest.raises(catalog.DownloadError, match="internet connection"):
        catalog.fetch_verified("http://127.0.0.1:9/none.zip", 10, "0" * 64, str(tmp_path), attempts=1)


def test_manager_runs_in_background_and_reports(tmp_path, fake_model, monkeypatch):
    done = threading.Event()
    finished = []

    def on_finish(job):
        finished.append(job)
        done.set()

    mgr = downloads.DownloadManager(on_finish, dest=str(tmp_path / "models"), cache=str(tmp_path / "cache"))
    job = mgr.start("vosk-small")
    assert mgr.start("vosk-small") is job  # one download per model at a time
    assert done.wait(30)
    assert finished == [job] and job.state == "done" and job.describe() == "Installed"
    assert os.path.isfile(os.path.join(job.path, "biverse-model.json"))


def test_not_enough_disk_space(tmp_path, monkeypatch):
    import shutil
    monkeypatch.setattr(shutil, "disk_usage", lambda p: type("U", (), {"free": 10})())
    with pytest.raises(catalog.DownloadError, match="disk space"):
        catalog.check_disk_space("parakeet", str(tmp_path), str(tmp_path))


def test_ai_summary_not_offered_where_it_cannot_run(monkeypatch):
    from biverse import llm
    monkeypatch.setattr(llm, "unsupported_reason", lambda: "The AI summary needs Windows 10 or later.")
    monkeypatch.setattr(llm, "find_pack", lambda: None)
    st = downloads.status(downloads.item("ai-summary"))
    assert not st.installed and not st.can_download and "Windows 10" in st.note


def test_ai_summary_downloads_only_this_platform():
    it = downloads.item("ai-summary")
    urls = [u for u, _s, _h in catalog.files_for("ai-summary", it.platforms)]
    assert len(urls) == 2 and urls[0].endswith(".gguf")


def test_parakeet_needs_64_bit(monkeypatch):
    from biverse import recognizer, sysinfo
    monkeypatch.setattr(sysinfo, "is_64bit", lambda: False)
    monkeypatch.setattr(recognizer, "engine_available", lambda e: True)
    st = downloads.status(downloads.item("parakeet"))
    assert not st.can_download and "64-bit" in st.note


def test_progress_text():
    job = downloads.Job(downloads.item("vosk-small"))
    job._samples = [(0.0, 0), (2.0, 4 * 10 ** 6)]
    job.update(4 * 10 ** 6, 41205931, "download")
    job._samples = [(0.0, 0), (2.0, 4 * 10 ** 6)]
    text = job.describe()
    assert text.startswith("Downloading 4 MB of 41 MB (9%)") and "2.0 MB/s" in text


def test_operator_fullscreen_is_the_default(tmp_path):
    from biverse.settings import Settings
    assert Settings(str(tmp_path / "s.json"))["operator_fullscreen"] is True
