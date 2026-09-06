"""Phoenix Document Pipeline V2 - Fase 3: Normalizer (Python puro).

PHX-NEW (2026-08-29, sequência direta da Fase 2 - ver PHX-NEW no topo de
`normalized.py`/`docx_parser.py` pro contexto completo): converte um
VALOR CRU de texto (já reconhecido como sendo de um tipo - moeda, data,
número com unidade, EAN, NCM, CEST, telefone, e-mail) na sua forma
NORMALIZADA, pronta pra virar célula de Excel/comparação/validação.

Deliberadamente NÃO faz parte deste módulo (por decisão explícita do
usuário, pra manter esta fase pequena e limpa):
  - Procurar candidatos DENTRO de um texto maior (isso é o Candidate
    Engine, Fase 4 - regex que ENCONTRA um EAN solto num parágrafo).
  - Decidir se uma imagem embutida precisa de análise visual (isso é uma
    decisão do orquestrador/Job Planner, não do Normalizer).
  - Qualquer chamada a LLM, OCR ou visão (MiniCPM-V/Tesseract) - Fase 3 é
    Python puro, sem rede e sem GPU.
  - Inferir headings semânticos a partir de texto solto (isso é o Record
    Segmenter, Fase 5 - o parser da Fase 2 e este Normalizer só lidam
    com fato estrutural/de formato, nunca com interpretação).

Toda função aqui devolve um `NormalizationResult`: SEMPRE guarda
`raw` (exatamente como veio) separado de `normalized` (forma pronta pro
Excel) - nunca descarta o valor bruto, mesmo quando a normalização falha
(`valid=False`, `normalized=None`, `raw` preservado) - pedido explícito
do usuário reforçado em várias rodadas desta reestruturação."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional, Union

from phoenix_kernel.documents.ncm_lookup import ncm_exists
from phoenix_kernel.documents.cest_lookup import cest_exists


@dataclass
class NormalizationResult:
    """PHX-FIX (2026-08-29, achado real testando a Fase 6/Evidence Engine
    contra os documentos reais - relatado pelo usuário e corrigido na
    ORIGEM do contrato, aqui, não no Evidence Engine): "Peso: 0,600 kg" e
    "Peso: 600g" no MESMO produto viravam um "conflict" falso porque
    comparávamos 0.6 com 600.0 literalmente - a mesma grandeza física, só
    escrita em unidades diferentes. `unit`/`normalized` agora SEMPRE
    representam a UNIDADE CANÔNICA (ver `_DIMENSIONAL_UNITS` abaixo -
    massa->kg, comprimento->m, volume->l) quando a unidade encontrada é
    reconhecida; `original_unit`/`parsed_value` preservam o número e a
    unidade EXATAMENTE como apareceram no texto, antes de qualquer
    conversão - nunca descartados (mesmo raciocínio já usado em `raw`
    desde a primeira versão deste módulo), importantes pra auditoria e
    pra escrita final. Com isso o Evidence Engine (Fase 6) volta a só
    comparar número com número (`0.6 == 0.6`) sem precisar entender
    física nem conversão nenhuma - a inteligência dimensional fica toda
    aqui, na origem do valor normalizado, nunca espalhada por quem
    consome o valor depois."""

    raw: str
    normalized: Optional[Union[str, float, int]] = None
    unit: Optional[str] = None
    valid: bool = False
    parsed_value: Optional[float] = None
    original_unit: Optional[str] = None


# ---------------------------------------------------------------------------
# Números / moeda
# ---------------------------------------------------------------------------

_NUMBER_WITH_UNIT_RE = re.compile(
    r"^\s*(?P<sign>-)?\s*(?P<number>[\d.,]+)\s*(?P<unit>[A-Za-zµ%°]*)\s*$"
)

# Unidades DIMENSIONAIS reconhecidas -> (dimensão, unidade CANÔNICA, fator
# multiplicativo até a canônica). Só existem três unidades canônicas
# internas de propósito (pedido explícito do usuário): massa->kg,
# comprimento->m, volume->l - qualquer unidade fora desta tabela (%, °,
# "un", ou nenhuma) passa direto sem conversão (comportamento idêntico ao
# de antes deste fix).
_DIMENSIONAL_UNITS: dict[str, tuple[str, str, float]] = {
    "kg": ("mass", "kg", 1.0),
    "g": ("mass", "kg", 0.001),
    "mg": ("mass", "kg", 0.000001),
    "m": ("length", "m", 1.0),
    "cm": ("length", "m", 0.01),
    "mm": ("length", "m", 0.001),
    "l": ("volume", "l", 1.0),
    "ml": ("volume", "l", 0.001),
}


def _parse_br_or_plain_number(raw_number: str) -> Optional[float]:
    """Interpreta um número em formato BR (`1.234,56`) OU já em formato
    "plano" com ponto decimal (`3.5`) - a regra é: se tem vírgula, o ponto
    é separador de milhar e a vírgula é o decimal (formato BR); se NÃO
    tem vírgula, qualquer ponto presente é tratado como decimal (formato
    já normalizado/inteiro). Cobre os dois formatos que aparecem de
    verdade nos documentos-fonte reais vistos até agora ("25,500 Kg",
    "R$ 1.234,56", "18L", "3.5mm")."""
    s = raw_number.strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def normalize_currency_brl(raw: str) -> NormalizationResult:
    """"R$ 1.234,56" / "R$1.234,56" / "1234.56" -> 1234.56 (float, 2 casas).
    Preserva `raw` exatamente como veio, mesmo quando a normalização
    falha."""
    s = (raw or "").strip()
    stripped = re.sub(r"(?i)^r\$\s*", "", s)
    value = _parse_br_or_plain_number(stripped)
    if value is None:
        return NormalizationResult(raw=raw, valid=False)
    return NormalizationResult(raw=raw, normalized=round(value, 2), valid=True)


def normalize_number_with_unit(raw: str) -> NormalizationResult:
    """"25,500 Kg" -> (normalized=25.5, unit="kg"); "600g" -> (normalized
    =0.6, unit="kg" - CONVERTIDO pra canônica); "18L" -> (18.0, unit="l");
    "100cm" -> (1.0, unit="m"); "42" -> (42.0, unit=None). `parsed_value`/
    `original_unit` sempre preservam o número e a unidade exatamente como
    apareceram no texto, ANTES de qualquer conversão (ver PHX-FIX no
    `NormalizationResult` acima) - "600g" tem `parsed_value=600.0`,
    `original_unit="g"`, mas `normalized=0.6`, `unit="kg"`. Uma unidade
    fora de `_DIMENSIONAL_UNITS` (%, °, "un", ou nenhuma) passa direto sem
    conversão - `normalized`/`unit` ficam iguais a `parsed_value`/
    `original_unit`."""
    s = (raw or "").strip()
    match = _NUMBER_WITH_UNIT_RE.match(s)
    if not match:
        return NormalizationResult(raw=raw, valid=False)
    parsed_value = _parse_br_or_plain_number(match.group("number"))
    if parsed_value is None:
        return NormalizationResult(raw=raw, valid=False)
    if match.group("sign") == "-":
        parsed_value = -parsed_value
    original_unit = match.group("unit") or None
    original_unit = original_unit.lower() if original_unit else None

    conversion = _DIMENSIONAL_UNITS.get(original_unit) if original_unit else None
    if conversion is not None:
        _dimension, canonical_unit, factor = conversion
        normalized_value = round(parsed_value * factor, 6)
        unit = canonical_unit
    else:
        normalized_value = parsed_value
        unit = original_unit

    return NormalizationResult(
        raw=raw,
        normalized=normalized_value,
        unit=unit,
        valid=True,
        parsed_value=parsed_value,
        original_unit=original_unit,
    )


# ---------------------------------------------------------------------------
# Datas
# ---------------------------------------------------------------------------

_DATE_NUMERIC_RE = re.compile(r"^\s*(\d{1,4})[/-](\d{1,2})[/-](\d{1,4})\s*$")

_MONTH_NAMES_PT = {
    "janeiro": 1, "jan": 1,
    "fevereiro": 2, "fev": 2,
    "março": 3, "marco": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "maio": 5, "mai": 5,
    "junho": 6, "jun": 6,
    "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9,
    "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12,
}

_DATE_WITH_MONTH_NAME_RE = re.compile(
    r"^\s*(\d{1,2})\s+de\s+([a-zçãéóú]+)\s+de\s+(\d{4})\s*$", re.IGNORECASE
)


def _expand_two_digit_year(year: int) -> int:
    """"26" -> 2026, "99" -> 1999 - heurística padrão (ano < 70 vira 20xx,
    senão 19xx). Só usada quando o ano de fato veio com 2 dígitos."""
    if year < 70:
        return 2000 + year
    return 1900 + year


def normalize_date(raw: str) -> NormalizationResult:
    """Aceita "15/09/2026", "15-09-2026", "2026-09-15" (ISO, já no
    formato certo) e "15 de setembro de 2026" -> sempre devolve ISO
    "YYYY-MM-DD" como string em `normalized`. Data invertida/impossível
    (ex: "32/13/2026") volta com `valid=False` e `normalized=None` - NUNCA
    inventa uma data plausível a partir de uma inválida."""
    s = (raw or "").strip()

    month_name_match = _DATE_WITH_MONTH_NAME_RE.match(s)
    if month_name_match:
        day_s, month_name, year_s = month_name_match.groups()
        month = _MONTH_NAMES_PT.get(month_name.lower())
        if month is None:
            return NormalizationResult(raw=raw, valid=False)
        try:
            d = date(int(year_s), month, int(day_s))
        except ValueError:
            return NormalizationResult(raw=raw, valid=False)
        return NormalizationResult(raw=raw, normalized=d.isoformat(), valid=True)

    numeric_match = _DATE_NUMERIC_RE.match(s)
    if numeric_match:
        a, b, c = numeric_match.groups()
        # ISO (ano primeiro, 4 dígitos): YYYY-MM-DD
        if len(a) == 4:
            year, month, day = int(a), int(b), int(c)
        else:
            # BR (dia primeiro): DD/MM/YYYY ou DD/MM/YY
            day, month = int(a), int(b)
            year = int(c) if len(c) == 4 else _expand_two_digit_year(int(c))
        try:
            d = date(year, month, day)
        except ValueError:
            return NormalizationResult(raw=raw, valid=False)
        return NormalizationResult(raw=raw, normalized=d.isoformat(), valid=True)

    return NormalizationResult(raw=raw, valid=False)


# ---------------------------------------------------------------------------
# Identificadores fiscais/comerciais (EAN, NCM, CEST)
# ---------------------------------------------------------------------------

_EAN_VALID_LENGTHS = (8, 12, 13, 14)


def _gtin_check_digit(digits_without_check: str) -> int:
    """Dígito verificador padrão GTIN (funciona igual pra EAN-8, UPC-A/
    GTIN-12, EAN-13 e GTIN-14 - o peso alternado 3/1 é sempre contado a
    partir do dígito mais à DIREITA de `digits_without_check`, então o
    mesmo algoritmo serve pra qualquer um dos quatro tamanhos)."""
    total = 0
    for i, ch in enumerate(reversed(digits_without_check)):
        weight = 3 if i % 2 == 0 else 1
        total += int(ch) * weight
    return (10 - (total % 10)) % 10


def normalize_ean(raw: str) -> NormalizationResult:
    """Aceita EAN-8/UPC-A(GTIN-12)/EAN-13/GTIN-14, com ou sem espaços/
    hífen. Valida o dígito verificador de verdade (não só a contagem de
    dígitos) - "7891019125302" é um EAN-13 válido, mudar o último dígito
    pra "...301" já reprova. `normalized` só vem preenchido quando
    `valid=True`."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) not in _EAN_VALID_LENGTHS:
        return NormalizationResult(raw=raw, valid=False)
    body, check_digit = digits[:-1], digits[-1]
    if _gtin_check_digit(body) != int(check_digit):
        return NormalizationResult(raw=raw, valid=False)
    return NormalizationResult(raw=raw, normalized=digits, valid=True)


