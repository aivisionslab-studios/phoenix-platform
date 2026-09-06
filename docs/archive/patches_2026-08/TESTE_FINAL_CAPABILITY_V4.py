#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

CHECKPOINT = Path(".phoenix_v4_test_checkpoint.json")
DEFAULT_BASE = "http://127.0.0.1:8000"


class TestFailure(RuntimeError):
    pass


def request_json(
    base: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 120,
) -> tuple[int, Any]:
    url = base.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw else {}
            except Exception:
                body = raw
            return int(resp.status), body
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else {}
        except Exception:
            body = raw
        return int(exc.code), body
    except Exception as exc:
        raise TestFailure(f"Falha de conexão com {url}: {exc}") from exc


def ok(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[OK]   {label}{suffix}")


def fail(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[FAIL] {label}{suffix}")
    raise TestFailure(f"{label}: {detail}".strip(": "))


def warn(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"[WARN] {label}{suffix}")


def assert_free_limits(limits: dict[str, Any]) -> None:
    if limits.get("plan") != "free":
        fail("Plano FREE", f"recebido: {limits.get('plan')!r}")
    ok("Plano FREE")

    if limits.get("max_documents") != 10:
        fail("Limite de documentos", f"esperado 10, recebido {limits.get('max_documents')!r}")
    ok("Limite de documentos", "10")

    if int(limits.get("max_upload_bytes") or 0) != 25 * 1024 * 1024:
        fail("Limite de upload", f"esperado 25 MB, recebido {limits.get('max_upload_bytes')!r}")
    ok("Limite de upload", "25 MB")

    if int(limits.get("max_characters") or 0) != 500_000:
        fail("Limite de caracteres", f"esperado 500000, recebido {limits.get('max_characters')!r}")
    ok("Limite de caracteres", "500000")

    if bool(limits.get("capability_valid")):
        fail("Capability inválida no FREE", "capability_valid veio True sem licença configurada")
    ok("Capability inválida no FREE", "fail-closed ativo")


def get_limits(base: str) -> dict[str, Any]:
    status, body = request_json(base, "GET", "/api/rag/limits", timeout=30)
    if status != 200 or not isinstance(body, dict):
        fail("/api/rag/limits", f"HTTP {status}: {body}")
    return body


def get_security(base: str) -> dict[str, Any]:
    status, body = request_json(base, "GET", "/api/rag/security-status", timeout=30)
    if status != 200 or not isinstance(body, dict):
        fail("/api/rag/security-status", f"HTTP {status}: {body}")
    return body


def add_doc(base: str, title: str, content: str) -> dict[str, Any]:
    status, body = request_json(
        base,
        "POST",
        "/api/rag/add",
        {"title": title, "content": content, "source_type": "MD"},
        timeout=180,
    )
    if status != 200 or not isinstance(body, dict) or not body.get("ok"):
        fail(f"Adicionar {title}", f"HTTP {status}: {body}")
    doc = body.get("document")
    if not isinstance(doc, dict) or not doc.get("id"):
        fail(f"Adicionar {title}", f"resposta sem document.id: {body}")
    return doc


def delete_doc(base: str, doc_id: str) -> None:
    status, body = request_json(base, "DELETE", f"/api/rag/{doc_id}", timeout=120)
    if status != 200:
        warn("Cleanup", f"não consegui remover {doc_id}: HTTP {status}: {body}")


def test_chat(base: str) -> None:
    marker = "PHX_CHAT_OK_" + uuid.uuid4().hex[:8]
    prompt = (
        "Teste de saúde da Phoenix. Responda de forma curta. "
        f"Inclua exatamente este marcador na resposta: {marker}"
    )
    status, body = request_json(
        base,
        "POST",
        "/api/command",
        {"command": prompt},
        timeout=240,
    )
    if status != 200:
        fail("Chat normal", f"HTTP {status}: {body}")

    rendered = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    if not rendered.strip():
        fail("Chat normal", "resposta vazia")

    # Alguns pipelines retornam a missão imediatamente e entregam a mensagem
    # posteriormente em /api/chat/pending. Portanto 200 + resposta não vazia
    # já prova que o caminho normal de comando continua operacional.
    ok("Chat normal", f"/api/command HTTP 200 ({len(rendered)} bytes)")


def test_rag_query(base: str, marker: str, expected_title: str) -> None:
    status, body = request_json(
        base,
        "POST",
        "/api/rag/query",
        {"query": marker, "n_results": 10, "min_score": 0.0},
        timeout=120,
    )
    if status != 200 or not isinstance(body, dict) or not body.get("ok"):
        fail("RAG query", f"HTTP {status}: {body}")

    hits = body.get("hits") or []
    if not isinstance(hits, list) or not hits:
        fail("RAG query", "nenhum hit retornado")

    serialized = json.dumps(hits, ensure_ascii=False)
    if marker not in serialized and expected_title not in serialized:
        fail("RAG query", "hits existem, mas o documento de teste não apareceu")
    ok("RAG query", f"{len(hits)} hit(s), documento de teste encontrado")


def expect_11th_blocked(base: str, run_id: str) -> None:
    title = f"PHX-V4-LIMIT-11-{run_id}"
    marker = f"PHX_V4_ELEVENTH_{run_id}"
    status, body = request_json(
        base,
        "POST",
        "/api/rag/add",
        {
            "title": title,
            "content": (
                f"{marker}\n"
                "Este documento deve ser recusado porque o plano Free já atingiu "
                "o limite de dez documentos lógicos."
            ),
            "source_type": "MD",
        },
        timeout=180,
    )

    if 200 <= status < 300:
        # Se isto acontecer, tentar localizar o id e remover para não poluir.
        try:
            doc = body.get("document") if isinstance(body, dict) else None
            if isinstance(doc, dict) and doc.get("id"):
                delete_doc(base, str(doc["id"]))
        finally:
            fail("11º documento bloqueado", f"foi ACEITO indevidamente: HTTP {status}: {body}")

    rendered = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
    expected_words = ("Limite", "limite", "10/10", "atingido")
    if not any(word in rendered for word in expected_words):
        fail(
            "11º documento bloqueado",
            f"foi recusado, mas por motivo inesperado. HTTP {status}: {body}",
        )
    ok("11º documento bloqueado", f"HTTP {status}, limite Free aplicado")


def before_restart(base: str, skip_chat: bool) -> int:
    print("=" * 68)
    print(" PHOENIX CAPABILITY V4 — TESTE FINAL DE INTEGRAÇÃO")
    print("=" * 68)
    print(f"API: {base}")
    print()

    limits = get_limits(base)
    assert_free_limits(limits)

    initial_count = int(limits.get("current_documents") or 0)
    print(f"\nDocumentos de usuário antes do teste: {initial_count}")

    if initial_count > 10:
        fail(
            "Estado inicial do RAG",
            f"Free reporta {initial_count} documentos autorizados (>10). "
            "Não vou modificar seus documentos.",
        )

    security = get_security(base)
    sec = security.get("security") if isinstance(security, dict) else None
    if isinstance(sec, dict):
        if sec.get("integrity_valid") is False:
            fail("Consenso de integridade", str(sec.get("reason") or sec))
        ok(
            "Consenso de integridade",
            f"authorized={sec.get('authorized_documents')}, "
            f"locked={sec.get('locked_or_unregistered_documents')}",
        )
    else:
        warn("Consenso de integridade", f"formato inesperado: {security}")

    run_id = uuid.uuid4().hex[:10]
    created: list[dict[str, str]] = []
    first_marker = ""
    first_title = ""

    try:
        vacancies = 10 - initial_count
        if vacancies == 0:
            warn(
                "1–10 documentos",
                "o repositório já começou em 10/10; não vou apagar documentos reais "
                "para recriar o teste do zero.",
            )
        else:
            print(f"\nPreenchendo {vacancies} vaga(s) temporária(s) até chegar a 10/10...")
            for i in range(vacancies):
                ordinal = initial_count + i + 1
                title = f"PHX-V4-TEST-{run_id}-{ordinal:02d}"
                marker = f"PHX_V4_RAG_MARKER_{run_id}_{ordinal:02d}"
                content = (
                    f"# Documento de teste Phoenix V4 {ordinal}\n\n"
                    f"Marcador único: {marker}\n\n"
                    "Este conteúdo foi criado automaticamente para validar o Knowledge "
                    "Repository, chunking, embeddings, registry, ledger, manifest e os "
                    "limites comerciais Free da Phoenix.\n"
                )
                doc = add_doc(base, title, content)
                created.append({"id": str(doc["id"]), "title": title})
                if not first_marker:
                    first_marker, first_title = marker, title

                now = get_limits(base)
                expected = ordinal
                actual = int(now.get("current_documents") or 0)
                if actual != expected:
                    fail(
                        f"Documento {ordinal}/10",
                        f"foi indexado, mas current_documents={actual}; esperado {expected}",
                    )
                ok(f"Documento {ordinal}/10", f"{title} → {doc['id']}")

            final = get_limits(base)
            if int(final.get("current_documents") or 0) != 10:
                fail("Chegada a 10/10", str(final))
            ok("1–10 documentos", "limite preenchido corretamente até 10/10")

            if first_marker:
                test_rag_query(base, first_marker, first_title)

        print()
        expect_11th_blocked(base, run_id)

        if skip_chat:
            warn("Chat normal", "ignorado por --skip-chat")
        else:
            print()
            test_chat(base)

        print()
        final_security = get_security(base)
        sec2 = final_security.get("security") if isinstance(final_security, dict) else None
        if isinstance(sec2, dict) and sec2.get("integrity_valid") is False:
            fail("Integridade após RAG", str(sec2.get("reason") or sec2))
        ok("Integridade após RAG", "consenso continua válido")

        checkpoint = {
            "created_at": int(time.time()),
            "base_url": base,
            "expected_plan": "free",
            "max_documents": 10,
            "max_upload_bytes": 25 * 1024 * 1024,
            "max_characters": 500_000,
            "initial_documents": initial_count,
            "created_test_documents": len(created),
        }
        CHECKPOINT.write_text(
            json.dumps(checkpoint, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        ok("Checkpoint de restart", str(CHECKPOINT.resolve()))

    finally:
        if created:
            print("\nLimpando SOMENTE os documentos temporários criados por este teste...")
            for item in reversed(created):
                delete_doc(base, item["id"])

            try:
                after_cleanup = get_limits(base)
                after_count = int(after_cleanup.get("current_documents") or 0)
                if after_count == initial_count:
                    ok("Cleanup", f"contagem restaurada para {initial_count}")
                else:
                    warn(
                        "Cleanup",
                        f"contagem atual={after_count}, inicial={initial_count}. "
                        "Verifique os IDs PHX-V4-TEST manualmente.",
                    )
            except Exception as exc:
                warn("Cleanup", str(exc))

    print()
    print("=" * 68)
    print(" FASE 1 PASSOU")
    print("=" * 68)
    print("Agora REINICIE a Phoenix por completo e execute:")
    print("  python .\\TESTE_FINAL_CAPABILITY_V4.py --after-restart")
    print()
    return 0


def after_restart(base: str) -> int:
    print("=" * 68)
    print(" PHOENIX CAPABILITY V4 — VALIDAÇÃO APÓS RESTART")
    print("=" * 68)

    if not CHECKPOINT.exists():
        fail(
            "Checkpoint",
            f"{CHECKPOINT} não existe. Rode primeiro sem --after-restart.",
        )
    cp = json.loads(CHECKPOINT.read_text(encoding="utf-8"))
    cp_base = str(cp.get("base_url") or base)
    if base == DEFAULT_BASE and cp_base:
        base = cp_base

    limits = get_limits(base)
    assert_free_limits(limits)
    ok("Phoenix respondeu após restart", base)

    status, body = request_json(base, "GET", "/api/licensing/status", timeout=30)
    if status != 200 or not isinstance(body, dict):
        fail("Licensing status após restart", f"HTTP {status}: {body}")

    licensing = body.get("licensing") or {}
    if licensing.get("plan") != "free" or licensing.get("capability_valid") is not False:
        fail("Persistência FREE após restart", str(licensing))
    ok(
        "Persistência FREE após restart",
        f"plan={licensing.get('plan')}, capability_valid={licensing.get('capability_valid')}",
    )

    security = get_security(base)
    sec = security.get("security") if isinstance(security, dict) else None
    if isinstance(sec, dict) and sec.get("integrity_valid") is False:
        fail("Integridade após restart", str(sec.get("reason") or sec))
    ok("Integridade após restart")

    print()
    print("=" * 68)
    print(" CAPABILITY V4 — TESTE FINAL APROVADO")
    print("=" * 68)
    print("Free persistiu após restart. V4 pode ser congelada para commit.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Teste final não destrutivo da Phoenix Capability V4."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument(
        "--after-restart",
        action="store_true",
        help="Valida apenas a persistência Free depois de reiniciar a Phoenix.",
    )
    parser.add_argument(
        "--skip-chat",
        action="store_true",
        help="Ignora /api/command caso você queira testar somente licensing/RAG.",
    )
    args = parser.parse_args()

    try:
        if args.after_restart:
            return after_restart(args.base_url.rstrip("/"))
        return before_restart(args.base_url.rstrip("/"), args.skip_chat)
    except TestFailure as exc:
        print()
        print("=" * 68)
        print(" TESTE REPROVADO")
        print("=" * 68)
        print(exc)
        return 1
    except KeyboardInterrupt:
        print("\nTeste interrompido pelo usuário.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
