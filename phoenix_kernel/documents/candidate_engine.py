"""Phoenix Document Pipeline V2 - Fase 4: Candidate Engine.

PHX-NEW (2026-08-29, especificação fechada pelo usuário depois da Fase 3):
procura, dentro do texto de um `Block` (Fase 2), ocorrências que PARECEM
ser um campo conhecido (EAN, NCM, CEST, preço, telefone, e-mail, data,
peso) e devolve um `Candidate` (Fase 1) pra cada uma - usando o
`normalizer.py` (Fase 3) pra validar/normalizar o valor encontrado.

Princípios fechados explicitamente pelo usuário pra esta fase (não
inventados aqui, só implementados):
  - "Achar um padrão != aceitar como verdade": um candidato ENCONTRADO
    mas que falha a validação (ex: EAN com dígito verificador errado)
    NUNCA é descartado - vira um `Candidate` com `valid=False`, porque uma
    fase futura de conflito/evidência pode precisar exatamente dessa
    ocorrência (ex: "o texto diz ...301, a imagem da embalagem diz
    ...302 - o texto provavelmente tem erro de digitação").
  - Reconhece rótulo forte ("EAN:", "NCM:", "CEST:", "Preço:"...) quando
    presente, mas TAMBÉM reconhece ocorrência sem rótulo quando o próprio
    FORMATO já é um sinal forte o bastante (endereço de e-mail, "R$" na
    frente de um valor, uma data em formato numérico, um EAN cujo dígito
    verificador bate mesmo sem a palavra "EAN" do lado).
  - Cada candidato preserva: `block_id`, `raw_value`, `normalized_value`,
    `method`, `valid`, `confidence`, `start`/`end` (offset dentro do texto
    onde foi encontrado) e um contexto curto antes/depois.
  - Zero LLM, zero OCR, zero MiniCPM-V - Python puro (mesma regra da
    Fase 3).

Limitações conhecidas, documentadas de propósito (mesmo espírito das
Fases 2/3 - nada escondido):
  - NCM, CEST e peso só são reconhecidos quando vêm com rótulo explícito
    ("NCM: 32091010") OU quando a célula está numa coluna de tabela cujo
    CABEÇALHO já diz o que ela é (ver `_candidates_from_table_block`
    abaixo) - sem nenhum dos dois sinais, um número de 7-8 dígitos solto é
    indistinguível de qualquer outro número solto (diferente de EAN, que
    tem dígito verificador pra se autoconfirmar).
  - Telefone sem rótulo só é reconhecido quando tem pontuação típica de
    telefone brasileiro (parênteses/hífen) - um "11999998888" bruto,
    sem rótulo nem pontuação, colide demais com outros números longos
    (EAN, NCM) pra valer a pena tentar sem sinal nenhum.
  - Quando duas regras encontram EXATAMENTE o mesmo span de texto pro
    MESMO `field_type` (ex: uma regra rotulada e uma regra "solta" acham
    o mesmo EAN), só o candidato de MAIOR confiança daquele span
    sobrevive - evita duplicata idêntica sem esconder achados
    genuinamente diferentes (spans diferentes, ou o mesmo span com
    `field_type` diferente, continuam todos preservados) - EXCETO pra
    família "price"/"price_min"/"price_max" (ver PHX-FIX abaixo), onde o
    mesmo span É tratado como duplicata mesmo com field_type diferente.

PHX-FIX (2026-08-29, achado real testando a Fase 6/Evidence Engine contra
os dois documentos reais - não um bug do Evidence, e sim uma
simplificação desta fase que só apareceu quando a Fase 6 começou a
AGREGAR por field_type): "Preço Mínimo: R$ 589,00 | Preço Máximo: R$
749,00" gerava dois `Candidate`s com o MESMO `field_type` genérico
"price" - o Evidence Engine então via dois valores DIFERENTES
"concorrendo" pelo mesmo campo dentro do mesmo record e reportava
"conflict" (ex: 589.00 vs 749.00), quando na verdade não existe conflito
nenhum - são dois campos legítimos e distintos, não duas leituras
divergentes do mesmo dado. Corrigido separando o `field_type` já na
ORIGEM (aqui, Fase 4) quando o próprio rótulo captura explicitamente
"Mínimo"/"Máximo" (`price_min`/`price_max`) - "Preço de Venda"/"Preço de
Custo"/"Preço:"/"Valor:" sem qualificador continuam genericamente "price"
(nenhum documento real testado até agora qualifica esses com um segundo
valor concorrente; se isso mudar no futuro, o mesmo padrão usado aqui
serve de modelo).

PHX-NEW (2026-08-29, expansão de vocabulário V2, especificação fechada
pelo usuário depois de validar a Fase 10 contra o XLSX real do MarketUP -
só 4/39 colunas reais tinham `field_type` correspondente): adiciona o
grupo "determinístico" da expansão - dimensões (`height`/`width`/`depth`,
rótulos "Altura"/"Largura"/"Profundidade", reaproveitando o MESMO
Normalizer dimensional que `weight` já usa) e texto livre explicitamente
rotulado (`brand`/`model`/`tags`/`included_items`/`specifications`/
`explicit_product_name`/`description_html`). Regra explícita do usuário
respeitada: nenhum hack específico de MarketUP - os detectores reconhecem
RÓTULOS GENÉRICOS ("Marca:", "Altura:", um bloco que começa com `<p>`),
o nome da coluna de destino real continua sendo problema do
`ColumnMapping` (Fase 10), nunca deste módulo. Zero LLM nesta rodada
(pedido explícito). Dois achados reais que mudaram o desenho:
  - `weight` ganhou um bug fix de quebra (não um campo novo): o rótulo
    fechado da Fase 4 original só reconhecia "Peso: 25,500" - "Peso
    (Kg): 24,500 (Líq.)" (unidade colada no RÓTULO, não no valor) nunca
    virava `Candidate`, mesmo esse formato aparecendo dezenas de vezes no
    MESMO documento real já usado pra fechar as Fases 6/9/10. A mesma
    generalização de rótulo (`_labeled_dimensional_pattern`) que height/
    width/depth precisavam corrige isso de graça.
  - `explicit_product_name` EXCLUI "Título" do vocabulário de rótulo de
    propósito - achado real: nos dois documentos-fonte (conversas SOBRE
    como escrever títulos), "Título:" aparece muito mais como PROSA de
    estratégia (ex: "Título: Produto + Medida + Marca + Resultado.", uma
    FÓRMULA, não um nome de produto de verdade) do que como rótulo de um
    valor real - incluir geraria falso-positivo sistemático. Ficou só
    "Nome do Produto"/"Nome na Loja Virtual", mesmo tendo ZERO ocorrência
    real nos dois documentos testados (cobertura baixa aqui é um
    problema de FONTE, não deste detector - documentado, não escondido).
  - `description_html` não usa o delimitador textual "[DESCRIÇÃO DO
    PRODUTO ...]" que fazia parte da especificação original - achado
    real: esse delimitador aparece 141/128 vezes nos dois documentos, mas
    quase sempre dentro do trecho INSTRUCIONAL da conversa (definindo o
    padrão desejado), colado no conteúdo real gerado em só 1 dos 141
    casos. O sinal que É confiável, achado no MESMO documento: um bloco
    cujo texto começa direto com `<p>`/`<div><p>` é, por si só, HTML de
    descrição de verdade (14 ocorrências reais, sempre descrição de
    produto genuína) - mesma categoria de "formato já é sinal forte"
    que e-mail/"R$"/EAN com checksum, sem rótulo nenhum precisar estar do
    lado.

PHX-NEW (2026-08-29, expansão de vocabulário V2 - grupo "preço",
especificação fechada pelo usuário depois de validar o grupo
determinístico contra o XLSX real do MarketUP - cobertura 14/39):
adiciona SEIS `field_type`s comerciais novos - `cost_price` (custo de
aquisição), `retail_price` (preço de venda normal/varejo),
`wholesale_price` (preço de venda no atacado), `wholesale_min_quantity`
(quantidade mínima pro atacado valer), `compare_at_price` ("Preço De" -
preço de referência/anterior) e `sale_price` ("Preço Por" - preço
final/promocional). DELIBERADAMENTE separados de `price`/`price_min`/
`price_max` - esses três continuam significando SÓ "o valor observado no
documento-fonte", nunca um conceito de política comercial; nenhuma regra
automática (`price_min` -> `cost_price` ou parecido) foi criada aqui, só
uma futura regra EXPLÍCITA de `JobPlan` poderia fazer essa transformação.
Os cinco campos de moeda usam `normalize_currency_brl_commercial`
(normalizer.py) - MESMO parsing de `normalize_currency_brl`, mas sempre
preenchendo `unit="BRL"`/`original_unit="R$"`/`parsed_value` (o contrato
de `price`/`price_min`/`price_max`, que não preenche `unit`, fica
intocado de propósito). `wholesale_min_quantity` usa
`normalize_quantity_count` - `unit="unit"` sempre, nunca mistura
quantidade com moeda. Achado real que confirma uma colisão arquitetural
pré-existente (não um bug novo): o `_PRICE_LABEL_RE` genérico (Fase 4
original, ver PHX-FIX acima) já reconhece "Preço de Venda"/"Preço de
Custo" como variantes de rótulo, mas mapeava as duas pra `price`
genérico - como o vocabulário de `cost_price`/`retail_price` desta
rodada inclui EXATAMENTE esses dois rótulos, o mesmo span de texto
passaria a gerar dois `Candidate`s (um genérico, um comercial). Resolvido
com uma família de dedup por span SEPARADA e LOCAL
(`_COMMERCIAL_PRICE_FIELD_TYPES`, ver `_dedupe_key_field`) - NÃO
estende `PRICE_FIELD_TYPES` (que o Record Segmenter/Fase 5 já fechada
usa pra fronteira de record) - e confiança do detector comercial (0.97)
maior que a do genérico (0.95), fazendo a leitura mais específica vencer
o desempate: "Preço de Venda: R$ 100,00" agora produz SÓ `retail_price`.
Mudança de comportamento pequena, deliberada e testada, restrita a esse
caso; "Preço:"/"Valor:"/"Preço Mínimo:"/"Preço Máximo:" soltos continuam
100% inalterados. `compare_at_price`/`sale_price` exigem literalmente o
prefixo "Preço" (nunca "De:"/"Por:" isolados - são palavras comuns demais
pra virar rótulo de campo, mesma filosofia que excluiu "Título:" de
`explicit_product_name`). Achado real esperado e aceito explicitamente
pelo usuário: os dois documentos-fonte reais usados pra validar esta
pipeline são conversas sobre COMO escrever anúncios, não contêm política
comercial de custo/atacado - cobertura real de 0% destes seis campos
nos dois documentos é o resultado CORRETO ("fonte documental não contém
essa informação, a Phoenix não deve inventá-la"), não um defeito destes
detectores."""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable, Optional

