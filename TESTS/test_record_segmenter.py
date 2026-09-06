"""Testes da Fase 5 do "Document Pipeline V2" (phoenix_kernel/documents/
record_segmenter.py) - agrupa Block+Candidate em Record. Ver PHX-NEW no
topo daquele arquivo pro contexto e princípios completos (só agrupa,
nunca valida/classifica/chama LLM).

O teste mais importante deste arquivo é
`test_two_distinct_products_become_two_separate_records` - pedido
explícito do usuário: "produto A / dados A / descrição A" seguido de
"produto B / dados B / descrição B" tem que virar DOIS records, nunca um
record único misturando os dois (erro considerado mais perigoso que
perder um candidato individual)."""
from __future__ import annotations

from phoenix_kernel.documents.candidate_engine import find_candidates_in_document
from phoenix_kernel.documents.normalized import Block, BlockType, ImageMedia, NormalizedDocument, RecordKind
from phoenix_kernel.documents.record_segmenter import segment_records


def _doc(blocks: list[Block]) -> NormalizedDocument:
    return NormalizedDocument(document_id="doc1", source_name="teste.docx", source_type="docx", blocks=blocks)


def test_two_distinct_products_become_two_separate_records():
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="1. Produto A"),
        Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="NCM: 32091010 | Preço: R$ 10,00"),
        Block(id="b3", type=BlockType.PARAGRAPH, order=2, text_raw="Descrição do produto A, ótimo pra uso geral."),
        Block(id="b4", type=BlockType.PARAGRAPH, order=3, text_raw="2. Produto B"),
        Block(id="b5", type=BlockType.PARAGRAPH, order=4, text_raw="NCM: 38245000 | Preço: R$ 20,00"),
        Block(id="b6", type=BlockType.PARAGRAPH, order=5, text_raw="Descrição do produto B."),
    ]
    doc = _doc(blocks)
    candidates = find_candidates_in_document(doc)
    records = segment_records(doc, candidates)

    assert len(records) == 2
    assert records[0].block_ids == ["b1", "b2", "b3"]
    assert records[1].block_ids == ["b4", "b5", "b6"]
    assert records[0].kind is RecordKind.UNKNOWN  # segmenter nunca classifica
    assert records[1].kind is RecordKind.UNKNOWN


def test_consecutive_data_blocks_without_title_still_split():
    """Padrão real visto no documento do usuário: blocos de dados ERP em
    sequência, sem nenhuma linha de título separando um do outro - ainda
    assim precisam virar records distintos."""
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="[DADOS ERP] NCM: 11111111 CEST: 1000100 Preço: R$ 5,00"),
        Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="[DADOS ERP] NCM: 22222222 CEST: 2400100 Preço: R$ 6,00"),
    ]
    doc = _doc(blocks)
    candidates = find_candidates_in_document(doc)
    records = segment_records(doc, candidates)

    assert len(records) == 2
    assert records[0].block_ids == ["b1"]
    assert records[1].block_ids == ["b2"]


def test_invalid_ean_is_preserved_inside_record_not_dropped_or_fixed():
    """Regra explícita do usuário: o Segmenter não corrige nem descarta
    Candidate - um EAN inválido continua fazendo parte do record."""
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="1. Produto com EAN suspeito"),
        Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="EAN: 7891019125301 | NCM: 32091010"),
    ]
    doc = _doc(blocks)
    candidates = find_candidates_in_document(doc)
    records = segment_records(doc, candidates)

    assert len(records) == 1
    ean_candidates = [c for c in candidates if c.field_type == "ean"]
    assert len(ean_candidates) == 1
    assert ean_candidates[0].valid is False  # continua inválido, não "corrigido"
    assert ean_candidates[0].id in records[0].candidate_ids  # e continua referenciado no record


def test_record_start_and_end_order_span_its_blocks():
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=5, text_raw="1. Produto"),
        Block(id="b2", type=BlockType.PARAGRAPH, order=6, text_raw="NCM: 32091010"),
        Block(id="b3", type=BlockType.PARAGRAPH, order=7, text_raw="mais descrição"),
    ]
    doc = _doc(blocks)
    candidates = find_candidates_in_document(doc)
    records = segment_records(doc, candidates)

    assert len(records) == 1
    assert records[0].start_order == 5
    assert records[0].end_order == 7
    assert records[0].segmentation_method == "structural+heuristic"


