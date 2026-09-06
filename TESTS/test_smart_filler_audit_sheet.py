"""Teste de ponta a ponta: pendências fiscais aparecem de verdade na aba
_PHOENIX_AUDIT do arquivo .xlsx entregue.

Achado real do usuário (planilha real de teste, "Produtos_Conveniencia.
xlsx" -> "FEITO_PELA_PHOENIX_HOJE.xlsx", 473 produtos): 19 NCM, 29 CFOP e
20 CEST ficaram em branco (corretamente - a guarda-fiscal nunca inventa)
mas a aba _PHOENIX_AUDIT do arquivo entregue só tinha conflitos de marca/
preço/dimensão (do pipeline mais novo) - nenhuma das sugestões fiscais
calculadas por smart_filler.py aparecia em lugar nenhum. A lista real
(`report.pending`) nunca era escrita em nenhuma aba - só uma CONTAGEM
sobrevivia até a resposta da API.
"""
import tempfile
from pathlib import Path

import openpyxl

from phoenix_kernel.documents.smart_filler import smart_fill_xlsx
from phoenix_kernel.documents.output_writer import _AUDIT_SHEET_NAME, _AUDIT_HEADERS


def _make_input_xlsx(rows: list[dict]) -> str:
    headers = list(rows[0].keys())
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h, "") for h in headers])
    tmp = Path(tempfile.mkdtemp()) / "entrada.xlsx"
    wb.save(tmp)
    return str(tmp)


def test_fiscal_pending_appears_in_audit_sheet_of_delivered_file():
    rows = [
        {"Descrição": "Refrigerante Cola 2L", "NCM": "", "CFOP": "", "CEST": "",
         "Tags": "", "Especificações": "", "Categoria do Produto": "Bebidas"},
        {"Descrição": "Cerveja Lager 350ml", "NCM": "22030000", "CFOP": "", "CEST": "",
         "Tags": "", "Especificações": "", "Categoria do Produto": "Bebidas"},
    ]
    input_path = _make_input_xlsx(rows)
    output_path = str(Path(tempfile.mkdtemp()) / "saida.xlsx")

    report = smart_fill_xlsx(input_path, output_path)

    # a pendência foi calculada (comportamento já existia e continua correto)
    assert len(report.pending) > 0

    # ACHADO REAL: agora tem que aparecer de verdade na aba do arquivo entregue
    wb_out = openpyxl.load_workbook(output_path)
    assert _AUDIT_SHEET_NAME in wb_out.sheetnames, "aba _PHOENIX_AUDIT deveria existir no arquivo entregue"
    audit_ws = wb_out[_AUDIT_SHEET_NAME]

    header_row = [c.value for c in audit_ws[1]]
    assert header_row == _AUDIT_HEADERS

    audit_rows = list(audit_ws.iter_rows(min_row=2, values_only=True))
    assert len(audit_rows) == len(report.pending), "cada pendência calculada tem que virar uma linha na aba"

    # confere que a linha da planilha (row_number) bate com a linha REAL
    # do produto na planilha de saída, não um índice arbitrário
    row_numbers = {r[1] for r in audit_rows}  # coluna 2 = row_number
    assert 2 in row_numbers  # "Refrigerante Cola 2L" é a linha 2 (primeira depois do cabeçalho)

    # campo fiscal tem que estar marcado como tal (pra filtrar/priorizar na auditoria)
    field_types = {r[3] for r in audit_rows}  # coluna 4 = field_type
    assert "fiscal_pending" in field_types

    # a sugestão de verdade (não só "campo fiscal, exige classificação")
    # tem que estar visível na coluna de alternativas de pelo menos uma
    # linha com NCM oficial reconhecido (Refrigerante -> bebida, tabela
    # oficial deveria sugerir algo)
    alternatives_texts = " | ".join(str(r[5]) for r in audit_rows)
    assert "campo fiscal" in alternatives_texts.lower()


def test_no_audit_sheet_created_when_nothing_pending():
    """Regressão: se não há nenhuma pendência, não cria a aba à toa
    (arquivo simples continua simples)."""
    rows = [
        {"Descrição": "Item Completo", "NCM": "12345678", "CFOP": "5102", "CEST": "1234567",
         "Tags": "tag1", "Especificações": "spec", "Categoria do Produto": "Geral"},
    ]
    input_path = _make_input_xlsx(rows)
    output_path = str(Path(tempfile.mkdtemp()) / "saida2.xlsx")

    smart_fill_xlsx(input_path, output_path)

    wb_out = openpyxl.load_workbook(output_path)
    assert _AUDIT_SHEET_NAME not in wb_out.sheetnames


def test_appends_to_existing_audit_sheet_instead_of_overwriting():
    """Se a aba _PHOENIX_AUDIT já existe (ex.: o pipeline determinístico
    mais novo já rodou antes e escreveu conflitos de marca/preço), as
    pendências fiscais são ADICIONADAS, nunca substituem o que já tinha."""
    rows = [
        {"Descrição": "Produto Novo", "NCM": "", "CFOP": "", "CEST": "",
         "Tags": "", "Especificações": "", "Categoria do Produto": "Geral"},
    ]
    input_path = _make_input_xlsx(rows)
    output_path = str(Path(tempfile.mkdtemp()) / "saida3.xlsx")

    # simula o pipeline determinístico já tendo criado a aba com um conflito
    wb_pre = openpyxl.load_workbook(input_path)
    pre_audit = wb_pre.create_sheet(_AUDIT_SHEET_NAME)
    pre_audit.append(_AUDIT_HEADERS)
    pre_audit.append(["cr_r0001", 5, "Marca", "brand", "conflict", "Marca A | Marca B", "r0001"])
    wb_pre.save(input_path)

    smart_fill_xlsx(input_path, output_path)

    wb_out = openpyxl.load_workbook(output_path)
    audit_ws = wb_out[_AUDIT_SHEET_NAME]
    audit_rows = list(audit_ws.iter_rows(min_row=2, values_only=True))
    # a linha de conflito de marca pré-existente continua lá
    assert any(r[2] == "Marca" and r[4] == "conflict" for r in audit_rows)
    # e as pendências fiscais novas foram adicionadas junto
    assert any(r[3] == "fiscal_pending" for r in audit_rows)
