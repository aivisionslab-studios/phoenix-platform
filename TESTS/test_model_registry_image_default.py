"""Regressão: SDXL, não Flux, é o default de image_generation.

PHX-FIX (auditoria Claude, 2026-09-05): catalog/models.json tinha o "flux"
com default_for_roles=["image_generation"] e o "sdxl" com nota explícita
"não é default (Flux é)" — contradizendo phoenix_kernel/models/health.py
(cujo default já era sdxl) e a conclusão de duas investigações independentes
de que o Flux crasha de forma nativa e reproduzível (0xC0000005) em TODOS os
4 placements de fallback nesta GPU (RX 580), não corrigível via configuração.
Esse descompasso era a causa real de instalações novas ainda baixarem e usar
Flux por padrão, mesmo com health.py "correto".
"""
from phoenix_kernel.models.registry import ModelRegistry


def test_image_generation_default_is_sdxl_not_flux():
    reg = ModelRegistry("catalog/models.json")
    resolved = reg.resolve("image_generation")
    assert resolved is not None
    assert resolved.id == "sdxl"
    assert resolved.id != "flux"


def test_flux_still_selectable_by_explicit_hint():
    """Flux continua disponível pra quem escolher manualmente — só não é
    mais o default automático."""
    reg = ModelRegistry("catalog/models.json")
    resolved = reg.resolve("image_generation", hint="flux")
    assert resolved is not None
    assert resolved.id == "flux"
