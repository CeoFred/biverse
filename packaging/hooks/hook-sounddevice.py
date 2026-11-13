"""sounddevice hook that collects only this platform's PortAudio library.

The sounddevice wheels ship every platform's PortAudio (Windows 32/64-bit/ARM,
with and without ASIO, plus macOS). Older pyinstaller-hooks-contrib releases
(2023.x, used with PyInstaller 5.13.2) collect all of them as binaries, and
PyInstaller 5 then fails on macOS while analysing the Windows DLLs.
"""

import ctypes.util
import os
import pathlib
import sys

from PyInstaller.utils.hooks import get_module_file_attribute

binaries = []
datas = []

module_dir = pathlib.Path(get_module_file_attribute("sounddevice")).parent
data_dir = module_dir / "_sounddevice_data" / "portaudio-binaries"
if data_dir.is_dir():
    dest = str(data_dir.relative_to(module_dir))
    if sys.platform == "darwin":
        wanted = ["libportaudio.dylib"]
    elif sys.platform == "win32":
        wanted = ["libportaudio64bit.dll" if sys.maxsize > 2 ** 32 else "libportaudio32bit.dll"]
    else:
        wanted = []
    for name in wanted:
        path = data_dir / name
        if path.is_file():
            binaries.append((str(path), dest))
    readme = data_dir / "README.md"
    if readme.is_file():
        datas.append((str(readme), dest))
else:  # Linux: the system libportaudio2
    name = ctypes.util.find_library("portaudio")
    if name:
        for d in ("/usr/lib/x86_64-linux-gnu", "/usr/lib/aarch64-linux-gnu", "/usr/lib", "/usr/local/lib"):
            if os.path.exists(os.path.join(d, name)):
                binaries.append((os.path.join(d, name), "."))
                break
