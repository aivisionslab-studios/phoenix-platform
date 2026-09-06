"""Consulta à Tabela CEST↔NCM oficial — cest_lookup.py.

CEST (Código Especificador da Substituição Tributária) não depende só do
NCM — a tabela oficial registra cada CEST contra um PREFIXO de NCM (pode
ser o código completo de 8 dígitos, ou só o capítulo/posição, valendo pra
todo NCM que começa daquele jeito). Achado real ao processar a fonte: o
MESMO prefixo de NCM aparece registrado sob CEST diferentes em ~144 casos —
isso não é erro da tabela, é a regra de verdade do ICMS-ST: o CEST de um
produto depende do NCM *e* do segmento de atuação de quem vende (ex.: um
tubo de plástico NCM 3917 pode ser CEST de autopeças OU de material de
construção, dependendo de quem vende). Por isso `get_cest_for_ncm` sempre
devolve uma LISTA de candidatos, nunca um único "CEST certo" — a escolha
final exige saber o segmento, que só um humano (ou uma regra de negócio
externa) decide. Nunca inventa: sem prefixo correspondente, lista vazia.

Fonte: CEST_E_NCM_2026_CONTABILIZEI.xlsx, convertida uma vez pra
data/cest_ncm_tabela_oficial.json (mesmo padrão do ncm_lookup.py).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "cest_ncm_tabela_oficial.json"


def _only_digits(codigo: str) -> str:
    return re.sub(r"\D", "", str(codigo or ""))


@dataclass(frozen=True)
class CESTMatch:
    """Um CEST candidato para um NCM, com o prefixo oficial que bateu."""
    cest: str              # ex: "01.002.00"
    ncm_prefixo: str       # o prefixo registrado que bateu, ex: "3917"
    descricao: str         # descrição oficial da categoria

    @property
    def especifico(self) -> bool:
        """True quando o prefixo é o NCM completo (8 dígitos) — o match
        mais confiável. False quando é um prefixo genérico (ex.: capítulo
        inteiro "38"/"39") — ainda válido, mas abrange muitos produtos
        diferentes (comum nos CEST de venda por catálogo/porta-a-porta,
        segmento "28", que capturam capítulos inteiros de propósito)."""
        return len(self.ncm_prefixo) == 8


@lru_cache(maxsize=1)
def _load_table() -> tuple[dict[str, list[CESTMatch]], int]:
    """Carrega a tabela oficial uma vez por processo. Índice por PREFIXO
    exato (não por NCM completo) — a busca por NCM completo testa todos os
    prefixos possíveis (do mais específico ao mais genérico) contra o
    índice, não o contrário."""
    if not _DATA_PATH.exists():
        return {}, 0
    with open(_DATA_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    indice: dict[str, list[CESTMatch]] = {}
    for item in raw.get("entradas", []):
        prefixo = item["ncm_prefixo"]
        indice.setdefault(prefixo, []).append(
            CESTMatch(cest=item["cest"], ncm_prefixo=prefixo, descricao=item["descricao"])
        )
    return indice, raw.get("total", 0)


def get_cest_for_ncm(ncm: str, *, apenas_especifico: bool = False) -> list[CESTMatch]:
    """Dado um NCM completo (8 dígitos), devolve TODOS os CEST cujo prefixo
    registrado bate com esse NCM — do prefixo mais específico (8 dígitos,
    código exato) ao mais genérico (2 dígitos, capítulo inteiro).

    Pode devolver MAIS DE UM resultado legitimamente (ver módulo) — quando
    isso acontece, o campo `ncm_prefixo` de cada um mostra o nível de
    especificidade, do mais específico (lista) pro mais genérico, pra
    ajudar a escolha humana. Sem nenhum prefixo correspondente, lista
    vazia — nunca inventa um CEST.

    `apenas_especifico=True` descarta os matches por capítulo inteiro (ex.:
    os CEST de venda por catálogo/porta-a-porta, que capturam capítulos "38"/
    "39" completos) — útil quando quem chama já sabe que não opera nesse
    canal e só quer os matches de NCM completo (8 dígitos)."""
    digitos = _only_digits(ncm)
    if not digitos:
        return []
    indice, _ = _load_table()
    encontrados: list[CESTMatch] = []
    vistos: set[tuple[str, str]] = set()
    # do prefixo mais longo (mais específico) pro mais curto (mais genérico)
    for tamanho in range(min(len(digitos), 8), 1, -1):
        prefixo = digitos[:tamanho]
        for match in indice.get(prefixo, []):
            chave = (match.cest, match.ncm_prefixo)
            if chave not in vistos:
                vistos.add(chave)
                if not apenas_especifico or match.especifico:
                    encontrados.append(match)
    return encontrados


def cest_exists(cest: str) -> bool:
    """Verifica se um código CEST realmente existe na tabela oficial."""
    indice, _ = _load_table()
    alvo = str(cest or "").strip()
    return any(m.cest == alvo for lista in indice.values() for m in lista)


def table_size() -> int:
    """Quantos pares (CEST, prefixo NCM) estão carregados."""
    _, total = _load_table()
    return total
