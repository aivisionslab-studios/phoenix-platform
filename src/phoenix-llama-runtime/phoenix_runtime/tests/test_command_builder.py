from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'phoenix_runtime'))
import phoenix_llama_runtime as pr


def test_cpu_command_contains_reasoning_and_no_device(monkeypatch, tmp_path):
    server = tmp_path/'llama-server'; server.write_text('x')
    model = tmp_path/'model.gguf'; model.write_text('x')
    cmd, dev = pr.build_command(server, model, 'cpu', ctx=4096, threads=8)
    assert dev is None
    assert '--jinja' in cmd
    assert '--reasoning-format' in cmd and 'auto' in cmd
    assert '--device' in cmd and 'none' in cmd
    assert '-ngl' in cmd and cmd[cmd.index('-ngl')+1] == '0'


def test_gpu_command_resolves_device(monkeypatch, tmp_path):
    server = tmp_path/'llama-server'; server.write_text('x')
    model = tmp_path/'model.gguf'; model.write_text('x')
    monkeypatch.setattr(pr, 'resolve_device', lambda *a, **k: 'Vulkan0')
    cmd, dev = pr.build_command(server, model, 'gpu')
    assert dev == 'Vulkan0'
    assert cmd[cmd.index('-ngl')+1] == 'all'
    assert cmd[cmd.index('--device')+1] == 'Vulkan0'
