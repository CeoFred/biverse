#!/usr/bin/env python3
"""Add a translation your church holds a licence for.

Biverse ships public-domain translations only. If you have the right to use
another translation, put it in a CSV (or JSON) file and import it:

    python tools/import_translation.py MYTR "My Translation" mytranslation.csv
    Biverse.exe --import-translation MYTR "My Translation" mytranslation.csv

CSV format (UTF-8, header row required) – the same as scrollmapper's:

    Book,Chapter,Verse,Text
    1,1,1,In the beginning ...          <- Book as 1-66, or
    Genesis,1,1,In the beginning ...    <- Book names, in canonical order

JSON format: a list of {"book": 1, "chapter": 1, "verse": 1, "text": "..."}.

The translation is stored in your user settings folder
(user_translations.db), so it survives app updates and is never bundled.
Restart Biverse afterwards; it appears in the Bible list.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from . import bible_import, paths


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="import_translation", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("code", help="short code shown in the app, e.g. NIV")
    ap.add_argument("name", help="full name, e.g. 'New International Version'")
    ap.add_argument("file", help="CSV or JSON file")
    ap.add_argument("--license", default="Used under licence held by the user",
                    help="licence note stored with the translation")
    ap.add_argument("--db", default=None, help="target database (default: your user translations database)")
    ap.add_argument("--remove", action="store_true", help="remove the translation with this code instead")
    args = ap.parse_args(argv)

    db = args.db or paths.user_bible_db_path()
    conn = sqlite3.connect(db)
    bible_import.create_schema(conn)
    code = args.code.upper()
    if args.remove:
        with conn:
            conn.execute("DELETE FROM verses WHERE translation=?", (code,))
            conn.execute("DELETE FROM translations WHERE code=?", (code,))
        print("removed %s from %s" % (code, db))
        return 0

    with open(args.file, encoding="utf-8-sig") as f:
        data = f.read()
    if args.file.lower().endswith(".json"):
        rows = bible_import.rows_from_json(data)
    else:
        rows = bible_import.rows_from_csv(data)
    try:
        warnings = bible_import.write_translation(conn, code, args.name, args.license, rows)
    except ValueError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    for w in warnings:
        print("note: " + w)
    print("imported %s (%d verses) into %s" % (code, len(rows), db))
    return 0


def run_import(args) -> int:
    """``Biverse --import-translation CODE NAME FILE``."""
    return run(list(args))
