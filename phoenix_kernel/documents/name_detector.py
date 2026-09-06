from __future__ import annotations
import re
from typing import Optional
from .confidence import FieldEvidence, ConfidenceStatus
from .structure_detector import Block

_LABEL_NAME = re.compile(r"(?i)(?:nome\s+do\s+produto|nome\s+na\s+loja\s+virtual|descri[çc][ãa]o)\s*:\s*(.+)")
_FIELD_LINE = re.compile(r"(?i)\b(ncm|cest|cfop|ean|c[oó]digo\s+de\s+barras|peso|pre[çc]o|altura|largura|profundidade)\s*[:\-\(]")
_EMOJI_PREFIX = re.compile(r"^\s*[\U0001F300-\U0001FAFF\u2600-\u27BF]+\s*")

def detect_name(block):
    if block.title:
        name=_clean_name(block.title)
        if name:
            return FieldEvidence(value=name, status=ConfidenceStatus.PROBABLE, source="structure", reason=f"Nome do título do bloco ({block.block_id})")
    for line in block.lines:
        m=_LABEL_NAME.search(line)
        if m:
            name=_clean_name(m.group(1))
            if name:
                return FieldEvidence(value=name, status=ConfidenceStatus.CONFIRMED, source="label", reason="Nome por rótulo explícito")
    if block.has_structured_data:
        for line in block.lines:
            s=line.strip()
            if not s: continue
            if _FIELD_LINE.search(s): continue
            if s.startswith("[") and s.endswith("]"): continue
            name=_clean_name(s)
            if name:
                return FieldEvidence(value=name, status=ConfidenceStatus.PROBABLE, source="fallback", reason="Nome inferido da linha de maior destaque")
    return None

def _clean_name(raw):
    s=raw.strip()
    s=_EMOJI_PREFIX.sub("", s)
    s=re.sub(r"^\d{1,3}\.\s*", "", s)  # remove "63. " se escapar
    s=s.strip("*•-– ")
    s=re.sub(r"\s+"," ",s)
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s=s[1:-1].strip()
    return s[:160]
