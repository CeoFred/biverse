#!/usr/bin/env python3
"""Build data/bible.db from pinned public-domain sources.

    python tools/build_bible_db.py            # download (cached) and build
    python tools/build_bible_db.py --offline  # use data/cache only

Sources
  * scrollmapper/bible_databases (MIT repository; the texts are public domain),
    pinned to a commit SHA, with SHA-256 checksums for each CSV.
  * World English Bible (engwebp, public domain) from eBible.org. eBible does
    not version its download URLs, so a checksum change is reported as a
    warning (use --strict to make it an error) and the actual checksum is
    recorded in the database's meta table.

This script is the only part of Biverse that touches the network, and it runs
at build time only.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import sqlite3
import sys
import time
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from biverse import bible_import  # noqa: E402
from biverse.versification import VERSE_COUNTS  # noqa: E402

SCROLLMAPPER_SHA = "59b18c5af5845728c275d5b7178ad0d024172b1f"
SCROLLMAPPER_URL = "https://raw.githubusercontent.com/scrollmapper/bible_databases/%s/formats/csv/%s.csv"

# code, display name, licence, source kind, url/file, sha256
TRANSLATIONS = [
    ("KJV", "King James Version (1769)", "Public domain",
     "scrollmapper", "KJV", "a1051b4395bee78d01e239984425f3919563db5caee6fc162d4ddc7faff7eaa8"),
    ("WEB", "World English Bible", "Public domain",
     "vpl-zip", "https://ebible.org/Scriptures/engwebp_vpl.zip",
     "7ebe6b7dc416ce63691d1a3889a06f841ccb7f414ada69be82da891f4b9be44f"),
    ("ASV", "American Standard Version (1901)", "Public domain",
     "scrollmapper", "ASV", "95d26cb14704ab4804635d533f2a518f4a9575e5f63fe44f4db025990f1cabb5"),
    ("YLT", "Young's Literal Translation (1898)", "Public domain",
     "scrollmapper", "YLT", "d325557cfe7398e5c914b87b582f032903ee8ace8b14f7df1a3ea1739ad38a15"),
    ("BBE", "Bible in Basic English (1965)", "Public domain",
     "scrollmapper", "BBE", "9d3503851b50e381fbf1fb6505d45817f795de866c689899234cd378e98e74fb"),
]
UNPINNED = {"WEB"}


def fetch(url: str, cache_path: str, offline: bool) -> bytes:
    if os.path.exists(cache_path):
        with open(cache_path, "rb") as f:
            return f.read()
    if offline:
        raise SystemExit("not cached and --offline given: %s" % cache_path)
    print("  downloading %s" % url)
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "biverse-build"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = resp.read()
            break
        except Exception as exc:  # network hiccups on CI
            last = exc
            time.sleep(2 ** attempt)
    else:
        raise SystemExit("download failed: %s (%s)" % (url, last))
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path + ".part", "wb") as f:
        f.write(data)
    os.replace(cache_path + ".part", cache_path)
    return data


def load_rows(kind: str, src: str, cache: str, offline: bool, expected_sha: str, strict: bool, code: str):
    if kind == "scrollmapper":
        url = SCROLLMAPPER_URL % (SCROLLMAPPER_SHA, src)
        data = fetch(url, os.path.join(cache, "%s-%s.csv" % (src, SCROLLMAPPER_SHA[:12])), offline)
    else:
        url = src
        data = fetch(url, os.path.join(cache, os.path.basename(src)), offline)
    sha = hashlib.sha256(data).hexdigest()
    if sha != expected_sha:
        msg = "%s: checksum %s does not match pinned %s" % (code, sha, expected_sha)
        if code in UNPINNED and not strict:
            print("  WARNING: " + msg + " (upstream updated; continuing, structure is still validated)")
        else:
            raise SystemExit(msg)
    if kind == "scrollmapper":
        rows = bible_import.rows_from_book_order_csv(data.decode("utf-8-sig"))
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = [n for n in zf.namelist() if n.endswith("_vpl.txt")][0]
            rows = bible_import.rows_from_vpl(zf.read(name).decode("utf-8-sig"))
    return rows, url, sha


def verify_counts(rows, code: str) -> None:
    books = {r[0] for r in rows}
    assert len(books) == 66, (code, len(books))
    if code != "WEB":  # WEB is mapped onto the KJV grid
        assert len(rows) == bible_import.TOTAL_VERSES, (code, len(rows))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "data", "bible.db"))
    ap.add_argument("--cache", default=os.path.join(ROOT, "data", "cache"))
    ap.add_argument("--offline", action="store_true", help="use cached downloads only")
    ap.add_argument("--strict", action="store_true", help="fail on any checksum mismatch")
    ap.add_argument("--only", help="comma-separated translation codes (default: all)")
    ap.add_argument("--skip-web", action="store_true", help="build without WEB if eBible is unreachable")
    args = ap.parse_args(argv)

    wanted = None if not args.only else {c.strip().upper() for c in args.only.split(",")}
    tmp = args.out + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    conn = sqlite3.connect(tmp)
    bible_import.create_schema(conn)
    built = []
    for code, name, lic, kind, src, sha in TRANSLATIONS:
        if (wanted and code not in wanted) or (args.skip_web and code == "WEB"):
            continue
        print("%s – %s" % (code, name))
        try:
            rows, url, actual = load_rows(kind, src, args.cache, args.offline, sha, args.strict, code)
        except SystemExit:
            if code in UNPINNED and not args.strict:
                print("  WARNING: %s unavailable, skipping" % code)
                continue
            raise
        verify_counts(rows, code)
        for w in bible_import.write_translation(conn, code, name, lic, rows):
            print("  note: " + w)
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", ("source:" + code, url))
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?,?)", ("sha256:" + code, actual))
        built.append(code)
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('order', ?)", (",".join(built),))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('built', ?)",
                 (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),))
    conn.commit()

    # sanity checks
    chapters = conn.execute("SELECT book, chapter, verse_count FROM chapters ORDER BY book, chapter").fetchall()
    assert chapters == [(b, c, n) for b, chs in enumerate(VERSE_COUNTS, 1) for c, n in enumerate(chs, 1)]
    if "KJV" in built:
        jn = conn.execute("SELECT text FROM verses WHERE translation='KJV' AND book=43 AND chapter=3 AND verse=16"
                          ).fetchone()[0]
        assert jn.startswith("For God so loved the world"), jn
    from biverse import quotes
    t0 = time.time()
    n = quotes.build_index(conn)
    print("quoted-verse index: %d buckets (%.1fs)" % (n, time.time() - t0))
    conn.execute("VACUUM")
    conn.close()
    os.replace(tmp, args.out)
    print("wrote %s (%s) – %.1f MB" % (args.out, ", ".join(built), os.path.getsize(args.out) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
