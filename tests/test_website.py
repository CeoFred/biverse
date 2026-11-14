from __future__ import annotations

import json
import os
import re

import biverse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "website")


def test_website_version_matches_app():
    with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
        html = f.read()
    m = re.search(r'data-version="([^"]+)"', html)
    assert m and m.group(1) == biverse.__version__, "update data-version in website/index.html"
    assert ">%s<" % biverse.__version__ in html  # the visible version note


def test_website_files_referenced_exist():
    with open(os.path.join(WEB, "index.html"), encoding="utf-8") as f:
        html = f.read()
    for path in re.findall(r'(?:src|href)="/([^"#]+)"', html):
        assert os.path.isfile(os.path.join(WEB, path)), path
    with open(os.path.join(WEB, "vercel.json"), encoding="utf-8") as f:
        json.load(f)
