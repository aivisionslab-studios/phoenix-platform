"""
phoenix_kernel/intelligence/dual_collab.py

PHX-NEW (pedido do usuário 2026-08-22): colaboração real entre DOIS
modelos de texto - um roda inteiro na CPU, o outro inteiro na GPU via
Vulkan (nunca split de camadas entre os dois - ver
phoenix_kernel/models/hardware_fit.py para o bloqueio real de "cabe
inteiro ou não roda", e resident_manager.py::run_dual_model_collaboration_direct
para como cada lado é ligado a um motor de hardware específico).

Este módulo só conhece a LÓGICA PURA de turnos/busca/conclusão - não sabe
nada sobre llama-server, portas, VRAM, etc. (essas decisões de hardware
ficam em resident_manager.py, que injeta aqui só duas funções
"pergunte a um modelo" via `cpu_execute`/`gpu_execute`). Mesmo princípio
de separação já usado em documents/engine.py e models/health.py.

Busca na internet: o usuário pediu explicitamente "acesso a internet sem
restrições" - qualquer turno pode pedir uma busca real emitindo uma linha
sozinha `BUSCAR: <termo>`; como não existe tool-calling nativo no
llama-server local deste projeto, essa é a convenção textual mais simples
e confiável disponível hoje (ver LEIA-ME da entrega para mais detalhes e
o racional de por que não é uma limitação arbitrária).
"""
from __future__ import annotations

import difflib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

MAX_ROUNDS_DEFAULT = 6
# PHX-NOTE: limite por TURNO (não por colaboração inteira) - evita um
# único turno entrar num loop de "pedir busca -> não gostar do resultado
# -> pedir de novo" sem fim. "Sem restrições" (pedido do usuário) é sobre
# não limitar a QUANTIDADE de buscas úteis ao longo da colaboração toda -
# isso continua ilimitado (cada turno de cada rodada pode buscar até este
# limite, e há várias rodadas).
MAX_SEARCHES_PER_TURN = 3
# 20 minutos - uma colaboração real de verdade pode legitimamente levar
# tempo (CPU + GPU alternando, cada turno é uma inferência completa), mas
# não pode ser literalmente infinita.
TOTAL_TIME_BUDGET_SECONDS = 1200.0
TURN_EXECUTE_TIMEOUT_SECONDS = 240.0
# Exige pelo menos esta rodada completa (os dois lados já falaram mais de
# uma vez) antes de aceitar um sinal de conclusão - evita "terminar" já na
# primeira resposta de cada lado, o que não seria uma colaboração de
# verdade.
MIN_ROUNDS_BEFORE_CONCLUSION = 2

# PHX-FIX (2026-08-22, achado real do usuário - releu o transcript de uma
# colaboração de verdade linha por linha, em vez de aceitar "parece
# impressionante": Rodada 4 e Rodada 5 do lado GPU saíram quase idênticas,
# palavra por palavra, sobre o tópico aberto "ola"). Confirmado por
# inspeção de código (não só suposição) que os dois lados rodam em
# PROCESSOS REALMENTE SEPARADOS (porta 8081 compartilhada pro CPU, porta
# 8090 dedicada com --ngl 999 pro GPU - ver run_dual_model_collaboration_direct
# em resident_manager.py) - ou seja, não é o mesmo motor respondendo duas
# vezes por engano, é o MESMO modelo (do mesmo lado, duas rodadas depois)
# reciclando a própria resposta anterior porque o tópico parou de dar
# conteúdo novo pra render e não havia NENHUM critério que percebesse
# isso - o loop só pararia no limite de rodadas (max_rounds) ou num sinal
# explícito de conclusão que um modelo pequeno/quantizado raramente emite
# sozinho. Detecta repetição comparando cada turno novo com o ÚLTIMO turno
# do MESMO falante (similaridade de texto, difflib - biblioteca padrão,
# sem dependência nova) - acima do limiar, a colaboração para ali, em vez
# de continuar reciclando ideia até o limite de rodadas.
REPETITION_SIMILARITY_THRESHOLD = 0.80
# Textos muito curtos podem ser parecidos por coincidência (ex: dois "Sim,
# concordo." seguidos não é reciclagem de conteúdo) - só aplica o guard
# acima deste tamanho mínimo.
REPETITION_MIN_TEXT_LENGTH = 80

