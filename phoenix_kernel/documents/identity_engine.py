"""Phoenix Document Pipeline V2 - Fase 9: Identity / Merge / Dedup.

PHX-NEW (2026-08-29, especificação fechada pelo usuário depois de aprovar
o CÓDIGO/CONTRATO da Fase 8 - o smoke test com o Qwen real fica pendente,
fora do escopo deste módulo): a pergunta que esta fase responde é "quais
Records (Fase 5) representam a mesma ENTIDADE real, e qual é a visão
consolidada dessa entidade sem perder nenhuma evidência original?".

Regra fundamental pedida explicitamente pelo usuário, e o motivo de
`CanonicalRecord` ser um tipo NOVO em vez de "marcar" um Record como
absorvido: "Nenhum Record original é apagado, alterado ou absorvido
fisicamente. O merge cria uma nova entidade canônica que referencia os
Records de origem." Este módulo NUNCA muta um `Record`/`Candidate`
existente - só LÊ. `Record` continua sendo "o que existia naquele trecho
do documento"; `CanonicalRecord` é "o que a Phoenix concluiu sobre a
entidade real" - dois conceitos diferentes, nunca um substituindo o outro
na estrutura de dados (embora um vá se tornar a fonte da escrita final, na
Fase 10).

Arquitetura (pedida explicitamente pelo usuário):

    Records + Candidates + FieldEvidence
                 v
        Identity / Dedup Engine (blocking -> scoring -> clustering)
                 v
            Record Groups (RecordCluster)
                 v
          Validation + Merge (reaproveita build_field_evidence, Fase 6)
                 v
             CanonicalRecord

Hierarquia de sinais de identidade (pedida explicitamente, nesta ordem de
força):
  1. EAN/GTIN válido IDÊNTICO entre dois records - sinal mais forte
     possível pra "mesmo produto". EAN/GTIN válido DIFERENTE é o BLOQUEIO
     mais forte possível - nunca funde automaticamente mesmo com nome/
     marca/NCM parecidos ("garrafa individual != caixa com 12, e
     normalmente têm GTINs diferentes"). Decidido isoladamente, sem olhar
     pra mais nada - nem NCM nem nome mudam essa decisão.
  2. `pack_count` (unidade vs caixa fechada) - quando um dos dois lados
     detecta explicitamente uma contagem de pacote (ex: "Caixa com 12") e
     elas DIVERGEM, também é tratado como BLOQUEIO, pelo mesmo motivo do
     EAN: sem essa trava, "Produto X 970ml" e "Produto X 970ml Caixa com
     12" teriam nome+peso idênticos e pareceriam duplicatas óbvias, quando
     na prática são unidades comerciais DIFERENTES (documento real do
     usuário já contém esse padrão exato).
  3. NCM IGUAL nunca é sinal de identidade sozinho - NCM identifica classe
     FISCAL, não produto (pedido explícito: "centenas de chocolates podem
     ter o mesmo NCM"). Vale só como reforço FRACO quando já existem
     outros sinais.
  4. fingerprint textual residual (nome/marca aproximados, depois de
     remover o que já virou Candidate estruturado e qualquer quantidade
     solta tipo "350ml") comparado por Jaccard de tokens - NUNCA decide
     merge sozinho ("similaridade textual só deve dizer 'vale investigar',
     nunca 'são iguais'" - pedido explícito). "Pringles Original 165g" vs
     "Pringles Paprika 165g" tem altíssima similaridade textual e são
     produtos DIFERENTES - por isso o peso desse sinal sozinho nunca
     alcança o limiar de `auto_merge`.
  5. quantidade/peso equivalente (reaproveitando a canonicalização
     dimensional já feita na Fase 3/4 - "600g" e "0,600 kg" comparam
     como iguais aqui do mesmo jeito que já comparavam no Evidence
     Engine) - sinal de apoio, nunca autoridade.

Pontuação (pedida explicitamente, PESOS ARBITRÁRIOS E DOCUMENTADOS COMO
TAL - mesmo espírito de todo limiar arbitrário já usado nas fases
anteriores, ex: `_MAX_BLOCKS_WITHOUT_SIGNAL` da Fase 5, `_PROBABLE_MIN_
CONFIDENCE` da Fase 6 - precisam ser calibrados contra os dois documentos
reais, a FILOSOFIA importa mais que os números exatos):
  score >= 90  -> "auto_merge"          (funde de verdade, forma cluster)
  70 <= score < 90 -> "probable_duplicate" (fica só como MergeDecision -
                      auditoria/candidato forte, NUNCA funde sozinho nesta
                      primeira versão)
  40 <= score < 70 -> "possible_duplicate" (idem, candidato mais fraco)
  score < 40   -> "do_not_merge"

QUALQUER sinal de bloqueio (EAN válido diferente, pack_count divergente)
força `do_not_merge` IMEDIATAMENTE, ignorando a pontuação - "sinais
negativos fortes precisam impedir merges perigosos" (pedido explícito).

Só pares com decisão `auto_merge` de fato entram no agrupamento
(`RecordCluster`)/viram `CanonicalRecord` nesta primeira versão -
"probable_duplicate"/"possible_duplicate" ficam disponíveis como
`MergeDecision` pra auditoria/revisão humana ou, no futuro, pra alimentar
o Semantic Resolver (Fase 8) com uma pergunta do tipo "estes dois
registros representam exatamente o mesmo produto comercial?" - NÃO
implementado aqui (Fase 9 é 100% Python, zero LLM, pedido explícito) - só
o "clusters" resultante entra no cano de Merge/`build_field_evidence`.

Reaproveitamento explícito da Fase 6 (pedido explícito - "não criaria uma
segunda lógica de confiança"): `build_canonical_record` reúne TODOS os
`candidate_ids` dos Records de um cluster e chama o MESMO
`evidence_engine.build_field_evidence` já usado desde a Fase 6 - o
dedup por `source_origin_hash` (evidência repetida não vira fonte
independente) continua valendo automaticamente através do merge, sem
nenhuma lógica nova aqui. Um campo onde os Records do cluster divergem
(ex: preços diferentes de fato) vira "conflict" normalmente - identidade
e validade de campo são problemas DIFERENTES (pedido explícito): a
identidade decide QUEM funde, o Evidence Engine decide o QUE cada campo
vale depois de fundido.

Vocabulário de identidade FECHADO, deliberadamente SEPARADO do vocabulário
de `EvidenceStatus` (Fase 6) - pedido explícito, "são conceitos
diferentes": ver `IdentityStatus`.

Escala (pedido explícito, "não comparar todos contra todos"):
`find_candidate_pairs` faz BLOCKING antes de pontuar - um Record com EAN
válido só é comparado com outros do MESMO EAN; sem EAN, cai num bucket por
token de nome residual, e só Records que compartilham pelo menos um
bucket chegam a ser comparados par-a-par. Clusterização usa union-find
sobre as arestas `auto_merge` (nunca merge par-a-par destrutivo em
cadeia - "se A==B e B==C, queremos um cluster [A,B,C]", não "A absorve B
depois A absorve C").

PHX-FIX (2026-08-29, achado real validando esta fase contra os dois
documentos reais - não um bug de lógica, e sim uma simplificação de
escala que só apareceu no documento inteiro, mesmo padrão de descoberta
já visto nas Fases 5/6): o blocking por token de nome sozinho não
aguentava um documento que é uma CONVERSA (não um catálogo limpo) - com
2061 records, palavras comuns na conversa ("para", "técnica", "NCM",
"acabamento"...) viravam buckets de 500+ records cada, e mesmo com
`_MAX_BUCKET_SIZE_FOR_NAME_TOKENS` cortando os maiores, a CAUDA LONGA de
milhares de buckets médios ainda gerava mais de 2 milhões de pares
candidatos - impraticável, e pior: um token genérico compartilhado por
centenas de records também INFLA `_jaccard` entre records que não têm
nada a ver um com o outro (falso positivo de similaridade, não só
lentidão). Corrigido com um filtro de FREQUÊNCIA DE DOCUMENTO
(`_MAX_TOKEN_DOCUMENT_FREQUENCY`, limiar arbitrário e documentado, mesmo
espírito de todo limiar já usado nas fases anteriores): antes de montar
qualquer bucket ou comparar qualquer par, `_compute_corpus_name_tokens`
calcula em QUANTOS records cada token aparece no corpus inteiro e remove
de vez os tokens genéricos demais (aparecem em mais registros que o
limiar) tanto do bucket de blocking quanto do cálculo de Jaccard - um
token só conta como sinal de nome quando é RARO o bastante pra
identificar alguma coisa. Isso também elimina a recomputação repetida de
tokens por record (calculado uma vez só por todo o corpus, não a cada par
comparado). `compare_records`/`_bucket_keys`/`find_candidate_pairs`
continuam aceitando um `name_tokens_by_record` pré-computado opcional -
quando chamados diretamente com só 2 records (ex: nos testes), calculam
o fingerprint na hora, sem filtro de corpus (não faz sentido "frequência
de documento" com um corpus de 2 elementos).

Limitações desta primeira versão, documentadas de propósito:
  - Não existe ainda um `field_type` "sku"/"marca"/"modelo"/"variante"
    estruturado no Candidate Engine (Fase 4) - o fingerprint textual usa
    o texto RESIDUAL dos blocos do record (depois de remover o que já
    virou Candidate estruturado e uma quantidade solta tipo "350ml" via
    regex própria deste módulo, nunca tocando `candidate_engine.py`) como
    aproximação de "nome/marca". Uma lista pequena e arbitrária de
    "stopwords de embalagem" (lata/garrafa/caixa/kit/pack/...) é removida
    do fingerprint pra não competir com o sinal de `pack_count`.
  - `_detect_pack_count`/`_BARE_QUANTITY_RE` são heurísticas de regex
    NOVAS, isoladas neste módulo (nunca em `candidate_engine.py`, que já
    está fechado/aprovado) - poucos padrões testados (Caixa/cx/pack/kit
    seguido de número, "N unidades") - precisam de mais tuning contra os
    documentos reais, mesmo espírito de todo limiar/regex arbitrário já
    documentado nas fases anteriores.
  - Com os pesos atuais, `auto_merge` só é alcançável de verdade via EAN
    válido idêntico (a soma máxima só de fingerprint/peso/NCM não chega
    a 90) - o que torna a relação de equivalência SEMPRE transitiva sem
    contradição na prática (EAN igual é uma igualdade de verdade), então
    o caminho de detecção de `IDENTITY_CONFLICT` (contradição transitiva
    dentro de um cluster) é defensivo/testado isoladamente, mas não
    esperado de disparar com os documentos reais atuais - fica pronto pra
    quando os pesos forem recalibrados e um cluster puder se formar por
    fingerprint sozinho.
  - Zero LLM (pedido explícito) - "probable_duplicate"/"possible_
    duplicate" ficam só como dado de auditoria (`MergeDecision`) nesta
    versão; usar o Semantic Resolver (Fase 8) pra desambiguar esses pares
    fica reservado pra uma fase/iteração futura.
  - `merge_method` em `CanonicalRecord` hoje só existe como "exact_ean"
    (único jeito de alcançar `auto_merge` com os pesos atuais) - o campo
    já existe pronto pra quando outro caminho de auto_merge existir
    (ex: "exact_sku" quando um `field_type` de SKU existir)."""
