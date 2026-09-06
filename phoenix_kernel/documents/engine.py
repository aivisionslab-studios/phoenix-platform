"""
phoenix_kernel/documents/engine.py

Extração e reconstrução de documentos (PDF, DOCX, XLSX, PPTX, TXT/MD) para
a Document Engine da Phoenix.

Mantém o mesmo princípio dos outros drivers (vision, piper, sd_cpp): o
ResidentManager não sabe NADA sobre bibliotecas de documento - só chama
extract_text()/rebuild_document() e manda o texto pro LLM via
runtime.execute(), exatamente como já faz com imagem (sd_cpp.py) e voz
(piper.py). Esse módulo é o único lugar que conhece pymupdf4llm/
python-docx/openpyxl/python-pptx.

Todas as funções aqui são SÍNCRONAS de propósito (I/O + CPU puro, sem
GPU) - quem chamar deve rodar via loop.run_in_executor() para não
bloquear o event loop asyncio, igual reasoning_engine.py já faz com
self.knowledge.build_context.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}

# PHX-NEW: Phoenix Document Transform — qualquer formato suportado pode ser
# FONTE e qualquer formato suportado pode ser SAÍDA. Isso não significa
# prometer preservação pixel-perfect do layout original: rebuild_document()
# materializa um NOVO documento a partir do conteúdo final produzido pelo
# pipeline. PDF deixa de ser proibido como saída.
REBUILD_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md"}


class DocumentEngineError(Exception):
    """Erro ao extrair ou reconstruir um documento. Sempre carrega uma
    mensagem clara o suficiente para virar a resposta HTTP de erro."""


# ============================================================
# EXTRAÇÃO
# ============================================================

def extract_text(path: Path) -> str:
    """Extrai o conteúdo textual/estruturado de um documento como Markdown
    (PDF/DOCX/PPTX) ou texto tabular (XLSX) ou texto puro (TXT/MD).

    Lança DocumentEngineError com uma mensagem clara se a extensão não for
    suportada, a dependência não estiver instalada, ou a extração falhar -
    nunca devolve string vazia silenciosamente (isso já causou bug real
    no endpoint antigo /api/documents/ingest, que devolvia
    {"error": "..."} só depois de já ter tentado mandar texto vazio pro
    LLM).
    """
    ext = path.suffix.lower()

    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext == ".xlsx":
        return _extract_xlsx(path)
    if ext == ".pptx":
        return _extract_pptx(path)
    if ext in (".txt", ".md"):
        return _extract_plain_text(path)

    raise DocumentEngineError(
        f"Extensão '{ext}' não suportada. Formatos aceitos: "
        f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}."
    )


def _extract_pdf(path: Path) -> str:
    text = ""
    try:
        import pymupdf4llm

        # PHX-FIX (auditoria 2026-08-20, "existem falhas e fallbacks -
        # rastrear e tirar tudo", evidência real: log de produção do
        # usuário mostrou "Using Tesseract for OCR processing." e "OCR on
        # page.number=2/3." sob um cabeçalho "=== Document parser
        # messages ===", durante uma /api/documents/read que travou no
        # timeout de 240s do DirectDocumentBridge (resident_manager.py) e
        # devolveu 422 - contradizendo a mensagem de erro logo abaixo, que
        # promete "esta versão da Document Engine não faz OCR").
        #
        # Root cause, confirmado lendo e reproduzindo localmente contra
        # pymupdf4llm 1.28.2 (o pacote instalado; requirements.txt só pede
        # ">=0.0.17", sem pin de versão): esta versão tem um "layout engine"
        # novo (ativo por padrão porque `pymupdf_layout` está instalado -
        # ver pymupdf4llm/__init__.py:_use_layout) cujo to_markdown() tem
        # `use_ocr=OCRMode.SELECT_KEEP_OLD` como PADRÃO IMPLÍCITO - ou seja,
        # pra qualquer página que a biblioteca ache "sem texto suficiente"
        # (típico de PDF escaneado, mas também de páginas com imagem de
        # fundo), ela invoca OCR de verdade (Tesseract, se disponível no
        # PATH - e é, o instalador da Phoenix já garante isso) SEM avisar o
        # código chamador, SEM nenhum timeout próprio, e SEM que
        # `_extract_pdf` (ou `read_document_direct`) jamais tenha pedido
        # isso. `read_document_direct()` só aplica seu timeout de 240s em
        # cima da INFERÊNCIA do LLM (`self.runtime.execute(plan)`) - a
        # chamada de extração que roda ANTES disso não tinha proteção
        # nenhuma, e OCR renderizando cada página em 150 DPI + rodando o
        # binário tesseract por página é ordens de magnitude mais lento que
        # ler o layer de texto nativo, explicando o timeout relatado.
        #
        # Reproduzido localmente: pymupdf4llm.to_markdown() num PDF sem
        # texto (só um retângulo desenhado) imprime exatamente
        # "=== Document parser messages ===" / "Using Tesseract for OCR
        # processing." e devolve texto vazio de qualquer forma (Tesseract
        # não acha texto numa imagem sem texto real) - ou seja, o OCR
        # silencioso não SALVAVA o caso de PDF escaneado, só o deixava
        # mais lento e imprevisível antes de acabar caindo no mesmo erro
        # "PDF extraído está vazio" abaixo.
        #
        # Fix: `use_ocr=OCRMode.NEVER` explícito torna a promessa da
        # mensagem de erro abaixo ("esta versão não faz OCR") verdadeira de
        # novo - extração de PDF volta a ser rápida e determinística (só
        # texto nativo), e um PDF escaneado falha IMEDIATAMENTE com o erro
        # claro já existente, em vez de travar minutos em OCR silencioso
        # pra no fim falhar de qualquer jeito. Se no futuro a Phoenix quiser
        # OCR de verdade em PDF escaneado, isso precisa ser uma decisão
        # explícita e documentada (endpoint próprio, timeout próprio,
        # feedback de progresso pro usuário) - não um default escondido de
        # uma dependência de terceiros.
        try:
            from pymupdf4llm.ocr import OCRMode
            text = pymupdf4llm.to_markdown(str(path), use_ocr=OCRMode.NEVER)
        except ImportError:
            # Versão de pymupdf4llm sem o submódulo pymupdf4llm.ocr (mais
            # antiga que 1.x, provavelmente sem a engine de layout/OCR
            # nova) - to_markdown() nunca fez OCR nessas versões, então
            # chamar sem o kwarg é seguro e equivalente.
            text = pymupdf4llm.to_markdown(str(path))
    except ImportError:
        try:
            import fitz  # PyMuPDF puro - fallback se pymupdf4llm não estiver instalado
        except ImportError as e:
            raise DocumentEngineError(
                "Nenhuma biblioteca de PDF instalada (pymupdf4llm/pymupdf). "
                "Rode: pip install pymupdf pymupdf4llm"
            ) from e
        doc = fitz.open(str(path))
        try:
            text = "\n\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    except Exception as e:
        raise DocumentEngineError(f"Falha ao extrair texto do PDF: {e}") from e

    if not text or not text.strip():
        raise DocumentEngineError(
            "PDF extraído está vazio (pode ser um PDF escaneado sem OCR - "
            "esta versão da Document Engine não faz OCR)."
        )
    return text


# PHX-NEW (pedido do usuário 2026-08-22: "habilitar todas as funçoes do
# modelo de ocr pra qualquer função" - escopo confirmado com o usuário:
# OCR real para ler PDF escaneado): o comentário de _extract_pdf() acima
# já deixava escrito o que faltava para fazer OCR direito - "isso precisa
# ser uma decisão explícita e documentada (endpoint próprio, timeout
# próprio, feedback de progresso pro usuário)". Esta função é só a parte
# de PDF dessa decisão: renderiza páginas como imagem para o
# ResidentManager rodar OCR de verdade via visão nativa (MiniCPM-V, já
# testada e funcionando em describe_image_direct) - ver
# `_ocr_scanned_pdf()` em resident_manager.py, chamada só como FALLBACK
# EXPLÍCITO quando extract_text() já confirmou que o PDF não tem texto
# nativo (nunca "por via das dúvidas" em cima de um PDF que já tem
# texto - isso reintroduziria o mesmo problema de lentidão/timeout
# silencioso que o `use_ocr=OCRMode.NEVER` acima corrigiu).
def render_pdf_pages_to_images(path: Path, out_dir: Path, *, max_pages: int = 10, dpi: int = 150) -> tuple[list[Path], int]:
    """Renderiza até `max_pages` páginas de um PDF como PNGs em `out_dir`
    (uma por página, 'page_0001.png', 'page_0002.png', ...).

    Devolve (lista_de_caminhos_renderizados, total_de_paginas_do_pdf) - o
    segundo valor permite a quem chamar reportar honestamente quantas
    páginas ficaram de fora quando o PDF tem mais páginas que `max_pages`,
    em vez de um corte silencioso.

    Só sabe abrir/renderizar PDF - não faz OCR nem chama modelo nenhum
    (isso é responsabilidade de quem chamar), mantendo o princípio deste
    módulo (só ele conhece a biblioteca de PDF)."""
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise DocumentEngineError(
            "PyMuPDF (fitz) não instalado - necessário para renderizar páginas de PDF "
            "para OCR. Rode: pip install pymupdf"
        ) from e

    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    try:
        doc = fitz.open(str(path))
        try:
            total_pages = doc.page_count
            zoom = dpi / 72.0
            matrix = fitz.Matrix(zoom, zoom)
            for page_index in range(min(total_pages, max_pages)):
                page = doc.load_page(page_index)
                pix = page.get_pixmap(matrix=matrix)
                page_path = out_dir / f"page_{page_index + 1:04d}.png"
                pix.save(str(page_path))
                rendered.append(page_path)
        finally:
            doc.close()
    except Exception as e:
        raise DocumentEngineError(f"Falha ao renderizar páginas do PDF para imagem: {e}") from e

    return rendered, total_pages


def _extract_docx(path: Path) -> str:
    try:
        import docx
    except ImportError as e:
        raise DocumentEngineError("python-docx não instalado. Rode: pip install python-docx") from e

    try:
        document = docx.Document(str(path))
    except Exception as e:
        raise DocumentEngineError(f"Falha ao abrir o DOCX: {e}") from e

    parts = []
    for para in document.paragraphs:
        if para.text.strip():
            parts.append(para.text)
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))

    text = "\n\n".join(parts)
    if not text.strip():
        raise DocumentEngineError("DOCX extraído está vazio.")
    return text


def _extract_xlsx(path: Path) -> str:
    try:
        import openpyxl
    except ImportError as e:
        raise DocumentEngineError("openpyxl não instalado. Rode: pip install openpyxl") from e

    try:
        wb = openpyxl.load_workbook(str(path), data_only=True)
    except Exception as e:
        raise DocumentEngineError(f"Falha ao abrir o XLSX: {e}") from e

    parts = []
    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]
        parts.append(f"## Planilha: {sheet_name}")
        for row in sheet.iter_rows(values_only=True):
            if any(cell is not None for cell in row):
                parts.append(" | ".join("" if c is None else str(c) for c in row))

    text = "\n".join(parts)
    if not text.strip():
        raise DocumentEngineError("XLSX extraído está vazio.")
    return text


# PHX-NEW (auditoria 2026-08-20, "XLSX timeout" - Seção 13): achado real -
# _extract_xlsx() acima despeja TODA linha de TODA planilha, sem limite
# nenhum, numa string só - pra uma planilha grande (milhares de linhas),
# isso sozinho é lento (openpyxl construindo uma string gigante em
# memória) e, mesmo com o prompt final cortado em 12000 caracteres em
# resident_manager.py, o LLM só via um pedaço arbitrário do meio/início
# do dump bruto - nunca um resumo de verdade da planilha (sem nome das
# colunas garantido, sem contagem real de linhas, sem tipos de dado). O
# resultado prático era o timeout de 5 minutos relatado: em CPU, gerar
# uma resposta útil a partir de um trecho bruto e truncado de milhares de
# células era lento e ainda assim pouco útil.
#
# summarize_xlsx_structure() troca "manda tudo" por "lê a ESTRUTURA":
# nomes de planilha, dimensões reais (via sheet.max_row/max_column - não
# precisa iterar a planilha inteira pra saber isso), cabeçalho (primeira
# linha não-vazia), N linhas de amostra, tipo de dado inferido por
# coluna (numérico/texto/data/vazio) e contagem real de linhas de dados.
# Usa read_only=True (openpyxl streama em vez de carregar tudo em
# memória) e para de iterar assim que já tem amostra suficiente de cada
# planilha - nunca varre a planilha inteira à toa.
def summarize_xlsx_structure(path: Path, max_sample_rows: int = 15, max_sheets: int = 12) -> str:
    """Lê um XLSX estruturalmente (sem despejar todas as linhas) e devolve
    um resumo determinístico e compacto: planilhas, dimensões, cabeçalho,
    amostra de linhas, tipos de coluna inferidos, contagem de linhas.
    Pensado especificamente pro caso "descreva/resuma este documento" -
    edição de XLSX continua usando _extract_xlsx() (precisa do conteúdo
    completo pra reconstruir o arquivo de verdade)."""
    try:
        import openpyxl
    except ImportError as e:
        raise DocumentEngineError("openpyxl não instalado. Rode: pip install openpyxl") from e

    try:
        # read_only=True: openpyxl streama linha a linha em vez de montar
        # a árvore inteira do XML em memória - essencial pra planilha
        # grande não travar já no load_workbook().
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    except Exception as e:
        raise DocumentEngineError(f"Falha ao abrir o XLSX: {e}") from e

    sheet_names = wb.sheetnames
    total_sheets = len(sheet_names)
    parts = [
        f"# Resumo estrutural da planilha '{path.name}'",
        f"Total de planilhas: {total_sheets}"
        + (f" (mostrando as primeiras {max_sheets})" if total_sheets > max_sheets else ""),
    ]

    try:
        for sheet_name in sheet_names[:max_sheets]:
            sheet = wb[sheet_name]
            # max_row/max_column vêm dos metadados da planilha - não
            # exige iterar linha por linha pra saber as dimensões.
            dim_rows = sheet.max_row or 0
            dim_cols = sheet.max_column or 0

            parts.append(f"\n## Planilha: {sheet_name}")
            parts.append(f"Dimensões: {dim_rows} linha(s) x {dim_cols} coluna(s).")

            if dim_rows == 0 or dim_cols == 0:
                parts.append("(planilha vazia)")
                continue

            header = None
            sample_rows = []
            data_row_count = 0
            col_types: dict[int, set[str]] = {}

            for row in sheet.iter_rows(values_only=True):
                if not any(cell is not None for cell in row):
                    continue
                if header is None:
                    header = row
                    continue
                data_row_count += 1
                # PHX-NOTE: inspeção por célula (inferência de tipo) só
                # roda enquanto ainda estamos coletando linhas de amostra
                # (no máximo max_sample_rows). Pra planilhas com centenas
                # de milhares de linhas, isso evita repetir um loop por
                # coluna em CADA linha (era o gargalo real: O(linhas x
                # colunas) mesmo depois de já ter amostra/tipos
                # suficientes). Depois do cap, cada linha adicional custa
                # só o incremento de data_row_count acima + o teste
                # "any(...)" de linha em branco - ambos baratos.
                if len(sample_rows) < max_sample_rows:
                    sample_rows.append(row)
                    for col_idx, cell in enumerate(row):
                        if cell is None:
                            continue
                        kind = (
                            "número" if isinstance(cell, (int, float)) and not isinstance(cell, bool)
                            else "booleano" if isinstance(cell, bool)
                            else "data" if hasattr(cell, "isoformat")
                            else "texto"
                        )
                        col_types.setdefault(col_idx, set()).add(kind)

            if header:
                parts.append("Cabeçalho: " + " | ".join("" if c is None else str(c) for c in header))
            parts.append(f"Linhas de dados (sem contar cabeçalho): {data_row_count}")

            if col_types:
                type_summary = []
                for col_idx in sorted(col_types.keys()):
                    col_label = (header[col_idx] if header and col_idx < len(header) and header[col_idx] is not None else f"coluna {col_idx + 1}")
                    type_summary.append(f"{col_label} ({'/'.join(sorted(col_types[col_idx]))})")
                parts.append("Tipos de dado por coluna (amostrado): " + "; ".join(type_summary))

            if sample_rows:
                parts.append(f"Amostra ({len(sample_rows)} de {data_row_count} linha(s)):")
                for row in sample_rows:
                    parts.append("  " + " | ".join("" if c is None else str(c) for c in row))
    finally:
        wb.close()

    if total_sheets > max_sheets:
        parts.append(f"\n(+{total_sheets - max_sheets} planilha(s) adicional(is) não mostrada(s) neste resumo)")

    return "\n".join(parts)


# ============================================================
# PREENCHIMENTO DE TEMPLATE (PHX-NEW, pedido do usuário 2026-08-28:
# "aceitar dois arquivos - um fonte, um template alvo - e editar o
# segundo em vez de gerar do zero"). Diferente de rebuild_document()
# (que sempre materializa um arquivo NOVO a partir de texto puro,
# perdendo formatação/fórmulas/outras planilhas do original), as duas
# funções abaixo abrem o workbook .xlsx ORIGINAL com openpyxl e só
# ACRESCENTAM linhas nele - outras planilhas, fórmulas e formatação de
# células não tocadas permanecem intactas. Por isso, hoje, só .xlsx é
# suportado como template alvo: é o único formato com um conceito claro
# de "coluna nomeada" pra mapear dados com segurança. Ver
# reference_file_path em resident_manager.py::edit_document_direct para
# o caso de usar um segundo arquivo como referência ao editar PDF/DOCX/
# PPTX/TXT/MD (fluxo diferente: dobra o conteúdo na instrução de edição,
# não faz merge estrutural).
# ============================================================

def read_xlsx_template_structure(path: Path, max_sheets: int = 12) -> dict:
    """Lê a ESTRUTURA de um XLSX-alvo (template) sem alterar nada em disco:
    por planilha, o cabeçalho real (primeira linha não vazia) e a última
    linha já ocupada (pra saber onde continuar preenchendo sem
    sobrescrever dados existentes).

    Diferente de summarize_xlsx_structure() (que devolve um resumo em
    TEXTO LIVRE pra "descreva esta planilha"), esta função devolve dados
    ESTRUTURADOS - fill_xlsx_template() precisa saber o nome exato de
    cada coluna e o número da última linha, não um resumo legível por
    humano.

    Devolve {"sheets": [{"name": str, "headers": list[str],
    "last_row": int}, ...]}. Uma planilha vazia aparece com
    headers=[] e last_row=0 - fill_xlsx_template() cria o cabeçalho a
    partir das chaves da primeira linha recebida nesse caso."""
    try:
        import openpyxl
    except ImportError as e:
        raise DocumentEngineError("openpyxl não instalado. Rode: pip install openpyxl") from e

    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    except Exception as e:
        raise DocumentEngineError(f"Falha ao abrir o XLSX-template: {e}") from e

    sheets_info = []
    try:
        for sheet_name in wb.sheetnames[:max_sheets]:
            sheet = wb[sheet_name]
            headers: list[str] = []
            header_row_idx = 0
            last_row = 0
            for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if not any(cell is not None for cell in row):
                    continue
                if not headers:
                    headers = ["" if c is None else str(c).strip() for c in row]
                    header_row_idx = row_idx
                last_row = row_idx
            sheets_info.append({
                "name": sheet_name,
                "headers": headers,
                "header_row": header_row_idx,
                "last_row": last_row,
            })
    finally:
        wb.close()

    return {"sheets": sheets_info}


def fill_xlsx_template(
    template_path: Path,
    sheet_rows: dict[str, list[dict]],
    output_path: Path,
) -> dict:
    """Abre `template_path` PRESERVANDO tudo que já existe (outras
    planilhas, fórmulas, formatação de células não tocadas) e ACRESCENTA
    as linhas de `sheet_rows` logo após a última linha ocupada de cada
    planilha, casando cada chave de linha com o cabeçalho REAL da
    planilha (comparação normalizada: strip + minúsculas). Salva o
    resultado em `output_path` - NUNCA sobrescreve `template_path`.

    `sheet_rows`: {"Nome da Planilha": [{"Coluna A": valor, ...}, ...]}.
    Uma chave de linha que não bate com nenhum cabeçalho existente vira
    uma NOVA coluna ao final da planilha (nunca é descartada em
    silêncio) - o relatório devolvido lista exatamente o que foi feito,
    pra quem chamar decidir o que mostrar ao usuário.

    Devolve {"rows_written": int, "sheets_used": list[str],
    "auto_created_columns": {"Planilha": [nomes]},
    "sheets_not_found": list[str]}."""
    if template_path.suffix.lower() != ".xlsx":
        raise DocumentEngineError(
            f"fill_xlsx_template só aceita template .xlsx (recebido: '{template_path.suffix}')."
        )

    try:
        import openpyxl
        from openpyxl.styles import Font
    except ImportError as e:
        raise DocumentEngineError("openpyxl não instalado. Rode: pip install openpyxl") from e

    try:
        # Sem read_only/data_only: precisamos de acesso de ESCRITA, e
        # data_only=False preserva as FÓRMULAS existentes como fórmulas
        # (data_only=True as substituiria pelo último valor calculado,
        # perdendo a fórmula em si ao salvar de novo).
        wb = openpyxl.load_workbook(str(template_path))
    except Exception as e:
        raise DocumentEngineError(f"Falha ao abrir o XLSX-template: {e}") from e

    rows_written = 0
    sheets_used: list[str] = []
    auto_created_columns: dict[str, list[str]] = {}
    sheets_not_found: list[str] = []

    try:
        for requested_sheet_name, rows in sheet_rows.items():
            if not rows:
                continue

            sheet_name = requested_sheet_name
            if sheet_name not in wb.sheetnames:
                # Sem correspondência exata: se o template só tem UMA
                # planilha, é seguro assumir que é essa (o LLM pode não
                # reproduzir o nome exato). Com mais de uma e nenhum
                # match, registra como não encontrada em vez de
                # adivinhar em qual planilha escrever.
                if len(wb.sheetnames) == 1:
                    sheet_name = wb.sheetnames[0]
                else:
                    sheets_not_found.append(requested_sheet_name)
                    continue

            sheet = wb[sheet_name]

            # Acha o cabeçalho real (primeira linha não vazia) e a
            # última linha ocupada - mesmo critério de
            # read_xlsx_template_structure(), refeito aqui porque o
            # workbook foi reaberto em modo de escrita (objetos de
            # planilha não são compartilháveis entre load_workbook()
            # com read_only diferente).
            header_row_idx = 0
            header_map: dict[str, int] = {}
            last_row = 0
            for row_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                if not any(cell is not None for cell in row):
                    continue
                if not header_map:
                    header_row_idx = row_idx
                    for col_idx, cell in enumerate(row, start=1):
                        if cell is not None and str(cell).strip():
                            header_map[str(cell).strip().lower()] = col_idx
                last_row = row_idx

            created_here: list[str] = []

            if not header_map:
                # Planilha vazia: cria o cabeçalho a partir das chaves
                # da PRIMEIRA linha recebida, na ordem em que vieram.
                header_row_idx = 1
                first_row_keys = list(rows[0].keys())
                for col_idx, key in enumerate(first_row_keys, start=1):
                    sheet.cell(row=1, column=col_idx, value=key)
                    header_map[str(key).strip().lower()] = col_idx
                    created_here.append(str(key))
                for cell in sheet[1]:
                    if cell.value is not None:
                        cell.font = Font(bold=True)
                last_row = 1

            current_row = max(last_row, header_row_idx) + 1
            for row_dict in rows:
                for key, value in row_dict.items():
                    if value is None:
                        continue
                    norm_key = str(key).strip().lower()
                    col_idx = header_map.get(norm_key)
                    if col_idx is None:
                        # Coluna nova: acrescenta ao final, nunca
                        # descarta o dado em silêncio.
                        col_idx = sheet.max_column + 1 if sheet.max_column else len(header_map) + 1
                        # max_column pode não refletir colunas só de
                        # cabeçalho recém-criadas acima nesta mesma
                        # chamada - garante que nunca colide com uma
                        # coluna já mapeada.
                        while col_idx in header_map.values():
                            col_idx += 1
                        sheet.cell(row=header_row_idx, column=col_idx, value=str(key))
                        sheet.cell(row=header_row_idx, column=col_idx).font = Font(bold=True)
                        header_map[norm_key] = col_idx
                        created_here.append(str(key))
                    sheet.cell(row=current_row, column=col_idx, value=value)
                current_row += 1
                rows_written += 1

            sheets_used.append(sheet_name)
            if created_here:
                auto_created_columns.setdefault(sheet_name, []).extend(created_here)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(str(output_path))
    finally:
        wb.close()

    validate_document(output_path)

    return {
        "rows_written": rows_written,
        "sheets_used": sheets_used,
        "auto_created_columns": auto_created_columns,
        "sheets_not_found": sheets_not_found,
    }


def _extract_pptx(path: Path) -> str:
    try:
        from pptx import Presentation
    except ImportError as e:
        raise DocumentEngineError("python-pptx não instalado. Rode: pip install python-pptx") from e

    try:
        prs = Presentation(str(path))
    except Exception as e:
        raise DocumentEngineError(f"Falha ao abrir o PPTX: {e}") from e

    parts = []
    for i, slide in enumerate(prs.slides, 1):
        slide_lines = [f"## Slide {i}"]
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                slide_lines.append(shape.text_frame.text)
        if len(slide_lines) > 1:
            parts.append("\n".join(slide_lines))

    text = "\n\n".join(parts)
    if not text.strip():
        raise DocumentEngineError("PPTX extraído está vazio.")
    return text


def _extract_plain_text(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    except Exception as e:
        raise DocumentEngineError(f"Falha ao ler arquivo de texto: {e}") from e

    if not text.strip():
        raise DocumentEngineError("Arquivo de texto está vazio.")
    return text


# ============================================================
# RECONSTRUÇÃO — recebe o texto (já editado pelo LLM) e grava um novo
# arquivo. A extensão de `output_path` decide o formato de saída.
# ============================================================

def rebuild_document(new_text: str, output_path: Path) -> Path:
    """Grava `new_text` em `output_path`, escolhendo o formato pela
    extensão de `output_path`. O resultado é um NOVO documento materializado
    pela Phoenix; não há restrição especial contra PDF."""
    ext = output_path.suffix.lower()
    if ext not in REBUILD_EXTENSIONS:
        raise DocumentEngineError(
            f"Não é possível gerar saída no formato '{ext}'. "
            f"Formatos de saída suportados: {', '.join(sorted(REBUILD_EXTENSIONS))}."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if ext == ".pdf":
        _rebuild_pdf(new_text, output_path)
    elif ext == ".docx":
        _rebuild_docx(new_text, output_path)
    elif ext == ".xlsx":
        _rebuild_xlsx(new_text, output_path)
    elif ext == ".pptx":
        _rebuild_pptx(new_text, output_path)
    else:  # .txt / .md
        output_path.write_text(new_text, encoding="utf-8")

    validate_document(output_path)
    return output_path



def _rebuild_pdf(text: str, output_path: Path) -> None:
    """Cria um PDF novo e válido a partir de texto/Markdown simples.

    Usa PyMuPDF, que já é dependência da Document Engine. A proposta aqui é
    materialização de conteúdo, não clonagem pixel-perfect do layout de um
    PDF de origem.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise DocumentEngineError("PyMuPDF não instalado. Rode: pip install pymupdf") from e

    import textwrap

    # A4 em pontos; margens confortáveis e fonte padrão embutida pelo PDF.
    page_width, page_height = 595.0, 842.0
    margin_x, margin_y = 54.0, 54.0
    font_size = 10.5
    line_height = 14.0
    usable_width = page_width - 2 * margin_x
    # Aproximação conservadora para Helvetica 10.5pt.
    chars_per_line = max(40, int(usable_width / (font_size * 0.52)))
    lines_per_page = max(25, int((page_height - 2 * margin_y) / line_height))

    logical_lines: list[str] = []
    for raw in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        # Remove só marcadores Markdown de heading na materialização básica;
        # preserva o conteúdo textual.
        cleaned = re.sub(r"^\\s{0,3}#{1,6}\\s+", "", raw).rstrip()
        if not cleaned:
            logical_lines.append("")
            continue
        wrapped = textwrap.wrap(
            cleaned,
            width=chars_per_line,
            replace_whitespace=False,
            drop_whitespace=True,
            break_long_words=True,
            break_on_hyphens=False,
        )
        logical_lines.extend(wrapped or [""])

    doc = fitz.open()
    try:
        if not logical_lines:
            logical_lines = [""]

        for offset in range(0, len(logical_lines), lines_per_page):
            page = doc.new_page(width=page_width, height=page_height)
            y = margin_y
            for line in logical_lines[offset:offset + lines_per_page]:
                page.insert_text(
                    (margin_x, y),
                    line,
                    fontsize=font_size,
                    fontname="helv",
                )
                y += line_height

        doc.save(str(output_path))
    finally:
        doc.close()


