# pipeline_orchestrator.py
from typing import Callable, Optional
from .structure_detector import detect_format
from .name_detector import detect_name
from .field_extractor import extract_fields
from .evidence_engine import resolve_by_confidence_hierarchy, apply_semantic_sanity
from .llm_reviewer import review_with_llm
from .smart_filler import fill_derived_defaults
from .fiscal_rag import FiscalRAG
from .output_writer import write_to_template
from .confidence import FieldEvidence, ConfidenceStatus, is_writeable, needs_audit

def fill_spreadsheet(document_text: str, template_path: str, output_path: str, ncm_table_path: str = "", llm_callback: Optional[Callable] = None, sheet_name: Optional[str] = None) -> dict:
    fiscal_rag = FiscalRAG(ncm_table_path) if ncm_table_path else None
    detection = detect_format(document_text)
    records, stats, row_num = [], {"total": 0, "with_name": 0, "fields_written": 0, "audit_count": 0, "ncm_injected": 0}, 1
    
    for block in detection.blocks:
        stats["total"] += 1; row_num += 1
        name_ev = detect_name(block)
        if name_ev: stats["with_name"] += 1
        fields = extract_fields(block, block.local_format, None)
        if name_ev: fields["explicit_product_name"] = name_ev
            
        if fiscal_rag:
            if "ncm" in fields and fields["ncm"].value:
                if fiscal_rag.validate_ncm(fields["ncm"].value): fields["ncm"].status = ConfidenceStatus.CONFIRMED
                else: fields["ncm"].status = ConfidenceStatus.INVALID
            elif name_ev and llm_callback:
                sugg = fiscal_rag.suggest_ncm_with_llm(name_ev.value, llm_callback)
                if sugg: fields["ncm"] = sugg; stats["ncm_injected"] += 1
                
        fields = apply_semantic_sanity(fields)
        resolved = {}
        for ft, ev in fields.items():
            cands = ev if isinstance(ev, list) else [ev]
            r_ev = resolve_by_confidence_hierarchy(cands)
            if r_ev is None and len(cands) > 1 and llm_callback: r_ev = review_with_llm(block, ft, cands, llm_callback)
            elif r_ev is None and len(cands) > 1: r_ev = next((c for c in cands if c.status != ConfidenceStatus.INVALID), cands[0])
            elif r_ev is None: r_ev = cands[0]
            resolved[ft] = r_ev
            if is_writeable(r_ev): stats["fields_written"] += 1
            if needs_audit(r_ev): stats["audit_count"] += 1
            
        resolved = fill_derived_defaults(resolved, row_num)
        records.append(resolved)
        
    write_to_template(template_path, output_path, records, sheet_name)
    return stats
