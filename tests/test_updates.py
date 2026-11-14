"""In-app updates: signed manifest, verified resumable download, unpack, folder swap."""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import stat
import sys
import threading
import zipfile

import pytest

from biverse import ed25519, settings, updates

SECRET = bytes(range(32))
PUBLIC = ed25519.public_key(SECRET)
SHA = "ab" * 32
URL = "https://github.com/CeoFred/biverse/releases/download/v9.0.0/Biverse-9.0.0-macos-arm.zip"


def _signed(doc, secret=SECRET):
    data = json.dumps(doc).encode()
    return data, base64.b64encode(ed25519.sign(secret, data)) + b"\n"


def _doc(version="9.0.0", **build):
    entry = {"url": URL, "size": 1234, "sha256": SHA}
    entry.update(build)
    return {"version": version, "notes_url": "https://github.com/CeoFred/biverse/releases/tag/v" + version,
            "builds": {"macos-arm": entry}}


# -- Ed25519 --------------------------------------------------------------------------

def test_ed25519_rfc8032_vector():
    sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    pk = ed25519.public_key(sk)
    assert pk.hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = ed25519.sign(sk, b"")
    assert sig.hex().startswith("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e0652249015")
    ed25519.verify(pk, b"", sig)
    with pytest.raises(ed25519.BadSignature):
        ed25519.verify(pk, b"x", sig)


# -- versions -------------------------------------------------------------------------

@pytest.mark.parametrize("new,old,expected", [
    ("1.5.0", "1.4.0", True), ("v1.10.0", "1.9.9", True), ("1.4.0", "1.4.0", False),
    ("1.4", "1.4.0", False), ("1.4.0", "1.4.1", False), ("1.5.0-rc1", "1.5.0", False),
    ("1.5.0", "1.5.0-rc1", True), ("nonsense", "1.0.0", False),
])
def test_is_newer(new, old, expected):
    assert updates.is_newer(new, old) is expected


# -- manifest -------------------------------------------------------------------------

def test_manifest_offers_newer_build():
    data, sig = _signed(_doc())
    u = updates.parse_manifest(data, sig, PUBLIC, "macos-arm", current="1.4.0")
    assert (u.version, u.url, u.size, u.sha256) == ("9.0.0", URL, 1234, SHA)
    assert u.filename == "Biverse-9.0.0-macos-arm.zip"


def test_manifest_up_to_date_or_other_flavour():
    data, sig = _signed(_doc())
    assert updates.parse_manifest(data, sig, PUBLIC, "macos-arm", current="9.0.0") is None
    assert updates.parse_manifest(data, sig, PUBLIC, "windows-x64", current="1.4.0") is None


def test_manifest_with_wrong_key_or_tampering_is_refused():
    data, sig = _signed(_doc(), secret=bytes(32))
    with pytest.raises(updates.UpdateError, match="not signed"):
        updates.parse_manifest(data, sig, PUBLIC, "macos-arm", current="1.4.0")
    data, sig = _signed(_doc())
    with pytest.raises(updates.UpdateError, match="not signed"):
        updates.parse_manifest(data.replace(b"9.0.0", b"9.0.1"), sig, PUBLIC, "macos-arm", current="1.4.0")
    with pytest.raises(updates.UpdateError, match="unreadable"):
        updates.parse_manifest(data, b"!!not base64!!", PUBLIC, "macos-arm", current="1.4.0")
    with pytest.raises(updates.UpdateError, match="no update key"):
        updates.parse_manifest(data, sig, b"", "macos-arm", current="1.4.0")


@pytest.mark.parametrize("bad", [
    {"url": "http://github.com/x.zip"}, {"url": "https://evil.example/x.zip"}, {"size": 0},
    {"size": "12"}, {"sha256": "XYZ"},
])
def test_manifest_with_bad_entry_is_refused(bad):
    data, sig = _signed(_doc(**bad))
    with pytest.raises(updates.UpdateError, match="unreadable"):
        updates.parse_manifest(data, sig, PUBLIC, "macos-arm", current="1.4.0")


def test_check_from_source_is_not_offered_updates():
    with pytest.raises(updates.UpdateError, match="downloaded"):
        updates.check(build="")


def test_make_update_manifest_round_trip(tmp_path, monkeypatch):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tools import make_update_manifest
    (tmp_path / "Biverse-9.0.0-macos-arm.zip").write_bytes(b"zipdata")
    (tmp_path / "Biverse-model-pack-parakeet-9.0.0.zip").write_bytes(b"pack")
    monkeypatch.setenv("UPDATE_SIGNING_KEY", SECRET.hex())
    assert make_update_manifest.main(["--version", "9.0.0", "--dir", str(tmp_path), "--repo", "CeoFred/biverse"]) == 0
    data = (tmp_path / "latest.json").read_bytes()
    u = updates.parse_manifest(data, (tmp_path / "latest.json.sig").read_bytes(), PUBLIC, "macos-arm", "1.4.0")
    assert u.size == 7 and u.sha256 == hashlib.sha256(b"zipdata").hexdigest()
    assert u.url == URL
    assert list(json.loads(data)["builds"]) == ["macos-arm"]  # packs are not app builds


