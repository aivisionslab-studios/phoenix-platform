"""Preenchimento de planilha em LOTES com checkpoint incremental em disco.

Este módulo existe para o cenário que `fill_spreadsheet_template_direct`
(em resident_manager.py) não cobre: um documento-fonte GRANDE (centenas de
páginas, dezenas/centenas de registros) que precisa virar uma planilha
preenchida sem:

  - estourar a RAM (a versão de uma-chamada acumula TODAS as linhas na
    memória e só grava o .xlsx no fim);
  - perder trabalho se algo travar no meio (a versão de uma-chamada grava
    uma vez só, no fim - travar no pedaço 55 de 80 perde tudo);
  - descartar páginas por causa de um teto fixo de pedaços
    (_SPREADSHEET_FILL_MAX_CHUNKS = 60).

Estratégia (exatamente o fluxo pedido pelo usuário):

  1. Localiza o disco MAIS RÁPIDO com espaço livre (NVMe > SSD > HDD),
     conversando com a telemetria/discovery de hardware da própria
     Phoenix. Esse disco vira a área de trabalho dos checkpoints.
  2. Divide o documento em lotes. O tamanho do lote se AJUSTA sozinho
     conforme o modelo/VRAM (modelo maior com GPU aguenta lotes maiores;
     modelo pequeno em CPU usa lotes menores).
  3. Para CADA lote: extrai as linhas via LLM e GRAVA IMEDIATAMENTE no
     .xlsx de checkpoint no disco rápido, acrescentando após a última
     linha já ocupada. Como cada lote é persistido assim que sai, não há
     acúmulo em RAM e não há "trabalho em andamento" para se perder - o
     arquivo no disco está sempre atualizado com tudo que já foi extraído.
  4. Ao terminar, o checkpoint É o resultado final (copiado para a pasta
     de saída oficial).

A extração de UM lote (montar prompt, chamar o modelo, parsear JSON) é
injetada como callback `extract_rows_for_chunk`, para este módulo não
depender do ResidentManager nem de runtime - fica testável isoladamente e
o resident continua sendo o dono da política de modelo/timeout/web.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional

from phoenix_kernel.documents.engine import (
    DocumentEngineError,
    fill_xlsx_template,
    read_xlsx_template_structure,
)

# Ranking de velocidade por tipo de mídia. Maior = mais rápido = preferido
# como área de checkpoint. Bate com a classificação que o discovery de
# hardware já produz (StorageInfo.type: "NVMe" | "SSD" | "HDD").
_MEDIA_SPEED_RANK = {"NVME": 3, "NVM": 3, "SSD": 2, "HDD": 1, "UNKNOWN": 0}

# Margem de espaço livre exigida no disco de checkpoint. Um .xlsx de
# catálogo raramente passa de dezenas de MB, mas exigimos folga real para
# nunca encher o disco de sistema por engano.
_MIN_FREE_BYTES = 512 * 1024 * 1024  # 512 MiB


@dataclass
class DiskCandidate:
    """Um destino possível para os checkpoints, já com tudo que a escolha
    por 'grau de importância' precisa: velocidade, espaço e um caminho
    gravável real."""
    mount: str          # raiz gravável, ex. "J:\\" ou "/mnt/nvme"
    media_type: str     # "NVMe" | "SSD" | "HDD" | "Unknown"
    free_bytes: int
    total_bytes: int
    label: str = ""     # modelo do disco, quando a telemetria informa

    @property
    def speed_rank(self) -> int:
        return _MEDIA_SPEED_RANK.get(self.media_type.upper(), 0)

    def __str__(self) -> str:
        gb = self.free_bytes / (1024 ** 3)
        return f"{self.mount} [{self.media_type}, {gb:.1f} GiB livres]"


def rank_disks(candidates: list[DiskCandidate]) -> list[DiskCandidate]:
    """Ordena os discos por 'grau de importância' para checkpoint: primeiro
    os que têm espaço suficiente, depois por velocidade da mídia (NVMe
    antes de SSD antes de HDD) e, como desempate, por espaço livre. Discos
    sem espaço mínimo vão para o fim, nunca são a primeira escolha."""
    def key(c: DiskCandidate):
        tem_espaco = c.free_bytes >= _MIN_FREE_BYTES
        return (tem_espaco, c.speed_rank, c.free_bytes)
    return sorted(candidates, key=key, reverse=True)


def choose_checkpoint_disk(
    candidates: list[DiskCandidate],
    fallback_dir: Path,
) -> tuple[Path, Optional[DiskCandidate]]:
    """Escolhe o melhor disco de checkpoint. Se nenhum candidato tiver
    espaço mínimo (ou a lista vier vazia porque a telemetria não achou
    nada), cai para `fallback_dir` - o pipeline nunca deixa de rodar por
    causa da escolha de disco; só perde a otimização de velocidade."""
    ranked = rank_disks(candidates)
    if ranked and ranked[0].free_bytes >= _MIN_FREE_BYTES:
        best = ranked[0]
        work = Path(best.mount) / "PhoenixBatchFill"
        try:
            work.mkdir(parents=True, exist_ok=True)
            # Prova de escrita real: telemetria pode reportar um disco que
            # não é gravável pelo processo (permissão, montagem read-only).
            probe = work / ".phoenix_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return work, best
        except Exception:
            pass  # cai para o próximo da lista, ou para o fallback
        for c in ranked[1:]:
            if c.free_bytes < _MIN_FREE_BYTES:
                break
            work = Path(c.mount) / "PhoenixBatchFill"
            try:
                work.mkdir(parents=True, exist_ok=True)
                probe = work / ".phoenix_write_probe"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
                return work, c
            except Exception:
                continue
    fallback_dir.mkdir(parents=True, exist_ok=True)
    return fallback_dir, None


def auto_batch_char_budget(
    model_id: str,
    vram_free_mb: Optional[int],
    runs_on_gpu: bool,
) -> int:
    """Decide o tamanho do lote (em caracteres de documento por chamada)
    conforme o modelo e a VRAM disponível - o 'Phoenix ajusta sozinha'.

    Racional: o custo real por lote é a inferência. Modelo grande e/ou com
    GPU processa um prompt maior por chamada sem estourar contexto nem
    ficar lento demais; modelo pequeno em CPU rende mais com lotes menores
    (mais chamadas curtas, cada uma barata, com menos risco de o JSON de
    saída ser truncado). Os números ficam abaixo do contexto do
    llama-server (16k tokens ~= 48k chars) com folga para o JSON de saída."""
    mid = (model_id or "").lower()
    large_markers = ("12b", "14b", "20b", "27b", "30b", "32b", "35b", "70b")
    is_large = any(m in mid for m in large_markers)

    if runs_on_gpu and (vram_free_mb or 0) >= 6000 and is_large:
        return 30000
    if runs_on_gpu and (vram_free_mb or 0) >= 4000:
        return 26000
    if is_large:
        return 24000
    # modelo pequeno em CPU (o caso comum nesta RX 580 de 8 GB, onde o chat
    # roda em CPU por design): lotes menores, mais seguros.
    return 18000


@dataclass
class BatchFillProgress:
    """Estado do preenchimento em lotes - o mesmo objeto serve de retorno
    final e de payload para reportar progresso lote a lote."""
    total_chunks: int = 0
    done_chunks: int = 0
    rows_written: int = 0
    checkpoint_path: Optional[Path] = None
    disk_used: Optional[DiskCandidate] = None
    failed_chunks: list[int] = field(default_factory=list)
    auto_created_columns: dict[str, list[str]] = field(default_factory=dict)
    finished: bool = False


# Assinatura do callback que extrai as linhas de UM lote. Recebe o texto do
# lote e o número (1-based) / total, devolve a lista de dicts-linha e o
# nome de planilha pedido (ou "" se indiferente). Erro do lote = devolver
# (None, "").
ExtractFn = Callable[[str, int, int], Awaitable[tuple[Optional[list[dict]], str]]]


def split_into_chunks(text: str, char_budget: int) -> list[str]:
    """Divide o texto em lotes de até `char_budget` caracteres, quebrando
    em fronteira de parágrafo/linha quando possível para não cortar um
    registro no meio. Não tem teto de número de lotes - vai até acabar."""
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + char_budget, n)
        if end < n:
            # recua até a última quebra de parágrafo (ou linha) dentro do
            # orçamento, para não partir um registro ao meio
            cut = text.rfind("\n\n", start, end)
            if cut <= start:
                cut = text.rfind("\n", start, end)
            if cut > start:
                end = cut
        chunks.append(text[start:end])
        start = end
    return [c for c in chunks if c.strip()]


async def run_batch_fill(
    *,
    source_text: str,
    template_path: Path,
    output_final_path: Path,
    checkpoint_dir: Path,
    disk_used: Optional[DiskCandidate],
    char_budget: int,
    extract_rows_for_chunk: ExtractFn,
    default_sheet: Optional[str] = None,
    progress_cb: Optional[Callable[[BatchFillProgress], None]] = None,
) -> BatchFillProgress:
    """Executa o preenchimento em lotes com checkpoint incremental.

    Para cada lote: chama `extract_rows_for_chunk`, e SE vier alguma linha,
    grava imediatamente no .xlsx de checkpoint (acrescentando após a última
    linha ocupada). O checkpoint É o estado - depois de cada lote, o disco
    já reflete tudo que foi extraído até ali. Um lote que falha é registrado
    e pulado; os outros seguem. Ao final, o checkpoint é copiado para
    `output_final_path`.

    Não acumula linhas em memória entre lotes: a cada lote, as linhas vão
    para o disco e são liberadas. É isso que permite documentos de qualquer
    tamanho sem crescer o uso de RAM."""
    chunks = split_into_chunks(source_text, char_budget)
    prog = BatchFillProgress(total_chunks=len(chunks), disk_used=disk_used)

    if not chunks:
        raise DocumentEngineError("Documento-fonte vazio: nada para dividir em lotes.")

    # descobre o nome de planilha-alvo a partir da estrutura do template
    structure = read_xlsx_template_structure(template_path)
    sheets = structure.get("sheets", [])
    if not sheets:
        raise DocumentEngineError("Template não tem nenhuma planilha.")
    valid_sheet_names = {s["name"] for s in sheets}
    fallback_sheet = default_sheet if default_sheet in valid_sheet_names else sheets[0]["name"]

    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    checkpoint = checkpoint_dir / f"{template_path.stem}_checkpoint.xlsx"
    # o primeiro lote parte do TEMPLATE original; os seguintes partem do
    # próprio checkpoint (cada lote empilha sobre o anterior)
    current_base = template_path
    prog.checkpoint_path = checkpoint

    for idx, chunk_text in enumerate(chunks, start=1):
        rows, requested_sheet = await extract_rows_for_chunk(chunk_text, idx, len(chunks))
        prog.done_chunks = idx

        if rows is None:
            prog.failed_chunks.append(idx)
            if progress_cb:
                progress_cb(prog)
            continue
        if not rows:
            # lote sem registros relevantes é normal (não é erro); segue
            if progress_cb:
                progress_cb(prog)
            continue

        target_sheet = requested_sheet if requested_sheet in valid_sheet_names else fallback_sheet

        # grava ESTE lote imediatamente, acrescentando ao que já existe no
        # checkpoint. fill_xlsx_template escreve num arquivo NOVO, então
        # escrevemos num temporário e o promovemos a checkpoint - assim o
        # checkpoint nunca fica num estado meio-escrito se algo falhar no
        # meio do save.
        tmp_out = checkpoint_dir / f"{template_path.stem}_checkpoint.next.xlsx"
        report = fill_xlsx_template(
            template_path=current_base,
            sheet_rows={target_sheet: rows},
            output_path=tmp_out,
        )
        # promove o temporário a checkpoint oficial (troca atômica no mesmo
        # volume - os dois estão no mesmo disco de trabalho)
        tmp_out.replace(checkpoint)
        current_base = checkpoint  # próximo lote parte do checkpoint já gravado

        prog.rows_written += report.get("rows_written", 0)
        for sheet_name, cols in (report.get("auto_created_columns") or {}).items():
            prog.auto_created_columns.setdefault(sheet_name, [])
            for c in cols:
                if c not in prog.auto_created_columns[sheet_name]:
                    prog.auto_created_columns[sheet_name].append(c)

        if progress_cb:
            progress_cb(prog)

    # materializa a saída final a partir do checkpoint (se algum lote gravou)
    if checkpoint.exists():
        output_final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(checkpoint, output_final_path)
    prog.finished = True
    if progress_cb:
        progress_cb(prog)
    return prog