CONCLUSION_MARKER = "PROJETO_CONCLUIDO"
SEARCH_MARKER_PATTERN = re.compile(r"^[ \t]*BUSCAR:[ \t]*(.+)$", re.IGNORECASE | re.MULTILINE)

BUSCAR_INSTRUCTION = (
    "Se precisar de informação atual da internet para continuar, escreva numa linha "
    "SOZINHA exatamente: BUSCAR: <o que pesquisar> - o resultado real da busca será "
    "devolvido a você antes de continuar. Use quantas vezes genuinamente precisar."
)


@dataclass
class TurnRecord:
    round_number: int
    speaker: str  # "cpu" ou "gpu"
    engine_label: str
    text: str
    searches: list[str] = field(default_factory=list)
    signaled_done: bool = False
    # PHX-NEW (2026-08-22, achado real do usuário: 6 rodadas seguidas de
    # "corrigi o bug" sem NUNCA corrigir de verdade - `cache = {}` continuava
    # dentro do corpo da função, recriado a cada chamada) - resultado REAL de
    # rodar o código proposto (quando aplicável, ver patch_verification.py),
    # não a opinião de nenhum dos dois modelos sobre a própria resposta.
    objective_check: str | None = None


@dataclass
class CollaborationResult:
    ok: bool
    transcript: list[TurnRecord]
    concluded: bool
    rounds_completed: int
    stopped_reason: str
    error: str | None = None


# PHX-NEW (2026-08-23, achado real do usuário: uma colaboração terminou com
# "✅ Concluída - os dois modelos concordaram" enquanto a ÚNICA verificação
# objetiva que rodou de verdade tinha devolvido NÃO RODOU/FALHOU, e as
# rodadas seguintes - que pareciam ter corrigido o código - nunca chegaram a
# ser testadas de novo porque o modelo trocou de formato (classe sem função
# solta) e o verificador ficou em silêncio por estar fora do escopo dele -
# ver `run_dual_model_collaboration` e `topic_is_verifiable` abaixo pra
# como isso é usado pra recusar uma conclusão "de mentirinha"). Mesma
# convenção textual já usada em ArenaView.tsx::formatCollabResultForChat
# (frontend) pra classificar CONFIRMADO vs NÃO CONFIRMADO/FALHOU/PULADA POR
# SEGURANÇA - mantém as duas pontas (Python e TS) concordando sobre o que
# conta como "confirmado de verdade".
def _is_confirmed_verdict(objective_check_text: str) -> bool:
    return "CONFIRMADO -" in objective_check_text and "NÃO CONFIRMADO" not in objective_check_text


def _build_transcript_context(
    transcript: list[TurnRecord], max_chars: int = 6000, extra_note: str | None = None
) -> str:
    lines = []
    for t in transcript:
        label = "MODELO-CPU" if t.speaker == "cpu" else "MODELO-GPU"
        lines.append(f"[{label}]: {t.text.strip()}")
        if t.objective_check:
            # PHX-NEW: entra como uma linha à parte, sem rótulo de falante -
            # é um FATO observado de fora, não a fala de nenhum dos dois
            # modelos, e precisa ficar visualmente distinto disso pro modelo
            # que lê o histórico não confundir com algo que o outro "disse".
            lines.append(t.objective_check)
    if extra_note:
        # PHX-NEW: nota de nível de COLABORAÇÃO (não de um turno específico -
        # ex.: "sua conclusão anterior foi recusada") - entra por último de
        # propósito, pra sobreviver ao corte por tamanho abaixo (que mantém
        # o FINAL do texto, não o início) e ficar bem visível pro próximo
        # turno de cada lado.
        lines.append(extra_note)
    joined = "\n\n".join(lines)
    if len(joined) > max_chars:
        joined = "...(início do histórico omitido por tamanho)...\n\n" + joined[-max_chars:]
    return joined