from __future__ import annotations

from functools import lru_cache

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional

from phoenix_kernel.documents.evidence_engine import FieldEvidence, build_field_evidence
from phoenix_kernel.documents.normalized import Candidate, Record
from phoenix_kernel.documents.normalizer import normalize_number_with_unit


class IdentityStatus(str, Enum):
    """Vocabulário de IDENTIDADE - deliberadamente separado do
    `EvidenceStatus` da Fase 6 (pedido explícito do usuário: "não
    reutilizar confirmed/probable/conflict dos campos... são conceitos
    diferentes"). Descreve o que aconteceu com UM Record na resolução de
    identidade, nunca o valor de um campo."""

    UNIQUE = "unique"
    DUPLICATE_CONFIRMED = "duplicate_confirmed"
    DUPLICATE_PROBABLE = "duplicate_probable"
    DUPLICATE_AMBIGUOUS = "duplicate_ambiguous"
    IDENTITY_CONFLICT = "identity_conflict"


_DECISION_AUTO_MERGE = "auto_merge"
_DECISION_PROBABLE = "probable_duplicate"
_DECISION_POSSIBLE = "possible_duplicate"
_DECISION_DO_NOT_MERGE = "do_not_merge"

# Ver docstring do módulo - limiares e pesos ARBITRÁRIOS e documentados
# como tal, pendentes de calibração contra os dois documentos reais.
_SCORE_AUTO_MERGE = 90
_SCORE_PROBABLE = 70
_SCORE_POSSIBLE = 40

