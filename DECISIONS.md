# Decisions

Choices made where the brief was silent or contradictory, with the reason for each.
"Spec" means the original build brief.

## Naming

- **Product name: Biverse (v1.3).** The original brief used both "BiVerse" and *VerseCast*.
  v1.0–v1.2 showed "BiVerse" to users and kept `versecast` as the Python package and
  `org.versecast.app` as the macOS bundle id. From v1.3 the name is **Biverse** everywhere:
  - window titles, `Biverse.exe`, `Biverse.app` and zip names (`Biverse-<version>-<build>.zip`)
  - the Python package `biverse` (`python -m biverse`) and `packaging/biverse.spec`
  - the bundle id `org.biverse.app`. macOS will ask for microphone permission again once,
    because it sees a new app.
  - the settings folder `%APPDATA%\Biverse`, `~/Library/Application Support/Biverse`,
    `~/.config/biverse`. On Windows and default macOS disks, names are case-insensitive, so the
    old `BiVerse` folder is the same folder. On case-sensitive disks it is renamed on first run.
- **Repository layout.** The local git repository root was the parent `personal/` folder. To
  put `.github/` at the repository root, `biverse/` was made its own checkout of the same
  remote (`CeoFred/biverse`), continuing its history. The parent repository was left as it
  was.

## Bible data

- **31,102 verses, not 31,103.** The scrollmapper CSVs have 31,103 *lines*, including the
  header. The KJV has 31,102 verses. The builder and tests assert 31,102 verses.
- **The KJV verse grid is canonical.** Every translation is stored on the KJV grid (the
  `chapters` table). WEB puts the Romans doxology at 14:24–26. Verses outside the grid are
  appended to the last grid verse of their chapter (WEB Romans 14:23). Grid verses a
  translation lacks are stored empty, and the slide then reads "(Matthew 17:21 is not
  included in the ASV.)". This affects 16 verses in ASV and BBE and 7 in WEB.
- **WEB** comes from eBible.org `engwebp_vpl.zip`. eBible does not version its download URLs,
  so a checksum change is reported as a *warning*, not a failure (`--strict` makes it a
  failure). The structure is still validated. The checksum actually used is recorded in the
  database's `meta` table. If eBible is unreachable, the build continues without WEB.
