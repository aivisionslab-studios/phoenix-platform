"""Testes da Fase 4 do "Document Pipeline V2" (phoenix_kernel/documents/
candidate_engine.py) - encontra candidatos de campo dentro do texto de um
Block, usando o Normalizer (Fase 3) pra validar. Ver PHX-NEW no topo
daquele arquivo pro contexto e princípios completos (achar padrão !=
aceitar como verdade; rótulo forte quando presente, formato
autoidentificável quando não; zero LLM/OCR)."""
from __future__ import annotations

from phoenix_kernel.documents.candidate_engine import find_candidates_in_block, find_candidates_in_text
from phoenix_kernel.documents.normalized import Block, BlockType


def _paragraph(text: str, block_id: str = "b0001") -> Block:
    return Block(id=block_id, type=BlockType.PARAGRAPH, order=0, text_raw=text)


# ---------------------------------------------------------------------------
# rotulado
# ---------------------------------------------------------------------------

def test_labeled_ean_with_valid_checksum():
    candidates = find_candidates_in_text("EAN: 4006381333931", "b1")
    ean_candidates = [c for c in candidates if c.field_type == "ean"]
    assert len(ean_candidates) == 1
    c = ean_candidates[0]
    assert c.valid is True
    assert c.normalized_value == "4006381333931"
    assert c.block_id == "b1"
    assert c.method == "label+checksum"


def test_labeled_ean_with_invalid_checksum_is_preserved_not_discarded():
    """Achado real do usuário: "achar um padrão != aceitar como verdade" -
    um EAN rotulado com dígito verificador ERRADO ainda vira Candidate,
    só com valid=False."""
    candidates = find_candidates_in_text("EAN: 7891019125301", "b1")
    ean_candidates = [c for c in candidates if c.field_type == "ean"]
    assert len(ean_candidates) == 1
    c = ean_candidates[0]
    assert c.valid is False
    assert c.normalized_value is None
    assert c.raw_value == "7891019125301"  # valor bruto nunca é descartado


def test_labeled_ncm():
    candidates = find_candidates_in_text("NCM: 32091010", "b1")
    ncm = [c for c in candidates if c.field_type == "ncm"]
    assert len(ncm) == 1
    assert ncm[0].valid
    assert ncm[0].normalized_value == "32091010"


def test_labeled_cest():
    candidates = find_candidates_in_text("CEST: 24.001.00", "b1")
    cest = [c for c in candidates if c.field_type == "cest"]
    assert len(cest) == 1
    assert cest[0].normalized_value == "2400100"


def test_labeled_price_with_currency():
    candidates = find_candidates_in_text("Preço: R$ 589,00", "b1")
    price = [c for c in candidates if c.field_type == "price"]
    assert len(price) == 1
    assert price[0].normalized_value == 589.00


def test_labeled_price_min_and_max_get_distinct_field_types():
    """PHX-FIX (achado real testando a Fase 6/Evidence contra documentos
    reais): "Preço Mínimo"/"Preço Máximo" precisam virar field_types
    DIFERENTES (price_min/price_max) - não dois candidatos genéricos
    "price" com valores diferentes, senão uma fase de agregação por campo
    (Evidence, Fase 6) enxerga isso como "conflito" quando não é."""
    text = "Preço Mínimo: R$ 589,00 | Preço Máximo: R$ 749,00"
    candidates = find_candidates_in_text(text, "b1")
    price_min = [c for c in candidates if c.field_type == "price_min"]
    price_max = [c for c in candidates if c.field_type == "price_max"]
    assert len(price_min) == 1
    assert price_min[0].normalized_value == 589.00
    assert len(price_max) == 1
    assert price_max[0].normalized_value == 749.00
    # e nenhum candidato "price" genérico sobra pra essas duas ocorrências
    # (o detector solto de "R$" não pode duplicar o mesmo span)
    assert [c for c in candidates if c.field_type == "price"] == []


def test_labeled_price_without_qualifier_stays_generic():
    candidates = find_candidates_in_text("Preço: R$ 99,90", "b1")
    prices = [c for c in candidates if c.field_type == "price"]
    assert len(prices) == 1
    assert prices[0].normalized_value == 99.90


def test_labeled_weight_with_unit():
    candidates = find_candidates_in_text("Peso: 25,500 Kg", "b1")
    weight = [c for c in candidates if c.field_type == "weight"]
    assert len(weight) == 1
    assert weight[0].normalized_value == 25.5
    assert weight[0].unit == "kg"
    assert weight[0].original_unit == "kg"
    assert weight[0].parsed_value == 25.5


