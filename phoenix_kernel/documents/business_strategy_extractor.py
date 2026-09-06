"""Extrator de estratégia comercial — captura em vez de descartar.

Nasceu de um achado real: o documento-fonte tinha uma matriz de margem por
categoria ("Quadrante: O BOI", "Quadrante: O CARRINHO"...) que o detector de
produto confundia com produto de verdade (bug corrigido em structure_detector
— ver PHX-FIX "achado real: O preço tem que ser o panfleto da loja"). Depois
de corrigir o bug, esse conteúdo passou a ser simplesmente IGNORADO — mas ele
tem valor real: é conhecimento de negócio escrito por um humano (ou LLM a
pedido do usuário) sobre como precificar por categoria.

Este módulo CAPTURA esse conteúdo como dado estruturado (nunca mais jogado
fora), para virar uma aba extra na planilha final ou ser reaproveitado por
outras features (ex.: sugestão de combo/cross-sell, Passo 3 da mesma
colaboração).

Padrão reconhecido (visto no documento real, 4 ocorrências):

    N. Quadrante: NOME (Subtítulo)
    Produtos: item1, item2, item3.
    Estratégia: Margem <rótulo> (MIN% a MAX%).
    Função: texto livre explicando o papel do quadrante.

Determinístico: regex + parsing de texto, sem LLM. Se o documento não usa a
palavra "Quadrante", ou usa outro layout, simplesmente não encontra nada —
nunca inventa uma regra de negócio que o documento não descreveu.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class PricingQuadrant:
    """Uma categoria de estratégia de precificação extraída do documento."""
    number: int
    name: str                      # "O BOI"
    subtitle: str                  # "Volume / Isca"
    example_products: list[str] = field(default_factory=list)
    margin_label: str = ""         # "Margem Mínima"
    margin_min_pct: float | None = None
    margin_max_pct: float | None = None
    role: str = ""                 # texto livre do "Função:"


_QUADRANT_TITLE = re.compile(
    r'^\d{1,3}\.\s*Quadrante:\s*([^\(]+?)\s*(?:\(([^)]*)\))?\s*$', re.IGNORECASE
)
_PRODUCTS_LINE = re.compile(r'(?i)^produtos:\s*(.+)$')
_STRATEGY_LINE = re.compile(
    r'(?i)^estrat[ée]gia:\s*(.+?)\s*\(([\d.,]+)\s*%?\s*a\s*([\d.,]+)\s*%\)\.?\s*$'
)
_ROLE_LINE = re.compile(r'(?i)^fun[çc][ãa]o:\s*(.+)$')


def is_quadrant_title(line: str) -> bool:
    """Reconhece o título de um quadrante de estratégia — usado também pelo
    structure_detector como exclusão explícita (nunca tratar como nome de
    produto, mesmo que passe em outros critérios)."""
    return bool(_QUADRANT_TITLE.match(line.strip()))


def extract_pricing_quadrants(text: str) -> list[PricingQuadrant]:
    """Varre o texto procurando o padrão de quadrante de estratégia e devolve
    a lista estruturada. Nunca inventa: um quadrante sem "Produtos:"/
    "Estratégia:"/"Função:" reconhecíveis ainda é capturado com os campos que
    achou, deixando o resto vazio (não é dado fiscal, então não precisa da
    mesma cautela extrema — mas também não inventa texto)."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    quadrants: list[PricingQuadrant] = []
    current: PricingQuadrant | None = None

    for line in lines:
        m_title = _QUADRANT_TITLE.match(line)
        if m_title:
            if current is not None:
                quadrants.append(current)
            num_m = re.match(r'^(\d{1,3})\.', line)
            current = PricingQuadrant(
                number=int(num_m.group(1)) if num_m else len(quadrants) + 1,
                name=m_title.group(1).strip(),
                subtitle=(m_title.group(2) or "").strip(),
            )
            continue
        if current is None:
            continue  # texto antes do 1º quadrante não pertence a nenhum

        m_prod = _PRODUCTS_LINE.match(line)
        if m_prod:
            items = [p.strip().rstrip(".") for p in m_prod.group(1).split(",") if p.strip()]
            current.example_products = items
            continue

        m_strat = _STRATEGY_LINE.match(line)
        if m_strat:
            current.margin_label = m_strat.group(1).strip()
            try:
                current.margin_min_pct = float(m_strat.group(2).replace(",", "."))
                current.margin_max_pct = float(m_strat.group(3).replace(",", "."))
            except ValueError:
                pass
            continue

        m_role = _ROLE_LINE.match(line)
        if m_role:
            current.role = m_role.group(1).strip()
            continue

    if current is not None:
        quadrants.append(current)

    return quadrants
