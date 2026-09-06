from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_document_worker_has_correctness_gate_and_dynamic_port():
    text = (ROOT / "phoenix_kernel/documents/document_llm_worker.py").read_text(encoding="utf-8")
    assert "find_free_local_port" in text
    assert "sanity_check" in text
    assert "cpu_fallback" in text
    assert '"output.weight": "CPU"' in text


def test_resident_heavy_document_router_is_fail_closed():
    text = (ROOT / "phoenix_kernel/resident/resident_manager.py").read_text(encoding="utf-8")
    assert "_execute_document_plan_routed" in text
    assert "self-test Vulkan rejeitou backend" in text
    assert "fallback para CPU compartilhada" in text


def test_installer_pins_llama_and_preserves_previous_build():
    text = (ROOT / "install/common.ps1").read_text(encoding="utf-8")
    assert "PHOENIX_LLAMA_CPP_REF" in text
    assert "0b5be7e4a" in text
    assert "$llamaBuildDir.previous" in text
    assert "--list-devices" in text


def test_unlimited_output_is_actually_honored():
    text = (ROOT / "phoenix_kernel/runtime/drivers/llama_cpp.py").read_text(encoding="utf-8")
    assert '_unlimited_output = bool(params.get("unlimited_output"))' in text
    assert 'if not _unlimited_output:' in text
