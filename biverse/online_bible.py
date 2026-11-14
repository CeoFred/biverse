"""Online Bible versions from the YouVersion Platform API.

Each user enters their own YouVersion app key in Settings -> Bibles. Without a
key there are no online versions; the bundled and imported translations work
as before.

* The version list (titles and copyright lines, no Bible text) is kept on disk,
  so the versions stay in the picker after a restart without internet.
* Text is fetched a chapter at a time, the first time a verse of that chapter
  is shown, and split into verses on the KJV grid like every other translation.
* Licensed versions (NIV, NASB, AMP, TPT...) are kept in memory only, for
  ``MEMORY_TTL`` seconds (the API's own cache lifetime). Versions under
  YouVersion's "Public Domain and Creative Commons" licence are also kept on disk,
  so they keep working offline.
* When a request fails the client counts as offline for ``RETRY_AFTER`` seconds
  and does not try again in that time, so a lost connection costs one short
  timeout, not one per slide. ``Bible.resolve`` then falls back to a local
  translation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple

from . import books

log = logging.getLogger(__name__)

API = "https://api.youversion.com/v1"
TIMEOUT = 3.0          # seconds per request; a slide waits at most this long once
RETRY_AFTER = 30.0     # seconds without requests after a failure
MEMORY_TTL = 3600.0    # licensed text is kept in memory this long (the API's max-age)
FREE_LICENCE_ID = 1    # YouVersion's "Public Domain and Creative Commons" licence
MAX_PAGES = 100        # 25 versions a page
MAX_DETAIL_LOOKUPS = 40  # copyright lines fetched one version at a time (about 0.5 s each)

# States, as Settings and the operator window show them
NO_KEY = "nokey"
IDLE = "idle"
ONLINE = "online"
OFFLINE = "offline"
BAD_KEY = "badkey"

STATE_TEXT = {
    NO_KEY: "No YouVersion key. Add one to use online Bible versions.",
    IDLE: "Not connected yet.",
    ONLINE: "Connected.",
    OFFLINE: "Offline. Showing the fallback version until the internet is back.",
    BAD_KEY: "YouVersion did not accept the key.",
}

Fetch = Callable[[str, str, float], Tuple[int, object]]  # (url, key, timeout) -> (status, json or None)


class ApiError(Exception):
    def __init__(self, status: int, message: str = "") -> None:
        Exception.__init__(self, message or "HTTP %d" % status)
        self.status = status


def _http_get(url: str, key: str, timeout: float) -> Tuple[int, object]:
    from .catalog import _ssl_context, _user_agent
    req = urllib.request.Request(url, headers={"X-YVP-App-Key": key, "Accept": "application/json",
                                                "User-Agent": _user_agent()})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, None


class Version(object):
    """One online Bible version."""

    __slots__ = ("code", "id", "name", "copyright", "publisher", "free", "books", "language")

    def __init__(self, code: str, id: int, name: str, copyright: str = "", publisher: str = "",
                 free: bool = False, books: Optional[List[str]] = None, language: str = "") -> None:
        self.code, self.id, self.name = code, id, name
        self.copyright, self.publisher, self.free = copyright, publisher, free
        self.books = list(books or [])
        self.language = language

    def to_dict(self) -> Dict[str, object]:
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d: Dict[str, object]) -> "Version":
        return cls(str(d["code"]), int(d["id"]), str(d["name"]), str(d.get("copyright") or ""),
                   str(d.get("publisher") or ""), bool(d.get("free")), list(d.get("books") or []),
                   str(d.get("language") or ""))

    def licence(self) -> str:
        if self.free:
            return "Public domain or Creative Commons (YouVersion, online)"
        line = (self.copyright or "").strip().splitlines()
        return (line[0] if line else ("© " + self.publisher if self.publisher else "Licensed")) + \
            " (YouVersion, online)"


# -- chapter HTML -> verses ----------------------------------------------------------

# Classes that are not verse text: psalm titles, section headings, "the next part is not
# translated yet" notes, signatures, verse labels, cross references and footnote marks.
_SKIP = frozenset(("d", "iex", "sig", "s", "s1", "s2", "s3", "ms", "ms1", "mr", "r", "sr", "cl", "cp",
                   "yv-vlbl", "rq", "sup", "f", "x", "fn", "note"))
_VOID = frozenset(("br", "img", "hr", "wbr"))


class _ChapterParser(HTMLParser):
    def __init__(self) -> None:
        HTMLParser.__init__(self, convert_charrefs=True)
        self.verses = {}  # type: Dict[int, List[str]]
        self.verse = 0
        self._stack = []  # type: List[bool]  # per open element: does it start a skipped region?
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        if "yv-v" in classes and a.get("v"):
            m = re.match(r"\d+", a["v"])
            if m:
                self.verse = int(m.group(0))
                self.verses.setdefault(self.verse, [])
        if tag in _VOID:
            self._add(" ")
            return
        skip = bool(classes & _SKIP)
        self._stack.append(skip)
        if skip:
            self._skip += 1
        if tag in ("div", "p"):
            self._add(" ")

    def handle_endtag(self, tag):
        if tag in _VOID or not self._stack:
            return
        if self._stack.pop():
            self._skip -= 1
        if tag in ("div", "p"):
            self._add(" ")

    def handle_data(self, data):
        if not self._skip:
            self._add(data)

    def _add(self, text: str) -> None:
        if self.verse:
            self.verses.setdefault(self.verse, []).append(text)


def parse_chapter(html: str) -> Dict[int, str]:
    """``{verse number: text}`` from a passage in ``format=html``. Verses the version
    leaves out (NIV Matthew 17:21 comes back as an empty "[21]") are empty strings."""
    p = _ChapterParser()
    p.feed(html or "")
    p.close()
    out = {}
    for v, parts in p.verses.items():
        text = re.sub(r"\s+", " ", unescape("".join(parts))).strip()
        text = re.sub(r"\s+([,.;:!?’”])", r"\1", text)
        out[v] = text
    return out


def _fit_grid(verses: Dict[int, str], grid_count: int) -> Dict[int, str]:
    """Put verses on the KJV grid: verses past the grid's last verse are appended to it."""
    if not grid_count:
        return dict(verses)
    out = {v: t for v, t in verses.items() if v <= grid_count}
    extra = [verses[v] for v in sorted(verses) if v > grid_count and verses[v]]
    if extra:
        out[grid_count] = " ".join([out.get(grid_count, "")] + extra).strip()
    return out


