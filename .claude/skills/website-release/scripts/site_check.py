#!/usr/bin/env python3
"""Compare the Biverse website with the app and its GitHub release.

Prints: app and website versions, the previous tag, feat/fix commits since it,
the release's assets, and every download link on the page that would 404.
Exits 1 when the versions disagree or a link would 404, 0 otherwise.

    python .claude/skills/website-release/scripts/site_check.py [--since vX.Y.Z] [--offline]

Stdlib only; uses `git` and (unless --offline) the `gh` CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
INDEX = os.path.join(ROOT, "website", "index.html")
INIT = os.path.join(ROOT, "biverse", "__init__.py")


def run(*cmd):
    try:
        out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def app_version():
    m = re.search(r'__version__\s*=\s*"([^"]+)"', read(INIT))
    return m.group(1) if m else ""


def site_info(html):
    ver = re.search(r'<html[^>]*data-version="([^"]*)"', html)
    note = re.search(r'class="ver">([^<]*)<', html)
    files = sorted(set(f for f in re.findall(r'data-file="([^"]*)"', html) if f))
    packs = sorted(set(re.findall(r'data-pack="([^"]+)"', html)))
    features = re.findall(r"<dt>(.*?)</dt>", html)
    return (ver.group(1) if ver else ""), (note.group(1) if note else ""), files, packs, features


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", help="tag to compare against (default: the tag before the newest)")
    ap.add_argument("--offline", action="store_true", help="don't ask GitHub for release assets")
    args = ap.parse_args()

    problems = []
    app = app_version()
    html = read(INDEX)
    site, note, files, packs, features = site_info(html)
    print("App version      %s" % app)
    print("Website version  %s (hero note: %s)" % (site, note))
    if site != app or note != app:
        problems.append("website version (%s / %s) differs from the app (%s)" % (site, note, app))

    tags = (run("git", "tag", "--sort=-v:refname") or "").split()
    app_tag = "v" + app
    released = app_tag in tags
    since = args.since or next((t for t in tags if t != app_tag), None)

    def commits(rng, title):
        print("\n%s" % title)
        log = run("git", "log", "--no-merges", "--format=%h %s", rng) or ""
        shown = [line for line in log.splitlines() if re.match(r"\w+ (feat|fix|perf|docs)(\(|!|:)", line)]
        for line in shown:
            print("  " + line)
        if not shown:
            print("  (no feat/fix/perf/docs commits)")

    if since:
        end = app_tag if released else "HEAD"
        commits("%s..%s" % (since, end), "In %s (%s..%s)" % (app_tag if released else "the next release", since, end))
        if released:
            commits("%s..HEAD" % app_tag,
                    "Not released yet (%s..HEAD): describe on the site only once shipped" % app_tag)
        files_changed = run("git", "diff", "--stat", since, "--", "USER_GUIDE.md", "DECISIONS.md", "website")
        if files_changed:
            print("\nDocs changed since %s:\n%s" % (since, files_changed))
    else:
        print("\n(no earlier tag to compare with)")

    print("\nFeatures on the site (%d): %s" % (len(features), "; ".join(re.sub("<[^>]+>", "", f) for f in features)))

    wanted = ["Biverse-%s-%s.zip" % (site, f) for f in files] + ["Biverse-%s-%s.zip" % (p, site) for p in packs]
    if args.offline:
        print("\nLinks the page builds (not checked, --offline):")
        for w in wanted:
            print("  " + w)
    else:
        raw = run("gh", "release", "view", "v" + site, "--json", "assets,isDraft,publishedAt")
        if raw is None:
            problems.append("no GitHub release v%s yet (or gh is not signed in); every download link would 404" % site)
        else:
            data = json.loads(raw)
            assets = set(a["name"] for a in data.get("assets", []))
            print("\nRelease v%s: %d assets%s" % (site, len(assets), " (DRAFT)" if data.get("isDraft") else ""))
            for w in wanted:
                ok = w in assets
                print("  %s %s" % ("ok     " if ok else "MISSING", w))
                if not ok:
                    problems.append("download link would 404: %s" % w)
            extra = sorted(a for a in assets if a.endswith(".zip") and a not in wanted)
            if extra:
                print("  Assets the page doesn't link to: %s" % ", ".join(extra))

    if problems:
        print("\nProblems:")
        for p in problems:
            print("  - " + p)
        return 1
    print("\nNo problems found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
