"""Phoenix Document Pipeline V2 - Fase 5: Record Segmenter.

PHX-NEW (2026-08-29, especificação fechada pelo usuário depois da Fase 4):
agrupa `Block`s (Fase 2) + `Candidate`s (Fase 4) que parecem pertencer à
MESMA entidade lógica (um produto, na maioria dos documentos reais vistos
até agora) num `Record` (Fase 1).

Regra central pedida explicitamente pelo usuário, respeitada à risca
aqui: o Segmenter SÓ AGRUPA. Ele nunca:
  - valida ou "corrige" um `Candidate` (um EAN com `valid=False` continua
    exatamente como veio - a decisão sobre o que fazer com isso é da
    Evidence/Validation, Fase 6+, nunca daqui);
  - classifica a entidade de verdade (`kind` continua `UNKNOWN` sempre -
    decidir "isso é um produto" é responsabilidade de outra fase);
  - chama LLM, OCR ou qualquer coisa fora de Python puro determinístico/
    heurístico (nível 1 e 2 da escala fechada nas rodadas anteriores -
    nível 3, LLM, fica pra quando este nível 1+2 não bastar, e não está
    implementado ainda de propósito).

Sinais usados nesta primeira versão (documentados explicitamente - nem
todos os sinais que o usuário listou como possíveis estão implementados
ainda, ver limitações no fim do docstring):
  - Presença de um CANDIDATO DE IDENTIFICADOR FORTE (EAN/NCM/CEST/preço) -
    o sinal mais confiável de "aqui começa/está o dado de um item".
  - Um parágrafo/heading que PARECE TÍTULO (numeração "1. Nome...", ou
    começa com emoji, ou é o próprio `BlockType.HEADING`) fecha o record
    em andamento (se ele já tiver algum identificador forte) e abre um
    novo - mesmo sem precisar do padrão específico de nenhum documento
    (`[DADOS ESTRUTURADOS PARA O ERP]` não é usado aqui de propósito,
    exatamente pra não virar uma regra MarketUP-específica).
  - Reaparecimento de um identificador forte enquanto o record atual JÁ
    tem um - sinal de que começou um item novo mesmo sem título explícito
    entre eles (cobre o padrão real visto no documento do usuário: vários
    blocos "[DADOS ESTRUTURADOS PARA O ERP] NCM:... Preço:..." em
    sequência, sem nenhuma linha de título separando um do outro).

PHX-FIX-2 (2026-08-29, achado testando o MESMO segundo documento real
depois de já ter corrigido o primeiro bug acima): mesmo com o título
sempre fechando o record, sobrou um segundo caso real com 487 blocos
grudados num record só (`r0215`, começando no produto real "94. Batata
Pringles..."). Causa: depois que um record já tem um identificador forte
(`acc.has_strong_identifier=True`), se NENHUM bloco seguinte for
título-like nem trouxer outro identificador forte por um trecho MUITO
longo (o documento tem blocos de comentário/relacionamento entre
produtos que não batem em nenhuma das duas regras de fronteira), o
record nunca fecha sozinho - ele fica esperando um sinal que só chega
dezenas ou centenas de blocos depois, e absorve tudo no meio. Fechar
sempre que o record atual "está em silêncio" há muito tempo é a
salvaguarda que faltava: um contador (`blocks_since_signal`) zera toda
vez que aparece um sinal (título OU identificador forte) e, se passar de
`_MAX_BLOCKS_WITHOUT_SIGNAL` blocos seguidos sem nenhum sinal DENTRO de
um record que já tinha identificador forte, força o fechamento antes de
continuar acumulando. Isso é deliberadamente um "cinto de segurança", não
uma tentativa de entender o conteúdo do trecho de silêncio - o trecho
"órfão" vira um record de baixa confiança isolado (o mesmo trade-off já
aceito no PHX-FIX anterior: separar demais é sempre mais seguro que
misturar contexto de itens diferentes).

Limitações desta primeira versão, documentadas de propósito:
  - Imagem "próxima" de um record NÃO é usada como sinal ainda (uma
    imagem não produz nenhum Candidate hoje - ver Fase 4 - então ela só
    é absorvida pelo grupo em que cai pela ordem, sem peso próprio na
    decisão de fronteira). Vale revisar quando a Fase 12 existir.
  - Uma TABELA com identificador forte segue a MESMA regra de qualquer
    outro bloco (fecha o record atual se ele já tinha identificador) -
    não tem tratamento especial só por ser tabela.
  - `_MAX_BLOCKS_WITHOUT_SIGNAL` (40) é um limiar arbitrário, documentado
    como tal - não veio de nenhuma medição estatística, só da observação
    de que 487 é claramente patológico e produtos reais nos dois
    documentos de teste nunca precisaram de mais de ~10-15 blocos entre
    um identificador forte e outro. Deve ser reavaliado se aparecer um
    documento real onde um produto legítimo tenha uma descrição mais
    longa que isso sem repetir nenhum campo.
  - Não há fallback de LLM pra caso ambíguo ainda (nível 3 da escala) -
    um documento sem NENHUM sinal estrutural/heurístico reconhecível
    simplesmente vira um único Record (ou nenhum, se não houver
    candidato algum) - aceitável pra esta fase, que é só a base
    determinística de que as fases seguintes precisam.
  - `confidence` é uma heurística simples (mais identificadores fortes e
    válidos = mais confiança), não uma probabilidade calibrada."""
