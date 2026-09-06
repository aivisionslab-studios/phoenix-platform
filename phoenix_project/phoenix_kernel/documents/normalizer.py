# normalizer.py
"""Camada A: validação determinística."""
from __future__ import annotations
import re
from typing import Optional
from .confidence import FieldEvidence, ConfidenceStatus

def validate_ean13(ean: str) -> bool:
    if not re.fullmatch(r"\d{13}", ean): return False
    digits = [int(d) for d in ean]
    checksum = sum(d * (1 if i % 2 == 0 else 3) for i, d in enumerate(digits[:-1]))
    return (10 - (checksum % 10)) % 10 == digits[-1]

def validate_ean8(ean: str) -> bool:
    if not re.fullmatch(r"\d{8}", ean): return False
    digits = [int(d) for d in ean]
    checksum = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(digits[:-1]))
    return (10 - (checksum % 10)) % 10 == digits[-1]

def normalize_ean(raw: str) -> Optional[FieldEvidence]:
    if not raw: return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 13 and validate_ean13(digits):
        return FieldEvidence(digits, ConfidenceStatus.CONFIRMED, "checksum", "EAN-13 válido")
    if len(digits) == 8 and validate_ean8(digits):
        return FieldEvidence(digits, ConfidenceStatus.CONFIRMED, "checksum", "EAN-8 válido")
    if 12 <= len(digits) <= 14:
        return FieldEvidence(digits, ConfidenceStatus.INVALID, "formato", "Checksum falhou")
    return None

def normalize_ncm(raw: str) -> Optional[FieldEvidence]:
    if not raw: return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) != 8: return None
    return FieldEvidence(digits, ConfidenceStatus.PROBABLE, "formato", "NCM 8 dígitos")

def normalize_cest(raw: str) -> Optional[FieldEvidence]:
    if not raw: return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 7:
        return FieldEvidence(digits, ConfidenceStatus.PROBABLE, "formato", "CEST 7 dígitos")
    return None

def normalize_cfop(raw: str) -> Optional[FieldEvidence]:
    if not raw: return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) != 4: return None
    n = int(digits)
    if any(lo <= n <= hi for lo, hi in [(1100, 1999), (2100, 2999), (3100, 3999), (4100, 4999), (5100, 5999), (6100, 6999), (7100, 7999)]):
        return FieldEvidence(digits, ConfidenceStatus.PROBABLE, "faixa", "CFOP válido")
    return FieldEvidence(digits, ConfidenceStatus.INVALID, "faixa", "CFOP fora da faixa")

def normalize_price(raw: str) -> Optional[FieldEvidence]:
    if not raw: return None
    s = str(raw).replace("R$", "").replace(" ", "")
    if "," in s and "." in s: s = s.replace(".", "").replace(",", ".")
    elif "," in s: s = s.replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m: return None
    try: v = float(m.group())
    except: return None
    if 0.01 <= v <= 999999: return FieldEvidence(v, ConfidenceStatus.PROBABLE, "faixa", "Preço plausível")
    return FieldEvidence(v, ConfidenceStatus.INVALID, "faixa", "Preço fora da faixa")

def normalize_weight(raw: str) -> Optional[FieldEvidence]:
    if not raw: return None
    s = str(raw).replace("kg", "").replace(" ", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m: return None
    try: v = float(m.group())
    except: return None
    if 0.001 <= v <= 50000: return FieldEvidence(v, ConfidenceStatus.PROBABLE, "faixa", "Peso plausível")
    return FieldEvidence(v, ConfidenceStatus.INVALID, "faixa", "Peso suspeito")

def normalize_dimension(raw: str) -> Optional[FieldEvidence]:
    if not raw: return None
    s = str(raw).replace("cm", "").replace(" ", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    if not m: return None
    try: v = float(m.group())
    except: return None
    if 0.1 <= v <= 99999: return FieldEvidence(v, ConfidenceStatus.PROBABLE, "faixa", "Dimensão plausível")
    return FieldEvidence(v, ConfidenceStatus.INVALID, "faixa", "Dimensão suspeita")
