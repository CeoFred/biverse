# BiVerse user guide

BiVerse listens to the preacher. When it hears a Bible reference ("John chapter three verse
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
- [9. Installing a bigger speech model](#9-installing-a-bigger-speech-model)
- [10. Adding a licensed translation](#10-adding-a-licensed-translation)
- [11. Troubleshooting](#11-troubleshooting)

---

## 1. Installing

Download the right file from the project's **Releases** page.

| Your computer | Download |
|---|---|
| Windows 10 or 11 (almost all PCs from the last 10 years) | `BiVerse-…-windows-x64.zip` |
| Windows 7 or 8, 64-bit | `BiVerse-…-windows-legacy-x64.zip` |
| Windows 7 or 8, 32-bit (older netbooks) | `BiVerse-…-windows-legacy-x86.zip` |
| Mac with Apple Silicon (M1, M2, M3, M4…) | `BiVerse-…-macos-arm.zip` |
| Mac with an Intel processor, macOS 10.13 or newer | `BiVerse-…-macos-intel.zip` (also runs on Apple Silicon) |

To check your Windows type: **Start → right-click Computer / This PC → Properties**, then look
at "System type". To check your Mac: **Apple menu → About This Mac**, then look at "Chip" or
"Processor".

### Windows

1. Right-click the zip file and choose **Extract All…**. Put the folder somewhere permanent,
   such as `Documents`.
2. Open the `BiVerse` folder and double-click **BiVerse.exe**. Keep the whole folder together,
   because the program needs the files next to it.
3. If Windows shows "Windows protected your PC", click **More info → Run anyway**. This
   happens because the program is free and not code-signed.
4. Optional: right-click `BiVerse.exe` and choose **Send to → Desktop (create shortcut)**.

**Windows 7 needs two things first.** Without them BiVerse will not start (you may see an
error about `api-ms-win-crt-runtime`):

- **Service Pack 1.** Check under Computer → Properties. If it does not say "Service Pack 1",
  install it from Windows Update.
- **Update KB2999226** (Universal C Runtime). Get it from Windows Update, or download
  "Update for Universal C Runtime in Windows" (KB2999226) from Microsoft's website on another
  computer and copy it over on a USB stick.

### macOS

1. Double-click the zip file. This makes **BiVerse.app**. Drag it into **Applications**.
2. The first time, **right-click (or Control-click) BiVerse.app and choose Open**, then click
   **Open** again. The app is not signed by Apple, so a normal double-click will refuse to
   open it the first time.
   - On macOS 15 and later, if there is no Open button: try to open the app once, then go to
     **System Settings → Privacy & Security**, scroll down and click **Open Anyway**.
   - If macOS says the app "is damaged", open **Terminal** and run:
     `xattr -dr com.apple.quarantine /Applications/BiVerse.app`
3. When you first press **Listen**, macOS asks for permission to use the microphone. Click
   **OK**.

---

## 2. Connecting the projector

BiVerse shows the verse on a **second screen**: the projector or TV. Your laptop screen keeps
the BiVerse controls.

### Windows

1. Plug in the projector (HDMI or VGA).
2. Press **Windows key + P** and choose **Extend**. Do not choose *Duplicate*. With Duplicate,
   the congregation would see your controls.

### macOS

1. Plug in the projector.
2. Open **System Settings → Displays** (System Preferences → Displays on older Macs).
3. Make sure the projector is **not mirrored**. On older macOS, untick "Mirror Displays" in
   the **Arrangement** tab. On newer macOS, set "Use as" to **Extended display**.

### In BiVerse

- **Output:** choose the projector, for example `Display 2 — 1920×1080`. BiVerse picks the
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
  **Stereo Mix** and choose **Enable**. Then choose *Stereo Mix* in BiVerse. Not every PC has
  it.
- **Windows: VB-Cable** (free, from vb-audio.com). Install it, set the livestream software or
  player to output to *CABLE Input*, and choose **CABLE Output** in BiVerse.
- **macOS: BlackHole** (free, from existential.audio). Install *BlackHole 2ch*, send the
  livestream audio to BlackHole, and choose **BlackHole 2ch** in BiVerse. To hear the audio
  at the same time, make a **Multi-Output Device** in *Audio MIDI Setup*.

---

## 4. Running a service

1. Start BiVerse. Wait until the status no longer says "Loading speech model…". This takes a
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

**References BiVerse understands**

- "John three sixteen", "John chapter three verse sixteen", "John three colon sixteen"
- Ranges: "First Corinthians thirteen four through seven", "verses four to seven"
- Whole chapters: "Romans chapter eight". This shows verse 1, and you can step on with Next.
- "Psalm one nineteen" is understood as Psalm 119.
- Relative verses: after John 3:16, "now look at verse eighteen" means John 3:18. The entry
  in Detected is marked *(relative)*.
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
mode, BiVerse only sends a reference live when both a chapter **and** a verse were heard
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
- **Extra reference listener** (Detection tab, on by default): a second listener that only knows
  book names and numbers. It catches references the main one mishears, such as "genesis two
  eighteen" heard as "genesis to a team". It only adds references with both a chapter and a
  verse. It roughly doubles the CPU used for listening, so turn it off on a very slow computer.
- **Test output** shows a sample verse on the projector.

BiVerse remembers everything (devices, display, translation, mode and appearance) for next
time.

---

## 9. Installing a bigger speech model

BiVerse comes with a small English model (about 40 MB) that runs on old laptops. **If your
computer has 4 GB of RAM or more, install a bigger model: it is the single biggest
improvement to detection.** It recognises speech much more accurately, especially with
accents or a room microphone, but needs more memory and a faster computer.

The small model does not know some book names at all, so it cannot detect these books when
they are spoken: **Thessalonians, Haggai, Habakkuk, Deuteronomy, Zephaniah** and often
**Philemon**. Philippians, Zechariah, Malachi, Galatians, Colossians and Ephesians usually work
through common mis-hearings. Search still finds every book.

1. On any computer with internet, go to **alphacephei.com/vosk/models** and download an
   English model, for example **vosk-model-en-us-0.22-lgraph** (about 130 MB, needs about
   1 GB of RAM).
2. Unzip it. You get a folder containing `am`, `conf`, `graph` and so on.
3. Copy that folder to the church computer.
4. In BiVerse, go to **Settings → Speech → Choose speech model folder…** and select it.

Alternatively, put the model folder into a folder called `models` next to BiVerse.exe (or next
to BiVerse.app).

---

## 10. Adding a licensed translation

BiVerse includes only public-domain translations: KJV, WEB, ASV, YLT and BBE. Modern
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
   - Windows: `BiVerse.exe --import-translation NIV "New International Version" niv.csv`
     (run it from a Command Prompt in the BiVerse folder)
   - macOS: `/Applications/BiVerse.app/Contents/MacOS/BiVerse --import-translation NIV "New International Version" niv.csv`
   - From source: `python tools/import_translation.py NIV "New International Version" niv.csv`
3. Restart BiVerse. The new code appears in the **Bible** list.

To remove it, run `python tools/import_translation.py NIV x x --remove`.

---

## 11. Troubleshooting

**The level meter does not move.**
- Check that the right **Input** is selected, press **⟳**, and try speaking into it.
- On a Mac, go to **System Settings → Privacy & Security → Microphone** and make sure
  **BiVerse** is switched on. Then restart BiVerse.
- On Windows, go to **Settings → Privacy → Microphone** and allow desktop apps to use the
  microphone.
- A sound-desk feed may simply be turned down. Ask the sound engineer.
- If the status says "… is not responding", the device or macOS permission is blocking it.
  Check the permission above, or pick another input.

**Speech is heard, but references are missed.**
- Look at the Transcript. If "genesis two eighteen" appears as "genesis to a team", the
  speech model is mishearing; the words are not reaching BiVerse cleanly.
- Use a cleaner feed (from the desk rather than a microphone in the room). A laptop microphone
  picking up a loudspeaker is the hardest case.
- Install a bigger speech model (section 9).
- Make sure Settings → Detection → **Extra reference listener** is on.
- Check that **strict book names** are not the cause: "John three" alone is not enough, but
  "John chapter three" is.

**The verse appears on the wrong screen, or on my laptop.**
- Windows: press **Win+P → Extend**. macOS: turn off mirroring (section 2).
- Press **⟳** next to Output and choose the projector again.
- With Windows display scaling (125 %, 150 %), BiVerse uses real pixels, so this should line
  up. If it does not, press F11 on the output window for a movable window.
- macOS: if the output hides behind the menu bar or is on another desktop (Space), choose the
  display again in the Output list.

**I unplugged the microphone or projector by mistake.** BiVerse keeps running. Plug it back
in and press the **⟳** button next to Input or Output. While listening, BiVerse also retries
the microphone by itself every few seconds.

**"No speech model found" banner.** The `models` folder is missing. Re-extract the download,
or choose a model folder in Settings → Speech. Search and projection still work without one.

**macOS says the app is damaged or from an unidentified developer.** See *Installing → macOS*
(right-click → Open, or the `xattr` command).

**My antivirus deleted or blocked BiVerse.exe.** Programs made with PyInstaller are sometimes
falsely flagged. Restore the file from quarantine and add the BiVerse folder as an exception.
If you are unsure, check the zip's SHA-256 against `SHA256SUMS.txt` on the Releases page.

**Something went wrong.** Use **Help → Open log folder** and send `biverse.log` to whoever
helps you with computers. It contains no audio.
