"""Testes do preenchimento de planilha em lotes com checkpoint incremental."""

import asyncio
from pathlib import Path

import openpyxl
import pytest

from phoenix_kernel.documents.batch_fill import (
    DiskCandidate, auto_batch_char_budget, choose_checkpoint_disk,
    rank_disks, run_batch_fill, split_into_chunks,
)


def _make_template(tmp_path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Produtos"
    ws.append(["Descrição", "NCM", "Preço"])
    p = tmp_path / "template.xlsx"
    wb.save(p)
    return p


def test_rank_prefers_nvme_then_ssd_then_hdd():
    cands = [
        DiskCandidate("C:\\", "HDD", 200 * 1024**3, 500 * 1024**3),
        DiskCandidate("J:\\", "NVMe", 100 * 1024**3, 256 * 1024**3),
        DiskCandidate("D:\\", "SSD", 80 * 1024**3, 250 * 1024**3),
    ]
    ranked = rank_disks(cands)
    assert ranked[0].media_type == "NVMe"
    assert ranked[1].media_type == "SSD"
    assert ranked[2].media_type == "HDD"


def test_disk_without_space_never_wins():
    cands = [
        DiskCandidate("J:\\", "NVMe", 10 * 1024**2, 256 * 1024**3),   # NVMe mas quase cheio
        DiskCandidate("D:\\", "SSD", 100 * 1024**3, 250 * 1024**3),
    ]
    ranked = rank_disks(cands)
    assert ranked[0].media_type == "SSD"  # SSD com espaço vence NVMe sem espaço


def test_batch_size_scales_with_model_and_vram():
    small_cpu = auto_batch_char_budget("qwen3-4b", 0, False)
    large_gpu = auto_batch_char_budget("gemma-12b", 7000, True)
    assert large_gpu > small_cpu  # modelo grande com GPU usa lote maior


def test_split_has_no_chunk_ceiling():
    text = "".join(f"registro {i}\n\n" for i in range(100_000))  # documento enorme
    chunks = split_into_chunks(text, 18000)
    # 100k linhas curtas -> muito mais que os 60 do teto antigo
    assert len(chunks) > 60


def test_checkpoint_written_every_batch_and_final_matches(tmp_path):
    template = _make_template(tmp_path)
    # 3 lotes, cada um com 2 produtos
    source = "\n\n".join(f"Produto {i}" for i in range(6))
    checkpoint_dir = tmp_path / "ckpt"
    out = tmp_path / "final.xlsx"

    seen_after_each_batch = []

    async def extract(chunk_text, idx, total):
        # cada lote devolve 2 linhas fixas
        base = (idx - 1) * 2
        return [
            {"Descrição": f"Item {base}", "NCM": "111", "Preço": "10"},
            {"Descrição": f"Item {base+1}", "NCM": "222", "Preço": "20"},
        ], "Produtos"

    def on_progress(prog):
        # a cada lote, o checkpoint no disco já deve existir e crescer
        if prog.checkpoint_path and prog.checkpoint_path.exists():
            wb = openpyxl.load_workbook(prog.checkpoint_path)
            seen_after_each_batch.append(wb.active.max_row - 1)  # -1 cabeçalho

    prog = asyncio.run(run_batch_fill(
        source_text=source, template_path=template, output_final_path=out,
        checkpoint_dir=checkpoint_dir, disk_used=None, char_budget=8,
        extract_rows_for_chunk=extract, default_sheet="Produtos",
        progress_cb=on_progress,
    ))

    # o checkpoint cresceu monotonicamente lote a lote (2, 4, 6...)
    assert seen_after_each_batch == sorted(seen_after_each_batch)
    assert seen_after_each_batch[-1] == prog.rows_written
    # arquivo final bate com o total
    wb = openpyxl.load_workbook(out)
    assert wb.active.max_row - 1 == prog.rows_written
    assert prog.failed_chunks == []


def test_failed_batch_is_skipped_not_fatal(tmp_path):
    template = _make_template(tmp_path)
    source = "\n\n".join(f"P{i}" for i in range(6))
    out = tmp_path / "final.xlsx"

    async def extract(chunk_text, idx, total):
        if idx == 2:
            return None, ""  # lote 2 falha
        return [{"Descrição": f"ok{idx}", "NCM": "1", "Preço": "1"}], "Produtos"

    prog = asyncio.run(run_batch_fill(
        source_text=source, template_path=template, output_final_path=out,
        checkpoint_dir=tmp_path / "ckpt", disk_used=None, char_budget=8,
        extract_rows_for_chunk=extract, default_sheet="Produtos",
    ))
    assert 2 in prog.failed_chunks
    assert prog.rows_written > 0  # os outros lotes ainda gravaram
    assert out.exists()
