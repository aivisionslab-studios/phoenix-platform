import pytest
from phoenix_kernel.documents.field_extractor import extract_fields
from phoenix_kernel.documents.structure_detector import Block, DocumentFormat
from phoenix_kernel.documents.confidence import ConfidenceStatus

def test_extract_from_labeled_blocks_with_separators():
    block = Block(block_id="B1",
        text="Tinta Acrílica Suvinil\nNCM: 32091010 | CEST: 2400100\nPeso: 24.5 Kg\nPreço: R$ 100,00",
        lines=["Tinta Acrílica Suvinil","NCM: 32091010 | CEST: 2400100","Peso: 24.5 Kg","Preço: R$ 100,00"],
        has_structured_data=True)
    fields = extract_fields(block, DocumentFormat.LABELED_BLOCKS)
    assert fields["ncm"].value == "32091010"
    assert fields["cest"].value == "2400100"
    assert fields["weight"].value == 24.5
    assert fields["price"].value == 100.00

def test_extract_from_table_by_position():
    header = ["Descrição","NCM","CEST","Peso","Preço Venda Varejo"]
    row = "Cerveja X\t22030000\t0302100\t0.350\t8.69"
    block = Block(block_id="T1", text=row, lines=[row], has_structured_data=True)
    fields = extract_fields(block, DocumentFormat.TABLE, table_header=header)
    assert fields["ncm"].value == "22030000"
    assert fields["weight"].value == 0.350
    assert fields["retail_price"].value == 8.69
    assert "price" not in fields

def test_extract_invalid_ean_goes_to_audit():
    block = Block(block_id="B2", text="Produto Z\nEAN: 7891114000141",
        lines=["Produto Z","EAN: 7891114000141"], has_structured_data=True)
    fields = extract_fields(block, DocumentFormat.LABELED_BLOCKS)
    assert "ean" in fields
    assert fields["ean"].status == ConfidenceStatus.INVALID

def test_extract_synonyms_ean():
    block = Block(block_id="B3", text="Produto W\nCód. Barras: 7891000100103",
        lines=["Produto W","Cód. Barras: 7891000100103"], has_structured_data=True)
    fields = extract_fields(block, DocumentFormat.LABELED_BLOCKS)
    assert fields["ean"].value == "7891000100103"
    assert fields["ean"].status == ConfidenceStatus.CONFIRMED

def test_extract_brazilian_price_format():
    block = Block(block_id="B4", text="Produto Y\nPreço Venda Varejo: R$ 1.234,56",
        lines=["Produto Y","Preço Venda Varejo: R$ 1.234,56"], has_structured_data=True)
    fields = extract_fields(block, DocumentFormat.LABELED_BLOCKS)
    assert fields["retail_price"].value == 1234.56
