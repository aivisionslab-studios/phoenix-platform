"""Teste de calibração CPU (8081) vs GPU Vulkan (8090) para
`DocumentLLMWorker`, usando UM produto real do pipeline de documentos -
não é pytest (não começa com `test_`), mesmo espírito não-automatizado
dos outros scripts `*_smoke_test.py`/`*_benchmark_run.py` deste pipeline.

POR QUE UM PRODUTO SÓ, E POR QUE ESTE: já provamos capacidade Vulkan em
hardware real (subida manual isolada na porta 8082, RX 580 enumerada,
inferência real ~15.7 tok/s de geração). O que falta medir é o
comportamento com o tipo de carga que realmente importa no pipeline de
documentos - prompt de ENTRADA grande, saída pequena - não um prompt
sintético de 26 tokens. "Chá Gelado Lipton Limão 1.5L" (row_id 161 no
dataset da Loja Virtual) é a escolha natural: já é conhecido de cauda a
cauda nesta auditoria (é o caso MODEL_WRONG mais claro do benchmark de
36 produtos, com contexto grande e nada ambíguo - "Chá" aparece
repetido no nome/tags/descrição), e já temos o resultado real dele
rodando em CPU (`taxonomy_benchmark_store_results.csv`/
`taxonomy_benchmark_hard8_thinkingon_results.csv`) pra comparar.

O QUE ESTE SCRIPT MEDE: o MESMO payload semântico (mesmos fields,
mesmo system prompt, mesma allowlist, mesmo max_tokens, mesmo
no_think) rodando duas vezes - uma via `DocumentLLMWorker(mode="cpu")`
(assume 8081 já de pé, gerenciado pelo Kernel - este script nunca
sobe/derruba esse processo), outra via
`DocumentLLMWorker(mode="gpu")` (sobe um worker dedicado na 8090 com
`force_ngl="999"`, executa, derruba ao final). Isso prova (ou não) que
`DocumentLLMWorker` entrega o ganho de performance esperado no tipo de
carga real do pipeline - não só num prompt sintético - E valida a
abstração em si (lifecycle de subida/derrubada do worker GPU) antes de
qualquer generalização maior.

ISOLAMENTO: não modifica taxonomy_resolver.py, document_llm_worker.py,
resident_manager.py nem nenhum arquivo global/protegido. Só CONSOME
DocumentLLMWorker e taxonomy_resolver.py, exatamente como um script de
pipeline real faria.

Uso:
    .venv\\Scripts\\python.exe -m phoenix_kernel.documents.document_llm_worker_smoke_test \\
        --xlsx-path "C:\\PROJETO COMPLETO\\Produtos.xlsx" \\
        --dataset-csv taxonomy_benchmark_store_dataset.csv \\
        --row-id 161

Se quiser rodar só um dos dois modos (por exemplo, se a Arena já
estiver usando a porta 8090 e você não quiser disputar):
    ... --skip-gpu
    ... --skip-cpu
"""
from __future__ import annotations

import argparse
import asyncio
import csv

from phoenix_kernel.documents.document_llm_worker import DOCUMENT_GPU_PORT_START, DocumentLLMWorker
from phoenix_kernel.documents.evidence_engine import EvidenceEntry, FieldEvidence
from phoenix_kernel.documents.taxonomy_benchmark_dataset import build_store_taxonomy, load_products
from phoenix_kernel.documents.taxonomy_resolver import TaxonomyLevel, resolve_taxonomy_pair, resolve_taxonomy_source


def _fe(value: str, *, field_type: str, final_confidence: float = 0.9) -> FieldEvidence:
    entry = EvidenceEntry(
        candidate_id="c1", source="text", value=value, valid=True, confidence=final_confidence,
        source_block="b1", source_record="r_calib", source_method="label", source_origin_hash="hash-b1",
    )
    return FieldEvidence(field_type=field_type, record_id="r_calib", status="probable", value=value,
                          final_confidence=final_confidence, evidence=[entry])


