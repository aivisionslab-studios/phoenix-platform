"""Testes das regras de sanidade de negócio (defesa contra erro semântico)."""
from phoenix_kernel.documents.business_sanity import (
    check_price_coherence, apply_sanity_checks,
)


def test_cost_higher_than_sale_is_flagged():
    """O erro que aconteceu: custo maior que venda = margem negativa."""
    fields = {"cost_price": 50.0, "retail_price": 30.0}  # custo > venda!
    violations = check_price_coherence(fields)
    assert len(violations) == 1
    assert violations[0].rule == "custo_maior_que_venda"


def test_suspect_prices_not_written():
    """Campos com violação são removidos dos seguros (vão para auditoria)."""
    fields = {"cost_price": 50.0, "retail_price": 30.0, "weight": 0.5}
    safe, violations = apply_sanity_checks(fields)
    assert "cost_price" not in safe      # suspeito, não escrito
    assert "retail_price" not in safe    # suspeito, não escrito
    assert "weight" in safe              # sem problema, passa
    assert len(violations) == 1


def test_coherent_prices_pass():
    """Preços coerentes (custo < venda) passam sem violação."""
    fields = {"cost_price": 10.0, "retail_price": 25.0, "sale_price": 20.0}
    safe, violations = apply_sanity_checks(fields)
    assert violations == []
    assert safe == fields


def test_preco_de_menor_que_por_is_flagged():
    """'Preço De' (riscado) menor que 'Preço Por' = invertido."""
    fields = {"sale_price": 20.0, "compare_at_price": 15.0}  # de < por!
    violations = check_price_coherence(fields)
    assert any(v.rule == "preco_de_menor_que_por" for v in violations)


def test_real_conveniencia_prices_are_coherent():
    """Os preços reais de conveniência (Mín 12,90 < Máx 18,50) são coerentes."""
    # após a correção semântica: Mínimo->sale_price, Máximo->compare_at_price
    fields = {"sale_price": 12.90, "compare_at_price": 18.50}
    safe, violations = apply_sanity_checks(fields)
    assert violations == []  # 12,90 < 18,50, coerente
    assert safe == fields
