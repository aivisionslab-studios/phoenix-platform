"""
Teste de regressão pra auditoria completa 2026-08-28, achado de privacidade
real levantado pelo próprio usuário durante a revisão desta rodada: até
aqui, `sendToProvider()` em AviaryApp.tsx consultava o RAG e anexava o
contexto (trechos dos documentos indexados pelo usuário) ao
systemInstruction em TODA chamada de chat - inclusive quando o provedor
selecionado era de nuvem (Gemini), sem nenhum aviso ou opção de desligar.
Ou seja: texto de documento privado do usuário saía da máquina dele em
toda mensagem, se ele estivesse conversando com o Gemini com RAG ativo.

Fix: uma trava nova, ligada por padrão (`blockRagOnCloudProviders: true`
em ChatParameters) - quando o provedor ativo é de nuvem e a trava está
ligada, a consulta ao RAG nem é feita (não é só descartado depois - a
requisição de rede pro backend nunca acontece). Usuário pode desligar
explicitamente em Parâmetros (ParametersDrawer.tsx) se quiser usar RAG
com um provedor de nuvem mesmo assim. Um indicativo visual permanente
("RAG bloqueado (nuvem)") aparece ao lado do seletor de modelo em
ChatView.tsx sempre que a trava está ativa e o provedor é de nuvem -
não é um toast que aparece uma vez e some, fica visível o tempo todo
que a condição for verdadeira.

Mesmo padrão de teste de tests/test_aviary_provider_no_fake_models.py -
lê o código-fonte real, não roda um browser.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = Path(__file__).resolve().parent.parent
_TYPES = _ROOT / "platform_source" / "src" / "types.ts"
_AVIARYAPP = _ROOT / "platform_source" / "src" / "components" / "aviary" / "AviaryApp.tsx"
_PARAMETERS_DRAWER = _ROOT / "platform_source" / "src" / "components" / "aviary" / "ParametersDrawer.tsx"
_CHATVIEW = _ROOT / "platform_source" / "src" / "components" / "aviary" / "ChatView.tsx"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_chat_parameters_declares_the_block_flag():
    src = _read(_TYPES)
    iface_start = src.index("export interface ChatParameters")
    iface_end = src.index("}", iface_start)
    iface_body = src[iface_start:iface_end]
    assert "blockRagOnCloudProviders: boolean" in iface_body, (
        "ChatParameters precisa declarar blockRagOnCloudProviders - sem isso "
        "não existe como o usuário desligar/ligar o envio de RAG pra nuvem"
    )


def test_default_parameters_default_to_safe_blocked_state():
    src = _read(_AVIARYAPP)
    defaults_start = src.index("const DEFAULT_PARAMETERS: ChatParameters = {")
    defaults_end = src.index("};", defaults_start)
    defaults_body = src[defaults_start:defaults_end]
    assert re.search(r"blockRagOnCloudProviders:\s*true", defaults_body), (
        "DEFAULT_PARAMETERS precisa vir com blockRagOnCloudProviders: true - "
        "o default tem que ser SEGURO (bloqueado), nunca vazar por padrão"
    )


def test_parameters_drawer_reset_also_defaults_to_blocked():
    src = _read(_PARAMETERS_DRAWER)
    reset_start = src.index("const handleReset = ()")
    reset_end = src.index("};", reset_start)
    reset_body = src[reset_start:reset_end]
    assert re.search(r"blockRagOnCloudProviders:\s*true", reset_body), (
        "handleReset() em ParametersDrawer.tsx precisa manter "
        "blockRagOnCloudProviders: true - resetar parâmetros não pode "
        "reabrir o vazamento de RAG pra nuvem"
    )


def test_parameters_drawer_exposes_a_working_toggle():
    src = _read(_PARAMETERS_DRAWER)
    assert "id=\"block-rag-cloud-toggle\"" in src
    toggle_start = src.index('id="block-rag-cloud-toggle"')
    toggle_chunk = src[toggle_start:toggle_start + 400]
    assert "checked={parameters.blockRagOnCloudProviders}" in toggle_chunk, (
        "o checkbox precisa refletir o estado real de blockRagOnCloudProviders"
    )
    assert "blockRagOnCloudProviders: e.target.checked" in toggle_chunk, (
        "o checkbox precisa de fato conseguir MUDAR blockRagOnCloudProviders, "
        "não só exibir o valor"
    )


def test_send_to_provider_skips_the_rag_network_call_for_blocked_cloud_providers():
    """O núcleo da trava: quando isCloudProvider && blockRagOnCloudProviders,
    o fetch('/api/rag/query') não pode nem ser tentado - a proteção real é
    não fazer a consulta, não só descartar o resultado depois."""
    src = _read(_AVIARYAPP)

    assert "const CLOUD_PROVIDER_TYPES: ReadonlySet<string> = new Set(['gemini']);" in src, (
        "lista central de tipos de provedor considerados nuvem não encontrada "
        "- sem ela não dá pra saber quais provedores a trava protege"
    )

    send_start = src.index("const sendToProvider = async (msgList: ChatMessage[]) => {")
    send_chunk = src[send_start:send_start + 3000]

    assert "const isCloudProvider = CLOUD_PROVIDER_TYPES.has(providerObj.type);" in send_chunk
    assert re.search(
        r"const ragBlockedForCloudPrivacy\s*=\s*isCloudProvider\s*&&\s*parameters\.blockRagOnCloudProviders;",
        send_chunk,
    ), "a condição de bloqueio precisa depender tanto do tipo de provedor quanto do parâmetro do usuário"

    # O fetch precisa estar de fato dentro do branch "NÃO bloqueado" - ou
    # seja, depois de "if (ragBlockedForCloudPrivacy) { ... } else if
    # (ragQuery) {", nunca antes/fora dessa checagem.
    guard_idx = send_chunk.index("if (ragBlockedForCloudPrivacy)")
    fetch_idx = send_chunk.index("fetch('/api/rag/query'")
    else_branch_idx = send_chunk.index("} else if (ragQuery) {")
    assert guard_idx < else_branch_idx < fetch_idx, (
        "fetch('/api/rag/query') precisa estar dentro do branch 'else if (ragQuery)' "
        "que só roda quando ragBlockedForCloudPrivacy é falso"
    )


def test_local_providers_are_never_affected_by_the_cloud_privacy_flag():
    """Confirma que a trava é específica de nuvem - Ollama/llama-server/
    LM Studio continuam recebendo RAG independente desta flag."""
    src = _read(_AVIARYAPP)
    assert "CLOUD_PROVIDER_TYPES: ReadonlySet<string> = new Set(['gemini']);" in src
    # Nenhum dos três tipos locais pode estar na lista de "nuvem".
    cloud_set_line = src[src.index("CLOUD_PROVIDER_TYPES"):src.index("CLOUD_PROVIDER_TYPES") + 200]
    for local_type in ("ollama", "llama-server", "lmstudio"):
        assert f"'{local_type}'" not in cloud_set_line, (
            f"'{local_type}' não pode estar na lista de provedores de nuvem - "
            "ele é um provedor LOCAL e nunca deveria ter o RAG bloqueado"
        )


def test_chatview_shows_a_persistent_indicator_when_rag_is_blocked():
    """O aviso precisa ser visível o tempo todo que a condição for
    verdadeira (não um toast que aparece uma vez e nunca mais) - condicionado
    exatamente ao mesmo par (provedor de nuvem + trava ligada)."""
    src = _read(_CHATVIEW)
    assert "RAG bloqueado (nuvem)" in src
    badge_start = src.index("RAG bloqueado (nuvem)")
    badge_chunk = src[max(0, badge_start - 700):badge_start]
    assert "selectedModelObj?.providerType === 'gemini'" in badge_chunk
    assert "parameters.blockRagOnCloudProviders" in badge_chunk