def test_make_update_manifest_without_key_writes_nothing(tmp_path, monkeypatch):
    from tools import make_update_manifest
    monkeypatch.delenv("UPDATE_SIGNING_KEY", raising=False)
    (tmp_path / "Biverse-9.0.0-macos-arm.zip").write_bytes(b"zipdata")
    assert make_update_manifest.main(["--version", "9.0.0", "--dir", str(tmp_path), "--repo", "a/b"]) == 0
    assert not (tmp_path / "latest.json").exists()


# -- download -------------------------------------------------------------------------

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
        start = int(rng[6:].split("-")[0]) if rng else 0
        self.send_response(206 if rng else 200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    _Handler.files, _Handler.hits = {}, []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def test_download_resumes_and_verifies(tmp_path, server):
    data = os.urandom(200000)
    _Handler.files["/Biverse-9.0.0-x.zip"] = data
    u = updates.Update("9.0.0", server + "/Biverse-9.0.0-x.zip", len(data), hashlib.sha256(data).hexdigest())
    (tmp_path / "Biverse-9.0.0-x.zip.part").write_bytes(data[:5000])
    path = updates.download(u, cache=str(tmp_path))
    assert open(path, "rb").read() == data
    assert _Handler.hits == [("/Biverse-9.0.0-x.zip", "bytes=5000-")]


def test_download_with_wrong_checksum_fails(tmp_path, server):
    _Handler.files["/a.zip"] = b"hello"
    u = updates.Update("9.0.0", server + "/a.zip", 5, "0" * 64)
    with pytest.raises(updates.UpdateError, match="damaged"):
        updates.download(u, cache=str(tmp_path))
    assert os.listdir(str(tmp_path)) == []


def test_check_against_local_server(tmp_path, server):
    data, sig = _signed(_doc())
    _Handler.files["/latest.json"] = data
    _Handler.files["/latest.json.sig"] = sig
    u = updates.check(build="macos-arm", current="1.4.0", manifest_url=server + "/latest.json", public_key=PUBLIC)
    assert u.version == "9.0.0"
    assert updates.check(build="macos-arm", current="1.4.0", manifest_url=server + "/missing.json",
                         public_key=PUBLIC) is None


# -- unpack ---------------------------------------------------------------------------

def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data, mode in entries:
            info = zipfile.ZipInfo(name)
            info.external_attr = mode << 16
            zf.writestr(info, data)


def test_stage_finds_windows_style_folder_and_keeps_modes(tmp_path):
    z = tmp_path / "u.zip"
    _zip(str(z), [("Biverse/Biverse.exe", b"exe", 0o100755), ("Biverse/_internal/a.txt", b"a", 0o100644),
                  ("README.txt", b"r", 0o100644)])
    root = updates.stage(str(z), "9.0.0", base=str(tmp_path / "updates"))
    assert root == str(tmp_path / "updates" / "staged-9.0.0" / "Biverse")
    assert open(os.path.join(root, "_internal", "a.txt")).read() == "a"
    if sys.platform != "win32":
        assert os.stat(os.path.join(root, "Biverse.exe")).st_mode & stat.S_IXUSR


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks")
def test_stage_keeps_app_bundle_symlinks(tmp_path):
    z = tmp_path / "u.zip"
    _zip(str(z), [("Biverse.app/Contents/MacOS/Biverse", b"bin", 0o100755),
                  ("Biverse.app/Contents/Resources/lib.dylib", b"lib", 0o100644),
                  ("Biverse.app/Contents/Frameworks/lib.dylib", b"../Resources/lib.dylib", 0o120777)])
    root = updates.stage(str(z), "9.0.0", base=str(tmp_path / "updates"))
    assert root.endswith("Biverse.app")
    link = os.path.join(root, "Contents", "Frameworks", "lib.dylib")
    assert os.path.islink(link) and open(link).read() == "lib"


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "Biverse/../../evil.txt"])
def test_stage_refuses_unsafe_paths(tmp_path, name):
    z = tmp_path / "u.zip"
    _zip(str(z), [("Biverse/Biverse.exe", b"exe", 0o100755), (name, b"x", 0o100644)])
    with pytest.raises(updates.UpdateError, match="unsafe"):
        updates.stage(str(z), "9.0.0", base=str(tmp_path / "updates"))
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "updates" / "staged-9.0.0").exists()


