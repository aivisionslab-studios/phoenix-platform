from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = (ROOT / "native" / "src" / "main.cpp").read_text(encoding="utf-8")
CMAKE = (ROOT / "native" / "CMakeLists.txt").read_text(encoding="utf-8")
BUILD = (ROOT / "BUILD_WINDOWS.ps1").read_text(encoding="utf-8")


def test_windows_minmax_hardening():
    assert "#define NOMINMAX" in CPP
    assert "#undef min" in CPP
    assert "#undef max" in CPP
    assert "NOMINMAX WIN32_LEAN_AND_MEAN" in CMAKE


def test_native_dispatcher_not_single_line():
    assert "int main(int argc, char** argv)" in CPP
    assert "rc = doVram(" in CPP
    assert "rc = doVramMap(" in CPP
    assert "(std::max)(1, passes)" in CPP
    assert "(std::max<uint32_t>)(1u, rounds)" in CPP


def test_build_script_validates_native_and_shader():
    assert "Phoenix Forge v0.12.0" in BUILD
    assert "phoenix-forge-native.exe --help" in BUILD
    assert "stress.spv was not installed" in BUILD