def test_labeled_weight_in_grams_converts_to_canonical_kg_and_keeps_original():
    """PHX-FIX: achado real testando a Fase 6 - "Peso: 600g" precisa
    chegar ao Candidate já convertido pra kg (0.6), preservando g/600
    como original_unit/parsed_value pra auditoria. Achado adicional
    (bug de regressão do próprio fix, não de documento real): o rebuild
    final de `find_candidates_in_text` (depois do dedup por span) tinha
    esquecido de propagar unit/original_unit/parsed_value pro Candidate
    final - só apareceu rodando este teste ponta a ponta."""
    candidates = find_candidates_in_text("Peso: 600g", "b1")
    weight = [c for c in candidates if c.field_type == "weight"]
    assert len(weight) == 1
    assert weight[0].normalized_value == 0.6
    assert weight[0].unit == "kg"
    assert weight[0].original_unit == "g"
    assert weight[0].parsed_value == 600.0


# ---------------------------------------------------------------------------
# NCM/CEST/peso sem rótulo não são reconhecidos (limitação documentada)
# ---------------------------------------------------------------------------

def test_ncm_without_label_is_not_detected_as_ncm():
    candidates = find_candidates_in_text("32091010", "b1")
    ncm = [c for c in candidates if c.field_type == "ncm"]
    assert ncm == []


# ---------------------------------------------------------------------------
# sem rótulo, formato autoidentificável
# ---------------------------------------------------------------------------

def test_unlabeled_email_is_found():
    candidates = find_candidates_in_text("fale com carlos@example.com pra mais detalhes", "b1")
    emails = [c for c in candidates if c.field_type == "email"]
    assert len(emails) == 1
    assert emails[0].normalized_value == "carlos@example.com"


def test_unlabeled_price_with_currency_symbol_is_found():
    candidates = find_candidates_in_text("sai por R$ 99,90 na promoção", "b1")
    prices = [c for c in candidates if c.field_type == "price"]
    assert len(prices) == 1
    assert prices[0].normalized_value == 99.90


def test_unlabeled_valid_ean_is_found_by_checksum_alone():
    candidates = find_candidates_in_text("código impresso na embalagem: 4006381333931", "b1")
    ean = [c for c in candidates if c.field_type == "ean" and c.method == "checksum"]
    assert len(ean) == 1
    assert ean[0].valid
    assert ean[0].normalized_value == "4006381333931"


def test_unlabeled_invalid_length_number_is_not_treated_as_ean():
    """Um número de 13 dígitos com checksum ERRADO e SEM rótulo não deve
    virar Candidate de EAN - ruído demais sem nenhum sinal (nem rótulo,
    nem checksum válido)."""
    candidates = find_candidates_in_text("código interno 1234567890123 do sistema", "b1")
    ean = [c for c in candidates if c.field_type == "ean"]
    assert ean == []


def test_unlabeled_formatted_phone_is_found():
    candidates = find_candidates_in_text("contato: (11) 98765-4321", "b1")
    phones = [c for c in candidates if c.field_type == "phone"]
    assert len(phones) == 1
    assert phones[0].normalized_value == "+5511987654321"


def test_unlabeled_date_numeric_format_is_found():
    candidates = find_candidates_in_text("validade até 15/09/2026", "b1")
    dates = [c for c in candidates if c.field_type == "date"]
    assert len(dates) == 1
    assert dates[0].normalized_value == "2026-09-15"


# ---------------------------------------------------------------------------
# offsets / contexto
# ---------------------------------------------------------------------------

def test_offsets_point_at_the_raw_value_inside_the_text():
    text = "Peso 25kg | EAN: 4006381333931 | Tags: tinta"
    candidates = find_candidates_in_text(text, "b1")
    ean = [c for c in candidates if c.field_type == "ean"][0]
    assert text[ean.start:ean.end] == ean.raw_value
    assert "EAN" in ean.context_before or ":" in ean.context_before
    assert "Tags" in ean.context_after


# ---------------------------------------------------------------------------
# deduplicação por span
# ---------------------------------------------------------------------------