async def _run_turn_with_search(
    *,
    execute_fn: Callable[[str, str], Awaitable[str]],
    search_fn: Callable[[str], Awaitable[str]],
    system_prompt: str,
    base_user_prompt: str,
    logs_event: Callable[[str, str, str], None],
    speaker_label: str,
) -> tuple[str, list[str]]:
    """Roda um turno, permitindo até MAX_SEARCHES_PER_TURN idas-e-voltas de
    busca real quando o modelo pede via 'BUSCAR: ...' numa linha sozinha.
    Devolve (texto_final_bruto, lista_de_buscas_feitas) - o texto bruto
    ainda pode conter a linha BUSCAR/marcador de conclusão; quem chama
    limpa isso antes de guardar no transcript."""
    searches_done: list[str] = []
    user_prompt = base_user_prompt
    text = ""
    for attempt in range(MAX_SEARCHES_PER_TURN + 1):
        text = await execute_fn(system_prompt, user_prompt)
        match = SEARCH_MARKER_PATTERN.search(text)
        if not match or attempt == MAX_SEARCHES_PER_TURN:
            return text, searches_done
        query = match.group(1).strip()
        logs_event("INFO", "DualCollabBridge", f"{speaker_label} pediu busca real: '{query}'")
        search_result = await search_fn(query)
        searches_done.append(query)
        user_prompt = (
            f"{base_user_prompt}\n\n(Você pediu uma busca: '{query}'. Resultado real da internet:\n"
            f"{search_result}\n\nContinue sua resposta considerando isso - só peça outra busca se "
            "genuinamente ainda precisar.)"
        )
    return text, searches_done


def default_speaker_order(transcript: list[TurnRecord], round_number: int) -> list[str]:
    """Ordem padrão, EXATAMENTE a de sempre (v24 em diante): CPU fala,
    depois GPU, toda rodada, sem exceção - ignora os argumentos recebidos de
    propósito. É a função usada quando `select_next_speaker` não é
    informado, então nenhum comportamento muda pra quem não passa esse
    parâmetro novo."""
    return ["cpu", "gpu"]


