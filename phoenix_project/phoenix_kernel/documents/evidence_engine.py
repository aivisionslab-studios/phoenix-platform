# evidence_engine.py
from typing import Optional
from .confidence import FieldEvidence, ConfidenceStatus

def resolve_by_confidence_hierarchy(candidates: list) -> Optional[FieldEvidence]:
    if not candidates: return None
    if len(candidates) == 1: return candidates[0]
    status_weight = {ConfidenceStatus.CONFIRMED: 3, ConfidenceStatus.PROBABLE: 2, ConfidenceStatus.INVALID: 0}
    highest_weight = max(status_weight[c.status] for c in candidates)
    winners = [c for c in candidates if status_weight[c.status] == highest_weight]
    return winners[0] if len(winners) == 1 else None

def apply_semantic_sanity(fields: dict) -> dict:
    cost = fields.get("cost_price")
    retail = fields.get("retail_price")
    sale = fields.get("sale_price")
    if cost and retail and cost.value >= retail.value:
        fields["cost_price"].status = ConfidenceStatus.AMBIGUOUS
        fields["retail_price"].status = ConfidenceStatus.AMBIGUOUS
    if cost and sale and cost.value > sale.value:
        fields["cost_price"].status = ConfidenceStatus.AMBIGUOUS
        fields["sale_price"].status = ConfidenceStatus.AMBIGUOUS
    return fields
