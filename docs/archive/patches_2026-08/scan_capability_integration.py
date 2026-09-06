"""
Executar NA RAIZ do Phoenix.

Este script NÃO altera arquivos automaticamente.
Ele descobre todos os pontos que ainda dependem das travas antigas para que a
integração possa ser feita sem quebrar APIs existentes.

Uso:
    python scan_capability_integration.py
"""

from pathlib import Path
import re

ROOT = Path.cwd()

PATTERNS = [
    r"phoenix_kernel\.licensing\.entitlements",
    r"phoenix_kernel\.licensing\.plans",
    r"rag_consensus",
    r"rag_integrity",
    r"rag_usage_ledger",
    r"rag_integrity_manifest",
    r"max_documents",
    r"max_upload",
    r"max_extracted",
]

SKIP = {".git", "node_modules", "repos", "dist", "__pycache__"}

for path in ROOT.rglob("*"):
    if not path.is_file() or path.suffix.lower() not in {".py", ".ts", ".tsx", ".ps1"}:
        continue
    if any(part in SKIP for part in path.parts):
        continue
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    hits = []
    for pat in PATTERNS:
        if re.search(pat, text, flags=re.I):
            hits.append(pat)
    if hits:
        print(f"{path.relative_to(ROOT)} :: {', '.join(hits)}")
