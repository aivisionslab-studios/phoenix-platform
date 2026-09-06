"""Testes do buscador de EAN — pesquisa, valida, e exige auditoria humana."""
import asyncio

from phoenix_kernel.documents.barcode_finder import (
    apply_approved_eans, approve_ean, build_audit_queue,
    find_ean_for_product, validate_ean13, validate_ean8,
)


def test_ean13_checksum():
    assert validate_ean13("7894900011517")      # Coca-Cola real
    assert not validate_ean13("1234567890123")   # aleatório
    assert not validate_ean13("123")             # curto demais


def test_search_extracts_and_validates_candidates():
    async def fake(query):
        return [{"title": "X", "url": "u", "snippet": "EAN 7896045504831 e lixo 1234567890123"}]
    item = asyncio.run(find_ean_for_product("Heineken 330ml", "Produto", web_search=fake))
    codes = {c.code: c.valid_checksum for c in item.candidates}
    assert codes["7896045504831"] is True
    assert codes["1234567890123"] is False
    assert item.status == "pending_review"       # nunca auto-confirma
    assert item.product_type == "Produto"


def test_nothing_applied_without_human_approval():
    async def fake(query):
        return [{"title": "X", "url": "u", "snippet": "EAN 7896045504831"}]
    prods = [{"Descrição": "Heineken 330ml", "Código de Barras": ""}]
    queue = asyncio.run(build_audit_queue(prods, web_search=fake))
    # sem aprovar
    assert apply_approved_eans(prods, queue) == 0
    assert prods[0]["Código de Barras"] == ""
    # aprova e aplica
    assert approve_ean(queue[0], "7896045504831")
    assert apply_approved_eans(prods, queue) == 1
    assert prods[0]["Código de Barras"] == "7896045504831"


def test_approval_rejects_invalid_ean():
    async def fake(query):
        return [{"title": "X", "url": "u", "snippet": "7896045504831"}]
    prods = [{"Descrição": "P", "Código de Barras": ""}]
    queue = asyncio.run(build_audit_queue(prods, web_search=fake))
    assert not approve_ean(queue[0], "0000")     # checksum inválido -> recusa
    assert queue[0].status != "approved"


def test_skips_products_that_already_have_ean():
    calls = []
    async def fake(query):
        calls.append(query)
        return [{"title": "X", "url": "u", "snippet": "7896045504831"}]
    prods = [
        {"Descrição": "Sem EAN", "Código de Barras": ""},
        {"Descrição": "Com EAN", "Código de Barras": "7891000315507"},
    ]
    asyncio.run(build_audit_queue(prods, web_search=fake))
    assert len(calls) == 1                        # só pesquisou o sem EAN
