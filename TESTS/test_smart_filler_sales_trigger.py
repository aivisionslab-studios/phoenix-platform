"""Testes do Passo 3: gatilho de venda (smart_filler + case-insensitivity)."""
from phoenix_kernel.documents.smart_filler import smart_fill_rows, _ci_find_key, _ci_get


def test_ci_find_key_matches_regardless_of_case():
    row = {"DESCRIÇÃO": "X", "tags": "", "Categoria do Produto": "Y"}
    assert _ci_find_key(row, "Descrição") == "DESCRIÇÃO"
    assert _ci_find_key(row, "Tags") == "tags"
    assert _ci_find_key(row, "categoria do produto") == "Categoria do Produto"
    assert _ci_find_key(row, "Inexistente") is None


def test_all_caps_template_gets_filled():
    """Achado real: template ALL CAPS deixava 226 de 231 produtos sem
    conteúdo gerado, silenciosamente. Agora preenche."""
    row = {"DESCRIÇÃO": "Cerveja Heineken 330ml", "TAGS": "", "MARCA": "Heineken",
           "CATEGORIA DO PRODUTO": "Bebidas", "ESPECIFICAÇÕES": "",
           "ITENS INCLUSOS": "", "MODELO": "", "DESCRIÇÃO DO PRODUTO": ""}
    rows, rep = smart_fill_rows([row])
    assert row["TAGS"]
    assert row["ESPECIFICAÇÕES"]
    assert row["ITENS INCLUSOS"]
    assert row["MODELO"]
    assert row["DESCRIÇÃO DO PRODUTO"]


def test_sales_trigger_generated_for_descricao_do_produto():
    row = {"Descrição": "Cerveja Heineken 330ml", "Descrição do Produto": ""}
    smart_fill_rows([row])
    assert row["Descrição do Produto"]
    assert "Heineken" in row["Descrição do Produto"]


def test_sales_trigger_tone_differs_for_anchor_vs_complementary():
    """Contexto de quadrante (Passos 1/2) muda o tom do gatilho gerado."""
    row_ancora = {
        "Descrição": "Cerveja Heineken 330ml", "Descrição do Produto": "",
        "_quadrant_context": {"role_hint": "ancora", "margin_label": "Margem Mínima", "quadrant_name": "O BOI"},
    }
    row_comp = {
        "Descrição": "Vinho Casillero 750ml", "Descrição do Produto": "",
        "_quadrant_context": {"role_hint": "complementar", "margin_label": "Margem Alta", "quadrant_name": "A ESTRELA"},
    }
    smart_fill_rows([row_ancora])
    smart_fill_rows([row_comp])
    assert "oferta de entrada" in row_ancora["Descrição do Produto"].lower()
    assert "experiência" in row_comp["Descrição do Produto"].lower()


def test_never_overwrites_existing_sales_trigger():
    row = {"Descrição": "Produto X", "Descrição do Produto": "Texto já existente"}
    smart_fill_rows([row])
    assert row["Descrição do Produto"] == "Texto já existente"


def test_llm_rewrite_hook_still_works_for_new_field():
    """O callback llm_rewrite (já existente) também é chamado para o campo novo."""
    captured = []
    def fake_llm(field_type, row):
        captured.append(field_type)
        return "Texto do LLM"
    row = {"Descrição": "Produto Y", "Descrição do Produto": ""}
    smart_fill_rows([row], llm_rewrite=fake_llm)
    assert "Descrição do Produto" in captured
    assert row["Descrição do Produto"] == "Texto do LLM"
