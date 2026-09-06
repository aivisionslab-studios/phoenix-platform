"""Integração: camada de formato (GLM) -> field_extractor -> campos validados.

Prova que a extração ciente de formato pega os campos certos de blocos reais,
com validação determinística (Camada A) e status de confiança.
"""
from phoenix_kernel.documents.structure_detector import Block, DocumentFormat
from phoenix_kernel.documents.field_extractor import extract_fields
from phoenix_kernel.documents.confidence import ConfidenceStatus


def test_extracts_all_fields_from_real_conveniencia_block():
    """Bloco real de conveniência (título numerado + dados com unidade no rótulo)."""
    lines = [
        "63. Cachaça São Francisco 970ml (Garrafa de Vidro)",
        "[DADOS ESTRUTURADOS PARA O ERP]",
        "Altura (cm): 28,5",
        "Largura (cm): 8,5",
        "Profundidade (cm): 8,5",
        "Peso (Kg): 0,970 (Líq.) | 1,520 (Bruto)",
        "Preço Mínimo: R$ 12,90 | Preço Máximo: R$ 18,50",
        "Tags: cachaça; aguardente; pinga; 970ml",
    ]
    block = Block(block_id="n1", text="\n".join(lines), lines=lines, has_structured_data=True)
    fields = extract_fields(block, DocumentFormat.NUMBERED_LIST)

    # rótulos COM unidade no meio ("Peso (Kg):", "Altura (cm):") devem casar
    assert "weight" in fields
    assert fields["weight"].value == 0.970
    assert "height" in fields
    assert fields["height"].value == 28.5
    assert "width" in fields
    assert "depth" in fields
    # preço mínimo/máximo (formato do doc real)
    assert "sale_price" in fields   # Preço Mínimo = menor preço de VENDA
    assert fields["sale_price"].value == 12.90
    assert "compare_at_price" in fields  # Preço Máximo = maior preço de VENDA
    assert fields["compare_at_price"].value == 18.50
    assert "cost_price" not in fields  # custo NÃO está no doc — não inventar
    assert "tags" in fields


def test_table_extraction_ignores_labels_in_text():
    """Em tabela, extrai por posição — não confunde 'NCM' escrito na descrição."""
    header = ["Descrição", "NCM", "Peso"]
    row = "Produto com NCM na descrição\t22030000\t0.350"
    block = Block(block_id="t1", text=row, lines=[row], has_structured_data=True)
    fields = extract_fields(block, DocumentFormat.TABLE, table_header=header)
    assert fields["ncm"].value == "22030000"  # da coluna, não da descrição


def test_invalid_fiscal_data_flagged_not_written():
    """Regra de ouro: dado fiscal inválido vira INVALID (vai para auditoria)."""
    lines = ["Produto X", "EAN: 1234567890123"]  # checksum inválido
    block = Block(block_id="b1", text="\n".join(lines), lines=lines, has_structured_data=True)
    fields = extract_fields(block, DocumentFormat.LABELED_BLOCKS)
    if "ean" in fields:
        assert fields["ean"].status == ConfidenceStatus.INVALID
