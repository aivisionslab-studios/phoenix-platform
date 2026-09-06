from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def test_frozen_base():
    lock = json.loads((ROOT / "DEPENDENCIES.lock.json").read_text(encoding="utf-8"))
    assert lock["upstream_base"]["commit"] == "6b3edaaf32cc19e5bb2d819c788bd557eddc8eba"
    assert lock["dependencies"]["ggml"]["commit"] == "e20c3a14aa70ee84ca58499814206dd08d8026bc"

def test_bridge_present():
    cpp=(ROOT / "phoenix/src/phoenix_sd_bridge.cpp").read_text(encoding="utf-8")
    assert '#include "stable-diffusion.h"' in cpp
    assert "new_sd_ctx" in cpp
    assert "generate_image" in cpp
    assert "free_sd_ctx" in cpp

def test_no_kobold_runtime_files():
    forbidden={"sdtype_adapter.cpp","kcpp_backend.cpp","kcpp_backend.h","koboldcpp.py","kcpp_sd_extensions.h"}
    found={p.name for p in ROOT.rglob('*') if p.is_file()}
    assert forbidden.isdisjoint(found)

def test_windows_vulkan_preset():
    data=json.loads((ROOT / "CMakePresets.json").read_text(encoding="utf-8"))
    p=data["configurePresets"][0]["cacheVariables"]
    assert p["SD_VULKAN"] == "ON"
    assert p["SD_CUDA"] == "OFF"
    assert p["PHOENIX_BUILD_BRIDGE"] == "ON"
