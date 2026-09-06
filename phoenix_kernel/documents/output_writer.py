"""Phoenix Document Pipeline V2 - Fase 10: XLSX Output Writer.

PHX-NEW (2026-08-29, especificação fechada pelo usuário depois de 9 fases
de trabalho pra construir `CanonicalRecord`/`FieldEvidence` sem nunca
achatar informação estruturada em texto): este módulo é o ÚLTIMO passo do
pipeline - pega o que a Fase 9 (Identity/Merge/Dedup, ver
`identity_engine.py`) produziu e escreve num arquivo `.xlsx` real.

Princípio central, nas palavras do usuário: "O Writer não interpreta
nada." Ele recebe `CanonicalRecord[]` + um mapeamento coluna->field_type
(`ColumnMapping`, ver `normalized.py`) e só faz: mapear / validar /
escrever / preservar formato / registrar provenance. Nunca deduplica
(isso é Fase 9), nunca chama LLM (isso é Fase 8), nunca "adivinha" um
valor pra um campo em conflito.

Regra de decisão por campo, EXATAMENTE como o usuário especificou:
    - `FieldEvidence.status` em {"confirmed", "probable"} -> escreve
      `FieldEvidence.value` na célula de negócio.
    - `FieldEvidence.status` em {"ambiguous", "conflict", "invalid"}, OU
      o campo simplesmente NÃO aparece em `CanonicalRecord.fields` mas a
      coluna é `required=True` -> célula de negócio fica VAZIA, e uma
      linha estruturada é escrita na aba de auditoria `_PHOENIX_AUDIT`
      (nunca um marcador de texto tipo "#CONFLITO" dentro da célula de
      negócio - risco documentado pelo usuário de quebrar import de ERP
      ou ser lido como dado legítimo).
    - Nenhuma coluna sem candidato algum e `required=False` gera
      auditoria - célula fica vazia silenciosamente, mesmo comportamento
      de "esse produto não tinha essa informação".

Dois caminhos, o usuário foi explícito sobre qual é o principal:
    - `write_to_template` (PRINCIPAL): abre um `.xlsx` REAL existente com
      `openpyxl.load_workbook(..., data_only=False)` (modo normal, NUNCA
      `write_only` - `write_only` reconstrói o arquivo do zero e perderia
      estilos/larguras/fórmulas de colunas não mapeadas, exatamente o que
      o usuário pediu pra preservar), localiza a linha de cabeçalho
      (`header_row`, 1-based, configurado explicitamente por quem chama -
      este módulo NUNCA adivinha onde o cabeçalho está), resolve cada
      `ColumnMapping.header` contra os headers REAIS daquela linha (por
      igualdade exata de texto, após strip - o template real é a
      autoridade sobre nome/ordem/quantidade de colunas, o código nunca
      inventa isso), escreve as linhas de dados numa aba nova ou existente
      pedida, escreve a aba `_PHOENIX_AUDIT`, e salva em `output_path`
      OBRIGATORIAMENTE diferente de `template_path` (uma tentativa de
      escrever em cima do template é recusada com `ValueError` antes de
      qualquer escrita - "o ponto crítico: não sobrescrever o template
      original").
    - `write_blank_workbook` (SECUNDÁRIO/fallback): gera um workbook novo
      do zero a partir só de uma lista de `ColumnMapping`s, sem template
      nenhum - "barato e útil para testes" (palavras do usuário), nunca o
      caminho recomendado pra uso real com o MarketUP.

Limitação conhecida e documentada (não escondida): a resolução de coluna
é por IGUALDADE EXATA de texto de header (com strip). Se o cabeçalho real
tiver variações (espaços duplos, acentuação diferente, etc.) a coluna
correspondente simplesmente não é encontrada e vira um erro explícito
(`ValueError` listando headers disponíveis) em vez de um "quase igual"
arriscado - o usuário ainda não forneceu o arquivo `.xlsx` real do
MarketUP pra calibrar isso; quando fornecido, a lista de `ColumnMapping`
correta deve ser montada a partir dos headers exatos daquele arquivo,
nunca hardcoded neste módulo (pedido explícito: "não invente esses
valores no código").

Nenhum arquivo protegido foi tocado pra criar este módulo - novo,
isolado, dentro de `documents/`, sem nenhuma relação de código com a
OUTRA feature de preenchimento de planilha (`api_server.py`/
`phoenix_kernel/documents/engine.py`/`resident_manager.py`/
`platform_source/...`), mesmo que o assunto (preencher planilha) se
pareça - são dois pipelines completamente diferentes e este módulo não
importa nada daqueles arquivos.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import openpyxl
from openpyxl.workbook.workbook import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from phoenix_kernel.documents.evidence_engine import EvidenceStatus, FieldEvidence
from phoenix_kernel.documents.identity_engine import CanonicalRecord
from phoenix_kernel.documents.normalized import ColumnMapping

_AUDIT_SHEET_NAME = "_PHOENIX_AUDIT"
_AUDIT_HEADERS = [
    "canonical_id",
    "row_number",
    "column_header",
    "field_type",
    "status",
    "alternatives",
    "source_record_ids",
]

# PHX-NEW: status de FieldEvidence que autorizam escrever o valor na
# célula de negócio - exatamente "confirmed"/"probable", pedido explícito
# do usuário ("Campo confirmed/probable aceitável ... -> escreve").
_WRITABLE_STATUSES = {EvidenceStatus.CONFIRMED.value, EvidenceStatus.PROBABLE.value}

# Únicas políticas de conflito que o vocabulário do JobStrategy admite
# hoje (ver PHX-NEW em normalized.py/JobStrategy.conflict_policy) - só
# "blank" tem comportamento implementado nesta Fase 10.
_SUPPORTED_CONFLICT_POLICIES = {"blank"}


@dataclass
class AuditRow:
    """Uma linha da aba `_PHOENIX_AUDIT` - um problema, um campo, uma
    linha (nunca um record inteiro achatado numa string só, ver rejeição
    explícita do usuário ao formato `_conflitos: "price: 19.9 | 21.9"`)."""

    canonical_id: str
    row_number: int
    column_header: str
    field_type: str
    status: str
    alternatives: str
    source_record_ids: str

    def as_row(self) -> list:
        return [
            self.canonical_id,
            self.row_number,
            self.column_header,
            self.field_type,
            self.status,
            self.alternatives,
            self.source_record_ids,
        ]


@dataclass
class WriteResult:
    """Resumo do que `write_to_template`/`write_blank_workbook` fizeram -
    pra quem chama (e pros testes) verificarem sem reabrir o arquivo."""

    output_path: str
    rows_written: int
    audit_rows: list[AuditRow] = field(default_factory=list)


def _format_alternatives(evidence: Optional[FieldEvidence]) -> str:
    """Formata os valores concorrentes de um campo em "conflict" pra
    auditoria - só texto legível pra humano nesta coluna (a estrutura de
    verdade já está preservada em `CanonicalRecord.fields`, nunca
    descartada; isto aqui é só uma leitura rápida da aba de auditoria)."""
    if evidence is None or not evidence.values:
        return ""
    return " | ".join(str(v.value) for v in evidence.values)


def _resolve_header_indices(
    worksheet: Worksheet, header_row: int, columns: list[ColumnMapping]
) -> dict[str, int]:
    """Resolve cada `ColumnMapping.header` pra um índice de coluna
    (1-based) na linha de cabeçalho real do template - por igualdade
    exata (com strip), nunca aproximação (ver limitação documentada no
    topo do módulo). Levanta `ValueError` explícito e imediato (nunca
    silenciosamente ignora uma coluna não encontrada) se algum header
    pedido não existir na planilha real."""
    real_headers: dict[str, int] = {}
    for cell in worksheet[header_row]:
        if cell.value is not None:
            real_headers[str(cell.value).strip()] = cell.column

    indices: dict[str, int] = {}
    missing: list[str] = []
    for column in columns:
        key = column.header.strip()
        if key in real_headers:
            indices[column.header] = real_headers[key]
        else:
            missing.append(column.header)

    if missing:
        raise ValueError(
            f"Header(s) não encontrado(s) na linha {header_row} do template: {missing}. "
            f"Headers disponíveis: {sorted(real_headers.keys())}"
        )
    return indices


def _write_audit_sheet(workbook: Workbook, audit_rows: list[AuditRow]) -> None:
    if _AUDIT_SHEET_NAME in workbook.sheetnames:
        del workbook[_AUDIT_SHEET_NAME]
    audit_sheet = workbook.create_sheet(_AUDIT_SHEET_NAME)
    audit_sheet.append(_AUDIT_HEADERS)
    for row in audit_rows:
        audit_sheet.append(row.as_row())


def _fill_rows(
    worksheet: Worksheet,
    header_indices: dict[str, int],
    first_data_row: int,
    records: list[CanonicalRecord],
    columns: list[ColumnMapping],
    conflict_policy: str,
) -> list[AuditRow]:
    if conflict_policy not in _SUPPORTED_CONFLICT_POLICIES:
        # PHX-NEW: o vocabulário já existe em JobStrategy.conflict_policy
        # pra uma fase futura, mas fingir suportar "skip_row"/"error" sem
        # implementar de verdade seria pior que recusar explicitamente.
        raise NotImplementedError(
            f"conflict_policy={conflict_policy!r} ainda não implementado nesta Fase 10 "
            f"(suportado agora: {sorted(_SUPPORTED_CONFLICT_POLICIES)})"
        )

    audit_rows: list[AuditRow] = []
    for offset, record in enumerate(records):
        row_number = first_data_row + offset
        for column in columns:
            col_index = header_indices[column.header]
            evidence = record.fields.get(column.field_type)

            if evidence is None:
                if column.required:
                    audit_rows.append(AuditRow(
                        canonical_id=record.canonical_id,
                        row_number=row_number,
                        column_header=column.header,
                        field_type=column.field_type,
                        status="missing_required",
                        alternatives="",
                        source_record_ids=",".join(record.source_record_ids),
                    ))
                # coluna opcional sem candidato algum -> vazia, sem
                # auditoria (produto simplesmente não tinha essa
                # informação, isso não é um "problema").
                continue

            if evidence.status in _WRITABLE_STATUSES:
                worksheet.cell(row=row_number, column=col_index, value=evidence.value)
                continue

            # ambiguous / conflict / invalid -> nunca escolhe sozinho,
            # célula fica vazia, vira auditoria.
            audit_rows.append(AuditRow(
                canonical_id=record.canonical_id,
                row_number=row_number,
                column_header=column.header,
                field_type=column.field_type,
                status=evidence.status,
                alternatives=_format_alternatives(evidence),
                source_record_ids=",".join(record.source_record_ids),
            ))

    return audit_rows


def write_to_template(
    template_path: str,
    output_path: str,
    records: list[CanonicalRecord],
    columns: list[ColumnMapping],
    header_row: int,
    sheet_name: Optional[str] = None,
    first_data_row: Optional[int] = None,
    conflict_policy: str = "blank",
) -> WriteResult:
    """Caminho PRINCIPAL da Fase 10 (ver docstring do módulo). Abre
    `template_path` (nunca modificado - só lido), preenche as linhas de
    dados a partir de `header_row + 1` (ou `first_data_row`, se um
    template já tiver linhas de exemplo/legenda antes dos dados reais) e
    salva o resultado em `output_path`. `sheet_name=None` usa a aba ATIVA
    do template (`workbook.active`) - o template real é a autoridade,
    este módulo nunca cria uma aba de negócio nova do zero."""
    if template_path == output_path:
        raise ValueError(
            "output_path não pode ser igual a template_path - a Fase 10 nunca "
            "sobrescreve o template original (pedido explícito do usuário)."
        )

    workbook = openpyxl.load_workbook(template_path)
    worksheet = workbook[sheet_name] if sheet_name is not None else workbook.active

    header_indices = _resolve_header_indices(worksheet, header_row, columns)
    data_start = first_data_row if first_data_row is not None else header_row + 1

    audit_rows = _fill_rows(
        worksheet=worksheet,
        header_indices=header_indices,
        first_data_row=data_start,
        records=records,
        columns=columns,
        conflict_policy=conflict_policy,
    )

    _write_audit_sheet(workbook, audit_rows)
    workbook.save(output_path)

    return WriteResult(output_path=output_path, rows_written=len(records), audit_rows=audit_rows)


def write_blank_workbook(
    output_path: str,
    records: list[CanonicalRecord],
    columns: list[ColumnMapping],
    sheet_name: str = "Sheet1",
    conflict_policy: str = "blank",
) -> WriteResult:
    """Caminho SECUNDÁRIO/fallback (ver docstring do módulo) - gera um
    `.xlsx` novo do zero, sem nenhum template real envolvido. Útil pra
    teste rápido/smoke, NÃO o caminho recomendado pra uso real com o
    MarketUP (o usuário foi explícito: "Opção 2 = principal, Opção 1 =
    fallback/teste")."""
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet_name

    header_row = 1
    for col_index, column in enumerate(columns, start=1):
        worksheet.cell(row=header_row, column=col_index, value=column.header)

    header_indices = {column.header: idx for idx, column in enumerate(columns, start=1)}

    audit_rows = _fill_rows(
        worksheet=worksheet,
        header_indices=header_indices,
        first_data_row=header_row + 1,
        records=records,
        columns=columns,
        conflict_policy=conflict_policy,
    )

    _write_audit_sheet(workbook, audit_rows)
    workbook.save(output_path)

    return WriteResult(output_path=output_path, rows_written=len(records), audit_rows=audit_rows)
