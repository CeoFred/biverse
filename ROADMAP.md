# Roadmap

Planned work. When something ships, its reasoning and benchmarks move to `DECISIONS.md`.

## Next

1. **Website release skill** (`.claude/skills/website-release/`). After each release: gather the
   changes since the previous tag, check the release assets exist, update features, downloads, FAQ
   and screenshots on the website, verify, then open a PR.
2. **Update notice, download with progress, install.** Biverse checks for a new release by itself
   (on by default, can be turned off, never while listening) and offers it: Download / Later /
   Skip this version. The download shows a progress bar with size, speed and time left, can be
   cancelled and resumed, and keeps going in the background with progress in the status bar. The
   update is installed with "Restart now" or "When I close Biverse". Each build records its
   flavour in `build.json`, and CI publishes a signed `latest.json` (Ed25519). Installing swaps the
   app folder from the new copy (`--apply-update`) and keeps a `.old` copy for rollback. Falls back
   to opening the downloaded zip when the folder can't be written to or macOS runs a translocated
   copy. The website FAQ about going online changes with it.
3. **Idle screen.** When no verse has been read for N seconds (configurable, default 30): do
   nothing, clear to the blank screen, or show an idle background (a colour, a picture, or a
   looping muted video). The timer resets on any live change and while the follower still hears
   the live verse being read. The verse comes back as soon as a new one goes live or the reading
   resumes. Phase 1: colour and pictures (adds Pillow for JPEG/WebP and smooth scaling). Phase 2:
   video (PyAV, 64-bit builds only), after a CPU spike on an old laptop.
4. **Verses recognised from their words.** Recognise a verse from the preacher's words when no
   reference is spoken. An index of word 3-grams in `bible.db` finds candidates, which are ranked
   by alignment. The best match goes to Preview, marked "Possible reference" with the words that
   matched. A "Possible references" list shows the top 5 with match strength, and the operator can
   push any of them live (double-click, Enter, or keys 1–5). Setting: "Send strong matches live
   automatically" (off by default; Auto mode only; a strong, unique match confirmed twice). A
   benchmark must show no false go-lives before that setting can be turned on. Phase 2: an
   optional embedding pack that matches paraphrases (suggestions only).

## Later

### Mark speaking in tongues in the transcript

No dedicated model for this exists, so it has to be inferred: fluent speech that doesn't come out
as English.

- **Signals** (window of about 4 s, with hysteresis: about 3 s to enter, about 2 s to leave):
  - the VAD hears speech, but the recogniser outputs few or no words
  - a high share of words not in an English word list
  - Kroko and Parakeet disagree strongly with each other
  - repetitive syllables with little variety
  - low recogniser confidence
- **Real languages are the main risk.** Yoruba, Igbo, Twi or Swahili look the same on these
  signals. A language-ID model (for example the sherpa-onnx spoken-language-ID model on
  onnxruntime) must rule them out. Those get `[other language]`, and `[tongues]` appears only when
  no language is recognised confidently. Singing (steady pitch and energy) is marked `[singing]`.
  The operator can change or remove any label.
- **What the app does:** the transcript shows one `[tongues]` line with a time span. Verse
  detection and quoted-verse matching pause, and the live screen stays as it is. The sermon record
  notes the span and leaves it out of the AI summary. Setting: on by default.
- **Needs:** 30–60 minutes of real service audio with speaking in tongues, local-language prayer
  and preaching, singing and plain English. Speaking in tongues can't be produced synthetically.
- **Order:** after quoted verses, which need the same transcript and benchmark setup. First the
  transcript label only, then language ID before labels appear in the sermon summary.