def _load_row(dataset_csv: str, row_id: str) -> dict:
    with open(dataset_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["row_id"] == str(row_id):
                return row
    raise SystemExit(f"row_id={row_id!r} não encontrado em {dataset_csv!r}.")


def _build_fields(row: dict) -> dict:
    fields = {}
    if row.get("explicit_product_name"):
        fields["explicit_product_name"] = _fe(row["explicit_product_name"], field_type="explicit_product_name")
    if row.get("brand"):
        fields["brand"] = _fe(row["brand"], field_type="brand")
    if row.get("tags"):
        fields["tags"] = _fe(row["tags"], field_type="tags")
    if row.get("description_html"):
        fields["description_html"] = _fe(row["description_html"], field_type="description_html")
    return fields


async def _run_one(mode: str, *, row: dict, fields: dict, category_level, subcategory_level, gpu_port: int) -> dict:
    async with DocumentLLMWorker(
        mode=mode, no_think=True, max_tokens=2000, timeout=600.0, gpu_port=gpu_port,
    ) as worker:
        result = resolve_taxonomy_pair(
            f"calib_{row['row_id']}", fields, category_level, subcategory_level, worker.call,
        )
    diag = dict(worker.last_call_diagnostics)
    # `result.parent_value` já é o valor EFETIVO (resolution.selected_value,
    # ver taxonomy_resolver.py::_resolve_one_level) - correto tanto quando
    # veio de uma resolução LLM nova quanto de evidência já existente.
    # Não existe um "child_value" equivalente em TaxonomyPairResult - o
    # valor da subcategoria só está acessível via `child_candidate`
    # (`.raw_value`/`.normalized_value`, ver semantic_resolver.py::
    # resolution_to_candidate), que fica None só quando o LLM não foi
    # chamado pro filho (pai não resolveu, ou já havia evidência boa).
    return {
        "mode": mode,
        "predicted_category": result.parent_value,
        "confidence_category": (result.parent_candidate.confidence if result.parent_candidate else None),
        "predicted_subcategory": (result.child_candidate.raw_value if result.child_candidate else None),
        "confidence_subcategory": (result.child_candidate.confidence if result.child_candidate else None),
        "skipped_reasons": result.skipped_reasons,
        "diagnostics_by_field": diag,
    }


def _print_result(label: str, r: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"  categoria prevista:    {r['predicted_category']!r} (confidence={r['confidence_category']!r})")
    print(f"  subcategoria prevista: {r['predicted_subcategory']!r} (confidence={r['confidence_subcategory']!r})")
    if r["skipped_reasons"]:
        print(f"  skipped_reasons: {r['skipped_reasons']}")
    for field_type, d in r["diagnostics_by_field"].items():
        print(
            f"  [{field_type}] porta={d['port']} elapsed={d['elapsed']:.2f}s "
            f"prompt_tokens={d['prompt_tokens']} completion_tokens={d['completion_tokens']} "
            f"finish_reason={d['finish_reason']!r}"
        )
        # PHX-DIAG (30/08): campos novos vindos de document_llm_worker.py -
        # só existem pra investigar o achado real "content vazio + tokens
        # bateram o teto" visto no worker GPU (ver comentário completo no
        # worker). content_length/message_keys são baratos e sempre
        # mostrados; os previews de texto só saem quando parece o caso
        # suspeito (content vazio) ou quando o parser rejeitou a resposta -
        # pra não poluir a saída de um run que deu certo.
        content_length = d.get("content_length")
        if content_length is not None:
            print(f"    content_length={content_length} message_keys={d.get('message_keys')}")
        if content_length == 0 or r["skipped_reasons"]:
            if d.get("reasoning_content_preview"):
                print(f"    reasoning_content_preview: {d['reasoning_content_preview']!r}")
            if d.get("content_preview"):
                print(f"    content_preview: {d['content_preview']!r}")
            if d.get("raw_response_preview"):
                print(f"    raw_response_preview: {d['raw_response_preview']!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--xlsx-path", required=True)
    parser.add_argument("--dataset-csv", required=True)
    parser.add_argument("--row-id", default="161", help="row_id do produto no dataset CSV (default: 161, Lipton).")
    parser.add_argument("--skip-cpu", action="store_true")
    parser.add_argument("--skip-gpu", action="store_true")
    parser.add_argument(
        "--gpu-port", type=int, default=DOCUMENT_GPU_PORT,
        help=(
            "Porta do worker GPU dedicado (default: mesma porta 8090 que a Arena usa hoje). "
            "PHX-FIX (achado real 2026-08-29): em pelo menos uma máquina de teste, 8090 já "
            "estava ocupada por um processo do Windows sem relação nenhuma com a Phoenix "
            "('WsToastNotification') - confirme com "
            "'Get-NetTCPConnection -LocalPort <porta> -State Listen' antes de escolher uma "
            "porta alternativa, e não mate esse processo do Windows."
        ),
    )
    args = parser.parse_args()

    df = load_products(args.xlsx_path)
    taxonomy = build_store_taxonomy(df)
    category_level = TaxonomyLevel(
        field_type="store_category",
        source=resolve_taxonomy_source(erp_template_values=taxonomy["categories"]),
    )
    subcategory_level = TaxonomyLevel(
        field_type="store_subcategory",
        source=resolve_taxonomy_source(erp_template_values=["placeholder"]),
        parent_field_type="store_category",
        values_by_parent=taxonomy["subcategories_by_category"],
    )

    row = _load_row(args.dataset_csv, args.row_id)
    fields = _build_fields(row)
    print(f"Calibração CPU vs GPU - produto: {row['explicit_product_name']!r} (row_id={row['row_id']})")
    print(f"Esperado (referência humana): {row.get('expected_store_category')!r} / {row.get('expected_store_subcategory')!r}")

    results = {}
    if not args.skip_cpu:
        print("\nRodando em mode='cpu' (porta 8081, motor compartilhado)...")
        results["cpu"] = asyncio.run(
            _run_one("cpu", row=row, fields=fields, category_level=category_level, subcategory_level=subcategory_level,
                      gpu_port=args.gpu_port)
        )
        _print_result("CPU (8081)", results["cpu"])

    if not args.skip_gpu:
        print(f"\nRodando em mode='gpu' (porta {args.gpu_port}, worker Vulkan dedicado)...")
        results["gpu"] = asyncio.run(
            _run_one("gpu", row=row, fields=fields, category_level=category_level, subcategory_level=subcategory_level,
                      gpu_port=args.gpu_port)
        )
        _print_result(f"GPU Vulkan ({args.gpu_port})", results["gpu"])

    if "cpu" in results and "gpu" in results:
        print("\n=== comparação ===")
        same_cat = results["cpu"]["predicted_category"] == results["gpu"]["predicted_category"]
        same_sub = results["cpu"]["predicted_subcategory"] == results["gpu"]["predicted_subcategory"]
        print(f"  decisão de categoria idêntica entre CPU e GPU:    {same_cat}")
        print(f"  decisão de subcategoria idêntica entre CPU e GPU: {same_sub}")
        if not same_cat or not same_sub:
            print("  ATENÇÃO: decisão mudou entre backends - isso é dado relevante (ver docstring do script).")


if __name__ == "__main__":
    main()
