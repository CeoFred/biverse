# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Biverse. Works with PyInstaller 5.13.2 (Python 3.8
# legacy builds) and 6.x. One-dir build.
#
#   pyinstaller --noconfirm --clean packaging/biverse.spec
#
# Environment:
#   BIVERSE_MACOS_MIN       LSMinimumSystemVersion (default 10.13)
#   BIVERSE_CODESIGN_ID     optional Developer ID identity for macOS signing
#   BIVERSE_ENTITLEMENTS    optional entitlements plist for that signing

import glob
import json
import os
import re
import sys

import PyInstaller
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))  # noqa: F821 (SPECPATH is provided by PyInstaller)
sys.path.insert(0, ROOT)

with open(os.path.join(ROOT, "biverse", "__init__.py"), encoding="utf-8") as f:
    VERSION = re.search(r'__version__ = "([^"]+)"', f.read()).group(1)
PI_MAJOR = int(PyInstaller.__version__.split(".")[0])
APP = "Biverse"
# Speech models to bundle, by manifest id (tools/fetch_model.py installs them):
# every build bundles Kroko; Windows legacy builds add the classic Vosk model as
# a fallback for Windows 7, where ONNX Runtime may not load.
BUNDLE_MODELS = [m.strip() for m in os.environ.get("BIVERSE_BUNDLE_MODELS", "kroko").split(",") if m.strip()]

db = os.path.join(ROOT, "data", "bible.db")
if not os.path.exists(db):
    raise SystemExit("missing %s - run tools/build_bible_db.py first" % db)

datas = [
    (db, "data"),
    (os.path.join(ROOT, "assets"), "assets"),
]
bundled = {}
models_root = os.path.join(ROOT, "models")
for name in sorted(os.listdir(models_root)) if os.path.isdir(models_root) else []:
    manifest = os.path.join(models_root, name, "biverse-model.json")
    if not os.path.isfile(manifest):
        continue
    with open(manifest, encoding="utf-8") as f:
        mid = json.load(f).get("id")
    if mid in BUNDLE_MODELS and mid not in bundled:
        bundled[mid] = name
        for dirpath, _dirs, files in os.walk(os.path.join(models_root, name)):
            for fname in files:
                rel = os.path.relpath(dirpath, models_root)
                datas.append((os.path.join(dirpath, fname), os.path.join("models", rel)))
missing = [m for m in BUNDLE_MODELS if m not in bundled]
if missing:
    raise SystemExit("models not installed: %s - run tools/fetch_model.py --name %s" % (missing, ",".join(missing)))
print("bundling speech models:", bundled)

# -- native libraries ------------------------------------------------------------------
# Vosk loads libvosk (.dll / .so / .dyld - note the unusual macOS extension) from
# its package folder, so put it (and its MinGW runtime DLLs on Windows) there.
import vosk  # noqa: E402

vosk_dir = os.path.dirname(vosk.__file__)
binaries = [(src, "vosk") for src, _dest in collect_dynamic_libs("vosk")]
for pattern in ("libvosk*", "*.dll", "*.so", "*.dylib", "*.dyld"):
    for p in glob.glob(os.path.join(vosk_dir, pattern)):
        if (p, "vosk") not in binaries:
            binaries.append((p, "vosk"))
if not any(os.path.basename(p).startswith("libvosk") for p, _ in binaries):
    raise SystemExit("libvosk not found in %s" % vosk_dir)

def _keep(entry):
    """Only this platform's / architecture's PortAudio build (the wheels ship all of them)."""
    base = os.path.basename(entry[0]).lower()
    if "portaudio" not in base:
        return True
    if "asio" in base:
        return False
    if sys.platform == "darwin":
        return base.endswith(".dylib")
    if sys.platform == "win32":
        want = "64bit" if sys.maxsize > 2 ** 32 else "32bit"
        return base.endswith(".dll") and want in base
    return True


# sounddevice ships PortAudio in _sounddevice_data; packaging/hooks/hook-sounddevice.py
# collects only this platform's library (overrides the contrib hook).

# sherpa-onnx (Kroko / Parakeet engines): its extension and ONNX Runtime live in sherpa_onnx/lib
import sherpa_onnx  # noqa: E402

