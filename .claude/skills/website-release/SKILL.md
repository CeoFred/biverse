---
name: website-release
description: Keep the Biverse website (website/, deployed on Vercel) in step with the app. Use after tagging or publishing a Biverse release, after a version bump in biverse/__init__.py, when new features, settings, downloads or packs have landed, or whenever the user says "update the website", "refresh the site", "the site is out of date", "add X to the website" or "we just released vX". Also use when a feature changes something the site promises (offline use, supported OS versions, downloads), even if the user didn't mention the website.
---

# Website release

The site is one static page, `website/index.html`, plus `site.js` and `styles.css`, with no build
step. It does two jobs, and a release can break either one:

1. **Downloads.** `site.js` builds every download link from `data-version` on `<html>`:
   `releases/download/v<version>/Biverse-<version>-<data-file>.zip` and
   `Biverse-<data-pack>-<version>.zip`. If the version points at a release whose files don't exist
   yet, or a `data-file`/`data-pack` name has no matching asset, visitors get a 404.
2. **Claims.** The copy promises things: "no internet", which OS versions are supported, what is
   free, what each pack needs. A feature can make a claim untrue (for example, an update check
   breaks "only goes online when you press Download"). A false claim on a church's media desk is
   worse than a missing feature.

So the job is: bring both up to date, check them, then hand over a PR.

## 1. Find out what changed

Run the helper from the repo root. It prints the app version, the website version, the previous
tag, the `feat`/`fix` commits since it, the release assets on GitHub and any link that would 404:

```bash
.venv312/bin/python .claude/skills/website-release/scripts/site_check.py
```

Pass `--since vX.Y.Z` to compare against a specific tag, or `--offline` to skip GitHub.

Then read what the commits actually did, in this order of trust: `USER_GUIDE.md` (what users are
told), the `DECISIONS.md` diff (limits and numbers), then the code. Commit subjects are short and
sometimes describe internals, so check before writing a claim about them.

## 2. Decide what the site needs

For each user-visible change, decide where it belongs. Most commits need nothing on the site
(fixes, refactors, CI). Things that usually do:

| Change | Where |
|---|---|
| New version released | `data-version` on `<html>` and the `.ver` span in the hero note (a test checks both match `biverse.__version__`) |
| New user-facing feature | A `<div><dt>…</dt><dd>…</dd></div>` in `#features`. Keep the grid even (currently 9). Merge or replace a weaker item instead of growing it without limit |
| New or renamed build flavour | A row in the `#download` table, the `data-os` hint in `site.js` `detect()`, and the AI table if it affects the AI summary |
| New or renamed pack | A row in "Optional packs" with `data-pack` matching the release asset name |
| Changes to network use, privacy, OS support, price or licences | The FAQ, the hero lede, the `facts` row and the `<meta name="description">`/`og:description` |
| A visible UI change | Screenshots (see step 4) |

Before writing, search the page for every claim the change touches: `grep -n -i "internet\|offline\|online" website/index.html`.
The same promise is often repeated in the hero, facts, FAQ and meta tags.

## 3. Write in the site's voice

The page is read by church media volunteers, often non-technical, on old laptops and phones.
Match the existing copy:

- Plain words, short sentences, no hype ("powerful", "seamless", "revolutionary").
- Say what it does from the user's side: "Settings → Models downloads a model with a progress
  bar", not "async resumable downloader".
- Exact numbers and limits from `DECISIONS.md`/`USER_GUIDE.md` (RAM, OS versions, sizes). Never
  round a limit in the user's favour.
- Name menu paths with `→` and keys as they appear in the app.
- Keep each `<dd>` to one or two sentences.

## 4. Screenshots and images (only when the UI visibly changed)

Screenshots are WebP copies of `docs/screenshots/*.png`, made by `tools/screenshots.py` under Xvfb
(Linux). On macOS without Xvfb, say what changed and ask the user whether to retake them. Don't
ship screenshots of an older UI next to copy describing a newer one. The social image comes from
`python3 tools/make_og_image.py` (needs Pillow); it only needs regenerating when the tagline or
mark changes.

## 5. Check

```bash
.venv312/bin/python -m pytest -q tests/test_website.py
.venv312/bin/python .claude/skills/website-release/scripts/site_check.py
```

`site_check.py` exits non-zero when a download link would 404. Don't hand over a site in that
state. If the assets are missing only because the release workflow is still running (`gh run list
--workflow build.yml`), say so and wait. Merging a version bump to `main` deploys it straight away.

Then look at the page: start the `website` preview from `.claude/launch.json`, check the console
for CSP errors (`vercel.json` allows only same-origin scripts and Google Fonts), and take
screenshots at desktop width and at phone width (375 px). Check the new copy wraps cleanly and
nothing scrolls sideways.

## 6. Hand over

Follow the user's git conventions (the `git-conventions` skill): a branch such as
`docs/website-v1.5.0`, a commit like `docs(website): v1.5.0 – update notice and idle screen`, and
a PR whose body lists each change and the claim or commit behind it.

Vercel deploys `main` through its git integration, so merging is deploying. Don't merge, push to
`main`, or run `npx vercel --prod` without the user saying so in this conversation. A preview
(`npx vercel`) is fine to offer.

Finish with a short report: what changed on the site, which commits needed nothing, and anything
left for the user (screenshots to retake, release still building).