# PHX-PERF (2026-09-03, passo 2): abaixo deste número de blocos, o overhead de
# criar threads não compensa — roda serial. Acima, paraleliza no ThreadPool
# (re.search libera a GIL, então threads dão ganho real no Xeon sem o custo de
# serialização de processos do Windows). _PARALLEL_MAX_WORKERS limita o teto de
# threads independente do número de cores, pra não criar centenas em máquinas
# grandes.
_PARALLEL_BLOCK_THRESHOLD = 400
_PARALLEL_MAX_WORKERS = 24

from phoenix_kernel.documents.normalized import Block, BlockType, Candidate, NormalizedDocument
from phoenix_kernel.documents.normalizer import (
    NormalizationResult,
    normalize_cest,
    normalize_currency_brl,
    normalize_currency_brl_commercial,
    normalize_date,
    normalize_ean,
    normalize_email,
    normalize_html_single_line,
    normalize_labeled_text,
    normalize_ncm,
    normalize_number_with_unit,
    normalize_phone_br,
    normalize_quantity_count,
    normalize_tag_list,
)

_CONTEXT_CHARS = 20

# Rótulos fortes reconhecidos por campo - usados só pra dar um "empurrão"
# de confiança quando presentes; a ausência de rótulo não impede a
# detecção nos campos cujo FORMATO já é autoidentificável (ver
# `_UNLABELED_DETECTORS` abaixo).
_LABELS_BY_FIELD = {
    "ean": r"EAN|GTIN|C[oó]digo\s+de\s+Barras",
    "ncm": r"NCM",
    "cest": r"CEST",
    "phone": r"Telefone|Tel\.?|Fone|WhatsApp",
    "email": r"E-?mail",
    "date": r"Data|Validade|Vencimento",
    "weight": r"Peso",
    # PHX-NEW (2026-08-29, expansão de vocabulário V2 - grupo
    # "determinístico" pedido pelo usuário depois de validar a Fase 10
    # contra o XLSX real do MarketUP, ver docstring do módulo pro
    # contexto completo): dimensões reaproveitam o MESMO Normalizer
    # dimensional (Fase 3) que peso já usa - "28,5 cm" == "0,285 m" pela
    # mesma razão que "600g" == "0,6 kg".
    "height": r"Altura",
    "width": r"Largura",
    "depth": r"Profundidade",
    # Texto livre explicitamente rotulado - zero checksum/formato
    # autoidentificável, só "um rótulo precede o valor" (ver
    # `_labeled_text_pattern` abaixo). PHX-NEW: "Título" foi
    # deliberadamente EXCLUÍDO do rótulo de `explicit_product_name` -
    # achado real testando os dois documentos: "Título:" aparece muito
    # mais como PROSA de conversa sobre ESTRATÉGIA de título (ex:
    # "Título: Produto + Medida + Marca + Resultado.", uma fórmula, não
    # um nome de produto de verdade) do que como rótulo de um valor real -
    # incluir geraria falso-positivo sistemático nestes documentos.
    # "Nome do Produto"/"Nome na Loja Virtual" ficam no vocabulário mesmo
    # tendo ZERO ocorrência real nos dois documentos testados - rótulo
    # limpo e seguro, cobertura real é um problema de FONTE, não deste
    # detector (documentado no relatório de cobertura).
    "brand": r"Marca",
    "model": r"Modelo",
    "tags": r"Tags",
    "included_items": r"Itens\s+Inclusos",
    "specifications": r"Especifica[çc][õo]es",
    "explicit_product_name": r"Nome\s+do\s+Produto|Nome\s+na\s+Loja\s+Virtual",
    # PHX-NEW (2026-08-29, expansão de vocabulário V2 - grupo "preço",
    # especificação fechada pelo usuário depois do grupo determinístico,
    # ver PHX-NEW completo no topo do módulo): SEIS conceitos comerciais
    # novos, DELIBERADAMENTE separados de price/price_min/price_max (que
    # continuam significando só "o valor que apareceu no texto-fonte",
    # nunca uma política comercial). `compare_at_price`/`sale_price`
    # exigem o prefixo literal "Preço" ("Preço De"/"Preço Por") - o
    # usuário foi explícito que "De:"/"Por:" sozinhos são palavras comuns
    # demais pra virar rótulo de campo (mesma filosofia que excluiu
    # "Título:" de `explicit_product_name` acima).
    "cost_price": r"Pre[çc]o\s+de\s+Custo|Pre[çc]o\s+Custo|Custo",
    "retail_price": r"Pre[çc]o\s+Venda\s+Varejo|Pre[çc]o\s+de\s+Venda|Pre[çc]o\s+Varejo",
    "wholesale_price": r"Pre[çc]o\s+Venda\s+Atacado|Pre[çc]o\s+Atacado",
    "wholesale_min_quantity": r"Quantidade\s+M[íi]nima\s+Atacado|Qtd\.?\s+M[íi]nima\s+Atacado",
    "compare_at_price": r"Pre[çc]o\s+De",
    "sale_price": r"Pre[çc]o\s+Por",
}

