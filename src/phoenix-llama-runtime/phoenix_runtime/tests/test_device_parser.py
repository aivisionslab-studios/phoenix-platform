from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'phoenix_runtime'))
import phoenix_llama_runtime as pr


def test_list_devices_parses_vulkan_and_cuda(monkeypatch):
    def fake_run(*a, **k):
        return SimpleNamespace(returncode=0, stdout='Available devices:\n  Vulkan0: AMD Radeon RX 580\n  CUDA0: RTX\n', stderr='')
    monkeypatch.setattr(pr.subprocess, 'run', fake_run)
    assert pr.list_devices(Path('/fake/server')) == ['Vulkan0', 'CUDA0']


def test_resolve_device_prefers_vulkan(monkeypatch):
    monkeypatch.setattr(pr, 'list_devices', lambda s: ['CUDA0', 'Vulkan0'])
    assert pr.resolve_device(Path('/fake/server'), 'auto', 'Vulkan') == 'Vulkan0'


def test_explicit_device_is_not_rewritten():
    assert pr.resolve_device(Path('/fake/server'), 'CUDA0') == 'CUDA0'
