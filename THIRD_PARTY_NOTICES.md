# Third-party notices

Biverse itself is MIT-licensed (see `LICENSE`). It bundles or uses the following components.

| Component | Use | Licence |
|---|---|---|
| [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 2.0.1 | Speech recognition engine (Kroko, Parakeet) | Apache License 2.0 |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) (bundled by sherpa-onnx) | Neural network runtime | MIT |
| [Kroko ASR](https://huggingface.co/Banafo/Kroko-ASR) English community streaming model (2025-08-06), by Banafo, ONNX export by sherpa-onnx | Built-in live speech model | CC-BY-SA, as stated on the model card (the repository's LICENSE file is empty and gives no version). Attribution: "Kroko ASR community model by Banafo". The model files keep this licence; Biverse's own code is MIT |
| [NVIDIA Parakeet TDT 0.6B v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2), int8 ONNX export by sherpa-onnx | Optional high-accuracy model pack | CC-BY-4.0. Attribution: "parakeet-tdt-0.6b-v2 by NVIDIA". NVIDIA does not endorse Biverse |
| [Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) (GGUF q4_k_m) | Optional AI summary pack | Apache License 2.0 (Alibaba Cloud / Qwen team) |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) b12366 `llama-completion` | Runs the AI summary model in the optional pack | MIT |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Speech/pause detection in the Parakeet pack | MIT |
| [Vosk API](https://github.com/alphacep/vosk-api) 0.3.44 (`libvosk`, Python bindings) | Offline speech recognition | Apache License 2.0 |
| [vosk-model-small-en-us-0.15](https://alphacephei.com/vosk/models) | English speech model, © 2020 Alpha Cephei Inc | Apache License 2.0 |
| Kaldi (statically linked into libvosk) | Speech recognition toolkit | Apache License 2.0 |
| [python-sounddevice](https://github.com/spatialaudio/python-sounddevice) 0.5.6 | Audio input | MIT |
| [PortAudio](http://www.portaudio.com/), bundled by sounddevice on Windows and macOS | Audio I/O library | MIT-style PortAudio licence |
| cffi | Used by vosk and sounddevice | MIT |
| requests, srt, tqdm | Imported by vosk; not used by Biverse | Apache-2.0 / MIT / MPL-2.0 AND MIT |
| [Pillow](https://python-pillow.org/) 11.3.0 (10.4.0 in the Windows 7 builds), with its bundled libjpeg-turbo, libpng, libwebp, zlib and FreeType | Idle screen and background pictures (JPEG, PNG, WebP, GIF) | MIT-CMU (HPND); the bundled libraries are under BSD-style, libpng, zlib and FreeType licences |
| certifi | CA certificates for HTTPS model downloads (Settings → Models) | MPL-2.0 |
| Python and Tcl/Tk (bundled by PyInstaller) | Runtime and GUI | PSF licence / Tcl/Tk BSD-style licence |
| PyInstaller bootloader | Packaging | GPL-2.0 with a bootloader exception that allows distributing bundled apps under any licence |

## Bible texts

All bundled translations are in the **public domain**.

| Code | Translation | Source | Status |
|---|---|---|---|
| KJV | King James Version (1769 Oxford text) | [scrollmapper/bible_databases](https://github.com/scrollmapper/bible_databases) (MIT-licensed repository), commit `59b18c5a` | Public domain, except in the UK, where Crown rights (letters patent) apply. UK churches should check their own licensing |
| WEB | World English Bible | [eBible.org](https://ebible.org/engwebp/) | Public domain. "World English Bible" is a trademark of eBible.org, so the name is used only for the unmodified text |
| ASV | American Standard Version (1901) | scrollmapper | Public domain |
| YLT | Young's Literal Translation (1898) | scrollmapper | Public domain |
| BBE | Bible in Basic English (1965) | scrollmapper | Treated as public domain by its distributors. Churches should confirm its status in their country |

The scrollmapper repository is under the MIT License, "Copyright (c) 2024 Scrollmapper". Its
full text is the standard MIT licence (the same text as Biverse's `LICENSE`, with that
copyright line).

Biverse never bundles copyrighted translations such as NIV, NKJV, ESV or NLT. A church that
holds a licence can import one locally (see USER_GUIDE.md, "Adding a licensed translation").

## Full licence texts

- Apache License 2.0: https://www.apache.org/licenses/LICENSE-2.0
- MIT: https://opensource.org/licenses/MIT
- PortAudio: http://www.portaudio.com/license.html
- Python: https://docs.python.org/3/license.html
- Tcl/Tk: https://www.tcl.tk/software/tcltk/license.html