def test_image_block_is_absorbed_without_starting_a_new_record():
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="1. Produto A"),
        Block(id="b2", type=BlockType.IMAGE, order=1, media=ImageMedia(filename="foto.jpg")),
        Block(id="b3", type=BlockType.PARAGRAPH, order=2, text_raw="NCM: 32091010 | Preço: R$ 10,00"),
    ]
    doc = _doc(blocks)
    candidates = find_candidates_in_document(doc)
    records = segment_records(doc, candidates)

    assert len(records) == 1
    assert records[0].block_ids == ["b1", "b2", "b3"]


def test_table_with_strong_identifier_can_start_new_record():
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="NCM: 32091010 | Preço: R$ 10,00"),
        Block(id="b2", type=BlockType.TABLE, order=1, headers=["Produto", "EAN"], rows=[["Outro item", "4006381333931"]]),
    ]
    doc = _doc(blocks)
    candidates = find_candidates_in_document(doc)
    records = segment_records(doc, candidates)

    assert len(records) == 2
    assert records[1].block_ids == ["b2"]


def test_confidence_is_higher_with_more_valid_strong_identifiers():
    blocks_one_field = [Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Preço: R$ 10,00")]
    blocks_three_fields = [Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="NCM: 32091010 | CEST: 2400100 | Preço: R$ 10,00")]

    doc_one = _doc(blocks_one_field)
    doc_three = _doc(blocks_three_fields)
    records_one = segment_records(doc_one, find_candidates_in_document(doc_one))
    records_three = segment_records(doc_three, find_candidates_in_document(doc_three))

    assert records_three[0].confidence > records_one[0].confidence
    assert records_three[0].confidence <= 0.95


def test_no_strong_identifier_anywhere_yields_low_confidence_single_record():
    blocks = [
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="Texto solto sem nenhum campo reconhecível."),
    ]
    doc = _doc(blocks)
    records = segment_records(doc, find_candidates_in_document(doc))
    assert len(records) == 1
    assert records[0].confidence == 0.2


def test_long_stretch_without_any_signal_forces_a_new_record_boundary():
    """Achado real testando com o segundo documento real do usuário
    ("instruções para construção de site de vendas.docx"): mesmo depois
    do fix do título-sempre-fecha, um record que já tinha identificador
    forte e depois entrava num trecho MUITO longo sem nenhum sinal (sem
    título, sem novo identificador forte) nunca fechava sozinho - no
    documento real isso chegou a grudar 487 blocos num record só,
    começando num produto real ("94. Batata Pringles...") e arrastando
    consigo dezenas de blocos de comentário sem relação nenhuma. Depois
    de `_MAX_BLOCKS_WITHOUT_SIGNAL` blocos seguidos "em silêncio", o
    record tem que fechar sozinho."""
    blocks = [
        Block(id="b0", type=BlockType.PARAGRAPH, order=0, text_raw="1. Produto A"),
        Block(id="b1", type=BlockType.PARAGRAPH, order=1, text_raw="NCM: 32091010 | Preço: R$ 10,00"),
    ]
    for i in range(50):
        blocks.append(Block(
            id=f"noise{i}",
            type=BlockType.PARAGRAPH,
            order=2 + i,
            text_raw=f"Comentário solto número {i}, sem nenhum campo reconhecível.",
        ))
    doc = _doc(blocks)
    candidates = find_candidates_in_document(doc)
    records = segment_records(doc, candidates)

    assert len(records) >= 2
    # o record do produto A de verdade não pode ter engolido todo o
    # trecho de silêncio - tem que ter fechado bem antes dos 50 blocos.
    assert len(records[0].block_ids) < 45


def test_empty_document_yields_no_records():
    doc = _doc([])
    assert segment_records(doc, []) == []


def test_records_do_not_reorder_blocks():
    blocks = [
        Block(id="b3", type=BlockType.PARAGRAPH, order=2, text_raw="descrição"),
        Block(id="b1", type=BlockType.PARAGRAPH, order=0, text_raw="1. Produto"),
        Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="NCM: 32091010"),
    ]
    doc = _doc(blocks)  # blocos deliberadamente fora de ordem na lista
    records = segment_records(doc, find_candidates_in_document(doc))
    assert len(records) == 1
    assert records[0].block_ids == ["b1", "b2", "b3"]  # ordenado por .order, não pela ordem da lista
