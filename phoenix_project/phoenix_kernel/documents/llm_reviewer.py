# llm_reviewer.py
from typing import Optional, Callable
from .confidence import FieldEvidence, ConfidenceStatus
from .structure_detector import Block

def review_with_llm(block: Block, field_type: str, candidates: list, llm_callback: Callable) -> FieldEvidence:
    if not candidates: raise ValueError("Sem candidatos")
    allowlist = list(set(str(c.value) for c in candidates))
    context = block.text[:500]
    prompt = f"Produto: {block.title}. Contexto: {context}. Qual o valor correto para {field_type}? Opções: {allowlist}. Responda apenas com uma das opções."
    
    llm_response = None
    try: llm_response = llm_callback(prompt, allowlist)
    except: pass
        
    for cand in candidates:
        if str(cand.value) == str(llm_response):
            return FieldEvidence(cand.value, ConfidenceStatus.CONFIRMED, "llm", f"LLM escolheu este valor")
            
    for cand in candidates:
        if cand.status != ConfidenceStatus.INVALID:
            return FieldEvidence(cand.value, ConfidenceStatus.PROBABLE, "fallback", "LLM falhou. Valor assumido por fallback.")
    return candidates[0]
