# Roadmap

Planned work. When something ships, its reasoning and benchmarks move to `DECISIONS.md`.

## Next

1. **Website release skill** (`.claude/skills/website-release/`). After each release: gather the
   changes since the previous tag, check the release assets exist, update features, downloads, FAQ
   and screenshots on the website, verify, then open a PR.
2. **Idle screen.** When no verse has been read for N seconds (configurable, default 30): do
   nothing, clear to the blank screen, or show an idle background (a colour, a picture, or a
   looping muted video). The timer resets on any live change and while the follower still hears
   the live verse being read. The verse comes back as soon as a new one goes live or the reading
   resumes. Phase 1: colour and pictures (adds Pillow for JPEG/WebP and smooth scaling). Phase 2:
   video (PyAV, 64-bit builds only), after a CPU spike on an old laptop.
3. **Verses recognised from their words: real sermons and phase 2.** Phase 1 shipped (see
   DECISIONS.md): suggestions under Possible references, clicked to preview or go live. Next:
   - benchmark real sermon transcripts: run `tools/bench_quotes.py transcript.txt --review
     review.tsv`, mark each suggestion right or wrong, then label the quotes (`=> Ref`) and add
     the file to `tests/data/quotes/`;
   - when real transcripts show no false go-lives, set `quotes.AUTO_LIVE_ALLOWED` so "Send strong
     matches live automatically" (Auto mode only, off by default) can be turned on;
   - phase 2: an optional embedding pack that matches paraphrases (suggestions only).

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