# Unidade opcional "encostada" no rótulo dimensional, achado real nos
# dois documentos: "Altura (cm): 34,8" e "Peso (Kg): 24,500" convivem com
# "Altura: 32,0 cm"/"Peso: 25,500" (unidade só no VALOR, ou nem isso) no
# MESMO documento. `{1,10}` é só um limite de segurança contra um
# parêntese gigante sem relação nenhuma virar "ruído aceito" por engano -
# nenhuma unidade real precisa de mais de 10 caracteres dentro do
# parêntese.
_DIMENSIONAL_VALUE_PATTERN = r"[\d.,]+\s*[A-Za-zµ%]*"


def _labeled_dimensional_pattern(label_regex: str) -> re.Pattern:
    """PHX-FIX (2026-08-29, achado real testando a expansão de vocabulário
    V2 contra os dois documentos): esta generalização também CORRIGE um
    gap real da Fase 4 original, não outro campo novo - o detector de
    `weight` já fechado (`_labeled_pattern("weight", ...)`, sem suporte a
    unidade-no-rótulo) só reconhecia "Peso: 25,500"; "Peso (Kg): 24,500
    (Líq.)" NUNCA virava `Candidate` nenhum, mesmo esse formato aparecendo
    dezenas de vezes no MESMO documento real já usado pra fechar as Fases
    6/9/10 - ninguém tinha notado porque nenhuma fase anterior precisou de
    100% de cobertura de peso pra fechar. `weight` agora usa esta MESMA
    função (ver `_LABELED_DETECTORS` abaixo), não duas implementações
    paralelas.

    O parêntese depois do rótulo vira o grupo nomeado `unit_hint` (ver
    `_run_detector`) em vez de só ser "engolido" - achado real que exigiu
    isso: "Altura (cm): 34,8" tem a unidade SÓ no rótulo, nunca no valor
    (`normalize_number_with_unit("34,8")` não tem como saber que é "cm").
    Sem propagar essa dica, "Altura (cm): 34,8" (fica unit=None) e
    "Altura: 0,348 m" (fica unit=m) nunca seriam reconhecidos como a
    MESMA medida - exatamente o problema de equivalência dimensional que
    o usuário pediu pra evitar."""
    return re.compile(
        rf"(?i)\b(?:{label_regex})\b\s*(?:\((?P<unit_hint>[^)]{{1,10}})\))?\s*[:\-]?\s*(?P<value>{_DIMENSIONAL_VALUE_PATTERN})"
    )


# Ruído de marcação HTML/espaço que pode aparecer ENTRE o rótulo e o
# dois-pontos, ou ENTRE o dois-pontos e o valor de verdade - achado real:
# "<b>Marca:</b> <b>Bonafont (Danone) |</b>" (o fechamento do <b> do
# RÓTULO vem colado no ":"; o <b> do VALOR abre logo depois, antes do
# texto de verdade). `{0,20}` limita o tamanho de uma tag individual
# (evita casar algo que não é tag de verdade).
_HTML_TAG_NOISE = r"(?:\s|<\/?[a-zA-Z][^<>]{0,20}>)*"


def _labeled_text_pattern(label_regex: str, max_len: int = 120) -> re.Pattern:
    """Detector de texto livre rotulado (Marca/Modelo/Tags/Itens
    Inclusos/Especificações/Nome do Produto). Corta o valor no primeiro
    "|" (separador de campo dentro da mesma linha "Ficha Técnica: Marca:
    X | Volume: Y | ..." - achado real) ou "<" (próxima tag HTML) ou fim
    de linha/texto - o que vier primeiro. `max_len` é um limite de
    segurança (não uma regra de negócio) contra um rótulo isolado sem
    delimitador nenhum até o fim de um texto de origem malformado/
    concatenado (achado real: uma célula de tabela sem separador virou
    "modelo: telada medida: 100mm x 20m e 50mm x 45m marca: atlas..." -
    sem este limite, a captura "vazaria" pra dentro do próximo campo);
    `tags` (ver `_LABELED_DETECTORS`) usa um `max_len` bem maior de
    propósito, porque uma lista de tags real é longa e não tem "|" no
    meio pra servir de limite natural."""
    return re.compile(
        rf"(?i)\b(?:{label_regex})\b{_HTML_TAG_NOISE}:{_HTML_TAG_NOISE}"
        rf"(?P<value>[^|<\n]{{1,{max_len}}}?)\s*(?=\s*\||\s*<|\n|$)"
    )

