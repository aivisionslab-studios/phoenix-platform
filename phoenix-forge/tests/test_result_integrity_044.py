import base64
from phoenix_forge.models import DetectReport,GPUInfo,StressResult
from phoenix_forge.modules import gpu_safety,result_integrity
from phoenix_forge.modules.autopilot import decide

def gpu():
    return GPUInfo(name="RX 580",vendor_id="1002",device_id="6FDF",pnp_device_id=r"PCI\VEN_1002&DEV_6FDF\1",
      vulkan_detected=True,vulkan_primary_device_local_bytes=8*1024**3)
def report():
    return DetectReport(hostname="x",os="Windows",os_version="x",architecture="AMD64",cpu="x",logical_cpus=8,
      ram_total_bytes=16*1024**3,vulkan_available=True,gpus=[gpu()])

def test_text_degenerate_and_access_violation():
    assert "DEGENERATE_REPEATED_CHARACTERS" in result_integrity.validate_text("????????????????")["failures"]
    assert "ACCESS_VIOLATION_0XC0000005" in result_integrity.validate_text("x",process_exit_code=-1073741819)["failures"]
    assert result_integrity.validate_text("Resposta completa.",finish_reason="stop")["passed"]

def test_text_scope_blocks_without_blocking_image(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    gpu_safety.record_output_failure(workload="llm",backend="vulkan",runtime="llama",model="qwen",
      reason="DEGENERATE_OUTPUT",gpu=gpu(),cpu_control_passed=True,reproduced=True)
    assert gpu_safety.authorize(gpu(),workload="llm",backend="vulkan",runtime="llama",model="qwen")["state"]=="BLOCKED"
    assert gpu_safety.authorize(gpu(),workload="image",backend="vulkan",runtime="diffusion",model="sd15")["state"]=="ALLOWED"
    assert decide(report(),workload="llm",runtime="llama",model="qwen").mode=="CPU"

def test_two_failed_domains_block_all_ai(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    for workload in ("llm","image"):
        gpu_safety.record_output_failure(workload=workload,backend="vulkan",reason="CORRUPT_OUTPUT",
          gpu=gpu(),cpu_control_passed=True,reproduced=True)
    state=gpu_safety.status_for_gpu(gpu(),workload="ocr")
    assert state["device_health"]=="AI_COMPUTE_UNSAFE"
    assert state["global_ai_blocked"] is True
    assert state["authorization"]["effective_mode"]=="CPU"

def test_vram_error_degrades_but_does_not_guess_every_workload(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    gpu_safety.record_result(StressResult(module="VRAM",passed=False,duration_s=1,
      metrics={"status":"MEMORY_ERROR","sample_errors":2}),gpu())
    state=gpu_safety.status_for_gpu(gpu(),workload="image")
    assert state["diagnostic_required"] is True
    assert state["authorization"]["state"]=="ALLOWED_MONITORED"

def test_image_ocr_and_vision_rejection(tmp_path):
    p=tmp_path/"bad.png"
    p.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
    result=result_integrity.validate_image(p,expected_text="PHOENIX ENGINE",ocr_text="PHO//// 0000",
      ocr_confidence=.1,vision_score=.1,vision_verdict="UNUSABLE")
    assert not result["passed"]
    assert "OCR_TEXT_MISMATCH" in result["failures"]
    assert "VISION_REJECTED_OUTPUT" in result["failures"]