def test_same_span_same_field_type_deduplicated_keeping_highest_confidence():
    # "EAN: 4006381333931" dispara tanto o detector ROTULADO quanto o
    # detector "checksum" solto pro mesmo span exato -> só um sobrevive.
    candidates = find_candidates_in_text("EAN: 4006381333931", "b1")
    ean = [c for c in candidates if c.field_type == "ean"]
    assert len(ean) == 1
    assert ean[0].method == "label+checksum"  # o de maior confiança venceu


# ---------------------------------------------------------------------------
# blocos de tabela usando o cabeçalho como rótulo estrutural
# ---------------------------------------------------------------------------

def test_table_block_uses_column_header_as_implicit_label():
    block = Block(
        id="b_table",
        type=BlockType.TABLE,
        order=0,
        headers=["Produto", "EAN", "Preço"],
        rows=[["Tinta Suvinil", "4006381333931", "589,00"]],
    )
    candidates = find_candidates_in_block(block)
    ean = [c for c in candidates if c.field_type == "ean" and c.method == "table_header"]
    price = [c for c in candidates if c.field_type == "price" and c.method == "table_header"]
    assert len(ean) == 1
    assert ean[0].normalized_value == "4006381333931"
    assert len(price) == 1
    assert price[0].normalized_value == 589.00
    assert all(c.block_id == "b_table" for c in candidates)


def test_table_block_without_useful_header_still_scans_cell_text():
    block = Block(
        id="b_table2",
        type=BlockType.TABLE,
        order=0,
        headers=["Coluna A", "Coluna B"],
        rows=[["contato: carlos@example.com", "sem campo aqui"]],
    )
    candidates = find_candidates_in_block(block)
    emails = [c for c in candidates if c.field_type == "email"]
    assert len(emails) == 1


# ---------------------------------------------------------------------------
# rótulo explícito vence detector sem rótulo no mesmo span (mesmo campo
# diferente) - achado real testando a Fase 6 contra documentos reais
# ---------------------------------------------------------------------------

def test_unlabeled_ean_checksum_does_not_fire_inside_an_already_labeled_ncm():
    """Achado real: um NCM de 8 dígitos pode, por coincidência, "passar"
    no dígito verificador de EAN-8 - sem esta regra isso virava um
    segundo Candidate "ean" pro MESMO número já rotulado como NCM."""
    text = "NCM: 84672100 | EAN: 3165140832342"
    candidates = find_candidates_in_text(text, "b1")
    ean = [c for c in candidates if c.field_type == "ean"]
    ncm = [c for c in candidates if c.field_type == "ncm"]
    assert len(ncm) == 1
    assert ncm[0].normalized_value == "84672100"
    # só o EAN de verdade, rotulado - nenhum EAN "fantasma" nascido do NCM
    assert len(ean) == 1
    assert ean[0].normalized_value == "3165140832342"


def test_unlabeled_phone_does_not_fire_inside_an_already_labeled_ean():
    """Achado real: um EAN de 13 dígitos contém, por acaso, uma
    sequência de 11 dígitos que bate no formato de telefone brasileiro -
    sem esta regra isso virava um telefone "fantasma" nascido de dentro
    do EAN já rotulado."""
    text = "EAN: 3165140832342"
    candidates = find_candidates_in_text(text, "b1")
    phones = [c for c in candidates if c.field_type == "phone"]
    assert phones == []


def test_heading_block_is_scanned_like_paragraph():
    block = Block(id="b_h", type=BlockType.HEADING, order=0, text_raw="Contato: carlos@example.com", level=2)
    candidates = find_candidates_in_block(block)
    assert any(c.field_type == "email" for c in candidates)


def test_image_block_produces_no_candidates():
    from phoenix_kernel.documents.normalized import ImageMedia
    block = Block(id="b_img", type=BlockType.IMAGE, order=0, media=ImageMedia(filename="x.jpg"))
    assert find_candidates_in_block(block) == []


def test_empty_text_produces_no_candidates():
    assert find_candidates_in_text("", "b1") == []
    assert find_candidates_in_text(None, "b1") == []


# ---------------------------------------------------------------------------
# PHX-NEW (2026-08-29) - expansão de vocabulário V2, grupo
# "determinístico": dimensões (height/width/depth) e texto livre
# explicitamente rotulado. Ver PHX-NEW no topo do módulo pro contexto
# completo dos achados reais que motivaram cada decisão.
# ---------------------------------------------------------------------------

