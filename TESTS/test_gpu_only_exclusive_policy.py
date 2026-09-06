from pathlib import Path
from phoenix_kernel.orchestration.execution_arbiter import ExecutionArbiter, ResourcePolicy
ROOT=Path(__file__).parents[1]
def test_resource_policy_is_differentiated_not_blanket_gpu():
    # PHX-FIX (31/08, mesma investigação RX580/Vulkan que corrigiu
    # llama_cpp.py/execution_arbiter.py): esta era a premissa perigosa que
    # causou o incidente original - "tudo é GPU", inclusive chat trivial
    # ("ola"), sem nenhum self-test no caminho. Nesta GPU (RX 580/Polaris),
    # isso corrompe silenciosamente QUALQUER saída de texto do llama.cpp.
    # Substituído por uma checagem que confirma a política real,
    # diferenciada por intenção (ver PHOENIX_GPU_ONLY_EXCLUSIVE_POLICY.md).
    a = ExecutionArbiter()
    chat = a.intercept("ola")
    image = a.intercept("gere uma imagem")
    transcribe = a.intercept("transcreva", attachments=[{"name": "a.wav"}])
    vision = a.intercept("descreva", attachments=[{"name": "a.png"}])
    heavy_doc = a.intercept(
        "crie um documento longo", requested_operation="create", unlimited_output=True,
    )
    assert chat.resource_policy == ResourcePolicy.CPU
    assert chat.resource_policy != ResourcePolicy.GPU
    assert image.resource_policy == ResourcePolicy.GPU
    # PHX-NOTE: visão (mtmd_driver.py) e transcrição (whisper.py) ficam em
    # CPU puro aqui, não GPU_WITH_CPU_FALLBACK - ao contrário do worker de
    # documentos (document_llm_worker.py), nenhum dos dois drivers
    # implementa hoje um sanity_check()/self-test de correctness antes de
    # aceitar saída Vulkan. Rotear pra GPU_WITH_CPU_FALLBACK sem essa rede
    # de segurança recriaria o mesmo risco de aceitar saída corrompida
    # como sucesso - CPU continua sendo o único caminho comprovado pra
    # esses dois até existir um self-test real no driver.
    assert transcribe.resource_policy == ResourcePolicy.CPU
    assert vision.resource_policy == ResourcePolicy.CPU
    assert heavy_doc.resource_policy == ResourcePolicy.GPU_WITH_CPU_FALLBACK
def test_exclusive_runtime_contract():
    t=(ROOT/"phoenix_kernel/runtime/engine.py").read_text(encoding="utf-8")
    assert "self._exclusive_execution_lock = asyncio.Lock()" in t
    assert "await self.stop_all(except_runtime=plan.runtime)" in t