def normalize_ncm(raw: str) -> NormalizationResult:
    """NCM é sempre 8 dígitos (com ou sem os pontos de exibição, ex:
    "3209.10.10" == "32091010"). PHX-FIX (ligação com a tabela oficial,
    ncm_lookup.py, 2026-09-06): o comentário original deste módulo dizia
    que validar contra a tabela real da Receita "é responsabilidade de
    uma fase de validação/regra de negócio, não do Normalizer" — essa
    fase agora existe (ncm_lookup.py, ~10.515 NCM extraídos da Res. Gecex
    vigente). `valid` volta a significar o que os consumidores (ex.:
    candidate_engine.py, que calibra confiança 0.9/0.4 por esse booleano)
    sempre esperaram: "é um NCM real", não só "tem 8 dígitos". Checado
    contra todo NCM já usado nos testes existentes antes desta mudança —
    nenhum ficou órfão."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 8:
        return NormalizationResult(raw=raw, valid=False)
    if not ncm_exists(digits):
        return NormalizationResult(raw=raw, normalized=digits, valid=False)
    return NormalizationResult(raw=raw, normalized=digits, valid=True)


def normalize_cest(raw: str) -> NormalizationResult:
    """CEST é sempre 7 dígitos (ex: "24.001.00" == "2400100" - o mesmo
    formato visto no documento real do usuário). PHX-FIX (ligação com
    cest_lookup.py, 2026-09-06): mesmo raciocínio do `normalize_ncm`
    acima — `valid` agora exige existência real na tabela oficial CEST↔NCM,
    não só formato."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 7:
        return NormalizationResult(raw=raw, valid=False)
    formatado = f"{digits[0:2]}.{digits[2:5]}.{digits[5:7]}"
    if not cest_exists(formatado):
        return NormalizationResult(raw=raw, normalized=digits, valid=False)
    return NormalizationResult(raw=raw, normalized=digits, valid=True)