def test_stage_without_app_fails(tmp_path):
    z = tmp_path / "u.zip"
    _zip(str(z), [("something/else.txt", b"x", 0o100644)])
    with pytest.raises(updates.UpdateError, match="does not contain"):
        updates.stage(str(z), "9.0.0", base=str(tmp_path / "updates"))


# -- paths and install ----------------------------------------------------------------

def test_app_root_and_executable():
    exe = "/Applications/Biverse.app/Contents/MacOS/Biverse"
    assert updates.app_root(exe, "darwin") == "/Applications/Biverse.app"
    assert updates.executable_in("/Applications/Biverse.app", "darwin") == exe
    assert updates.app_root("/opt/Biverse/Biverse", "linux") == "/opt/Biverse"
    assert updates.executable_in("C:\\Biverse", "win32").endswith("Biverse.exe")


def test_backup_path():
    assert updates.backup_path("/Applications/Biverse.app") == "/Applications/Biverse.old.app"
    assert updates.backup_path("/opt/Biverse") == "/opt/Biverse.old"


def test_install_problem(tmp_path):
    app = tmp_path / "Biverse"
    app.mkdir()
    assert updates.install_problem(str(app)) == ""
    assert "temporary" in updates.install_problem("/private/var/folders/x/AppTranslocation/y/Biverse.app")


def _tree(root, text):
    os.makedirs(os.path.join(root, "_internal"))
    with open(os.path.join(root, "_internal", "v.txt"), "w") as f:
        f.write(text)


def test_replace_app_keeps_old_copy(tmp_path):
    target, new = str(tmp_path / "Biverse"), str(tmp_path / "staged" / "Biverse")
    _tree(target, "old")
    _tree(new, "new")
    _tree(str(tmp_path / "Biverse.old"), "older")  # from the previous update
    backup = updates.replace_app(new, target)
    assert open(os.path.join(target, "_internal", "v.txt")).read() == "new"
    assert open(os.path.join(backup, "_internal", "v.txt")).read() == "old"


def test_replace_app_rolls_back_when_copy_fails(tmp_path):
    target, new = str(tmp_path / "Biverse"), str(tmp_path / "staged" / "Biverse")
    _tree(target, "old")
    _tree(new, "new")

    def broken_copy(src, dest):
        os.makedirs(dest)
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        updates.replace_app(new, target, copy=broken_copy)
    assert open(os.path.join(target, "_internal", "v.txt")).read() == "old"
    assert not os.path.exists(updates.backup_path(target))


def test_apply_update_records_result(tmp_path, monkeypatch):
    target, new = str(tmp_path / "Biverse"), str(tmp_path / "staged" / "Biverse")
    _tree(target, "old")
    _tree(new, "new")
    monkeypatch.setattr(updates, "app_root", lambda *a, **k: new)
    assert updates.apply_update(target, 0, relaunch=False) == 0
    assert open(os.path.join(target, "_internal", "v.txt")).read() == "new"
    result = updates.take_result()
    assert result["ok"] is True and updates.take_result() is None


def test_apply_update_from_installed_copy_is_refused(tmp_path, monkeypatch):
    target = str(tmp_path / "Biverse")
    _tree(target, "old")
    monkeypatch.setattr(updates, "app_root", lambda *a, **k: target)
    assert updates.apply_update(target, 0, relaunch=False) == 2
    assert updates.take_result()["ok"] is False


def test_cleanup_keeps_part_files(tmp_path):
    folder = updates.updates_dir()
    os.makedirs(os.path.join(folder, "staged-9.0.0", "Biverse"))
    for name in ("a.zip", "b.zip.part"):
        open(os.path.join(folder, name), "w").close()
    updates.cleanup()
    assert sorted(os.listdir(folder)) == ["b.zip.part"]


def test_wait_for_exit_of_dead_process():
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert updates.wait_for_exit(p.pid, timeout=5)


def test_settings_defaults():
    s = settings.Settings().load()
    assert s["update_check"] is True and s["update_skipped"] == "" and s["update_last_check"] == 0.0


def test_build_info(monkeypatch, tmp_path):
    monkeypatch.setattr(updates.paths, "resource_dir", lambda: str(tmp_path))
    assert updates.build_info() is None and updates.flavour() == ""
    (tmp_path / "build.json").write_text(json.dumps({"flavour": "windows-x64", "version": "1.5.0"}))
    assert updates.flavour() == "windows-x64"


def test_pinned_public_key_is_a_valid_point():
    key = updates._public_key()
    assert len(key) == 32
    ed25519._decompress(key)  # raises BadSignature for a mistyped key
