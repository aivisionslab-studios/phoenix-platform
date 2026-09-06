"""Testes do detector de formato com suporte a documentos MISTOS.

2ª rodada da colaboração com o GLM: a 1ª tentativa dele reintroduziu o bug do
"desempate de tabela" (linhas com ';'/tab dentro de blocos rotulados/numerados
viravam tabelas falsas, fragmentando produtos). Corrigido com guarda de
contexto (um sinal de tabela só abre bloco fora de um bloco de produto já
aberto) e lookahead para título numerado (só é boundary se seguido de perto
por dado real — evita confundir cabeçalho de categoria/índice com produto).
"""
from phoenix_kernel.documents.structure_detector import detect_format, DocumentFormat


_MIXED_DOC = """
Descrição\tNCM\tCEST
Cerveja X\t22030000\t0302100
Refrigerante Y\t22021000\t0301000

Tinta Acrílica Suvinil
[DADOS ESTRUTURADOS] NCM: 32091010

63. Cachaça
NCM: 22084000
"""


def test_mixed_document_has_per_block_format():
    """Documento com 3 formatos: cada bloco carrega o SEU formato correto."""
    result = detect_format(_MIXED_DOC)
    assert result.format == DocumentFormat.MIXED
    formats = [b.format for b in result.blocks]
    assert DocumentFormat.TABLE in formats
    assert DocumentFormat.LABELED_BLOCKS in formats
    assert DocumentFormat.NUMBERED_LIST in formats


def test_pure_numbered_list_no_regression():
    text = "63. Cachaça\nNCM: 123\n64. Cerveja\nNCM: 456"
    result = detect_format(text)
    assert result.format == DocumentFormat.NUMBERED_LIST
    assert len(result.blocks) == 2


def test_pure_labeled_blocks_no_regression():
    text = "Tinta\n[DADOS ESTRUTURADOS] NCM: 123\nArgamassa\n[DADOS ESTRUTURADOS] NCM: 456"
    result = detect_format(text)
    assert result.format == DocumentFormat.LABELED_BLOCKS
    assert len(result.blocks) == 2
    assert result.blocks[0].title == "Tinta"
    assert result.blocks[1].title == "Argamassa"


def test_semicolon_data_inside_labeled_block_does_not_fragment():
    """Regressão do bug original: dados com ';' dentro de um bloco rotulado
    NÃO devem virar uma tabela falsa (bug reintroduzido e corrigido nesta
    rodada)."""
    text = (
        "Produto A\n"
        "[DADOS ESTRUTURADOS] NCM: 111; CEST: 222; Peso: 1; Altura: 2\n"
        "Produto B\n"
        "[DADOS ESTRUTURADOS] NCM: 333; CEST: 444; Peso: 3; Altura: 4\n"
    )
    result = detect_format(text)
    assert result.format == DocumentFormat.LABELED_BLOCKS
    assert len(result.blocks) == 2  # não fragmentou em blocos-tabela falsos


def test_category_header_numbered_line_is_not_a_product():
    """'1. Linha Suvinil Fosco Completo' (cabeçalho de categoria/índice, sem
    dado logo depois) não deve virar um produto numerado falso."""
    text = (
        "1. Linha Suvinil Fosco Completo\n"
        "Texto de introdução sobre a linha de produtos.\n"
        "Mais um parágrafo de contexto sem dado nenhum.\n"
    )
    result = detect_format(text)
    # não deve segmentar como numbered_list (sem NCM/preço/etc por perto)
    assert not any(b.format == DocumentFormat.NUMBERED_LIST for b in result.blocks)


def test_prose_mention_of_data_word_is_not_a_data_signal():
    """Achado real: 'O preço tem que ser o panfleto da loja' (prosa comum
    numa discussão de estratégia de vendas) NÃO deve ser confundido com dado
    de produto — a palavra 'preço' solta na frase, sem rótulo:número por
    perto, não é sinal de produto real. Antes desta correção, um cabeçalho de
    seção ('1. Quadrante: O BOI...') seguido de perto por essa frase virava
    um produto falso que roubava dados de um produto real distante."""
    text = (
        "1. Quadrante: O BOI (Volume / Isca)\n"
        "Produtos: Cerveja de giro (Brahma/Skol/Antarctica), Coca-Cola 2L, Cigarros.\n"
        "Estratégia: Margem Mínima (5% a 12%).\n"
        "Função: Trazer o cliente para dentro. O preço tem que ser o \"panfleto\" da loja.\n"
        "2. Quadrante: O CARRINHO (Conveniência / Giro Médio)\n"
    )
    result = detect_format(text)
    # nenhum bloco deve ter "Quadrante" como título de produto numerado
    assert not any(
        b.format == DocumentFormat.NUMBERED_LIST and "Quadrante" in b.title
        for b in result.blocks
    )


def test_real_numbered_product_with_price_label_still_works():
    """Zero regressão: um rótulo real ('Preço Mínimo: R$ 12,90') continua
    sendo reconhecido como dado de produto — só a palavra solta em prosa que
    deixou de contar."""
    text = (
        "63. Cachaça São Francisco 970ml\n"
        "Preço Mínimo: R$ 12,90 | Preço Máximo: R$ 18,50\n"
    )
    result = detect_format(text)
    assert any(
        b.format == DocumentFormat.NUMBERED_LIST and "Cachaça" in b.title
        for b in result.blocks
    )
