"""Testes do contrato de dados da Fase 1 do "Document Pipeline V2"
(phoenix_kernel/documents/normalized.py) - ver PHX-NEW no topo daquele
arquivo pro contexto completo (achado real: preenchimento de planilha
perdendo dezenas de produtos de uma vez quando um chunk de caracteres
falhava).

Este arquivo testa SÓ o contrato (serialização, preservação de ordem,
separação raw/normalized, identidade por conteúdo) - nenhuma lógica de
parsing/segmentação/execução existe ainda pra testar."""
from __future__ import annotations

import json

from phoenix_kernel.documents.normalized import (
    Block,
    BlockSource,
    BlockType,
    Candidate,
    DocumentMetadata,
    ImageMedia,
    JobMapping,
    JobPlan,
    JobSource,
    JobState,
    JobStrategy,
    JobTarget,
    NormalizedDocument,
    Record,
    RecordKind,
    RecordState,
    RecordStatus,
    compute_document_id,
)


def test_paragraph_block_roundtrip():
    block = Block(
        id="b000001",
        type=BlockType.PARAGRAPH,
        order=0,
        text_raw="Tinta Acrílica Suvinil 18L",
        text_normalized="Tinta Acrílica Suvinil 18L",
        source=BlockSource(paragraph_index=87),
    )
    restored = Block.from_dict(block.to_dict())
    assert restored == block
    assert restored.type is BlockType.PARAGRAPH


def test_heading_block_has_level():
    block = Block(id="b000002", type=BlockType.HEADING, order=1, text_raw="Dados do contrato", level=2)
    d = block.to_dict()
    assert d["type"] == "heading"
    assert d["level"] == 2
    restored = Block.from_dict(d)
    assert restored.level == 2


def test_table_block_keeps_headers_and_rows_structured_not_flattened():
    """Achado real que motivou este schema: `_extract_docx` hoje achata
    cada linha de tabela em "cel1 | cel2 | cel3" sem cabeçalho. O
    `Block` de tabela nunca deve fazer isso - precisa expor `headers` e
    `rows` como listas estruturadas, nunca como uma única string."""
    block = Block(
        id="b000003",
        type=BlockType.TABLE,
        order=2,
        headers=["Produto", "EAN", "NCM", "Preço"],
        rows=[["Tinta Suvinil", "7891019125301", "32091010", "589,00"]],
        source=BlockSource(table_index=3),
    )
    d = block.to_dict()
    assert d["headers"] == ["Produto", "EAN", "NCM", "Preço"]
    assert d["rows"] == [["Tinta Suvinil", "7891019125301", "32091010", "589,00"]]
    assert "|" not in json.dumps(d["rows"])  # nunca achatado em string com "|"
    restored = Block.from_dict(d)
    assert restored.headers == block.headers
    assert restored.rows == block.rows


def test_image_block_records_placeholder_before_any_ocr_exists():
    block = Block(
        id="b000004",
        type=BlockType.IMAGE,
        order=3,
        source=BlockSource(relationship_id="rId19"),
        media=ImageMedia(filename="image7.png", mime_type="image/png"),
    )
    restored = Block.from_dict(block.to_dict())
    assert restored.media.filename == "image7.png"
    assert restored.text_raw is None  # sem OCR nesta fase - só o placeholder


def test_normalized_document_roundtrip_preserves_block_order():
    doc = NormalizedDocument(
        document_id=compute_document_id(b"conteudo de teste"),
        source_name="Conversa com o Gemini.docx",
        source_type="docx",
        metadata=DocumentMetadata(title=None, author=None, created_at=None),
        blocks=[
            Block(id="b1", type=BlockType.HEADING, order=0, text_raw="Produtos", level=1),
            Block(id="b2", type=BlockType.PARAGRAPH, order=1, text_raw="Tinta Acrílica..."),
            Block(id="b3", type=BlockType.TABLE, order=2, headers=["Produto", "EAN"], rows=[["Tinta", "789"]]),
        ],
    )
    restored = NormalizedDocument.from_json(doc.to_json())
    assert [b.id for b in restored.blocks] == ["b1", "b2", "b3"]
    assert [b.order for b in restored.blocks] == [0, 1, 2]
    assert restored.document_id == doc.document_id


def test_compute_document_id_is_content_based_not_path_based():
    id_a = compute_document_id(b"mesmo conteudo")
    id_b = compute_document_id(b"mesmo conteudo")
    id_c = compute_document_id(b"conteudo diferente")
    assert id_a == id_b  # mesmo conteúdo -> mesmo id, não importa de onde veio
    assert id_a != id_c
    assert "/" not in id_a and "\\" not in id_a  # nunca parece um caminho


def test_candidate_keeps_raw_and_normalized_value_separate():
    candidate = Candidate(
        field_type="money",
        raw_value="R$ 1.234,56",
        normalized_value=1234.56,
        block_id="b000010",
        method="regex",
        confidence=1.0,
    )
    restored = Candidate.from_dict(candidate.to_dict())
    assert restored.raw_value == "R$ 1.234,56"  # nunca descarta o valor bruto
    assert restored.normalized_value == 1234.56


def test_record_defaults_to_unknown_kind():
    record = Record(record_id="r0042", block_ids=["b1", "b2"])
    assert record.kind is RecordKind.UNKNOWN
    restored = Record.from_dict(record.to_dict())
    assert restored.kind is RecordKind.UNKNOWN
    assert restored.block_ids == ["b1", "b2"]


def test_job_plan_sources_reference_document_id_not_a_file_path():
    plan = JobPlan(
        job_id="job_123",
        operation="fill_spreadsheet",
        sources=[JobSource(document_id=compute_document_id(b"doc"))],
        target=JobTarget(type="xlsx", path="CATALOGO_FINAL_MARKETUP.xlsx"),
        mapping=JobMapping(columns=["Código de Barras", "Descrição", "NCM", "Preço"]),
        strategy=JobStrategy(),
    )
    d = plan.to_dict()
    assert "document_id" in d["sources"][0]
    assert "path" not in d["sources"][0]  # identidade da FONTE nunca é um caminho
    restored = JobPlan.from_dict(d)
    assert restored.sources[0].document_id == plan.sources[0].document_id
    assert restored.strategy.deterministic_first is True
    assert restored.strategy.llm_fallback is True


def test_job_state_tracks_status_per_record_not_per_chunk():
    state = JobState(
        job_id="job_123",
        records={
            "r0001": RecordState(status=RecordStatus.DONE, attempts=1),
            "r0002": RecordState(status=RecordStatus.FAILED, attempts=2),
            "r0003": RecordState(status=RecordStatus.PENDING),
        },
    )
    restored = JobState.from_dict(state.to_dict())
    assert restored.records["r0001"].status is RecordStatus.DONE
    assert restored.records["r0002"].attempts == 2
    assert restored.records["r0003"].status is RecordStatus.PENDING
    # um record falho não apaga nem contamina o estado dos outros
    assert restored.records["r0001"].status is not RecordStatus.FAILED
