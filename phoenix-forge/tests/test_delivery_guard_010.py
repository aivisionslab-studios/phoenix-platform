from PIL import Image

from phoenix_forge.models import GPUInfo, StressResult
from phoenix_forge.modules import delivery_guard, gpu_safety, result_integrity


GPU=GPUInfo(name="RX 580",vendor_id="1002",device_id="6FDF",
            pnp_device_id=r"PCI\VEN_1002&DEV_6FDF\4&TEST&0&0010")
BAD={"text":"????????????????","finish_reason":"stop"}
GOOD={"text":"Resposta completa e validada.","finish_reason":"stop"}


def test_guard_requests_one_clean_gpu_retry(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    result=delivery_guard.evaluate_sequence(kind="text",workload="llm",gpu_outputs=[BAD],gpu=GPU)
    assert result["status"]=="GPU_RETRY_REQUIRED"
    assert result["deliver"] is False


def test_repeated_gpu_failure_cpu_pass_blocks_only_scope(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    result=delivery_guard.evaluate_sequence(kind="text",workload="llm",gpu_outputs=[BAD,BAD],
      cpu_output=GOOD,gpu=GPU,device_name=GPU.name,runtime="llama",model="qwen")
    assert result["status"]=="DELIVERED_CPU_GPU_SCOPE_BLOCKED"
    assert result["deliver"] is True and result["effective_mode"]=="CPU"
    assert gpu_safety.authorize(GPU,workload="llm",runtime="llama",model="qwen")["state"]=="BLOCKED"
    assert gpu_safety.authorize(GPU,workload="image",runtime="diffusion",model="sd15")["state"]=="ALLOWED"


def test_cpu_failure_does_not_falsely_convict_gpu(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    result=delivery_guard.evaluate_sequence(kind="text",workload="llm",gpu_outputs=[BAD,BAD],
      cpu_output=BAD,gpu=GPU,device_name=GPU.name)
    assert result["status"]=="OUTPUT_PIPELINE_FAILURE"
    assert gpu_safety.authorize(GPU,workload="llm")["state"]=="ALLOWED"


def test_historical_vram_failure_routes_llm_directly_to_cpu(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    gpu_safety.record_result(StressResult(module="VRAM",passed=False,duration_s=1,
      metrics={"status":"MEMORY_ERROR"}),GPU)
    result=delivery_guard.evaluate_sequence(kind="text",workload="llm",gpu_outputs=[],gpu=GPU,device_name=GPU.name)
    assert result["status"]=="CPU_REQUIRED"


def test_execute_guarded_runs_two_gpu_attempts_then_cpu(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path));calls={"gpu":0,"cpu":0}
    def run_gpu():calls["gpu"]+=1;return BAD
    def run_cpu():calls["cpu"]+=1;return GOOD
    result=delivery_guard.execute_guarded(kind="text",workload="llm",gpu_runner=run_gpu,
      cpu_runner=run_cpu,gpu=GPU,device_name=GPU.name)
    assert calls=={"gpu":2,"cpu":1}
    assert result["effective_mode"]=="CPU"


def test_monitored_image_requires_independent_quality_evidence(tmp_path):
    path=tmp_path/"image.png";image=Image.new("RGB",(64,64))
    image.putdata([((x*17)%256,(y*29)%256,((x+y)*11)%256) for y in range(64) for x in range(64)]);image.save(path)
    missing=result_integrity.validate_image(path,require_independent_validation=True)
    checked=result_integrity.validate_image(path,vision_score=.9,vision_verdict="VALID",
      require_independent_validation=True)
    assert "INDEPENDENT_VALIDATOR_MISSING" in missing["failures"]
    assert checked["passed"]


def test_output_limit_is_rejected_inside_delivery_gate(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    limited={"text":"Resposta interrompida por limite","finish_reason":"length"}
    result=delivery_guard.evaluate_sequence(kind="text",workload="llm",gpu_outputs=[limited],gpu=GPU)
    assert result["trace"][0]["validation"]["passed"] is False
    assert "OUTPUT_LIMIT_REACHED" in result["trace"][0]["validation"]["failures"]
