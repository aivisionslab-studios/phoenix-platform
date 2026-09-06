# smart_filler.py
from .confidence import FieldEvidence, ConfidenceStatus

def fill_derived_defaults(fields: dict, row_num: int) -> dict:
    if not fields.get("origin"): fields["origin"] = FieldEvidence("NACIONAL", ConfidenceStatus.PROBABLE, "derivation", "Padrão MarketUP")
    if not fields.get("product_type"): fields["product_type"] = FieldEvidence("Mercadoria para Revenda", ConfidenceStatus.PROBABLE, "derivation")
    if not fields.get("active"): fields["active"] = FieldEvidence("Sim", ConfidenceStatus.PROBABLE, "derivation")
    if not fields.get("stock_movement"): fields["stock_movement"] = FieldEvidence("Sim", ConfidenceStatus.PROBABLE, "derivation")
    if not fields.get("internal_code"): fields["internal_code"] = FieldEvidence(f"PROD{row_num:03d}", ConfidenceStatus.PROBABLE, "derivation")
    if not fields.get("unit"): fields["unit"] = FieldEvidence("Unidade", ConfidenceStatus.PROBABLE, "derivation")
    return fields
