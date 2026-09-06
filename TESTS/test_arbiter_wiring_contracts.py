from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_api_has_first_gate_before_routes():
    text = (ROOT / 'api_server.py').read_text(encoding='utf-8')
    assert '@app.middleware("http")' in text
    assert 'execution_arbiter_first_gate' in text
    assert '/api/intent/intercept' in text
    assert 'preflight_path' in text


def test_resident_delegates_resource_decision():
    text = (ROOT / 'phoenix_kernel/resident/resident_manager.py').read_text(encoding='utf-8')
    assert 'self.execution_arbiter = default_execution_arbiter' in text
    assert 'Compatibilidade: delega a decisão exclusivamente ao ExecutionArbiter' in text
    assert 'decision.resource_policy' in text
    assert 'PHOENIX SELF CONTEXT' in text
    assert 'BLOQUEADO para não materializar conteúdo inventado' in text


def test_frontend_calls_arbiter_before_legacy_heuristics():
    text = (ROOT / 'platform_source/src/components/aviary/AviaryApp.tsx').read_text(encoding='utf-8')
    arbiter = text.index("fetch('/api/intent/intercept'")
    legacy = text.index('const DOCUMENT_ACTION_PATTERN')
    assert arbiter < legacy
    assert 'arbiterClaimed' in text


def test_node_proxies_arbiter():
    text = (ROOT / 'platform_source/server.ts').read_text(encoding='utf-8')
    assert 'app.post("/api/intent/intercept"' in text
    assert 'PHOENIX_ENGINE_URL}/api/intent/intercept' in text
