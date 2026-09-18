import base64
import io

import pytest
from PIL import Image

from phoenix_forge.models import GPUInfo,StressResult
from phoenix_forge.modules import gpu_ledger,gpu_safety,runtime_guard

GPU=GPUInfo(name="RX 580",vendor_id="1002",device_id="6FDF",
  pnp_device_id=r"PCI\VEN_1002&DEV_6FDF\4&RUNTIME&0&0010")


class Response:
    def __init__(self,data,status=200):self.data=data;self.status_code=status
    def raise_for_status(self):
        if self.status_code>=400:raise RuntimeError(f"HTTP {self.status_code}")
    def json(self):return self.data


def test_guarded_chat_uses_gpu_when_allowed(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path));calls=[]
    def post(url,**kwargs):
        calls.append(url);return Response({"choices":[{"message":{"content":"Resposta GPU íntegra."},"finish_reason":"stop"}]})
    monkeypatch.setattr(runtime_guard.httpx,"post",post)
    result=runtime_guard.guarded_chat(gpu_url="http://127.0.0.1:8081/v1",cpu_url="http://127.0.0.1:8082/v1",
      model="qwen",messages=[{"role":"user","content":"Teste"}],device_name=GPU.name,gpu=GPU)
    assert result["status"]=="DELIVERED_GPU"
    assert calls==["http://127.0.0.1:8081/v1/chat/completions"]


def test_guarded_chat_skips_gpu_when_ledger_restricts_llm(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path));calls=[]
    gpu_safety.record_result(StressResult(module="VRAM",passed=False,duration_s=1,
      metrics={"status":"MEMORY_ERROR"}),GPU)
    def post(url,**kwargs):
        calls.append(url);return Response({"choices":[{"message":{"content":"Resposta CPU íntegra."},"finish_reason":"stop"}]})
    monkeypatch.setattr(runtime_guard.httpx,"post",post)
    result=runtime_guard.guarded_chat(gpu_url="http://127.0.0.1:8081/v1",cpu_url="http://127.0.0.1:8082/v1",
      model="qwen",messages=[{"role":"user","content":"Teste"}],device_name=GPU.name,gpu=GPU)
    assert result["status"]=="DELIVERED_CPU"
    assert calls==["http://127.0.0.1:8082/v1/chat/completions"]


def _png()->str:
    image=Image.new("RGB",(64,64));image.putdata([((x%2)*255,(y%2)*255,((x+y)%2)*255) for y in range(64) for x in range(64)])
    stream=io.BytesIO();image.save(stream,format="PNG");return base64.b64encode(stream.getvalue()).decode()


def test_guarded_image_retries_gpu_then_delivers_cpu(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path));calls=[]
    def post(url,**kwargs):
        calls.append(url)
        if ":7860" in url:return Response({"images":["not-base64"]})
        return Response({"images":[_png()]})
    monkeypatch.setattr(runtime_guard.httpx,"post",post)
    result=runtime_guard.guarded_image(gpu_url="http://127.0.0.1:7860",cpu_url="http://127.0.0.1:7861",
      prompt="phoenix",device_name=GPU.name,gpu=GPU)
    assert result["status"]=="DELIVERED_CPU_GPU_SCOPE_BLOCKED"
    assert sum(":7860" in x for x in calls)==2 and sum(":7861" in x for x in calls)==1
    assert result["output"]["path"].endswith(".png")


def test_remote_runtime_is_blocked_by_default(monkeypatch):
    monkeypatch.delenv("PHOENIX_ALLOW_REMOTE_RUNTIME",raising=False)
    with pytest.raises(ValueError):runtime_guard._endpoint("https://example.com/v1")


def test_scoped_block_is_enforced_by_router(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    gpu_safety.record_output_failure(workload="image",backend="vulkan",runtime="stable-diffusion-api",
      model="sd15",reason="SEVERE_VISUAL_ARTIFACTS",gpu=GPU,cpu_control_passed=True,reproduced=True)
    blocked=gpu_ledger.route("image",device_name=GPU.name,backend="vulkan",runtime="stable-diffusion-api",model="sd15")
    other=gpu_ledger.route("image",device_name=GPU.name,backend="vulkan",runtime="stable-diffusion-api",model="sdxl")
    assert blocked["effective_mode"]=="CPU" and blocked["scoped_authorization"]["state"]=="BLOCKED"
    assert other["effective_mode"]!="CPU"


def test_reasoning_is_preserved_but_never_promoted_to_answer(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    def post(url,**kwargs):
        return Response({"choices":[{"message":{"content":"Resposta final.",
          "reasoning_content":"Raciocínio separado."},"finish_reason":"stop"}],"usage":{"completion_tokens":3}})
    monkeypatch.setattr(runtime_guard.httpx,"post",post)
    result=runtime_guard.guarded_chat(gpu_url="http://127.0.0.1:8082/v1",cpu_url="http://127.0.0.1:8081/v1",
      model="qwen",messages=[{"role":"user","content":"Teste"}],device_name=GPU.name,gpu=GPU,user_mode="CPU")
    assert result["output"]["text"]=="Resposta final."
    assert result["output"]["reasoning_content"]=="Raciocínio separado."


def test_empty_or_length_limited_cpu_answer_is_blocked(tmp_path,monkeypatch):
    monkeypatch.setenv("PHOENIX_FORGE_STATE_DIR",str(tmp_path))
    def post(url,**kwargs):
        return Response({"choices":[{"message":{"content":"","reasoning_content":"Não vazar."},
          "finish_reason":"length"}]})
    monkeypatch.setattr(runtime_guard.httpx,"post",post)
    result=runtime_guard.guarded_chat(gpu_url="http://127.0.0.1:8082/v1",cpu_url="http://127.0.0.1:8081/v1",
      model="qwen",messages=[{"role":"user","content":"Teste"}],device_name=GPU.name,gpu=GPU,user_mode="CPU")
    assert result["status"]=="CPU_OUTPUT_REJECTED"
    assert result["deliver"] is False and result["output"] is None
    assert result["notice"]["code"]=="CPU_OUTPUT_REJECTED"
