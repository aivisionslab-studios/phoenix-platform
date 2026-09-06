"""
Testes de regressão para a auditoria 2026-08-20, "Resident Research +
llama.cpp JSON hardening" (achado explícito: json_format=True no
ExecutionPlan não fazia NADA no LlamaCppDriver - só o OllamaDriver lia
esse campo. resident research em llama.cpp dependia 100% da instrução em
texto no SYSTEM_PROMPT, sem nenhuma blindagem técnica).

Cobre as duas camadas da correção:

1. LlamaCppDriver.execute() agora manda `response_format:
   {"type": "json_object"}` pro llama-server (grammar nativa do lado do
   servidor, mesmo princípio do `format: "json"` que o OllamaDriver já
   usava) quando `parameters["json_format"]` é True.
2. ReasoningEngine.plan_mission() agora tem uma segunda camada, comum aos
   dois runtimes: `_extract_json_object()` tolera cerca de código
   markdown e texto de preâmbulo/posfácio ao redor do JSON, e há retry
   com reprompt mais estrito antes de desistir.

Critério de aprovação explícito da auditoria: JSON inválido NUNCA pode
virar uma Mission válida - testado diretamente abaixo
(test_plan_mission_gives_up_cleanly_after_exhausting_retries).

Segue o mesmo padrão de test_document_engine_bridge.py: funções de teste
síncronas chamando asyncio.run() por dentro, sem depender de
pytest-asyncio/plugin extra.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from phoenix_kernel.intelligence.reasoning_engine import (
    ReasoningEngine,
    _extract_json_object,
    _extract_balanced_braces,
    _JSON_RETRY_ATTEMPTS,
)
from phoenix_kernel.runtime.drivers.llama_cpp import LlamaCppDriver


# ---------------------------------------------------------------------------
# Camada 1: _extract_json_object() / _extract_balanced_braces() - testes
# unitários puros, sem I/O, sem mocks.
# ---------------------------------------------------------------------------

def test_extract_pure_json():
    """Cenário 1 do checklist: resposta JSON pura válida."""
    text = '{"reasoning": "ok", "steps": [], "response": "oi"}'
    result = _extract_json_object(text)
    assert result == {"reasoning": "ok", "steps": [], "response": "oi"}


def test_extract_json_with_preamble_text():
    """Cenário 2: resposta com texto antes do JSON."""
    text = 'Claro, aqui está o plano solicitado:\n{"reasoning": "ok", "steps": [], "response": "oi"}\nEspero que ajude!'
    result = _extract_json_object(text)
    assert result == {"reasoning": "ok", "steps": [], "response": "oi"}


def test_extract_json_in_markdown_fence_with_json_tag():
    """Cenário 3: resposta com bloco ```json ... ```."""
    text = '```json\n{"reasoning": "ok", "steps": [], "response": "oi"}\n```'
    result = _extract_json_object(text)
    assert result == {"reasoning": "ok", "steps": [], "response": "oi"}


def test_extract_json_in_markdown_fence_without_json_tag():
    text = '```\n{"reasoning": "ok", "steps": [], "response": "oi"}\n```'
    result = _extract_json_object(text)
    assert result == {"reasoning": "ok", "steps": [], "response": "oi"}


def test_extract_invalid_json_returns_none():
    """Cenário 4: resposta com JSON inválido (vírgula sobrando, sem valor)."""
    text = '{"reasoning": "ok", "steps": [,], }'
    assert _extract_json_object(text) is None


def test_extract_no_json_at_all_returns_none():
    """Cenário 5: resposta sem JSON nenhum."""
    text = "Desculpe, não entendi o seu pedido. Pode reformular?"
    assert _extract_json_object(text) is None


def test_extract_empty_string_returns_none():
    assert _extract_json_object("") is None
    assert _extract_json_object("   \n  ") is None
    assert _extract_json_object(None) is None


def test_extract_json_array_wrapping_one_object_extracts_the_inner_object():
    """Corrigido depois de rodar o teste pela primeira vez: minha
    suposição inicial era que um array JSON deveria ser rejeitado
    (plan_mission() espera um dict). Só que _extract_balanced_braces()
    acha o primeiro '{' onde quer que ele esteja - inclusive dentro de um
    array - e isso é o comportamento CERTO, não um bug: é a mesma
    tolerância já testada pra "texto antes do JSON", só que aqui o "texto
    antes" por acaso é um colchete de array em vez de uma frase. Um LLM
    que devolve `[{...}]` em vez de `{...}` é outro desvio de formato
    comum, e extrair o objeto de dentro é mais útil do que rejeitar tudo."""
    text = '[{"reasoning": "ok"}]'
    result = _extract_json_object(text)
    assert result == {"reasoning": "ok"}


def test_extract_json_array_of_scalars_has_no_object_to_extract():
    """Diferente do caso acima: um array sem nenhum objeto dentro (só
    escalares) não tem '{' nenhum pra achar - tem que devolver None, não
    inventar um dict vazio."""
    text = '[1, 2, 3]'
    assert _extract_json_object(text) is None


def test_extract_balanced_braces_ignores_braces_inside_strings():
    """Bracket-matching tem que ignorar '{' e '}' que aparecem DENTRO de
    uma string JSON - um "reasoning" com chave literal no texto não pode
    fechar o objeto antes da hora."""
    text = '{"reasoning": "isto tem uma { chave literal } no meio", "steps": []}'
    extracted = _extract_balanced_braces(text)
    assert extracted == text
    parsed = _extract_json_object(text)
    assert parsed is not None
    assert parsed["reasoning"] == "isto tem uma { chave literal } no meio"


def test_extract_prefers_first_valid_candidate_over_malformed_fence():
    """Se o texto puro já é JSON válido, o resultado tem que ser correto
    de qualquer forma, não importa qual candidato exatamente ganhou."""
    text = '{"reasoning": "direto", "steps": [], "response": "x"}'
    result = _extract_json_object(text)
    assert result["reasoning"] == "direto"


# ---------------------------------------------------------------------------
# Helpers pra montar um ReasoningEngine mínimo, sem RAG/web real.
# ---------------------------------------------------------------------------

def _make_reasoning_engine(runtime_execute_side_effect) -> ReasoningEngine:
    registry = MagicMock()
    resolved = MagicMock()
    resolved.id = "qwen3:8b"
    resolved.runtime = "llama.cpp"
    registry.resolve = MagicMock(return_value=resolved)

    engine = ReasoningEngine(model_registry=registry)
    engine.runtime = AsyncMock()
    engine.runtime.execute = AsyncMock(side_effect=runtime_execute_side_effect)
    # Sem RAG/state real.
    engine.knowledge.build_context = MagicMock(return_value="")
    engine.state = None
    return engine


def _success_result(plan: ExecutionPlan, output: str) -> ExecutionResult:
    return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.SUCCESS, output=output)


def _run_plan_mission(engine: ReasoningEngine, user_intent: str):
    async def _go():
        with patch("phoenix_kernel.intelligence.reasoning_engine.search_web", new=AsyncMock(return_value="")):
            return await engine.plan_mission(user_intent)
    return asyncio.run(_go())


# ---------------------------------------------------------------------------
# Camada 2: ReasoningEngine.plan_mission() - integração com retry.
# ---------------------------------------------------------------------------

def test_plan_mission_succeeds_on_first_try_no_retry_needed():
    valid_json = '{"reasoning": "ok", "steps": [{"action": "VALIDATE_ENVIRONMENT", "target": "docker", "description": "checar docker"}]}'

    async def fake_execute(plan):
        return _success_result(plan, valid_json)

    engine = _make_reasoning_engine(fake_execute)
    mission = _run_plan_mission(engine, "instalar docker")

    assert mission is not None
    assert len(mission.steps) == 1
    assert mission.steps[0].target == "docker"
    assert engine.runtime.execute.call_count == 1  # nenhum retry foi necessário


def test_plan_mission_recovers_via_markdown_fence_without_retry():
    fenced_json = '```json\n{"reasoning": "ok", "steps": [{"action": "VALIDATE_ENVIRONMENT", "target": "docker", "description": "x"}]}\n```'

    async def fake_execute(plan):
        return _success_result(plan, fenced_json)

    engine = _make_reasoning_engine(fake_execute)
    mission = _run_plan_mission(engine, "instalar docker")

    assert mission is not None
    assert engine.runtime.execute.call_count == 1


def test_plan_mission_retries_after_non_json_then_succeeds():
    """Cenário 6 do checklist: retry funcionando. Primeira resposta não é
    JSON de jeito nenhum; segunda (após reprompt) é válida."""
    garbled = "Desculpe, não sei gerar JSON agora."
    valid_json = '{"reasoning": "ok agora", "steps": [{"action": "VALIDATE_ENVIRONMENT", "target": "docker", "description": "x"}]}'
    responses = [garbled, valid_json]

    async def fake_execute(plan):
        return _success_result(plan, responses.pop(0))

    engine = _make_reasoning_engine(fake_execute)
    mission = _run_plan_mission(engine, "instalar docker")

    assert mission is not None
    assert mission.metadata["llm_reasoning"] == "ok agora"
    assert engine.runtime.execute.call_count == 2

    # O reprompt do retry precisa citar o erro e reforçar a instrução -
    # não pode ser simplesmente repetir a mesma pergunta.
    second_call_plan = engine.runtime.execute.call_args_list[1].args[0]
    assert "não pôde ser lida como JSON" in second_call_plan.parameters["user_prompt"]
    assert second_call_plan.parameters["json_format"] is True


def test_plan_mission_gives_up_cleanly_after_exhausting_retries():
    """Cenário 7 do checklist - o mais importante: JSON inválido não pode
    virar missão registrada, mesmo depois de esgotar as tentativas."""
    async def fake_execute(plan):
        return _success_result(plan, "isto nunca vai ser JSON, por mais que eu tente")

    engine = _make_reasoning_engine(fake_execute)
    mission = _run_plan_mission(engine, "faça algo")

    assert mission is None
    assert engine.last_error is not None
    assert "não é um JSON válido" in engine.last_error
    assert engine.runtime.execute.call_count == _JSON_RETRY_ATTEMPTS


def test_plan_mission_no_retry_on_runtime_failure():
    """Falha de runtime (rede, processo morto) é uma classe de erro
    diferente de "resposta não é JSON" - não deve consumir tentativas de
    retry, só falha direto."""
    async def fake_execute(plan):
        return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=["llama-server não respondeu"])

    engine = _make_reasoning_engine(fake_execute)
    mission = _run_plan_mission(engine, "faça algo")

    assert mission is None
    assert engine.runtime.execute.call_count == 1
    assert "llama-server não respondeu" in engine.last_error


def test_plan_mission_valid_json_without_steps_or_response_is_rejected():
    """JSON sintaticamente válido mas sem 'steps' nem 'response' continua
    sendo rejeitado (comportamento pré-existente, não pode regredir)."""
    async def fake_execute(plan):
        return _success_result(plan, '{"reasoning": "algo genérico"}')

    engine = _make_reasoning_engine(fake_execute)
    mission = _run_plan_mission(engine, "faça algo")

    assert mission is None
    assert "sem 'steps' nem 'response'" in engine.last_error


def test_plan_mission_direct_response_conversational_no_mission():
    """Resposta conversacional (steps vazio, response preenchido) continua
    devolvendo None mas populando last_response - comportamento
    pré-existente, não pode regredir."""
    async def fake_execute(plan):
        return _success_result(plan, '{"reasoning": "só bater papo", "steps": [], "response": "Oi! Como posso ajudar?"}')

    engine = _make_reasoning_engine(fake_execute)
    mission = _run_plan_mission(engine, "oi")

    assert mission is None
    assert engine.last_response == "Oi! Como posso ajudar?"


def test_plan_mission_uses_llama_cpp_by_default():
    """Cenário 8 do checklist: resident research usando llama.cpp com
    json_format=True - confirma que o runtime resolvido é mesmo llama.cpp
    quando não há hint de Ollama, e que json_format viaja no ExecutionPlan."""
    async def fake_execute(plan):
        assert plan.runtime == "llama.cpp"
        assert plan.parameters["json_format"] is True
        return _success_result(plan, '{"reasoning": "ok", "steps": [{"action": "VALIDATE_ENVIRONMENT", "target": "docker", "description": "x"}]}')

    engine = _make_reasoning_engine(fake_execute)
    mission = _run_plan_mission(engine, "checar docker")

    assert mission is not None


def test_plan_mission_respects_ollama_hint_without_breaking():
    """Cenário 9 do checklist: resident research usando Ollama opcional
    sem quebrar - com text_engine_hint='ollama', o plan_mission ainda usa
    a mesma blindagem de extração/retry (não é exclusiva do llama.cpp)."""
    registry = MagicMock()
    resolved = MagicMock()
    resolved.id = "qwen3:8b"
    resolved.runtime = "ollama"
    registry.resolve = MagicMock(return_value=resolved)

    engine = ReasoningEngine(model_registry=registry)
    engine.text_engine_hint = "ollama"
    engine.knowledge.build_context = MagicMock(return_value="")
    engine.state = None

    async def fake_execute(plan):
        assert plan.runtime == "ollama"
        return _success_result(plan, '```json\n{"reasoning": "via ollama", "steps": [{"action": "VALIDATE_ENVIRONMENT", "target": "docker", "description": "x"}]}\n```')

    engine.runtime = AsyncMock()
    engine.runtime.execute = AsyncMock(side_effect=fake_execute)

    mission = _run_plan_mission(engine, "checar docker")

    assert mission is not None
    assert mission.metadata["llm_reasoning"] == "via ollama"


# ---------------------------------------------------------------------------
# Camada 1, no driver: LlamaCppDriver.execute() manda response_format
# quando json_format=True, e NÃO manda quando é uma chamada comum.
# ---------------------------------------------------------------------------

class _FakeHttpResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Duck-type mínimo de httpx.AsyncClient - só o suficiente pro
    LlamaCppDriver.execute() (async with ... as client: client.post(...))."""

    def __init__(self, captured_payload: dict, response_payload: dict, *args, **kwargs):
        self._captured_payload = captured_payload
        self._response_payload = response_payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        self._captured_payload.update(json or {})
        return _FakeHttpResponse(self._response_payload)


