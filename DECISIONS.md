# Decisions

Choices made where the brief was silent or contradictory, with the reason for each.
"Spec" means the original build brief.

## Naming

- **Product name: BiVerse.** The brief opens with "You are building BiVerse" but later uses
  *VerseCast* for the package, settings folder, zip names and bundle id. Everything a user
  sees uses **BiVerse**: window titles, `BiVerse.exe`, `BiVerse.app`, zip names
  (`BiVerse-<version>-<build>.zip`) and the settings folder (`%APPDATA%\BiVerse`,
  `~/Library/Application Support/BiVerse`, `~/.config/biverse`). Two internal identifiers
  keep the spec's literal values because they were spelled out explicitly: the Python package
  is `versecast` (per the package layout) and the macOS bundle identifier is
  `org.versecast.app`. The PyInstaller spec keeps the name `packaging/versecast.spec`.
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
  `tools/import_translation.py` or `BiVerse --import-translation`.
- **No FTS.** Word-wise `LIKE` search takes 20–40 ms over a translation, so the optional
  runtime FTS table was not added. Exact-order matches are ranked first, then all-words
  matches.

## Parser

- **A verse table is embedded for validation** (`versecast/versification.py`, generated from
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

## Packaging and CI

- **Pinned versions.** vosk 0.3.44 and sounddevice 0.5.6 everywhere. PyInstaller 5.13.2 with
  `pyinstaller-hooks-contrib` 2023.10 for Python 3.8, and PyInstaller 6.22.3 for 3.12.
  vosk's own dependencies (cffi, requests, srt, tqdm) are pinned as well.
- **libvosk on macOS is named `libvosk.dyld`.** `collect_dynamic_libs` does not recognise that
  extension, so the spec adds it explicitly as a binary, which also gets it signed.
- **The sounddevice wheel ships every platform's PortAudio.** The spec keeps only this
  platform's and architecture's library, and drops the ASIO variants.
- **No UPX.** It causes antivirus false positives.
- **Windows smoke test.** `BiVerse.exe` is a GUI-subsystem program with no console, so CI runs
  it with `Start-Process -Wait` and reads the JSON from `--report self-test.json`.
- **The Intel macOS runner is `macos-15-intel`**, the last Intel image GitHub announced
  (available until 2027). `macos-13` has been retired.
- **The Python 3.8 test job runs on `ubuntu-22.04`**, the newest image for which setup-python
  provides 3.8.
- **build.yml also runs on pull requests that touch the code.** `workflow_dispatch` only works
  once a workflow is on the default branch, and this lets the five builds run on the PR that
  introduces them.
- **Icons are drawn by `tools/make_icons.py`** with the standard library alone (no Pillow).
  ICO and ICNS embed PNG images.
- **Optional macOS signing and notarisation** use the secrets `MACOS_CODESIGN_ID` and
  `MACOS_NOTARY_PROFILE`. Without them the app is signed ad hoc.

## Dependencies

Runtime dependencies are only vosk, sounddevice and the standard library. vosk itself pulls
in cffi, requests, srt and tqdm. BiVerse never uses requests or tqdm, which vosk needs only for
its model *download* helpers, and the app makes no network calls. Build-time-only tools are
PyInstaller, pytest and ruff.
