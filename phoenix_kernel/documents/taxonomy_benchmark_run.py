"""Phoenix Document Pipeline V2 - execução do benchmark semântico REAL
(grupo `taxonomy_resolver.py`) contra um LLM real, a partir do dataset
produzido por `taxonomy_benchmark_dataset.py` (produtos reais do
`Produtos.xlsx` da loja, taxonomia real da Loja Virtual). Mesmo espírito
do `taxonomy_resolver_smoke_test.py` (5 cenários fixos, já validado), mas
em lote sobre uma amostra maior e com referência humana real (o que o
ERP/loja já classificou), não casos sintéticos.

ISOLAMENTO: script novo, não modifica `taxonomy_resolver.py`,
`semantic_resolver.py`, `parse_and_validate_response` nem nenhuma regra
de Evidence. Duplica a chamada HTTP mínima (mesmo padrão dos outros
smoke tests deste pipeline, de propósito - cada script isolado não
depende de outro script de smoke test/benchmark pra fazer a chamada de
rede). NÃO é pytest (não começa com `test_`).

TAXONOMIA: reconstruída a partir do MESMO `Produtos.xlsx` real (via
`taxonomy_benchmark_dataset.build_store_taxonomy`), nunca hardcoded aqui -
garante que a allowlist usada na avaliação é fiel à realidade completa da
loja, não só aos valores que apareceram na amostra de ~36 produtos.

REFERÊNCIA E MÉTRICA (pedido explícito do usuário - "não quero que
ausência de gabarito ou gabarito suspeito vire erro do modelo"):
  - `match_category`/`match_subcategory` só são computados quando
    `reference_status == "ok"` no dataset; nas linhas "missing" o valor
    sai como "n/a (sem referência)" - a métrica principal de acerto
    (impressa no resumo agregado) considera SÓ as linhas com
    reference_status="ok" E reference_quality="ok".
  - linhas com reference_quality="suspect" (nenhuma nesta rodada da Loja
    Virtual, reservado pra quando o dataset da Rodada B/ERP tiver o caso
    já encontrado da Coca-Cola Plus Café) entram no CSV de saída com o
    match calculado normalmente, mas SEPARADAS do resumo principal -
    aparecem numa seção própria, porque "errar" contra um gabarito
    suspeito não é o mesmo que errar contra um gabarito confiável.
  - o resumo agregado quebra a taxa de acerto por `ambiguity_level`
    (low/medium/high) - a pergunta que motivou toda essa rodada:
    quando a ambiguidade humana sobe, a confidence do Qwen desce de
    verdade, ou ele continua reportando confidence alta mesmo errando
    mais?

`--no-think` funciona exatamente como em `taxonomy_resolver_smoke_test.py`
(mesma marcação `/no_think`, mesmo `max_tokens` default 2000) - decisão já
validada no A/B anterior de rodar a amostra grande majoritariamente com
thinking desligado.

Uso:
    python -m phoenix_kernel.documents.taxonomy_benchmark_run \\
        --xlsx-path "C:\\...\\Produtos.xlsx" \\
        --dataset-csv taxonomy_benchmark_store_dataset.csv \\
        --out-csv taxonomy_benchmark_store_results.csv \\
        --model qwen3-8b-q4_k_m --no-think
"""
from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from phoenix_kernel.documents.evidence_engine import EvidenceEntry, FieldEvidence, build_field_evidence
from phoenix_kernel.documents.normalized import Candidate, Record
from phoenix_kernel.documents.semantic_resolver import SemanticTask
from phoenix_kernel.documents.taxonomy_benchmark_dataset import build_store_taxonomy, load_products
from phoenix_kernel.documents.taxonomy_resolver import (
    TaxonomyLevel,
    resolve_taxonomy_pair,
    resolve_taxonomy_source,
)