def test_height_width_depth_with_unit_in_label_convert_to_canonical_meters():
    """Achado real: "Altura (cm): 34,8" - a unidade fica só no RÓTULO,
    nunca no valor. Sem propagar essa dica pro Normalizer, isso nunca
    seria reconhecido como equivalente a "Altura: 0,348 m"."""
    text = "Altura (cm): 34,8 | Largura (cm): 8,3 | Profundidade (cm): 8,5"
    candidates = find_candidates_in_text(text, "b1")
    by_type = {c.field_type: c for c in candidates}
    assert by_type["height"].normalized_value == 0.348
    assert by_type["height"].unit == "m"
    assert by_type["height"].raw_value.strip() == "34,8"  # raw NUNCA ganha a unidade emprestada
    assert by_type["width"].normalized_value == 0.083
    assert by_type["depth"].normalized_value == 0.085


def test_height_with_unit_in_label_equals_height_with_unit_in_value():
    a = find_candidates_in_text("Altura (cm): 34,8", "b1")[0]
    b = find_candidates_in_text("Altura: 0,348 m", "b2")[0]
    assert a.field_type == b.field_type == "height"
    assert a.normalized_value == b.normalized_value
    assert a.unit == b.unit == "m"


def test_weight_bugfix_unit_hint_in_label_now_recognized():
    """PHX-FIX: antes desta expansão, "Peso (Kg): 24,500" não gerava
    Candidate NENHUM (o rótulo fechado da Fase 4 original não previa
    unidade colada no rótulo) - achado real testando o mesmo documento
    já usado pra fechar as Fases 6/9/10."""
    candidates = find_candidates_in_text("Peso (Kg): 24,500 (Líq.) | 25,200 (Bruto)", "b1")
    weights = [c for c in candidates if c.field_type == "weight"]
    assert len(weights) == 1
    assert weights[0].normalized_value == 24.5
    assert weights[0].unit == "kg"
    assert weights[0].valid is True


def test_brand_label_strips_html_noise_and_stops_at_pipe():
    """Achado real (linha "Ficha Técnica" das descrições HTML):
    "<b>Marca:</b> <b>Bonafont (Danone) |</b> <b>Volume:</b> ..."."""
    text = "</p><p><b>Marca:</b> <b>Bonafont (Danone) |</b> <b>Volume:</b> <b>500ml |</b>"
    candidates = find_candidates_in_text(text, "b1")
    brands = [c for c in candidates if c.field_type == "brand"]
    assert len(brands) == 1
    assert brands[0].normalized_value == "Bonafont (Danone)"


def test_tags_label_splits_and_cleans_semicolon_list():
    text = "Tags: tinta suvinil; toque de seda; acetinado; premium."
    candidates = find_candidates_in_text(text, "b1")
    tags = [c for c in candidates if c.field_type == "tags"]
    assert len(tags) == 1
    assert tags[0].normalized_value == "tinta suvinil; toque de seda; acetinado; premium"


def test_description_html_block_detected_by_format_alone_no_label_needed():
    """Achado real: o delimitador textual "[DESCRIÇÃO DO PRODUTO ...]"
    quase sempre aparece em trecho INSTRUCIONAL da conversa, não colado
    no HTML de verdade - o sinal confiável é o bloco começar direto com
    `<p>`/`<div><p>` (mesma categoria de "formato já é sinal forte" que
    e-mail/"R$"/EAN com checksum)."""
    text = "<p>A <b>Água Mineral Bonafont Com Gás 500ml</b> é a escolha inteligente.</p>"
    candidates = find_candidates_in_text(text, "b1")
    desc = [c for c in candidates if c.field_type == "description_html"]
    assert len(desc) == 1
    assert desc[0].valid is True
    assert desc[0].normalized_value == text


def test_description_html_rejects_multiline_but_preserves_raw():
    text = "<p>Linha 1</p>\n<p>Linha 2</p>"
    candidates = find_candidates_in_text(text, "b1")
    desc = [c for c in candidates if c.field_type == "description_html"]
    assert len(desc) == 1
    assert desc[0].valid is False
    assert desc[0].raw_value == text  # "achar padrão != aceitar como verdade"


def test_explicit_product_name_recognizes_labeled_name_but_not_titulo():
    """PHX-NEW: "Título" foi deliberadamente excluído do vocabulário de
    `explicit_product_name` - achado real: nos documentos-fonte,
    "Título:" aparece muito mais como prosa de estratégia de título
    do que como rótulo de um nome de produto de verdade."""
    labeled = find_candidates_in_text("Nome do Produto: Furadeira de Impacto Bosch GSB 13 RE", "b1")
    names = [c for c in labeled if c.field_type == "explicit_product_name"]
    assert len(names) == 1
    assert names[0].normalized_value == "Furadeira de Impacto Bosch GSB 13 RE"

    titulo_text = "Título: Produto + Medida + Marca + Resultado."
    titulo_candidates = find_candidates_in_text(titulo_text, "b1")
    assert all(c.field_type != "explicit_product_name" for c in titulo_candidates)


