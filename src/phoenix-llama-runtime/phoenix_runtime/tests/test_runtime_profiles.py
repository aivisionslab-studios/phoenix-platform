from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'phoenix_runtime'))
import phoenix_llama_runtime as pr


def fake_server(tmp_path: Path):
    p = tmp_path / ('llama-server.exe' if sys.platform.startswith('win') else 'llama-server')
    p.write_text('x')
    return p


def test_cpu_profile_is_strict():
    p = pr.load_profile('cpu')
    assert ('-ngl', '0') == tuple(p.args[:2])
    assert '--device' in p.args and 'none' in p.args
    assert '--no-op-offload' in p.args


def test_gpu_uses_native_all():
    p = pr.load_profile('gpu')
    i = p.args.index('-ngl')
    assert p.args[i+1] == 'all'
    assert '999' not in p.args


def test_hybrid_uses_fit_and_auto():
    p = pr.load_profile('hybrid')
    assert p.args[p.args.index('-ngl')+1] == 'auto'
    assert p.args[p.args.index('--fit')+1] == 'on'
    assert '--fit-target' in p.args
    assert '--fit-ctx' in p.args


def test_polaris_conservative_keeps_real_gpu_layer():
    p = pr.load_profile('polaris-conservative')
    assert p.args[p.args.index('-ngl')+1] == '1'
    assert 'output.weight=CPU' in p.args
    assert '--no-op-offload' in p.args


def test_moe_profile_uses_native_cpu_moe():
    p = pr.load_profile('moe-hybrid')
    assert '--cpu-moe' in p.args


def test_lock_pins_upstream_and_disables_auto_update():
    lock = pr.load_lock()
    assert lock['upstream']['commit'] == 'e71b80510c848c00175924ecf3c40333ccae8eb5'
    assert lock['policy']['auto_update_upstream'] is False