# -- the client ----------------------------------------------------------------------

class OnlineBibles(object):
    def __init__(self, key: str, cache_dir: str, languages: str = "en", fetch: Optional[Fetch] = None,
                 verse_count: Optional[Callable[[int, int], int]] = None,
                 clock: Callable[[], float] = time.time) -> None:
        self.key = (key or "").strip()
        self.languages = [x.strip() for x in (languages or "en").replace(";", ",").split(",") if x.strip()] or ["en"]
        self.cache_dir = cache_dir
        self._fetch = fetch or _http_get
        self._verse_count = verse_count
        self._clock = clock
        self._lock = threading.Lock()
        self._mem = {}  # type: Dict[Tuple[str, int, int], Tuple[float, Dict[int, str]]]
        self._inflight = {}  # type: Dict[Tuple[str, int, int], threading.Event]
        self._down_until = 0.0
        self.state = NO_KEY if not self.key else IDLE
        self.message = ""
        self.versions = {}  # type: Dict[str, Version]
        self._db = None  # type: Optional[sqlite3.Connection]
        if self.key:
            self._load_versions()

    # -- files --------------------------------------------------------------
    def _fingerprint(self) -> str:
        raw = self.key + "|" + ",".join(self.languages)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _versions_path(self) -> str:
        return os.path.join(self.cache_dir, "online_versions.json")

    def _load_versions(self) -> None:
        try:
            with open(self._versions_path(), encoding="utf-8") as f:
                data = json.load(f)
            if data.get("fingerprint") != self._fingerprint():
                return  # another key or other languages
            self.versions = {v.code: v for v in (Version.from_dict(d) for d in data.get("versions", []))}
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def _save_versions(self) -> None:
        path = self._versions_path()
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"fingerprint": self._fingerprint(), "saved": self._clock(),
                           "versions": [v.to_dict() for v in self.versions.values()]}, f)
            os.replace(path + ".tmp", path)
        except OSError:
            log.exception("could not save the online version list")

    def _store(self) -> Optional[sqlite3.Connection]:
        """Disk store for public-domain / Creative Commons chapters."""
        if self._db is None:
            try:
                os.makedirs(self.cache_dir, exist_ok=True)
                self._db = sqlite3.connect(os.path.join(self.cache_dir, "online_free.db"), check_same_thread=False)
                self._db.execute("CREATE TABLE IF NOT EXISTS chapters (bible INTEGER, book INTEGER, chapter INTEGER, "
                                 "fetched REAL, verses TEXT, PRIMARY KEY (bible, book, chapter))")
                self._db.commit()
            except sqlite3.Error:
                log.exception("online Bible store unavailable")
                self._db = None
        return self._db

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None

    def clear_cache(self) -> None:
        with self._lock:
            self._mem.clear()
            db = self._store()
            if db is not None:
                db.execute("DELETE FROM chapters")
                db.commit()

    # -- network ------------------------------------------------------------
    def _get(self, path: str, params: Optional[List[Tuple[str, str]]] = None) -> object:
        if not self.key:
            raise ApiError(0, "no key")
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        try:
            status, data = self._fetch(url, self.key, TIMEOUT)
        except Exception as exc:  # timeouts, DNS, TLS, refused connections
            self._went_offline(str(exc))
            raise ApiError(0, str(exc))
        if status == 401 or (status == 403 and path in ("/bibles", "/licenses")):
            self.state, self.message = BAD_KEY, STATE_TEXT[BAD_KEY]
            raise ApiError(status)
        if status == 429 or status >= 500:
            self._went_offline("YouVersion answered %d" % status)
            raise ApiError(status)
        if status != 200:
            raise ApiError(status)
        self.state, self.message = ONLINE, ""
        return data

    def _went_offline(self, why: str) -> None:
        self._down_until = self._clock() + RETRY_AFTER
        if self.state != BAD_KEY:
            self.state, self.message = OFFLINE, why
        log.info("online Bibles offline: %s", why)

    def reachable(self) -> bool:
        return bool(self.key) and self.state != BAD_KEY and self._clock() >= self._down_until

    def refresh_versions(self) -> bool:
        """Fetch the versions this key may use (blocking: call it from a thread).
        Returns True when the list was refreshed."""
        if not self.key:
            return False
        if self.state == BAD_KEY:
            self.state = IDLE  # a new attempt
        try:
            free = set()
            try:
                lic = self._get("/licenses")
                for item in (lic or {}).get("data", []):
                    if item.get("id") == FREE_LICENCE_ID:
                        free.update(int(i) for i in item.get("bible_ids") or [])
            except ApiError as exc:
                if exc.status in (0, 401, 429) or exc.status >= 500:
                    raise
            found = []  # type: List[dict]
            token = None
            for _ in range(MAX_PAGES):
                params = [("language_ranges[]", lang) for lang in self.languages]
                if token:
                    params.append(("page_token", token))
                page = self._get("/bibles", params) or {}
                found.extend(page.get("data", []))
                token = page.get("next_page_token")
                if not token:
                    break
        except ApiError:
            return False
        versions = {}  # type: Dict[str, Version]
        for d in found:
            try:
                code = str(d.get("localized_abbreviation") or d.get("abbreviation") or d["id"]).strip()
                if code in versions:
                    code = "%s-%s" % (code, d["id"])
                versions[code] = Version(code, int(d["id"]), str(d.get("localized_title") or d.get("title") or code),
                                         str(d.get("copyright") or ""), str(d.get("publisher_name") or ""),
                                         int(d["id"]) in free, d.get("books") or [], str(d.get("language_tag") or ""))
            except (KeyError, TypeError, ValueError):
                continue
        # the list only carries copyright for some versions; fill it in for licensed ones
        # (capped: with many languages there are hundreds, and the publisher name is shown instead)
        lookups = [v for v in versions.values() if not v.free and not v.copyright][:MAX_DETAIL_LOOKUPS]
        for v in lookups:
            try:
                info = self._get("/bibles/%d" % v.id) or {}
                v.copyright = str(info.get("copyright") or "")
                v.publisher = v.publisher or str(info.get("publisher_name") or "")
            except ApiError as exc:
                if exc.status == 0:
                    break
        with self._lock:
            self.versions = versions
        self._save_versions()
        log.info("online Bibles: %d versions for %s", len(versions), ",".join(self.languages))
        return True

    # -- text ---------------------------------------------------------------
    def has(self, code: str) -> bool:
        return code in self.versions

    def cached(self, code: str, book: int, chapter: int) -> Optional[Dict[int, str]]:
        v = self.versions.get(code)
        if v is None:
            return None
        k = (code, book, chapter)
        with self._lock:
            hit = self._mem.get(k)
            if hit is not None:
                if self._clock() - hit[0] < MEMORY_TTL or v.free:
                    return hit[1]
                del self._mem[k]
            if v.free:
                db = self._store()
                if db is not None:
                    row = db.execute("SELECT verses FROM chapters WHERE bible=? AND book=? AND chapter=?",
                                     (v.id, book, chapter)).fetchone()
                    if row:
                        verses = {int(n): t for n, t in json.loads(row[0]).items()}
                        self._mem[k] = (self._clock(), verses)
                        return verses
        return None

    def chapter(self, code: str, book: int, chapter: int, wait: float = TIMEOUT + 1) -> Optional[Dict[int, str]]:
        """The chapter's verses, from the cache or the API. None when it cannot be had."""
        hit = self.cached(code, book, chapter)
        if hit is not None:
            return hit
        v = self.versions.get(code)
        if v is None or not self.reachable():
            return None
        bk = books.get(book)
        if v.books and bk.code not in v.books:
            return None
        k = (code, book, chapter)
        with self._lock:
            ev = self._inflight.get(k)
            mine = ev is None
            if mine:
                ev = self._inflight[k] = threading.Event()
        if not mine:
            ev.wait(wait)
            return self.cached(code, book, chapter)
        try:
            try:
                data = self._get("/bibles/%d/passages/%s.%d" % (v.id, bk.code, chapter), [("format", "html")])
            except ApiError:
                return None
            verses = parse_chapter(str((data or {}).get("content") or ""))
            if not verses:
                return None
            if self._verse_count:
                verses = _fit_grid(verses, self._verse_count(book, chapter))
            with self._lock:
                self._mem[k] = (self._clock(), verses)
                if v.free:
                    db = self._store()
                    if db is not None:
                        db.execute("INSERT OR REPLACE INTO chapters VALUES (?,?,?,?,?)",
                                   (v.id, book, chapter, self._clock(), json.dumps(verses)))
                        db.commit()
            return verses
        finally:
            with self._lock:
                self._inflight.pop(k, None)
            ev.set()

    def prefetch(self, code: str, book: int, chapter: int) -> None:
        """Fetch a chapter in the background (the next one a reading is likely to need)."""
        if code not in self.versions or not self.reachable() or self.cached(code, book, chapter) is not None:
            return
        threading.Thread(target=self.chapter, args=(code, book, chapter), name="online-bible", daemon=True).start()
