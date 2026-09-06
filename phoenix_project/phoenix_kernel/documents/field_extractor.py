# field_extractor.py
import re
from typing import Optional
from .confidence import FieldEvidence, ConfidenceStatus
from . import normalizer
from .structure_detector import Block, DocumentFormat
from .header_mapper import map_header

_LABEL_PATTERNS = [
    (re.compile(r"(?i)pre[çc]o\s+de\s+custo[^:\n]*[:\-]\s*(R?\$?\s*[\d.,]+)"), "cost_price", normalizer.normalize_price),
    (re.compile(r"(?i)pre[çc]o\s+venda\s+varejo[^:\n]*[:\-]\s*(R?\$?\s*[\d.,]+)"), "retail_price", normalizer.normalize_price),
    (re.compile(r"(?i)pre[çc]o\s+venda\s+atacado[^:\n]*[:\-]\s*(R?\$?\s*[\d.,]+)"), "wholesale_price", normalizer.normalize_price),
    (re.compile(r"(?i)pre[çc]o\s+m[ií]nimo[^:\n]*[:\-]\s*(R?\$?\s*[\d.,]+)"), "sale_price", normalizer.normalize_price),
    (re.compile(r"(?i)pre[çc]o\s+m[aá]ximo[^:\n]*[:\-]\s*(R?\$?\s*[\d.,]+)"), "compare_at_price", normalizer.normalize_price),
    (re.compile(r"(?i)^\s*pre[çc]o\s+de[^:\n]*[:\-]\s*(R?\$?\s*[\d.,]+)"), "compare_at_price", normalizer.normalize_price),
    (re.compile(r"(?i)^\s*pre[çc]o\s+por[^:\n]*[:\-]\s*(R?\$?\s*[\d.,]+)"), "sale_price", normalizer.normalize_price),
    (re.compile(r"(?i)\bpre[çc]o\b[^:\n]*[:\-]\s*(R?\$?\s*[\d.,]+)"), "price", normalizer.normalize_price),
    (re.compile(r"(?i)\bncm\b[^:\n]*[:\-]\s*([\d.]+)"), "ncm", normalizer.normalize_ncm),
    (re.compile(r"(?i)\bcest\b[^:\n]*[:\-]\s*([\d.]+)"), "cest", normalizer.normalize_cest),
    (re.compile(r"(?i)\bcfop\b[^:\n]*[:\-]\s*([\d.]+)"), "cfop", normalizer.normalize_cfop),
    (re.compile(r"(?i)(?:\bean\b|\bc[oó]d\.?\s*barras\b|\bc[oó]digo\s*de\s*barras\b|\bgtin\b)[^:\n]*[:\-]\s*([\d.]+)"), "ean", normalizer.normalize_ean),
    (re.compile(r"(?i)\bpeso\b[^:\n]*[:\-]\s*([\d.,]+)"), "weight", normalizer.normalize_weight),
    (re.compile(r"(?i)\baltura\b[^:\n]*[:\-]\s*([\d.,]+)"), "height", normalizer.normalize_dimension),
    (re.compile(r"(?i)\blargura\b[^:\n]*[:\-]\s*([\d.,]+)"), "width", normalizer.normalize_dimension),
    (re.compile(r"(?i)\bprofundidade\b[^:\n]*[:\-]\s*([\d.,]+)"), "depth", normalizer.normalize_dimension),
    (re.compile(r"(?i)\bmarca\b[^:\n]*[:\-]\s*([^\n|;]+)"), "brand", lambda x: FieldEvidence(x.strip(), ConfidenceStatus.PROBABLE, "label")),
    (re.compile(r"(?i)\btags\b[^:\n]*[:\-]\s*([^\n]+)"), "tags", lambda x: FieldEvidence(x.strip(), ConfidenceStatus.PROBABLE, "label")),
]

def extract_fields(block: Block, doc_format: DocumentFormat, table_header=None) -> dict:
    if doc_format == DocumentFormat.TABLE and table_header:
        return _extract_by_table_position(block, table_header)
    return _extract_by_label(block)

def _extract_by_table_position(block, table_header):
    fields = {}
    if not block.lines: return fields
    line = block.lines[0]
    if "\t" in line and line.count("\t") >= len(table_header) - 1: cells = line.split("\t")
    elif ";" in line and line.count(";") >= len(table_header) - 1: cells = line.split(";")
    else: cells = re.split(r"\s{2,}", line)
    for i, cell in enumerate(cells):
        if i >= len(table_header): break
        field_type, norm_fn = map_header(table_header[i])
        if field_type and norm_fn:
            ev = norm_fn(cell.strip())
            if ev: fields[field_type] = ev
    return fields

def _extract_by_label(block):
    fields = {}
    text = block.text
    for pattern, field_type, norm_fn in _LABEL_PATTERNS:
        if field_type in fields: continue
        m = pattern.search(text)
        if m:
            ev = norm_fn(m.group(1).strip())
            if ev:
                if field_type == "price" and any(k in fields for k in ["retail_price", "wholesale_price", "cost_price", "sale_price", "compare_at_price"]): continue
                fields[field_type] = ev
    return fields
