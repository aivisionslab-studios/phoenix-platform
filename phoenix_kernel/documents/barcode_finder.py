"""Barcode Finder — pesquisa o código de barras (EAN) e enfileira para AUDITORIA.

O problema: código de barras (EAN-13) errado quebra o PDV — o produto não passa
no caixa, ou passa como outro. Então, diferente de NCM (que pode ser sugerido
de uma base auditada), o EAN de cada produto precisa ser PESQUISADO e depois
CONFERIDO POR UM HUMANO antes de valer. Este módulo faz a pesquisa e monta a
fila de conferência — nunca escreve o EAN direto no catálogo.

Fluxo por produto:
  1. pesquisa na web pelo nome + "código de barras"/"EAN";
  2. extrai candidatos a EAN-13 dos resultados (13 dígitos);
  3. VALIDA o dígito verificador (um EAN-13 tem checksum — números aleatórios
     de 13 dígitos quase sempre falham, então isso filtra lixo);
  4. monta um AuditItem com o nome, o tipo do produto, os candidatos
     encontrados, e as fontes (URLs) de cada um — para o humano decidir.

Nada é "confirmado" automaticamente. Mesmo um único candidato válido entra como
`pending_review`. A confirmação é uma ação humana explícita (approve_ean), que
só então marca o EAN como bom para o catálogo. É o "humano audita" que você
pediu, embutido no fluxo — não um passo opcional.

A busca web é injetada como callback async, para o módulo ser testável sem rede
e para o resident manter a política de rede/timeout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

# callback: (query) -> lista de {title, url, snippet}
WebSearchFn = Callable[[str], Awaitable[list[dict]]]

_EAN13_RE = re.compile(r"\b(\d{13})\b")
_EAN8_RE = re.compile(r"\b(\d{8})\b")


def validate_ean13(code: str) -> bool:
    """Valida o dígito verificador de um EAN-13. O 13º dígito é calculado dos
    12 primeiros (pesos alternados 1 e 3); um número de 13 dígitos aleatório
    passa nisso com prob. ~1/10, então é um bom filtro contra lixo."""
    digits = re.sub(r"\D", "", code or "")
    if len(digits) != 13:
        return False
    nums = [int(d) for d in digits]
    check = nums[-1]
    total = sum(n * (1 if i % 2 == 0 else 3) for i, n in enumerate(nums[:12]))
    expected = (10 - (total % 10)) % 10
    return expected == check


def validate_ean8(code: str) -> bool:
    digits = re.sub(r"\D", "", code or "")
    if len(digits) != 8:
        return False
    nums = [int(d) for d in digits]
    total = sum(n * (3 if i % 2 == 0 else 1) for i, n in enumerate(nums[:7]))
    expected = (10 - (total % 10)) % 10
    return expected == nums[-1]


@dataclass
class EanCandidate:
    code: str
    valid_checksum: bool
    source_url: str = ""
    source_title: str = ""


@dataclass
class AuditItem:
    """Uma linha da fila de conferência humana."""
    product_name: str
    product_type: str = ""
    candidates: list[EanCandidate] = field(default_factory=list)
    status: str = "pending_review"   # pending_review | approved | rejected | not_found
    approved_ean: str = ""           # preenchido só quando um humano aprova

    @property
    def best_candidate(self) -> Optional[EanCandidate]:
        """O melhor palpite (checksum válido primeiro), só para exibir ao
        auditor — NUNCA é aplicado sem aprovação."""
        valids = [c for c in self.candidates if c.valid_checksum]
        if valids:
            return valids[0]
        return self.candidates[0] if self.candidates else None


def _extract_eans(results: list[dict]) -> list[EanCandidate]:
    """Puxa candidatos a EAN-13/8 dos resultados de busca, deduplicando e
    marcando quais passam no checksum. Preserva a fonte de cada um."""
    seen: dict[str, EanCandidate] = {}
    for res in results:
        blob = f"{res.get('title','')} {res.get('snippet','')}"
        url = res.get("url", "")
        title = res.get("title", "")
        for m in _EAN13_RE.finditer(blob):
            code = m.group(1)
            if code not in seen:
                seen[code] = EanCandidate(code, validate_ean13(code), url, title)
        for m in _EAN8_RE.finditer(blob):
            code = m.group(1)
            # evita capturar os 8 primeiros de um 13; só aceita se validar como EAN-8
            if code not in seen and validate_ean8(code):
                seen[code] = EanCandidate(code, True, url, title)
    # ordena: checksum válido primeiro
    return sorted(seen.values(), key=lambda c: (not c.valid_checksum, c.code))


async def find_ean_for_product(
    product_name: str,
    product_type: str = "",
    *,
    web_search: WebSearchFn,
    max_results: int = 5,
) -> AuditItem:
    """Pesquisa o EAN de UM produto e devolve um item de auditoria (nunca um
    valor aplicado). Sempre inclui o tipo do produto na fila, como você pediu
    ('colocar com o nome e tipo do produto')."""
    item = AuditItem(product_name=product_name, product_type=product_type)
    query = f'"{product_name}" código de barras EAN'
    try:
        results = await web_search(query)
    except Exception:
        results = []
    if not results:
        item.status = "not_found"
        return item
    item.candidates = _extract_eans(results)
    if not item.candidates:
        item.status = "not_found"
    return item


async def build_audit_queue(
    products: list[dict],
    *,
    web_search: WebSearchFn,
    name_col: str = "Descrição",
    type_col: str = "Tipo de Produto",
    only_missing_ean: bool = True,
    ean_col: str = "Código de Barras",
    max_products: Optional[int] = None,
) -> list[AuditItem]:
    """Monta a fila de auditoria de EAN para uma lista de produtos. Por padrão,
    só pesquisa os que ainda NÃO têm código de barras (`only_missing_ean`).
    `max_products` limita quantas buscas fazer (controle de tempo/rede)."""
    queue: list[AuditItem] = []
    n = 0
    for row in products:
        if only_missing_ean:
            cur = row.get(ean_col)
            if cur is not None and not (isinstance(cur, str) and not cur.strip()):
                continue  # já tem EAN, não pesquisa
        name = str(row.get(name_col, "") or "").strip()
        if not name:
            continue
        item = await find_ean_for_product(
            name, str(row.get(type_col, "") or ""), web_search=web_search,
        )
        queue.append(item)
        n += 1
        if max_products is not None and n >= max_products:
            break
    return queue


def approve_ean(item: AuditItem, ean: str) -> bool:
    """Ação HUMANA: aprova um EAN para o produto. Só aceita um código que
    valide o checksum (o auditor pode digitar um da embalagem física, não só
    escolher da lista). Marca o item como aprovado. Devolve True se aceito."""
    if validate_ean13(ean) or validate_ean8(ean):
        item.approved_ean = re.sub(r"\D", "", ean)
        item.status = "approved"
        return True
    return False


def apply_approved_eans(products: list[dict], queue: list[AuditItem],
                        *, name_col: str = "Descrição",
                        ean_col: str = "Código de Barras") -> int:
    """Escreve no catálogo APENAS os EANs que um humano aprovou. Itens ainda
    em `pending_review`/`rejected`/`not_found` não tocam o catálogo. Devolve
    quantos foram aplicados."""
    approved = {item.product_name: item.approved_ean
                for item in queue if item.status == "approved" and item.approved_ean}
    n = 0
    for row in products:
        name = str(row.get(name_col, "") or "").strip()
        if name in approved:
            cur = row.get(ean_col)
            if cur is None or (isinstance(cur, str) and not cur.strip()):
                row[ean_col] = approved[name]
                n += 1
    return n
