import json

from phoenix_forge.models import GPUInfo, StressResult
from phoenix_forge.modules import gpu_ledger, gpu_safety


PNP_A = r"PCI\VEN_1002&DEV_6FDF&SUBSYS_0B311002&REV_EF\4&AAAA&0&0010"
PNP_B = r"PCI\VEN_1002&DEV_6FDF&SUBSYS_0B311002&REV_EF\4&BBBB&0&0010"


def _gpu(pnp=PNP_A):
    return GPUInfo(name="AMD Radeon RX 580 2048SP", pnp_device_id=pnp,
                   vendor_id="1002", device_id="6FDF")


def test_migrates_generic_pci_key_without_losing_history(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR", str(tmp_path))
    old={"schema":gpu_safety.SCHEMA,"updated_at":"old","devices":{"pci":{
        "identity":gpu_safety.gpu_identity(_gpu()),"device_health":"DEGRADED",
        "diagnostic_required":True,"global_ai_blocked":False,"authorizations":{},
        "scope_failures":{},"failure_count":1,"observations":[{"kind":"hardware_test","status":"MEMORY_ERROR"}]}}}
    (tmp_path/"gpu-safety.json").write_text(json.dumps(old), encoding="utf-8")
    loaded=gpu_safety.load()
    assert "pci" not in loaded["devices"]
    device=next(iter(loaded["devices"].values()))
    assert device["identity_history"] == ["pci"]
    assert device["observations"][0]["status"] == "MEMORY_ERROR"
    assert "pci" not in json.loads((tmp_path/"gpu-safety.json").read_text())["devices"]


def test_identical_models_in_different_slots_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR", str(tmp_path))
    assert gpu_safety.gpu_identity(_gpu(PNP_A))["key"] != gpu_safety.gpu_identity(_gpu(PNP_B))["key"]
    gpu_safety.record_result(StressResult(module="Phoenix Memory / VRAM Map",passed=False,
        duration_s=1,metrics={"status":"MEMORY_ERROR"}),_gpu(PNP_A))
    gpu_safety.record_result(StressResult(module="Phoenix Memory / VRAM Map",passed=True,
        duration_s=1,metrics={"status":"FULL_SCAN_PASS"}),_gpu(PNP_B))
    devices=gpu_safety.load()["devices"]
    assert len(devices)==2
    assert sorted(d["diagnostic_required"] for d in devices.values()) == [False, True]


def test_utf16_reports_import_and_cross_encoding_deduplicate(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR", str(tmp_path/"state"))
    raw={"module":"Phoenix Memory / VRAM Map","passed":True,
         "metrics":{"status":"FULL_SCAN_PASS","device_name":"Test GPU"}}
    utf16=tmp_path/"report-utf16.json";utf8=tmp_path/"report-utf8.json"
    text=json.dumps(raw);utf16.write_bytes(text.encode("utf-16"));utf8.write_text(text,encoding="utf-8")
    first=gpu_ledger.ingest_report(str(utf16));second=gpu_ledger.ingest_report(str(utf8))
    assert first["ingest"]=="RECORDED"
    assert second["ingest"]=="DUPLICATE_SKIPPED"


def test_ledger_separates_hardware_external_correctness_and_setup(tmp_path, monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR", str(tmp_path))
    gpu=_gpu()
    cases=[
      ("Phoenix Memory / VRAM Map",False,{"status":"MEMORY_ERROR"}),
      ("Phoenix Memory / VRAM Map",True,{"status":"FULL_SCAN_PASS"}),
      ("Phoenix Crucible / GPU Compute",False,{"status":"NATIVE_ERROR","error":"stress.spv not found"}),
      ("Phoenix Crucible / GPU Compute",True,{"status":"PASS"}),
      ("Phoenix Crucible / GPU Compute",True,{"status":"PASS","correctness_verified":True}),
      ("External / OCCT",False,{"status":"MEMORY_ERROR","external_tool":"OCCT","sample_errors":12}),
    ]
    for module,passed,metrics in cases:
        gpu_safety.record_result(StressResult(module=module,passed=passed,duration_s=1,metrics=metrics),gpu)
    tests=gpu_ledger.summarize(gpu.name)["tests"]
    assert tests["phoenix_memory_error_runs"]==1
    assert tests["external_memory_error_runs"]==1
    assert tests["full_scan_passes"]==1
    assert tests["compute_operational_passes"]==1
    assert tests["compute_correctness_passes"]==1
    assert tests["setup_errors"]==1
    assert tests["hardware_evidence_total"]==5