def test_included_items_and_specifications_labels():
    items = find_candidates_in_text("Itens Inclusos: 01 fita telada 100mm x 20m", "b1")
    assert any(c.field_type == "included_items" and c.normalized_value == "01 fita telada 100mm x 20m" for c in items)

    specs = find_candidates_in_text("Especificações: aço inox, 30cm", "b1")
    assert any(c.field_type == "specifications" and c.normalized_value == "aço inox, 30cm" for c in specs)


def test_table_header_maps_new_dimensional_and_text_fields():
    block = Block(
        id="b_table3", type=BlockType.TABLE, order=0,
        headers=["Altura", "Marca", "Tags"],
        rows=[["34,8 cm", "Bonafont", "agua; mineral; gaseificada"]],
    )
    candidates = find_candidates_in_block(block)
    by_type = {c.field_type: c for c in candidates}
    assert by_type["height"].normalized_value == 0.348
    assert by_type["brand"].normalized_value == "Bonafont"
    assert by_type["tags"].normalized_value == "agua; mineral; gaseificada"


# PHX-NEW (2026-08-29, expansão de vocabulário V2 - grupo "preço", ver
# PHX-NEW no topo de candidate_engine.py pro contexto completo): os seis
# field_types comerciais - cost_price/retail_price/wholesale_price/
# wholesale_min_quantity/compare_at_price/sale_price - deliberadamente
# separados de price/price_min/price_max.

def test_cost_price_labeled_variants_produce_commercial_money_shape():
    for text in ("Preço de Custo: R$ 19,90", "Preço Custo: R$ 19,90", "Custo: R$ 19,90"):
        candidates = find_candidates_in_text(text, "b1")
        cost = [c for c in candidates if c.field_type == "cost_price"]
        assert len(cost) == 1, text
        assert cost[0].raw_value == "R$ 19,90"
        assert cost[0].parsed_value == 19.90
        assert cost[0].normalized_value == 19.90
        assert cost[0].unit == "BRL"
        assert cost[0].original_unit == "R$"


def test_retail_price_labeled_variants_produce_commercial_money_shape():
    for text in ("Preço Venda Varejo: R$ 29,90", "Preço de Venda: R$ 29,90", "Preço Varejo: R$ 29,90"):
        candidates = find_candidates_in_text(text, "b1")
        retail = [c for c in candidates if c.field_type == "retail_price"]
        assert len(retail) == 1, text
        assert retail[0].normalized_value == 29.90
        assert retail[0].unit == "BRL"
        assert retail[0].original_unit == "R$"


def test_wholesale_price_labeled_variants():
    for text in ("Preço Venda Atacado: R$ 24,90", "Preço Atacado: R$ 24,90"):
        candidates = find_candidates_in_text(text, "b1")
        wholesale = [c for c in candidates if c.field_type == "wholesale_price"]
        assert len(wholesale) == 1, text
        assert wholesale[0].normalized_value == 24.90
        assert wholesale[0].unit == "BRL"


def test_wholesale_min_quantity_is_a_bare_quantity_never_currency():
    candidates = find_candidates_in_text("Quantidade Mínima Atacado: 12 unidades", "b1")
    qty = [c for c in candidates if c.field_type == "wholesale_min_quantity"]
    assert len(qty) == 1
    assert qty[0].parsed_value == 12.0
    assert qty[0].normalized_value == 12.0
    assert qty[0].unit == "unit"
    assert qty[0].original_unit == "unidades"

    candidates2 = find_candidates_in_text("Qtd. Mínima Atacado: 6", "b1")
    qty2 = [c for c in candidates2 if c.field_type == "wholesale_min_quantity"]
    assert len(qty2) == 1
    assert qty2[0].normalized_value == 6.0
    assert qty2[0].unit == "unit"