# "price" fica FORA de `_LABELS_BY_FIELD`/`_LABELED_DETECTORS` de propósito
# (ver PHX-FIX no topo do módulo) - tem detector próprio
# (`_run_price_label_detector`) porque precisa decidir o `field_type`
# EXATO (price/price_min/price_max) por ocorrência, olhando o rótulo
# capturado - os outros campos nunca precisam disso (um NCM é sempre só
# "ncm", não existe "ncm_mínimo").
_PRICE_LABEL_RE = re.compile(
    r"(?i)\b(?P<label>Pre[çc]o(?:\s+(?:M[íi]nimo|M[áa]ximo|de\s+Venda|de\s+Custo))?|Valor)"
    r"\s*[:\-]?\s*(?P<value>R?\$?\s*[\d.,]+)"
)

# Qualquer `field_type` desta família representa "um preço" pra fins de
# deduplicação por span (ver `_dedupe_same_span`) e de sinal forte de
# fronteira no Record Segmenter (Fase 5) - só o NOME do campo virou mais
# específico, a natureza continua "preço".
PRICE_FIELD_TYPES = {"price", "price_min", "price_max"}

# PHX-NEW (2026-08-29, expansão de vocabulário V2 - grupo "preço"):
# família de dedup SEPARADA e LOCAL (não estende `PRICE_FIELD_TYPES`
# acima de propósito) - `PRICE_FIELD_TYPES` é importado por
# `record_segmenter.py` (Fase 5, já fechada) pra decidir FRONTEIRA de
# record (`_STRONG_IDENTIFIER_FIELDS`/`_strong_family`); estender aquele
# conjunto arriscaria mudar um comportamento já fechado e validado sem
# necessidade - os cinco `field_type`s comerciais abaixo só precisam
# entrar na família de dedup por SPAN (ver `_dedupe_key_field`), nunca na
# lógica de fronteira do Segmenter. `wholesale_min_quantity` fica de fora
# desta família: é uma QUANTIDADE, não um preço, e não tem risco de
# colisão de span com nenhum detector de preço existente.
_COMMERCIAL_PRICE_FIELD_TYPES = {
    "cost_price", "retail_price", "wholesale_price", "compare_at_price", "sale_price",
}


def _price_field_type_for_label(label_text: str) -> str:
    normalized = label_text.lower()
    if "mínimo" in normalized or "minimo" in normalized:
        return "price_min"
    if "máximo" in normalized or "maximo" in normalized:
        return "price_max"
    return "price"


def _run_price_label_detector(text: str) -> list[Candidate]:
    found: list[Candidate] = []
    for match in _PRICE_LABEL_RE.finditer(text):
        raw_value = match.group("value")
        start, end = match.span("value")
        result = normalize_currency_brl(raw_value)
        field_type = _price_field_type_for_label(match.group("label"))
        found.append(Candidate(
            field_type=field_type,
            raw_value=raw_value,
            block_id="",
            normalized_value=result.normalized,
            method="label",
            confidence=0.95 if result.valid else 0.4,
            valid=result.valid,
            start=start,
            end=end,
            context_before=text[max(0, start - _CONTEXT_CHARS):start],
            context_after=text[end:end + _CONTEXT_CHARS],
        ))
    return found


@dataclass(frozen=True)
class _Detector:
    field_type: str
    pattern: re.Pattern
    normalize: Callable[[str], NormalizationResult]
    method: str
    confidence_valid: float
    confidence_invalid: Optional[float]

    def confidence_for(self, result: NormalizationResult) -> float:
        return self.confidence_valid if result.valid else self.confidence_invalid


def _labeled_pattern(field_type: str, value_pattern: str) -> re.Pattern:
    label = _LABELS_BY_FIELD[field_type]
    return re.compile(rf"(?i)\b(?:{label})\s*[:\-]?\s*(?P<value>{value_pattern})")