async def run_dual_model_collaboration(
    *,
    topic: str,
    cpu_execute: Callable[[str, str], Awaitable[str]],
    gpu_execute: Callable[[str, str], Awaitable[str]],
    search_fn: Callable[[str], Awaitable[str]],
    logs_event: Callable[[str, str, str], None],
    max_rounds: int = MAX_ROUNDS_DEFAULT,
    # PHX-NEW (2026-08-22, ver patch_verification.py): opcional e SEMPRE
    # não-bloqueante - quando informado, roda uma checagem objetiva (código
    # de verdade executado, não opinião de nenhum modelo) depois de cada
    # turno, e injeta o resultado no histórico da PRÓXIMA rodada como fato.
    # `None` (padrão) preserva o comportamento de antes byte a byte - nenhum
    # teste já existente que não passa isso precisa mudar.
    verify_fn: Callable[[str, str], Awaitable[str | None]] | None = None,
    # PHX-NEW (2026-08-22, inspirado no "custom speaker selection function"
    # do AutoGen - ver LEIA-ME desta entrega pra citação/ressalva sobre o
    # que isso é de fato lá vs. aqui): função opcional que decide a ORDEM de
    # fala de cada rodada, recebendo o transcript até agora e o número da
    # rodada, e devolvendo uma lista de speakers (ex.: ["cpu", "gpu"] ou
    # ["gpu"] pra pular um lado naquela rodada). `None` (padrão) usa
    # `default_speaker_order()` - CPU sempre antes de GPU, toda rodada,
    # idêntico ao comportamento de v24 até aqui. Isto é só o PONTO DE
    # EXTENSÃO - a Phoenix hoje só tem 2 motores (CPU/GPU), então não existe
    # ainda uma função "inteligente" de seleção pronta pra usar aqui; é
    # preparação honesta pra quando/se isso crescer pra mais de 2 lados, não
    # uma feature que já faz algo diferente sozinha.
    select_next_speaker: Callable[[list[TurnRecord], int], list[str]] | None = None,
    # PHX-NEW (2026-08-22, pedido do usuário depois de ver a Arena travada
    # com a ampulheta piscando até as 6 rodadas terminarem, pra só então
    # cuspir tudo de uma vez): callback opcional e SEMPRE não-bloqueante,
    # chamado logo depois de CADA turno terminar (já com objective_check
    # preenchido, se houver) - deixa quem chamou (resident_manager.py)
    # publicar o progresso rodada a rodada num lugar que o frontend
    # consegue perguntar ENQUANTO a colaboração ainda está rodando, em vez
    # de só no final. `None` (padrão) preserva o comportamento de sempre -
    # nenhum teste que não passa isso precisa mudar.
    on_turn: Callable[[TurnRecord], Awaitable[None]] | None = None,
    # PHX-NEW (2026-08-23, achado real do usuário - ver `_is_confirmed_verdict`
    # acima pro caso concreto): função opcional que responde "este TÓPICO tem
    # uma verificação objetiva aplicável a ele?" (ex.: o tópico descreve uma
    # função com nome extraível - `patch_verification.extract_function_name`
    # via resident_manager.py). É INTENCIONALMENTE uma propriedade do TÓPICO,
    # não "algum turno já produziu uma nota até agora" - se fosse baseado só
    # em "já apareceu alguma nota", um modelo que NUNCA escrevesse código
    # testável (sempre fora do escopo do verificador, sempre None) escaparia
    # da trava abaixo por completo, e é exatamente esse buraco que a trava
    # existe pra fechar. `None` (padrão) preserva o comportamento de sempre -
    # PROJETO_CONCLUIDO mútuo sempre encerra, nenhum teste que não passa isso
    # precisa mudar (ex.: tópicos abertos tipo "ola", onde não existe nada
    # objetivo pra verificar e concordância mútua já é o critério certo).
    topic_is_verifiable: Callable[[str], bool] | None = None,
) -> CollaborationResult:
    transcript: list[TurnRecord] = []
    started = time.monotonic()
    concluded = False
    default_stopped_reason = f"limite de {max_rounds} rodada(s) atingido"
    stopped_reason = default_stopped_reason
    round_number = 0

    # PHX-NEW (2026-08-23): quando o tópico tem verificação aplicável, uma
    # conclusão mútua (PROJETO_CONCLUIDO dos dois lados na mesma rodada) só é
    # aceita de verdade se a ÚLTIMA nota objetiva conhecida até agora foi um
    # CONFIRMADO - nunca um FALHOU/NÃO CONFIRMADO/PULADA POR SEGURANÇA, e
    # nunca "nenhuma nota nunca apareceu" (esse último caso é o buraco real
    # que o usuário identificou: um código que nunca virou testável passaria
    # batido se a trava só olhasse "teve algum FALHOU registrado?"). `None` é
    # o estado "ainda não vi nenhuma verificação aplicável" - só vira
    # True/False quando uma nota de verdade chega.
    verification_required = False
    if verify_fn is not None and topic_is_verifiable is not None:
        try:
            verification_required = bool(topic_is_verifiable(topic))
        except Exception as exc:
            verification_required = False
            logs_event(
                "WARNING", "DualCollabBridge",
                f"topic_is_verifiable falhou ao avaliar o tópico - assumindo 'não verificável' "
                f"pra não travar a colaboração por causa de um bug nessa função externa: {exc}",
            )
    last_verdict_confirmed: bool | None = None
    conclusion_was_rejected = False
    pending_rejection_note: str | None = None

    base_system_prompt = (
        # PHX-FIX (2026-08-23, achado real do usuário: releu o transcript de
        # uma colaboração de verdade e viu o lado CPU - Qwen3-4B - raciocinar
        # e responder em INGLÊS inteiro, mesmo com o tópico e todo o resto da
        # Phoenix em português). Antes desta linha, `base_system_prompt` não
        # tinha NENHUMA instrução sobre idioma de resposta - o modelo ficava
        # livre pra usar o idioma "natural" dele pro tipo de conteúdo (código/
        # raciocínio técnico costuma puxar pro inglês em modelos pequenos
        # treinados majoritariamente em texto técnico em inglês). Isto aqui é
        # uma instrução explícita, em primeiro lugar no prompt (posição conta
        # pra modelo pequeno seguir instrução), mas - igual já documentado pra
        # instrução de não copiar rótulo [MODELO-CPU]/[MODELO-GPU] (v31) - é um
        # REFORÇO forte, não uma garantia: um modelo quantizado pequeno pode
        # ainda assim deslizar pro inglês em trechos, principalmente dentro de
        # comentários de código ou cadeia de raciocínio longa. Só o reteste em
        # hardware real confirma se isso resolve na prática.
        "Responda SEMPRE em português do Brasil - todo o seu raciocínio, explicação e "
        "comentários dentro de código devem estar em português, mesmo que o tópico ou "
        "trechos do histórico estejam em outro idioma. Nunca responda em inglês. "
        "Você está colaborando com OUTRO modelo de IA (rodando num motor de hardware "
        f"diferente do seu) num projeto sobre: '{topic}'. Vocês se alternam - leia o que "
        "o outro modelo escreveu no histórico abaixo e contribua de forma construtiva, "
        "concordando, discordando com argumentos, ou avançando o projeto de verdade "
        "(não repita o que já foi dito, nem reformule sua PRÓPRIA resposta anterior com "
        "palavras diferentes - se não tem nada genuinamente novo a acrescentar, é melhor "
        "concluir do que reciclar a mesma ideia). "
        # PHX-FIX (2026-08-22, achado real do usuário: a Rodada 1 e a Rodada
        # 3 da GPU começavam com o texto literal "[MODELO-CPU]:" dentro do
        # próprio corpo da resposta - o modelo estava copiando o formato de
        # rótulo do histórico recebido, em vez de responder só com o
        # próprio conteúdo). O histórico abaixo é rotulado com "[MODELO-CPU]:"
        # e "[MODELO-GPU]:" só pra você (o modelo) saber quem disse o quê -
        # isso NUNCA deve aparecer na sua resposta.
        "O histórico abaixo tem cada fala marcada com \"[MODELO-CPU]:\" ou \"[MODELO-GPU]:\" "
        "só pra você identificar quem disse o quê - isso é formatação do HISTÓRICO, nunca "
        "copie, repita ou inclua esses marcadores na sua própria resposta. Responda direto "
        "com o seu conteúdo, sem se identificar ou citar rótulos de falante. "
        "Quando você achar que o projeto está "
        f"genuinamente concluído, termine sua mensagem com a linha sozinha: {CONCLUSION_MARKER}. "
        # PHX-NEW (2026-08-22, ver patch_verification.py): quando o histórico
        # tiver uma linha começando com "VERIFICAÇÃO OBJETIVA", ela é um FATO
        # medido de verdade rodando o código proposto (nunca a opinião de
        # você ou do outro modelo) - se ela disser que uma correção não
        # funcionou, trate isso como verdade e proponha algo genuinamente
        # diferente, não repita a mesma explicação com mais confiança.
        "Se o histórico tiver uma linha começando com \"VERIFICAÇÃO OBJETIVA\", "
        "trate isso como um FATO medido de verdade (o código foi executado, não é opinião) - "
        "se ela apontar que a correção proposta não funcionou, não insista na mesma ideia. "
        + BUSCAR_INSTRUCTION
    )

    # PHX-FIX (2026-08-22, ver REPETITION_SIMILARITY_THRESHOLD acima): último
    # texto conhecido de CADA falante, pra comparar contra o turno novo dele
    # mesmo (nunca contra o outro lado - repetir o que O OUTRO disse já é
    # coberto pela instrução "não repita o que já foi dito"; isto aqui é
    # especificamente sobre um lado reciclar a PRÓPRIA resposta anterior).
    last_text_by_speaker: dict[str, str] = {}
    repetition_detected = False

    for round_number in range(1, max_rounds + 1):
        if time.monotonic() - started > TOTAL_TIME_BUDGET_SECONDS:
            stopped_reason = f"orçamento de tempo total ({TOTAL_TIME_BUDGET_SECONDS:.0f}s) esgotado"
            round_number -= 1  # esta rodada não chegou a rodar
            break

        engines: dict[str, tuple[Callable[[str, str], Awaitable[str]], str]] = {
            "cpu": (cpu_execute, "llama-server CPU (motor padrão, porta 8081)"),
            "gpu": (gpu_execute, "llama-server GPU/Vulkan (instância dedicada)"),
        }
        selector = select_next_speaker or default_speaker_order
        order = selector(transcript, round_number)
        # PHX-NEW: uma função customizada é código externo - não confia cegamente
        # nela. Nomes desconhecidos são ignorados (com aviso no log) em vez de
        # quebrar a colaboração inteira; se sobrar uma ordem vazia, cai pro
        # padrão em vez de pular a rodada inteira em silêncio.
        speaker_order = [s for s in order if s in engines]
        unknown = [s for s in order if s not in engines]
        if unknown:
            logs_event(
                "WARNING", "DualCollabBridge",
                f"select_next_speaker devolveu speaker(s) desconhecido(s) {unknown!r} na Rodada "
                f"{round_number} - ignorados (só 'cpu'/'gpu' existem hoje).",
            )
        if not speaker_order:
            logs_event(
                "WARNING", "DualCollabBridge",
                f"select_next_speaker devolveu uma ordem vazia/inválida na Rodada {round_number} - "
                "usando a ordem padrão (CPU, GPU) pra esta rodada.",
            )
            speaker_order = default_speaker_order(transcript, round_number)

        for speaker in speaker_order:
            execute_fn, engine_label = engines[speaker]
            context = _build_transcript_context(transcript, extra_note=pending_rejection_note)
            user_prompt = (
                f"Histórico da colaboração até agora:\n\n{context or '(nada ainda - você começa)'}\n\n"
                f"Sua vez de contribuir com o projeto '{topic}'."
            )
            raw_text, searches = await _run_turn_with_search(
                execute_fn=execute_fn,
                search_fn=search_fn,
                system_prompt=base_system_prompt,
                base_user_prompt=user_prompt,
                logs_event=logs_event,
                speaker_label=speaker.upper(),
            )
            signaled_done = CONCLUSION_MARKER in raw_text
            clean_text = SEARCH_MARKER_PATTERN.sub("", raw_text).replace(CONCLUSION_MARKER, "").strip()
            turn_record = TurnRecord(
                round_number=round_number, speaker=speaker, engine_label=engine_label,
                text=clean_text, searches=searches, signaled_done=signaled_done,
            )
            transcript.append(turn_record)
            logs_event(
                "INFO", "DualCollabBridge",
                f"Rodada {round_number}, {speaker.upper()}: {len(clean_text)} chars"
                + (f", {len(searches)} busca(s) real(is)" if searches else ""),
            )

            # PHX-NEW (2026-08-22, ver patch_verification.py e verify_fn
            # acima): roda a checagem objetiva DEPOIS de guardar o turno no
            # transcript (o texto original do modelo nunca é alterado por
            # isso) - o resultado vira uma nota separada que só entra no
            # histórico que a PRÓXIMA rodada lê. Uma falha aqui (bug no
            # verificador, timeout do subprocesso etc.) NUNCA derruba a
            # colaboração inteira - vira só um aviso no log, a colaboração
            # segue sem a nota objetiva daquele turno.
            if verify_fn is not None:
                try:
                    objective_note = await verify_fn(topic, clean_text)
                except Exception as exc:
                    objective_note = None
                    logs_event(
                        "WARNING", "DualCollabBridge",
                        f"Verificação objetiva falhou na Rodada {round_number} ({speaker.upper()}) - "
                        f"não bloqueante, colaboração continua sem essa nota: {exc}",
                    )
                if objective_note:
                    turn_record.objective_check = objective_note
                    logs_event("INFO", "DualCollabBridge", f"Rodada {round_number}, {speaker.upper()}: {objective_note}")
                    # PHX-NEW: atualiza o veredito MAIS RECENTE conhecido -
                    # usado só na hora de decidir se uma conclusão mútua pode
                    # ser aceita como sucesso real (ver topic_is_verifiable
                    # acima). Sobrescreve o anterior de propósito - o que
                    # importa é o estado mais atual, não o histórico inteiro.
                    last_verdict_confirmed = _is_confirmed_verdict(objective_note)

            # PHX-NEW (2026-08-22, ver `on_turn` acima): publica o turno já
            # completo (com objective_check, se houver) pra quem quiser
            # mostrar progresso ao vivo - roda DEPOIS da checagem objetiva
            # de propósito, pra quem está ouvindo já receber o turno com a
            # nota (se houver) em vez de precisar de uma segunda notificação
            # só pra isso. Mesma filosofia não-bloqueante de verify_fn: uma
            # falha aqui nunca derruba a colaboração, só vira aviso no log.
            if on_turn is not None:
                try:
                    await on_turn(turn_record)
                except Exception as exc:
                    logs_event(
                        "WARNING", "DualCollabBridge",
                        f"on_turn (callback de progresso ao vivo) falhou na Rodada {round_number} "
                        f"({speaker.upper()}) - não bloqueante, colaboração continua normalmente: {exc}",
                    )

            # PHX-FIX (achado real - ver REPETITION_SIMILARITY_THRESHOLD
            # acima): compara este turno com o ÚLTIMO turno DESTE MESMO
            # falante (pode ser rodadas atrás, já que cada um fala uma vez
            # por rodada) - se for quase o mesmo texto, o modelo está
            # reciclando a própria resposta em vez de avançar. Detecta e
            # PARA aqui, em vez de continuar até max_rounds fingindo
            # progresso que não existe.
            previous_text = last_text_by_speaker.get(speaker)
            if (
                previous_text
                and len(clean_text) >= REPETITION_MIN_TEXT_LENGTH
                and len(previous_text) >= REPETITION_MIN_TEXT_LENGTH
            ):
                similarity = difflib.SequenceMatcher(None, previous_text, clean_text).ratio()
                if similarity >= REPETITION_SIMILARITY_THRESHOLD:
                    logs_event(
                        "WARNING", "DualCollabBridge",
                        f"{speaker.upper()} repetiu a própria resposta anterior "
                        f"(similaridade {similarity:.0%}, limiar {REPETITION_SIMILARITY_THRESHOLD:.0%}) - "
                        "encerrando a colaboração em vez de reciclar conteúdo indefinidamente.",
                    )
                    repetition_detected = True
                    stopped_reason = (
                        f"{speaker.upper()} começou a repetir a própria resposta anterior quase "
                        f"palavra por palavra (similaridade {similarity:.0%}) - a colaboração foi "
                        "encerrada em vez de continuar reciclando a mesma ideia até o limite de rodadas."
                    )
                    break
            last_text_by_speaker[speaker] = clean_text

        if repetition_detected:
            break

        this_round = [t for t in transcript if t.round_number == round_number]
        if (
            round_number >= MIN_ROUNDS_BEFORE_CONCLUSION
            and len(this_round) == 2
            and all(t.signaled_done for t in this_round)
        ):
            # PHX-FIX (2026-08-23, achado real do usuário - o caso mais grave
            # da auditoria até agora: uma colaboração fechou como "✅
            # Concluída - os dois modelos concordaram" com a ÚNICA
            # verificação objetiva que rodou tendo dado FALHOU, e o código
            # "corrigido" das rodadas seguintes NUNCA foi testado de novo
            # porque o modelo mudou de formato (classe sem função solta) e o
            # verificador ficou em silêncio por estar fora do escopo dele -
            # ou seja, o sistema apresentou um resultado quebrado como
            # sucesso confirmado. Quando o tópico tem verificação aplicável
            # (`verification_required`), concordância mútua sozinha NÃO É
            # MAIS SUFICIENTE - só fecha como sucesso real se a última nota
            # objetiva conhecida foi um CONFIRMADO de verdade. Ausência total
            # de nota (`last_verdict_confirmed is None`) conta como "não
            # confirmado" também - de propósito, é o buraco que a formulação
            # inicial ("só bloqueia se o último veredito foi FALHOU") não
            # cobria: um código que nunca virou testável não devolve FALHOU
            # nenhum, devolve silêncio, e passaria batido se a trava
            # exigisse ver um FALHOU explícito em vez de exigir ver um
            # CONFIRMADO explícito.
            if not verification_required or last_verdict_confirmed is True:
                concluded = True
                stopped_reason = "os dois modelos sinalizaram que o projeto está concluído"
                break

            conclusion_was_rejected = True
            logs_event(
                "WARNING", "DualCollabBridge",
                f"Rodada {round_number}: os dois lados sinalizaram PROJETO_CONCLUIDO, mas a "
                "verificação objetiva "
                + ("ainda não confirmou sucesso (última nota foi NÃO CONFIRMADO/FALHOU/PULADA)"
                   if last_verdict_confirmed is False
                   else "nunca chegou a rodar pra esse código (nenhuma nota objetiva apareceu)")
                + " - conclusão RECUSADA, forçando pelo menos mais uma rodada em vez de fechar "
                "como sucesso sem confirmação real.",
            )
            pending_rejection_note = (
                "AVISO DO SISTEMA (não é fala de nenhum dos dois modelos): vocês dois sinalizaram "
                "que o projeto estava concluído, mas isso foi RECUSADO porque a verificação "
                "objetiva ainda não confirmou que a correção funciona de verdade (ou o código "
                "proposto nem chegou a ser testável até agora). NÃO declarem conclusão de novo até "
                "que uma verificação objetiva real confirme sucesso. Se a última proposta usou uma "
                "classe/objeto com estado, inclua TAMBÉM uma função solta (fora de qualquer classe) "
                "com o mesmo nome da função original e os mesmos parâmetros dela, pra que seja "
                "possível testar de verdade - sem isso, a verificação nunca roda."
            )

    if not concluded and conclusion_was_rejected and stopped_reason == default_stopped_reason:
        # PHX-NEW: rótulo honesto e distinto do "limite de rodadas atingido"
        # genérico - aqui os dois modelos CHEGARAM a se declarar concluídos
        # em algum momento, e foram impedidos; diferente de simplesmente
        # nunca terem tentado. O resultado final (`concluded=False`) já
        # impede a Arena de mostrar "✅ Concluída" (ver ArenaView.tsx), mas
        # esse texto deixa claro POR QUE parou sem confirmação, em vez de
        # parecer só "acabaram as rodadas".
        stopped_reason = (
            "os dois modelos sinalizaram conclusão em algum momento, mas a verificação objetiva "
            "nunca confirmou que a correção funciona de verdade - encerrado no limite de rodadas "
            "SEM confirmação real (isto não é um resultado confirmado, mesmo com os dois modelos "
            "tendo 'concordado' entre si)."
        )

    return CollaborationResult(
        ok=True, transcript=transcript, concluded=concluded,
        rounds_completed=round_number, stopped_reason=stopped_reason,
    )
