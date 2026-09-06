"""Testes: limite de caracteres do RAG Free — duas rodadas de correção,
mesma investigação:

RODADA 1 (500.000 -> 2.500.000): achado real do usuário, com análise
técnica detalhada trazida por ele (conversa com ChatGPT anexada):
500.000 caracteres extraídos era baixo demais pro próprio limite de 25MB
já anunciado - um .docx de menos de 1MB no disco (formato ZIP/XML
comprimido) facilmente ultrapassa 500 mil caracteres. Testado com 4
arquivos REAIS do usuário:

    instruçoes para construção de site de vendas(1).docx  0.454 MB  719.655 caracteres
    Conversa com o Gemini 2.0.docx                         0.341 MB  431.566 caracteres
    Conversa com o Gemini(2).docx                          0.952 MB  1.148.465 caracteres
    flux com comfyui.md                                    0.748 MB  743.393 caracteres

RODADA 2 (2.500.000 -> 150.000.000): usuário testou em produção com o
limite da rodada 1 já no ar (print de tela real do painel de estado,
"9/10 documentos... INTEGRIDADE OK") e encontrou um documento de
7.054.990 caracteres, ainda rejeitado pela mensagem 422 (já corrigida na
rodada 1 - "Documento excede o limite do plano: 7.054.990 caracteres
extraídos; máximo permitido: 2.500.000"). Pediu um número com muito mais
margem - decisão explícita dele, não derivada de um cálculo específico:
150.000.000 no Free, e "o triplo ou quádruplo" no Pro (escolhido o
quádruplo, 600.000.000, o topo da faixa que ele mencionou).

Segundo achado, mesma investigação original: `validate_product_limits()`
sempre levantou um ValueError claro e específico, mas nada em
`/api/rag/add-file` capturava esse erro - o FastAPI tratava como exceção
não prevista e devolvia 500 Internal Server Error genérico, escondendo a
mensagem específica que já existia. (`/api/rag/add`, a rota irmã, tinha
uma variante mais sutil do mesmo bug - já capturava ValueError mas ainda
devolvia 500.) Essa parte não mudou na rodada 2 - só o número do limite.
"""
from phoenix_kernel.licensing.commercial_guard import FREE_RAG_LIMITS, PRO_RAG_LIMITS
from phoenix_kernel.licensing.plans import RAG_PLAN_LIMITS
from phoenix_kernel.intelligence.chroma_rag_backend import ChromaRagBackend


def test_free_plan_character_limit_is_150_million():
    assert FREE_RAG_LIMITS.max_extracted_chars == 150_000_000


def test_free_plan_other_limits_unchanged():
    """Regressão: só o limite de caracteres mudou (nas duas rodadas) -
    documentos (10) e tamanho de arquivo (25MB) continuam os mesmos, o
    achado do usuário era especificamente sobre o limite de caracteres."""
    assert FREE_RAG_LIMITS.max_documents == 10
    assert FREE_RAG_LIMITS.max_upload_bytes == 25 * 1024 * 1024


def test_pro_plan_character_limit_is_4x_free():
    """Pedido explícito do usuário: Pro = "triplo ou quádruplo" do Free -
    escolhido o quádruplo (topo da faixa mencionada)."""
    assert PRO_RAG_LIMITS.max_extracted_chars == 600_000_000
    assert PRO_RAG_LIMITS.max_extracted_chars == FREE_RAG_LIMITS.max_extracted_chars * 4


def test_legacy_plans_constant_stays_in_sync_with_real_source_of_truth():
    """A cópia legada em plans.py (mantida só por compatibilidade de
    import, não decide o limite aplicado de verdade - ver
    commercial_guard.rag_limits()) precisa continuar espelhando o valor
    real, senão recria a mesma confusão de 'duas fontes de verdade
    discordantes' já corrigida antes nesta auditoria."""
    assert RAG_PLAN_LIMITS["free"]["max_characters"] == FREE_RAG_LIMITS.max_extracted_chars
    assert RAG_PLAN_LIMITS["pro"]["max_characters"] == PRO_RAG_LIMITS.max_extracted_chars


def test_real_user_documents_from_round_1_still_fit():
    """Confirma com os números REAIS dos 4 arquivos que motivaram a
    rodada 1 - continuam cabendo folgadamente no novo limite, ainda
    maior, da rodada 2."""
    caracteres_reais = [719_655, 431_566, 1_148_465, 743_393]
    for chars in caracteres_reais:
        assert chars <= FREE_RAG_LIMITS.max_extracted_chars


def test_real_document_from_round_2_screenshot_now_fits():
    """O documento REAL de 7.054.990 caracteres que o usuário testou em
    produção (print de tela, rejeitado pelo limite da rodada 1) precisa
    caber confortavelmente no novo limite da rodada 2."""
    assert 7_054_990 <= FREE_RAG_LIMITS.max_extracted_chars
    # com folga real, não só "cabe por pouco"
    assert FREE_RAG_LIMITS.max_extracted_chars >= 7_054_990 * 10


