"""
Teste de regressão pra auditoria 2026-08-20, "existem falhas e fallbacks -
rastrear e tirar tudo" (achado real, vindo de screenshots + logs de
produção do usuário, não hipotético): o usuário selecionou
"[OLLAMA] qwen3:8b" no seletor de modelo do chat da Aviary e tomou
"Falha ao obter resposta do modelo. Endpoint retornou (404): {"error":
{"message":"File Not Found","type":"not_found_error","code":404}}" em
TRÊS tipos de comando diferentes (chat direto, resumo pós-transcrição de
áudio, geração de imagem) - um padrão que aponta pra um problema no
ESTADO do seletor de modelo, não num bug isolado de um endpoint.

Root cause, encontrado lendo `AviaryApp.tsx`: os provedores locais
(Ollama/llama-server/LM Studio) em `DEFAULT_PROVIDERS` vinham com
`models: [...]` cheio de nomes de EXEMPLO fabricados (nunca verificados
contra a máquina real do usuário: "deepseek-r1:8b", "llama3.3:70b" etc.
pro Ollama). `availableModels` (fonte do dropdown "[PROVIDER] modelo",
usado em ChatView.tsx/ArenaView.tsx) filtrava só por `p.enabled`, nunca
por `p.status` - então esses nomes fabricados ficavam SELECIONÁVEIS desde
o primeiro render, mesmo com o provedor `status: 'disconnected'` (nunca
confirmado alcançável). Além disso, mesmo depois de um scan real
(`handleScanAllProviders`/`handleTestProvider`, que consultam a API de
verdade do provedor), a lista de modelos era só ACRESCENTADA (união) ou
preservada em caso de resposta vazia - nunca sobrescrita pelo resultado
real mais recente - então um nome obsoleto ou fabricado nunca saía do
dropdown.

Fix: `models` dos provedores locais começa vazio; `availableModels` só
inclui modelos de um provedor local quando `status === 'connected'`; os
dois pontos de merge (`handleScanAllProviders`/`handleTestProvider`) agora
SUBSTITUEM `p.models` pelo resultado real mais recente em vez de só somar
a ele.

Esta bateria lê o código-fonte real de AviaryApp.tsx (mesmo padrão de
tests/test_audio_upload_consistency.py) - não roda um browser.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_AVIARYAPP = (
    Path(__file__).resolve().parent.parent
    / "platform_source" / "src" / "components" / "aviary" / "AviaryApp.tsx"
)


def _read_source() -> str:
    return _AVIARYAPP.read_text(encoding="utf-8")


def _default_providers_block(src: str) -> str:
    start = src.index("const DEFAULT_PROVIDERS: ProviderConfig[] = [")
    # Bloco termina no primeiro "];" na coluna 0 depois do início - o
    # array de providers não tem nenhum "];" aninhado antes disso.
    end = src.index("\n];", start)
    return src[start:end]


def test_local_providers_do_not_ship_with_fabricated_placeholder_models():
    src = _read_source()
    block = _default_providers_block(src)

    # Os três provedores locais (nunca verificados no load inicial) não
    # podem mais vir com uma lista de modelos de exemplo hardcoded - só
    # `models: []`, populado depois por um scan real.
    for provider_id in ("ollama-local", "llama-server-local", "lmstudio-local"):
        provider_start = block.index(f"id: '{provider_id}'")
        provider_chunk = block[provider_start:provider_start + 400]
        models_match = re.search(r"models:\s*(\[[^\]]*\])", provider_chunk)
        assert models_match, f"não achei o campo models: do provedor {provider_id}"
        models_literal = models_match.group(1).replace(" ", "").replace("\n", "")
        assert models_literal == "[]", (
            f"provedor {provider_id} ainda tem modelos fabricados hardcoded: "
            f"{models_match.group(1)!r} - deveriam ser populados só por scan real"
        )


def test_available_models_filters_out_local_providers_not_confirmed_connected():
    src = _read_source()
    # A função availableModels precisa checar p.status antes de expor os
    # modelos de um provedor local no dropdown - sem isso, um provedor
    # nunca pingado com sucesso (status 'disconnected') ainda oferece
    # modelos como se estivessem prontos pra uso.
    memo_start = src.index("const availableModels: ModelInfo[] = useMemo(")
    # PHX-FIX (auditoria completa 2026-08-28): janela era 1500 chars - um
    # bloco novo (exclusão de 'piper-tts' da lista inteira, não só da
    # checagem de status) foi inserido ANTES do trecho que este teste
    # procura, empurrando "p.status !== 'connected'" pra ~1977 chars do
    # início do useMemo - fora da janela antiga. Código está correto, só a
    # janela ficou curta. 3000 dá margem confortável.
    #
    # PHX-FIX (2026-09-06, achado real do usuário com print de tela: o
    # dropdown de chat perdeu os modelos locais e caiu só pro Gemini com o
    # sistema sob carga pesada - GPU a 99%): o guard antigo (`if (p.type
    # !== 'gemini' && p.status !== 'connected') return;`) era rígido demais
    # - um ping AO VIVO que falha por TIMEOUT (servidor local ocupado, não
    # morto de verdade - ver timeout de handleTestProvider/`/api/proxy/
    # ping`) marca `status: 'error'` e escondia modelos já CONFIRMADOS por
    # um scan bem-sucedido minutos antes na mesma sessão (handleTestProvider
    # preserva `p.models` no catch - só muda o status; os dados não somem,
    # só ficavam ocultos aqui). Substituído por uma variável `isUsable` que
    # distingue 'disconnected'+models vazio (nunca conectou - continua
    # bloqueado, protege ESTE MESMO teste/achado de 20/08 contra nomes
    # fabricados) de 'error'+models preenchido (falha do ping mais recente,
    # não da existência do provedor - não esconde mais). Janela aumentada
    # para 4500 (a nova condição é mais longa que a antiga, e o
    # comentário explicativo do achado empurra isUsable pra ~3499 chars).
    memo_chunk = src[memo_start:memo_start + 4500]
    assert "const isUsable = " in memo_chunk, (
        "availableModels não tem mais a variável isUsable que decide se um "
        "provedor contribui modelos pro seletor"
    )
    isusable_start = memo_chunk.index("const isUsable = ")
    isusable_line = memo_chunk[isusable_start:memo_chunk.index("\n", isusable_start)]
    # Mesmo invariante do achado de 20/08: gemini sempre isento da checagem
    # de status (cloud, não tem ping local de conectividade).
    assert "p.type === 'gemini'" in isusable_line
    # Caminho feliz: provedor local com ping bem-sucedido continua incluído.
    assert "p.status === 'connected'" in isusable_line
    # O ACHADO NOVO desta rodada: 'error' só é tolerado quando já existem
    # modelos confirmados - nunca abre uma exceção incondicional que
    # reintroduziria nomes fabricados/nunca confirmados.
    assert "p.status === 'error'" in isusable_line and "p.models.length > 0" in isusable_line, (
        "availableModels precisa tolerar status='error' SÓ quando já existem "
        "modelos confirmados (p.models.length > 0) - nunca incondicionalmente"
    )
    assert "if (!isUsable) return;" in memo_chunk
    # E o guard precisa isentar gemini (cloud, não tem 'status' de ping local)
    # da exigência de status === 'connected'.
    assert "p.type !== 'gemini'" not in memo_chunk or "p.type === 'gemini'" in isusable_line
    # PHX-FIX (auditoria completa 2026-08-28): a asserção original esperava
    # 'piper-tts' isento DENTRO da mesma condição de status (`p.type !==
    # 'piper-tts'`), mas o PHX-FIX de 2026-08-23 tornou isso desnecessário -
    # 'piper-tts' agora é excluído da lista INTEIRA por um `return` bem mais
    # cedo no loop (`if (p.type === 'piper-tts') return;`), então nunca mais
    # chega até a checagem de status pra precisar de isenção ali. Verifica o
    # invariante real (piper-tts nunca aparece no seletor de chat) pela forma
    # atual, não pela forma antiga que não existe mais.
    assert "p.type === 'piper-tts'" in memo_chunk, (
        "availableModels não está mais excluindo 'piper-tts' da lista de "
        "modelos de chat - vozes de síntese de fala não podem aparecer como "
        "modelo selecionável no chat"
    )


def test_scan_all_providers_replaces_model_list_instead_of_unioning_stale_data():
    src = _read_source()
    scan_start = src.index("const handleScanAllProviders = async ()")
    scan_chunk = src[scan_start:scan_start + 2500]

    # Regressão específica: a união antiga (`models: Array.from(new
    # Set([...p.models, ...trackedData.XModels]))`) deixava modelo
    # fabricado/obsoleto grudado pra sempre. Procura só pelo padrão de
    # CÓDIGO real (atribuição a `models:`), não em comentários explicativos
    # que citam o padrão antigo como narrativa histórica.
    assert re.search(r"models:\s*\[?\.\.\.p\.models", scan_chunk) is None, (
        "handleScanAllProviders ainda mistura p.models (potencialmente "
        "obsoleto/fabricado) com o resultado real do scan, em vez de "
        "substituir pela lista real mais recente"
    )
    assert "trackedData.ollamaModels" in scan_chunk
    assert "models: [...new Set(trackedData.ollamaModels)]" in scan_chunk


def test_handle_test_provider_trusts_real_ping_result_even_when_empty():
    src = _read_source()
    test_start = src.index("const handleTestProvider = async (providerId: string)")
    # PHX-FIX (auditoria completa 2026-08-28): janela era 2500 - o comentário
    # que documenta o refinamento pra 'llama-server' (ver asserção mais
    # abaixo) empurrou "models: data.online" pra ~2964 chars do início.
    # 5000 dá margem confortável.
    test_chunk = src[test_start:test_start + 5000]

    # Regressão específica: o merge antigo só substituía p.models quando
    # `data.models.length > 0` - um ping bem-sucedido (`data.online: true`)
    # que devolvesse ZERO modelos reais (provedor rodando mas sem nenhum
    # modelo instalado) mantinha silenciosamente a lista antiga (fabricada
    # ou obsoleta) em vez de refletir a lista real (vazia).
    assert "data.models.length > 0 ? data.models : p.models" not in test_chunk, (
        "handleTestProvider ainda só confia no resultado real do ping "
        "quando ele não vier vazio - deveria confiar sempre que "
        "data.online for true"
    )
    # PHX-FIX (auditoria completa 2026-08-28): a asserção original esperava
    # o ternário simples `data.online ? (data.models || []) : p.models`, que
    # foi substituído por uma versão mais sofisticada (PHX-FIX 2026-08-22):
    # pra 'llama-server' especificamente, funde o resultado do ping com
    # `diskChatModelsRef.current` (o ping desse provedor só reporta o único
    # modelo carregado agora, nunca a lista completa do disco - limitação
    # real da forma como o llama-server nativo é iniciado). Não é regressão -
    # é um refinamento documentado do mesmo princípio (nunca ficar preso a
    # `p.models` obsoleto quando o ping teve sucesso). Verifica o invariante
    # real em vez do literal exato: quando online, SEMPRE deriva de
    # `data.models` (direto ou fundido) - nunca cai de volta pra `p.models`
    # a não ser no branch explícito de ping SEM sucesso.
    assert re.search(r"models:\s*data\.online\b", test_chunk), (
        "handleTestProvider não está mais decidindo `models` a partir de "
        "data.online - verifique se o resultado real do ping ainda é a "
        "fonte da verdade"
    )
    online_branch = test_chunk[test_chunk.index("models: data.online"):]
    online_branch = online_branch[:online_branch.index(": p.models") + len(": p.models")]
    assert "data.models" in online_branch, (
        "branch 'online' de handleTestProvider não referencia mais data.models"
    )
    assert online_branch.rstrip().endswith(": p.models"), (
        "handleTestProvider precisa manter p.models só no branch de ping SEM sucesso (offline)"
    )