# ---------------------------------------------------------------------------
# Telefone / e-mail
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_phone_br(raw: str) -> NormalizationResult:
    """Telefone brasileiro (com ou sem "+55"/"55", com ou sem DDD,
    formatado ou não) -> "+55DDNNNNNNNNN" (13 dígitos com código do país,
    DDD e número, sem nenhuma pontuação). Válido só quando o número LOCAL
    (sem o "55" do país) tem 10 dígitos (fixo, DDD+8) ou 11 (celular,
    DDD+9) - qualquer outra contagem de dígitos volta `valid=False`."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("55") and len(digits) in (12, 13):
        local = digits[2:]
    else:
        local = digits
    if len(local) not in (10, 11):
        return NormalizationResult(raw=raw, valid=False)
    return NormalizationResult(raw=raw, normalized=f"+55{local}", valid=True)


def normalize_email(raw: str) -> NormalizationResult:
    """Confere formato básico (`algo@algo.algo`) e normaliza pra
    minúsculo/sem espaço nas pontas - NÃO confere se o domínio existe de
    verdade (isso exigiria rede, fora de escopo de um Normalizer
    determinístico e offline)."""
    s = (raw or "").strip()
    if not _EMAIL_RE.match(s):
        return NormalizationResult(raw=raw, valid=False)
    return NormalizationResult(raw=raw, normalized=s.lower(), valid=True)


# ---------------------------------------------------------------------------
# Texto livre rotulado (PHX-NEW, 2026-08-29 - expansão de vocabulário V2,
# grupo "determinístico" pedido pelo usuário depois de validar a Fase 10
# contra o XLSX real do MarketUP: marca/modelo/tags/itens
# inclusos/especificações/nome explícito são texto livre, não têm
# checksum nem formato numérico - a única coisa determinística aqui é "um
# rótulo explícito precede o valor", nunca o CONTEÚDO do valor em si.
# Continua zero LLM: só limpeza mecânica (tira ruído de HTML residual,
# tira espaço nas pontas) - nenhuma interpretação de significado.
# ---------------------------------------------------------------------------

_HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^<>]*>")


def normalize_labeled_text(raw: str) -> NormalizationResult:
    """Valor de texto livre atrás de um rótulo explícito (Marca:/Modelo:/
    Itens Inclusos:/Especificações:/Nome do Produto:/Nome na Loja
    Virtual:). Só remove ruído de marcação HTML residual (`<b>`/`</b>`/
    `<p>`/...) que sobra quando o Candidate Engine corta o valor antes de
    uma tag de fechamento (ver `_labeled_text_pattern` em
    `candidate_engine.py` - achado real: "<b>Marca:</b> <b>Bonafont
    (Danone) |</b>") e espaço nas pontas - NUNCA interpreta o conteúdo
    (não decide se "Bonafont (Danone)" é uma marca real, só limpa o que
    já foi capturado). Vazio depois de limpar -> `valid=False`, `raw`
    preservado (mesma regra de sempre: achar rótulo != ter valor de
    verdade)."""
    cleaned = _HTML_TAG_RE.sub("", raw or "").strip()
    if not cleaned:
        return NormalizationResult(raw=raw, valid=False)
    return NormalizationResult(raw=raw, normalized=cleaned, valid=True)


def normalize_tag_list(raw: str) -> NormalizationResult:
    """"tinta suvinil; toque de seda; ...; secagem rápida." -> string
    normalizada com cada tag limpa (sem ponto final solto, sem espaço nas
    pontas) e rejuntada com "; " - preserva a forma de LISTA como uma
    string só, exatamente como a própria coluna real "Tags" do MarketUP
    guarda o dado (confirmado inspecionando o XLSX real: uma célula de
    texto só, tags separadas por ";" - não existe suporte a lista no
    `Candidate.normalized_value` hoje, e não seria o formato certo pro
    Excel de qualquer forma). Aceita ";" ou "," como separador (achado
    real: os dois aparecem nos documentos-fonte)."""
    cleaned = _HTML_TAG_RE.sub("", raw or "").strip()
    if not cleaned:
        return NormalizationResult(raw=raw, valid=False)
    tags = [part.strip(" .") for part in re.split(r"[;,]", cleaned)]
    tags = [t for t in tags if t]
    if not tags:
        return NormalizationResult(raw=raw, valid=False)
    return NormalizationResult(raw=raw, normalized="; ".join(tags), valid=True)


def normalize_currency_brl_commercial(raw: str) -> NormalizationResult:
    """PHX-NEW (2026-08-29, vocabulário comercial de preços - grupo
    pedido pelo usuário DEPOIS do grupo determinístico, especificação
    fechada por ele antes do código): mesmo parsing de
    `normalize_currency_brl`, mas com `unit`/`original_unit`/
    `parsed_value` preenchidos - formato exato pedido por ele:
    `{"raw_value": "R$ 19,90", "parsed_value": 19.9, "normalized_value":
    19.9, "unit": "BRL", "original_unit": "R$"}`. Usada SÓ pelos NOVOS
    field_types comerciais (`cost_price`/`retail_price`/
    `wholesale_price`/`compare_at_price`/`sale_price`) - `price`/
    `price_min`/`price_max` (Fase 4 já fechada, "preço observado na
    fonte") continuam usando `normalize_currency_brl` sem unidade,
    contrato intocado de propósito, mesma disciplina de nunca mexer em
    fase já aprovada sem necessidade real."""
    s = (raw or "").strip()
    stripped = re.sub(r"(?i)^r\$\s*", "", s)
    value = _parse_br_or_plain_number(stripped)
    if value is None:
        return NormalizationResult(raw=raw, valid=False)
    rounded = round(value, 2)
    return NormalizationResult(
        raw=raw, normalized=rounded, unit="BRL", valid=True,
        parsed_value=rounded, original_unit="R$",
    )


def normalize_quantity_count(raw: str) -> NormalizationResult:
    """"12 unidades" / "12 un" / "12" -> `parsed_value`/`normalized`=12.0,
    `unit="unit"` SEMPRE - é uma CONTAGEM por definição (nunca kg/m/l,
    nunca moeda), usada por `wholesale_min_quantity` ("Quantidade Mínima
    Atacado: 12 unidades" - pedido explícito do usuário: "nada de
    misturar quantidade com moeda"). `original_unit` preserva a palavra
    exata da fonte (ex: "unidades"), só pra auditoria - diferente das
    unidades dimensionais, aqui não existe conversão nenhuma: 12 unidades
    é sempre 12, não importa a palavra usada."""
    s = (raw or "").strip()
    match = re.match(r"^\s*(?P<number>[\d.,]+)\s*(?P<word>[A-Za-zÀ-ÿ]*)\s*$", s)
    if not match:
        return NormalizationResult(raw=raw, valid=False)
    value = _parse_br_or_plain_number(match.group("number"))
    if value is None:
        return NormalizationResult(raw=raw, valid=False)
    original_word = match.group("word") or None
    return NormalizationResult(
        raw=raw, normalized=value, unit="unit", valid=True,
        parsed_value=value, original_unit=original_word,
    )


def normalize_html_single_line(raw: str) -> NormalizationResult:
    """Valida que um bloco de descrição em HTML é DE LINHA ÚNICA (pedido
    explícito do usuário: "a descrição deve continuar em HTML Rich Text
    de linha única" - confirmado como requisito real inspecionando a
    coluna "Descrição do Produto" do XLSX do MarketUP). Aceita o texto
    como veio (só tira espaço nas pontas) quando não tem quebra de linha
    literal; rejeita (`valid=False`, `raw` preservado) quando tem -
    NUNCA tenta "consertar" juntando linhas sozinho, isso seria inventar
    uma junção que pode mudar o sentido do HTML."""
    s = (raw or "").strip()
    if not s:
        return NormalizationResult(raw=raw, valid=False)
    if "\n" in raw or "\r" in raw:
        return NormalizationResult(raw=raw, valid=False)
    return NormalizationResult(raw=raw, normalized=s, valid=True)