from __future__ import annotations

import re
from dataclasses import dataclass

from phoenix_kernel.documents.candidate_engine import PRICE_FIELD_TYPES
from phoenix_kernel.documents.normalized import Block, BlockType, Candidate, NormalizedDocument, Record

# PHX-FIX (2026-08-29, mesmo achado real que motivou o PHX-FIX em
# candidate_engine.py): "price_min"/"price_max" (Fase 4) são tão fortes
# quanto o "price" genérico pra decidir fronteira - por isso entram todos
# aqui via `PRICE_FIELD_TYPES`. Ver `_strong_family` abaixo pra saber por
# que eles NÃO contam como 2 identificadores distintos em
# `_estimate_confidence`.
_STRONG_IDENTIFIER_FIELDS = {"ean", "ncm", "cest"} | PRICE_FIELD_TYPES


def _strong_family(field_type: str) -> str:
    """price_min/price_max continuam contando como UM SÓ tipo de
    identificador forte ("price") pra fins de confiança - um record com
    "Preço Mínimo" + "Preço Máximo" não é mais confiável que um record
    com um "Preço:" genérico só; são a mesma informação (preço), só
    partida em duas ocorrências de texto."""
    return "price" if field_type in PRICE_FIELD_TYPES else field_type

# "1. Nome do produto", "2) Outro nome" ou uma linha começando com emoji -
# sinais de título/seção BEM genéricos, nunca amarrados a um documento
# específico (ver docstring acima sobre não usar "[DADOS ESTRUTURADOS
# PARA O ERP]" como regra).
_TITLE_LIKE_RE = re.compile(
    r"^\s*(?:\d+[.)]\s+\S|[\U0001F300-\U0001FAFF☀-➿])"
)
_TITLE_MAX_LENGTH = 120

# PHX-FIX-2: ver docstring do módulo - limiar arbitrário e documentado
# pra forçar o fechamento de um record que ficou "em silêncio" (sem
# título e sem identificador forte) por blocos demais seguidos.
_MAX_BLOCKS_WITHOUT_SIGNAL = 40


def _is_title_like(block: Block) -> bool:
    if block.type == BlockType.HEADING:
        return True
    if block.type != BlockType.PARAGRAPH:
        return False
    text = (block.text_raw or "").strip()
    if not text or len(text) > _TITLE_MAX_LENGTH:
        return False
    return bool(_TITLE_LIKE_RE.match(text))


def _estimate_confidence(candidates: list[Candidate]) -> float:
    """Heurística simples e documentada, não uma probabilidade
    calibrada: um record sem NENHUM identificador forte (pode ser um
    resto de texto solto antes do primeiro item de verdade) começa baixo;
    cada identificador forte VÁLIDO distinto encontrado (ean/ncm/cest/
    price) soma confiança, até um teto de 0.95 (nunca 1.0 absoluto -
    "agrupamento" nunca é certeza total nesta fase)."""
    strong_types_valid = {
        _strong_family(c.field_type) for c in candidates
        if c.field_type in _STRONG_IDENTIFIER_FIELDS and c.valid
    }
    if not strong_types_valid:
        return 0.2
    return min(0.95, 0.55 + 0.15 * len(strong_types_valid))


@dataclass
class _Accumulator:
    block_ids: list = None
    candidate_ids: list = None
    candidates: list = None
    has_strong_identifier: bool = False

    def __post_init__(self):
        self.block_ids = self.block_ids or []
        self.candidate_ids = self.candidate_ids or []
        self.candidates = self.candidates or []

    def is_empty(self) -> bool:
        return not self.block_ids


