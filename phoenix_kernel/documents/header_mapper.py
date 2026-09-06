from __future__ import annotations
import re
from typing import Callable, Optional
from . import glm_validators as normalizer
from .confidence import FieldEvidence, ConfidenceStatus

def _labeled(x): return FieldEvidence(value=x, status=ConfidenceStatus.PROBABLE, source="label", reason="por rótulo")

_HEADER_FIELD_MAP = [
    (re.compile(r"(?i)\bean\b|\bgtin\b|c[oó]digo\s*de\s*barras|c[oó]d\.?\s*barras"), "ean", normalizer.normalize_ean),
    (re.compile(r"(?i)\bncm\b"), "ncm", normalizer.normalize_ncm),
    (re.compile(r"(?i)\bcest\b"), "cest", normalizer.normalize_cest),
    (re.compile(r"(?i)\bcfop\b"), "cfop", normalizer.normalize_cfop),
    (re.compile(r"(?i)pre[çc]o\s+de\s+custo|\bcusto\b"), "cost_price", normalizer.normalize_price),
    (re.compile(r"(?i)pre[çc]o\s+venda\s+varejo"), "retail_price", normalizer.normalize_price),
    (re.compile(r"(?i)pre[çc]o\s+venda\s+atacado"), "wholesale_price", normalizer.normalize_price),
    (re.compile(r"(?i)^\s*pre[çc]o\s+de\s*$"), "compare_at_price", normalizer.normalize_price),
    (re.compile(r"(?i)^\s*pre[çc]o\s+por\s*$"), "sale_price", normalizer.normalize_price),
    (re.compile(r"(?i)pre[çc]o|valor"), "price", normalizer.normalize_price),
    (re.compile(r"(?i)\bpeso\b"), "weight", normalizer.normalize_weight),
    (re.compile(r"(?i)\baltura\b"), "height", normalizer.normalize_dimension),
    (re.compile(r"(?i)\blargura\b"), "width", normalizer.normalize_dimension),
    (re.compile(r"(?i)\bprofundidade\b"), "depth", normalizer.normalize_dimension),
    (re.compile(r"(?i)\bmarca\b"), "brand", _labeled),
    (re.compile(r"(?i)\bmodelo\b"), "model", _labeled),
    (re.compile(r"(?i)\btags\b"), "tags", _labeled),
    (re.compile(r"(?i)nome\s+do\s+produto|nome\s+na\s+loja"), "explicit_product_name", _labeled),
    (re.compile(r"(?i)^\s*descri[çc][ãa]o\s*$"), "explicit_product_name", _labeled),
]

def map_header(header_text):
    for pattern, field_type, norm_fn in _HEADER_FIELD_MAP:
        if pattern.search(header_text):
            return field_type, norm_fn
    return None, None
