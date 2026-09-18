#!/usr/bin/env python3
"""Package and verify the ready-to-run Windows Phoenix Llama Runtime bundle.

The CMake build tree is a development artifact. Public Windows releases use a
stable bundle under ``bin/phoenix-llama-runtime/windows-x64`` containing only
runtime executables/DLLs plus a cryptographic manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = RUNTIME_ROOT.parents[1]
DEFAULT_BUNDLE = PROJECT_ROOT / "bin" / "phoenix-llama-runtime" / "windows-x64"
BUNDLE_MANIFEST = "runtime_bundle_manifest.json"
REQUIRED_EXES = ("llama-server.exe", "llama-mtmd-cli.exe")
REQUIRED_DLLS = (
    "ggml.dll",
    "ggml-base.dll",
    "ggml-cpu.dll",
    "ggml-vulkan.dll",
    "llama.dll",
    "llama-common.dll",
    "llama-server-impl.dll",
    "mtmd.dll",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _runtime_version() -> str:
    p = RUNTIME_ROOT / "PHOENIX_RUNTIME_VERSION"
    return p.read_text(encoding="utf-8").strip() if p.is_file() else "unknown"


def _source_hash(name: str) -> str | None:
    p = RUNTIME_ROOT / "phoenix_runtime" / name
    return _sha256(p) if p.is_file() else None


def resolve_build_bin(explicit: str | None = None) -> Path:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).resolve())
    build = RUNTIME_ROOT / "build" / "bin"
    candidates.extend((build / "Release", build))
    for candidate in candidates:
        if all((candidate / exe).is_file() for exe in REQUIRED_EXES):
            return candidate
    searched = " | ".join(str(x) for x in candidates)
    raise FileNotFoundError(f"Phoenix Llama Runtime build bin nao encontrado: {searched}")


def _required_runtime_files(source_bin: Path) -> list[Path]:
    missing = [name for name in (*REQUIRED_EXES, *REQUIRED_DLLS) if not (source_bin / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "bundle Windows incompleto no build: " + ", ".join(missing)
        )
    # Copy every DLL emitted alongside the two requested targets. This safely
    # carries target-specific implementation DLLs without publishing CMake/MSVC
    # intermediates or unrelated executables.
    files = [source_bin / name for name in REQUIRED_EXES]
    files.extend(sorted(source_bin.glob("*.dll"), key=lambda p: p.name.lower()))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in files:
        key = path.name.lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _run_checked(args: list[str], accepted: tuple[int, ...] = (0,)) -> tuple[bool, str]:
    try:
        cp = subprocess.run(args, text=True, capture_output=True, timeout=30, check=False)
    except Exception as exc:
        return False, str(exc)
    output = ((cp.stdout or "") + "\n" + (cp.stderr or "")).strip()
    return cp.returncode in accepted, output


def validate_executables(bundle_dir: Path) -> list[str]:
    problems: list[str] = []
    if os.name != "nt":
        return problems
    server = bundle_dir / "llama-server.exe"
    mtmd = bundle_dir / "llama-mtmd-cli.exe"
    ok, out = _run_checked([str(server), "--version"])
    if not ok:
        problems.append("llama-server.exe --version falhou: " + out[-1000:])
    ok, out = _run_checked([str(server), "--list-devices"])
    if not ok:
        problems.append("llama-server.exe --list-devices falhou: " + out[-1000:])
    contract = RUNTIME_ROOT / "phoenix_runtime" / "verify_cli_contract.py"
    if contract.is_file():
        ok, out = _run_checked([sys.executable, str(contract), "--server", str(server)])
        if not ok:
            problems.append("contrato CLI do llama-server falhou: " + out[-1000:])
    ok, out = _run_checked([str(mtmd), "--help"], accepted=(0, 1))
    if not ok:
        problems.append("llama-mtmd-cli.exe --help falhou: " + out[-1000:])
    return problems


def build_manifest(bundle_dir: Path) -> dict:
    files: dict[str, dict[str, int | str]] = {}
    for path in sorted(bundle_dir.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.name == BUNDLE_MANIFEST:
            continue
        files[path.name] = {"size": path.stat().st_size, "sha256": _sha256(path)}
    return {
        "schema_version": 1,
        "bundle": "phoenix-llama-runtime/windows-x64",
        "runtime_version": _runtime_version(),
        "source_lock_sha256": _source_hash("upstream.lock.json"),
        "source_integrity_sha256": _source_hash("source_integrity.json"),
        "required_executables": list(REQUIRED_EXES),
        "required_dlls": list(REQUIRED_DLLS),
        "files": files,
    }


def verify_bundle(bundle_dir: Path, *, validate_exec: bool = False) -> list[str]:
    bundle_dir = Path(bundle_dir)
    problems: list[str] = []
    manifest_path = bundle_dir / BUNDLE_MANIFEST
    if not manifest_path.is_file():
        return [f"manifest do runtime ausente: {manifest_path}"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"manifest do runtime invalido: {exc}"]
    if manifest.get("runtime_version") != _runtime_version():
        problems.append(
            f"runtime_version divergente: bundle={manifest.get('runtime_version')} source={_runtime_version()}"
        )
    expected_lock = _source_hash("upstream.lock.json")
    if expected_lock and manifest.get("source_lock_sha256") != expected_lock:
        problems.append("bundle foi gerado para outro upstream.lock.json")
    expected_integrity = _source_hash("source_integrity.json")
    if expected_integrity and manifest.get("source_integrity_sha256") != expected_integrity:
        problems.append("bundle foi gerado para outro source_integrity.json")
    files = manifest.get("files") or {}
    for name in (*REQUIRED_EXES, *REQUIRED_DLLS):
        if name not in files:
            problems.append(f"arquivo obrigatorio nao registrado no manifest: {name}")
    for name, meta in files.items():
        path = bundle_dir / name
        if not path.is_file():
            problems.append(f"arquivo registrado ausente: {name}")
            continue
        if path.stat().st_size <= 0:
            problems.append(f"arquivo vazio: {name}")
            continue
        if int(meta.get("size", -1)) != path.stat().st_size:
            problems.append(f"tamanho divergente: {name}")
        if meta.get("sha256") != _sha256(path):
            problems.append(f"sha256 divergente: {name}")
    if validate_exec:
        problems.extend(validate_executables(bundle_dir))
    return problems


def package_bundle(source_bin: Path, bundle_dir: Path, *, validate_exec: bool = False) -> None:
    files = _required_runtime_files(source_bin)
    bundle_parent = bundle_dir.parent
    bundle_parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="phoenix_llama_bundle_", dir=str(bundle_parent)))
    try:
        for src in files:
            shutil.copy2(src, staging / src.name)
        manifest = build_manifest(staging)
        (staging / BUNDLE_MANIFEST).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        problems = verify_bundle(staging, validate_exec=validate_exec)
        if problems:
            raise RuntimeError("bundle invalido:\n - " + "\n - ".join(problems))
        backup = bundle_dir.with_name(bundle_dir.name + ".previous")
        if backup.exists():
            shutil.rmtree(backup)
        if bundle_dir.exists():
            bundle_dir.rename(backup)
        staging.rename(bundle_dir)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build-bin", default=None)
    ap.add_argument("--bundle-dir", default=str(DEFAULT_BUNDLE))
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--skip-exec-validation", action="store_true")
    ns = ap.parse_args()
    bundle = Path(ns.bundle_dir).resolve()
    validate_exec = not ns.skip_exec_validation
    if ns.verify_only:
        problems = verify_bundle(bundle, validate_exec=validate_exec)
        if problems:
            print("PHOENIX WINDOWS RUNTIME BUNDLE FAILED", file=sys.stderr)
            for problem in problems:
                print(" -", problem, file=sys.stderr)
            return 2
        print(f"PHOENIX WINDOWS RUNTIME BUNDLE OK: {bundle}")
        return 0
    try:
        source_bin = resolve_build_bin(ns.build_bin)
        package_bundle(source_bin, bundle, validate_exec=validate_exec)
    except Exception as exc:
        print(f"PHOENIX WINDOWS RUNTIME BUNDLE FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"PHOENIX WINDOWS RUNTIME BUNDLE OK: {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
