"""Testes: normalizer.normalize_ncm/normalize_cest — o módulo REALMENTE
usado em produção (identity_engine.py, candidate_engine.py, fiscal_rag.py)
— ligado às tabelas oficiais (ncm_lookup.py/cest_lookup.py).

PHX-FIX (2026-09-06): o comentário original deste módulo dizia que validar
existência real "é responsabilidade de uma fase de validação/regra de
negócio, não do Normalizer" — essa fase agora existe. `valid` volta a
significar "é um NCM/CEST real", não só "tem o número certo de dígitos".
"""
from phoenix_kernel.documents.normalizer import normalize_ncm, normalize_cest


def test_real_ncm_from_official_table_is_valid():
    r = normalize_ncm("3209.10.10")
    assert r.valid is True
    assert r.normalized == "32091010"


def test_ncm_valid_format_but_nonexistent_is_invalid():
    """A mudança central: 8 dígitos numéricos não bastam mais — o código
    precisa existir de verdade na tabela oficial."""
    r = normalize_ncm("9999.99.99")
    assert r.valid is False


def test_ncm_wrong_digit_count_is_invalid():
    r = normalize_ncm("3209101")  # 7 dígitos, não 8
    assert r.valid is False


def test_real_cest_from_official_table_is_valid():
    r = normalize_cest("24.001.00")
    assert r.valid is True
    assert r.normalized == "2400100"


def test_cest_valid_format_but_nonexistent_is_invalid():
    r = normalize_cest("99.999.99")
    assert r.valid is False


def test_cest_wrong_digit_count_is_invalid():
    r = normalize_cest("240010")  # 6 dígitos, não 7
    assert r.valid is False


def test_all_ncm_used_across_existing_test_suite_still_valid():
    """Rede de segurança: todo NCM já usado em outros testes do projeto
    (paint, cerveja, argamassa, ferramenta, vodca) continua válido depois
    da ligação — nenhum teste antigo pode ficar órfão silenciosamente."""
    codigos_reais_em_uso = ["32091010", "84672100", "22030000", "38245000", "22086000"]
    for codigo in codigos_reais_em_uso:
        assert normalize_ncm(codigo).valid is True, f"{codigo} deveria continuar válido"
