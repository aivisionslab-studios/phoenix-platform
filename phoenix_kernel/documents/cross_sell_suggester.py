"""Sugestão de combo/cross-sell — Passo 2 da colaboração (determinístico).

Cruza os PRODUTOS REAIS extraídos pelo pipeline com os QUADRANTES DE MARGEM
capturados pelo Passo 1 (business_strategy_extractor.py), e sugere combos
"produto-isca + produto-complementar" — a mesma lógica que o texto original
já descrevia ("Nunca venda um destilado sem empurrar esse quadrante"), só que
aplicada programaticamente a TODOS os produtos do catálogo, não só aos poucos
exemplos que o autor citou manualmente.

Determinístico, sem LLM: casamento produto->quadrante por sobreposição de
tokens (mesmo princípio do fiscal_rag.py — recuperação, não invenção); a
justificativa de cada sugestão é montada a partir do texto que a estratégia
já explicou (margem, função), nunca texto novo inventado.

Genérico: não assume nomes fixos de quadrante ("O Boi", "Quadrante 1") — o
papel de cada quadrante (isca/âncora vs. complementar) é decidido pela FAIXA
DE MARGEM capturada (menor margem = âncora, atrai cliente; maior margem =
complementar, gera lucro), então funciona com qualquer documento que descreva
uma estratégia parecida, com nomes de quadrante diferentes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from phoenix_kernel.documents.business_strategy_extractor import PricingQuadrant

_STOP = {
    "de", "da", "do", "com", "e", "a", "o", "para", "em", "kg", "g", "ml", "l",
    "un", "premium", "original", "tradicional",
}


def _tokens(text: str) -> set[str]:
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return {w for w in t.split() if len(w) > 2 and w not in _STOP}


@dataclass
class ComboSuggestion:
    anchor_product: str          # produto-isca (menor margem)
    anchor_quadrant: str         # nome do quadrante âncora
    complementary_product: str   # produto sugerido pra vender junto
    complementary_quadrant: str  # nome do quadrante complementar
    complementary_margin_label: str
    justification: str           # montada do texto já capturado, não inventada


def _quadrant_avg_margin(q: PricingQuadrant) -> float:
    """Margem média do quadrante, para ordenar âncora vs. complementar. Um
    quadrante sem margem numérica capturada vai para o fim (não decide)."""
    if q.margin_min_pct is None or q.margin_max_pct is None:
        return float("inf")
    return (q.margin_min_pct + q.margin_max_pct) / 2


def rank_quadrants_by_margin(quadrants: list[PricingQuadrant]) -> list[PricingQuadrant]:
    """Ordena por margem crescente — o(s) primeiro(s) são âncora/isca; os
    últimos são os de maior lucro (complementares)."""
    return sorted(quadrants, key=_quadrant_avg_margin)


def match_product_to_quadrant(
    product_name: str, quadrants: list[PricingQuadrant], min_score: float = 0.2,
) -> tuple[PricingQuadrant, float] | None:
    """Casa um produto real com o quadrante cujo produto-exemplo mais se
    parece com ele. Compara contra CADA exemplo individualmente (não a lista
    toda junta — misturar os exemplos de um quadrante numa sacola só dilui a
    marca real, porque "Heineken" perde força ao lado de "Coca-Cola"/
    "Cigarros" citados no MESMO quadrante para OUTRO produto-exemplo).

    Usa coeficiente de sobreposição (interseção / MENOR conjunto), não
    Jaccard (interseção / união) — um produto real tem várias palavras
    próprias (marca, ml, adjetivo) que o exemplo genérico não tem; Jaccard
    penaliza isso demais. Sem match forte o suficiente, devolve None — nunca
    força um produto num quadrante que não parece com ele."""
    pt = _tokens(product_name)
    if not pt:
        return None
    best: tuple[PricingQuadrant, float] | None = None
    for q in quadrants:
        for example in q.example_products:
            et = _tokens(example)
            if not et:
                continue
            inter = len(pt & et)
            smaller = min(len(pt), len(et))
            score = inter / smaller if smaller else 0.0
            if score >= min_score and (best is None or score > best[1]):
                best = (q, score)
    return best


def suggest_combos(
    products: list[dict],
    quadrants: list[PricingQuadrant],
    *,
    name_field: str = "Descrição",
    max_suggestions_per_anchor: int = 2,
    max_anchors: int | None = None,
) -> list[ComboSuggestion]:
    """Gera sugestões de combo: para cada produto casado com o quadrante
    ÂNCORA (menor margem), sugere produtos casados com quadrantes de margem
    MAIOR — a mesma lógica de "isca atrai o cliente, complementar gera lucro"
    que a estratégia original descreveu, agora aplicada a todo o catálogo.

    Sem quadrantes capturados (documento sem esse padrão), devolve lista
    vazia — nunca inventa uma estratégia que o documento não descreveu.
    """
    if not quadrants or len(quadrants) < 2:
        return []

    ranked = rank_quadrants_by_margin(quadrants)
    anchor_quadrant = ranked[0]
    complementary_quadrants = ranked[1:]

    anchors: list[str] = []
    seen_anchors: set[str] = set()
    complementary_by_quadrant: dict[int, list[str]] = {}
    seen_complementary: dict[int, set[str]] = {}

    for row in products:
        name = str(row.get(name_field, "") or "").strip()
        if not name:
            continue
        match = match_product_to_quadrant(name, quadrants)
        if match is None:
            continue
        matched_quadrant, _score = match
        if matched_quadrant.number == anchor_quadrant.number:
            if name not in seen_anchors:
                seen_anchors.add(name)
                anchors.append(name)
        else:
            seen = seen_complementary.setdefault(matched_quadrant.number, set())
            if name not in seen:
                seen.add(name)
                complementary_by_quadrant.setdefault(matched_quadrant.number, []).append(name)

    if max_anchors is not None:
        anchors = anchors[:max_anchors]

    suggestions: list[ComboSuggestion] = []
    for anchor_name in anchors:
        # alterna entre os quadrantes complementares (1 produto de cada por
        # vez), em vez de esgotar um só — dá sugestões mais variadas (não só
        # "sempre Pringles", também Vinho/Gelo quando fizer sentido).
        cursors = {q.number: 0 for q in complementary_quadrants}
        added = 0
        while added < max_suggestions_per_anchor:
            progressed = False
            for comp_q in complementary_quadrants:
                if added >= max_suggestions_per_anchor:
                    break
                pool = complementary_by_quadrant.get(comp_q.number, [])
                idx = cursors[comp_q.number]
                if idx >= len(pool):
                    continue
                comp_name = pool[idx]
                cursors[comp_q.number] += 1
                progressed = True
                justification = (
                    f"'{anchor_name}' atrai o cliente (quadrante {anchor_quadrant.name}, "
                    f"{anchor_quadrant.margin_label or 'margem de entrada'}). "
                    f"Ofereça junto '{comp_name}' (quadrante {comp_q.name}, "
                    f"{comp_q.margin_label or 'margem maior'}"
                    + (f", {comp_q.margin_min_pct:.0f}% a {comp_q.margin_max_pct:.0f}%"
                       if comp_q.margin_min_pct is not None else "")
                    + ") para converter o giro em lucro real."
                )
                suggestions.append(ComboSuggestion(
                    anchor_product=anchor_name,
                    anchor_quadrant=anchor_quadrant.name,
                    complementary_product=comp_name,
                    complementary_quadrant=comp_q.name,
                    complementary_margin_label=comp_q.margin_label,
                    justification=justification,
                ))
                added += 1
            if not progressed:
                break  # nenhum quadrante complementar tem mais produtos

    return suggestions


def make_quadrant_row_enricher(quadrants: list[PricingQuadrant], name_field: str = "Descrição"):
    """Passo 3: constrói um `row_enricher` (para `smart_filler.smart_fill_xlsx`)
    que casa cada linha com um quadrante de estratégia (Passos 1/2) e anota
    `row["_quadrant_context"]` com o papel (âncora/complementar) e a margem —
    para o gerador de gatilho de venda escolher o tom certo.

    Sem quadrantes capturados, devolve um enricher que não faz nada (linhas
    seguem sem contexto extra, o gerador cai no template genérico)."""
    if not quadrants or len(quadrants) < 2:
        def _noop(row: dict) -> None:
            return None
        return _noop

    ranked = rank_quadrants_by_margin(quadrants)
    anchor_number = ranked[0].number

    def _enrich(row: dict) -> None:
        name = None
        for key in row.keys():
            if isinstance(key, str) and key.strip().lower() == name_field.strip().lower():
                name = row.get(key)
                break
        if not name:
            return
        match = match_product_to_quadrant(str(name), quadrants)
        if match is None:
            return
        q, _score = match
        row["_quadrant_context"] = {
            "role_hint": "ancora" if q.number == anchor_number else "complementar",
            "margin_label": q.margin_label,
            "quadrant_name": q.name,
        }

    return _enrich