sherpa_lib = os.path.join(os.path.dirname(sherpa_onnx.__file__), "lib")
for p in sorted(glob.glob(os.path.join(sherpa_lib, "*"))):
    if p.endswith((".so", ".pyd", ".dll", ".dylib")) or ".so." in os.path.basename(p):
        binaries.append((p, os.path.join("sherpa_onnx", "lib")))
if not any("onnxruntime" in os.path.basename(p) for p, _ in binaries):
    raise SystemExit("ONNX Runtime library not found in %s" % sherpa_lib)

hiddenimports = ["_cffi_backend", "vosk.vosk_cffi", "sherpa_onnx", "sherpa_onnx.lib._sherpa_onnx"]
excludes = ["numpy", "PIL", "matplotlib", "PyQt5", "PySide2", "PySide6", "IPython", "pytest",
            "vosk.transcriber", "websockets"]

# -- Windows version resource ----------------------------------------------------------
version_file = None
if sys.platform == "win32":
    parts = (VERSION.split(".") + ["0", "0", "0"])[:4]
    nums = ", ".join(str(int(re.sub(r"\D.*", "", x) or 0)) for x in parts)
    version_file = os.path.join(ROOT, "build", "version_info.txt")
    os.makedirs(os.path.dirname(version_file), exist_ok=True)
    with open(version_file, "w", encoding="utf-8") as f:
        f.write("""VSVersionInfo(
  ffi=FixedFileInfo(filevers=(%(n)s), prodvers=(%(n)s), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable(u'040904B0', [
      StringStruct(u'CompanyName', u'Biverse'),
      StringStruct(u'FileDescription', u'Biverse - live Bible verse projection'),
      StringStruct(u'FileVersion', u'%(v)s'),
      StringStruct(u'InternalName', u'Biverse'),
      StringStruct(u'LegalCopyright', u'MIT licence'),
      StringStruct(u'OriginalFilename', u'Biverse.exe'),
      StringStruct(u'ProductName', u'Biverse'),
      StringStruct(u'ProductVersion', u'%(v)s')])]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])]
)
""" % {"n": nums, "v": VERSION})

a = Analysis(  # noqa: F821
    [os.path.join(ROOT, "packaging", "launcher.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[os.path.join(ROOT, "packaging", "hooks")],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)


# TOC (PyInstaller 5) and list (6) both accept an iterable
a.binaries = type(a.binaries)(e for e in a.binaries if _keep(e))
a.datas = type(a.datas)(e for e in a.datas if _keep(e))

pyz = PYZ(a.pure)  # noqa: F821

exe_kwargs = dict(
    exclude_binaries=True,
    name=APP,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX triggers antivirus false positives
    console=False,
    icon=os.path.join(ROOT, "packaging", "icons", "biverse.ico" if sys.platform == "win32" else "biverse.icns"),
)
if version_file:
    exe_kwargs["version"] = version_file
if sys.platform == "darwin":
    exe_kwargs["argv_emulation"] = False
    if os.environ.get("BIVERSE_CODESIGN_ID"):
        exe_kwargs["codesign_identity"] = os.environ["BIVERSE_CODESIGN_ID"]
        if os.environ.get("BIVERSE_ENTITLEMENTS"):
            exe_kwargs["entitlements_file"] = os.environ["BIVERSE_ENTITLEMENTS"]

exe = EXE(pyz, a.scripts, [], **exe_kwargs)  # noqa: F821

coll_kwargs = dict(strip=False, upx=False, name=APP)
coll = COLLECT(exe, a.binaries, a.datas, **coll_kwargs)  # noqa: F821

if sys.platform == "darwin":
    app = BUNDLE(  # noqa: F821
        coll,
        name=APP + ".app",
        icon=os.path.join(ROOT, "packaging", "icons", "biverse.icns"),
        bundle_identifier="org.biverse.app",
        version=VERSION,
        info_plist={
            "CFBundleName": APP,
            "CFBundleDisplayName": APP,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "CFBundleIdentifier": "org.biverse.app",
            "LSMinimumSystemVersion": os.environ.get("BIVERSE_MACOS_MIN", "10.13"),
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "Biverse listens to the preacher to recognise Bible references. "
                                            "Audio never leaves this computer.",
            "NSRequiresAquaSystemAppearance": False,
            "LSApplicationCategoryType": "public.app-category.productivity",
        },
    )
