"""Testes da Fase 3 do "Document Pipeline V2" (phoenix_kernel/documents/
normalizer.py) - conversão de texto cru pra valor normalizado, Python
puro, sem LLM/OCR/rede. Ver PHX-NEW no topo daquele arquivo pro contexto
completo."""
from __future__ import annotations

from phoenix_kernel.documents.normalizer import (
    normalize_cest,
    normalize_currency_brl,
    normalize_date,
    normalize_ean,
    normalize_email,
    normalize_ncm,
    normalize_number_with_unit,
    normalize_phone_br,
)


# ---------------------------------------------------------------------------
# moeda
# ---------------------------------------------------------------------------

def test_currency_with_symbol_and_thousands_separator():
    result = normalize_currency_brl("R$ 1.234,56")
    assert result.valid
    assert result.normalized == 1234.56
    assert result.raw == "R$ 1.234,56"  # valor bruto nunca é descartado


def test_currency_without_symbol():
    result = normalize_currency_brl("589,00")
    assert result.valid
    assert result.normalized == 589.00


def test_currency_invalid_text_stays_invalid_and_keeps_raw():
    result = normalize_currency_brl("preço sob consulta")
    assert result.valid is False
    assert result.normalized is None
    assert result.raw == "preço sob consulta"


# ---------------------------------------------------------------------------
# número com unidade
# ---------------------------------------------------------------------------

def test_number_with_unit_weight_kg():
    result = normalize_number_with_unit("25,500 Kg")
    assert result.valid
    assert result.normalized == 25.5
    assert result.unit == "kg"
    assert result.parsed_value == 25.5
    assert result.original_unit == "kg"


def test_number_with_unit_no_space():
    result = normalize_number_with_unit("18L")
    assert result.valid
    assert result.normalized == 18.0
    assert result.unit == "l"
    assert result.parsed_value == 18.0
    assert result.original_unit == "l"


def test_number_without_unit():
    result = normalize_number_with_unit("42")
    assert result.valid
    assert result.normalized == 42.0
    assert result.unit is None
    assert result.parsed_value == 42.0
    assert result.original_unit is None


def test_number_negative_value():
    """PHX-FIX: "mm" NÃO é a unidade canônica de comprimento (é "m") -
    o valor negativo também passa pela conversão dimensional."""
    result = normalize_number_with_unit("-12,5 mm")
    assert result.valid
    assert result.normalized == -0.0125
    assert result.unit == "m"
    assert result.parsed_value == -12.5
    assert result.original_unit == "mm"


# ---------------------------------------------------------------------------
# unidades canônicas (massa/comprimento/volume) - PHX-FIX 2026-08-29,
# achado real testando a Fase 6/Evidence Engine: "Peso: 0,600 kg" e
# "Peso: 600g" no mesmo produto viravam um "conflict" falso porque a
# comparação de valor era ingênua sobre unidade. Corrigido convertendo
# toda quantidade dimensional pra uma unidade canônica ANTES de virar
# `normalized` - ver PHX-FIX no docstring de `NormalizationResult`.
# ---------------------------------------------------------------------------

def test_weight_grams_converts_to_canonical_kg():
    result = normalize_number_with_unit("600g")
    assert result.valid
    assert result.normalized == 0.6
    assert result.unit == "kg"
    assert result.parsed_value == 600.0
    assert result.original_unit == "g"
    assert result.raw == "600g"  # raw nunca é descartado


def test_weight_kg_and_grams_normalize_to_the_same_canonical_value():
    """0,600 kg == 600 g - o pedido central deste fix."""
    kg_result = normalize_number_with_unit("0,600 kg")
    g_result = normalize_number_with_unit("600g")
    assert kg_result.normalized == g_result.normalized == 0.6
    assert kg_result.unit == g_result.unit == "kg"
    # mas o valor ORIGINAL de cada um continua intacto e diferente
    assert kg_result.original_unit == "kg"
    assert g_result.original_unit == "g"
    assert kg_result.parsed_value == 0.6
    assert g_result.parsed_value == 600.0


def test_one_kg_equals_a_thousand_grams():
    assert (
        normalize_number_with_unit("1 kg").normalized
        == normalize_number_with_unit("1000 g").normalized
        == 1.0
    )


def test_volume_ml_and_liters_normalize_to_the_same_canonical_value():
    assert normalize_number_with_unit("500 ml").normalized == 0.5
    assert normalize_number_with_unit("0,5 L").normalized == 0.5
    assert normalize_number_with_unit("500ml").unit == "l"


def test_length_cm_converts_to_canonical_meters():
    assert normalize_number_with_unit("100cm").normalized == 1.0
    assert normalize_number_with_unit("100cm").unit == "m"
    assert normalize_number_with_unit("1,5 m").normalized == 1.5