def test_compare_at_price_and_sale_price_require_the_word_preco():
    """Pedido explícito do usuário: "De:"/"Por:" isolados são palavras
    comuns demais pra virar rótulo de campo - só "Preço De:"/"Preço Por:"
    contam (mesma filosofia que excluiu "Título:" de
    explicit_product_name)."""
    de_candidates = find_candidates_in_text("Preço De: R$ 59,90", "b1")
    compare = [c for c in de_candidates if c.field_type == "compare_at_price"]
    assert len(compare) == 1
    assert compare[0].normalized_value == 59.90
    assert compare[0].unit == "BRL"

    por_candidates = find_candidates_in_text("Preço Por: R$ 39,90", "b1")
    sale = [c for c in por_candidates if c.field_type == "sale_price"]
    assert len(sale) == 1
    assert sale[0].normalized_value == 39.90

    # "De:"/"Por:" sozinhos (sem "Preço") NUNCA viram compare_at_price/sale_price
    bare_de = find_candidates_in_text("De: R$ 10,00", "b1")
    assert [c for c in bare_de if c.field_type == "compare_at_price"] == []
    bare_por = find_candidates_in_text("Por: R$ 5,00", "b1")
    assert [c for c in bare_por if c.field_type == "sale_price"] == []


def test_generic_price_family_unaffected_for_non_overlapping_labels():
    """"Preço:"/"Valor:"/"Preço Mínimo:"/"Preço Máximo:" soltos continuam
    100% inalterados pela expansão comercial - só "Preço de Custo"/"Preço
    de Venda" mudam de família (ver próximo teste)."""
    assert find_candidates_in_text("Preço: R$ 45,00", "b1")[0].field_type == "price"
    assert find_candidates_in_text("Valor: R$ 33,00", "b1")[0].field_type == "price"
    text = "Preço Mínimo: R$ 10,00 | Preço Máximo: R$ 20,00"
    candidates = find_candidates_in_text(text, "b1")
    assert {c.field_type for c in candidates} == {"price_min", "price_max"}


def test_preco_de_venda_and_preco_de_custo_no_longer_also_produce_generic_price():
    """PHX-NEW: achado arquitetural desta rodada - o `_PRICE_LABEL_RE`
    genérico já reconhecia "Preço de Venda"/"Preço de Custo" como rótulo,
    mapeando pra `price` genérico; agora que `cost_price`/`retail_price`
    também reconhecem esses mesmos rótulos, o span idêntico precisa
    resolver pra UMA leitura só - a mais específica vence (confiança
    0.97 > 0.95), então o `price` genérico duplicado desaparece."""
    venda = find_candidates_in_text("Preço de Venda: R$ 39,90", "b1")
    assert {c.field_type for c in venda} == {"retail_price"}
    assert len(venda) == 1

    custo = find_candidates_in_text("Preço de Custo: R$ 19,90", "b1")
    assert {c.field_type for c in custo} == {"cost_price"}
    assert len(custo) == 1


def test_table_header_maps_commercial_price_fields_before_generic_price():
    """As colunas reais do MarketUP ("Preço de Custo", "Preço Venda
    Varejo", "Preço Venda Atacado", "Preço De", "Preço Por") todas contêm
    a palavra "Preço" - precisam ser reconhecidas pelos field_types
    comerciais específicos, não pelo cabeçalho genérico "preço|valor"."""
    block = Block(
        id="b_table_price", type=BlockType.TABLE, order=0,
        headers=[
            "Preço de Custo", "Preço Venda Varejo", "Preço Venda Atacado",
            "Quantidade Mínima Atacado", "Preço De", "Preço Por", "Preço",
        ],
        rows=[["19.90", "29.90", "24.90", "12", "59.90", "39.90", "45.00"]],
    )
    candidates = find_candidates_in_block(block)
    header_candidates = {c.field_type: c for c in candidates if c.method == "table_header"}
    assert header_candidates["cost_price"].normalized_value == 19.90
    assert header_candidates["retail_price"].normalized_value == 29.90
    assert header_candidates["wholesale_price"].normalized_value == 24.90
    assert header_candidates["wholesale_min_quantity"].normalized_value == 12.0
    assert header_candidates["wholesale_min_quantity"].unit == "unit"
    assert header_candidates["compare_at_price"].normalized_value == 59.90
    assert header_candidates["sale_price"].normalized_value == 39.90
    assert header_candidates["price"].normalized_value == 45.00
    for field in ("cost_price", "retail_price", "wholesale_price", "compare_at_price", "sale_price"):
        assert header_candidates[field].unit == "BRL"
        assert header_candidates[field].original_unit == "R$"