- **Cleanup.** Markup, `{notes}` and pilcrows are stripped. Square brackets are removed: in the
  KJV they mark italics (`[but]`), and in the ASV they open "[Selah". BBE's `***` markers for
  unclear text become `…`. YLT's backtick quotes become `'`, and `--` becomes an em dash.
- **The database is built in CI, not committed.** It is about 27 MB, and it is fully
  reproducible from pinned sources.
- **Licensed translations go to a separate user database** (`user_translations.db` in the
  settings folder), so they survive updates and are never bundled. Import them with
  `tools/import_translation.py` or `Biverse --import-translation`.
- **No FTS.** Word-wise `LIKE` search takes 20–40 ms over a translation, so the optional
  runtime FTS table was not added. Exact-order matches are ranked first, then all-words
  matches.
- **Online versions come from the YouVersion Platform API, with each user's own app key**
  (Settings -> Bibles). No key, no online versions; nothing is bundled. Text is fetched a
  whole chapter at a time (`/v1/bibles/{id}/passages/JHN.3?format=html`; verse ranges such
  as `JHN.3.16-JHN.3.18` return 404) and split on the `yv-v` verse markers. Psalm titles
  (`d`), cross references (`rq`), signatures (`sig`) and notes (`iex`) are dropped. Verses a
  version leaves out come back empty, so they get the usual "not included" slide.
- **Licensed online text is never written to disk.** It stays in memory for one hour, the
  API's own `max-age`. Versions under YouVersion licence 1 ("Public Domain and Creative
  Commons") are also kept in `online_bibles/online_free.db`, so they work offline. Only the
  version list (titles, copyright lines) is saved, tied to a hash of the key and languages.
  The publisher licences (NIV, NASB, AMP, TPT...) were not reviewed; check them before
  storing licensed text.
- **Offline fallback.** One failed request marks the client offline for 30 s, so a dropped
  connection costs one 3 s wait, not one per slide. While offline, chapters are retried in
  the background only, and the slide shows the fallback translation (Settings, default KJV),
  labelled with that code. It switches back by itself once a retry succeeds. Following the
  reading and phrase search use local translations only.

## Parser

- **A verse table is embedded for validation** (`biverse/versification.py`, generated from
  the KJV). The parser validates without opening the database, and the app passes the
  database's `verse_count` in. Both hold the same numbers, and the DB builder asserts that
  they agree.
- **Single-chapter books.** "Jude 3" and "Philemon 6" mean verse 3 and verse 6, as people say
  them. "Jude 2:1" is still rejected.
- **Speech merges hundreds.** Vosk turns "one hundred fifty six" into 156. When 156 is not a
  chapter but 150:6 is, the parser reads 150:6. Likewise "psalm one fifty six" becomes
  150:6. This rule applies to speech only.
- **A strict book is rejected when its chapter number is not followed by a verse.** The
  invalid reference is skipped as a whole. For example, the "verse 1" in "jude chapter two
  verse one" is not reread as a relative reference.
- **Strictness applies to one-word names only.** "Acts of the apostles 2 38" and "first john
  1 9" are accepted without the "chapter" word.
- **Abbreviations are typed-mode only.** Roman `i`/`ii`/`iii` and ordinals become digits only
  before a numbered-book name.
- **`Reference` has two extra fields:** `explicit_verse` (chapter-only references show verse 1
  and are not sent live by auto-mode safety) and `span` (token positions, used by the
  detector's context handling).
- **Recorded mis-transcriptions (spec §15).** In CI, Vosk's small model heard espeak-ng's "john
  chapter three verse sixteen" as "jog chapter three were sixteen". "jog" is now a spoken name
  for John (strict, so it needs a chapter and a verse). "were", "versus", "vers" and "worse"
  count as "verse" only *between* a chapter number and a verse number. "we were sixteen
  people" still does not match. More entries should be collected from real sermons.
- **Speech engine: sherpa-onnx with Kroko by default and an optional Parakeet pack (v1.1).**
  A real service showed the small Vosk model failing on accented speech. Eight offline models
  were benchmarked. The test set was 40 random clips of OpenSLR 70 (Nigerian English, CC BY-SA)
  for word error rate, and 192 synthetic sermon clips (8 voices including South African
  English, clean and with noise) for reference detection and false positives:

  | Model | WER (Nigerian) | Refs found | Wrong verses | Speed (RTF, 2 threads) | RAM |
  |---|---|---|---|---|---|
  | Vosk small 0.15 | 32.5 % | 30/96 | 0 | 0.127 | low |
  | Vosk 0.22-lgraph | 28.5 % | 34/96 | 0 | 0.688 | |
  | NeMo streaming CTC 80 ms | 23.4 % | 36/96 | 0 | 0.103 | |
  | Whisper base.en | 19.2 % | 48/96 | 0 | 0.060 | |
  | Kroko (2025-08-06) | 19.9 % | 67/96 | 0 | 0.019 | ~370 MB |
  | Moonshine base | 14.3 % | 60/96 | 0 | 0.016 | ~650 MB |
  | Whisper small.en | 11.3 % | 70/96 | 0 | 0.131 | |
  | **Parakeet TDT 0.6B v2 int8** | **7.3 %** | **88/96** | 0 | 0.055 | ~1.6 GB |

  Kroko is built into every download because it is small (81 MB), streaming and light.
  Parakeet ships as a separate pack (about 480 MB) because of its size and RAM. "Automatic"
  uses Parakeet only on 64-bit computers with at least 6 GB RAM. Its phrases are cut at pauses
  by Silero VAD (0.45 s silence, maximum 12 s). sherpa-onnx has wheels for Python 3.8, win32 and
  macOS, and it needs no numpy. Whisper-based Python packages (faster-whisper, pywhispercpp)
  need Python 3.9+ and numpy, which would drop the Windows 7 builds.
- **Vosk stays as a fallback** in the Windows legacy builds only, because ONNX Runtime may not
  load on Windows 7. If sherpa-onnx fails to import, "Automatic" picks Vosk with its reference
  listener.
- **The Intel Mac build uses python.org Python 3.12, not 3.8.10 (v1.2.1).** python.org 3.8.10 bundles
  Tk 8.6.8, which on macOS 11/12 drew both Biverse windows black and crashed (reported on an
  Intel Mac running macOS 11/12 with v1.1.0). Tk 8.6.10+ fixed this. The python.org 3.12 installer
  (universal2, macOS 10.13+) ships Tk 8.6.13+. On macOS the packaged self-test now *fails* if Tk
  is older than 8.6.10, so a regression cannot ship. The Windows legacy builds stay on 3.8.10
  for Windows 7.
- **The minimum macOS for the Intel build rises from 10.13 to 10.15,** because sherpa-onnx's
  macOS wheels target 10.15.
- **Audio is resampled to 16 kHz in Python before it reaches sherpa-onnx** (box-filter
  decimation for 48/32 kHz, linear otherwise). sherpa-onnx aborts the whole process if a
  stream's sample rate changes, which happened when padding the end of a stream at 16 kHz
  after 48 kHz input.
- **Parser support for neural-model output:** digits with colons and dashes ("Genesis 2:18",
  "3:16-18"), and merged chapter+verse digits ("Philippians 413" → 4:13), the latter in speech
  mode only and never for strict books ("my job 365 days").
- **Model packs** are zips holding one model folder with `biverse-model.json`. They are
  validated (no absolute or `..` paths, exactly one folder, a known engine) before extraction,
  unpacked into a temporary folder and then moved into place, inside the settings folder.
- **Kroko licence caveat:** the model card says CC-BY-SA, but the repository's LICENSE file is
  empty and gives no version. Ask Banafo to confirm the exact terms before wide distribution.
- **Voice navigation (v1.2).** "next verse", "go back", "next/previous chapter" act on the live
  slide in Auto mode and on Preview in Manual mode, matching how detections behave in each
  mode. Explicit phrases are matched anywhere in an utterance. The bare words
  "next"/"back"/"previous" count only when they make up an utterance of five words or fewer
  after filler words ("okay next please"), because they are everyday words. With both models
  running, the same command arriving from the other model within 3 s is ignored. "Move to
  verse 8" is a relative reference rather than a command: the UI tells the detector which book
  and chapter are on screen (`Detector.set_position`), and relative verses resolve against the
  newest of that and the last detection.
- **Bible version by voice (v1.3)** stays switched until it is changed again, as the user chose.
  A request needs a switching verb ("switch/change/use/show"), a "read … in …" instruction at
  the start of the sentence, or a short request ("ASV please"). "As we read in the King
  James…" and "the King James version says…" are quotations and do not switch. Names are
  matched longest first ("New King James" before "King James", "New American Standard" before
  "American Standard"). Spelled-out abbreviations are joined ("k j v" → kjv). "young" and
  "amp" alone are not names ("the young people", "the amp").
- **Emphasis (v1.3)** is stored per translation, book, chapter and verse as word indices in
  `emphasis.json`, because word positions differ between translations. Verses with marks are
  drawn word by word, using the same greedy wrap and auto-fit size as plain verses, so line
  breaks don't change when marks are added. Plain verses still use the single text item
  (unchanged rendering). Highlighted words use dark text on the highlight colour for contrast.
- **Modern look (v1.3)** uses ttk "clam" restyled with two palettes; the native aqua and vista
  themes cannot be recoloured. It follows the OS dark/light setting (macOS `defaults`, the
  Windows registry, GNOME `gsettings`), re-checked every 5 s. `BIVERSE_THEME` forces one look
  for screenshots.
- **Sermon summary (v1.3).** The built-in summary is extractive and offline: sentences of 7–60
  words, scored by frequent content words, with a bonus for signposts ("the point is",
  "remember", "number one", "in conclusion") and for sentences within 60 s after a scripture.
  It shows the top 7 in chronological order, plus the scriptures and a timeline.

  The optional AI pack is Qwen2.5-1.5B-Instruct (Apache-2.0; the 3B model's licence is not
  Apache) run by llama.cpp's `llama-completion` as a separate process, so there are no Python
  dependencies and no network. One pack holds the binaries for macOS (both CPUs), Windows x64
  and Linux x64. The model only sees the extractive key points and scriptures (small prompt,
  fast, grounded), and is told not to add verses.

  Biverse checks the platform before offering it (`llm.unsupported_reason`): 32-bit builds,
  Windows before 10 (llama.cpp's release builds need it) and platforms without a binary
  (ARM Windows/Linux) get a clear reason, and the pack installer refuses the pack there. macOS
  below 13.3 (the deployment target of llama.cpp's macOS releases) gets a warning only, since
  this is not verified.

  It was **not run locally**: executing the downloaded binary was blocked by the session's
  permission policy. A CI job (`ai-summary`) runs the real model on Linux, and a stand-in
  program tests the integration on every platform.
- **Following the reading (phase 2).** `biverse/follow.py` aligns the last 12 spoken words
  (Kroko partials, about 5 updates a second) with the live verse in every installed translation,
  using a fuzzy in-order longest common subsequence. Spoken and verse words count as equal if
  identical, if they share a 4-letter prefix, or if their similarity ratio is at least 0.75.
  - **End trigger:** the newest words reach the last word, or the third-to-last word for
    verses of 16+ words, and half the verse (at least 3 words) has been matched.
  - **Start trigger:** the newest 8 words match the opening of the next verse (or one or two
    after it, for skipped verses), with at least 4 words in order, 2 of them content words
    (not "and the for God…"), and they fit that verse better than the current one.
  - **Guards:** 0.8 s minimum per verse. The end trigger never fires on the last verse of a
    range; only reading the next verse aloud continues past it.
  - **Mode:** following moves the live slide in Manual mode too, because the operator already
    approved the passage. It does not follow while the screen is blank or black.

  **Benchmark:** 7 passages (John 3:16–18, Psalm 23, Romans 8:28–31, Genesis 1:1–5,
  1 Corinthians 13:4–8, Matthew 5:3–9, Philippians 4:6–8) × 4 voices (US, UK, Indian, South
  African), 104 verse changes, run through the real Kroko engine:
  - 104/104 followed, 0 wrong verses, 0 premature (before 60% of a verse).
  - The slide changes a median of 0.31 s after the verse ends; 90 % within 1.03 s; worst 1.39 s.
  - Romans 8:29 → 8:30 ("…he also did predestinate" vs "whom he did predestinate") caused two
    premature moves until the "fits the current verse better" rule was added.
  - Moving one word earlier on long verses cut the median from 0.49 s to 0.31 s.
- **Navigation intents replace fixed phrases.** The v1.2 phrase list missed how preachers
  actually talk ("can we go back", "go back two verses", "back to the previous one") and
  misread "go back one more verse" as *next*. `commands.parse_intent` now combines an action,
  a direction, a scripture unit and an optional count. It has four kinds: step, goto,
  stop and resume. Every rule needs a scripture unit, "the next/previous one" plus a movement
  word, or an utterance made up only of the command (up to 8 words, filler ignored). Stop and
  resume phrases accept at most one trailing content word, so "let's continue to worship" and
  "keep reading your bible every day" are ignored. `tests/test_intents.py` holds about 150
  phrases that must work and about 85 that must not. Add real phrasings there.
- **A book-less "chapter N verse M" means the same book** as on screen. It is parsed only at
  the start of an utterance or after a lead word ("turn to chapter 4 verse 2", "in chapter 3
  verse 16"). "<garbled book> chapter 3 verse 5" therefore cannot be pulled into the current
  book. A chapter alone ("back to chapter 3") needs a movement verb and is handled as a goto
  intent.
- **"Back to where we started"** goes to the first verse of the passage last sent live.
- **Merged digits for strict books (v1.2).** "Job 120" → Job 1:20 and "John 316" → 3:16 at the
  user's request, unless the next word is a quantity (days, years, people, times, naira…). The
  known remaining risk: "my job 365" at the very end of a sentence becomes Job 36:5.
- **A dash between two numbers is a range only after "C:V" or "verse(s) N".** Parakeet writes
  "habakkuk two four" as "Habakkuk 2-4", which means chapter 2, verse 4.
- **Kroko + Parakeet together (v1.2).** A virtual "both" model runs Kroko (live partials, fast
  detections) and Parakeet (VAD phrases) on the same audio. Kroko's finals feed the detector on
  their own channel and stay grey in the transcript until Parakeet's line replaces them.
  "Automatic" prefers it when the pack is installed and the machine qualifies for Parakeet.
- **Hotwords: on for Kroko, off for Parakeet (v1.2).** Measured on 528 synthetic clips (all 66
  books in "turn with me to <book> chapter X verse Y", 4 voices US/UK/Indian/South African,
  clean and noisy), all with the same final parser:

  | Setup | References caught |
  |---|---|
  | Parakeet | 499/528 (94.5 %) |
  | Parakeet + hotwords (1.5) | 496/528 (93.9 %) |
  | Kroko | 413/528 (78.2 %) |
  | Kroko + hotwords (1.5) | 421/528 (79.7 %) |
  | Kroko + Parakeet together | **502/528 (95.1 %)** |

  On 96 ordinary-speech clips every setup had 0 false alarms. Parakeet already knows the rare
  names; its misses are near-miss spellings ("Habakku", "Nebamiah"), so the fuzzy name match
  helps more than biasing does. Hotwords at 2.0 started breaking "2 John" and "Haggai".
  Hotwords use modified beam search (4 paths) with a BPE vocab generated from the model's
  tokens.txt into the settings folder. If a model rejects them, Biverse falls back to plain
  decoding.
- **Near-miss book names** are matched with difflib (ratio ≥ 0.75, a clear margin over the
  next book, at least 5 letters, not a common English word). They count only when "chapter N"
  or "N verse M" follows. They get confidence 0.6, below the Auto-mode threshold of 0.65, so
  in Auto mode they go to Preview. A relative "verse N" never fires right after a number, so
  "<garbled book> chapter 3 verse 5" cannot become verse 5 of the chapter on screen.
- **The streaming flush pads 1.5 s of silence.** With 0.5 s, Kroko dropped the last word
  ("verse fi…"). The first benchmark run had this flaw, and it was corrected before the table
  above.
- **Reference-only second recogniser (v1.1).** Real use showed the small model turning
  "genesis two eighteen" into "genesis to a team". A second Vosk recogniser with a grammar of
  book names, number words and reference keywords now runs on the same audio. On 84
  synthetic clips (7 voices × 6 sentences, clean and with noise) the first reference was found
  15 times by the general recogniser alone and 46 times with the grammar recogniser. Because
  that recogniser forces any speech into book names and numbers, its output is trusted
  only for complete chapter-and-verse references. It gets no context carry-over across
  pauses, which in testing joined "mathew thirteen" and "fourteen" from separate utterances.
  It runs only for models with a dynamic graph (small and lgraph models). It can be turned off
  in Settings, since it roughly doubles recognition CPU.
- **Number homophones as the chapter.** "to/too" = 2, "for/fore" = 4, "ate" = 8 and "won" = 1
  are read as numbers only in the chapter position directly after a book name, and only if
  a number follows ("genesis to eighteen" → 2:18). "Romans 8, for we know" and "16 to 18"
  are unaffected.
- **Book names missing from the small model.** Its vocabulary has no "philippians",
  "thessalonians", "zechariah", "haggai" and others. What it produces instead was collected
  by synthesising "turn to <book> chapter four" in six voices. Consistent, rare outputs became
  spoken names ("zakaria", "malika", "galicians", "philadelphians", "ecclesiasties"). Outputs
  that are ordinary words ("look", "sam", "collections", "relations", "evasions") count only
  with chapter and verse (`MISHEARD_STRICT` in books.py). Thessalonians, Haggai, Habakkuk,
  Deuteronomy and Zephaniah came out as inconsistent noise and need a bigger model.
- **Chapter-only after a verse.** Mentioning "John chapter 3" within 60 s of John 3:16 is
  treated as a repeat and ignored. Hearing "John 3" and then "verse 16" updates the
  detection to John 3:16, the same way range extension works.

- **In-app model downloads (v1.4).** Biverse stays offline by default; it only goes online
  when the user presses Download in Settings → Models. Sources and SHA-256 checksums live in
  `biverse/catalog.py`, shared with `tools/fetch_model.py`, so build and app download the same
  pinned files from the upstream hosts (sherpa-onnx and llama.cpp GitHub releases, Hugging
  Face, alphacephei.com). We don't use our own release zips, whose checksums are only known
  after CI. The AI summary download takes only this computer's llama.cpp program (about
  1.1 GB in all, instead of the 1.2 GB all-platform zip).

  Downloads resume with HTTP Range from a `.part` file, so a dropped church Wi-Fi connection
  doesn't restart 480 MB. Files are verified before unpacking. Archives may only contain
  regular files under the model's folder, and the model is unpacked into a staging folder and
  moved into place whole. Archives are deleted after install. HTTPS uses the system
  certificates plus certifi's, because python.org's macOS Python (used for the Mac builds) has
  no system store.

  The download runs on a worker thread owned by the operator window, so it continues when
  Settings is closed. When it finishes, Biverse reloads the speech model if the setting is
  Automatic, and otherwise asks first. If listening is on, it waits until Stop, so a model
  switch never interrupts a sermon. "Install from a file…" stays for computers without
  internet.

## UI behaviour

- **Prev/Next (buttons and ←/→)** step the *live* slide when something is live, otherwise the
  preview. Stepping goes through a range first, then continues verse by verse through the
  Bible.
- **BLANK and BLACK toggle.** Pressing one again restores the verse, which is useful when
  someone presses Esc by accident.
- **One screen only.** If only one display exists, the output opens as a half-size *window*
  (a preview) rather than covering the operator window. F11 makes it full screen.
- **Display changes are detected automatically** on Windows and macOS, with a cheap check
  every 5 s. The Refresh button still exists, and it is the only option on Linux.
- **Opening an audio device runs in a background thread with an 8 s timeout.** PortAudio's
  open can block for a long time: macOS waiting for microphone permission, a Bluetooth
  headset switching profile, a wedged driver. During testing it blocked indefinitely on a
  Mac without microphone permission, which would have frozen the whole app. The UI shows
  "… is not responding" and a hint about the macOS permission instead.
- **Audio watchdog.** A stream that stops, or delivers no audio for 3 s, counts as lost. The
  app rescans devices and reopens the same device (matched by name and host API) every 3 s.
- **Windows host APIs.** MME and WASAPI are listed. DirectSound (duplicates) and WDM-KS
  (often fails to open) are hidden.
- **Downmix by averaging channels**, so a mixer feed on either channel is heard.
- **The level meter uses a 60 dB scale**, with fast attack and slow release.
- **Thumbnails** are laid out at the projector's real resolution and scaled down, so line
  breaks match what the congregation sees.
- **The default font is the first available of** Segoe UI, Helvetica Neue, Arial, DejaVu Sans,
  Liberation Sans and Helvetica. Text is bold with a shadow, white on black.
- **The settings dialog** is in its own module, `ui_settings.py`. Pure Preview/Live logic is in
  `controller.py`, so it can be unit-tested.

- **The operator window opens full screen (v1.4)**, which suits the media desk and small
  netbooks. F11 switches on Windows and Linux, and Ctrl+Cmd+F (or F11) on macOS; View → Full
  screen does the same. The choice is remembered. Escape stays Blank, as operators expect, so
  it does not leave full screen. The toggle tracks its own state because on macOS Tk reports
  `-fullscreen` only after the animation.

## Packaging and CI

- **Pinned versions.** vosk 0.3.44 and sounddevice 0.5.6 everywhere. PyInstaller 5.13.2 with
  `pyinstaller-hooks-contrib` 2023.10 for Python 3.8, and PyInstaller 6.22.3 for 3.12.
  vosk's own dependencies (cffi, requests, srt, tqdm) are pinned as well.
- **libvosk on macOS is named `libvosk.dyld`.** `collect_dynamic_libs` does not recognise that
  extension, so the spec adds it explicitly as a binary, which also gets it signed.
- **The sounddevice wheel ships every platform's PortAudio.** The spec keeps only this
  platform's and architecture's library, and drops the ASIO variants.
- **No UPX.** It causes antivirus false positives.
- **Windows smoke test.** `Biverse.exe` is a GUI-subsystem program with no console, so CI runs
  it with `Start-Process -Wait` and reads the JSON from `--report self-test.json`.
- **The Intel macOS runner is `macos-15-intel`**, the last Intel image GitHub announced
  (available until 2027). `macos-13` has been retired.
- **The Python 3.8 test job runs on `ubuntu-22.04`**, the newest image for which setup-python
  provides 3.8.
- **build.yml also runs on pull requests that touch the code.** `workflow_dispatch` only works
  once a workflow is on the default branch, and this lets the five builds run on the PR that
  introduces them.
- **Icons are drawn by `tools/make_icons.py`** with the standard library alone (no Pillow).
  ICO and ICNS embed PNG images. The mark (v1.3) is a gold voice waveform above an open Bible
  with a ribbon bookmark, on a navy tile. One geometry feeds both the rasteriser and the SVG
  writer, so the app icons, favicon and website logo always match. Below 33 px it draws three
  chunkier bars so it stays legible. The website's social image (`tools/make_og_image.py`) is the
  one asset that needs Pillow; it is a developer tool and is not used at runtime.
- **Optional macOS signing and notarisation** use the secrets `MACOS_CODESIGN_ID` and
  `MACOS_NOTARY_PROFILE`. Without them the app is signed ad hoc.

## In-app updates

- **The manifest is signed, the zip is checksummed.** The release job writes `latest.json`
  (version and, for each build flavour, the zip's URL, size and SHA-256) and
  `latest.json.sig`, a base64 Ed25519 signature of its exact bytes, using the secret
  `UPDATE_SIGNING_KEY` (`tools/make_update_key.py`, `tools/make_update_manifest.py`). The app
  pins the public key in `biverse/updates.py` and installs nothing the signature and checksum do
  not vouch for. Download URLs must be HTTPS on github.com. Without the secret, a release gets
  no manifest and is simply not offered.
- **Pure-Python Ed25519** (`biverse/ed25519.py`, the RFC 8032 algorithm, about 3 ms per check).
  Python 3.8 has no Ed25519 in the standard library, and adding `cryptography` or PyNaCl to the
  runtime for one check is not worth it. It is not constant-time, which does not matter for
  verifying public data or for signing on a CI runner.
- **Each build knows its flavour.** The spec writes `build.json` (`{"flavour": <matrix name>}`)
  from `BIVERSE_FLAVOUR`, so a 32-bit Windows 7 copy is offered the `windows-legacy-x86` zip and
  never a 64-bit one. A copy run from source has no `build.json` and is never offered updates.
- **The new copy installs itself.** `--apply-update <app> --wait-pid <pid> [--relaunch]` runs
  from the unpacked update: it waits for the old process to exit, renames the old app to
  `Biverse.old` / `Biverse.old.app` (kept for rollback, replaced at the next update), copies
  itself into place (`ditto` on macOS to keep signatures and links) and starts it. A failed copy
  puts the old app back. The result goes to `updates/result.json` for the next start to report.
  Copying rather than moving works on Windows, where a running program's folder cannot be moved.
- **Fallback: show the zip.** When the app folder cannot be written to, or macOS runs a
  translocated copy (`/AppTranslocation/`), Biverse downloads the zip and shows it in
  Finder/Explorer instead.
- **Never during a service.** Automatic checks happen at most every 12 hours and not while
  listening; offers that arrive while listening wait until it stops. The download reuses the
  model downloader (`catalog.fetch_verified`): it resumes from a `.part` file after Cancel, a
  closed app or a dropped connection.

## Idle screen

- **What counts as "read".** The idle timer (`controller.IdleTimer`) restarts on every live
  change (Go Live, Prev/Next, a voice command, the follower moving on) and whenever the reading
  follower's progress through the live verse grows. So a long verse read slowly stays up, and
  the verse comes back the moment the preacher carries on reading it. Redraws that are not live
  changes (translation switch, settings, an online text arriving) leave the idle state alone.
- **Hidden, not cleared.** Idle only changes what is drawn (`LiveState.idle`); the live selection
  and the follower stay on the verse, which is what lets the reading bring it back. BLANK and
  BLACK are the operator's and always win; the timer does not run under them.
- **Off by default** ("Keep the verse on screen"), so nothing changes for existing users until
  they choose an idle action.
- **Pillow for pictures** (11.3.0; 10.4.0 is the last release for Python 3.8). Tk's PhotoImage
  reads only PNG and GIF and scales by integer factors, which left gaps or blocky pictures on a
  projector. Pillow adds JPEG and WebP, EXIF rotation and a smooth "cover" scale (centre-crop to
  the screen). Pictures are decoded once at no more than 3840 px a side (JPEG draft mode), and the
  scaled copy is cached per size. Without Pillow the app falls back to PhotoImage, and the
  self-test's `pictures` check fails the CI build if Pillow is not bundled. Video (phase 2) is
  still on the roadmap.

## Dependencies

Runtime dependencies are vosk, sounddevice, Pillow (pictures) and the standard library. vosk itself pulls
in cffi, requests, srt and tqdm. Biverse never uses requests or tqdm, which vosk needs only for
its model *download* helpers. The app goes online only for downloads the operator starts, online
Bible versions when turned on, and the update check. Build-time-only tools are
PyInstaller, pytest and ruff.
