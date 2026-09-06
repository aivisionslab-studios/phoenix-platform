"""Detecção de formato — com suporte a documentos MISTOS (Camada B, evolução).

PHX-FIX (2026-09, 2ª rodada da colaboração com o GLM): a primeira tentativa de
suporte a formatos mistos reintroduziu o bug do "desempate de tabela" já
corrigido antes — qualquer linha com muitos delimitadores (';'/tab) virava uma
nova tabela, MESMO dentro de um bloco rotulado/numerado já em andamento,
fragmentando produtos reais em centenas de blocos-tabela falsos (testado: doc
de construção foi de 125 blocos corretos para 354 fragmentados; conveniência de
296 para 742). A causa: o detector de linha-de-tabela não tinha memória de
"já estou processando um produto" — tratava toda linha isoladamente.

A correção: um sinal de tabela só INICIA um bloco novo quando NÃO estamos no
meio de um bloco rotulado/numerado já aberto (guarda de contexto). Dentro de um
produto já identificado, uma linha com múltiplos ';' é DADO daquele produto
(ex.: "NCM: X; CEST: Y; Peso: Z"), não uma nova linha de tabela.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class DocumentFormat(Enum):
    TABLE = "table"
    LABELED_BLOCKS = "labeled_blocks"
    NUMBERED_LIST = "numbered_list"
    HIGHLIGHTED_TITLE = "highlighted_title"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass
class Block:
    block_id: str
    text: str
    lines: list = field(default_factory=list)
    title: str = ""
    number: int | None = None
    has_structured_data: bool = False
    format: DocumentFormat = DocumentFormat.UNKNOWN  # formato DESTE bloco


@dataclass
class DetectionResult:
    format: DocumentFormat
    blocks: list
    confidence: float = 0.0


_NUM_TITLE = re.compile(r'^(\d{1,3})\.\s+([A-ZÀ-Ú].{4,158})$')

# PHX-NEW (2026-09, defesa extra além do _STRICT_DATA_HINT): "N. Quadrante:
# NOME (Subtítulo)" é um padrão CONHECIDO de título de ESTRATÉGIA comercial
# (matriz de margem por categoria), nunca nome de produto — mesmo que
# eventualmente passe no lookahead de dado real (ex.: se a "Função:" citar um
# preço com valor numérico por coincidência). Excluído aqui explicitamente,
# em vez de depender só da heurística de prosa. Ver
# business_strategy_extractor.py, que CAPTURA esse conteúdo como dado
# estruturado em vez de simplesmente descartá-lo.
_QUADRANT_TITLE_EXCLUSION = re.compile(r'(?i)^\d{1,3}\.\s*Quadrante:')
_LABELED_MARK = re.compile(r"(?i)\[dados\s+estruturados")
_DATA_HINT = re.compile(r"(?i)\b(ncm|cest|cfop|ean|peso|pre[çc]o|altura|largura)\b")

# PHX-FIX (2026-09, achado real: "O preço tem que ser o 'panfleto' da loja"):
# _DATA_HINT (acima) casa a PALAVRA solta em qualquer lugar, inclusive em
# prosa comum de um documento de estratégia de vendas — "preço", "margem",
# "peso" aparecem em frases normais sem serem dado de produto nenhum. Isso
# fazia o lookahead de título numerado confundir um cabeçalho de seção
# ("1. Quadrante: O BOI...") com produto real, porque a discussão de
# estratégia MENCIONA "preço" em prosa duas linhas depois. Usado só na
# decisão de boundary (não no has_structured_data geral, que é informativo),
# este critério mais rígido exige a palavra seguida de perto por um NÚMERO —
# o padrão de um rótulo de campo real ("NCM: 123", "Peso (Kg): 0,970"), não
# uma palavra solta numa frase.
_STRICT_DATA_HINT = re.compile(
    r"(?i)\b(ncm|cest|cfop|ean)\b[^\d\n]{0,12}\d|\b(peso|pre[çc]o|altura|largura)\b[^\d\n]{0,18}\d"
)

# formatos "de produto" — enquanto estamos dentro de um bloco desses, um sinal
# de tabela não deve fragmentar o bloco (guarda de contexto do fix).
_PRODUCT_FORMATS = {DocumentFormat.LABELED_BLOCKS, DocumentFormat.NUMBERED_LIST,
                    DocumentFormat.HIGHLIGHTED_TITLE}


def _is_table_row(line: str) -> bool:
    """3+ colunas (2+ delimitadores) — mais permissivo que antes, mas seguro
    porque só vale fora de um bloco de produto já aberto (guarda de contexto)."""
    return line.count("\t") >= 2 or line.count(";") >= 2


def _looks_like_title(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 160:
        return False
    if _DATA_HINT.search(s):
        return False
    if s.endswith((".", "!", "?", ":")):
        return False
    return any(c.isupper() for c in s)


def _followed_by_data_signal(lines: list[str], idx: int, lookahead: int = 6) -> bool:
    """Olha as próximas `lookahead` linhas a partir de `idx` (exclusive) e
    diz se alguma parece dado de produto (campo estruturado ou marcador). Um
    título numerado de produto REAL é seguido de perto por dados; um
    falso-positivo (cabeçalho de categoria tipo "1. Linha Suvinil...", comum
    em documentos com índice/sumário) é seguido só de texto corrido."""
    for j in range(idx + 1, min(idx + 1 + lookahead, len(lines))):
        s = lines[j].strip()
        if _STRICT_DATA_HINT.search(s) or _LABELED_MARK.search(s):
            return True
        if _NUM_TITLE.match(s):  # já bateu no próximo título — não teve dado
            return False
    return False


def detect_format(text: str) -> DetectionResult:
    """Segmenta por sinal de início de produto, com formato POR BLOCO.
    Um sinal de tabela só abre bloco novo fora de um bloco de produto aberto —
    isso evita fragmentar dados internos (';'-separados) de blocos rotulados
    ou numerados. Um título numerado só é boundary se for seguido de perto por
    dados de produto — evita confundir cabeçalho de categoria/índice (comum em
    documentos de blocos rotulados) com produto numerado de verdade."""
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    blocks: list[Block] = []
    current_lines: list[str] = []
    current_format = DocumentFormat.UNKNOWN
    block_idx = 0

    def flush():
        nonlocal block_idx, current_lines, current_format
        if not current_lines:
            return
        txt = "\n".join(current_lines)
        has_data = bool(_DATA_HINT.search(txt))
        title, num = "", None
        fmt = current_format
        if fmt == DocumentFormat.NUMBERED_LIST:
            m = _NUM_TITLE.match(current_lines[0].strip())
            if m:
                num = int(m.group(1))
                title = m.group(2).strip()
        elif fmt == DocumentFormat.LABELED_BLOCKS:
            if not _LABELED_MARK.search(current_lines[0]):
                title = current_lines[0].strip()
        elif fmt == DocumentFormat.HIGHLIGHTED_TITLE:
            title = current_lines[0].strip()
        elif fmt == DocumentFormat.TABLE:
            title = current_lines[0].strip() if len(current_lines) == 1 else ""
        blocks.append(Block(f"B{block_idx:05d}", txt, list(current_lines), title, num, has_data, fmt))
        block_idx += 1
        current_lines = []

    for idx, line in enumerate(lines):
        s = line.strip()

        # sinal 1: título numerado — só é boundary se for seguido de perto
        # por dado de produto (evita cabeçalho de categoria/índice falso), E
        # nunca se for um título de estratégia comercial conhecido
        # ("Quadrante:") — defesa extra, independente do lookahead.
        m_num = _NUM_TITLE.match(s)
        if (m_num and not _QUADRANT_TITLE_EXCLUSION.match(s)
                and _followed_by_data_signal(lines, idx)):
            flush()
            current_lines = [line]
            current_format = DocumentFormat.NUMBERED_LIST
            continue

        # sinal 2: marcador de bloco rotulado. Se já estamos DENTRO de um
        # produto numerado/destacado que acabamos de abrir (ex.: "63. Nome"
        # seguido de "[DADOS ESTRUTURADOS]"), o marcador é DADO daquele
        # produto, não uma troca de formato — sem essa guarda, o marcador
        # sobrescrevia numbered_list->labeled_blocks e fragmentava a
        # conveniência (296 produtos corretos viravam 228 misturados).
        if _LABELED_MARK.search(s):
            if current_format in (DocumentFormat.NUMBERED_LIST, DocumentFormat.HIGHLIGHTED_TITLE) and current_lines:
                current_lines.append(line)
                continue
            if current_format == DocumentFormat.LABELED_BLOCKS and current_lines:
                last = current_lines.pop() if len(current_lines) > 0 else None
                flush()
                current_lines = ([last] if last else []) + [line]
            else:
                current_lines.append(line)
            current_format = DocumentFormat.LABELED_BLOCKS
            continue

        # sinal 3: linha de tabela — SÓ conta como boundary se NÃO estamos
        # dentro de um bloco de produto já aberto (guarda de contexto do fix).
        if _is_table_row(s) and current_format not in _PRODUCT_FORMATS:
            flush()
            current_lines = [line]
            current_format = DocumentFormat.TABLE
            flush()  # cada linha de tabela é o próprio bloco (1 produto/linha)
            current_format = DocumentFormat.TABLE
            continue

        # sinal 4: título em destaque — só troca de bloco se o bloco atual já
        # tem dado (não corta um produto no meio) e não estamos em bloco
        # rotulado/numerado ainda não fechado por um sinal forte.
        if (_looks_like_title(s) and current_lines
                and current_format in (DocumentFormat.HIGHLIGHTED_TITLE, DocumentFormat.UNKNOWN)
                and bool(_DATA_HINT.search("\n".join(current_lines)))):
            flush()
            current_lines = [line]
            current_format = DocumentFormat.HIGHLIGHTED_TITLE
            continue

        # linha comum: dado do bloco atual
        current_lines.append(line)
        if current_format == DocumentFormat.UNKNOWN:
            txt = "\n".join(current_lines)
            if _LABELED_MARK.search(txt):
                current_format = DocumentFormat.LABELED_BLOCKS
            elif _DATA_HINT.search(txt):
                current_format = DocumentFormat.HIGHLIGHTED_TITLE

    flush()

    fmts = {b.format for b in blocks if b.format != DocumentFormat.UNKNOWN}
    if len(fmts) > 1:
        global_fmt = DocumentFormat.MIXED
    elif fmts:
        global_fmt = next(iter(fmts))
    else:
        global_fmt = DocumentFormat.UNKNOWN
    return DetectionResult(global_fmt, blocks, 1.0 if blocks else 0.0)
