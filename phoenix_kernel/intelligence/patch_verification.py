"""
phoenix_kernel/intelligence/patch_verification.py

PHX-NEW (2026-08-22, achado real do usuário): no teste real de colaboração
CPU+GPU sobre um bug de performance concreto (`buscar_usuario` reprocessando
uma lista inteira a cada chamada em vez de cachear), o modelo da GPU propôs
"correções" em 6 rodadas seguidas que NUNCA resolviam o bug de verdade - o
`cache = {}` continuava declarado DENTRO do corpo da função, sendo recriado
e descartado a cada chamada, então a segunda chamada continuava tão lenta
quanto a primeira. Cada rodada só reescrevia a explicação em texto com mais
confiança ("isso vai melhorar significativamente a performance"), sem que
ninguém - nem o outro modelo, nem o sistema - checasse se isso era verdade.

Este módulo existe pra resolver exatamente esse ponto: rodar o código
proposto DE VERDADE, num SUBPROCESSO isolado com timeout curto (nunca
`exec()` no processo principal - o código vem de um modelo de IA local
rodando sem supervisão humana rodada a rodada, então mesmo sem intenção
maliciosa um bug de loop infinito ou recursão descontrolada não pode travar
o `dual_collab.py` inteiro), e devolver um veredito objetivo (baseado em
tempo de execução medido, não na opinião de nenhum dos dois modelos) pra ser
injetado no histórico da PRÓXIMA rodada como fato.

ESCOPO HONESTO (não é um verificador universal de "qualquer código"): isso
cobre especificamente a classe de bug que apareceu no teste real do
usuário - uma função de duas posições, tipo `f(lista_de_registros, chave)`,
que deveria ficar mais rápida numa SEGUNDA chamada com a MESMA chave (sinal
de cache/memoização funcionando). Detecta e roda quando: (1) o TEMA da
colaboração contém a definição da função original (`def nome(...)`), e (2)
a rodada mais recente propõe um bloco de código Python que redefine essa
mesma função. Fora desse formato (funções com outra assinatura, tarefas que
não são sobre performance de busca), `verify_lookup_cache_patch()` devolve
`None` - nenhuma alegação é feita fora do que este módulo consegue checar de
verdade.

PHX-FIX (2026-08-22, revisão do usuário sobre os dois pontos que ele pediu
pra conferir no código, não só na descrição):

1) "10s de timeout é suficiente mesmo em hardware mais lento?" - sim, e o
   motivo importa: o timeout NÃO cobre inferência de modelo nenhuma (o
   subprocesso nunca chama o llama-server) - ele só mede o tempo de rodar
   uma função Python simples de busca numa lista de
   `_LOOKUP_RECORD_COUNT` registros, duas vezes. Medido no ambiente de
   teste desta entrega, uma busca linear de pior caso (sem cache nenhum,
   exatamente o bug real do usuário) levou ~6-8ms - mesmo um Xeon E5-2690 v3
   (bem mais antigo) sendo várias vezes mais lento pra isso ainda ficaria na
   casa dos milissegundos, não segundos. O timeout só dispara de verdade em
   dois casos: um loop infinito genuíno (o resultado CORRETO nesse caso é
   reportar falha, não um falso positivo) ou uma "correção" que trocou o
   algoritmo por outra coisa muito mais cara - também um sinal real, não
   ruído de medição.

2) "subprocesso isolado não é sandbox completo - ele herda rede/filesystem
   do processo principal?" - correto, e essa era uma lacuna real: antes,
   `asyncio.create_subprocess_exec` não restringia nada além de rodar num
   processo à parte (proteção contra travar/derrubar o `dual_collab.py`,
   NUNCA proteção contra código malicioso). Duas mitigações adicionadas
   agora, sendo honesto sobre o que cada uma cobre e o que não cobre:
     - `_looks_dangerous()` recusa rodar o código ANTES de sequer escrever o
       arquivo/abrir o subprocesso, se ele contiver import ou chamada de
       módulos de risco óbvio (`os`, `subprocess`, `socket`, `shutil`,
       `sys`, `ctypes`, `eval`/`exec`, abrir arquivo em modo escrita, etc.)
       - e também idiomas de introspecção via dunder (`__builtins__`,
       `__globals__`, `__subclasses__`, `__bases__`) usados no truque
       clássico de contornar um bloqueio de nome direto, tipo
       `getattr(__builtins__, 'eval')(...)` (achado real de revisão do
       usuário: um `eval(`/`exec(` literal é pego, mas essa forma
       alternativa não continha nenhum desses dois textos - PHX-FIX
       adicionado). Isso continua sendo uma lista de bloqueio, NÃO uma
       sandbox de verdade - um ataque deliberado e persistente sempre
       consegue inventar mais uma variante de ofuscação que o texto atual
       não cobre (é uma corrida sem fim por definição, uma lista de
       bloqueio nunca "fecha" a classe inteira). O modelo de ameaça aqui é
       "modelo local pequeno/quantizado alucinando uma 'correção' que por
       acidente inclui uma chamada destrutiva ou reproduz um idioma de
       'truque avançado' que viu em algum texto de treino" - não "atacante
       humano deliberado escrevendo ofuscação sob medida pra escapar desta
       checagem específica". Pra esse cenário realista, a checagem é uma
       rede de segurança honesta; NÃO tratar isso como se fechasse a classe
       inteira de bypass possível.
     - O subprocesso agora roda com um `env` mínimo (não herda as variáveis
       de ambiente inteiras do processo principal, que podem conter chaves
       de API de busca web etc.) - reduz o que haveria pra vazar mesmo que
       a checagem acima fosse contornada.
   Isolamento forte de verdade (usuário/processo sem privilégios, limite de
   CPU/memória do SO, sem acesso a rede nenhum) exigiria mecanismos
   específicos de plataforma (cgroups/seccomp no Linux, Job Objects no
   Windows - que é onde a Phoenix realmente roda) e fica fora do escopo
   desta correção; se quiser isso implementado de verdade, vale pedir como
   item separado.

3) PHX-NEW (2026-08-22, "pesquisar e replicar" - pedido explícito do
   usuário depois de descobrir que o padrão "múltiplos agentes + execução
   real de código" já é área estabelecida, tipo AutoGen/CrewAI/LangGraph):
   `_looks_dangerous()` foi reescrita de regex/texto pra análise de AST
   (Abstract Syntax Tree - a árvore sintática real do código Python, via
   `ast.parse()`, biblioteca padrão, sem dependência nova). Motivo
   confirmado por pesquisa real (não suposição): o repositório do AutoGen
   (Microsoft) tem uma discussão pública de um contribuidor externo
   ("VAREK", github.com/microsoft/autogen discussion #7595 - IMPORTANTE
   ser preciso aqui: é uma discussão pública em andamento, NÃO uma mudança
   já oficial/lançada pelo time do AutoGen) propondo exatamente essa troca,
   com o mesmo raciocínio: regex/denylist de texto vaza por ofuscação
   (aliasing de import, formatação diferente), AST enxerga a ESTRUTURA
   real do código. Concretamente, isso fecha uma lacuna que a versão
   anterior baseada em regex tinha: `import os as sistema` seguido de
   `sistema.system(...)` não continha o texto `os\.\w+\(` em lugar nenhum
   (o padrão antigo só reconhecia o nome literal do módulo colado no
   texto) - a árvore AST sabe que `sistema` É o módulo `os` de verdade,
   independente do alias escolhido. A ressalva do item 2 acima continua
   valendo palavra por palavra: isto é uma lista de bloqueio estrutural,
   ainda não uma sandbox - só ficou mais difícil de escapar por acidente
   ou por ofuscação simples.

4) PHX-FIX (2026-08-22, achado real de auditoria de código, depois de
   confirmar que a fiação `resident_manager.py` -> `dual_collab.py` ->
   `patch_verification.py` estava correta de ponta a ponta e mesmo assim
   nenhum veredito objetivo aparecia na tela real da Arena): o campo de
   tema no frontend (`ArenaView.tsx`) era um `<input type="text">` - e um
   `<input>` de HTML É INCAPAZ de guardar qualquer caractere de quebra de
   linha, sempre (não é bug de navegador específico, é como o elemento
   funciona por definição). Ao colar ou digitar um tema multi-linha (como
   o do teste real: uma frase seguida de `def buscar_usuario(...):` com o
   corpo da função em linhas indentadas), o navegador cola tudo numa linha
   só, sem inserir espaço nenhum entre as linhas originais - o texto que
   de fato chegava neste módulo era algo como "...proponha uma
   correção:def buscar_usuario(lista_usuarios, id_alvo):    for u in
   lista_usuarios:...", sem NENHUMA quebra de linha sobrando.
   `FUNCTION_DEF_PATTERN` antiga (`^\s*def...`, com `re.MULTILINE`)
   dependia de existir uma posição de início-de-linha real antes de "def"
   pra reconhecer a função - com o texto colado numa linha só, essa
   posição nunca existia (exceto no início absoluto da string, que não é
   onde "def" ficava), então `extract_function_name(topic)` devolvia
   `None` SEMPRE que o tema vinha da Arena, e `verify_lookup_cache_patch()`
   retornava `None` já na primeira linha - a verificação nunca rodava, em
   silêncio, apesar de toda a fiação estar certa. Duas correções, uma em
   cada ponta (as duas juntas, não uma OU outra):
     - Aqui: `FUNCTION_DEF_PATTERN` trocou `^\s*def` (âncora de início de
       linha) por `\bdef` (fronteira de palavra) - continua reconhecendo
       `def nome(...)` normalmente, mas não depende mais de nenhuma quebra
       de linha ter sobrevivido no texto.
     - No frontend (`ArenaView.tsx`): o `<input type="text">` do tema virou
       um `<textarea>` de verdade - agora o usuário CONSEGUE digitar ou
       colar texto multi-linha (incluindo código com indentação) sem o
       navegador destruir a formatação. Ver LEIA-ME desta entrega pro
       detalhe completo e a prova em teste de cada lado.
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# PHX-FIX (2026-08-22, pesquisa real motivada pela revisão do usuário sobre
# o bypass `getattr(__builtins__, 'eval')(...)`): a versão anterior usava
# regex/denylist de TEXTO - pesquisei se esse é um problema conhecido em
# frameworks profissionais do mesmo tipo (múltiplos agentes de LLM rodando
# código proposto), e é: o próprio repositório do AutoGen (Microsoft) tem
# uma discussão pública ("VAREK", github.com/microsoft/autogen discussion
# #7595) propondo endurecer a execução de código local exatamente trocando
# checagem por regex/padrão de texto por análise de AST (Abstract Syntax
# Tree) - a árvore sintática real do código, não o texto bruto. É uma
# proposta de contribuidor externo em discussão pública, não uma mudança já
# oficial/lançada pelo time do AutoGen - mas o raciocínio técnico é sólido e
# se aplica aqui: AST enxerga a ESTRUTURA do código (é um import de verdade,
# é uma chamada de verdade), então não importa quantos espaços, aliases
# (`import os as sistema` - o nome real do módulo continua "os" na árvore,
# mesmo que o texto bruto diga "sistema") ou formatação diferente o código
# use - o que a versão anterior baseada em regex podia perder. Continua
# sendo uma lista de bloqueio (nomes de módulo/atributo proibidos), não uma
# sandbox de verdade - a ressalva completa da docstring do módulo continua
# valendo integralmente.
_DANGEROUS_MODULES = {
    "os", "subprocess", "socket", "shutil", "sys", "ctypes",
    "ftplib", "smtplib", "winreg", "multiprocessing",
}
_DANGEROUS_DUNDER_NAMES = {"__builtins__", "__globals__", "__subclasses__", "__bases__", "__import__"}
_DANGEROUS_CALL_NAMES = {"eval", "exec", "__import__"}
_WRITE_MODES = {"w", "a", "x", "w+", "a+", "x+", "wb", "ab", "xb"}


def _looks_dangerous(code: str) -> str | None:
    """Devolve uma descrição do que foi encontrado, ou None se o código
    parecer seguro pra rodar isolado (ver ressalva na docstring do módulo:
    isto é uma lista de bloqueio - agora estrutural via AST, não mais texto
    bruto -, não uma sandbox real). Se o código nem chega a ter uma AST
    válida (erro de sintaxe), não é este o lugar certo pra reportar isso -
    devolve None e deixa a execução real (que já trata sintaxe quebrada)
    reportar o erro de verdade."""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_module = alias.name.split(".")[0]
                if root_module in _DANGEROUS_MODULES:
                    return f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else "")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in _DANGEROUS_MODULES:
                return f"from {node.module} import ..."
        elif isinstance(node, ast.Name) and node.id in _DANGEROUS_DUNDER_NAMES:
            return node.id
        elif isinstance(node, ast.Attribute) and node.attr in _DANGEROUS_DUNDER_NAMES:
            return node.attr
        elif isinstance(node, ast.Call):
            func = node.func
            func_name = func.id if isinstance(func, ast.Name) else (func.attr if isinstance(func, ast.Attribute) else None)
            if func_name in _DANGEROUS_CALL_NAMES:
                return f"{func_name}(...)"
            if func_name == "open" and len(node.args) >= 2:
                mode_arg = node.args[1]
                if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str) and mode_arg.value in _WRITE_MODES:
                    return f"open(..., '{mode_arg.value}')"
    return None


CODE_BLOCK_PATTERN = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
# PHX-FIX (2026-08-22, achado real de auditoria: o campo de tema da Arena no
# frontend - ArenaView.tsx - era um <input type="text"> comum, e um
# <input> de HTML NUNCA guarda quebra de linha nenhuma (\n) - o navegador
# apaga toda quebra de linha ao colar/digitar texto multi-linha, GRUDANDO
# as linhas sem inserir espaço nenhum no lugar. Isso significa que o TEMA
# de verdade que chegava até este módulo, no teste real do usuário, nunca
# tinha a quebra de linha que o padrão antigo `^\s*def` (MULTILINE) exigia
# pra reconhecer onde uma linha de código começa - "...uma correção:def
# buscar_usuario(...)" (sem nada entre ":" e "def") nunca batia com
# "^\s*def" porque não existe posição de início-de-linha ali (não há "\n"
# nenhum sobrando no texto). Resultado prático: `extract_function_name()`
# devolvia `None` pro tema em TODA colaboração iniciada pela Arena, e
# `verify_lookup_cache_patch()` retornava `None` na primeira linha - a
# verificação objetiva nunca rodava, silenciosamente, mesmo com toda a
# fiação (dual_collab.py + resident_manager.py) 100% correta. Trocamos
# `^\s*def` (dependia de linha própria) por `\bdef` (fronteira de palavra -
# funciona colado a qualquer caractere que não seja letra/dígito/underline,
# incluindo ":" logo antes de "def") - continua reconhecendo definições de
# função normais, mas não depende mais de quebra de linha nenhuma
# sobreviver. A correção de verdade (deixar o usuário digitar/colar texto
# multi-linha sem que o navegador destrua as quebras) é separada, no
# ArenaView.tsx (troca de <input> por <textarea>) - as duas juntas fecham
# o problema: o texto chega intacto E, mesmo que chegue mutilado de algum
# outro jeito no futuro, o reconhecimento da função não depende mais disso.
FUNCTION_DEF_PATTERN = re.compile(r"\bdef\s+(\w+)\s*\(([^)]*)\)")

# Registros suficientes pra tornar uma busca linear (O(n), sem cache) MUITO
# mais lenta que um lookup de dicionário (O(1), com cache de verdade) de um
# jeito mensurável mesmo em hardware modesto - mas pequeno o bastante pra
# rodar em milissegundos, não segundos, mesmo no pior caso.
_LOOKUP_RECORD_COUNT = 300_000
_SUBPROCESS_TIMEOUT_S = 10.0
# Segunda chamada precisa ser bem mais rápida (não só "um pouco") pra contar
# como cache confirmado de verdade - evita falso-positivo por ruído de
# medição (GC, agendamento do SO, etc.).
_SPEEDUP_RATIO_THRESHOLD = 0.4  # segunda chamada precisa ser < 40% do tempo da primeira

_HARNESS_TEMPLATE = '''
import json
import sys
import time
import inspect

CODE_PATH = sys.argv[1]
FUNCTION_NAME = sys.argv[2]

result = {{"ok": False, "error": None, "code_executed": False, "function_found": False,
           "first_call_ms": None, "second_call_ms": None,
           "same_result_both_calls": None}}

try:
    with open(CODE_PATH, "r", encoding="utf-8") as f:
        source = f.read()
    namespace = {{}}
    exec(compile(source, "<patch_proposto>", "exec"), namespace)
    result["code_executed"] = True
except Exception as exc:
    result["error"] = f"código não executou (provável alucinação/sintaxe quebrada): {{type(exc).__name__}}: {{exc}}"
    print(json.dumps(result))
    sys.exit(0)

func = namespace.get(FUNCTION_NAME)
if func is None or not callable(func):
    result["error"] = f"a rodada não definiu uma função chamada '{{FUNCTION_NAME}}' (mesma da função original) - nada pra verificar"
    print(json.dumps(result))
    sys.exit(0)

result["function_found"] = True

try:
    sig = inspect.signature(func)
    n_params = len(sig.parameters)
except (TypeError, ValueError):
    n_params = 2

if n_params < 2:
    result["error"] = f"função '{{FUNCTION_NAME}}' tem {{n_params}} parâmetro(s) - esperado 2 (lista, chave), não dá pra montar chamada de teste"
    print(json.dumps(result))
    sys.exit(0)

lista_teste = [{{"id": i}} for i in range({_record_count})]
alvo = {_record_count} - 1  # pior caso pra busca linear: último elemento da lista

try:
    t0 = time.perf_counter()
    r1 = func(lista_teste, alvo)
    t1 = time.perf_counter()
    r2 = func(lista_teste, alvo)
    t2 = time.perf_counter()
except Exception as exc:
    result["error"] = f"função '{{FUNCTION_NAME}}' levantou exceção ao ser chamada com dados de teste reais: {{type(exc).__name__}}: {{exc}}"
    print(json.dumps(result))
    sys.exit(0)

result["ok"] = True
result["first_call_ms"] = (t1 - t0) * 1000.0
result["second_call_ms"] = (t2 - t1) * 1000.0
result["same_result_both_calls"] = (r1 == r2)
print(json.dumps(result))
'''


@dataclass
class ObjectiveVerdict:
    checked: bool
    function_name: str
    speedup_confirmed: bool | None  # None quando checked=False ou houve erro
    detail: str


def extract_python_code_block(text: str) -> str | None:
    """Extrai o ÚLTIMO bloco ```python ... ``` (ou ``` genérico) do texto -
    é o mais provável de ser a versão final da rodada, já que os modelos
    tendem a reescrever o bloco inteiro a cada rodada em vez de só mostrar
    um diff (ver LEIA-ME da entrega sobre isso ser um problema separado,
    ainda não resolvido nesta entrega)."""
    matches = CODE_BLOCK_PATTERN.findall(text or "")
    if not matches:
        return None
    return matches[-1].strip() or None


def extract_function_name(text: str) -> str | None:
    """Primeiro `def nome(a, b)` encontrado no texto - usado hoje só no TEMA
    original, pra achar o nome da função com bug (a checagem de se o código
    de uma rodada redefine essa MESMA função é feita à parte, com um
    `in code` simples em `verify_lookup_cache_patch()`). PHX-FIX: usa
    fronteira de palavra (`\\bdef`), não âncora de início de linha - ver nota
    completa em `FUNCTION_DEF_PATTERN` acima sobre o bug real que isso
    corrigiu (tema chegando sem quebra de linha nenhuma vindo de um
    `<input>` de HTML)."""
    match = FUNCTION_DEF_PATTERN.search(text or "")
    return match.group(1) if match else None


async def _run_harness_subprocess(code: str, function_name: str) -> dict:
    harness_source = _HARNESS_TEMPLATE.format(_record_count=_LOOKUP_RECORD_COUNT)
    with tempfile.TemporaryDirectory(prefix="phoenix_patch_verify_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        code_file = tmp_path / "patch_proposto.py"
        harness_file = tmp_path / "harness.py"
        code_file.write_text(code, encoding="utf-8")
        harness_file.write_text(harness_source, encoding="utf-8")

        try:
            # PHX-NEW: env mínimo (não o os.environ inteiro do processo
            # principal) - reduz o que um código proposto poderia ler/vazar
            # mesmo que a checagem de _looks_dangerous() fosse contornada.
            # PATH precisa continuar presente pro próprio Python resolver
            # bibliotecas padrão do sistema operacional.
            minimal_env = {"PATH": os.environ.get("PATH", "")}
            if os.name == "nt":
                # PHX-FIX: no Windows (onde a Phoenix roda de verdade),
                # remover SYSTEMROOT quebra o próprio interpretador Python
                # ao iniciar (várias DLLs do runtime dependem disso) -
                # mínimo necessário, ainda bem mais restrito que o
                # os.environ inteiro do processo principal.
                minimal_env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(harness_file), str(code_file), function_name,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                env=minimal_env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_SUBPROCESS_TIMEOUT_S)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                # PHX-FIX (2026-08-22, achado real de revisão do usuário):
                # a mensagem antiga cravava "possível loop infinito" como se
                # fosse a única explicação - mas o timeout mede tempo total,
                # não SE é um loop infinito ou só um algoritmo genuinamente
                # mais caro (ex: O(n²) por engano) rodando devagar de
                # verdade num registro de 300 mil itens. As duas situações
                # merecem reportar falha (nenhuma das duas é "confirmado
                # mais rápido"), mas a explicação não devia afirmar a causa
                # com mais certeza do que o teste realmente tem.
                return {"ok": False, "error": (
                    f"código não terminou dentro de {_SUBPROCESS_TIMEOUT_S:.0f}s isolado num "
                    f"subprocesso separado - pode ser um loop infinito genuíno, ou pode ser um "
                    f"algoritmo genuinamente mais caro que o esperado (ex: complexidade maior por "
                    f"engano) - qualquer um dos dois casos não é 'ficou mais rápido', então não é "
                    f"aceito como correção confirmada de qualquer forma"
                )}
        except Exception as exc:
            return {"ok": False, "error": f"não foi possível rodar o subprocesso de verificação: {exc}"}

        if not stdout.strip():
            err_text = (stderr or b"").decode("utf-8", errors="replace").strip()
            return {"ok": False, "error": f"subprocesso não devolveu resultado (código pode ter travado o interpretador) - stderr: {err_text[-300:] if err_text else '(vazio)'}"}
        try:
            return json.loads(stdout.decode("utf-8", errors="replace").strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError) as exc:
            return {"ok": False, "error": f"resultado do subprocesso não é JSON válido: {exc}"}


async def verify_lookup_cache_patch(topic: str, turn_text: str) -> str | None:
    """Ponto de entrada usado por dual_collab.py (injetado como `verify_fn`).
    Devolve uma frase pronta pra entrar no histórico como FATO (resultado
    real de execução, nunca opinião de um dos modelos) ou `None` quando o
    formato da tarefa está fora do escopo que este módulo sabe checar (ver
    docstring do módulo) - nesse caso, dual_collab.py simplesmente não
    injeta nenhuma nota, sem alegar nada que não foi verificado."""
    original_function_name = extract_function_name(topic)
    if not original_function_name:
        return None
    code = extract_python_code_block(turn_text)
    if not code:
        return None
    if original_function_name not in code:
        # A rodada nem menciona a função original - provavelmente não é uma
        # proposta de correção dela (pode ser análise em texto, outro
        # trecho de código, etc.) - não força um veredito fora de contexto.
        return None

    dangerous_hit = _looks_dangerous(code)
    if dangerous_hit:
        # PHX-NEW: recusa mesmo rodar isolado - ver ressalva completa na
        # docstring do módulo sobre o que esta checagem cobre (alucinação
        # acidental) e o que não cobre (ataque deliberado sofisticado).
        return (
            f"VERIFICAÇÃO OBJETIVA (código executado de verdade, não opinião): "
            f"PULADA POR SEGURANÇA - o código proposto contém uma operação que não "
            f"tem nada a ver com buscar/cachear numa lista ('{dangerous_hit}') - não foi "
            f"executado, nem isolado em subprocesso, por precaução."
        )

    raw = await _run_harness_subprocess(code, original_function_name)

    if not raw.get("ok"):
        error = raw.get("error", "motivo desconhecido")
        # PHX-FIX (bug achado rodando o próprio teste antes de entregar): um
        # código com erro de SINTAXE também chega aqui com function_found=False
        # (o exec() nem roda, então a função nunca é definida) - a versão
        # anterior confundia isso com "não é sobre essa função" e devolvia
        # None (silêncio) em vez de reportar a falha real. Só é "fora de
        # escopo, sem alegação" quando o código RODOU (code_executed=True) e
        # mesmo assim não definiu a função - aí sim pode ser outra coisa
        # (análise em texto, código de outro trecho, etc.), não uma tentativa
        # de correção quebrada.
        if raw.get("code_executed") is True and raw.get("function_found") is False:
            return None
        return (
            f"VERIFICAÇÃO OBJETIVA (código executado de verdade, não opinião): "
            f"o código proposto NÃO RODOU corretamente - {error}"
        )

    first_ms = raw["first_call_ms"]
    second_ms = raw["second_call_ms"]
    same_result = raw["same_result_both_calls"]
    speedup_confirmed = (
        same_result
        and first_ms > 0
        and (second_ms / first_ms) < _SPEEDUP_RATIO_THRESHOLD
    )

    if speedup_confirmed:
        return (
            f"VERIFICAÇÃO OBJETIVA (código executado de verdade, não opinião): CONFIRMADO - "
            f"'{original_function_name}' ficou genuinamente mais rápida na 2ª chamada com a "
            f"mesma chave ({first_ms:.2f}ms -> {second_ms:.2f}ms, resultado idêntico nas duas "
            f"chamadas) - o cache/memoização está funcionando de verdade."
        )
    return (
        f"VERIFICAÇÃO OBJETIVA (código executado de verdade, não opinião): NÃO CONFIRMADO - "
        f"'{original_function_name}' rodou sem erro, mas a 2ª chamada com a MESMA chave não "
        f"ficou significativamente mais rápida que a 1ª ({first_ms:.2f}ms -> {second_ms:.2f}ms"
        + ("" if same_result else ", e o resultado nem bateu entre as duas chamadas")
        + ") - isso indica que o cache/memoização proposto NÃO está persistindo entre chamadas "
        "(sinal clássico de cache declarado DENTRO do corpo da função, recriado a cada chamada)."
    )