_W_NCM_EQUAL = 5
_W_NAME_STRONG = 45
_W_NAME_MODERATE = 15
_W_WEIGHT_EQUAL = 15
_W_WEIGHT_DIFFERENT = -40
_W_PACK_COUNT_EQUAL = 15

_JACCARD_STRONG = 0.8
_JACCARD_MODERATE = 0.5

# Segurança de escala (ver docstring do módulo, ponto "não comparar todos
# contra todos") - um token de nome comum demais (aparece em centenas de
# records) vira um bucket gigante e caro de comparar par-a-par; acima
# deste tamanho o bucket é ignorado (limiar arbitrário, documentado).
_MAX_BUCKET_SIZE_FOR_NAME_TOKENS = 200

# Ver PHX-FIX no topo do módulo (achado real contra os dois documentos
# reais) - um token que aparece em mais de N records do MESMO corpus é
# genérico demais pra servir de sinal de identidade OU de chave de
# blocking, mesmo que não esteja na lista fixa de `_PACKAGING_STOPWORDS`.
# Limiar arbitrário, documentado como tal, pendente de calibração.
_MAX_TOKEN_DOCUMENT_FREQUENCY = 25

# Palavras de EMBALAGEM/quantidade - removidas do fingerprint de nome de
# propósito, pra não competir com o sinal dedicado de `pack_count` nem
# inflar falsamente a similaridade textual entre produtos genuinamente
# diferentes que só compartilham a forma de embalagem.
_PACKAGING_STOPWORDS = {
    "lata", "garrafa", "pote", "sache", "sachê", "unidade", "unidades",
    "un", "pct", "pacote", "frasco", "caixa", "cx", "kit", "pack",
    "com", "de", "da", "do", "e",
}

_BARE_QUANTITY_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:kg|mg|cm|mm|ml|g|l|m)\b", re.IGNORECASE
)

_PACK_COUNT_PATTERNS = [
    re.compile(r"(?i)\bcaixa\s+(?:com\s+|c/\s*)?(\d{1,4})\b"),
    re.compile(r"(?i)\bcx\.?\s*c\/?\s*(\d{1,4})\b"),
    re.compile(r"(?i)\bpack\s+(?:com\s+|c/\s*)?(\d{1,4})\b"),
    re.compile(r"(?i)\bkit\s+(?:com\s+|c/\s*)?(\d{1,4})\b"),
    re.compile(r"(?i)\b(\d{1,4})\s*unidades\b"),
]


@dataclass
class Signal:
    """Um sinal individual (positivo, negativo ou bloqueador) que entrou
    no cálculo de um `MergeDecision` - pedido explícito do usuário pra
    auditoria ("isso vai ser fantástico pra auditoria da Phoenix")."""

    type: str
    weight: float = 0.0
    detail: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Signal":
        return Signal(**data)


