from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from phoenix_forge.models import StressResult
from phoenix_forge.modules import crucible, detect, gpu_qualification, gpu_safety, memory, native_benchmark, compute_fabric, gpu_identity_registry

SCHEMA = "phoenix.forge.post-flash-qualification/v1"
RUN_SCHEMA = "phoenix.forge.post-flash-run/v1"
HARDWARE_FAILURES = {"MEMORY_ERROR", "DATA_MISMATCH", "COMPUTE_MISMATCH"}
CAPACITY_FAILURES = {"OOM", "OUT_OF_MEMORY", "OUTOFDEVICEMEMORY", "TIMEOUT", "ALLOCATION_FAILED", "BUDGET_EXHAUSTED"}
STOP_FAILURES = {"SAFETY_ABORT", "DRIVER_ERROR", "DEVICE_LOST"}
PASS_STATES = {"PASS", "QUICK_PASS", "FULL_SCAN_PASS"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _runs_path() -> Path:
    return gpu_safety.state_dir() / "post-flash-qualification.jsonl"


def _append(entry: dict[str, Any]) -> None:
    path = _runs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _status(result: StressResult) -> str:
    return str(result.metrics.get("status") or ("PASS" if result.passed else "UNKNOWN")).upper()


def _record_step(name: str, result: StressResult, attempt: int = 1) -> dict[str, Any]:
    return {
        "name": name,
        "attempt": attempt,
        "status": _status(result),
        "passed": bool(result.passed),
        "duration_s": round(float(result.duration_s), 3),
        "metrics": result.metrics,
        "warnings": result.warnings,
    }


def _latest_post(device_key: str, legacy_label_key: str | None = None) -> dict[str, Any] | None:
    rows = gpu_qualification.history(None, 200).get("entries", [])
    return next((row for row in reversed(rows) if row.get("phase") == "POST_FLASH" and (row.get("device_key") == device_key or (legacy_label_key and row.get("device_key") == legacy_label_key) or (legacy_label_key and row.get("legacy_label_key") == legacy_label_key))), None)


def _identity_compatible(post: dict[str, Any], current: dict[str, Any]) -> tuple[bool, list[str]]:
    before = post.get("identity") or {}
    mismatches: list[str] = []
    # Subsystem/PNP may legitimately change after a BIOS flash or slot move.
    for field in ("vendor_id", "device_id", "revision_id"):
        a, b = before.get(field), current.get(field)
        if a and b and str(a).upper() != str(b).upper():
            mismatches.append(field)
    if before.get("vram_bytes") and current.get("vram_bytes"):
        if int(before["vram_bytes"]) != int(current["vram_bytes"]):
            mismatches.append("vram_bytes")
    return not mismatches, mismatches


def _profile(profile: str, vram_mb: int) -> list[tuple[str, Callable[[], StressResult]]]:
    normalized = str(profile or "standard").strip().lower()
    if normalized not in {"quick", "standard", "deep"}:
        raise ValueError("profile deve ser quick, standard ou deep")

    if normalized == "quick":
        map_target = min(max(512, int(vram_mb * 0.35)), 3072)
        return [
            ("vram_sample", lambda: memory.native_vram_test(256, 1, full_scan=False)),
            ("vram_map", lambda: memory.vram_map(chunk_mb=256, target_mb=map_target, passes=1, full_scan=False, adaptive=True, reserve_mb=256)),
            ("vram_bandwidth", lambda: native_benchmark.execute("vram-bandwidth", seconds=8, mb=256)),
            ("gpu_compute", lambda: crucible.gpu_compute_stress(8, 128, 32)),
        ]
    if normalized == "deep":
        map_target = min(max(1024, int(vram_mb * 0.90)), max(1024, vram_mb - 256))
        return [
            ("vram_full_scan", lambda: memory.native_vram_test(512, 2, full_scan=True, continue_on_error=True, max_errors=256)),
            ("vram_map_deep", lambda: memory.vram_map(chunk_mb=512, target_mb=map_target, passes=2, full_scan=True, adaptive=True, min_chunk_mb=128, reserve_mb=256, continue_on_error=True, max_errors=256)),
            ("vram_bandwidth", lambda: native_benchmark.execute("vram-bandwidth", seconds=60, mb=512)),
            ("gpu_compute", lambda: crucible.gpu_compute_stress(60, 256, 256)),
            ("gpu_stress", lambda: crucible.gpu_stress(60, 256)),
        ]
    map_target = min(max(768, int(vram_mb * 0.70)), max(768, vram_mb - 384))
    return [
        ("vram_full_scan", lambda: memory.native_vram_test(512, 1, full_scan=True, continue_on_error=True, max_errors=128)),
        ("vram_map", lambda: memory.vram_map(chunk_mb=512, target_mb=map_target, passes=1, full_scan=True, adaptive=True, min_chunk_mb=128, reserve_mb=384, continue_on_error=True, max_errors=128)),
        ("vram_bandwidth", lambda: native_benchmark.execute("vram-bandwidth", seconds=20, mb=512)),
        ("gpu_compute", lambda: crucible.gpu_compute_stress(20, 256, 128)),
        ("gpu_stress", lambda: crucible.gpu_stress(20, 256)),
    ]


def plan(device_label: str, device_index: int = 0, profile: str = "standard") -> dict[str, Any]:
    label = str(device_label or "").strip()
    if not label:
        raise ValueError("device_label é obrigatório")
    report = detect.collect()
    if device_index < 0 or device_index >= len(report.gpus):
        raise ValueError("GPU index not found")
    gpu = report.gpus[device_index]
    key = gpu.device_key or compute_fabric.stable_device_key(gpu)
    legacy_key = hashlib.sha256(label.casefold().encode("utf-8")).hexdigest()[:24]
    registry = gpu_identity_registry.resolve(key)
    if registry and registry.get("physical_alias") != label:
        raise ValueError(f"Alias físico divergente para esta GPU. Registrado: {registry.get('physical_alias')}")
    post = _latest_post(key, legacy_key)
    current = gpu_qualification._identity(gpu)
    compatible, mismatches = _identity_compatible(post, current) if post else (False, ["POST_FLASH_MISSING"])
    vram_mb = max(1024, int((gpu.adapter_ram_bytes or 0) / 1024 / 1024))
    steps = [name for name, _ in _profile(profile, vram_mb)]
    return {
        "schema": SCHEMA,
        "device_label": label,
        "device_key": key,
        "identity_source": "GPU_DEVICE_KEY",
        "physical_alias_confirmed": bool(registry),
        "device_index": int(device_index),
        "gpu": current,
        "profile": profile,
        "post_flash_present": bool(post),
        "identity_compatible": compatible,
        "identity_mismatches": mismatches,
        "steps": steps,
        "rule": "One data mismatch is repeated exactly once. Only reproducible mismatch is hardware evidence. Capacity failures stop the profile without becoming hardware proof.",
        "real_workloads_after_synthetic_pass": ["llm", "sd15", "sdxl"],
    }


def run(device_label: str, device_index: int = 0, profile: str = "standard") -> dict[str, Any]:
    p = plan(device_label, device_index, profile)
    if not p["post_flash_present"]:
        raise ValueError("Registre POST_FLASH para esta placa antes da qualificação.")
    if not p["identity_compatible"]:
        raise ValueError("A identidade atual da GPU não corresponde ao POST_FLASH selecionado: " + ", ".join(p["identity_mismatches"]))

    report = detect.collect()
    gpu = report.gpus[device_index]
    vram_mb = max(1024, int((gpu.adapter_ram_bytes or 0) / 1024 / 1024))
    raw_steps = _profile(profile, vram_mb)
    # Bind the selected device at the Python layer as well as in the native helper.
    bound: list[tuple[str, Callable[[], StressResult]]] = []
    for name, _ in raw_steps:
        if name.startswith("vram_sample"):
            fn = lambda d=device_index: memory.native_vram_test(256, 1, full_scan=False, device=d)
        elif name == "vram_full_scan":
            fn = lambda d=device_index: memory.native_vram_test(512, 1 if profile != "deep" else 2, full_scan=True, device=d, continue_on_error=True, max_errors=256 if profile == "deep" else 128)
        elif name == "vram_map_deep":
            target = min(max(1024, int(vram_mb * 0.90)), max(1024, vram_mb - 256))
            fn = lambda d=device_index, t=target: memory.vram_map(chunk_mb=512, target_mb=t, passes=2, full_scan=True, device=d, adaptive=True, min_chunk_mb=128, reserve_mb=256, continue_on_error=True, max_errors=256)
        elif name == "vram_map":
            target = min(max(512 if profile == "quick" else 768, int(vram_mb * (0.35 if profile == "quick" else 0.70))), max(768, vram_mb - 384))
            fn = lambda d=device_index, t=target: memory.vram_map(chunk_mb=256 if profile == "quick" else 512, target_mb=t, passes=1, full_scan=profile != "quick", device=d, adaptive=True, min_chunk_mb=128, reserve_mb=256 if profile == "quick" else 384, continue_on_error=profile != "quick", max_errors=128)
        elif name == "vram_bandwidth":
            fn = lambda d=device_index: native_benchmark.execute("vram-bandwidth", seconds=8 if profile == "quick" else (60 if profile == "deep" else 20), mb=256 if profile == "quick" else 512, device=d)
        elif name == "gpu_compute":
            fn = lambda d=device_index: crucible.gpu_compute_stress(8 if profile == "quick" else (60 if profile == "deep" else 20), 128 if profile == "quick" else 256, 32 if profile == "quick" else (256 if profile == "deep" else 128), device=d)
        elif name == "gpu_stress":
            fn = lambda d=device_index: crucible.gpu_stress(60 if profile == "deep" else 20, 256, device=d)
        else:
            continue
        bound.append((name, fn))

    rows: list[dict[str, Any]] = []
    terminal = "SYNTHETIC_PASS"
    for name, fn in bound:
        first = fn()
        row = _record_step(name, first, 1)
        rows.append(row)
        status = row["status"]
        if status in HARDWARE_FAILURES:
            second = fn()
            row2 = _record_step(name, second, 2)
            rows.append(row2)
            if row2["status"] in HARDWARE_FAILURES:
                terminal = "REPRODUCIBLE_DATA_CORRUPTION"
                break
            terminal = "SINGLE_MISMATCH_NOT_REPRODUCED"
            continue
        if status in STOP_FAILURES:
            terminal = status
            break
        if any(token in status for token in CAPACITY_FAILURES):
            terminal = "CAPACITY_LIMIT"
            break
        if status not in PASS_STATES:
            terminal = "INCONCLUSIVE"
            break

    statuses = [row["status"] for row in rows]
    classification = gpu_qualification.classify_statuses(statuses)
    if terminal == "SYNTHETIC_PASS" and classification.get("physical_defect_suspected"):
        terminal = "REPRODUCIBLE_DATA_CORRUPTION"

    result: dict[str, Any] = {
        "schema": RUN_SCHEMA,
        "run_id": hashlib.sha256(f"{p['device_key']}|{_now()}|{profile}".encode()).hexdigest()[:24],
        "started_at": _now(),
        "device_label": p["device_label"],
        "device_key": p["device_key"],
        "device_index": int(device_index),
        "profile": str(profile).lower(),
        "gpu": p["gpu"],
        "status": terminal,
        "classification": classification,
        "steps": rows,
        "synthetic_qualification_passed": terminal in {"SYNTHETIC_PASS", "SINGLE_MISMATCH_NOT_REPRODUCED"},
        "hardware_failure_confirmed": terminal == "REPRODUCIBLE_DATA_CORRUPTION",
        "capacity_failure_is_hardware_proof": False,
        "next_required_workloads": ["llm", "sd15", "sdxl"] if terminal in {"SYNTHETIC_PASS", "SINGLE_MISMATCH_NOT_REPRODUCED"} else [],
    }
    result["record_sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    _append(result)
    return result


def history(device_key: str | None = None, limit: int = 50) -> dict[str, Any]:
    try:
        lines = _runs_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and (not device_key or row.get("device_key") == device_key):
            rows.append(row)
    rows = rows[-max(1, min(int(limit), 200)):]
    return {"schema": RUN_SCHEMA, "count": len(rows), "entries": rows}
