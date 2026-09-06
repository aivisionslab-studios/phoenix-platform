"""Orquestrador do Document Pipeline V2 — liga as peças que já existem.

O Pipeline V2 (Fases 1-10) está inteiro no projeto, com 200 testes passando,
MAS desligado: nenhuma rota/resident o chama em produção. Cada peça é pública
e testada isoladamente; faltava o encadeamento ponta a ponta. Este módulo é
esse encadeamento — nada de lógica de extração nova, só orquestração das
funções existentes na ordem correta:

    parse_docx_to_normalized_document / normalized-from-text
        -> find_candidates_in_document        (candidate_engine)
        -> segment_records                    (record_segmenter)
        -> resolve_identity                   (identity_engine)
        -> build_evidence_for_document        (evidence_engine)
        -> write_to_template                  (output_writer, Fase 10)

É determinístico (regex/parsers/normalizadores), não usa LLM para colar dado
na célula — exatamente o "Python lendo e colando corretamente" pedido. O LLM
só entraria depois, opcionalmente, para os campos que o pipeline marca como
`ambiguous`/`conflict` (resolução semântica), fora do escopo deste fio.

O mapeamento coluna-do-template -> field_type interno é resolvido pelo
`_HEADER_FIELD_MAP` que o candidate_engine já mantém (Código de Barras->ean,
NCM->ncm, Preço De->compare_at_price, Peso->weight, Tags->tags, ...), então o
usuário NÃO precisa mapear coluna a coluna à mão.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import re
import uuid

import openpyxl

from phoenix_kernel.documents.business_sanity import check_price_coherence
from phoenix_kernel.documents.candidate_engine import (
    _HEADER_FIELD_MAP, find_candidates_in_document,
)
from phoenix_kernel.documents.evidence_engine import (
    EvidenceStatus, ValueGroup, build_evidence_for_document,
)
from phoenix_kernel.documents.identity_engine import resolve_identity
from phoenix_kernel.documents.normalized import (
    Block, BlockType, ColumnMapping, DocumentMetadata, NormalizedDocument,
)
from phoenix_kernel.documents.output_writer import write_to_template
from phoenix_kernel.documents.record_segmenter import segment_records

_WRITABLE_STATUSES = {EvidenceStatus.CONFIRMED.value, EvidenceStatus.PROBABLE.value}


def _apply_business_sanity_guard(canonical_records: list) -> int:
    """PHX-NEW (2026-09, Camada C — guarda de sanidade de negócio): roda
    ANTES da escrita, sobre os valores já extraídos e prontos pra ir na
    célula. Nasceu do bug real que motivou toda essa camada: "Preço Mínimo"
    mapeado para custo faria a planilha dizer que um produto CUSTA o menor
    preço de VENDA — margem de lucro toda errada.

    Não decide qual valor é o certo (isso exigiria adivinhar dado financeiro,
    o oposto do que este projeto faz) — só REBAIXA os campos envolvidos pra
    fora do conjunto gravável quando a combinação é logicamente impossível
    (custo > venda, "de" menor que "por"). O mecanismo de auditoria já
    existente (`_WRITABLE_STATUSES`/`AuditRow` no output_writer) cuida do
    resto sozinho: um campo sem status confirmed/probable vai pra
    `_PHOENIX_AUDIT` automaticamente, com o motivo. Devolve quantos campos
    foram rebaixados."""
    downgraded = 0
    for cr in canonical_records:
        values = {
            ft: fe.value for ft, fe in cr.fields.items()
            if fe.status in _WRITABLE_STATUSES and fe.value is not None
        }
        violations = check_price_coherence(values)
        if not violations:
            continue
        for v in violations:
            for ft in v.field_types:
                fe = cr.fields.get(ft)
                if fe is None or fe.status not in _WRITABLE_STATUSES:
                    continue
                fe.status = "business_sanity_violation"
                fe.values = [ValueGroup(value=f"{fe.value} — {v.detail}", evidence_count=1)]
                downgraded += 1
    return downgraded


def normalized_document_from_text(text: str, source_name: str = "", source_type: str = "txt") -> NormalizedDocument:
    """Constrói um NormalizedDocument a partir de TEXTO puro, para formatos
    que não têm parser estrutural dedicado (PDF/TXT/MD/PPTX já extraídos pela
    Document Engine). Cada parágrafo (bloco separado por linha em branco) vira
    um Block; linhas que parecem título (curtas, sem terminação de frase)
    viram heading — o record_segmenter usa isso para separar registros.

    Para .docx, prefira parse_docx_to_normalized_document (preserva tabelas e
    estrutura de verdade); este helper é o caminho genérico para o resto."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    blocks: list[Block] = []
    for order, para in enumerate(paras):
        collapsed = re.sub(r"\s*\n\s*", " ", para).strip()
        # heurística de título: linha curta, sem pontuação final de frase,
        # frequentemente com "--"/"—" (padrão dos catálogos)
        is_title = (
            len(collapsed) <= 120
            and not collapsed.endswith((".", "!", "?"))
            and ("--" in collapsed or "—" in collapsed or collapsed.isupper() or len(collapsed.split()) <= 12)
        )
        blocks.append(Block(
            id=f"b{order:05d}",
            type=BlockType.HEADING if is_title else BlockType.PARAGRAPH,
            order=order,
            text_raw=collapsed,
            text_normalized=collapsed,
            level=1 if is_title else None,
        ))
    return NormalizedDocument(
        document_id=uuid.uuid4().hex,
        source_name=source_name or "documento",
        source_type=source_type,
        metadata=DocumentMetadata(),
        blocks=blocks,
    )