def test_same_number_different_unit_is_not_silently_equal():
    """0,600 kg (=600g) é bem diferente de 600 kg - a conversão nunca
    "aproxima" nada, cada unidade converte pelo seu próprio fator."""
    assert (
        normalize_number_with_unit("0,600 kg").normalized
        != normalize_number_with_unit("600 kg").normalized
    )


def test_ml_and_liters_with_same_number_are_not_equal():
    """500 ml != 500 L - mesma grandeza numérica no texto, valores
    fisicamente bem diferentes depois de canonizar."""
    assert (
        normalize_number_with_unit("500 ml").normalized
        != normalize_number_with_unit("500 L").normalized
    )


def test_unrecognized_unit_passes_through_without_conversion():
    result = normalize_number_with_unit("25,5 %")
    assert result.valid
    assert result.normalized == 25.5
    assert result.unit == "%"
    assert result.original_unit == "%"
    assert result.parsed_value == 25.5


# ---------------------------------------------------------------------------
# datas
# ---------------------------------------------------------------------------

def test_date_br_format_four_digit_year():
    result = normalize_date("15/09/2026")
    assert result.valid
    assert result.normalized == "2026-09-15"


def test_date_iso_format_passthrough():
    result = normalize_date("2026-09-15")
    assert result.valid
    assert result.normalized == "2026-09-15"


def test_date_br_format_two_digit_year_expands_to_2000s():
    result = normalize_date("15/09/26")
    assert result.valid
    assert result.normalized == "2026-09-15"


def test_date_with_portuguese_month_name():
    result = normalize_date("15 de setembro de 2026")
    assert result.valid
    assert result.normalized == "2026-09-15"


def test_date_impossible_calendar_date_is_invalid():
    result = normalize_date("32/13/2026")
    assert result.valid is False
    assert result.normalized is None


def test_date_garbage_text_is_invalid():
    result = normalize_date("data a combinar")
    assert result.valid is False


# ---------------------------------------------------------------------------
# EAN (com dígito verificador de verdade)
# ---------------------------------------------------------------------------

def test_ean13_valid_checksum_accepted():
    # 4006381333931 é um EAN-13 real (Nivea) - validação externa, não
    # inventada pra este teste.
    result = normalize_ean("4006381333931")
    assert result.valid
    assert result.normalized == "4006381333931"


def test_ean13_wrong_checksum_rejected():
    # mesmo prefixo do teste acima, dígito verificador errado de propósito.
    result = normalize_ean("7891019125301")
    assert result.valid is False
    assert result.normalized is None


def test_ean_formatted_with_spaces_still_validates():
    result = normalize_ean("4006 3813 3393 1")
    assert result.valid
    assert result.normalized == "4006381333931"


def test_ean_wrong_length_rejected():
    result = normalize_ean("12345")
    assert result.valid is False


# ---------------------------------------------------------------------------
# NCM / CEST
# ---------------------------------------------------------------------------

def test_ncm_with_dots_normalizes_to_plain_digits():
    result = normalize_ncm("3209.10.10")
    assert result.valid
    assert result.normalized == "32091010"


def test_ncm_wrong_digit_count_rejected():
    result = normalize_ncm("3209101")
    assert result.valid is False


def test_cest_with_dots_normalizes_to_plain_digits():
    result = normalize_cest("24.001.00")
    assert result.valid
    assert result.normalized == "2400100"


def test_cest_wrong_digit_count_rejected():
    result = normalize_cest("240010")
    assert result.valid is False


# ---------------------------------------------------------------------------
# telefone / e-mail
# ---------------------------------------------------------------------------

def test_phone_mobile_with_country_code_and_formatting():
    result = normalize_phone_br("+55 (11) 98765-4321")
    assert result.valid
    assert result.normalized == "+5511987654321"


def test_phone_mobile_without_country_code():
    result = normalize_phone_br("(11) 98765-4321")
    assert result.valid
    assert result.normalized == "+5511987654321"


def test_phone_landline_ten_digits():
    result = normalize_phone_br("11 3456-7890")
    assert result.valid
    assert result.normalized == "+551134567890"


def test_phone_wrong_digit_count_rejected():
    result = normalize_phone_br("123456")
    assert result.valid is False


def test_email_normalizes_to_lowercase():
    result = normalize_email("  Carlos@Example.COM  ")
    assert result.valid
    assert result.normalized == "carlos@example.com"


def test_email_missing_at_sign_is_invalid():
    result = normalize_email("carlos.example.com")
    assert result.valid is False
    assert result.normalized is None
