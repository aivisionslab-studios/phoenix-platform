"""Consulta à Tabela NCM oficial (governo) — existência real e busca por texto.

Diferença do fiscal_rag.py: aquele módulo sugere NCM a partir do HISTÓRICO
JÁ AUDITADO da própria empresa (produtos que ela mesma já classificou antes).
Este módulo consulta a TABELA OFICIAL do governo (Res. Gecex, publicada pela
Receita/Camex) — os ~10.500 códigos NCM de 8 dígitos que realmente existem,
com a descrição oficial de cada um. São complementares: o fiscal_rag acerta
mais quando a empresa já tem histórico; este módulo funciona mesmo pra
produtos totalmente novos, e serve pra VALIDAR que um código realmente existe
(não só que tem o formato certo — 8 dígitos numéricos passa no formato mas
pode não corresponder a nenhum NCM real).

Fonte: Tabela_NCM_Desc_Concatenada_Vigente_20260427.xlsx (vigente em
27/04/2026, Res. Gecex nº 812/2025), convertida uma vez pra
data/ncm_tabela_oficial.json — carregar o Excel inteiro a cada consulta seria
lento; o JSON compacto carrega uma vez por processo e fica em memória.

Nunca inventa: `search_ncm_by_text` é recuperação (mesmo princípio do
fiscal_rag) — devolve o código oficial mais parecido, com pontuação, pra
auditoria humana decidir. Sem correspondência forte o suficiente, devolve
lista vazia — não força um palpite.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "ncm_tabela_oficial.json"

_STOP = {
    "de", "da", "do", "para", "com", "e", "a", "o", "em", "the", "outros",
    "outras", "outro", "outra", "kg", "g", "ml", "l", "cm", "mm", "un",
}


def _singular(palavra: str) -> str:
    """Normalização leve de plural — só o padrão mais comum e seguro do
    português (vogal + 's', ex.: "cavalos"->"cavalo", "produtos"->"produto").
    Deliberadamente NÃO cobre plurais irregulares ("reprodutor"/"reprodutores",
    "animal"/"animais") — um stemmer agressivo o suficiente pra cobrir esses
    corre risco de colidir palavras diferentes por engano, o que é pior
    (sugestão errada) do que não casar um plural específico (sem resultado,
    vai pra auditoria humana — a regra de ouro do projeto)."""
    if len(palavra) > 3 and palavra[-1] == "s" and palavra[-2] in "aeiou":
        return palavra[:-1]
    return palavra


def _tokens(text: str) -> frozenset[str]:
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return frozenset(_singular(w) for w in t.split() if len(w) > 2 and w not in _STOP)


def _only_digits(code: str) -> str:
    return re.sub(r"\D", "", str(code or ""))


@dataclass(frozen=True)
class NCMEntry:
    """Um código NCM real (8 dígitos) da tabela oficial."""
    codigo: str              # só dígitos, ex: "01012100"
    codigo_formatado: str    # ex: "0101.21.00"
    descricao: str           # descrição do nível folha, ex: "-- Reprodutores de raça pura"
    descricao_concatenada: str  # caminho hierárquico completo (capítulo > posição > ... > este)
    tokens_folha: frozenset = field(default_factory=frozenset, compare=False, repr=False)
    tokens_contexto: frozenset = field(default_factory=frozenset, compare=False, repr=False)


@lru_cache(maxsize=1)
def _load_table() -> dict[str, NCMEntry]:
    """Carrega a tabela oficial uma vez por processo (cache em memória)."""
    if not _DATA_PATH.exists():
        return {}
    with open(_DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    tabela: dict[str, NCMEntry] = {}
    for item in raw.get("entradas", []):
        tokens_folha = _tokens(item["descricao"])
        # PHX-FIX (achado real): a "descrição concatenada" inclui o capítulo
        # inteiro (nível mais genérico da hierarquia) — uma palavra pode
        # aparecer ali por coincidência de um item TOTALMENTE não relacionado
        # do mesmo capítulo (ex.: "cerveja" aparece no título do capítulo 23
        # -- "resíduos da fabricação de cerveja" -- mesmo numa linha sobre
        # "polpas de beterraba", nada a ver com vender cerveja de verdade).
        # Guardamos os tokens do CONTEXTO (ancestrais) separados dos da
        # FOLHA (a descrição específica deste código) pra pesar diferente:
        # bater na folha é sinal forte; bater só no contexto é sinal fraco.
        tokens_contexto = _tokens(item["descricao_concatenada"]) - tokens_folha
        entry = NCMEntry(
            codigo=item["codigo"],
            codigo_formatado=item["codigo_formatado"],
            descricao=item["descricao"],
            descricao_concatenada=item["descricao_concatenada"],
            tokens_folha=tokens_folha,
            tokens_contexto=tokens_contexto,
        )
        tabela[entry.codigo] = entry
    return tabela


def ncm_exists(codigo: str) -> bool:
    """Verifica se um NCM (8 dígitos) REALMENTE EXISTE na tabela oficial —
    não só se tem o formato certo. Um código com 8 dígitos numéricos passa
    na validação de formato, mas pode ser um NCM que nunca existiu (erro de
    digitação, código descontinuado, invenção)."""
    return _only_digits(codigo) in _load_table()


def get_ncm_entry(codigo: str) -> NCMEntry | None:
    """Devolve a entrada oficial completa (descrição real) para um NCM, ou
    None se o código não existir na tabela."""
    return _load_table().get(_only_digits(codigo))


def search_ncm_by_text(
    query: str, *, limit: int = 5, min_score: float = 0.3,
) -> list[tuple[NCMEntry, float]]:
    """Busca os NCM oficiais cuja descrição mais se parece com `query`
    (nome/descrição de produto). Palavra que bate na descrição ESPECÍFICA
    do código (nível folha, ex.: "-- Cerveja sem álcool") pesa 3x mais que
    palavra que só bate no contexto ancestral (capítulo/posição/subposição) —
    sem isso, uma palavra citada de passagem no título do capítulo (ex.:
    "cerveja" no capítulo de resíduos industriais) empataria com o produto
    de verdade. Contexto ainda importa: é o que permite achar "cavalo
    reprodutor" mesmo quando a linha-folha só diz "Reprodutores de raça
    pura" (o tipo de animal só aparece no nível de POSIÇÃO, acima).

    Devolve (entrada, score) ordenado por score decrescente, score em [0,1]
    (fração ponderada das palavras da busca encontradas). Sem nenhum
    resultado acima de `min_score`, devolve lista vazia — nunca força uma
    correspondência fraca."""
    qt = _tokens(query)
    if not qt:
        return []
    peso_max = len(qt) * 3  # melhor caso: toda palavra da busca bate na folha
    resultados: list[tuple[NCMEntry, float]] = []
    for entry in _load_table().values():
        pontos = 3 * len(qt & entry.tokens_folha) + 1 * len(qt & entry.tokens_contexto)
        if pontos == 0:
            continue
        score = pontos / peso_max
        if score >= min_score:
            resultados.append((entry, min(score, 1.0)))
    resultados.sort(key=lambda par: par[1], reverse=True)
    return resultados[:limit]


def table_size() -> int:
    """Quantos NCM reais estão carregados — útil pra diagnóstico/self-test."""
    return len(_load_table())
