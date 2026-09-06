"""Testes: glm_validators.normalize_ncm/normalize_cest ligados às tabelas
oficiais (ncm_lookup.py / cest_lookup.py) — formato correto não é a mesma
coisa que o código EXISTIR de verdade."""
from phoenix_kernel.documents.confidence import ConfidenceStatus
from phoenix_kernel.documents.glm_validators import normalize_ncm, normalize_cest


def test_ncm_real_is_confirmed():
    r = normalize_ncm("0101.21.00")
    assert r.status == ConfidenceStatus.CONFIRMED


def test_ncm_valid_format_but_nonexistent_is_invalid():
    """Achado que motivou a ligação: 8 dígitos numéricos passa no formato,
    mas pode ser invenção/erro de digitação. Isso tem que ser INVALID, não
    PROBABLE — nunca deixar passar como 'talvez' um código que sabemos que
    não existe."""
    r = normalize_ncm("99999999")
    assert r.status == ConfidenceStatus.INVALID


def test_ncm_wrong_format_returns_none_unchanged():
    assert normalize_ncm("123") is None
    assert normalize_ncm("") is None


def test_cest_real_is_confirmed():
    r = normalize_cest("01.001.00")
    assert r.status == ConfidenceStatus.CONFIRMED


def test_cest_valid_format_but_nonexistent_is_invalid():
    r = normalize_cest("99.999.99")
    assert r.status == ConfidenceStatus.INVALID


def test_cest_wrong_format_returns_none_unchanged():
    assert normalize_cest("123") is None