def validate_document(path: Path) -> None:
    """Valida que o arquivo materializado existe, não está vazio e reabre."""
    path = Path(path)
    if not path.exists() or path.stat().st_size <= 0:
        raise DocumentEngineError(f"Documento gerado está ausente ou vazio: {path}")

    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            import fitz
            doc = fitz.open(str(path))
            try:
                if doc.page_count < 1:
                    raise DocumentEngineError("PDF gerado não contém páginas.")
            finally:
                doc.close()
        elif ext == ".docx":
            import docx
            docx.Document(str(path))
        elif ext == ".xlsx":
            import openpyxl
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=False)
            wb.close()
        elif ext == ".pptx":
            from pptx import Presentation
            Presentation(str(path))
        elif ext in (".txt", ".md"):
            path.read_text(encoding="utf-8")
    except DocumentEngineError:
        raise
    except Exception as e:
        raise DocumentEngineError(f"Documento gerado não pôde ser reaberto/validado: {e}") from e

def _strip_inline_markdown(value: str) -> str:
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    return value.strip()


def _rebuild_docx(text: str, output_path: Path) -> None:
    try:
        import docx
    except ImportError as e:
        raise DocumentEngineError("python-docx não instalado. Rode: pip install python-docx") from e

    document = docx.Document()
    lines = str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()
        stripped = raw.strip()
        if not stripped:
            document.add_paragraph("")
            i += 1
            continue
        if re.fullmatch(r"-{3,}", stripped):
            i += 1
            continue

        # Markdown table -> Word table.
        if "|" in stripped and i + 1 < len(lines):
            sep = lines[i + 1].strip()
            if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", sep):
                headers = [_strip_inline_markdown(c) for c in stripped.strip("|").split("|")]
                rows = []
                i += 2
                while i < len(lines) and "|" in lines[i]:
                    row = [_strip_inline_markdown(c) for c in lines[i].strip().strip("|").split("|")]
                    if len(row) == len(headers):
                        rows.append(row)
                    i += 1
                table = document.add_table(rows=1, cols=len(headers))
                table.style = "Table Grid"
                for idx, value in enumerate(headers):
                    table.rows[0].cells[idx].text = value
                for row in rows:
                    cells = table.add_row().cells
                    for idx, value in enumerate(row):
                        cells[idx].text = value
                continue

        hm = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if hm:
            level = min(len(hm.group(1)), 3)
            document.add_heading(_strip_inline_markdown(hm.group(2)), level=level)
        elif re.match(r"^[-*]\s+", stripped):
            document.add_paragraph(_strip_inline_markdown(re.sub(r"^[-*]\s+", "", stripped)), style="List Bullet")
        elif re.match(r"^\d+[.)]\s+", stripped):
            document.add_paragraph(_strip_inline_markdown(re.sub(r"^\d+[.)]\s+", "", stripped)), style="List Number")
        else:
            document.add_paragraph(_strip_inline_markdown(stripped))
        i += 1

    document.save(str(output_path))