@dataclass
class PipelineResult:
    output_path: str
    rows_written: int = 0
    records_total: int = 0
    audit_rows: int = 0
    columns_mapped: list[str] = field(default_factory=list)
    columns_unmapped: list[str] = field(default_factory=list)
    header_row: int = 1
    sheet_name: str = ""


def resolve_columns_from_template(
    template_path: str,
    sheet_name: Optional[str] = None,
) -> tuple[list[ColumnMapping], int, str, list[str], list[str]]:
    """Lê os cabeçalhos REAIS do template e resolve cada um para um
    field_type interno usando o `_HEADER_FIELD_MAP` já existente. Uma coluna
    cujo cabeçalho não casa com nenhum padrão conhecido é devolvida como
    não-mapeada (o writer simplesmente não escreve nela — nunca inventa
    correspondência aproximada, requisito explícito da Fase 10).

    Devolve (columns, header_row, sheet_name, mapeadas, nao_mapeadas)."""
    wb = openpyxl.load_workbook(template_path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name] if sheet_name else wb[wb.sheetnames[0]]
        used_sheet = ws.title
        header_row = 0
        headers: list[str] = []
        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            if any(c is not None for c in row):
                headers = ["" if c is None else str(c).strip() for c in row]
                header_row = row_idx
                break
    finally:
        wb.close()

    columns: list[ColumnMapping] = []
    mapped: list[str] = []
    unmapped: list[str] = []
    for header in headers:
        if not header:
            continue
        field_type = None
        for header_pattern, ftype, _norm in _HEADER_FIELD_MAP:
            if header_pattern.search(header):
                field_type = ftype
                break
        if field_type:
            columns.append(ColumnMapping(header=header, field_type=field_type, required=False))
            mapped.append(f"{header} -> {field_type}")
        else:
            unmapped.append(header)

    return columns, (header_row or 1), used_sheet, mapped, unmapped