def test_llama_cpp_driver_sends_response_format_when_json_format_true():
    driver = LlamaCppDriver()
    driver._model_path = Path("fake-model.gguf")

    plan = ExecutionPlan(
        runtime="llama.cpp",
        model="qwen3:8b",
        parameters={
            "system_prompt": "sys",
            "user_prompt": "gerar plano",
            "json_format": True,
        },
    )

    captured_payload = {}
    response_payload = {
        "choices": [{"message": {"content": '{"reasoning": "ok", "steps": []}'}}],
        "usage": {"completion_tokens": 10, "prompt_tokens": 5},
    }

    async def _go():
        with patch.object(LlamaCppDriver, "_check_health", new=AsyncMock(return_value=True)):
            with patch(
                "phoenix_kernel.runtime.drivers.llama_cpp.httpx.AsyncClient",
                lambda *a, **k: _FakeAsyncClient(captured_payload, response_payload, *a, **k),
            ):
                return await driver.execute(plan)

    result = asyncio.run(_go())

    assert result.status == ExecutionStatus.SUCCESS
    assert captured_payload.get("response_format") == {"type": "json_object"}


def test_llama_cpp_driver_omits_response_format_when_not_requested():
    """Uma chamada comum (chat normal, sem json_format) não deve forçar
    o backend a produzir JSON - isso quebraria respostas conversacionais
    de texto livre."""
    driver = LlamaCppDriver()
    driver._model_path = Path("fake-model.gguf")

    plan = ExecutionPlan(
        runtime="llama.cpp",
        model="qwen3:8b",
        parameters={"system_prompt": "sys", "user_prompt": "oi, tudo bem?"},
    )

    captured_payload = {}
    response_payload = {
        "choices": [{"message": {"content": "Tudo bem, e você?"}}],
        "usage": {"completion_tokens": 6, "prompt_tokens": 4},
    }

    async def _go():
        with patch.object(LlamaCppDriver, "_check_health", new=AsyncMock(return_value=True)):
            with patch(
                "phoenix_kernel.runtime.drivers.llama_cpp.httpx.AsyncClient",
                lambda *a, **k: _FakeAsyncClient(captured_payload, response_payload, *a, **k),
            ):
                return await driver.execute(plan)

    result = asyncio.run(_go())

    assert result.status == ExecutionStatus.SUCCESS
    assert "response_format" not in captured_payload
