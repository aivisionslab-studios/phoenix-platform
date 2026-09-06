from __future__ import annotations
import re
from typing import Optional
from .confidence import FieldEvidence, ConfidenceStatus
from .ncm_lookup import ncm_exists
from .cest_lookup import cest_exists

def validate_ean13(ean):
    if not re.fullmatch(r"\d{13}", ean): return False
    digits=[int(d) for d in ean]
    checksum=sum(d*(1 if i%2==0 else 3) for i,d in enumerate(digits[:-1]))
    return (10-(checksum%10))%10==digits[-1]

def validate_ean8(ean):
    if not re.fullmatch(r"\d{8}", ean): return False
    digits=[int(d) for d in ean]
    checksum=sum(d*(3 if i%2==0 else 1) for i,d in enumerate(digits[:-1]))
    return (10-(checksum%10))%10==digits[-1]

def normalize_ean(raw):
    if not raw: return None
    digits=re.sub(r"\D","",str(raw))
    if len(digits)==13 and validate_ean13(digits):
        return FieldEvidence(value=digits,status=ConfidenceStatus.CONFIRMED,source="checksum",reason="EAN-13 válido")
    if len(digits)==8 and validate_ean8(digits):
        return FieldEvidence(value=digits,status=ConfidenceStatus.CONFIRMED,source="checksum",reason="EAN-8 válido")
    if 12<=len(digits)<=14:
        return FieldEvidence(value=digits,status=ConfidenceStatus.INVALID,source="formato",reason="checksum falhou")
    return None

_NCM_TABLE=None
def normalize_ncm(raw):
    if not raw: return None
    digits=re.sub(r"\D","",str(raw))
    if len(digits)!=8: return None
    # PHX-NEW (ligação com a tabela oficial, ncm_lookup.py): formato certo
    # não é a mesma coisa que o código EXISTIR. 8 dígitos numéricos passa
    # no formato mas pode ser invenção/erro de digitação/código
    # descontinuado. Existindo na tabela oficial -> CONFIRMED (mesmo
    # patamar que EAN com checksum batendo). Formato certo mas NÃO existe
    # -> INVALID (mesmo patamar que EAN com checksum falhando) - nunca
    # deixamos passar como "provável" um código que sabemos que não existe.
    if ncm_exists(digits):
        return FieldEvidence(value=digits,status=ConfidenceStatus.CONFIRMED,source="tabela_oficial",reason="NCM existe na tabela oficial (Res. Gecex)")
    return FieldEvidence(value=digits,status=ConfidenceStatus.INVALID,source="tabela_oficial",reason="NCM tem formato válido mas NÃO existe na tabela oficial")

def normalize_cest(raw):
    if not raw: return None
    digits=re.sub(r"\D","",str(raw))
    if len(digits)==7:
        # PHX-NEW (ligação com cest_lookup.py): mesma lógica do NCM acima -
        # o cest_lookup guarda o CEST formatado ("XX.XXX.XX"), então
        # reformatamos os 7 dígitos antes de checar existência.
        formatado=f"{digits[0:2]}.{digits[2:5]}.{digits[5:7]}"
        if cest_exists(formatado):
            return FieldEvidence(value=digits,status=ConfidenceStatus.CONFIRMED,source="tabela_oficial",reason="CEST existe na tabela oficial")
        return FieldEvidence(value=digits,status=ConfidenceStatus.INVALID,source="tabela_oficial",reason="CEST tem formato válido mas NÃO existe na tabela oficial")
    return None

_VALID_CFOP_RANGES=[(1100,1999),(2100,2999),(3100,3999),(4100,4999),(5100,5999),(6100,6999),(7100,7999)]
def normalize_cfop(raw):
    if not raw: return None
    digits=re.sub(r"\D","",str(raw))
    if len(digits)!=4: return None
    n=int(digits)
    for lo,hi in _VALID_CFOP_RANGES:
        if lo<=n<=hi:
            return FieldEvidence(value=digits,status=ConfidenceStatus.PROBABLE,source="faixa",reason=f"CFOP {lo}-{hi}")
    return FieldEvidence(value=digits,status=ConfidenceStatus.INVALID,source="faixa",reason="CFOP fora de faixa")

def normalize_price(raw):
    if not raw: return None
    s=str(raw).replace("R$","").replace(" ","")
    if "," in s and "." in s:
        s=s.replace(".","").replace(",",".")
    elif "," in s:
        s=s.replace(",",".")
    m=re.search(r"\d+(?:\.\d+)?",s)
    if not m: return None
    try: v=float(m.group())
    except ValueError: return None
    if 0.01<=v<=999999:
        return FieldEvidence(value=v,status=ConfidenceStatus.PROBABLE,source="faixa",reason="preço plausível")
    return FieldEvidence(value=v,status=ConfidenceStatus.INVALID,source="faixa",reason="preço fora de faixa")

def normalize_weight(raw):
    if not raw: return None
    s=str(raw).replace("kg","").replace("Kg","").replace(" ","").replace(",",".")
    m=re.search(r"\d+(?:\.\d+)?",s)
    if not m: return None
    try: v=float(m.group())
    except ValueError: return None
    if 0.001<=v<=50000:
        return FieldEvidence(value=v,status=ConfidenceStatus.PROBABLE,source="faixa",reason="peso plausível")
    return FieldEvidence(value=v,status=ConfidenceStatus.INVALID,source="faixa",reason="peso fora de faixa")

def normalize_dimension(raw):
    if not raw: return None
    s=str(raw).replace("cm","").replace(" ","").replace(",",".")
    m=re.search(r"\d+(?:\.\d+)?",s)
    if not m: return None
    try: v=float(m.group())
    except ValueError: return None
    if 0.1<=v<=99999:
        return FieldEvidence(value=v,status=ConfidenceStatus.PROBABLE,source="faixa",reason="dimensão plausível")
    return FieldEvidence(value=v,status=ConfidenceStatus.INVALID,source="faixa",reason="dimensão fora de faixa")
