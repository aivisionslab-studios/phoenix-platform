import pytest
from phoenix_kernel.documents.structure_detector import detect_format
from phoenix_kernel.documents.name_detector import detect_name

_FORMAT1_LABELED = """
Tinta Acrílica Suvinil Toque de Seda 18L – A Elegância do Acabamento Acetinado
[DADOS ESTRUTURADOS PARA O ERP] NCM: 32091010 | CEST: 2400100 Altura (cm): 34,8
Argamassa AC3 Quartzolit Cimentcola Flexível 20kg – A Força do Porcelanato
[DADOS ESTRUTURADOS PARA O ERP] NCM: 38245000 | CEST: 1000100 Altura (cm): 45,0
Tinta Acrílica Coral Rende Muito 18L – O Poder da Ultra-Diluição
[DADOS ESTRUTURADOS PARA O ERP] NCM: 32091010 | CEST: 2400100 Altura (cm): 34,8
"""
_FORMAT2_NUMBERED = """
63. Cachaça São Francisco 970ml
NCM: 22084000
Peso: 0.970
64. Cerveja Antarctica Pilsen 300ml
NCM: 22030000
Peso: 0.300
65. Refrigerante Sukita Laranja 350ml
NCM: 22021000
Peso: 0.350
"""

def _extract_names(text):
    result=detect_format(text)
    names=[]
    for block in result.blocks:
        ev=detect_name(block)
        if ev: names.append(ev.value)
    return names

def test_same_code_extracts_from_two_formats():
    names1=_extract_names(_FORMAT1_LABELED)
    names2=_extract_names(_FORMAT2_NUMBERED)
    assert any("Suvinil" in n for n in names1)
    assert any("Argamassa" in n for n in names1)
    assert any("Coral" in n for n in names1)
    assert any("Cachaça" in n for n in names2)
    assert any("Cerveja" in n for n in names2)
    assert any("Refrigerante" in n for n in names2)
    assert len(names1)>=3
    assert len(names2)>=3