# Detectores COM rótulo obrigatório - usados pros campos cujo formato
# sozinho (só dígitos) não teria como se autoidentificar.
_LABELED_DETECTORS: list[_Detector] = [
    _Detector("ean", _labeled_pattern("ean", r"\d[\d .\-]{6,18}\d"), normalize_ean, "label+checksum", 0.98, 0.55),
    _Detector("ncm", _labeled_pattern("ncm", r"\d[\d.\-]{5,12}\d"), normalize_ncm, "label", 0.9, 0.4),
    _Detector("cest", _labeled_pattern("cest", r"\d[\d.\-]{4,10}\d"), normalize_cest, "label", 0.9, 0.4),
    # "price" NÃO está aqui - ver `_run_price_label_detector` (PHX-FIX no
    # topo do módulo): precisa decidir price/price_min/price_max por
    # ocorrência, o que o `_Detector` genérico (um field_type fixo por
    # detector inteiro) não permite.
    _Detector("phone", _labeled_pattern("phone", r"[\d()+\-\s]{8,20}\d"), normalize_phone_br, "label", 0.92, 0.4),
    _Detector("date", _labeled_pattern("date", r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}"), normalize_date, "label", 0.9, 0.4),
    # dimensionais - todos usam `_labeled_dimensional_pattern` (PHX-FIX:
    # inclusive `weight`, que ganhou suporte a "Peso (Kg): X" aqui, ver
    # docstring da função) + o MESMO Normalizer dimensional da Fase 3.
    _Detector("weight", _labeled_dimensional_pattern(_LABELS_BY_FIELD["weight"]), normalize_number_with_unit, "label", 0.85, 0.4),
    _Detector("height", _labeled_dimensional_pattern(_LABELS_BY_FIELD["height"]), normalize_number_with_unit, "label", 0.85, 0.4),
    _Detector("width", _labeled_dimensional_pattern(_LABELS_BY_FIELD["width"]), normalize_number_with_unit, "label", 0.85, 0.4),
    _Detector("depth", _labeled_dimensional_pattern(_LABELS_BY_FIELD["depth"]), normalize_number_with_unit, "label", 0.85, 0.4),
    # PHX-NEW (expansão V2 - grupo "determinístico"): texto livre
    # explicitamente rotulado, zero LLM (ver `normalize_labeled_text`/
    # `normalize_tag_list` em `normalizer.py` - só limpeza mecânica,
    # nenhuma interpretação de conteúdo).
    _Detector("brand", _labeled_text_pattern(_LABELS_BY_FIELD["brand"]), normalize_labeled_text, "label", 0.85, 0.3),
    _Detector("model", _labeled_text_pattern(_LABELS_BY_FIELD["model"]), normalize_labeled_text, "label", 0.85, 0.3),
    _Detector("included_items", _labeled_text_pattern(_LABELS_BY_FIELD["included_items"]), normalize_labeled_text, "label", 0.8, 0.3),
    _Detector("specifications", _labeled_text_pattern(_LABELS_BY_FIELD["specifications"]), normalize_labeled_text, "label", 0.8, 0.3),
    _Detector("explicit_product_name", _labeled_text_pattern(_LABELS_BY_FIELD["explicit_product_name"]), normalize_labeled_text, "label", 0.8, 0.3),
    # `max_len` bem maior de propósito (ver docstring de
    # `_labeled_text_pattern`) - uma lista de tags real não tem "|" no
    # meio pra servir de limite natural, só o fim da linha/bloco.
    _Detector("tags", _labeled_text_pattern(_LABELS_BY_FIELD["tags"], max_len=2000), normalize_tag_list, "label", 0.85, 0.3),
    # PHX-NEW (2026-08-29, expansão V2 - grupo "preço"): `cost_price`/
    # `retail_price` colidem DE PROPÓSITO com o rótulo "Preço de
    # Custo"/"Preço de Venda" já reconhecido pelo `_PRICE_LABEL_RE`
    # genérico (Fase 4 original, ver PHX-FIX no topo do módulo) - por
    # isso a confiança aqui (0.97) é DELIBERADAMENTE maior que a do
    # detector genérico (0.95): "Preço de Venda: R$ 100,00" passa a virar
    # SÓ `retail_price` (ver `_COMMERCIAL_PRICE_FIELD_TYPES`/
    # `_dedupe_key_field` acima pro mecanismo de desempate), nunca mais
    # também um `price` genérico duplicado - mudança de comportamento
    # pequena e deliberada, documentada e testada, restrita a este
    # qualificador específico ("Preço:"/"Valor:"/"Preço Mínimo:"/"Preço
    # Máximo:" soltos continuam 100% inalterados). `wholesale_price`/
    # `compare_at_price`/`sale_price` não colidem com nada existente
    # (rótulos "Atacado"/"De"/"Por" não fazem parte do `_PRICE_LABEL_RE`),
    # confiança padrão de rótulo (0.9).
    _Detector("cost_price", _labeled_pattern("cost_price", r"R?\$?\s*[\d.,]+"), normalize_currency_brl_commercial, "label", 0.97, 0.5),
    _Detector("retail_price", _labeled_pattern("retail_price", r"R?\$?\s*[\d.,]+"), normalize_currency_brl_commercial, "label", 0.97, 0.5),
    _Detector("wholesale_price", _labeled_pattern("wholesale_price", r"R?\$?\s*[\d.,]+"), normalize_currency_brl_commercial, "label", 0.9, 0.4),
    _Detector("compare_at_price", _labeled_pattern("compare_at_price", r"R?\$?\s*[\d.,]+"), normalize_currency_brl_commercial, "label", 0.9, 0.4),
    _Detector("sale_price", _labeled_pattern("sale_price", r"R?\$?\s*[\d.,]+"), normalize_currency_brl_commercial, "label", 0.9, 0.4),
    # Quantidade, não preço - `normalize_quantity_count` NUNCA mistura
    # moeda com quantidade (ver docstring em normalizer.py); por isso
    # fica FORA de `_COMMERCIAL_PRICE_FIELD_TYPES`.
    _Detector("wholesale_min_quantity", _labeled_pattern("wholesale_min_quantity", r"[\d.,]+\s*[A-Za-zÀ-ÿ]*"), normalize_quantity_count, "label", 0.9, 0.4),
]

# Detectores SEM rótulo - só existem pros campos cujo FORMATO já é sinal
# forte o bastante sozinho (endereço de e-mail, "R$" explícito, EAN com
# dígito verificador batendo, data em formato numérico reconhecível,
# telefone com pontuação típica, um bloco INTEIRO de HTML de descrição -
# ver PHX-NEW abaixo).
_UNLABELED_DETECTORS: list[_Detector] = [
    _Detector("email", re.compile(r"(?P<value>[\w.+-]+@[\w-]+\.[\w.-]+)"), normalize_email, "format", 0.95, 0.2),
    _Detector("price", re.compile(r"(?P<value>R\$\s*[\d.,]+)"), normalize_currency_brl, "format(R$)", 0.9, 0.3),
    _Detector("date", re.compile(r"(?P<value>\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b)"), normalize_date, "format", 0.7, 0.3),
    _Detector("ean", re.compile(r"(?<!\d)(?P<value>\d{8}|\d{12}|\d{13}|\d{14})(?!\d)"), normalize_ean, "checksum", 0.75, None),
    _Detector("phone", re.compile(r"(?P<value>\(?\d{2}\)?[\s.\-]?\d{4,5}[\s.\-]?\d{4})"), normalize_phone_br, "format", 0.8, 0.3),
    # PHX-NEW (2026-08-29, expansão V2 - grupo "determinístico"): achado
    # real testando o delimitador textual "[DESCRIÇÃO DO PRODUTO ...]"
    # pedido inicialmente - ele aparece 141/128 vezes nos dois documentos,
    # mas quase sempre dentro de trecho INSTRUCIONAL da conversa (define o
    # PADRÃO desejado), não colado no conteúdo real gerado (só 1/141 caso
    # tinha HTML de verdade no bloco seguinte) - rótulo pouco confiável
    # pra virar Candidate aqui. O sinal que É confiável, achado no MESMO
    # documento: um bloco cujo texto começa direto com `<p>` (ou
    # `<div><p>`) É, por si só, um HTML de descrição de verdade (14
    # ocorrências reais, sempre um parágrafo de descrição de produto
    # genuíno) - mesma categoria de "formato já é sinal forte" que
    # e-mail/"R$"/EAN com checksum, sem precisar de rótulo nenhum do lado.
    _Detector("description_html", re.compile(r"^\s*(?P<value>(?:<div>\s*)?<p>.+)$", re.DOTALL), normalize_html_single_line, "format(html)", 0.9, 0.3),
]


def _run_detector(detector: _Detector, text: str) -> list[Candidate]:
    found: list[Candidate] = []
    for match in detector.pattern.finditer(text):
        raw_value = match.group("value")
        start, end = match.span("value")

        # PHX-FIX (2026-08-29, ver docstring de `_labeled_dimensional_pattern`):
        # quando o padrão tem um grupo `unit_hint` (só os detectores
        # dimensionais têm) E o valor capturado não trouxe unidade
        # nenhuma sozinho, completa o valor com a dica do rótulo ANTES de
        # normalizar - nunca muda `raw_value` (o que fica no Candidate
        # continua exatamente o que o documento escreveu), só o texto que
        # vai pro Normalizer.
        value_to_normalize = raw_value
        if "unit_hint" in match.groupdict():
            unit_hint = match.group("unit_hint")
            if unit_hint and re.fullmatch(r"[A-Za-zµ%°]{1,6}", unit_hint.strip()) and not re.search(r"[A-Za-zµ%°]", raw_value):
                value_to_normalize = f"{raw_value.strip()}{unit_hint.strip()}"

        result = detector.normalize(value_to_normalize)
        # Detector "checksum"-only (EAN sem rótulo): só vale a pena
        # registrar quando o dígito verificador realmente bate - sem
        # rótulo, um número de 8/12/13/14 dígitos com checksum ERRADO é
        # ruído demais (colide com telefone, NCM+algo, id interno etc.)
        # pra merecer virar Candidate.
        if detector.confidence_invalid is None and not result.valid:
            continue
        found.append(Candidate(
            field_type=detector.field_type,
            raw_value=raw_value,
            block_id="",  # preenchido por quem chama (sabe o block.id)
            normalized_value=result.normalized,
            method=detector.method,
            confidence=detector.confidence_for(result),
            valid=result.valid,
            start=start,
            end=end,
            context_before=text[max(0, start - _CONTEXT_CHARS):start],
            context_after=text[end:end + _CONTEXT_CHARS],
            # PHX-FIX: propaga o raciocínio dimensional do Normalizer (Fase
            # 3) - ver PHX-FIX em normalizer.py/NormalizationResult. Pra
            # campos sem unidade (ean/ncm/cest/price/phone/date/email)
            # esses três continuam None, sem efeito nenhum.
            unit=result.unit,
            original_unit=result.original_unit,
            parsed_value=result.parsed_value,
        ))
    return found


def _dedupe_key_field(field_type: str) -> str:
    """Pra fins de deduplicação por span, price/price_min/price_max
    contam como a MESMA "família" (ver PHX-FIX no topo do módulo) -
    "Preço Mínimo: R$ 589,00" é capturado pelo detector rotulado como
    `price_min` E pelo detector solto (`format(R$)`) como `price`
    genérico, no MESMO span exato; sem isso os dois sobreviveriam juntos,
    duplicando a mesma ocorrência com dois field_types diferentes.

    PHX-NEW (2026-08-29, grupo "preço" da expansão V2): os cinco
    `field_type`s comerciais de `_COMMERCIAL_PRICE_FIELD_TYPES` entram
    NESTA MESMA família de dedup por span (não em `PRICE_FIELD_TYPES` em
    si, ver comentário lá pra não afetar o Record Segmenter/Fase 5) -
    "Preço de Venda: R$ 100,00" é capturado tanto pelo `_PRICE_LABEL_RE`
    genérico (`price`) quanto pelo novo detector rotulado
    (`retail_price`), no MESMO span exato do valor; a maior confiança do
    detector comercial (ver `_LABELED_DETECTORS`) garante que só
    `retail_price` sobrevive."""
    if field_type in PRICE_FIELD_TYPES or field_type in _COMMERCIAL_PRICE_FIELD_TYPES:
        return "price"
    return field_type


def _dedupe_same_span(candidates: list[Candidate]) -> list[Candidate]:
    """Quando dois detectores acham EXATAMENTE o mesmo span pro MESMO
    campo (ex: uma regra rotulada e a "solta" acham o mesmo EAN, ou um
    "Preço Mínimo" rotulado e o detector solto de "R$" genérico), mantém
    só o de maior confiança - spans diferentes, ou o mesmo span com um
    campo de FAMÍLIA diferente, continuam todos preservados (não é
    deduplicação por VALOR, é só por span+campo/família idêntica)."""
    best_by_key: dict[tuple, Candidate] = {}
    for candidate in candidates:
        key = (_dedupe_key_field(candidate.field_type), candidate.start, candidate.end)
        current_best = best_by_key.get(key)
        if current_best is None or candidate.confidence > current_best.confidence:
            best_by_key[key] = candidate
    # preserva a ordem de primeira aparição
    seen_keys: list[tuple] = []
    for candidate in candidates:
        key = (_dedupe_key_field(candidate.field_type), candidate.start, candidate.end)
        if key not in seen_keys:
            seen_keys.append(key)
    return [best_by_key[key] for key in seen_keys]


def _spans_overlap(a_start: Optional[int], a_end: Optional[int], b_start: int, b_end: int) -> bool:
    if a_start is None or a_end is None:
        return False
    return a_start < b_end and b_start < a_end


def find_candidates_in_text(text: str, block_id: str) -> list[Candidate]:
    """Procura todos os campos conhecidos dentro de UM texto (o texto de
    um parágrafo, ou de uma célula de tabela) e devolve os `Candidate`
    encontrados, já com `block_id` preenchido."""
    if not text:
        return []
    raw_candidates: list[Candidate] = []
    for detector in _LABELED_DETECTORS:
        raw_candidates.extend(_run_detector(detector, text))
    raw_candidates.extend(_run_price_label_detector(text))

    # PHX-FIX (2026-08-29, achado real testando a Fase 6/Evidence Engine
    # contra os dois documentos reais): um detector SEM RÓTULO (formato
    # ou checksum sozinho) não pode "roubar" um span que um detector COM
    # RÓTULO já explicou. Achado concreto: "NCM: 84672100" tem "84672100"
    # explicitamente rotulado como NCM; sem esta regra, o detector solto
    # de EAN (só checksum) TAMBÉM batia no mesmo número - coincidência
    # real, um NCM de 8 dígitos tem ~1/10 de chance de "passar" no dígito
    # verificador de EAN-8 por acaso - virando um segundo `Candidate`
    # "ean" que o Evidence Engine (Fase 6) via como um valor diferente
    # "brigando" pelo campo ean dentro do record (falso "conflict"),
    # quando não existe EAN nenhum ali, só coincidência de dígitos. Mesma
    # lógica também suprime um telefone "solto" nascendo de dentro de um
    # EAN já rotulado (span parcialmente sobreposto, achado no mesmo
    # documento real). Rótulo explícito sempre vence uma leitura só de
    # formato/checksum, mesmo quando são CAMPOS diferentes - se um número
    # legitimamente fosse as duas coisas ao mesmo tempo (não visto em
    # nenhum documento real testado até agora), a leitura sem rótulo seria
    # descartada silenciosamente; aceitável dado o trade-off (evitar ruído
    # de coincidência é mais valioso que este caso hipotético raro).
    labeled_spans = [(c.start, c.end) for c in raw_candidates if c.start is not None]
    for detector in _UNLABELED_DETECTORS:
        for candidate in _run_detector(detector, text):
            if any(_spans_overlap(candidate.start, candidate.end, s, e) for s, e in labeled_spans):
                continue
            raw_candidates.append(candidate)

    deduped = _dedupe_same_span(raw_candidates)
    return [
        Candidate(
            field_type=c.field_type, raw_value=c.raw_value, block_id=block_id,
            normalized_value=c.normalized_value, method=c.method, confidence=c.confidence,
            valid=c.valid, start=c.start, end=c.end,
            context_before=c.context_before, context_after=c.context_after,
            # PHX-FIX (2026-08-29): este rebuild final tinha esquecido de
            # propagar unit/original_unit/parsed_value - achado rodando o
            # próprio teste novo do fix dimensional (test_evidence_engine.py),
            # não num documento real desta vez, mas do mesmo jeito: testar
            # de ponta a ponta antes de considerar qualquer coisa fechada.
            unit=c.unit, original_unit=c.original_unit, parsed_value=c.parsed_value,
        )
        for c in deduped
    ]


# Mapeia nome de coluna (cabeçalho de tabela) -> field_type + normalizador,
# pro caso de tabela: quando o CABEÇALHO da coluna já diz o que a célula
# é, não precisamos que o VALOR da célula também repita o rótulo (uma
# célula de tabela sob a coluna "EAN" com o valor cru "7891019125302", sem
# a palavra "EAN" escrita dentro dela, ainda deve virar Candidate - a
# estrutura da tabela já É o rótulo).
_HEADER_FIELD_MAP: list[tuple[re.Pattern, str, Callable[[str], NormalizationResult]]] = [
    (re.compile(r"(?i)\bean\b|\bgtin\b|c[oó]digo\s+de\s+barras"), "ean", normalize_ean),
    (re.compile(r"(?i)\bncm\b"), "ncm", normalize_ncm),
    (re.compile(r"(?i)\bcest\b"), "cest", normalize_cest),
    # PHX-NEW (expansão V2 - grupo "preço"): estas SEIS entradas precisam
    # vir ANTES do padrão genérico "pre[çc]o|valor" logo abaixo - esta
    # função usa só o PRIMEIRO padrão que bate (`break` na linha do
    # `_HEADER_FIELD_MAP`), e os cabeçalhos reais do MarketUP "Preço de
    # Custo"/"Preço Venda Varejo"/"Preço Venda Atacado"/"Preço De"/"Preço
    # Por" TODOS contêm a palavra "Preço" - cairiam no genérico por
    # engano (virando `price` em vez do conceito comercial certo) se
    # ficassem depois. `compare_at_price`/`sale_price` usam âncora de
    # início/fim (`^...$`) porque "Preço De"/"Preço Por" são exatamente o
    # texto INTEIRO desses dois cabeçalhos reais - sem âncora, "Preço De"
    # também "bateria" como prefixo de "Preço de Venda"/"Preço de Custo"
    # (só muda maiúscula/minúscula do "de"/"De").
    (re.compile(r"(?i)pre[çc]o\s+de\s+custo|pre[çc]o\s+custo|\bcusto\b"), "cost_price", normalize_currency_brl_commercial),
    (re.compile(r"(?i)pre[çc]o\s+venda\s+varejo|pre[çc]o\s+de\s+venda|pre[çc]o\s+varejo"), "retail_price", normalize_currency_brl_commercial),
    (re.compile(r"(?i)pre[çc]o\s+venda\s+atacado|pre[çc]o\s+atacado"), "wholesale_price", normalize_currency_brl_commercial),
    (re.compile(r"(?i)quantidade\s+m[íi]nima\s+atacado|qtd\.?\s+m[íi]nima\s+atacado"), "wholesale_min_quantity", normalize_quantity_count),
    (re.compile(r"(?i)^\s*pre[çc]o\s+de\s*$"), "compare_at_price", normalize_currency_brl_commercial),
    (re.compile(r"(?i)^\s*pre[çc]o\s+por\s*$"), "sale_price", normalize_currency_brl_commercial),
    (re.compile(r"(?i)pre[çc]o|valor"), "price", normalize_currency_brl),
    (re.compile(r"(?i)telefone|\btel\.?\b|fone|whatsapp"), "phone", normalize_phone_br),
    (re.compile(r"(?i)e-?mail"), "email", normalize_email),
    (re.compile(r"(?i)data|validade|vencimento"), "date", normalize_date),
    (re.compile(r"(?i)\bpeso\b"), "weight", normalize_number_with_unit),
    # PHX-NEW (expansão V2): mesma ideia - cabeçalho de coluna já diz o
    # campo, célula não precisa repetir o rótulo dentro do texto.
    (re.compile(r"(?i)\baltura\b"), "height", normalize_number_with_unit),
    (re.compile(r"(?i)\blargura\b"), "width", normalize_number_with_unit),
    (re.compile(r"(?i)\bprofundidade\b"), "depth", normalize_number_with_unit),
    (re.compile(r"(?i)\bmarca\b"), "brand", normalize_labeled_text),
    (re.compile(r"(?i)\bmodelo\b"), "model", normalize_labeled_text),
    (re.compile(r"(?i)\btags\b"), "tags", normalize_tag_list),
    (re.compile(r"(?i)itens\s+inclusos"), "included_items", normalize_labeled_text),
    (re.compile(r"(?i)especifica[çc][õo]es"), "specifications", normalize_labeled_text),
    (re.compile(r"(?i)nome\s+do\s+produto|nome\s+na\s+loja"), "explicit_product_name", normalize_labeled_text),
    # PHX-FIX (2026-09-03, achado real: planilha saiu sem Descrição): a coluna
    # "Descrição" do MarketUP recebe o NOME do produto. Vem por último porque é
    # a mais genérica — só casa se nenhuma das colunas específicas acima casou.
    (re.compile(r"(?i)^\s*descri[çc][ãa]o\s*$"), "explicit_product_name", normalize_labeled_text),
]


def _candidates_from_table_block(block: Block) -> list[Candidate]:
    candidates: list[Candidate] = []
    headers = block.headers or []
    for row in (block.rows or []):
        for col_index, cell_text in enumerate(row):
            cell_text = cell_text or ""
            header = headers[col_index] if col_index < len(headers) else ""

            # 1) o cabeçalho da coluna já diz o campo -> a célula inteira
            # é o valor, mesmo sem repetir o rótulo dentro dela.
            for header_pattern, field_type, normalize_fn in _HEADER_FIELD_MAP:
                if header and header_pattern.search(header):
                    # mesmo ajuste do PHX-FIX pro detector rotulado: um
                    # cabeçalho de coluna "Preço Mínimo"/"Preço Máximo"
                    # também precisa virar price_min/price_max, não o
                    # "price" genérico (mesmo raciocínio, mesma correção).
                    if field_type == "price":
                        field_type = _price_field_type_for_label(header)
                    result = normalize_fn(cell_text.strip())
                    candidates.append(Candidate(
                        field_type=field_type, raw_value=cell_text.strip(), block_id=block.id,
                        normalized_value=result.normalized, method="table_header", confidence=0.97 if result.valid else 0.5,
                        valid=result.valid, start=0, end=len(cell_text.strip()),
                        unit=result.unit, original_unit=result.original_unit, parsed_value=result.parsed_value,
                    ))
                    break

            # 2) além disso, roda a detecção normal em cima do texto da
            # célula (cobre o caso de uma tabela SEM cabeçalho útil, ou
            # uma célula com mais de um campo dentro do mesmo texto).
            candidates.extend(find_candidates_in_text(cell_text, block.id))
    return candidates


def _detect_numbered_title_name(text: str, block_id: str) -> list[Candidate]:
    """PHX-FIX (2026-09-03, achado real do usuário — planilha de conveniência
    saiu sem Descrição): alguns catálogos nomeiam produtos por TÍTULO NUMERADO
    ('63. Cachaça São Francisco 970ml', '64. Cerveja Heineken Lata') em vez de
    um rótulo 'Nome do Produto:'. O detector de rótulo não pega isso, então o
    nome do produto (que vira a coluna Descrição) ficava vazio. Este detector
    reconhece o padrão 'NN. Nome' e emite um explicit_product_name.

    Critérios pra evitar falso-positivo (não confundir com item de lista comum):
    - começa com 1-3 dígitos + '.' + espaço;
    - o texto após o número começa com letra maiúscula;
    - tem tamanho de nome de produto (>= 6 chars, <= 160);
    - não termina em pontuação de frase (não é uma frase de prosa);
    - não contém rótulo de campo conhecido (evita 'NCM:', 'Peso:' etc.).
    """
    t = (text or "").strip()
    m = re.match(r'^(\d{1,3})\.\s+([A-ZÀ-Ú].{4,158})$', t)
    if not m:
        return []
    nome = m.group(2).strip()
    if nome.endswith((".", "!", "?", ":")):
        return []
    if re.search(r'\b(NCM|CEST|CFOP|Peso|Altura|Largura|Profundidade|Tags|Marca|Pre[çc]o)\s*[:\(]', nome, re.I):
        return []
    return [Candidate(
        field_type="explicit_product_name",
        raw_value=nome,
        normalized_value=nome,
        valid=True,
        block_id=block_id,
    )]


def find_candidates_in_block(block: Block) -> list[Candidate]:
    """Ponto de entrada principal da Fase 4: acha candidatos dentro de UM
    `Block` (Fase 2), usando a estrutura do bloco (texto corrido vs.
    tabela com cabeçalho) pra decidir como procurar. Nunca olha pra fora
    do bloco - juntar candidatos de blocos diferentes num mesmo registro
    é trabalho do Record Segmenter (Fase 5)."""
    if block.type == BlockType.TABLE:
        return _candidates_from_table_block(block)
    if block.type in (BlockType.PARAGRAPH, BlockType.HEADING):
        text = block.text_raw or ""
        found = find_candidates_in_text(text, block.id)
        # PHX-FIX (2026-09-03): também tenta o padrão de título numerado, que
        # o detector de rótulo não cobre. Só adiciona se ainda não houver um
        # nome de produto neste bloco (não duplica).
        if not any(c.field_type == "explicit_product_name" for c in found):
            found = found + _detect_numbered_title_name(text, block.id)
        return found
    return []


def find_candidates_in_document(document: NormalizedDocument) -> list[Candidate]:
    """PHX-NEW (2026-08-29, pré-requisito da Fase 5): roda
    `find_candidates_in_block` em TODO bloco do documento, na ordem, e
    atribui um `Candidate.id` sequencial e ESTÁVEL (`c000000`, `c000001`,
    ...) a cada candidato encontrado. `find_candidates_in_block` sozinho
    não pode fazer isso - ele roda por bloco isoladamente, então IDs
    atribuídos ali reiniciariam a cada bloco e colidiriam entre blocos
    diferentes. O Record Segmenter (Fase 5) referencia esses ids em
    `Record.candidate_ids` - por isso este passo precisa existir antes
    dele, no nível do DOCUMENTO inteiro, não do bloco.

    PHX-PERF (2026-09-03, passo 2): em documentos grandes, roda os blocos em
    paralelo num ThreadPool. `find_candidates_in_block` é ~100% regex, e o
    `re.search` do CPython LIBERA a GIL, então threads paralelizam de verdade
    no Xeon (12C/24T) SEM o overhead de serialização de processos do Windows.
    A ORDEM é preservada: `executor.map` devolve na ordem de entrada, e os ids
    sequenciais continuam sendo atribuídos depois, igual ao caminho serial —
    a saída é idêntica byte a byte à versão sequencial (garantido em teste).
    Abaixo do limiar, roda serial (o overhead de thread não compensa)."""
    blocks = document.blocks
    if len(blocks) < _PARALLEL_BLOCK_THRESHOLD:
        candidates: list[Candidate] = []
        for block in blocks:
            candidates.extend(find_candidates_in_block(block))
    else:
        max_workers = min(_PARALLEL_MAX_WORKERS, (os.cpu_count() or 1) * 2)
        chunk_size = -(-len(blocks) // max_workers)  # ceil
        chunks = [blocks[i:i + chunk_size] for i in range(0, len(blocks), chunk_size)]

        def _process_chunk(chunk: list) -> list:
            out: list[Candidate] = []
            for block in chunk:
                out.extend(find_candidates_in_block(block))
            return out

        candidates = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # map preserva a ordem dos chunks -> ordem dos blocos preservada
            for chunk_result in executor.map(_process_chunk, chunks):
                candidates.extend(chunk_result)

    for index, candidate in enumerate(candidates):
        candidate.id = f"c{index:06d}"
    return candidates