@dataclass
class MergeDecision:
    """Resultado da comparação de UM par de Records - sempre gerado,
    mesmo quando a decisão é `do_not_merge` (auditoria completa, nunca só
    os pares que deram merge)."""

    left_record_id: str
    right_record_id: str
    decision: str
    score: float
    signals: list[Signal] = field(default_factory=list)
    blocking_signals: list[Signal] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "left_record_id": self.left_record_id,
            "right_record_id": self.right_record_id,
            "decision": self.decision,
            "score": self.score,
            "signals": [s.to_dict() for s in self.signals],
            "blocking_signals": [s.to_dict() for s in self.blocking_signals],
        }

    @staticmethod
    def from_dict(data: dict) -> "MergeDecision":
        data = dict(data)
        data["signals"] = [Signal.from_dict(s) for s in data.get("signals", [])]
        data["blocking_signals"] = [Signal.from_dict(s) for s in data.get("blocking_signals", [])]
        return MergeDecision(**data)


@dataclass
class RecordCluster:
    """Um grupo de Records que a Fase 9 concluiu (via `auto_merge`,
    incluindo a transitividade A==B==C -> [A,B,C], nunca merge par-a-par
    destrutivo) que representam a MESMA entidade real."""

    cluster_id: str
    record_ids: list[str]
    identity_confidence: float
    merge_method: str = "exact_ean"

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "RecordCluster":
        return RecordCluster(**data)


@dataclass
class CanonicalRecord:
    """A entidade REAL consolidada - "o que a Phoenix concluiu", nunca
    substitui nem apaga os `Record`s de origem (`source_record_ids` é só
    uma referência, ver PHX-NEW no topo do módulo). `fields` reaproveita
    o MESMO `FieldEvidence` da Fase 6 por campo (nenhuma lógica de
    confiança nova) - `conflicts` é só a lista dos `field_type`s cujo
    `FieldEvidence.status == "conflict"`, derivada de `fields` (nunca uma
    segunda fonte de verdade)."""

    canonical_id: str
    source_record_ids: list[str]
    merge_method: str
    merge_confidence: float
    fields: dict[str, FieldEvidence] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    status: str = "validated"

    def to_dict(self) -> dict:
        return {
            "canonical_id": self.canonical_id,
            "source_record_ids": list(self.source_record_ids),
            "merge_method": self.merge_method,
            "merge_confidence": self.merge_confidence,
            "fields": {ft: fe.to_dict() for ft, fe in self.fields.items()},
            "conflicts": list(self.conflicts),
            "status": self.status,
        }

    @staticmethod
    def from_dict(data: dict) -> "CanonicalRecord":
        data = dict(data)
        data["fields"] = {ft: FieldEvidence.from_dict(fe) for ft, fe in data.get("fields", {}).items()}
        return CanonicalRecord(**data)


@dataclass
class IdentityResolution:
    """Ponto de saída de mais alto nível de `resolve_identity` - reúne
    tudo que a Fase 9 produz sobre um conjunto de Records.

    PHX-FIX (2026-08-29, hotfix pedido pelo usuário - ver
    `_build_singleton_canonical_record`): `canonical_records` cobre TODO
    `record_id` de entrada, não só os que entraram num cluster de
    `auto_merge` - N records de entrada nunca produzem mais que N
    `CanonicalRecord`s de saída, e nenhum `record_id` fica de fora. `clusters`
    continua sendo só os agrupamentos REAIS de `auto_merge` (não inclui os
    singletons) - é a estrutura certa pra quem quer auditar só as decisões
    de merge de verdade, sem se importar com o passthrough de records
    únicos."""

    decisions: list[MergeDecision] = field(default_factory=list)
    clusters: list[RecordCluster] = field(default_factory=list)
    canonical_records: list[CanonicalRecord] = field(default_factory=list)
    identity_status_by_record: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# extração de sinais a partir de um Record
# ---------------------------------------------------------------------------

def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _record_full_text(record: Record, blocks_by_id: dict, _cache: Optional[dict] = None) -> str:
    # PHX-PERF (2026-09-03, passo 2): chamado ~40 mil vezes pros mesmos ~500
    # records (uma vez por par comparado), reconstruindo o mesmo texto ~80x
    # cada. Um cache por record_id (preenchido em build_identity_graph) elimina
    # a repetição — mesma lição do cache de _detect_pack_count. Sem cache, o
    # comportamento é idêntico ao original (compatível com quem chama sem ele).
    if _cache is not None:
        hit = _cache.get(record.record_id)
        if hit is not None:
            return hit
    parts = []
    for block_id in record.block_ids:
        block = blocks_by_id.get(block_id)
        if block is not None and block.text_raw:
            parts.append(block.text_raw)
    text = " ".join(parts)
    if _cache is not None:
        _cache[record.record_id] = text
    return text


def _valid_candidate_value(record: Record, candidates_by_id: dict, field_type: str) -> Optional[str]:
    for candidate_id in record.candidate_ids:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is not None and candidate.field_type == field_type and candidate.valid:
            return candidate.normalized_value
    return None


