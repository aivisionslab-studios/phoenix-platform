# TESTS/test_fill_xlsx_template_engine.py
#
# PHX-NEW (pedido do usuário 2026-08-28: "aceitar dois arquivos - um fonte,
# um template alvo - e editar o segundo em vez de gerar do zero").
#
# Testa phoenix_kernel.documents.engine.read_xlsx_template_structure() e
# fill_xlsx_template() com arquivos .xlsx REAIS (openpyxl), sem mocks -
# são funções puramente de I/O de arquivo, então vale testar contra o
# comportamento real da biblioteca em vez de mockar openpyxl.
#
# Cobre especificamente a promessa central do recurso: preservar o que já
# existe no template (outras planilhas, fórmulas) em vez de recriar o
# arquivo do zero como rebuild_document()/_rebuild_xlsx() já fazem.

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

openpyxl = pytest.importorskip("openpyxl")

from phoenix_kernel.documents.engine import (  # noqa: E402
    DocumentEngineError,
    fill_xlsx_template,
    read_xlsx_template_structure,
)


def _make_template(path: Path, headers: list[str], rows: list[list] | None = None, sheet_name: str = "Dados") -> None:
    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = sheet_name
    for col_idx, h in enumerate(headers, start=1):
        sheet.cell(row=1, column=col_idx, value=h)
    for r_idx, row in enumerate(rows or [], start=2):
        for c_idx, val in enumerate(row, start=1):
            sheet.cell(row=r_idx, column=c_idx, value=val)
    wb.save(str(path))


# ---------------------------------------------------------------------
# read_xlsx_template_structure
# ---------------------------------------------------------------------

def test_read_structure_finds_header_and_last_row(tmp_path):
    path = tmp_path / "template.xlsx"
    _make_template(path, ["Nome", "CPF", "Valor"], rows=[["Ana", "111", 10], ["Beto", "222", 20]])

    structure = read_xlsx_template_structure(path)

    assert len(structure["sheets"]) == 1
    sheet_info = structure["sheets"][0]
    assert sheet_info["name"] == "Dados"
    assert sheet_info["headers"] == ["Nome", "CPF", "Valor"]
    assert sheet_info["last_row"] == 3  # cabeçalho (1) + 2 linhas de dado


def test_read_structure_empty_sheet_reports_no_headers(tmp_path):
    path = tmp_path / "vazio.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Planilha1"
    wb.save(str(path))

    structure = read_xlsx_template_structure(path)

    assert structure["sheets"][0]["headers"] == []
    assert structure["sheets"][0]["last_row"] == 0


def test_read_structure_multiple_sheets(tmp_path):
    path = tmp_path / "multi.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Clientes"
    wb.active.append(["Nome", "Email"])
    wb.create_sheet("Resumo").append(["Total", 0])
    wb.save(str(path))

    structure = read_xlsx_template_structure(path)
    names = [s["name"] for s in structure["sheets"]]
    assert names == ["Clientes", "Resumo"]


# ---------------------------------------------------------------------
# fill_xlsx_template - preservação do que já existe
# ---------------------------------------------------------------------

def test_fill_appends_rows_after_existing_data(tmp_path):
    template = tmp_path / "template.xlsx"
    _make_template(template, ["Nome", "CPF", "Valor"], rows=[["Ana", "111", 10]])
    out = tmp_path / "preenchido.xlsx"

    report = fill_xlsx_template(
        template, {"Dados": [{"Nome": "Beto", "CPF": "222", "Valor": 20}]}, out,
    )

    assert report["rows_written"] == 1
    assert report["sheets_used"] == ["Dados"]
    assert report["auto_created_columns"] == {}

    wb = openpyxl.load_workbook(str(out))
    sheet = wb["Dados"]
    assert [c.value for c in sheet[1]] == ["Nome", "CPF", "Valor"]
    assert [c.value for c in sheet[2]] == ["Ana", "111", 10]
    assert [c.value for c in sheet[3]] == ["Beto", "222", 20]
    # Não escreveu numa quarta linha à toa nem sobrescreveu a existente.
    assert sheet.max_row == 3


