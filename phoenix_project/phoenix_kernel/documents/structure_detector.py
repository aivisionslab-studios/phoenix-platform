# structure_detector.py
import re
from dataclasses import dataclass, field
from enum import Enum

class DocumentFormat(Enum):
    TABLE = "table"
    LABELED_BLOCKS = "labeled_blocks"
    NUMBERED_LIST = "numbered_list"
    HIGHLIGHTED_TITLE = "highlighted_title"
    MIXED = "mixed"
    UNKNOWN = "unknown"

@dataclass
class Block:
    block_id: str
    text: str
    lines: list = field(default_factory=list)
    title: str = ""
    number: int = None
    has_structured_data: bool = False
    local_format: DocumentFormat = DocumentFormat.UNKNOWN

@dataclass
class DetectionResult:
    format: DocumentFormat
    blocks: list
    confidence: float = 0.0

_NUM_TITLE = re.compile(r'^(\d{1,3})\.\s+([A-ZÀ-Ú].{4,158})$')
_LABELED_MARK = re.compile(r"(?i)\[dados\s+estruturados")
_DATA_HINT = re.compile(r"(?i)\b(ncm|cest|cfop|ean|peso|pre[çc]o|altura)\b")

def detect_format(text: str) -> DetectionResult:
    lines = [l.rstrip() for l in text.splitlines() if l.strip()]
    blocks, current_lines, block_idx = [], [], 0

    def flush_block(title="", num=None, fmt=DocumentFormat.UNKNOWN):
        nonlocal block_idx, current_lines
        if current_lines:
            txt = "\n".join(current_lines)
            has_data = bool(_DATA_HINT.search(txt))
            blocks.append(Block(f"B{block_idx}", txt, current_lines, title, num, has_data, fmt))
            block_idx += 1
            current_lines = []

    for line in lines:
        s = line.strip()
        is_num = _NUM_TITLE.match(s)
        is_labeled = _LABELED_MARK.search(s)
        
        if (is_num or is_labeled) and current_lines:
            txt = "\n".join(current_lines)
            fmt = DocumentFormat.HIGHLIGHTED_TITLE
            if "\t" in txt or txt.count(";") >= 3: fmt = DocumentFormat.TABLE
            elif _LABELED_MARK.search(txt): fmt = DocumentFormat.LABELED_BLOCKS
            flush_block(current_lines[0] if fmt==DocumentFormat.HIGHLIGHTED_TITLE else "", None, fmt)
            current_lines = []
            
        if is_num: current_lines.append(line)
        elif is_labeled: current_lines.append(line)
        else: current_lines.append(line)

    if current_lines:
        txt = "\n".join(current_lines)
        fmt = DocumentFormat.HIGHLIGHTED_TITLE
        if "\t" in txt or txt.count(";") >= 3: fmt = DocumentFormat.TABLE
        elif _LABELED_MARK.search(txt): fmt = DocumentFormat.LABELED_BLOCKS
        flush_block(current_lines[0] if fmt==DocumentFormat.HIGHLIGHTED_TITLE else "", None, fmt)

    global_fmt = DocumentFormat.MIXED if len(set(b.local_format for b in blocks)) > 1 else (blocks[0].local_format if blocks else DocumentFormat.UNKNOWN)
    return DetectionResult(global_fmt, blocks, 1.0 if blocks else 0.0)