def _rebuild_xlsx(text: str, output_path: Path) -> None:
    try:
        import openpyxl
    except ImportError as e:
        raise DocumentEngineError("openpyxl não instalado. Rode: pip install openpyxl") from e

    wb = openpyxl.Workbook()
    sheet = wb.active
    sheet.title = "Phoenix"
    out_row = 1
    for raw_line in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        # Ignora separador de tabela Markdown: |---|---| ou --- | ---.
        if re.fullmatch(r"\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?", line):
            continue
        cells = [c.strip() for c in (line.strip("|").split("|") if "|" in line else [line])]
        cells = [_strip_inline_markdown(c) for c in cells]
        for col_idx, cell_val in enumerate(cells, 1):
            sheet.cell(row=out_row, column=col_idx, value=cell_val)
        out_row += 1

    if sheet.max_row >= 1:
        from openpyxl.styles import Font
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for column_cells in sheet.columns:
            max_len = max((len(str(c.value)) if c.value is not None else 0) for c in column_cells)
            sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_len + 2, 10), 45)
    wb.save(str(output_path))


def _rebuild_pptx(text: str, output_path: Path) -> None:
    try:
        from pptx import Presentation
        from pptx.util import Inches
    except ImportError as e:
        raise DocumentEngineError("python-pptx não instalado. Rode: pip install python-pptx") from e

    prs = Presentation()
    blank_layout = prs.slide_layouts[6]
    slide_chunks = text.split("## Slide")
    if len(slide_chunks) <= 1:
        # LLM não devolveu no formato "## Slide N" esperado - trata o
        # texto inteiro como um único slide em vez de descartar tudo.
        slide_chunks = [text]
    for chunk in slide_chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        slide = prs.slides.add_slide(blank_layout)
        textbox = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(9), Inches(6))
        textbox.text_frame.text = chunk
    prs.save(str(output_path))
