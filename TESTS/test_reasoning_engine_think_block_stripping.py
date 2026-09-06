# TESTS/test_reasoning_engine_think_block_stripping.py
#
# PHX-NEW (achado real do usuário 2026-08-28, na sequência do fix de
# timeout: depois do timeout ser corrigido, a mesma tela passou a mostrar
# "O modelo não devolveu um JSON válido mapeando os dados, mesmo após 2
# tentativa(s). Nenhum arquivo foi preenchido.").
#
# Causa raiz: qwen3-8b é um modelo "thinking" - produz um preâmbulo
# <think>...</think> antes da resposta final. _extract_json_object()
# não sabia disso, o que criava DOIS jeitos de falhar:
#   1. Se o raciocínio mencionar uma chave '{' (ex: o modelo "pensando em
#      voz alta" sobre como o JSON deveria ficar), _extract_balanced_braces()
#      pega esse trecho de DENTRO do <think> em vez do JSON real que vem
#      depois.
#   2. Com max_tokens baixo, o modelo podia gastar o orçamento inteiro
#      pensando e nunca chegar a emitir o JSON de verdade.
#
# Este arquivo prova especificamente o item (1): que _strip_think_block()/
# _extract_json_object() ignoram qualquer '{' mencionado dentro do bloco de
# raciocínio e extraem só o JSON real que vem depois dele. O item (2)
# (max_tokens/"/no_think") é mitigado em resident_manager.py
# (fill_spreadsheet_template_direct) e não é testável aqui sem subir um
# llama-server de verdade.
#
# Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from phoenix_kernel.intelligence.reasoning_engine import (  # noqa: E402
    _extract_json_object,
    _strip_think_block,
)


def test_extract_json_ignores_brace_mentioned_inside_think_block():
    text = (
        '<think>Deixa eu pensar... talvez eu devesse usar {"errado": true} '
        "como exemplo de estrutura, mas na verdade preciso usar as colunas "
        "certas do template.</think>"
        '{"sheet": "Dados", "rows": [{"preco": "10"}]}'
    )
    result = _extract_json_object(text)
    assert result == {"sheet": "Dados", "rows": [{"preco": "10"}]}


def test_extract_json_handles_think_block_with_no_braces_inside():
    text = (
        "<think>Vou analisar o documento-fonte e mapear cada campo pra "
        "coluna correspondente do template antes de responder.</think>\n"
        '{"sheet": "Planilha1", "rows": []}'
    )
    result = _extract_json_object(text)
    assert result == {"sheet": "Planilha1", "rows": []}


def test_extract_json_handles_fenced_json_after_think_block():
    text = (
        "<think>O usuário quer os dados em JSON dentro de um bloco de "
        "código, então vou formatar assim: {ainda pensando}.</think>\n"
        '```json\n{"sheet": "Dados", "rows": [{"nome": "Produto A"}]}\n```'
    )
    result = _extract_json_object(text)
    assert result == {"sheet": "Dados", "rows": [{"nome": "Produto A"}]}


def test_extract_json_returns_none_when_only_think_block_and_no_json():
    # Simula o pior caso do achado original: o modelo gastou todo o
    # orçamento de tokens pensando e nunca chegou a emitir JSON nenhum.
    # _extract_json_object() precisa devolver None de forma limpa (pra
    # plan_mission() decidir o retry), nunca inventar ou "vazar" um dict
    # de dentro do raciocínio.
    text = "<think>Estou pensando em como estruturar {isso: aqui} mas ainda não decidi..."
    result = _extract_json_object(text)
    assert result is None


def test_strip_think_block_removes_multiple_blocks_case_insensitively():
    text = "<THINK>primeiro bloco {x}</THINK> resposta real <think>segundo bloco {y}</think>"
    assert _strip_think_block(text) == "resposta real"


def test_strip_think_block_is_noop_when_there_is_no_think_tag():
    text = '{"sheet": "Dados", "rows": []}'
    assert _strip_think_block(text) == text
