"""Testes: create_document_direct nunca entrega o RACIOCÍNIO BRUTO do
modelo como se fosse o conteúdo final do documento.

Achado real do usuário, com print de tela: pedido "transformar em md" com
um .docx anexado devolveu, como "documento gerado", o pensamento interno
do modelo em inglês ("Okay, I need to convert the given content from the
'Documento01.docx' into a markdown format. Let me start by understanding
the content...") - não um markdown de verdade.

Causa raiz: `llama_cpp.py` tem um fallback antigo (PHX-FIX 22/08, pensado
pra outro cenário - comparação CPU/GPU) que usa `reasoning_content` como
resposta quando `content` volta vazio. Nunca era verificado por quem
consome o resultado - `create_document_direct` aceitava isso como
"sucesso" e materializava o raciocínio bruto como o arquivo.
"""
import asyncio

from core.domain.execution import ExecutionResult, ExecutionStatus
from phoenix_kernel.orchestration.execution_arbiter import ExecutionArbiter
from phoenix_kernel.resident.resident_manager import ResidentManager


class _FakeRuntime:
    def __init__(self, output_text: str, used_reasoning_fallback: bool):
        self._output_text = output_text
        self._used_reasoning_fallback = used_reasoning_fallback

    async def execute(self, plan):
        return ExecutionResult(
            plan_id="fake", status=ExecutionStatus.SUCCESS, output=self._output_text,
            metrics={"used_reasoning_fallback": self._used_reasoning_fallback},
        )


class _FakeRegistry:
    def resolve(self, role, hint=None):
        class R:
            runtime = "llama.cpp"
            id = "qwen3:4b"
        return R()


class _FakeLogs:
    def add_event(self, *a, **k):
        pass


def _make_resident(output_text, used_reasoning_fallback):
    resident = ResidentManager.__new__(ResidentManager)
    resident.runtime = _FakeRuntime(output_text, used_reasoning_fallback)
    resident.registry = _FakeRegistry()
    resident.logs = _FakeLogs()
    resident.execution_arbiter = ExecutionArbiter()
    resident._active_models = {}
    return resident


def test_reasoning_leaked_as_content_is_treated_as_failure():
    """O cenário exato do print de tela: content vazio, reasoning_content
    virou a 'resposta' - tem que ser tratado como falha clara, nunca
    materializado como documento."""
    raciocinio_vazado = (
        "Okay, I need to convert the given content from the 'Documento01.docx' "
        "into a markdown format. Let me start by understanding the content..."
    )
    resident = _make_resident(raciocinio_vazado, used_reasoning_fallback=True)

    async def rodar():
        return await resident.create_document_direct(
            instruction="transformar em md", output_format="md",
        )

    result = asyncio.run(rodar())
    assert result["ok"] is False
    assert "pensando" in result["error"].lower()
    assert raciocinio_vazado not in str(result)


def test_normal_response_without_fallback_is_accepted():
    """Regressão: resposta normal (sem fallback) continua funcionando -
    a correção não pode rejeitar documentos legítimos."""
    conteudo_real = "# Documento convertido\n\nConteúdo real em markdown."
    resident = _make_resident(conteudo_real, used_reasoning_fallback=False)

    async def rodar():
        return await resident.create_document_direct(
            instruction="transformar em md", output_format="md",
        )

    result = asyncio.run(rodar())
    # não deve falhar por causa do fallback (pode falhar por outro motivo
    # de materialização não mockado aqui - o que importa é que NÃO é o
    # erro específico do fallback de raciocínio)
    if not result.get("ok"):
        assert "pensando" not in result.get("error", "").lower()


def test_missing_metrics_key_defaults_to_false_never_crashes():
    """Um ExecutionResult sem a chave used_reasoning_fallback (código mais
    antigo, ou outro driver que não a define) não pode quebrar - .get()
    tem que tratar ausência como False, não None-vs-True confuso."""
    resident = ResidentManager.__new__(ResidentManager)

    class _RuntimeSemMetrics:
        async def execute(self, plan):
            return ExecutionResult(plan_id="fake", status=ExecutionStatus.SUCCESS, output="conteúdo normal")

    resident.runtime = _RuntimeSemMetrics()
    resident.registry = _FakeRegistry()
    resident.logs = _FakeLogs()
    resident.execution_arbiter = ExecutionArbiter()
    resident._active_models = {}

    async def rodar():
        return await resident.create_document_direct(
            instruction="criar documento", output_format="md",
        )

    result = asyncio.run(rodar())
    # não pode ter dado erro de fallback (a chave nem existe)
    if not result.get("ok"):
        assert "pensando" not in result.get("error", "").lower()
