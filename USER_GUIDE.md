# Biverse user guide

Biverse listens to the preacher. When it hears a Bible reference ("John chapter three verse
sixteen"), it puts the verse on the projector or TV. It is free, needs no internet and sends
nothing anywhere.

This guide is written for church volunteers. You do not need to be technical.

- [1. Installing](#1-installing)
- [2. Connecting the projector](#2-connecting-the-projector)
- [3. Choosing the sound source](#3-choosing-the-sound-source)
- [4. Running a service](#4-running-a-service)
- [5. Manual and Auto mode](#5-manual-and-auto-mode)
- [6. Searching](#6-searching)
- [7. Keyboard shortcuts](#7-keyboard-shortcuts)
- [8. Settings](#8-settings)
- [9. Speech models: getting the best recognition](#9-speech-models-getting-the-best-recognition)
- [10. Adding a licensed translation](#10-adding-a-licensed-translation)
- [Bible versions, emphasis and the sermon summary](#bible-versions-emphasis-and-the-sermon-summary)
- [11. Troubleshooting](#11-troubleshooting)

---

## 1. Installing

Download the right file from the project's **Releases** page.

| Your computer | Download |
|---|---|
| Windows 10 or 11 (almost all PCs from the last 10 years) | `Biverse-…-windows-x64.zip` |
| Windows 7 or 8, 64-bit | `Biverse-…-windows-legacy-x64.zip` |
| Windows 7 or 8, 32-bit (older netbooks) | `Biverse-…-windows-legacy-x86.zip` |
| Mac with Apple Silicon (M1, M2, M3, M4…) | `Biverse-…-macos-arm.zip` |
| Mac with an Intel processor, macOS 10.15 or newer | `Biverse-…-macos-intel.zip` (also runs on Apple Silicon) |
| Optional, for the best recognition (see section 9) | `Biverse-model-pack-parakeet-….zip` |

To check your Windows type: **Start → right-click Computer / This PC → Properties**, then look
at "System type". To check your Mac: **Apple menu → About This Mac**, then look at "Chip" or
"Processor".

### Windows

1. Right-click the zip file and choose **Extract All…**. Put the folder somewhere permanent,
   such as `Documents`.
2. Open the `Biverse` folder and double-click **Biverse.exe**. Keep the whole folder together,
   because the program needs the files next to it.
3. If Windows shows "Windows protected your PC", click **More info → Run anyway**. This
   happens because the program is free and not code-signed.
4. Optional: right-click `Biverse.exe` and choose **Send to → Desktop (create shortcut)**.

**Windows 7 needs two things first.** Without them Biverse will not start (you may see an
error about `api-ms-win-crt-runtime`):

- **Service Pack 1.** Check under Computer → Properties. If it does not say "Service Pack 1",
  install it from Windows Update.
- **Update KB2999226** (Universal C Runtime). Get it from Windows Update, or download
  "Update for Universal C Runtime in Windows" (KB2999226) from Microsoft's website on another
  computer and copy it over on a USB stick.

### macOS

1. Double-click the zip file. This makes **Biverse.app**. Drag it into **Applications**.
2. The first time, **right-click (or Control-click) Biverse.app and choose Open**, then click
   **Open** again. The app is not signed by Apple, so a normal double-click will refuse to
   open it the first time.
   - On macOS 15 and later, if there is no Open button: try to open the app once, then go to
     **System Settings → Privacy & Security**, scroll down and click **Open Anyway**.
   - If macOS says the app "is damaged", open **Terminal** and run:
     `xattr -dr com.apple.quarantine /Applications/Biverse.app`
3. When you first press **Listen**, macOS asks for permission to use the microphone. Click
   **OK**.

---

## 2. Connecting the projector

Biverse shows the verse on a **second screen**: the projector or TV. Your laptop screen keeps
the Biverse controls.

### Windows

1. Plug in the projector (HDMI or VGA).
2. Press **Windows key + P** and choose **Extend**. Do not choose *Duplicate*. With Duplicate,
   the congregation would see your controls.

### macOS

1. Plug in the projector.
2. Open **System Settings → Displays** (System Preferences → Displays on older Macs).
3. Make sure the projector is **not mirrored**. On older macOS, untick "Mirror Displays" in
   the **Arrangement** tab. On newer macOS, set "Use as" to **Extended display**.

### In Biverse

- **Output:** choose the projector, for example `Display 2 — 1920×1080`. Biverse picks the
  first screen that is not your main screen automatically.
- Press **Show output**. The projector turns black, which is normal: nothing appears until
  you send a verse live.
- Press **⟳** next to the Output list after plugging in or unplugging a screen.
- **Test output** (in the Output menu or in Settings) shows Psalm 23:1, so you can check the
  projector before the service.
- If you only have one screen, the output opens as a window. Press **F11** on it to switch
  between full screen and a window.

---

## 3. Choosing the sound source

The **Input** list shows every microphone and audio input on the computer. The bar next to
it is the **level meter**. It should jump when someone speaks. Press **⟳** after plugging in
a USB microphone or audio interface.

### The simplest setup: the laptop microphone or a USB microphone

Put the microphone near a loudspeaker that carries the preacher's voice, or near the pulpit.
Clear sound matters more than loud sound. Avoid putting it next to the drums or a fan.

### The best setup: a feed from the sound desk

Speech recognition works best with a clean feed straight from the mixer.

1. Take a spare output from the desk: an **aux send**, **matrix** or **record out** that
   carries the **pulpit microphone only** (no music).
2. Connect it to a **USB audio interface** (for example a Behringer UCA202/U-Phoria or a
   Focusrite) with a suitable cable, usually a 6.35 mm jack or RCA cable.
3. Plug the interface into the computer and choose it in **Input**.
4. Ask the sound engineer to set the send level so the meter sits mostly in the green.

> Do **not** plug a mixer's line output into a laptop's microphone socket. It is far too
> loud and will distort.

### Capturing the livestream or computer audio

If the sermon audio is already on the computer (a livestream, or a video being played):

- **Windows: "Stereo Mix".** Right-click the speaker icon, choose **Sounds → Recording**,
  right-click in the empty space, tick **Show Disabled Devices**, then right-click
  **Stereo Mix** and choose **Enable**. Then choose *Stereo Mix* in Biverse. Not every PC has
  it.
- **Windows: VB-Cable** (free, from vb-audio.com). Install it, set the livestream software or
  player to output to *CABLE Input*, and choose **CABLE Output** in Biverse.
- **macOS: BlackHole** (free, from existential.audio). Install *BlackHole 2ch*, send the
  livestream audio to BlackHole, and choose **BlackHole 2ch** in Biverse. To hear the audio
  at the same time, make a **Multi-Output Device** in *Audio MIDI Setup*.

---

## 4. Running a service

1. Start Biverse. Wait until the status no longer says "Loading speech model…". This takes a
   few seconds.
2. Check **Input**, **Output** and **Bible** (the translation).
3. Press **Listen** (or Ctrl+L / Cmd+L). The dot turns **red** and the status says
   *Listening*.
4. Words appear in **Transcript** as they are heard. Grey text is still being worked out.
5. When a reference is heard, it appears in **Detected** with the time and the words that
   triggered it, and it loads into **Preview**.
6. Check the preview, then press **GO LIVE** (Ctrl+Enter / Cmd+Enter or F5).
7. Use **Next ▶** / **◀ Prev** (or the → / ← keys) to move verse by verse. Ranges such as
   "John 3:16-18" show one verse at a time.
8. Press **BLANK** (Esc) to clear the text and keep the background. Press **BLACK**
   (Shift+Esc) for a fully black screen. Press the same button again to bring the verse back.

In **Detected**, click an entry to preview it again, or double-click it to send it live.

**References Biverse understands**

- "John three sixteen", "John chapter three verse sixteen", "John three colon sixteen"
- Ranges: "First Corinthians thirteen four through seven", "verses four to seven"
- Whole chapters: "Romans chapter eight". This shows verse 1, and you can step on with Next.
- "Psalm one nineteen" is understood as Psalm 119.
- "Job one twenty" or "Job 120" is understood as Job 1:20, and "John 316" as John 3:16, unless
  a quantity follows ("my job 365 days a year" is ignored).
- Relative verses: after John 3:16, "now look at verse eighteen" or "move to verse eight"
  means a verse in the chapter **currently on screen**, even after you or the preacher moved
  on with Next. The entry in Detected is marked *(relative)*.

**Voice commands** (Settings → Detection, on by default). The preacher can move the slide by
voice, in their own words. Some examples Biverse understands:

| The preacher says | What happens |
|---|---|
| "next verse", "the next one", "one more verse", "Next.", "move forward" | next verse |
| "go back", "can we go back?", "the verse before", "back to the previous one" | previous verse |
| "go back two verses", "skip ahead three verses", "a couple of verses back" | moves that many verses |
| "next chapter", "go back a chapter", "go back two chapters" | verse 1 of that chapter |
| "go back to chapter three", "turn to chapter four verse two" | that chapter (and verse) of **the same book** |
| "move to verse eight", "verse eight" | verse 8 of the chapter on screen |
| "the beginning of the chapter", "back to verse one" | verse 1 of this chapter |
| "back to where we started" | the first verse of the passage you sent live |
| "stop there", "let's stop there" / "continue", "let's continue", "read on" | pause / resume following the reading |

**Following the reading.** Once a verse or passage is live (for example Genesis 10:3–10), Biverse
listens to the preacher reading it and moves to the next verse as they reach the end of each
one, typically within about a third of a second. It works even if the preacher reads from a
different translation from the one on screen, and it handles skipped verses. At the end of a
range it stays put unless the preacher carries on reading the next verse aloud. Following
moves the live slide in both Manual and Auto mode, because you already approved the passage.

- The indicator under the buttons shows **● Following 60%** (how far through the verse the
  preacher is) or **‖ Paused**.
- "**Stop there**" pauses following (the verse stays up). "**Continue**" or "**let's continue**"
  resumes it. You can also press **Pause following** or **F6**.
- Turn it off in Settings → Detection → "Follow the reading".
- Following uses the live words from Kroko. With Parakeet alone it can only move after each
  pause, so the combined "Kroko + Parakeet" setting is best.

In **Auto** mode voice commands change the projector straight away. In **Manual** mode the new
verse goes to Preview for you to send live. Ordinary sentences do nothing: "next week we have a retreat",
"go back to Egypt", "let's continue to worship" and "the chapter of your life" are ignored.
The Status line shows what Biverse heard and did.

---|---|
| "next verse", "the following verse", or just "Next." | next verse |
| "go back", "previous verse", "go back a verse" | previous verse |
| "next chapter", "move to the next chapter" | verse 1 of the next chapter |
| "previous chapter", "go back a chapter" | verse 1 of the previous chapter |
| "move to verse eight", "verse eight" | verse 8 of the chapter on screen |

In **Auto** mode the projector changes straight away. In **Manual** mode the new verse goes to
Preview for you to send live. "Next" and "go back" on their own only count when said as a short
command, so "next week we have a retreat" or "go back to Egypt" do nothing. The Status line
shows each command Biverse heard.
- Names that are also everyday words (Mark, John, Job, Acts, James, Jude, Ruth, Joel, Amos,
  Titus, Numbers, Judges) only count with a chapter **and** a verse, or with the word
  "chapter". So "I lost my job three years ago" is ignored, but "Job nineteen twenty five" is
  detected.

---

## 5. Manual and Auto mode

- **Manual** (the default): detected verses go to **Preview**. Nothing reaches the
  congregation until you press **GO LIVE**. Use this mode when someone is at the computer.
- **Auto**: detected verses go **straight to the projector**. Use it when nobody can operate
  the computer, for example a small midweek meeting.

Switch modes at any time with the Mode buttons or **Ctrl+M / Cmd+M**.

**When to trust Auto mode:** when the sound feed is clean (from the desk), the preacher reads
references clearly, and a wrong verse on screen for a few seconds would not matter. In Auto
mode, Biverse only sends a reference live when both a chapter **and** a verse were heard
("Romans eight" alone goes to Preview). You can change this in Settings → Detection. Run a
rehearsal before relying on it.

---

## 6. Searching

Type in the **Search** box and press Enter (Ctrl+F / Cmd+F jumps to it).

- **A reference** jumps straight to Preview: `jn 3:16`, `1 cor 13:4-7`, `ps 23`,
  `Romans 8 28`, `rev 22`.
- **Words** search the current translation: `for god so loved`, `shepherd`. Up to 50 results
  are listed. Click one to preview it, and double-click it (or press Enter) to send it live.

---

## 7. Keyboard shortcuts

On a Mac, use Cmd instead of Ctrl.

| Key | Action |
|---|---|
| Ctrl+Enter or F5 | Go Live |
| Esc | Blank (press again to restore) |
| Shift+Esc | Black (press again to restore) |
| ← / → | Previous / next verse on the live slide (not while typing in a box) |
| Ctrl+F | Jump to Search |
| Ctrl+L | Listen on/off |
| Ctrl+M | Manual / Auto |
| F6 | Pause / resume following the reading |
| Ctrl+E | Emphasis: bold / underline / highlight words of the verse |
| Ctrl+Shift+S | Sermon summary |
| F11 (on the output window) | Full screen / window |

---

## 8. Settings

Open **⚙ Settings**.

- **Appearance:** background and text colours, font, bold, text shadow, reference line at the
  bottom or top, and a background image (PNG or GIF, ideally the projector's size). You can
  also choose to show a short verse range on one slide when it fits.
- **Speech:** which speech model to use (see below).
- **Detection:** strict book names, relative verses, how long to ignore repeats (60 seconds
  by default), and the Auto-mode safety option.
- **Extra reference listener** (Detection tab; only used by the classic model): a second
  listener that only knows book names and numbers, which helps the classic model catch
  references it mishears. It roughly doubles the CPU used for listening.
- **Test output** shows a sample verse on the projector.

Biverse remembers everything (devices, display, translation, mode and appearance) for next
time.

---

## 9. Speech models: getting the best recognition

Biverse can use three speech models. **Settings → Speech** shows which one is in use.

| Model | Best for | Needs |
|---|---|---|
| **Kroko** (built in) | Every computer. Words appear live as the preacher speaks. | Any computer |
| **Kroko + Parakeet** (with the pack) | The most detections: Kroko reacts live, Parakeet re-checks each phrase at the pause. Chosen automatically when the computer can run it. | About 2 GB of free RAM |
| **Parakeet** (free model pack) | The most accurate, by far the best with African and other accents. The verse appears a moment after the preacher pauses. | A 64-bit computer with about 6 GB of RAM or more |
| **Classic** (Vosk, Windows 7/8 downloads only) | Old Windows 7 computers where Kroko cannot run | Any computer |

In tests with Nigerian English speakers, Parakeet got about 1 word in 14 wrong; Kroko about
1 in 5; the classic model about 1 in 3.

**Installing the Parakeet pack (recommended if your computer can run it):**

1. On any computer with internet, download `Biverse-model-pack-parakeet-….zip` (about 500 MB)
   from the same Releases page as Biverse. Copy it to the church computer if needed.
2. In Biverse, open **Settings → Speech → Install model pack…** and choose the zip.
3. Wait for "installed" (about a minute). With the model set to **Automatic**, Biverse now uses
   Parakeet whenever the computer can run it, and falls back to Kroko otherwise.

The pack is kept in your settings folder, so it survives Biverse updates. To force a particular
model, choose it in Settings → Speech.

**Other models.** Settings → Speech → "A model folder I choose" accepts a Vosk model folder
(from alphacephei.com/vosk/models) or a folder prepared by Biverse's `tools/fetch_model.py`.

---

## 10. Adding a licensed translation

Biverse includes only public-domain translations: KJV, WEB, ASV, YLT and BBE. Modern
translations such as the NIV, NKJV, ESV and NLT are copyrighted. If your church holds a
licence to display one and has the text as a file, you can add it yourself. It stays on your
computer only.

1. Prepare a CSV file (UTF-8) with this header and one line per verse:

   ```
   Book,Chapter,Verse,Text
   1,1,1,"In the beginning God created the heavens and the earth."
   ```

   *Book* is 1–66 (Genesis = 1, Revelation = 66). Book names in Bible order also work,
   for example `Genesis` or `I Samuel`.
2. Import it:
   - Windows: `Biverse.exe --import-translation NIV "New International Version" niv.csv`
     (run it from a Command Prompt in the Biverse folder)
   - macOS: `/Applications/Biverse.app/Contents/MacOS/Biverse --import-translation NIV "New International Version" niv.csv`
   - From source: `python tools/import_translation.py NIV "New International Version" niv.csv`
3. Restart Biverse. The new code appears in the **Bible** list.

To remove it, run `python tools/import_translation.py NIV x x --remove`.

---

## Bible versions, emphasis and the sermon summary

**Changing the Bible version by voice.** The preacher can say "let's read this in the ASV",
"switch to the King James", "World English please" or "can we see that in Young's Literal". The
projector switches at once and **stays on that version until it is changed again** (by voice or
the Bible list). If the version isn't installed (for example "the NIV"), the Status line says so
and lists the installed ones. Quoting a version ("the King James version says…") does not switch.

**Emphasis: bold, underline or highlight words.** Press **✎ Mark** (or Ctrl+E / Cmd+E) while
a verse is live or in Preview. Select words in the window that opens and press **Bold**,
**Underline** or **Highlight**; press again to remove. The projector updates immediately. Marks are
remembered for that verse in that version, so they come back next time. The highlight colour is in
Settings → Appearance.

**Sermon summary.** While listening, Biverse keeps a record of what was said and which scriptures
came up. Open **Service → Sermon summary** (Ctrl+Shift+S) during or after the service for:

- every scripture referenced, in order, with the time;
- the main themes and key points (sentences taken from the sermon itself);
- a timeline, and the full transcript when you **Save as…** or **Copy**.

Each service is saved automatically (Service → Open a previous sermon…). A new record starts when
you press Listen after a 30-minute break, or with Service → Start a new sermon.

**AI-written summary (optional).** Download `Biverse-ai-summary-pack-….zip` (about 1.2 GB) from the
Releases page and install it with Settings → Speech → **Install model pack…**. The summary window
then offers **Write AI summary**: a short prose summary written on this computer (nothing is sent
anywhere) in under a minute. It needs about 8 GB of RAM and one of these:

- Windows 10 or 11, 64-bit (the `windows-x64` or `windows-legacy-x64` download)
- A Mac with Apple Silicon or Intel (macOS 13.3 or later recommended)
- Linux on a 64-bit Intel/AMD computer (running from source)

It does **not** work on Windows 7 or 8, on the 32-bit (`windows-legacy-x86`) download, or on ARM
Windows/Linux. On those computers the summary window explains why, and Biverse won't install the
pack, so you don't waste the 1.2 GB download. The built-in summary works on every computer.

**The look of the window** follows your computer's light or dark setting. Choose Dark or Light
permanently in Settings → Appearance → "Operator window look".

---

## 11. Troubleshooting

**The level meter does not move.**
- Check that the right **Input** is selected, press **⟳**, and try speaking into it.
- On a Mac, go to **System Settings → Privacy & Security → Microphone** and make sure
  **Biverse** is switched on. Then restart Biverse.
- On Windows, go to **Settings → Privacy → Microphone** and allow desktop apps to use the
  microphone.
- A sound-desk feed may simply be turned down. Ask the sound engineer.
- If the status says "… is not responding", the device or macOS permission is blocking it.
  Check the permission above, or pick another input.

**Speech is heard, but references are missed.**
- Look at the Transcript. If "genesis two eighteen" appears as "genesis to a team", the
  speech model is mishearing; the words are not reaching Biverse cleanly.
- Use a cleaner feed (from the desk rather than a microphone in the room). A laptop microphone
  picking up a loudspeaker is the hardest case.
- Install the Parakeet model pack (section 9). It is the single biggest improvement.
- Check that **strict book names** are not the cause: "John three" alone is not enough, but
  "John chapter three" is.

**The verse appears on the wrong screen, or on my laptop.**
- Windows: press **Win+P → Extend**. macOS: turn off mirroring (section 2).
- Press **⟳** next to Output and choose the projector again.
- With Windows display scaling (125 %, 150 %), Biverse uses real pixels, so this should line
  up. If it does not, press F11 on the output window for a movable window.
- macOS: if the output hides behind the menu bar or is on another desktop (Space), choose the
  display again in the Output list.

**I unplugged the microphone or projector by mistake.** Biverse keeps running. Plug it back
in and press the **⟳** button next to Input or Output. While listening, Biverse also retries
the microphone by itself every few seconds.

**"No speech model could be used" banner.** The `models` folder is missing, or (on an old
computer) the model could not start. Re-extract the download,
or choose a model folder in Settings → Speech. Search and projection still work without one.

**On an Intel Mac, both windows are black or the app closes straight away.** Versions 1.0–1.2
had this problem on macOS 11 and 12; it is fixed from 1.2.1. Download the latest
`Biverse-…-macos-intel.zip`.

**macOS asks for microphone permission again after updating to 1.3.** That is expected once: the
app's internal identifier changed with the new name.

**macOS says the app is damaged or from an unidentified developer.** See *Installing → macOS*
(right-click → Open, or the `xattr` command).

**My antivirus deleted or blocked Biverse.exe.** Programs made with PyInstaller are sometimes
falsely flagged. Restore the file from quarantine and add the Biverse folder as an exception.
If you are unsure, check the zip's SHA-256 against `SHA256SUMS.txt` on the Releases page.

**Something went wrong.** Use **Help → Open log folder** and send `biverse.log` to whoever
helps you with computers. It contains no audio.