def _weight_signature(record: Record, candidates_by_id: dict, blocks_by_id: dict) -> Optional[tuple]:
    """Reaproveita a canonicalização dimensional da Fase 3/4 quando já
    existe um Candidate `weight` rotulado ("Peso: ...") no record; sem
    isso, cai pra uma leitura de quantidade SOLTA (ex: "970ml" dentro do
    nome do produto, sem rótulo nenhum) via `_BARE_QUANTITY_RE` - nova
    aqui, nunca em `candidate_engine.py` (Fase 4 já fechada)."""
    for candidate_id in record.candidate_ids:
        candidate = candidates_by_id.get(candidate_id)
        if (
            candidate is not None and candidate.field_type == "weight" and candidate.valid
            and candidate.normalized_value is not None and candidate.unit
        ):
            return (round(float(candidate.normalized_value), 6), candidate.unit)

    text = _record_full_text(record, blocks_by_id)
    match = _BARE_QUANTITY_RE.search(text)
    if not match:
        return None
    result = normalize_number_with_unit(match.group(0))
    if not result.valid or result.unit is None or result.normalized is None:
        return None
    return (round(float(result.normalized), 6), result.unit)


@lru_cache(maxsize=8192)
def _detect_pack_count(text: str) -> Optional[int]:
    # PHX-PERF (2026-09-03): função PURA de texto — mesmo texto sempre
    # devolve o mesmo resultado. compare_records a chamava por-par, então os
    # mesmos ~500 textos eram reprocessados ~160 mil vezes (87% do tempo do
    # identity em re.search). O cache elimina a repetição sem mudar nenhuma
    # saída (os 204 testes continuam idênticos).
    for pattern in _PACK_COUNT_PATTERNS:
        match = pattern.search(text)
        if match:
            try:
                count = int(match.group(1))
            except ValueError:
                continue
            if count >= 2:
                return count
    return None


def _raw_name_tokens(record: Record, candidates_by_id: dict, blocks_by_id: dict) -> set:
    """Fingerprint de nome de UM record, sem nenhum conhecimento do
    resto do corpus - ver `_compute_corpus_name_tokens` pro filtro de
    frequência de documento que remove tokens genéricos demais quando um
    corpus inteiro está disponível (PHX-FIX no topo do módulo)."""
    text = _record_full_text(record, blocks_by_id)
    for candidate_id in record.candidate_ids:
        candidate = candidates_by_id.get(candidate_id)
        if candidate is not None and candidate.raw_value:
            text = text.replace(candidate.raw_value, " ")
    text = _BARE_QUANTITY_RE.sub(" ", text)
    text = _strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)

    tokens = set()
    for token in text.split():
        if token.isdigit() or len(token) <= 2 or token in _PACKAGING_STOPWORDS:
            continue
        tokens.add(token)
    return tokens


def _compute_corpus_name_tokens(records: list[Record], candidates_by_id: dict, blocks_by_id: dict) -> dict:
    """PHX-FIX (ver topo do módulo): calcula o fingerprint de nome de
    TODO o corpus de uma vez (nunca recomputado por par comparado -
    achado real de performance) e remove tokens que aparecem em mais de
    `_MAX_TOKEN_DOCUMENT_FREQUENCY` records - genéricos demais pra
    identificar qualquer coisa, tanto pra blocking quanto pra Jaccard."""
    raw_by_record = {r.record_id: _raw_name_tokens(r, candidates_by_id, blocks_by_id) for r in records}
    document_frequency: Counter = Counter()
    for tokens in raw_by_record.values():
        document_frequency.update(tokens)
    common_tokens = {token for token, count in document_frequency.items() if count > _MAX_TOKEN_DOCUMENT_FREQUENCY}
    return {record_id: (tokens - common_tokens) for record_id, tokens in raw_by_record.items()}


def _name_tokens_for(
    record: Record, candidates_by_id: dict, blocks_by_id: dict, name_tokens_by_record: Optional[dict] = None
) -> set:
    if name_tokens_by_record is not None:
        return name_tokens_by_record.get(record.record_id, set())
    return _raw_name_tokens(record, candidates_by_id, blocks_by_id)


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


# ---------------------------------------------------------------------------
# comparação par-a-par
# ---------------------------------------------------------------------------