_SYSTEM_PROMPT = (
    "Você é um classificador determinístico dentro de um pipeline automatizado. "
    "Responda ESTRITAMENTE em JSON, sem nenhum texto fora do JSON, sem markdown, "
    "sem bloco de pensamento, no formato exato: "
    '{"selected_value": <um item EXATAMENTE igual a um dos valores permitidos>, '
    '"confidence": <número entre 0 e 1>, "reason": <string curta>}. '
    "Nunca inclua nenhuma chave além dessas três. Nunca invente um valor fora "
    "da lista de valores permitidos, mesmo que o texto de evidência sugira outra coisa. "
    "Se a evidência for genuinamente ambígua entre mais de um valor permitido, escolha o "
    "mais provável mas reporte um confidence BAIXO - nunca infle a confiança pra parecer certo."
)


def _fe(value: str, *, field_type: str, final_confidence: float = 0.9) -> FieldEvidence:
    entry = EvidenceEntry(
        candidate_id="c1", source="text", value=value, valid=True, confidence=final_confidence,
        source_block="b1", source_record="r_bench", source_method="label", source_origin_hash="hash-b1",
    )
    return FieldEvidence(field_type=field_type, record_id="r_bench", status="probable", value=value,
                          final_confidence=final_confidence, evidence=[entry])


