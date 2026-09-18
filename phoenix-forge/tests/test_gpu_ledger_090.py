import json
from phoenix_forge.models import GPUInfo,StressResult
from phoenix_forge.modules import gpu_ledger,gpu_safety

GPU=GPUInfo(name="AMD Radeon RX 580 2048SP",vendor_id="1002",device_id="6FDF")

def test_pass_does_not_erase_previous_memory_error(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    gpu_safety.record_result(StressResult(module="VRAM",passed=False,duration_s=1,
      metrics={"status":"MEMORY_ERROR","sample_errors":2}),GPU)
    gpu_safety.record_result(StressResult(module="VRAM",passed=True,duration_s=1,
      metrics={"status":"FULL_SCAN_PASS","sample_errors":0}),GPU)
    report=gpu_ledger.summarize(GPU.name)
    assert report["classification"]=="VRAM_INTERMITTENT_SUSPECTED"
    assert report["historical_failure_latched"] is True
    assert report["tests"]["memory_error_runs"]==1

def test_suspect_gpu_routes_llm_to_cpu_but_keeps_image_monitored(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    gpu_safety.record_result(StressResult(module="VRAM",passed=False,duration_s=1,
      metrics={"status":"MEMORY_ERROR","sample_errors":2}),GPU)
    assert gpu_ledger.route("llm",device_name=GPU.name)["effective_mode"]=="CPU"
    assert gpu_ledger.route("image",device_name=GPU.name)["effective_mode"]=="GPU_MONITORED"
    forced=gpu_ledger.route("llm",device_name=GPU.name,user_mode="GPU")
    assert forced["effective_mode"]=="CPU" and forced["safety_override"]

def test_report_ingestion_and_external_evidence(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    path=tmp_path/"result.json";path.write_text(json.dumps({"module":"VRAM","passed":True,
      "metrics":{"status":"FULL_SCAN_PASS","device_name":GPU.name,"sample_errors":0}}))
    assert gpu_ledger.ingest_report(str(path))["tests"]["passes"]==1
    assert gpu_ledger.ingest_report(str(path))["ingest"]=="DUPLICATE_SKIPPED"
    report=gpu_ledger.record_external(device_name=GPU.name,tool="OCCT",status="MEMORY_ERROR",error_count=1191355)
    assert report["historical_failure_latched"] and report["classification"]=="VRAM_INTERMITTENT_SUSPECTED"
    assert gpu_ledger.record_external(device_name=GPU.name,tool="OCCT",status="MEMORY_ERROR",error_count=1191355)["ingest"]=="DUPLICATE_SKIPPED"

def test_shader_search_includes_parent_build_location():
    from pathlib import Path
    source=(Path(__file__).resolve().parents[1]/"phoenix_forge/modules/crucible.py").read_text()
    assert "exe_path.parent.parent/'stress.spv'" in source
    build=(Path(__file__).resolve().parents[1]/"BUILD_WINDOWS.ps1").read_text()
    assert "Split-Path $c -Parent" in build

def test_native_compute_has_cpu_reference_readback():
    from pathlib import Path
    source=(Path(__file__).resolve().parents[1]/"native/src/main.cpp").read_text()
    assert 'vulkan_compute_verified' in source
    assert 'COMPUTE_MISMATCH' in source
    assert 'verification_samples' in source
    assert 'vkMapMemory compute verification failed' in source
