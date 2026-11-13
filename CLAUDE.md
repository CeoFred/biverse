# BiVerse – notes for Claude

## graphify (token-efficient code navigation)

A knowledge graph of this repo lives in `graphify-out/` (git-ignored).

- Before reading many files to answer "how does X work / what calls Y", query the graph:
  `graphify query "<question>"`, `graphify explain "<Symbol>"`, `graphify path "A" "B"`.
  Start with `graphify-out/GRAPH_REPORT.md` for the module map (communities, god nodes).
- Read source files only for the parts the graph points to.
- After code or doc changes, refresh it with `/graphify . --update`.
- If `graphify` is not on PATH, the interpreter is in `graphify-out/.graphify_python`.

## Project quick facts

- Python 3.8-compatible code (`from __future__ import annotations`, no 3.9+ APIs).
- Tests: `.venv312/bin/python -m pytest -q` (3.12) and `.venv38/bin/python -m pytest -q` (3.8).
- Lint: `.venv312/bin/ruff check .`
- Models live in `models/` (`python tools/fetch_model.py --name kroko,vosk-small,parakeet`).
- Design decisions and benchmarks: `DECISIONS.md`.
