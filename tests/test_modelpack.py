from __future__ import annotations

import json
import os
import zipfile

import pytest

from biverse import modelpack, recognizer

FILES = ["encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt", "silero_vad.onnx"]
MANIFEST = {"engine": "sherpa-offline", "id": "parakeet", "label": "Parakeet (high accuracy)",
            "encoder": "encoder.int8.onnx", "decoder": "decoder.int8.onnx", "joiner": "joiner.int8.onnx",
            "tokens": "tokens.txt", "vad": "silero_vad.onnx", "min_ram_gb": 6}


def _pack(path, folder="sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8", manifest=MANIFEST, extra=None):
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("README.txt", "pack")
        for f in FILES:
            zf.writestr("%s/%s" % (folder, f), "x")
        if manifest is not None:
            zf.writestr("%s/biverse-model.json" % folder, json.dumps(manifest))
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return str(path)


def test_install_valid_pack(tmp_path):
    info = modelpack.install(_pack(tmp_path / "p.zip"), str(tmp_path / "models"))
    assert info.id == "parakeet" and info.engine == "sherpa-offline"
    assert os.path.isfile(os.path.join(info.path, "silero_vad.onnx"))
    assert [p for p in os.listdir(str(tmp_path / "models")) if p.startswith(".pack-")] == []
    # reinstalling replaces it
    assert modelpack.install(_pack(tmp_path / "p2.zip"), str(tmp_path / "models")).id == "parakeet"


def test_installed_pack_is_discovered(tmp_path, monkeypatch):
    monkeypatch.setenv("BIVERSE_CONFIG_DIR", str(tmp_path / "cfg"))
    from biverse import paths
    modelpack.install(_pack(tmp_path / "p.zip"), paths.user_models_dir())
    assert "parakeet" in [m.id for m in recognizer.discover_models()]


@pytest.mark.parametrize("bad", [
    {"extra": {"../evil.txt": "x"}},
    {"manifest": None},
    {"manifest": dict(MANIFEST, engine="something")},
    {"extra": {"other-folder/file": "x"}},
])
def test_rejects_bad_packs(tmp_path, bad):
    with pytest.raises(modelpack.PackError):
        modelpack.install(_pack(tmp_path / "bad.zip", **bad), str(tmp_path / "models"))
    assert not os.path.exists(str(tmp_path / "models" / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8"))


def test_rejects_non_zip(tmp_path):
    p = tmp_path / "x.zip"
    p.write_text("not a zip")
    with pytest.raises(modelpack.PackError):
        modelpack.inspect(str(p))
