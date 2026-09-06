"""Regras de sanidade de NEGÓCIO — a defesa contra erro semântico.

Nasceu de um erro real: "Preço Mínimo" foi mapeado para "Preço de Custo",
o que poria o menor preço de VENDA na coluna de CUSTO e destruiria a margem
do lojista. O pipeline validava o FORMATO do dado (é um número? tem 8 dígitos?)
mas não a LÓGICA de negócio (faz sentido que o custo seja maior que a venda?).

Este módulo aplica regras de sanidade sobre os campos JÁ extraídos, ANTES de
escrever na planilha. Quando uma regra é violada, os campos envolvidos NÃO são
escritos com o valor suspeito — vão para auditoria com o motivo. É a regra de
ouro aplicada à semântica: melhor um campo em branco (auditado) que um valor
que quebra a contabilidade.

Proposta original do GLM (colaboração), avaliada e implementada aqui com a
ressalva de que a violação REBAIXA para auditoria, nunca "conserta" sozinha
(consertar exigiria adivinhar qual dos dois valores está certo — e adivinhar
dado financeiro é o que estamos evitando).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SanityViolation:
    """Uma regra de negócio violada, para a aba de auditoria."""
    field_types: list[str]        # campos envolvidos
    rule: str                     # qual regra ("custo_maior_que_venda")
    detail: str                   # explicação humana
    values: dict                  # os valores que dispararam a violação


def _to_number(v) -> Optional[float]:
    """Converte um valor de campo para número, se possível."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        s = str(v).replace("R$", "").replace(" ", "").replace(".", "").replace(",", ".")
        return float(s)
    except (ValueError, AttributeError):
        return None


def check_price_coherence(fields: dict) -> list[SanityViolation]:
    """Verifica coerência entre os preços de um produto. `fields` é um dict
    {field_type: valor} (já os valores, não os FieldEvidence).

    Regras (todas conservadoras — só disparam com certeza):
    - custo NÃO pode ser maior que qualquer preço de venda (margem negativa);
    - o "preço de" (compare_at) NÃO pode ser menor que o "preço por" (sale)
      — o "de" riscado é sempre o maior.
    """
    violations: list[SanityViolation] = []

    cost = _to_number(fields.get("cost_price"))
    retail = _to_number(fields.get("retail_price"))
    wholesale = _to_number(fields.get("wholesale_price"))
    sale = _to_number(fields.get("sale_price"))          # "Preço Por"
    compare = _to_number(fields.get("compare_at_price"))  # "Preço De"

    # regra 1: custo > venda = margem negativa (quase sempre erro de mapeamento)
    vendas = {"retail_price": retail, "wholesale_price": wholesale,
              "sale_price": sale, "compare_at_price": compare}
    if cost is not None:
        for venda_field, venda_val in vendas.items():
            if venda_val is not None and cost > venda_val:
                violations.append(SanityViolation(
                    field_types=["cost_price", venda_field],
                    rule="custo_maior_que_venda",
                    detail=(f"Custo (R$ {cost:.2f}) maior que {venda_field} "
                            f"(R$ {venda_val:.2f}) — margem negativa, provável erro "
                            f"de mapeamento de coluna."),
                    values={"cost_price": cost, venda_field: venda_val},
                ))

    # regra 2: "preço de" (riscado) menor que "preço por" (atual) = invertido
    if sale is not None and compare is not None and compare < sale:
        violations.append(SanityViolation(
            field_types=["sale_price", "compare_at_price"],
            rule="preco_de_menor_que_por",
            detail=(f"'Preço De' (R$ {compare:.2f}) menor que 'Preço Por' "
                    f"(R$ {sale:.2f}) — o 'de' riscado deveria ser o maior; "
                    f"valores provavelmente invertidos."),
            values={"sale_price": sale, "compare_at_price": compare},
        ))

    return violations


def apply_sanity_checks(fields: dict) -> tuple[dict, list[SanityViolation]]:
    """Roda as regras de sanidade e devolve (campos_seguros, violações).

    Campos envolvidos numa violação são REMOVIDOS de campos_seguros (não serão
    escritos) e listados nas violações (vão para auditoria). Campos sem
    problema passam intactos. Nunca "conserta" um valor — só protege contra
    escrever o suspeito.
    """
    violations = check_price_coherence(fields)
    if not violations:
        return dict(fields), []

    suspect_fields = set()
    for v in violations:
        suspect_fields.update(v.field_types)

    safe = {ft: val for ft, val in fields.items() if ft not in suspect_fields}
    return safe, violations