def compare_records(
    record_a: Record, record_b: Record, candidates_by_id: dict, blocks_by_id: dict,
    name_tokens_by_record: Optional[dict] = None,
    _text_cache: Optional[dict] = None,
) -> MergeDecision:
    """Compara DOIS Records e devolve uma `MergeDecision` - sempre
    devolve algo (nunca `None`), mesmo quando a decisão é `do_not_merge`,
    pra manter a auditoria completa (pedido explícito)."""
    ean_a = _valid_candidate_value(record_a, candidates_by_id, "ean")
    ean_b = _valid_candidate_value(record_b, candidates_by_id, "ean")

    if ean_a and ean_b:
        if ean_a == ean_b:
            signal = Signal(type="ean_equal_valid", weight=100, detail=ean_a)
            return MergeDecision(
                left_record_id=record_a.record_id, right_record_id=record_b.record_id,
                decision=_DECISION_AUTO_MERGE, score=100, signals=[signal],
            )
        blocking = Signal(type="different_valid_ean", detail=f"{ean_a} != {ean_b}")
        return MergeDecision(
            left_record_id=record_a.record_id, right_record_id=record_b.record_id,
            decision=_DECISION_DO_NOT_MERGE, score=0, blocking_signals=[blocking],
        )

    text_a = _record_full_text(record_a, blocks_by_id, _text_cache)
    text_b = _record_full_text(record_b, blocks_by_id, _text_cache)
    pack_a = _detect_pack_count(text_a)
    pack_b = _detect_pack_count(text_b)
    if pack_a is not None or pack_b is not None:
        effective_a = pack_a if pack_a is not None else 1
        effective_b = pack_b if pack_b is not None else 1
        if effective_a != effective_b:
            blocking = Signal(
                type="different_pack_count", detail=f"{effective_a} != {effective_b} (unidade vs pack/caixa)"
            )
            return MergeDecision(
                left_record_id=record_a.record_id, right_record_id=record_b.record_id,
                decision=_DECISION_DO_NOT_MERGE, score=0, blocking_signals=[blocking],
            )

    signals: list[Signal] = []
    score = 0.0

    ncm_a = _valid_candidate_value(record_a, candidates_by_id, "ncm")
    ncm_b = _valid_candidate_value(record_b, candidates_by_id, "ncm")
    if ncm_a and ncm_b and ncm_a == ncm_b:
        score += _W_NCM_EQUAL
        signals.append(Signal(type="ncm_equal", weight=_W_NCM_EQUAL, detail=ncm_a))

    tokens_a = _name_tokens_for(record_a, candidates_by_id, blocks_by_id, name_tokens_by_record)
    tokens_b = _name_tokens_for(record_b, candidates_by_id, blocks_by_id, name_tokens_by_record)
    similarity = _jaccard(tokens_a, tokens_b)
    if similarity >= _JACCARD_STRONG:
        score += _W_NAME_STRONG
        signals.append(Signal(type="name_similarity_strong", weight=_W_NAME_STRONG, detail=f"jaccard={similarity:.2f}"))
    elif similarity >= _JACCARD_MODERATE:
        score += _W_NAME_MODERATE
        signals.append(Signal(type="name_similarity_moderate", weight=_W_NAME_MODERATE, detail=f"jaccard={similarity:.2f}"))

    weight_a = _weight_signature(record_a, candidates_by_id, blocks_by_id)
    weight_b = _weight_signature(record_b, candidates_by_id, blocks_by_id)
    if weight_a is not None and weight_b is not None:
        if weight_a == weight_b:
            score += _W_WEIGHT_EQUAL
            signals.append(Signal(type="weight_equal", weight=_W_WEIGHT_EQUAL, detail=str(weight_a)))
        else:
            score += _W_WEIGHT_DIFFERENT
            signals.append(Signal(type="weight_different", weight=_W_WEIGHT_DIFFERENT, detail=f"{weight_a} != {weight_b}"))

    if pack_a is not None and pack_b is not None and pack_a == pack_b:
        score += _W_PACK_COUNT_EQUAL
        signals.append(Signal(type="pack_count_equal", weight=_W_PACK_COUNT_EQUAL, detail=str(pack_a)))

    if score >= _SCORE_AUTO_MERGE:
        decision = _DECISION_AUTO_MERGE
    elif score >= _SCORE_PROBABLE:
        decision = _DECISION_PROBABLE
    elif score >= _SCORE_POSSIBLE:
        decision = _DECISION_POSSIBLE
    else:
        decision = _DECISION_DO_NOT_MERGE

    return MergeDecision(
        left_record_id=record_a.record_id, right_record_id=record_b.record_id,
        decision=decision, score=score, signals=signals,
    )


# ---------------------------------------------------------------------------
# blocking / escala
# ---------------------------------------------------------------------------

def _bucket_keys(
    record: Record, candidates_by_id: dict, blocks_by_id: dict, name_tokens_by_record: Optional[dict] = None
) -> set:
    ean = _valid_candidate_value(record, candidates_by_id, "ean")
    if ean:
        return {("ean", ean)}
    tokens = _name_tokens_for(record, candidates_by_id, blocks_by_id, name_tokens_by_record)
    return {("name_token", token) for token in tokens}


def find_candidate_pairs(
    records: list[Record], candidates_by_id: dict, blocks_by_id: dict, name_tokens_by_record: Optional[dict] = None
) -> list:
    """BLOCKING (pedido explícito, "não comparar todos contra todos"): só
    gera pares de Records que compartilham pelo menos um bucket (mesmo
    EAN, ou pelo menos um token de nome residual em comum, já filtrado
    por frequência de documento - ver PHX-FIX no topo do módulo) - nunca
    o produto cartesiano completo."""
    buckets: dict = {}
    for record in records:
        for key in _bucket_keys(record, candidates_by_id, blocks_by_id, name_tokens_by_record):
            buckets.setdefault(key, []).append(record.record_id)

    pairs = set()
    for key, ids in buckets.items():
        if len(ids) < 2:
            continue
        if key[0] == "name_token" and len(ids) > _MAX_BUCKET_SIZE_FOR_NAME_TOKENS:
            continue  # token comum demais - ver docstring do módulo
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                pairs.add(tuple(sorted((ids[i], ids[j]))))
    return sorted(pairs)


# ---------------------------------------------------------------------------
# clusterização (union-find sobre arestas auto_merge)
# ---------------------------------------------------------------------------