def _call_llm(*, question: str, allowed_values: list, evidence_snippets: list, base_url: str, model: str,
              timeout: float, max_tokens: int, no_think: bool) -> dict:
    """Mesma chamada HTTP OpenAI-compatível do `taxonomy_resolver_smoke_test.py`,
    duplicada de propósito (isolamento entre scripts de benchmark)."""
    user_content = (
        f"Pergunta: {question}\n"
        f"Valores permitidos (allowed_values): {json.dumps(allowed_values, ensure_ascii=False)}\n"
        "Evidências disponíveis:\n" + "\n".join(f"- {s}" for s in evidence_snippets)
    )
    system_prompt = _SYSTEM_PROMPT + (" /no_think" if no_think else "")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(base_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    start = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
    elapsed = time.monotonic() - start
    data = json.loads(raw)
    choice = data["choices"][0]
    message = choice.get("message") or {}
    text = message.get("content") or ""
    usage = data.get("usage") or {}
    return {
        "text": text, "elapsed": elapsed,
        "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
        "finish_reason": choice.get("finish_reason"),
    }


def _diagnose(raw_text: str, allowed_values: list):
    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        return False, None, None, None
    if not isinstance(data, dict):
        return True, None, None, None
    sv = data.get("selected_value")
    conf = data.get("confidence")
    out = (sv is not None) and (sv not in allowed_values)
    return True, sv, conf, out


@dataclass
class _LevelDiagnostics:
    predicted_value: object = None
    confidence: object = None
    json_valid: Optional[bool] = None
    outside_allowlist: Optional[bool] = None
    post_evidence_status: Optional[str] = None
    latency: Optional[float] = None
    completion_tokens: Optional[int] = None


def _make_llm_call_fn(*, base_url: str, model: str, timeout: float, max_tokens: int, no_think: bool, log: dict):
    """`log` é um dict mutável field_type -> _LevelDiagnostics, preenchido
    a cada chamada real - só pra reportar no CSV, nunca usado por
    `parse_and_validate_response`/Fase 8, que decide a partir do texto
    puro devolvido por esta função."""
    def _fn(task: SemanticTask) -> str:
        raw = _call_llm(
            question=task.question, allowed_values=list(task.allowed_values),
            evidence_snippets=task.evidence_snippets, base_url=base_url, model=model,
            timeout=timeout, max_tokens=max_tokens, no_think=no_think,
        )
        text = raw["text"]
        json_valid, sv, conf, out = _diagnose(text, list(task.allowed_values))
        log[task.field_type] = _LevelDiagnostics(
            predicted_value=sv, confidence=conf, json_valid=json_valid, outside_allowlist=out,
            latency=raw["elapsed"], completion_tokens=raw["completion_tokens"],
        )
        return text
    return _fn


def _evidence_status_alone(candidate: Optional[Candidate]) -> Optional[str]:
    if candidate is None:
        return None
    candidate.id = f"c_bench_{id(candidate)}"
    record = Record(record_id="r_bench_eval", candidate_ids=[candidate.id])
    fe = build_field_evidence(record, {candidate.id: candidate}, {})[0]
    return fe.status


_OUT_FIELDS = [
    "row_id", "explicit_product_name", "reference_status", "reference_quality", "ambiguity_level",
    "expected_store_category", "predicted_category", "confidence_category", "match_category",
    "json_valid_category", "outside_allowlist_category", "post_evidence_status_category",
    "latency_category", "completion_tokens_category",
    "expected_store_subcategory", "predicted_subcategory", "confidence_subcategory", "match_subcategory",
    "json_valid_subcategory", "outside_allowlist_subcategory", "post_evidence_status_subcategory",
    "latency_subcategory", "completion_tokens_subcategory",
]


def run_benchmark(*, xlsx_path: str, dataset_csv: str, base_url: str, model: str, timeout: float,
                   max_tokens: int, no_think: bool) -> list[dict]:
    df = load_products(xlsx_path)
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

    with open(dataset_csv, encoding="utf-8") as f:
        dataset_rows = list(csv.DictReader(f))

    results: list[dict] = []
    for i, row in enumerate(dataset_rows, start=1):
        fields = {}
        if row["explicit_product_name"]:
            fields["explicit_product_name"] = _fe(row["explicit_product_name"], field_type="explicit_product_name")
        if row.get("brand"):
            fields["brand"] = _fe(row["brand"], field_type="brand")
        if row.get("tags"):
            fields["tags"] = _fe(row["tags"], field_type="tags")
        if row.get("description_html"):
            fields["description_html"] = _fe(row["description_html"], field_type="description_html")

        log: dict = {}
        llm = _make_llm_call_fn(base_url=base_url, model=model, timeout=timeout, max_tokens=max_tokens,
                                 no_think=no_think, log=log)
        result = resolve_taxonomy_pair(f"bench_{row['row_id']}", fields, category_level, subcategory_level, llm)

        cat_diag = log.get("store_category", _LevelDiagnostics())
        sub_diag = log.get("store_subcategory", _LevelDiagnostics())
        cat_diag.post_evidence_status = _evidence_status_alone(result.parent_candidate)
        sub_diag.post_evidence_status = _evidence_status_alone(result.child_candidate)

        ref_ok = row["reference_status"] == "ok"
        match_category = "n/a (sem referência)"
        match_subcategory = "n/a (sem referência)"
        if ref_ok:
            match_category = str(cat_diag.predicted_value == row["expected_store_category"])
            match_subcategory = str(sub_diag.predicted_value == row["expected_store_subcategory"])

        results.append({
            "row_id": row["row_id"], "explicit_product_name": row["explicit_product_name"],
            "reference_status": row["reference_status"], "reference_quality": row["reference_quality"],
            "ambiguity_level": row["ambiguity_level"],
            "expected_store_category": row["expected_store_category"], "predicted_category": cat_diag.predicted_value,
            "confidence_category": cat_diag.confidence, "match_category": match_category,
            "json_valid_category": cat_diag.json_valid, "outside_allowlist_category": cat_diag.outside_allowlist,
            "post_evidence_status_category": cat_diag.post_evidence_status,
            "latency_category": f"{cat_diag.latency:.2f}" if cat_diag.latency is not None else "",
            "completion_tokens_category": cat_diag.completion_tokens,
            "expected_store_subcategory": row["expected_store_subcategory"],
            "predicted_subcategory": sub_diag.predicted_value, "confidence_subcategory": sub_diag.confidence,
            "match_subcategory": match_subcategory, "json_valid_subcategory": sub_diag.json_valid,
            "outside_allowlist_subcategory": sub_diag.outside_allowlist,
            "post_evidence_status_subcategory": sub_diag.post_evidence_status,
            "latency_subcategory": f"{sub_diag.latency:.2f}" if sub_diag.latency is not None else "",
            "completion_tokens_subcategory": sub_diag.completion_tokens,
        })
        print(f"[{i}/{len(dataset_rows)}] {row['explicit_product_name'][:50]!r:52} "
              f"-> {cat_diag.predicted_value!r} / {sub_diag.predicted_value!r} "
              f"(esperado: {row['expected_store_category']!r} / {row['expected_store_subcategory']!r}, "
              f"ref={row['reference_status']}, amb={row['ambiguity_level']})")

    return results


def _print_summary(results: list[dict]) -> None:
    print("\n=== resumo agregado do benchmark ===")
    scored = [r for r in results if r["reference_status"] == "ok" and r["reference_quality"] == "ok"]
    print(f"linhas com referência confiável (reference_status=ok, reference_quality=ok): {len(scored)}/{len(results)}")
    if scored:
        cat_matches = sum(1 for r in scored if r["match_category"] == "True")
        sub_matches = sum(1 for r in scored if r["match_subcategory"] == "True")
        print(f"acerto categoria: {cat_matches}/{len(scored)}")
        print(f"acerto subcategoria: {sub_matches}/{len(scored)}")

        print("\npor ambiguity_level (categoria):")
        for level in ("low", "medium", "high"):
            bucket = [r for r in scored if r["ambiguity_level"] == level]
            if not bucket:
                continue
            matches = sum(1 for r in bucket if r["match_category"] == "True")
            confidences = [float(r["confidence_category"]) for r in bucket if r["confidence_category"] not in (None, "")]
            avg_conf = sum(confidences) / len(confidences) if confidences else None
            print(f"  {level:7} n={len(bucket):3} acerto={matches}/{len(bucket)} "
                  f"confidence média={f'{avg_conf:.2f}' if avg_conf is not None else 'n/d'}")

    others = [r for r in results if not (r["reference_status"] == "ok" and r["reference_quality"] == "ok")]
    if others:
        print(f"\nlinhas SEM referência confiável (reference_status=missing ou reference_quality=suspect): {len(others)} "
              f"- fora da métrica de acerto acima, de propósito. Detalhe:")
        for r in others:
            print(f"  [{r['row_id']}] {r['explicit_product_name'][:45]!r:47} -> "
                  f"{r['predicted_category']!r}/{r['predicted_subcategory']!r} "
                  f"(confidence {r['confidence_category']}/{r['confidence_subcategory']}, "
                  f"status={r['reference_status']}/{r['reference_quality']})")

    total_latency = sum(float(r["latency_category"] or 0) + float(r["latency_subcategory"] or 0) for r in results)
    total_completion = sum((r["completion_tokens_category"] or 0) + (r["completion_tokens_subcategory"] or 0) for r in results)
    print(f"\nlatência total: {total_latency:.2f}s | completion_tokens total: {total_completion}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx-path", required=True)
    parser.add_argument("--dataset-csv", required=True)
    parser.add_argument("--out-csv", default="taxonomy_benchmark_store_results.csv")
    parser.add_argument("--base-url", default="http://127.0.0.1:8081/v1/chat/completions")
    parser.add_argument("--model", default="qwen3-8b-q4_k_m")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--no-think", action="store_true")
    args = parser.parse_args()

    print(f"Benchmark semântico (taxonomy_resolver, Loja Virtual) - dataset={args.dataset_csv} "
          f"base_url={args.base_url} model={args.model} max_tokens={args.max_tokens} no_think={args.no_think}")
    try:
        results = run_benchmark(
            xlsx_path=args.xlsx_path, dataset_csv=args.dataset_csv, base_url=args.base_url, model=args.model,
            timeout=args.timeout, max_tokens=args.max_tokens, no_think=args.no_think,
        )
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"\n<erro chamando o llama-server real: {exc}> - confira --base-url/--model e se o servidor está no ar.")
        return

    with open(args.out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_OUT_FIELDS)
        writer.writeheader()
        for r in results:
            writer.writerow(r)
    print(f"\nresultados -> {args.out_csv}")
    _print_summary(results)


if __name__ == "__main__":
    main()