def segment_records(document: NormalizedDocument, candidates: list[Candidate]) -> list[Record]:
    """Ponto de entrada principal da Fase 5. `candidates` deve vir de
    `candidate_engine.find_candidates_in_document(document)` (precisa dos
    `Candidate.id` já atribuídos - ver PHX-NEW lá). Devolve os `Record`s
    na ordem em que aparecem no documento; nunca reordena blocos nem
    candidatos."""
    candidates_by_block: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        candidates_by_block.setdefault(candidate.block_id, []).append(candidate)

    blocks_by_id = {block.id: block for block in document.blocks}
    records: list[Record] = []
    acc = _Accumulator()
    # PHX-FIX-2: conta blocos consecutivos, DENTRO do record em
    # andamento, sem nenhum sinal de fronteira (nem título, nem
    # identificador forte). Zera a cada sinal e a cada flush() - ver
    # docstring do módulo.
    blocks_since_signal = 0

    def flush() -> None:
        nonlocal acc
        if acc.is_empty():
            return
        orders = [blocks_by_id[bid].order for bid in acc.block_ids if bid in blocks_by_id]
        records.append(Record(
            record_id=f"r{len(records):04d}",
            block_ids=list(acc.block_ids),
            candidate_ids=list(acc.candidate_ids),
            start_order=min(orders) if orders else None,
            end_order=max(orders) if orders else None,
            confidence=_estimate_confidence(acc.candidates),
            segmentation_method="structural+heuristic",
        ))
        acc = _Accumulator()

    for block in sorted(document.blocks, key=lambda b: b.order):
        block_candidates = candidates_by_block.get(block.id, [])
        has_strong_here = any(c.field_type in _STRONG_IDENTIFIER_FIELDS for c in block_candidates)
        is_title = _is_title_like(block)

        # PHX-FIX (2026-08-29, achado real testando com um segundo
        # documento - "instruções para construção de site de vendas.docx"):
        # a regra original só fechava o record atual quando um TÍTULO
        # aparecia E o record atual JÁ tinha um identificador forte. Isso
        # quebra exatamente no caso que mais importa evitar (pedido
        # explícito do usuário: misturar contexto é pior que perder um
        # candidato): um trecho longo de conversa/meta-comentário SEM
        # nenhum identificador forte (várias dezenas de blocos, ex.
        # "Você disse" / "O Gemini disse" / bullets de estratégia) não
        # fechava o record em andamento - então quando o próximo produto
        # de verdade aparecia (título numerado + dados ERP), ele era
        # ABSORVIDO junto com toda aquela conversa anterior num único
        # record gigante (chegou a juntar ~90 blocos, a maioria pura
        # meta-conversa, com o produto real perdido no meio). A regra
        # corrigida: um bloco TÍTULO SEMPRE fecha o record atual e abre
        # um novo, independente do record atual já ter identificador forte
        # ou não - um trecho de conversa sem nenhum campo vira um record
        # de baixa confiança (0.2) isolado, em vez de contaminar o produto
        # seguinte. Continua batendo nos testes originais (produtos
        # consecutivos com título entre eles, e produtos consecutivos SEM
        # título via `has_strong_here and acc.has_strong_identifier`).
        has_signal_here = is_title or has_strong_here

        # PHX-FIX-2 (ver docstring do módulo): um record - COM ou SEM
        # identificador forte já confirmado - que está "em silêncio" (sem
        # título, sem identificador forte) há `_MAX_BLOCKS_WITHOUT_SIGNAL`
        # blocos seguidos é fechado à força, ANTES de engolir mais um
        # bloco sem sinal nenhum. Achado adicional (mesmo documento real):
        # a primeira versão deste fix só disparava quando
        # `acc.has_strong_identifier` já era True, então um record que
        # NUNCA chegou a ter um identificador forte (ex.: começou num
        # bloco de título "solto" tipo "🚀 Próximos Passos:", sem nenhum
        # NCM/CEST/preço depois) crescia sem limite - chegou a 486 blocos
        # no documento real. O limiar de silêncio vale pra qualquer record
        # em andamento, não só pros que já "acharam algo forte".
        drift_timeout = (
            not has_signal_here
            and not acc.is_empty()
            and blocks_since_signal >= _MAX_BLOCKS_WITHOUT_SIGNAL
        )

        starts_new_record = is_title or (acc.has_strong_identifier and has_strong_here) or drift_timeout
        if starts_new_record:
            flush()
            blocks_since_signal = 0

        if has_signal_here:
            blocks_since_signal = 0
        else:
            blocks_since_signal += 1

        acc.block_ids.append(block.id)
        acc.candidate_ids.extend(c.id for c in block_candidates if c.id)
        acc.candidates.extend(block_candidates)
        if has_strong_here:
            acc.has_strong_identifier = True

    flush()
    return records
