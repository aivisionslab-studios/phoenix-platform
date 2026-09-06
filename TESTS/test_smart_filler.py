"""Testes do Smart Filler — a Phoenix raciocinando e preenchendo."""

from phoenix_kernel.documents.smart_filler import (
    DerivationRule, smart_fill_rows,
)


def test_derives_by_rule_copy_default_and_sequential():
    rows = [
        {"Descrição": "Tinta Coral 18L", "Origem": "", "Tipo": "",
         "Categoria na Loja Virtual": "Tintas", "Categoria PDV": "",
         "Código Interno": ""},
        {"Descrição": "Argamassa 20kg", "Origem": "", "Tipo": "",
         "Categoria na Loja Virtual": "Argamassas", "Categoria PDV": "",
         "Código Interno": "PROD005"},  # série existente -> próximo é 006
    ]
    rows, rep = smart_fill_rows(rows, generate_content=False)
    assert rows[0]["Origem"] == "NACIONAL"            # default
    assert rows[0]["Tipo"] == "Mercadoria para Revenda"
    assert rows[0]["Categoria PDV"] == "Tintas"       # copiado
    assert rows[0]["Código Interno"] == "PROD006"     # continua a série do 005
    assert rep.filled_by_rule["Origem"] == 2


def test_never_overwrites_existing_values():
    rows = [{"Descrição": "X", "Origem": "IMPORTADO", "Tipo": "Serviço"}]
    rows, _ = smart_fill_rows(rows, generate_content=False)
    assert rows[0]["Origem"] == "IMPORTADO"   # respeitado, não vira NACIONAL
    assert rows[0]["Tipo"] == "Serviço"


def test_fiscal_fields_are_never_guessed():
    rows = [{"Descrição": "Broxa Tigre 3\"", "NCM": "", "CFOP": "", "CEST": "",
             "Categoria do Produto": "Pincéis / Trinchas"}]
    rows, rep = smart_fill_rows(rows)
    # guarda-fiscal: continuam vazios
    assert rows[0]["NCM"] == ""
    assert rows[0]["CFOP"] == ""
    assert rows[0]["CEST"] == ""
    assert rep.left_blank_fiscal["NCM"] == 1
    assert rep.left_blank_fiscal["CEST"] == 1
    # e viraram pendência para decisão humana
    assert any(col in ("NCM", "CFOP", "CEST") for _, col, _, _ in rep.pending)


def test_placeholder_products_are_not_invented():
    rows = [{"Descrição": "Produto 61", "Tags": "", "Especificações": "",
             "Categoria do Produto": ""}]
    rows, rep = smart_fill_rows(rows)
    assert rows[0]["Tags"] == ""            # não gera tag pra nome-fantasma
    assert rows[0]["Especificações"] == ""
    assert rep.left_blank_placeholder == 1
    assert any("genérico" in motivo for _, _, motivo, _ in rep.pending)


def test_generates_content_from_category_and_name():
    rows = [{"Descrição": "Argamassa ACI Quartzolit 20kg", "Marca": "Quartzolit",
             "Categoria do Produto": "Argamassas", "Tags": "",
             "Especificações": "", "Itens Inclusos": "", "Modelo": "",
             "Peso (Kg)": "20"}]
    rows, rep = smart_fill_rows(rows)
    assert "argamassa" in rows[0]["Tags"].lower()
    assert "quartzolit" in rows[0]["Tags"].lower()      # marca entra na tag
    assert "20kg" in rows[0]["Tags"].lower()            # tamanho entra na tag
    assert "Marca: Quartzolit" in rows[0]["Especificações"]
    assert "20kg" in rows[0]["Itens Inclusos"]
    assert rows[0]["Modelo"]                            # nome-core preenchido


def test_llm_rewrite_is_optional_fallback():
    calls = []

    def rewrite(field_type, row):
        calls.append(field_type)
        return f"REESCRITO:{field_type}"

    rows = [{"Descrição": "Gin Hendrick's 750ml", "Marca": "Hendrick's",
             "Categoria do Produto": "Destilados", "Tags": "",
             "Especificações": "", "Itens Inclusos": "", "Modelo": ""}]
    rows, _ = smart_fill_rows(rows, llm_rewrite=rewrite)
    # o llm foi chamado e sua saída prevaleceu sobre o determinístico
    assert rows[0]["Tags"] == "REESCRITO:Tags"
    assert "Tags" in calls


def test_llm_failure_falls_back_to_deterministic():
    def rewrite(field_type, row):
        raise RuntimeError("modelo offline")

    rows = [{"Descrição": "Cerveja Pilsen 350ml", "Categoria do Produto": "Bebidas",
             "Tags": ""}]
    rows, _ = smart_fill_rows(rows, llm_rewrite=rewrite)
    assert rows[0]["Tags"]  # não vazio — caiu no determinístico
    assert "REESCRITO" not in rows[0]["Tags"]