def _make_backend_for_limit_check(existing_chars: int = 0) -> ChromaRagBackend:
    # validate_product_limits() agora checa o ORÇAMENTO AGREGADO (soma de
    # todos os documentos autorizados), não mais um teto por documento
    # isolado - precisa mockar _authorized_user_ids()/_raw_manual_documents()
    # (usados por total_extracted_characters()) e _user_registry.load()
    # (usado por _extracted_characters_for(), pro caso de reindex).
    backend = object.__new__(ChromaRagBackend)
    if existing_chars > 0:
        backend._authorized_user_ids = lambda: {"manual::existente"}
        backend._raw_manual_documents = lambda: [{"id": "manual::existente", "title": "já indexado"}]

        class _FakeRegistryState:
            valid = True
            documents = {"manual::existente": {"extracted_characters": existing_chars}}

        backend._user_registry = type("R", (), {"load": staticmethod(lambda: _FakeRegistryState())})()
    else:
        backend._authorized_user_ids = lambda: set()
        backend._raw_manual_documents = lambda: []
        backend._user_registry = type("R", (), {"load": staticmethod(lambda: type("S", (), {"valid": True, "documents": {}})())})()
    return backend


def test_document_within_new_limit_does_not_raise():
    backend = _make_backend_for_limit_check()
    conteudo = "x" * 7_054_990  # o próprio documento real do print de tela
    # não deve levantar nada - repositório vazio, documento cabe
    # confortavelmente no orçamento agregado (150M)
    backend.validate_product_limits("doc.docx", conteudo, max_documents=None, max_characters=150_000_000)


def test_document_exceeding_new_limit_still_raises_with_clear_message():
    """A trava continua existindo e funcionando - agora contra o
    ORÇAMENTO AGREGADO do repositório, não mais um teto por documento."""
    backend = _make_backend_for_limit_check()
    conteudo = "x" * 200_000_000  # sozinho já excede o orçamento total (150M)
    try:
        backend.validate_product_limits("doc.docx", conteudo, max_documents=None, max_characters=150_000_000)
        assert False, "deveria ter levantado ValueError"
    except ValueError as e:
        assert "200.000.000" in str(e) or "200,000,000" in str(e)
        assert "150.000.000" in str(e) or "150,000,000" in str(e)


def test_aggregate_budget_considers_existing_documents():
    """O ACHADO CENTRAL desta correção: um documento pequeno pode ser
    rejeitado se o repositório JÁ estiver perto do teto - o limite é do
    conjunto, não de cada arquivo isolado."""
    backend = _make_backend_for_limit_check(existing_chars=149_000_000)  # repositório quase cheio
    conteudo = "x" * 2_000_000  # pequeno sozinho, mas estoura o orçamento restante (1M livre)
    try:
        backend.validate_product_limits("doc_novo.docx", conteudo, max_documents=None, max_characters=150_000_000)
        assert False, "deveria ter levantado ValueError - orçamento agregado excedido"
    except ValueError as e:
        assert "149.000.000" in str(e) or "149,000,000" in str(e), f"deveria mostrar o uso atual: {e}"


def test_api_server_converts_limit_valueerror_to_422_not_500():
    """Verifica o código-fonte real de api_server.py: as DUAS rotas que
    chamam validate_product_limits() (/api/rag/add e /api/rag/add-file)
    precisam converter o ValueError em HTTPException(422), nunca deixar
    propagar cru (o que o FastAPI trataria como 500 genérico).

    Achado real: /api/rag/add-file tinha o bug óbvio (nenhum try/except
    ao redor da chamada). /api/rag/add tinha uma variante mais sutil - JÁ
    capturava ValueError explicitamente, mas ainda devolvia status_code=500
    mesmo assim, perdendo a distinção entre "regra de negócio" e "falha de
    servidor" no último passo. Não mudou entre as rodadas 1 e 2 - só o
    número do limite mudou."""
    src = open("api_server.py", encoding="utf-8").read()

    occurrences = []
    start = 0
    while True:
        idx = src.find("backend.validate_product_limits(", start)
        if idx == -1:
            break
        occurrences.append(idx)
        start = idx + 1
    assert len(occurrences) == 2, (
        f"esperava exatamente 2 chamadas a validate_product_limits() em "
        f"api_server.py (/api/rag/add e /api/rag/add-file), achei {len(occurrences)}"
    )

    for call_start in occurrences:
        window_start = max(0, call_start - 400)
        window_end = min(len(src), call_start + 1400)
        chunk = src[window_start:window_end]

        assert "try:" in chunk, (
            f"chamada em offset {call_start}: precisa estar dentro de um "
            "try/except - sem isso, o ValueError vira 500 genérico"
        )
        assert "except ValueError as e:" in chunk, (
            f"chamada em offset {call_start}: precisa capturar "
            "especificamente ValueError (o tipo que validate_product_limits() levanta)"
        )
        assert "status_code=422" in chunk, (
            f"chamada em offset {call_start}: limite de produto excedido é "
            "uma rejeição de regra de negócio previsível, não falha de "
            "servidor - precisa virar 422, não 500 (mesmo capturando "
            "ValueError explicitamente - achado real: uma das duas rotas "
            "capturava certo mas devolvia o status errado mesmo assim)"
        )