def build_identity_graph(records: list[Record], candidates_by_id: dict, blocks_by_id: dict):
    """Devolve `(decisions, clusters, conflicted_record_ids)`.
    `decisions` é a auditoria COMPLETA (todo par comparado, qualquer
    decisão). `clusters` só agrupa arestas `auto_merge`, via union-find
    (transitividade correta: A==B==C vira UM cluster [A,B,C], nunca merge
    par-a-par destrutivo). Se uma contradição transitiva aparecer dentro
    de um cluster proposto (dois membros do MESMO cluster têm entre si um
    sinal de BLOQUEIO - ver docstring do módulo sobre por que isso não é
    esperado com os pesos atuais, mas é verificado mesmo assim), o cluster
    inteiro é REJEITADO por segurança - os records envolvidos voltam pra
    `conflicted_record_ids` em vez de formar um `CanonicalRecord`
    potencialmente errado."""
    records_by_id = {r.record_id: r for r in records}
    # PHX-FIX (ver topo do módulo): calcula o fingerprint de nome de TODO
    # o corpus UMA VEZ só, já filtrado por frequência de documento - nunca
    # recomputado por par comparado.
    name_tokens_by_record = _compute_corpus_name_tokens(records, candidates_by_id, blocks_by_id)
    pairs = find_candidate_pairs(records, candidates_by_id, blocks_by_id, name_tokens_by_record)

    decisions: list[MergeDecision] = []
    decisions_by_pair: dict = {}
    parent = {r.record_id: r.record_id for r in records}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        root_x, root_y = find(x), find(y)
        if root_x != root_y:
            parent[root_x] = root_y

    # PHX-PERF (passo 2): cache de texto por record_id, compartilhado entre
    # todos os pares — _record_full_text deixa de reconstruir o mesmo texto
    # ~80x por record.
    _text_cache: dict = {}
    for left_id, right_id in pairs:
        decision = compare_records(
            records_by_id[left_id], records_by_id[right_id], candidates_by_id,
            blocks_by_id, name_tokens_by_record, _text_cache
        )
        decisions.append(decision)
        decisions_by_pair[(left_id, right_id)] = decision
        if decision.decision == _DECISION_AUTO_MERGE:
            union(left_id, right_id)

    groups: dict = {}
    for record in records:
        groups.setdefault(find(record.record_id), []).append(record.record_id)

    clusters: list[RecordCluster] = []
    conflicted_record_ids: list[str] = []
    for root, member_ids in sorted(groups.items()):
        if len(member_ids) < 2:
            continue
        member_ids = sorted(member_ids)
        pairwise_scores = []
        pairwise_signal_types = []
        has_conflict = False
        for i in range(len(member_ids)):
            for j in range(i + 1, len(member_ids)):
                pair = (member_ids[i], member_ids[j])
                decision = decisions_by_pair.get(pair)
                if decision is None:
                    continue  # par nunca comparado diretamente (ok, ligados por transitividade)
                if decision.blocking_signals:
                    has_conflict = True
                pairwise_scores.append(decision.score)
                pairwise_signal_types.extend(s.type for s in decision.signals)

        if has_conflict:
            conflicted_record_ids.extend(member_ids)
            continue

        identity_confidence = min(pairwise_scores) / 100 if pairwise_scores else 0.0
        merge_method = "exact_ean" if "ean_equal_valid" in pairwise_signal_types else "fingerprint_score"
        clusters.append(RecordCluster(
            cluster_id=f"cluster_{len(clusters):04d}", record_ids=member_ids,
            identity_confidence=round(identity_confidence, 4), merge_method=merge_method,
        ))

    return decisions, clusters, conflicted_record_ids


# ---------------------------------------------------------------------------
# merge - reaproveita a Fase 6 integralmente
# ---------------------------------------------------------------------------

def build_canonical_record(
    cluster: RecordCluster, records_by_id: dict, candidates_by_id: dict, blocks_by_id: dict,
) -> CanonicalRecord:
    """Reúne os `candidate_ids` de TODOS os Records do cluster e chama o
    MESMO `evidence_engine.build_field_evidence` da Fase 6 - nenhuma
    lógica de confiança nova (pedido explícito). NUNCA muta nenhum
    `Record` original - só lê `record.candidate_ids`, cria um `Record`
    temporário (id = o próprio `cluster.cluster_id`) só pra reaproveitar a
    assinatura já existente de `build_field_evidence`."""
    merged_candidate_ids: list[str] = []
    for record_id in cluster.record_ids:
        record = records_by_id[record_id]
        merged_candidate_ids.extend(record.candidate_ids)

    merged_record = Record(record_id=cluster.cluster_id, candidate_ids=merged_candidate_ids)
    field_evidences = build_field_evidence(merged_record, candidates_by_id, blocks_by_id)
    fields = {fe.field_type: fe for fe in field_evidences}
    conflicts = [field_type for field_type, fe in fields.items() if fe.status == "conflict"]

    return CanonicalRecord(
        canonical_id=f"cr_{cluster.cluster_id}",
        source_record_ids=list(cluster.record_ids),
        merge_method=cluster.merge_method,
        merge_confidence=cluster.identity_confidence,
        fields=fields,
        conflicts=conflicts,
        status="validated",
    )


