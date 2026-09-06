"""
Testes de regressão pra auditoria 2026-08-20, Seção 13 do LEIA-ME ("timeout
XLSX"): o Document Engine estava despejando TODAS as linhas de um XLSX
(via _extract_xlsx()) antes de truncar em [:12000] caracteres pra montar o
prompt do LLM. Pra planilha grande isso era lento (constrói uma string
gigante em memória só pra jogar quase tudo fora) e o corte era arbitrário
(sem cabeçalho, sem contagem real de linhas, podia cortar no meio de uma
linha). Combinado com o AbortController em platform_source/server.ts nas
rotas /api/documents/read e /api/documents/edit, planilhas grandes
conseguiam estourar o timeout do Node sem o Phoenix Engine nunca ficar
sabendo que devia ter desistido. (Os valores exatos dos dois timeouts foram
realinhados numa rodada posterior - auditoria 2026-08-21, "corrigir tudo" -
ver DOCUMENT_EXECUTE_TIMEOUT_SECONDS em resident_manager.py; a lógica e o
motivo descritos aqui continuam os mesmos.)

Esta bateria cobre a correção em duas frentes:
1. phoenix_kernel/documents/engine.py::summarize_xlsx_structure() - resumo
   estrutural compacto e determinístico (planilhas, dimensões, cabeçalho,
   amostra, tipos de coluna, contagem real de linhas) via openpyxl
   read_only=True, SEM despejar todas as linhas.
2. phoenix_kernel/resident/resident_manager.py::read_document_direct() -
   roteia arquivos .xlsx pro resumo estrutural (não pro extract_text()
   genérico + corte [:12000]) e aplica um timeout interno
   (DOCUMENT_EXECUTE_TIMEOUT_SECONDS, sempre bem abaixo do AbortController
   do Node) em volta de runtime.execute(), tanto pra leitura quanto pra
   edição - devolvendo um erro claro e controlado em vez de deixar o Node
   abortar a conexão com uma falha de rede genérica.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import asyncio
import sys
import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.domain.execution import ExecutionResult, ExecutionStatus
from phoenix_kernel.documents.engine import summarize_xlsx_structure, _extract_xlsx, DocumentEngineError
from phoenix_kernel.resident.resident_manager import ResidentManager, DOCUMENT_EXECUTE_TIMEOUT_SECONDS
from phoenix_kernel.models.registry import ModelRegistry
from phoenix_kernel.orchestration.execution_arbiter import default_execution_arbiter


def _make_resident_for_document_tests() -> ResidentManager:
    resident = object.__new__(ResidentManager)
    resident.registry = ModelRegistry()
    resident.runtime = AsyncMock()
    resident.logs = AsyncMock()
    resident.logs.add_event = lambda *a, **k: None
    resident.ahde = None
    resident._active_models = {}
    # PHX-FIX (31/08): object.__new__() pula o __init__ real, que é o
    # único lugar que seta self.execution_arbiter - ver comentário
    # completo em test_document_engine_bridge.py.
    resident.execution_arbiter = default_execution_arbiter
    return resident


def _make_workbook(path: Path, rows: int, sheet_name: str = "Planilha1"):
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(["ID", "Nome", "Valor", "Data"])
    for i in range(1, rows + 1):
        ws.append([i, f"Item{i}", i * 1.5, datetime.date(2026, 1, 1)])
    wb.save(str(path))
    return path


# ---------------------------------------------------------------------
# 1. summarize_xlsx_structure() - conteúdo e formato do resumo.
# ---------------------------------------------------------------------

def test_summarize_small_xlsx_reports_header_types_and_sample(tmp_path):
    src = _make_workbook(tmp_path / "pequena.xlsx", rows=5)

    summary = summarize_xlsx_structure(src)

    assert "Planilha1" in summary
    assert "6 linha(s) x 4 coluna(s)" in summary  # cabeçalho + 5 linhas
    assert "Cabeçalho: ID | Nome | Valor | Data" in summary
    assert "Linhas de dados (sem contar cabeçalho): 5" in summary
    assert "número" in summary
    assert "texto" in summary
    assert "data" in summary
    assert "Item1" in summary and "Item5" in summary


def test_summarize_xlsx_respects_sample_row_cap(tmp_path):
    src = _make_workbook(tmp_path / "media.xlsx", rows=50)

    summary = summarize_xlsx_structure(src, max_sample_rows=10)

    assert "Linhas de dados (sem contar cabeçalho): 50" in summary
    assert "Amostra (10 de 50 linha(s))" in summary
    # A amostra é só as primeiras 10 - linhas depois disso não devem
    # aparecer na saída (senão não está limitando de verdade).
    assert "Item11" not in summary
    assert "Item50" not in summary
    assert "Item10" in summary


def test_summarize_xlsx_handles_empty_sheet(tmp_path):
    from openpyxl import Workbook

    src = tmp_path / "vazia.xlsx"
    wb = Workbook()
    wb.active.title = "SemDados"
    wb.save(str(src))

    summary = summarize_xlsx_structure(src)

    assert "SemDados" in summary
    assert "Linhas de dados (sem contar cabeçalho): 0" in summary


def test_summarize_xlsx_caps_number_of_sheets_shown(tmp_path):
    from openpyxl import Workbook

    src = tmp_path / "multi_planilha.xlsx"
    wb = Workbook()
    wb.active.title = "Sheet0"
    for i in range(1, 5):
        wb.create_sheet(f"Sheet{i}")
    wb.save(str(src))

    summary = summarize_xlsx_structure(src, max_sheets=2)

    assert "Total de planilhas: 5 (mostrando as primeiras 2)" in summary
    assert "planilha(s) adicional(is) não mostrada(s)" in summary


def test_summarize_xlsx_stays_compact_for_large_sheet(tmp_path):
    # Regressão específica da Seção 13: o resumo estrutural precisa ficar
    # pequeno (compatível com virar prompt de LLM sem corte arbitrário)
    # mesmo pra uma planilha com muitas linhas - bem diferente de
    # _extract_xlsx(), que cresce proporcional ao número de linhas.
    src = _make_workbook(tmp_path / "grande.xlsx", rows=5000)

    summary = summarize_xlsx_structure(src)
    full_dump = _extract_xlsx(src)

    assert "Linhas de dados (sem contar cabeçalho): 5000" in summary
    assert len(summary) < 3000  # resumo estrutural é compacto...
    assert len(full_dump) > len(summary) * 10  # ...bem menor que o despejo bruto


def test_summarize_xlsx_missing_file_raises_document_engine_error(tmp_path):
    with pytest.raises(DocumentEngineError):
        summarize_xlsx_structure(tmp_path / "nao-existe.xlsx")


# ---------------------------------------------------------------------
# 2. ResidentManager.read_document_direct() roteando .xlsx pro resumo
#    estrutural em vez de extract_text() + corte [:12000].
# ---------------------------------------------------------------------

def test_read_document_direct_routes_xlsx_through_structural_summary(tmp_path):
    resident = _make_resident_for_document_tests()
    doc_path = _make_workbook(tmp_path / "planilha.xlsx", rows=3)

    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.SUCCESS, output="Resumo da planilha.",
    ))

    result = asyncio.run(resident.read_document_direct(str(doc_path), "Resuma a planilha."))

    assert result["ok"] is True
    sent_plan = resident.runtime.execute.call_args[0][0]
    prompt = sent_plan.parameters["user_prompt"]
    # O prompt precisa conter o resumo ESTRUTURAL (cabeçalho, contagem real
    # de linhas), não um despejo bruto de célula por célula sem estrutura.
    assert "Cabeçalho: ID | Nome | Valor | Data" in prompt
    assert "Linhas de dados (sem contar cabeçalho): 3" in prompt


def test_read_document_direct_non_xlsx_still_uses_extract_text_with_cap(tmp_path):
    # Regressão: só .xlsx deve mudar de comportamento - .txt/.docx/etc.
    # continuam pelo caminho antigo (extract_text + corte [:12000]).
    resident = _make_resident_for_document_tests()
    doc_path = tmp_path / "relatorio.txt"
    doc_path.write_text("Conteúdo simples de texto.", encoding="utf-8")

    resident.runtime.execute = AsyncMock(return_value=ExecutionResult(
        plan_id="p1", status=ExecutionStatus.SUCCESS, output="ok",
    ))

    result = asyncio.run(resident.read_document_direct(str(doc_path), ""))

    assert result["ok"] is True
    prompt = resident.runtime.execute.call_args[0][0].parameters["user_prompt"]
    assert "Conteúdo simples de texto." in prompt


# ---------------------------------------------------------------------
# 3. Timeout interno controlado (DOCUMENT_EXECUTE_TIMEOUT_SECONDS) - o
#    Engine precisa desistir e devolver um erro claro, em vez de depender
#    só do AbortController de 5min do lado do Node.
# ---------------------------------------------------------------------

def test_read_document_direct_returns_controlled_error_on_timeout(tmp_path, monkeypatch):
    resident = _make_resident_for_document_tests()
    doc_path = tmp_path / "relatorio.txt"
    doc_path.write_text("Conteúdo.", encoding="utf-8")

    async def _never_finishes(plan):
        await asyncio.sleep(999)

    resident.runtime.execute = _never_finishes
    # Não vamos esperar DOCUMENT_EXECUTE_TIMEOUT_SECONDS de verdade no
    # teste - reduzimos o timeout pra algo bem pequeno via monkeypatch do
    # módulo, mantendo a MESMA lógica de wait_for().
    import phoenix_kernel.resident.resident_manager as rm_module
    monkeypatch.setattr(rm_module, "DOCUMENT_EXECUTE_TIMEOUT_SECONDS", 0.05)

    result = asyncio.run(resident.read_document_direct(str(doc_path), ""))

    assert result["ok"] is False
    assert "demorou mais" in result["error"]


def test_edit_document_direct_returns_controlled_error_on_timeout(tmp_path, monkeypatch):
    resident = _make_resident_for_document_tests()
    doc_path = tmp_path / "relatorio.txt"
    doc_path.write_text("Conteúdo.", encoding="utf-8")

    async def _never_finishes(plan):
        await asyncio.sleep(999)

    resident.runtime.execute = _never_finishes
    import phoenix_kernel.resident.resident_manager as rm_module
    monkeypatch.setattr(rm_module, "DOCUMENT_EXECUTE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.chdir(tmp_path)

    result = asyncio.run(resident.edit_document_direct(str(doc_path), "Reescreva."))

    assert result["ok"] is False
    assert "demorou mais" in result["error"]


def test_document_execute_timeout_is_well_under_node_abort():
    # Trava de sanidade: o timeout interno do Engine SEMPRE precisa ficar
    # abaixo do AbortController de platform_source/server.ts, senão a "rede
    # de segurança" descrita nos comentários deixa de fazer sentido (o Node
    # abortaria primeiro de novo). Lê o valor real do server.ts em vez de
    # hardcodar um número aqui - isto já pegou uma vez uma rodada anterior
    # (auditoria 2026-08-21, "corrigir tudo") que subiu os dois números
    # juntos (240s/300s -> 480s/540s) mas deixou este teste com o 300
    # antigo, quebrando por estar defasado, não por regressão real. Ver
    # tests/test_proxy_backend_timeout_alignment.py para a cobertura
    # completa desse alinhamento em todas as rotas.
    import re
    server_ts = (
        Path(__file__).resolve().parent.parent / "platform_source" / "server.ts"
    ).read_text(encoding="utf-8")
    idx = server_ts.index('app.post("/api/documents/read"')
    m = re.search(r"setTimeout\(\(\)\s*=>\s*\w+\.abort\(\),\s*(\d[\d_]*)\)", server_ts[idx:idx + 2600])
    assert m, "não achei o AbortController de /api/documents/read em server.ts"
    node_abort_seconds = int(m.group(1).replace("_", "")) / 1000

    assert 0 < DOCUMENT_EXECUTE_TIMEOUT_SECONDS < node_abort_seconds
