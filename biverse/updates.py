"""In-app updates: find a newer release, download it, and swap the app folder.

The release job publishes ``latest.json`` (version, and for each build flavour
the zip's URL, size and SHA-256) with an Ed25519 signature in
``latest.json.sig``. Each build knows its flavour from ``build.json``, written
at package time. A manifest is used only when its signature matches
``PUBLIC_KEY``; the zip is used only when its size and SHA-256 match the
manifest.

Installing runs in the *new* copy (``--apply-update``): it waits for the old
process to exit, renames the old app to ``<name>.old`` (kept for rollback),
copies itself into place and starts it. If anything fails the old app is put
back. The result is written to ``updates/result.json`` for the next start to
report. When the app folder cannot be written to (or macOS runs a translocated
copy) the operator is offered the downloaded zip instead.

This module has no Tk code so it can be unit-tested.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import zipfile
from typing import Callable, List, Optional, Tuple

from . import APP_NAME, __version__, catalog, ed25519, paths

log = logging.getLogger(__name__)

REPO = "CeoFred/biverse"
MANIFEST_URL = "https://github.com/%s/releases/latest/download/latest.json" % REPO
# Ed25519 public key (hex) of the release job's UPDATE_SIGNING_KEY secret
# (tools/make_update_key.py). Empty: update checks are off in this build.
PUBLIC_KEY = "9154fd323113b7368df64b07ab0496a7315e9fbb65ddab1be9f68f5c3c0e9f18"
ALLOWED_HOSTS = ("github.com", "objects.githubusercontent.com")
MANIFEST_LIMIT = 256 * 1024
CHECK_TIMEOUT = 20

Progress = Callable[[int, int, str], None]


class UpdateError(Exception):
    pass


# -- versions and build identity --------------------------------------------------------

def parse_version(text: str) -> Tuple[int, ...]:
    """``"v1.10.2"`` -> ``(1, 10, 2)``; a pre-release suffix sorts before the release."""
    m = re.match(r"^v?(\d+(?:\.\d+)*)(.*)$", (text or "").strip())
    if not m:
        raise ValueError("not a version: %r" % text)
    nums = tuple(int(p) for p in m.group(1).split("."))
    nums = nums + (0,) * (3 - len(nums)) if len(nums) < 3 else nums
    return nums + ((0,) if m.group(2) else (1,))


def is_newer(candidate: str, current: str) -> bool:
    try:
        return parse_version(candidate) > parse_version(current)
    except ValueError:
        return False


def build_info() -> Optional[dict]:
    """``build.json`` of a packaged build (``{"flavour": "macos-arm", ...}``), or None from source."""
    path = os.path.join(paths.resource_dir(), "build.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) and data.get("flavour") else None
    except (OSError, ValueError):
        return None


def flavour() -> str:
    info = build_info()
    return str(info["flavour"]) if info else ""


# -- the manifest ----------------------------------------------------------------------

class Update(object):
    __slots__ = ("version", "url", "size", "sha256", "notes_url", "notes")

    def __init__(self, version: str, url: str, size: int, sha256: str, notes_url: str = "",
                 notes: str = "") -> None:
        self.version, self.url, self.size, self.sha256 = version, url, size, sha256
        self.notes_url, self.notes = notes_url, notes

    @property
    def filename(self) -> str:
        return os.path.basename(self.url.split("?")[0])

    def __repr__(self):  # pragma: no cover
        return "Update(%s, %s)" % (self.version, self.filename)


def _public_key() -> bytes:
    return binascii.unhexlify(PUBLIC_KEY) if PUBLIC_KEY else b""


def _allowed(url: str) -> bool:
    m = re.match(r"^https://([^/:]+)/", url)
    return bool(m) and m.group(1).lower() in ALLOWED_HOSTS


def parse_manifest(data: bytes, signature: bytes, public_key: bytes, build: str,
                   current: str = __version__) -> Optional[Update]:
    """The update for ``build`` when the signed manifest offers one newer than ``current``."""
    if not public_key:
        raise UpdateError("this copy of %s has no update key" % APP_NAME)
    try:
        sig = base64.b64decode(signature.strip(), validate=True)
    except (binascii.Error, ValueError):
        raise UpdateError("the update signature is unreadable")
    try:
        ed25519.verify(public_key, data, sig)
    except ed25519.BadSignature:
        raise UpdateError("the update information is not signed by the %s release key" % APP_NAME)
    try:
        doc = json.loads(data.decode("utf-8"))
        version = str(doc["version"])
        parse_version(version)
    except (ValueError, KeyError, TypeError):
        raise UpdateError("the update information is unreadable")
    if not is_newer(version, current):
        return None
    entry = (doc.get("builds") or {}).get(build)
    if not isinstance(entry, dict):
        log.info("update %s has no %r build", version, build)
        return None
    url, size, sha = entry.get("url"), entry.get("size"), entry.get("sha256")
    if (not isinstance(url, str) or not _allowed(url) or not isinstance(size, int) or size <= 0
            or not isinstance(sha, str) or not re.match(r"^[0-9a-f]{64}$", sha)):
        raise UpdateError("the update information is unreadable")
    notes_url = doc.get("notes_url") if isinstance(doc.get("notes_url"), str) else ""
    notes = doc.get("notes") if isinstance(doc.get("notes"), str) else ""
    return Update(version, url, size, sha, notes_url, notes)


def _get(url: str, timeout: float) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": catalog._user_agent()})
    with urllib.request.urlopen(req, timeout=timeout, context=catalog._ssl_context()) as resp:
        data = resp.read(MANIFEST_LIMIT + 1)
    if len(data) > MANIFEST_LIMIT:
        raise UpdateError("the update information is too large")
    return data


def check(build: Optional[str] = None, current: str = __version__, manifest_url: str = MANIFEST_URL,
          public_key: Optional[bytes] = None, timeout: float = CHECK_TIMEOUT) -> Optional[Update]:
    """The newest release for this build, or None when up to date. Raises ``UpdateError``."""
    build = build if build is not None else flavour()
    if not build:
        raise UpdateError("updates are only offered to the downloaded %s app" % APP_NAME)
    key = public_key if public_key is not None else _public_key()
    try:
        data = _get(manifest_url, timeout)
        sig = _get(manifest_url + ".sig", timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            log.info("no update manifest published yet")
            return None
        raise UpdateError(catalog._explain(exc))
    except (OSError, urllib.error.URLError) as exc:
        raise UpdateError("%s could not reach the update server (%s)" % (APP_NAME, getattr(exc, "reason", exc)))
    return parse_manifest(data, sig, key, build, current)


# -- download and unpack ---------------------------------------------------------------

def updates_dir() -> str:
    return os.path.join(paths.config_dir(), "updates")


def download(update: Update, progress: Optional[Progress] = None, cancel: Optional[threading.Event] = None,
             cache: Optional[str] = None) -> str:
    """The verified zip (resumes a ``.part`` file left by a cancelled download)."""
    cache = cache or updates_dir()
    try:
        return catalog.fetch_verified(update.url, update.size, update.sha256, cache, progress, cancel)
    except catalog.DownloadError as exc:
        raise UpdateError(str(exc))


def _safe_members(zf: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    out = []
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.startswith("/") or re.match(r"^[A-Za-z]:", name) or ".." in name.split("/"):
            raise UpdateError("the update archive has an unsafe path: %s" % info.filename)
        out.append(info)
    return out


def _extract(zip_path: str, dest: str) -> None:
    """Unzip keeping Unix modes and symlinks (macOS app bundles need both)."""
    if sys.platform == "darwin" and shutil.which("ditto"):
        with zipfile.ZipFile(zip_path) as zf:
            _safe_members(zf)
        subprocess.check_call(["ditto", "-x", "-k", zip_path, dest])
        return
    root = os.path.realpath(dest)
    with zipfile.ZipFile(zip_path) as zf:
        for info in _safe_members(zf):
            target = os.path.realpath(os.path.join(dest, info.filename))
            if target != root and not target.startswith(root + os.sep):
                raise UpdateError("the update archive has an unsafe path: %s" % info.filename)
            mode = info.external_attr >> 16
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if mode and (mode & 0o170000) == 0o120000 and hasattr(os, "symlink"):
                link = zf.read(info).decode("utf-8")
                resolved = os.path.realpath(os.path.join(os.path.dirname(target), link))
                if os.path.isabs(link) or not resolved.startswith(root + os.sep):
                    raise UpdateError("the update archive has an unsafe link: %s" % info.filename)
                os.symlink(link, target)
                continue
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)
            if mode & 0o777:
                os.chmod(target, mode & 0o777)


def find_app(folder: str) -> str:
    """The app inside an unpacked release zip: ``Biverse.app`` or the ``Biverse`` folder."""
    bundle = os.path.join(folder, APP_NAME + ".app")
    if os.path.isdir(bundle):
        return bundle
    plain = os.path.join(folder, APP_NAME)
    if os.path.isfile(os.path.join(plain, APP_NAME + ".exe")) or os.path.isfile(os.path.join(plain, APP_NAME)):
        return plain
    raise UpdateError("the update archive does not contain %s" % APP_NAME)


def stage(zip_path: str, version: str, base: Optional[str] = None) -> str:
    """Unpack the update into ``updates/staged-<version>``; returns the new app's path."""
    base = base or updates_dir()
    folder = os.path.join(base, "staged-%s" % version)
    if os.path.exists(folder):
        shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder)
    try:
        _extract(zip_path, folder)
        return find_app(folder)
    except (OSError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise UpdateError("the update could not be unpacked (%s)" % exc)
    except UpdateError:
        shutil.rmtree(folder, ignore_errors=True)
        raise


# -- where the running app lives -------------------------------------------------------

def app_root(executable: Optional[str] = None, platform: str = sys.platform) -> str:
    """The folder that gets replaced: ``…/Biverse.app`` on macOS, the folder with ``Biverse.exe`` elsewhere."""
    exe = os.path.abspath(executable or sys.executable)
    folder = os.path.dirname(exe)
    if platform == "darwin":
        parts = folder.split(os.sep)
        for i in range(len(parts) - 1, 0, -1):
            if parts[i].endswith(".app"):
                return os.sep.join(parts[:i + 1])
    return folder


def executable_in(root: str, platform: str = sys.platform) -> str:
    if platform == "darwin" and root.endswith(".app"):
        return os.path.join(root, "Contents", "MacOS", APP_NAME)
    if platform == "win32":
        return os.path.join(root, APP_NAME + ".exe")
    return os.path.join(root, APP_NAME)


def backup_path(target: str) -> str:
    """``Biverse.app`` -> ``Biverse.old.app``; ``Biverse`` -> ``Biverse.old``."""
    stem, ext = os.path.splitext(target.rstrip(os.sep))
    return stem + ".old" + ext if ext == ".app" else target.rstrip(os.sep) + ".old"


def install_problem(root: Optional[str] = None) -> str:
    """Why this copy cannot replace itself ("" when it can)."""
    if not paths.is_frozen() and root is None:
        return "%s is running from source" % APP_NAME
    root = root or app_root()
    if "/AppTranslocation/" in root:
        return ("macOS is running %s from a temporary, read-only location. Move %s.app to the "
                "Applications folder and open it from there" % (APP_NAME, APP_NAME))
    parent = os.path.dirname(root)
    if not os.access(parent, os.W_OK) or not os.access(root, os.W_OK):
        return "%s's folder (%s) cannot be written to" % (APP_NAME, parent)
    return ""


# -- installing ------------------------------------------------------------------------

def _copy_app(src: str, dest: str) -> None:
    if sys.platform == "darwin" and shutil.which("ditto"):
        subprocess.check_call(["ditto", src, dest])  # keeps signatures, links and modes
    else:
        shutil.copytree(src, dest, symlinks=True)


def _retry(fn, attempts: int = 20, delay: float = 0.5):
    """Windows keeps files locked for a moment after a process exits (and antivirus scans)."""
    for i in range(attempts):
        try:
            return fn()
        except OSError:
            if i + 1 == attempts:
                raise
            time.sleep(delay)


def replace_app(new_root: str, target: str, copy: Callable[[str, str], None] = _copy_app) -> str:
    """Put ``new_root`` at ``target``, keeping the old one at ``backup_path(target)``.

    Rolls back (the old app back in place) if the copy fails. Returns the backup path.
    """
    backup = backup_path(target)
    if os.path.exists(backup):
        _retry(lambda: shutil.rmtree(backup))
    _retry(lambda: os.rename(target, backup))
    try:
        copy(new_root, target)
    except BaseException:
        log.exception("copying the update failed, restoring %s", target)
        shutil.rmtree(target, ignore_errors=True)
        _retry(lambda: os.rename(backup, target))
        raise
    return backup


def _result_path() -> str:
    return os.path.join(updates_dir(), "result.json")


def write_result(ok: bool, version: str, detail: str = "") -> None:
    try:
        os.makedirs(updates_dir(), exist_ok=True)
        with open(_result_path(), "w", encoding="utf-8") as f:
            json.dump({"ok": ok, "version": version, "detail": detail}, f)
    except OSError:
        log.exception("cannot record the update result")


def take_result() -> Optional[dict]:
    """The last install's result (once), and clean up staged copies and downloads."""
    path = _result_path()
    try:
        with open(path, encoding="utf-8") as f:
            result = json.load(f)
        os.remove(path)
    except (OSError, ValueError):
        result = None
    cleanup()
    return result if isinstance(result, dict) else None


def cleanup(keep: str = "") -> None:
    """Remove staged copies and finished downloads (``.part`` files are kept to resume)."""
    folder = updates_dir()
    try:
        names = os.listdir(folder)
    except OSError:
        return
    for name in names:
        path = os.path.join(folder, name)
        if keep and name == keep:
            continue
        if name.startswith("staged-"):
            shutil.rmtree(path, ignore_errors=True)
        elif name.endswith(".zip"):
            try:
                os.remove(path)
            except OSError:
                pass


def launch_installer(new_root: str, target: str, relaunch: bool) -> None:
    """Start the new copy so it installs itself once this process has exited."""
    exe = executable_in(new_root)
    args = [exe, "--apply-update", target, "--wait-pid", str(os.getpid())]
    if relaunch:
        args.append("--relaunch")
    log.info("starting the installer: %s", args)
    kwargs = {}  # type: dict
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, **kwargs)


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return False
        try:
            return kernel32.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_exit(pid: int, timeout: float = 120.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not _pid_alive(pid):
            return True
        time.sleep(0.25)
    return False


def start_app(root: str) -> None:
    if sys.platform == "darwin" and root.endswith(".app"):
        subprocess.Popen(["open", "-n", root])
        return
    kwargs = {}  # type: dict
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([executable_in(root)], close_fds=True, **kwargs)


def apply_update(target: str, wait_pid: int, relaunch: bool) -> int:
    """``--apply-update``: runs in the new copy and replaces ``target`` with it."""
    new_root = app_root()
    log.info("installing %s %s from %s into %s", APP_NAME, __version__, new_root, target)
    if os.path.normcase(os.path.abspath(new_root)) == os.path.normcase(os.path.abspath(target)):
        write_result(False, __version__, "the installer was started from the installed copy")
        return 2
    if wait_pid and not wait_for_exit(wait_pid):
        write_result(False, __version__, "%s did not close" % APP_NAME)
        return 3
    ok = True
    try:
        replace_app(new_root, target)
        write_result(True, __version__)
        log.info("installed %s %s", APP_NAME, __version__)
    except Exception as exc:
        ok = False
        write_result(False, __version__, str(exc) or exc.__class__.__name__)
    if relaunch:
        try:
            start_app(target)
        except Exception:
            log.exception("could not start %s", target)
    return 0 if ok else 1


def open_file(path: str) -> None:
    """Show a downloaded zip to the operator (fallback install)."""
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", path])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])