# ---------------------------------------------------------------------------
# ponto de entrada de mais alto nível
# ---------------------------------------------------------------------------

def _build_singleton_canonical_record(
    record: Record, candidates_by_id: dict, blocks_by_id: dict,
) -> CanonicalRecord:
    """PHX-FIX (2026-08-29, hotfix pedido pelo usuário depois de validar a
    Fase 10 contra o XLSX real do MarketUP): ANTES desta correção,
    `resolve_identity` só materializava um `CanonicalRecord` por cluster
    de `auto_merge` - quem consumisse a Fase 9 (o script de validação da
    Fase 10, e qualquer fase futura) tinha que "adivinhar" que um record
    sem duplicata precisava virar um `CanonicalRecord` singleton por conta
    própria, vazando um detalhe interno da Fase 9 pra fora. Contrato
    correto, nas palavras dele: "`Record` é ocorrência documental.
    `CanonicalRecord` é entidade pronta para consumo pelas fases
    posteriores" - `resolve_identity` agora GARANTE que todo `record_id`
    de entrada aparece em EXATAMENTE UM `CanonicalRecord` de saída, seja
    um singleton (este helper) ou um consolidado (`build_canonical_record`
    com um cluster real).

    Reaproveita o PRÓPRIO `build_canonical_record` com um `RecordCluster`
    de 1 membro só, em vez de duplicar lógica de agregação -
    `merge_method="single_record"` deixa explícito que isto NÃO é uma
    decisão de merge (não existe segundo record concorrendo), é só o
    mesmo record encapsulado no tipo de saída da fase. `canonical_id`
    resultante é `f"cr_{record.record_id}"` (ex: record "r0001" vira
    "cr_r0001") - estável e prevísivel, mesmo formato que um cluster real
    geraria."""
    singleton_cluster = RecordCluster(
        cluster_id=record.record_id,
        record_ids=[record.record_id],
        identity_confidence=1.0,
        merge_method="single_record",
    )
    return build_canonical_record(
        singleton_cluster, {record.record_id: record}, candidates_by_id, blocks_by_id,
    )


def resolve_identity(records: list[Record], candidates_by_id: dict, blocks_by_id: dict) -> IdentityResolution:
    """Ponto de entrada principal da Fase 9: roda blocking+scoring+
    clustering e materializa um `CanonicalRecord` para CADA record de
    entrada - um consolidado por cluster de `auto_merge`, um singleton
    (ver `_build_singleton_canonical_record`, PHX-FIX acima) para todo
    record que não faz parte de nenhum cluster (inclusive os que ficaram
    de fora de um cluster REJEITADO por `IDENTITY_CONFLICT` - a rejeição
    já aconteceu por segurança dentro de `build_identity_graph`, então
    esses records seguem como registros independentes, nunca desaparecem).
    `canonical_records` sai na mesma ordem relativa de `records` de
    entrada (cada cluster aparece na posição do seu primeiro membro
    encontrado, sem repetir). Também calcula o `IdentityStatus` de CADA
    record de entrada (inclusive os que não participam de nenhum cluster -
    ficam `unique`, a menos que apareçam em algum `MergeDecision` mais
    fraco)."""
    decisions, clusters, conflicted_record_ids = build_identity_graph(records, candidates_by_id, blocks_by_id)
    records_by_id = {r.record_id: r for r in records}

    cluster_by_record_id: dict[str, RecordCluster] = {}
    for cluster in clusters:
        for record_id in cluster.record_ids:
            cluster_by_record_id[record_id] = cluster

    canonical_records: list[CanonicalRecord] = []
    emitted_cluster_ids: set = set()
    for record in records:
        cluster = cluster_by_record_id.get(record.record_id)
        if cluster is not None:
            if cluster.cluster_id in emitted_cluster_ids:
                continue  # este cluster já virou CanonicalRecord por outro membro
            emitted_cluster_ids.add(cluster.cluster_id)
            canonical_records.append(
                build_canonical_record(cluster, records_by_id, candidates_by_id, blocks_by_id)
            )
        else:
            canonical_records.append(
                _build_singleton_canonical_record(record, candidates_by_id, blocks_by_id)
            )

    identity_status_by_record: dict[str, str] = {r.record_id: IdentityStatus.UNIQUE.value for r in records}

    weaker_decision_by_record: dict[str, str] = {}
    for decision in decisions:
        for record_id in (decision.left_record_id, decision.right_record_id):
            if decision.decision == _DECISION_PROBABLE:
                weaker_decision_by_record[record_id] = IdentityStatus.DUPLICATE_PROBABLE.value
            elif decision.decision == _DECISION_POSSIBLE and record_id not in weaker_decision_by_record:
                weaker_decision_by_record[record_id] = IdentityStatus.DUPLICATE_AMBIGUOUS.value
    identity_status_by_record.update(weaker_decision_by_record)

    for cluster in clusters:
        for record_id in cluster.record_ids:
            identity_status_by_record[record_id] = IdentityStatus.DUPLICATE_CONFIRMED.value

    for record_id in conflicted_record_ids:
        identity_status_by_record[record_id] = IdentityStatus.IDENTITY_CONFLICT.value

    return IdentityResolution(
        decisions=decisions, clusters=clusters, canonical_records=canonical_records,
        identity_status_by_record=identity_status_by_record,
    )