def run_pipeline_docx_to_xlsx(
    *,
    document: NormalizedDocument,
    template_path: str,
    output_path: str,
    sheet_name: Optional[str] = None,
    first_data_row: Optional[int] = None,
) -> PipelineResult:
    """Encadeia o Pipeline V2 inteiro sobre um NormalizedDocument já pronto e
    escreve no template preservando estrutura. Determinístico: mesma entrada
    produz mesma saída.

    `first_data_row`: linha onde começar a escrever. Se None, o writer
    continua após a última linha ocupada — não sobrescreve dados existentes.
    """
    # 1) candidatos (regex/parsers) a partir dos blocos do documento
    candidates = find_candidates_in_document(document)
    # 2) segmenta em registros (um produto/pessoa por Record)
    records = segment_records(document, candidates)
    # 3) resolve identidade/dedupe -> CanonicalRecord por record
    candidates_by_id = {c.id: c for c in candidates if c.id}
    blocks_by_id = {b.id: b for b in document.blocks}
    identity = resolve_identity(records, candidates_by_id, blocks_by_id)
    # 4) evidência por campo (confirmed/probable/conflict/...) — o writer usa
    #    isso para decidir o que escrever vs. mandar pra auditoria
    #    (build_evidence_for_document é chamada dentro do fluxo do writer via
    #    os CanonicalRecord; aqui só garantimos que roda sem erro sobre o doc)
    _ = build_evidence_for_document(document, candidates, records)

    # 4b) guarda de sanidade de negócio (Camada C) — roda sobre os valores já
    # extraídos, ANTES de decidir o que é gravável. Rebaixa campos com
    # combinação logicamente impossível (custo > venda) pra fora da escrita;
    # eles caem automaticamente na aba _PHOENIX_AUDIT via o mecanismo que já
    # existe no output_writer, sem precisar tocar nele.
    _apply_business_sanity_guard(identity.canonical_records)

    # 5) resolve as colunas do template automaticamente
    columns, header_row, used_sheet, mapped, unmapped = resolve_columns_from_template(
        template_path, sheet_name
    )
    if not columns:
        raise ValueError(
            "Nenhuma coluna do template pôde ser mapeada para um campo conhecido "
            "(Código de Barras, NCM, CEST, Preço, Peso, Tags, ...). Verifique se o "
            "template é o correto."
        )

    # PHX-FIX (2026-09-03, achado real: planilha "vazia" com 1079 linhas em
    # branco): o pipeline cria um CanonicalRecord para CADA trecho segmentado,
    # inclusive pedaços de meta-conversa sem produto real (o segmenter isola
    # esses como registros de baixa confiança em vez de contaminar os produtos
    # vizinhos — correto). Mas escrever TODOS gera centenas de linhas vazias no
    # meio dos produtos de verdade, fazendo a planilha parecer vazia. Aqui
    # filtramos: só entra no XLSX o registro que tem NOME de produto OU pelo
    # menos um campo mapeado com valor real. Registro sem nada não vira linha.
    mapped_field_types = {c.field_type for c in columns}

    def _has_real_content(cr) -> bool:
        for ft, fe in cr.fields.items():
            if ft not in mapped_field_types:
                continue
            val = getattr(fe, "value", None)
            if val is not None and str(val).strip():
                return True
        return False

    records_to_write = [cr for cr in identity.canonical_records if _has_real_content(cr)]

    # 6) escreve no template (Fase 10) — preserva fórmulas/formatação/abas,
    #    nunca sobrescreve o original, gera aba _PHOENIX_AUDIT
    result = write_to_template(
        template_path=template_path,
        output_path=output_path,
        records=records_to_write,
        columns=columns,
        header_row=header_row,
        sheet_name=used_sheet,
        first_data_row=first_data_row,
        conflict_policy="blank",
    )

    return PipelineResult(
        output_path=output_path,
        rows_written=getattr(result, "rows_written", 0),
        records_total=len(records_to_write),
        audit_rows=getattr(result, "audit_rows_written", getattr(result, "audit_rows", 0)),
        columns_mapped=mapped,
        columns_unmapped=unmapped,
        header_row=header_row,
        sheet_name=used_sheet,
    )
