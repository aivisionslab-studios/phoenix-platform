"""
Teste pro achado real do usuário 2026-08-24: "verificar e aumentar
contexto de caracteres ou deixar em aberto pra livre resposta de cada
modelo" - depois de ver uma resposta do chat demorar mais que outra
(qwen3-8b, 4.6 tok/s numa pergunta de acompanhamento depois de uma busca
na web real).

Investigação real (não suposição): a diferença de velocidade entre as duas
mensagens do screenshot era esperada (a primeira só mostrava o resultado
cru da busca, sem nenhuma chamada ao modelo; a segunda era inferência real
do qwen3-8b em CPU pura, ~4.6 tok/s é uma taxa plausível pra um modelo de
8B nesse hardware) - não achei evidência de truncamento nessa resposta
específica (ela termina com uma nota final coerente, não corta no meio).

Mas achei um risco real e verificável: `phoenix_kernel/runtime/drivers/
llama_cpp.py` iniciava o llama-server com `-c 8192` (contexto FIXO de 8192
tokens). Corrigido pra 16384 na época.

PHX-UPDATE (2026-09-06, MESMO achado recorrendo): usuário relatou de novo
"qualquer resposta do modelo... fica cortada". Investigação confirmou por
que 16384 não bastou pra sempre: NÃO existe nenhum corte/trim do histórico
de conversa em lugar nenhum do projeto - cada mensagem reenvia a conversa
INTEIRA (sendToProvider() em AviaryApp.tsx). Uma conversa longa o
suficiente sempre acaba esbarrando de novo no teto, não importa o quão
alto - só empurra o problema pra mais tarde (o corte de histórico
continuaria sendo o próximo passo mais robusto se o sintoma voltar depois
desta segunda rodada). Contexto aumentado de novo, de 16384 pra 32768
(dobro), a pedido explícito do usuário depois de confirmar o trade-off de
RAM (máquina tem 32GB).

Segunda parte do pedido do usuário ("deixar livre pra modelo ter liberdade
de escrita"): o chat normal nunca tinha o equivalente ao
`unlimited_output` que a criação de documentos já usa - sempre mandava um
teto de max_tokens (2048 se o front-end não mandasse nada). Adicionado um
checkbox "Sem limite" em ParametersDrawer.tsx (maxTokens=0 como sinal) que
faz o server.ts OMITIR o campo max_tokens da requisição - o modelo para
sozinho por EOS ou fim físico do contexto, nunca por um teto arbitrário.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LLAMA_CPP_SRC = (_ROOT / "phoenix_kernel" / "runtime" / "drivers" / "llama_cpp.py").read_text(encoding="utf-8")
_AVIARY_APP_SRC = (_ROOT / "platform_source" / "src" / "components" / "aviary" / "AviaryApp.tsx").read_text(encoding="utf-8")
_SERVER_TS_SRC = (_ROOT / "platform_source" / "server.ts").read_text(encoding="utf-8")
_PARAMETERS_DRAWER_SRC = (_ROOT / "platform_source" / "src" / "components" / "aviary" / "ParametersDrawer.tsx").read_text(encoding="utf-8")


def _extract_ctx_flag_value(src: str) -> str:
    m = re.search(r"context_size:\s*int\s*=\s*(\d+)", src)
    assert m, "esperava achar o default de 'context_size' no construtor do LlamaCppDriver"
    assert "'-c', str(self._context_size)" in src or '"-c", str(self._context_size)' in src, (
        "esperava achar a flag '-c' usando self._context_size em _build_server_args"
    )
    return m.group(1)


def test_llama_server_context_size_is_32768():
    ctx = _extract_ctx_flag_value(_LLAMA_CPP_SRC)
    assert ctx == "32768", (
        f"esperava default de context_size=32768 (dobro da rodada anterior, pedido "
        f"explícito do usuário depois de confirmar o trade-off de RAM), achei {ctx}"
    )


def test_llama_server_launch_command_has_no_leftover_old_values():
    # Prova que não sobrou uma segunda referência a um valor antigo (8192 ou
    # 16384) perto da montagem do comando - dos dois aumentos de contexto já
    # feitos neste projeto.
    launch_block_match = re.search(
        r"def _build_server_args\(.*?\n(.*?)\n    @property",
        _LLAMA_CPP_SRC, re.DOTALL,
    )
    assert launch_block_match, "esperava achar o corpo de _build_server_args()"
    launch_block = launch_block_match.group(1)
    assert "8192" not in launch_block, f"o bloco de montagem de args ainda referencia um valor antigo (8192): {launch_block}"
    assert "16384" not in launch_block, f"o bloco de montagem de args ainda referencia um valor antigo (16384): {launch_block}"
    assert "context_size" in launch_block


def test_aviary_frontend_context_window_uses_real_llama_server_value():
    m = re.search(
        r"contextWindow:\s*p\.type === 'gemini' \? 1000000 : p\.type === 'llama-server' \? (\d+) : \d+",
        _AVIARY_APP_SRC,
    )
    assert m, "esperava um ramo específico pra 'llama-server' na expressão de contextWindow em AviaryApp.tsx"
    assert m.group(1) == "32768", (
        "o contextWindow exibido pro llama-server precisa bater com o valor real "
        "de lançamento (-c 32768 em llama_cpp.py), não um número arbitrário"
    )


def test_aviary_frontend_no_longer_claims_128000_for_llama_server_unconditionally():
    old_pattern = r"contextWindow:\s*p\.type === 'gemini' \? 1000000 : 128000,"
    assert not re.search(old_pattern, _AVIARY_APP_SRC), (
        "a expressão antiga (128000 fixo pra qualquer provedor local, sem distinguir "
        "llama-server) ainda está presente - o achado não foi corrigido de verdade"
    )


def test_chat_max_tokens_zero_means_unlimited_and_is_omitted_from_payload():
    """PHX-NEW (2026-09-06): maxTokens=0 (o checkbox "Sem limite" do
    ParametersDrawer) tem que fazer o server.ts OMITIR max_tokens da
    requisição - nunca mandar "max_tokens: 0" literal (a maioria dos
    servidores OpenAI-compatible trata isso como erro ou "gerar zero
    tokens", o oposto do que o usuário pediu)."""
    assert "maxTokens === 0" in _SERVER_TS_SRC or "maxTokens !== 0" in _SERVER_TS_SRC, (
        "esperava lógica tratando maxTokens===0 como sinal de 'sem limite' em server.ts"
    )
    assert 'max_tokens: 0' not in _SERVER_TS_SRC.replace(" ", ""), (
        "server.ts não pode mandar 'max_tokens: 0' literal pro llama-server - "
        "isso pede zero tokens de saída, o oposto de 'sem limite'"
    )


def test_parameters_drawer_has_unlimited_checkbox():
    assert "maxTokens === 0" in _PARAMETERS_DRAWER_SRC, (
        "esperava o checkbox 'Sem limite' em ParametersDrawer.tsx usando "
        "maxTokens===0 como sinal, consistente com o que server.ts espera"
    )