def test_fill_preserves_untouched_sheet_and_formula(tmp_path):
    """A promessa central do recurso: outra planilha e uma fórmula não
    tocadas continuam intactas depois do preenchimento - ao contrário de
    rebuild_document(), que sempre recria o arquivo do zero."""
    template = tmp_path / "template.xlsx"
    wb = openpyxl.Workbook()
    dados = wb.active
    dados.title = "Dados"
    dados.append(["Nome", "Valor"])
    dados.append(["Ana", 10])
    resumo = wb.create_sheet("Resumo")
    resumo["A1"] = "Total"
    resumo["B1"] = "=SUM(Dados!B:B)"
    wb.save(str(template))
    out = tmp_path / "preenchido.xlsx"

    fill_xlsx_template(template, {"Dados": [{"Nome": "Beto", "Valor": 20}]}, out)

    wb2 = openpyxl.load_workbook(str(out))
    assert "Resumo" in wb2.sheetnames
    assert wb2["Resumo"]["A1"].value == "Total"
    assert wb2["Resumo"]["B1"].value == "=SUM(Dados!B:B)"  # fórmula preservada, não virou valor


def test_fill_matches_headers_case_insensitively(tmp_path):
    template = tmp_path / "template.xlsx"
    _make_template(template, ["Nome", "CPF"])
    out = tmp_path / "preenchido.xlsx"

    fill_xlsx_template(template, {"Dados": [{"nome": "Ana", "cpf": "111"}]}, out)

    wb = openpyxl.load_workbook(str(out))
    sheet = wb["Dados"]
    assert [c.value for c in sheet[2]] == ["Ana", "111"]


def test_fill_auto_creates_column_for_unmatched_key(tmp_path):
    template = tmp_path / "template.xlsx"
    _make_template(template, ["Nome"])
    out = tmp_path / "preenchido.xlsx"

    report = fill_xlsx_template(
        template, {"Dados": [{"Nome": "Ana", "Observação": "cliente novo"}]}, out,
    )

    assert report["auto_created_columns"] == {"Dados": ["Observação"]}
    wb = openpyxl.load_workbook(str(out))
    sheet = wb["Dados"]
    assert [c.value for c in sheet[1]] == ["Nome", "Observação"]
    assert [c.value for c in sheet[2]] == ["Ana", "cliente novo"]


def test_fill_creates_header_from_scratch_on_blank_template(tmp_path):
    template = tmp_path / "vazio.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Planilha1"
    wb.save(str(template))
    out = tmp_path / "preenchido.xlsx"

    report = fill_xlsx_template(
        template, {"Planilha1": [{"Nome": "Ana", "Idade": 30}]}, out,
    )

    assert report["rows_written"] == 1
    wb2 = openpyxl.load_workbook(str(out))
    sheet = wb2["Planilha1"]
    assert [c.value for c in sheet[1]] == ["Nome", "Idade"]
    assert [c.value for c in sheet[2]] == ["Ana", 30]


def test_fill_single_sheet_template_ignores_mismatched_sheet_name(tmp_path):
    """LLM pode não reproduzir o nome exato da planilha - com só UMA
    planilha no template, usa ela mesmo assim em vez de falhar."""
    template = tmp_path / "template.xlsx"
    _make_template(template, ["Nome"], sheet_name="Clientes2026")
    out = tmp_path / "preenchido.xlsx"

    report = fill_xlsx_template(template, {"Sheet1": [{"Nome": "Ana"}]}, out)

    assert report["sheets_used"] == ["Clientes2026"]
    assert report["sheets_not_found"] == []


def test_fill_multi_sheet_template_reports_unmatched_sheet_name(tmp_path):
    template = tmp_path / "template.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "Clientes"
    wb.create_sheet("Fornecedores")
    wb.save(str(template))
    out = tmp_path / "preenchido.xlsx"

    report = fill_xlsx_template(template, {"NaoExiste": [{"Nome": "Ana"}]}, out)

    assert report["sheets_not_found"] == ["NaoExiste"]
    assert report["rows_written"] == 0


def test_fill_never_overwrites_the_template_file(tmp_path):
    template = tmp_path / "template.xlsx"
    _make_template(template, ["Nome"])
    original_bytes = template.read_bytes()
    out = tmp_path / "preenchido.xlsx"

    fill_xlsx_template(template, {"Dados": [{"Nome": "Ana"}]}, out)

    assert template.read_bytes() == original_bytes
    assert out.exists()


def test_fill_rejects_non_xlsx_template(tmp_path):
    fake_docx = tmp_path / "template.docx"
    fake_docx.write_bytes(b"not really a docx")
    out = tmp_path / "preenchido.xlsx"

    with pytest.raises(DocumentEngineError):
        fill_xlsx_template(fake_docx, {"Dados": [{"Nome": "Ana"}]}, out)
