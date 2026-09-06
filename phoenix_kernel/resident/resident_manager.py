import asyncio
import json
import logging
import os
import importlib
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
# PHX-NEW (auditoria completa, achado #4 do LEIA-ME): necessário pra
# transcribe_direct() checar existência do arquivo de áudio - nenhum uso
# de Path existia neste módulo antes.
from pathlib import Path

from .interfaces import IResidentManager
from phoenix_kernel.intelligence.reasoning_engine import ReasoningEngine
from phoenix_kernel.core.enums import MissionStatus, MissionAction
from phoenix_kernel.core.kernel import MissionKernel
from phoenix_kernel.core.exceptions import NoActiveMissionError
from core.domain.execution import ExecutionPlan, ExecutionResult, ExecutionStatus
from phoenix_kernel.orchestration.execution_arbiter import (
    ClaimState, IntentDecision, ResourcePolicy, default_execution_arbiter,
)

logger = logging.getLogger(__name__)

# PHX-NEW (auditoria 2026-08-20, "XLSX timeout" - Seção 13): timeout
# interno pro runtime.execute() em read_document_direct()/edit_document_direct().
# Fica bem abaixo do AbortController em platform_source/server.ts (rotas
# /api/documents/read e /api/documents/edit) de propósito: o Phoenix Engine
# precisa desistir e devolver um erro claro ANTES do Node abortar a conexão
# HTTP - senão o usuário só via uma falha de rede genérica sem nenhuma pista
# do que aconteceu de fato.
#
# PHX-FIX (auditoria 2026-08-21, "corrigir tudo" - achado real de uma
# auditoria externa independente, confirmado lendo o código: o valor original
# de 240s deixava só 60s de margem pro AbortController do Node, que estava em
# 300s - qualquer coisa além da própria inferência (upload do arquivo,
# serialização da resposta, fila do event loop) podia comer essa margem e
# fazer o Node abortar ANTES do Engine devolver seu próprio erro controlado -
# o usuário via só uma falha de rede genérica em vez da mensagem clara
# "O modelo demorou mais que Xs..." abaixo. Também era pouco pro hardware
# real relatado pelo usuário (Xeon E5-2690 v3 + RX 580 via Vulkan - CPU
# antigo + GPU sem muita VRAM, offload parcial), onde uma inferência sobre um
# documento grande pode legitimamente passar de 4 minutos sem estar travada,
# só sendo lenta mesmo. Subido pra 480s (8min), com o AbortController do Node
# subindo em conjunto pra 540s (9min) - ver platform_source/server.ts -
# mantendo a mesma margem de segurança de 60s, só que num teto mais realista
# pra hardware modesto.
DOCUMENT_EXECUTE_TIMEOUT_SECONDS = 480

# PHX-FIX V5: criação de documentos pode usar modelos muito maiores que o
# chatbot padrão (ex.: Gemma 4 12B Q4_0). Um teto único de 480s mata uma
# geração legítima antes de ela terminar. Mantemos 480s para leitura/edição
# leve, mas o CREATE usa orçamento adaptativo abaixo.
DOCUMENT_CREATE_TIMEOUT_MEDIUM_SECONDS = 1200   # 20 min
# PHX-FIX (pedido explícito do usuário 2026-08-28, testando Gemma 4 12B
# gerando um relatório longo via pesquisa web + PDF): o llama-server
# usado aqui não faz streaming pro nosso lado (`stream: false`) - o
# modelo "constrói" a resposta inteira e só "cospe tudo de uma vez" no
# final. Numa máquina rodando um modelo de 12b+ bastante em CPU, gerar um
# relatório longo (introdução + tabela + requisitos + vantagens +
# limitações + conclusão + fontes) pode legitimamente passar dos 30min
# que este teto tinha antes, sem estar travado - só é lento mesmo. A
# pedido do usuário, subido pra 1h (3600s), a mesma filosofia de sempre:
# NÃO é "sem limite" (nenhum LLM tem contexto infinito), é um teto de
# SEGURANÇA generoso o bastante pra não confundir "modelo lento" com
# "modelo travado". Ver PHX-FIX espelhado em llama_cpp.py (piso HTTP do
# driver) e platform_source/server.ts (proxy Node) - os três precisam
# subir JUNTOS (driver < Resident < proxy), senão o elo mais fraco corta
# a chamada antes dos outros dois terem qualquer chance de agir.
DOCUMENT_CREATE_TIMEOUT_LARGE_SECONDS = 3600    # 60 min

# PHX-FIX (achado real do usuário 2026-08-28, catálogo de construção real
# ~58KB de texto extraído de uma conversa longa com o Gemini):
# fill_spreadsheet_template_direct cortava o documento-fonte em
# char_limit=18000 ANTES de mandar pro modelo - o resto era descartado em
# SILÊNCIO, sem aviso nenhum na resposta. Resultado observado de verdade:
# de ~20 produtos distintos mencionados no documento, só 3 (os que
# calharam de caber dentro do corte) viraram linha na planilha - um
# "sucesso" técnico (sem erro nenhum) que na prática perdeu a maior parte
# dos dados. Substituído por processamento em PEDAÇOS: o texto COMPLETO
# (sem corte) é dividido em partes que cabem no contexto do modelo,
# cada parte processada com o mesmo loop de tentativa+retry de sempre, e
# as linhas de todas as partes são juntadas (com deduplicação - ver
# _merge_and_dedupe_rows, importante porque uma conversa longa costuma
# repetir o mesmo produto várias vezes ao longo de revisões, e cada
# repetição pode cair numa parte diferente).
#
# Orçamento por pedaço: contexto do llama-server é 32768 tokens (ver
# llama_cpp.py, `-c 32768` - aumentado de 16384 em 2026-09-06, mesmo achado
# do usuário recorrendo: "qualquer resposta... fica cortada"); reservando
# ~6144 tokens de saída (max_tokens já configurado abaixo) e uma margem
# pro resto do prompt (system_prompt + descrição das colunas do template +
# instrução do usuário), sobra confortavelmente espaço pra ~22000
# caracteres de entrada (~3,5 caracteres/token em português, com folga
# real - testado sem estourar o contexto). Teto de pedaços
# (_SPREADSHEET_FILL_MAX_CHUNKS, ver abaixo) evita um documento
# patologicamente grande gerar milhares de chamadas ao modelo sem
# perceber - mas generoso o bastante pra não recriar o mesmo problema
# desta correção com outro número: o documento REAL que motivou esta
# correção (conversa de catálogo, ~430 mil caracteres extraídos) já
# precisa de 21 pedaços sozinho; o teto fica bem acima disso (~1,3 milhão
# de caracteres) pra cobrir catálogos ainda maiores sem cortar em
# silêncio de novo - documentos extremamente grandes (upload por engano,
# por exemplo) ainda são pegos e reportados via
# `source_truncated_extra_parts` na resposta, nunca descartados sem
# aviso.
#
# PHX-NOTE (2026-09-06): essa conta foi feita pro contexto ANTERIOR
# (16384) e NÃO foi recalibrada pro novo contexto (32768) nesta rodada -
# de propósito: aumentar o orçamento por pedaço muda quantos pedaços um
# documento vira e o tamanho de cada chamada ao modelo, numa
# funcionalidade (preenchimento de planilha) já testada extensivamente
# nesta sessão - prefiro não recalibrar isso sem testar de novo com dado
# real, fora do escopo do pedido de hoje (que era sobre o CHAT, não sobre
# a planilha). O valor atual (22000) continua funcionando - só ficou mais
# conservador que precisaria ser, com ~16000 tokens extras de contexto
# sobrando sem uso aqui. Se quiser aproveitar isso (menos pedaços, menos
# chamadas, processamento mais rápido de documento grande), é um ajuste
# à parte, testável isoladamente.
_SPREADSHEET_FILL_CHUNK_CHAR_BUDGET = 22000
_SPREADSHEET_FILL_MAX_CHUNKS = 60

_BARCODE_LIKE_RE = re.compile(r"^\d{8,14}$")


def _split_text_into_chunks(text: str, budget: int) -> list[str]:
    """Divide `text` em pedaços de até `budget` caracteres sem nunca
    cortar um parágrafo ao meio - acumula parágrafos (separados por linha
    em branco; cai pra quebra de linha simples quando o texto não tem
    parágrafos com linha em branco, ex: uma linha por produto) até chegar
    perto do limite, então começa um pedaço novo. Um único parágrafo maior
    que `budget` sozinho vira seu próprio pedaço, fatiado no limite (nunca
    trava tentando achar uma quebra que não existe). Devolve uma lista
    vazia pra texto vazio, ou [text] inteiro se já couber num pedaço só -
    ou seja, pra qualquer documento pequeno o comportamento é idêntico a
    "não dividir nada"."""
    text = text or ""
    if not text:
        return []
    if len(text) <= budget:
        return [text]

    sep = "\n\n" if "\n\n" in text else "\n"
    paragraphs = text.split(sep)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for para in paragraphs:
        para_len = len(para) + len(sep)
        if para_len > budget:
            if current:
                chunks.append(sep.join(current))
                current, current_len = [], 0
            for i in range(0, len(para), budget):
                chunks.append(para[i:i + budget])
            continue
        if current and current_len + para_len > budget:
            chunks.append(sep.join(current))
            current, current_len = [], 0
        current.append(para)
        current_len += para_len
    if current:
        chunks.append(sep.join(current))
    return chunks


def _row_identity_key(row: dict) -> str:
    """Heurística pra reconhecer quando duas linhas (possivelmente vindas
    de pedaços DIFERENTES do mesmo documento) descrevem o MESMO item -
    comum quando a fonte é uma conversa longa em que o mesmo produto é
    revisado várias vezes ao longo do texto (achado real do usuário
    2026-08-28: catálogo de construção com o mesmo item reaparecendo em
    formatos HTML diferentes conforme a conversa avança). Prioriza um
    valor que pareça código de barras/EAN (8-14 dígitos) - identificador
    de negócio inequívoco quando presente; senão usa o valor de uma coluna
    cujo NOME pareça ser o nome/descrição do item (heurística sobre o
    nome da coluna, já que quem define os nomes reais é o template, não a
    Phoenix); na ausência dos dois, a linha é tratada como única (nunca
    arrisca fundir duas linhas sem um sinal confiável de que são o mesmo
    item)."""
    for value in row.values():
        s = str(value if value is not None else "").strip()
        if s and _BARCODE_LIKE_RE.match(s):
            return f"ean:{s}"
    name_like_markers = ("descri", "nome", "produto", "titulo", "título", "item")
    for key, value in row.items():
        key_lower = str(key).lower()
        if any(marker in key_lower for marker in name_like_markers):
            s = str(value if value is not None else "").strip()
            if s:
                return f"name:{key_lower}:{s.lower()[:80]}"
    return f"unique:{id(row)}"


def _merge_and_dedupe_rows(rows_by_chunk: list[list[dict]]) -> list[dict]:
    """Junta as linhas de todos os pedaços processados, na ordem em que
    aparecem no documento. Quando duas linhas de pedaços diferentes
    representam o MESMO item (mesma chave de _row_identity_key), fica a
    versão do pedaço MAIS TARDE - numa conversa revisada ao longo do
    texto, a versão mais recente tende a estar mais pra frente (mesmo
    padrão observado no achado real que motivou isso: o mesmo produto de
    construção reaparecia com dados mais completos/corretos nas partes
    finais da conversa)."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for chunk_rows in rows_by_chunk:
        for row in chunk_rows:
            key = _row_identity_key(row)
            if key not in merged:
                order.append(key)
            merged[key] = row
    return [merged[k] for k in order]

# PHX-FIX (varredura 2026-08-21, achado real confirmado com log de produção
# do usuário: tentou ler um PDF e um DOCX "muito grandes" - o primeiro
# derrubou a conexão do Node com UND_ERR_HEADERS_TIMEOUT (>5min sem
# resposta nenhuma do Engine), o segundo eventualmente devolveu um 500 do
# llama.cpp interno com a GPU a 100%). DOCUMENT_EXECUTE_TIMEOUT_SECONDS
# acima só limita a INFERÊNCIA (`self.runtime.execute(plan)`) - a
# EXTRAÇÃO (`extract_text()`/`summarize_xlsx_structure()`, chamada logo
# antes, via `run_in_executor`) nunca teve timeout nenhum. Pra um DOCX/PDF
# "muito grande" (milhares de parágrafos/linhas de tabela - `_extract_docx`
# em documents/engine.py não tem NENHUM limite/streaming, ao contrário do
# XLSX que já foi corrigido numa rodada anterior), essa extração sozinha
# pode legitimamente levar minutos, corroendo em silêncio a margem de 60s
# que o proxy Node reserva acima do teto de inferência - exatamente o tipo
# de tempo não-contabilizado que fecha a conta do timeout relatado. Sem
# isso, uma extração lenta nunca aparecia nos logs como o vilão - só o
# sintoma final (timeout de inferência, ou o proxy do Node desistindo)
# ficava visível. Timeout dedicado e generoso (extração é I/O+CPU puro,
# sem GPU - 120s já é folgado pra qualquer documento que não seja
# patologicamente grande) com uma mensagem que aponta pra ETAPA certa.
DOCUMENT_EXTRACT_TIMEOUT_SECONDS = 120
RAG_DOCUMENT_EXTRACT_TIMEOUT_SECONDS = 600  # v57: ingestão pode ler documentos muito maiores

# PHX-NEW (auditoria 2026-08-21, "corrigir tudo"): `run_token_benchmark_direct()`
# (abaixo) chamava `self.runtime.execute(plan)` DIRETO, sem nenhum timeout
# próprio - o único teto era o timeout interno de cada driver (600s no
# LlamaCppDriver via httpx, 600s no OllamaDriver via urllib), enquanto
# `platform_source/server.ts` (rota /api/benchmark) só esperava 60s antes de
# abortar a conexão. Um "gap" de 10x: numa inferência de benchmark que
# precisasse primeiro CARREGAR o modelo (cold start - servidor llama.cpp
# ainda não estava rodando, ou modelo ainda não estava na VRAM), 60s podia
# não ser suficiente nem pro carregamento, quanto mais pra geração dos 64
# tokens do benchmark em si - o Node abortava e o usuário via
# "Phoenix Engine indisponível" mesmo com o Engine são e ainda processando.
# Mesmo padrão de proteção do DOCUMENT_EXECUTE_TIMEOUT_SECONDS acima: um
# teto MENOR que o do Node (300s aqui vs 360s no proxy - ver server.ts) pra
# o Engine sempre desistir primeiro com um erro claro.
BENCHMARK_EXECUTE_TIMEOUT_SECONDS = 300

# PHX-NEW (pedido do usuário 2026-08-22: "habilitar todas as funçoes do
# modelo de ocr pra qualquer função" - escopo confirmado: OCR real para
# ler PDF escaneado): _extract_pdf() em documents/engine.py roda com
# use_ocr=OCRMode.NEVER de propósito (ver comentário lá - OCR "escondido"
# via Tesseract causava timeouts silenciosos e imprevisíveis). O próprio
# comentário já deixava escrito o que faltava: "isso precisa ser uma
# decisão explícita e documentada (endpoint próprio, timeout próprio,
# feedback de progresso pro usuário)". As constantes abaixo são
# exatamente isso: OCR real via visão nativa (MiniCPM-V, já testada e
# funcionando em describe_image_direct), acionado como FALLBACK EXPLÍCITO
# só quando extract_text() já confirmou que o PDF não tem texto nativo -
# nunca silencioso (sempre reportado em `ocr_used`/`ocr_pages_processed`/
# `ocr_truncated` na resposta final).
OCR_MAX_PAGES = 10
OCR_PAGE_TIMEOUT_SECONDS = 200.0
OCR_TOTAL_BUDGET_SECONDS = 300.0
OCR_EXTRACT_TIMEOUT_SECONDS = 330.0
OCR_MAX_TOKENS_PER_PAGE = 700

# PHX-NEW (2026-09-06, achado real: pedido original do usuário em 22/08
# era "habilitar todas as funções do OCR pra QUALQUER função" - o escopo
# daquela rodada foi restringido só a PDF escaneado, ver comentário acima;
# imagem solta [.png/.jpg/foto de documento, print de tela] ficou de fora
# e nunca foi ligada à ingestão de RAG - só existia via /api/describe-image
# ?mode=ocr, uma rota de CHAT, nunca alcançável por /api/rag/add-file).
# Mesma lista de extensões já usada em api_server.py (_ALLOWED_IMAGE_EXTS,
# rota /api/describe-image) - uma única fonte de verdade pro que conta como
# "imagem" no projeto, sem duplicar com valores diferentes por acidente.
RAG_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff"}

# PHX-NEW (pedido do usuário 2026-08-23: "pegar um arquivo doc, pdf de 40
# folhas e fazer áudio com voz neural"): orçamento de tempo TOTAL pra
# geração de um audiolivro inteiro (extração + síntese de todos os blocos +
# concatenação). Diferente dos outros timeouts acima (minutos), este é o
# maior do arquivo de propósito - um documento de 40 páginas sintetizado
# com Kokoro-82M foi medido de verdade nesta sessão em ~0.4-0.5x o tempo
# real de áudio (ver prova_testes/) num hardware BEM mais fraco (2 vCPUs)
# que o Xeon E5-2690 v3 real do usuário (12 núcleos/24 threads) - ou seja,
# esta margem é conservadora, não o tempo esperado normal. Verificado a
# CADA BLOCO sintetizado (não é um único asyncio.wait_for em volta do laço
# inteiro) pra permitir devolver o áudio já sintetizado até aqui em vez de
# jogar fora horas de trabalho só porque estourou o teto por um bloco.
AUDIOBOOK_TOTAL_TIME_BUDGET_SECONDS = 5400.0  # 90 minutos

_hardware_core = importlib.import_module("phoenix_kernel.telemetry.core")
_models_module = importlib.import_module("phoenix_kernel.models.model_manager")
_paths_module = importlib.import_module("phoenix_kernel.paths")
# PHX-NEW (Fase 2 - Abstração de Capacidades): Model Registry. Antes,
# "qwen3:8b"/"minicpmv"/"flux"/"pt_br-faber-medium" apareciam como string
# literal espalhados pelo código - trocar o modelo padrão de uma
# capacidade exigia caçar e editar em vários lugares. Agora
# catalog/models.json declara isso e o ResidentManager só pede uma ROLE
# (ex: "vision", "image_generation", "chat") pro registry.resolve() -
# mesmo princípio de abstração que phoenix_kernel/documents/engine.py já
# aplica pra formato de arquivo.
_registry_module = importlib.import_module("phoenix_kernel.models.registry")
# PHX-FIX (auditoria 17/08): AssetManager substitui o ModelManager para
# modelos de IMAGEM. O ModelManager (Ollama) continua para modelos de texto.
_asset_manager_module = importlib.import_module("Engine.provisioning.asset_manager")
ModelManager = _models_module.ModelManager
PhoenixPaths = _paths_module.PhoenixPaths
ModelRegistry = _registry_module.ModelRegistry
AssetManager = _asset_manager_module.AssetManager

HOT_TEMP_C = 80.0
HIGH_LOAD_PCT = 90.0

# PHX-FIX: padrões usados para classificar a arquitetura de um .gguf de
# imagem só pelo nome do arquivo. Isso é o mesmo critério que o
# SdCppDriver já usa pra decidir -m vs --diffusion-model - centralizado
# aqui pra não divergir entre os dois lugares.
_IMAGE_ARCH_PATTERNS = {
    "z-image": ("z_image", "z-image"),
    "flux": ("flux",),
    "sd15": ("dreamshaper", "sd15", "sd-1", "sd1.5", "sd_1_5"),
    "sdxl": ("sdxl", "xl-base", "xl_base"),
}

# PHX-FIX (achado real via log do usuário: "get sd version from file
# failed: '...\sdxl_vae-fp16-fix.safetensors'"): _resolve_image_model_target
# escolhia esse arquivo como "o modelo" quando o hint pedido era "sdxl" -
# porque fazia um substring cru ("sdxl" in nome_do_arquivo) que NUNCA bate
# no checkpoint real baixado pelo próprio catálogo ("sd_xl_base_1.0.safetensors",
# tem "sd_xl" com underscore, não "sdxl" grudado), mas bate por acidente
# no VAE ("sdxl_vae-fp16-fix.safetensors", que começa literalmente com
# "sdxl"). O VAE virava "o modelo", e o stable-diffusion.cpp falhava
# tentando ler a versão SD de um arquivo que não é um checkpoint completo
# - exatamente o erro reportado. Estes arquivos são sempre auxiliares
# (vae/clip/text-encoder) - SdCppDriver._find_component() já os acha
# separadamente pelo profile de cada arquitetura - nunca devem ser
# candidatos a "o modelo principal".
_COMPONENT_FILE_HINTS = (
    "vae", "clip_l", "clip_g", "t5xxl", "qwen3-4b-instruct-2507",
)


def _looks_like_component_file(name_lower: str) -> bool:
    """True se o nome (stem, minúsculo) parece um arquivo AUXILIAR
    (vae/clip/text-encoder) em vez de um checkpoint principal. O caso
    "ae" é o autoencoder do Flux (arquivo literalmente chamado
    "ae.safetensors") - comparação exata, não substring, pra não excluir
    por engano um checkpoint legítimo que só contenha "ae" em outra
    parte do nome (ex: "...base_1.0" não deveria ser afetado por isso -
    e não é, porque a checagem aqui é só pros hints de componente e pelo
    nome exato "ae", nunca substring solto)."""
    return name_lower == "ae" or any(hint in name_lower for hint in _COMPONENT_FILE_HINTS)


class ResidentManager(IResidentManager):
    def __init__(self, state_engine, planner_engine, services_engine, logs_engine, runtime_engine=None, model_manager=None, model_registry=None):
        self.state = state_engine
        self.planner = planner_engine
        self.services = services_engine
        self.logs = logs_engine
        self.runtime = runtime_engine
        # PHX-NEW 2026-08-30: autoridade única de intenção/executor/grounding/CPU-GPU.
        # ResidentManager executa a decisão; não compete mais com o árbitro.
        self.execution_arbiter = default_execution_arbiter

        # PHX-NEW (Fase 2): Model Registry - injetável (mesmo padrão de
        # model_manager abaixo) pra facilitar teste com um catálogo fake,
        # ou cria o real lendo catalog/models.json se ninguém injetar.
        self.registry = model_registry if model_registry else ModelRegistry()

        # PHX-NEW (Fase 3 - Hot-Swap): referência ao facade do AHDE, pra
        # consultar VRAM livre antes de subir um modelo pesado na GPU.
        # Injetada depois da construção via set_ahde() - não dá pra
        # injetar aqui porque no kernel.py o AHDE só é criado DEPOIS do
        # ResidentManager (mesmo padrão que state.py já usa com seu
        # próprio set_ahde()). None até lá - todo _vram_guard() trata
        # esse caso como "sem dado, não bloqueia" (mesmo espírito do
        # _thermal_guard: avisa, nunca impede).
        self.ahde = None

        # PHX-NEW (Fase 3 - Hot-Swap): rastreamento de "o que está
        # carregado agora", por runtime (alias) -> model_id. Isto não
        # existia antes - a única noção de "modelo ativo" vinha de fora
        # (step.metadata["from_runtime"] fornecido pelo LLM ao montar a
        # missão), nunca observado de verdade. Populado em todo ponto que
        # chama self.runtime.start()/.execute() com um modelo, limpo em
        # todo self.runtime.stop() - ver _track_model_loaded/_unloaded
        # abaixo. É a base que _vram_guard() usa pra decidir o que
        # descarregar antes de subir algo novo.
        self._active_models: dict[str, str] = {}

        # PHX-FIX: Injeta runtime_engine E logs_engine no ReasoningEngine - o
        # runtime pra usar o driver nativo (Vulkan), os logs pra você ver o
        # "pensamento" ao vivo no painel em vez do terminal ficar mudo.
        # PHX-NEW (Fase 2): também injeta o registry - o ReasoningEngine não
        # decide mais sozinho qual modelo de texto usar (era DEFAULT_MODEL =
        # "qwen3:8b" hardcoded).
        self.reasoning = ReasoningEngine(state_engine, runtime_engine=self.runtime, logs_engine=self.logs, model_registry=self.registry)

        # PHX-FIX: Usa o ModelManager injetado pelo Kernel ou cria um fallback
        self.model_manager = model_manager if model_manager else ModelManager()
        # PHX-FIX (auditoria 17/08): AssetManager para download de modelos de imagem
        self.asset_manager = AssetManager()

        # PHX-FIX (auditoria segunda rodada): MissionKernel existia como
        # classe isolada (criada pra destravar os testes), mas o ResidentManager
        # usava self._active_mission ad hoc, ignorando completamente o portao
        # de aprovacao. Agora o fluxo real passa pelo MissionKernel — o mesmo
        # objeto que os testes exercitam, tornando-os cobertura do caminho real.
        self._mission_kernel = MissionKernel()
        self._active_mission = None  # mantido so pra compatibilidade de leitura em get_status()

        # PHX-NEW: fila de mensagens que o Resident decide mandar direto
        # pro Chat WebUI (porta 3000), sem passar por missão de
        # provisionamento - populada em process_intent() quando
        # reasoning.plan_mission() devolve None mas reasoning.last_response
        # veio preenchido (campo "response" do JSON, ver reasoning_engine.py).
        # api_server.py serve isso em GET /api/chat/pending e limpa ao servir.
        self.pending_chat_messages: list[dict] = []

        # PHX-NEW (destravar Ollama como 2ª opção de engine de texto):
        # carrega a preferência persistida em disco (sobrevive a um
        # restart do api_server.py) e já sincroniza o ReasoningEngine com
        # ela - sem isso, escolher "ollama" numa sessão e reiniciar a
        # Phoenix voltaria silenciosamente pro llama.cpp sem avisar.
        self._text_engine_preference = self._load_text_engine_preference()
        self.reasoning.text_engine_hint = "" if self._text_engine_preference == "llama.cpp" else self._text_engine_preference

    _VALID_TEXT_ENGINES = ("llama.cpp", "ollama")

    def _load_text_engine_preference(self) -> str:
        path = _paths_module.TEXT_ENGINE_PREFERENCE_FILE
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                engine = data.get("engine")
                if engine in self._VALID_TEXT_ENGINES:
                    return engine
                logger.warning(f"ResidentManager: preferência de engine de texto inválida em disco ('{engine}'). Usando default 'llama.cpp'.")
        except Exception as e:
            logger.warning(f"ResidentManager: falha ao ler preferência de engine de texto ({e}). Usando default 'llama.cpp'.")
        return "llama.cpp"

    def get_text_engine_preference(self) -> dict:
        """Estado atual da escolha de engine de texto (llama.cpp nativo
        vs Ollama via Docker) - consumido por GET /api/engine/text-runtime."""
        return {"engine": self._text_engine_preference, "available": list(self._VALID_TEXT_ENGINES)}

    def set_text_engine_preference(self, engine: str) -> dict:
        """Troca qual engine de texto `infer`/`resident research` (e o
        Aviary Architect do Swarm, que reusa o mesmo ReasoningEngine)
        usam pra resolver a role 'chat'/'reasoning' no catalog/models.json.
        "ollama" é sempre a segunda opção (mais lenta, via Docker) - nunca
        vira default_for_roles no catálogo, só é escolhida quando o
        usuário troca aqui explicitamente. Persiste em disco pra
        sobreviver a um restart."""
        engine = (engine or "").strip()
        if engine not in self._VALID_TEXT_ENGINES:
            return {
                "ok": False,
                "error": f"Engine de texto inválido: '{engine}'. Use um de: {', '.join(self._VALID_TEXT_ENGINES)}.",
            }

        path = _paths_module.TEXT_ENGINE_PREFERENCE_FILE
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"engine": engine}), encoding="utf-8")
        except Exception as e:
            logger.error(f"ResidentManager: falha ao persistir preferência de engine de texto: {e}")
            return {"ok": False, "error": f"Falha ao salvar preferência em disco: {e}"}

        self._text_engine_preference = engine
        self.reasoning.text_engine_hint = "" if engine == "llama.cpp" else engine
        self.logs.add_event("INFO", "TextEngineBridge", f"Engine de texto trocado para '{engine}'.")
        return {"ok": True, "engine": engine}

    async def analyze_machine(self) -> str:
        """Coleta specs do State, faz a leitura completa de sensores, pede ao 
        Planner (RAG) uma sugestão de plano."""
        logger.info("ResidentManager: Iniciando análise de máquina...")
        state_data = await self.state.get_state()

        if "error" in state_data:
            return "Sistema ainda inicializando. Aguarde o Discovery concluir."

        hw = state_data.get("hardware", {})
        budget = state_data.get("budget", {})

        loop = asyncio.get_running_loop()
        try:
            devices = await loop.run_in_executor(None, _hardware_core.get_all_hardware_sensors)
        except Exception as e:
            logger.warning(f"ResidentManager: falha ao ler sensores completos - {e}")
            devices = []

        alerts = self._check_device_alerts(devices)

        query = f"Melhor configuração LLM para {hw.get('gpu', 'CPU')} com {hw.get('vram_mb', 0)}MB VRAM"
        # PHX-FIX (auditoria 2026-08-04): query_knowledge() é síncrono e
        # retorna list[str] — o "await" aqui levantava TypeError sem
        # nenhum try/except ao redor, derrubando analyze_hardware() toda
        # vez que era chamado. O código abaixo também presumia um dict
        # (.get('name'/'notes')), que nunca correspondeu ao formato real.
        try:
            rag_hits = self.planner.knowledge.query_knowledge(query)
        except Exception as e:
            logger.warning(f"ResidentManager: falha ao consultar RAG ({e}).")
            rag_hits = []

        report = "🔍 PHOENIX RESIDENT MANAGER - ANÁLISE DE HARDWARE 🔍\n\n"
        report += f"CPU: {hw.get('cpu', 'N/A')}\n"
        report += f"RAM: {hw.get('ram_mb', 0)} MB\n"
        report += f"GPU: {hw.get('gpu', 'N/A')} ({hw.get('vram_mb', 0)} MB VRAM)\n"
        report += f"Backends: {', '.join(hw.get('backends', []))}\n"
        report += f"Classe da Máquina: {budget.get('class', 'Unknown')} (Score: {budget.get('score', 0)}%)\n\n"

        report += f"📡 SCANNER COMPLETO: {len(devices)} dispositivo(s) ativo(s) lido(s)\n"
        if alerts:
            report += "⚠️ ALERTAS DE SENSOR:\n"
            for a in alerts:
                report += f"- {a['device']} / {a['sensor_name']}: {a['value']:.0f}{a['unit']} (acima de {a['threshold']:.0f}{a['unit']})\n"
        else:
            report += "Nenhum sensor fora da faixa normal no momento.\n"
        report += "\n"

        report += "💡 SUGESTÃO DE PLANO (Baseado no histórico RAG):\n"
        if rag_hits:
            report += "Baseado em testes anteriores, recomenda-se:\n"
            for hit in rag_hits:
                report += f"- {hit}\n"
        else:
            report += "Nenhuma recomendação histórica exata encontrada. Plano padrão: Instalar Ollama e OpenWebUI.\n"

        report += "\n⚠️ Nenhuma ação de execução foi tomada. A Phoenix apenas pensou."
        return report

    @staticmethod
    def _check_device_alerts(devices: list) -> list:
        alerts = []
        for dev in devices:
            for s in dev.get("sensors", []):
                if s["type"] == "Temperature" and s["value"] >= HOT_TEMP_C:
                    alerts.append({
                        "device": dev["name"], "sensor_name": s["name"], "sensor_type": s["type"],
                        "value": s["value"], "unit": "°C", "threshold": HOT_TEMP_C,
                    })
                elif s["type"] == "Load" and s["value"] >= HIGH_LOAD_PCT:
                    alerts.append({
                        "device": dev["name"], "sensor_name": s["name"], "sensor_type": s["type"],
                        "value": s["value"], "unit": "%", "threshold": HIGH_LOAD_PCT,
                    })
        return alerts

    async def _thermal_guard(self, context: str) -> None:
        """PHX-FIX: checagem térmica não-bloqueante antes de passos pesados de
        GPU (ex: GENERATE_IMAGE). Não aborta a missão - só avisa no log, já
        que decidir "abortar por causa de temperatura" é uma decisão do
        usuário, não do Resident Manager."""
        try:
            loop = asyncio.get_running_loop()
            devices = await loop.run_in_executor(None, _hardware_core.get_all_hardware_sensors)
            alerts = self._check_device_alerts(devices)
            gpu_alerts = [a for a in alerts if "gpu" in a["device"].lower() or "radeon" in a["device"].lower()]
            if gpu_alerts:
                for a in gpu_alerts:
                    self.logs.add_event(
                        "WARNING", "MissionExecutor",
                        f"⚠️ {context}: {a['device']} / {a['sensor_name']} em {a['value']:.0f}{a['unit']} "
                        f"(limite {a['threshold']:.0f}{a['unit']}) - prosseguindo mesmo assim."
                    )
        except Exception as e:
            logger.warning(f"ResidentManager: guarda térmica falhou ao ler sensores - {e}")

    # ============================================================
    # PHX-NEW (Fase 3 - Hot-Swap): rastreamento de modelo ativo + guarda
    # de VRAM. Antes de tudo isso, o ResidentManager não tinha nenhuma
    # noção própria de "o que está carregado agora" - dependia do LLM
    # informar from_runtime na missão. Isso serve pra duas coisas: (1)
    # decidir se vale a pena parar algo antes de subir um modelo novo
    # pesado, (2) no futuro, expor "o que está ativo" no /api/state pra
    # UI sem inventar número nenhum.
    # ============================================================

    def set_ahde(self, ahde) -> None:
        """Injeta o facade do AHDE depois da construção - no kernel.py o
        AHDE só existe depois do ResidentManager (mesma ordem que já
        obriga state.py a ter seu próprio set_ahde()). Chamado uma vez no
        boot(); nada quebra se nunca for chamado - _vram_guard() trata
        self.ahde is None como "sem dado, não bloqueia"."""
        self.ahde = ahde

    def _track_model_loaded(self, runtime: str, model_id: str) -> None:
        previous = self._active_models.get(runtime)
        self._active_models[runtime] = model_id
        if previous and previous != model_id:
            self.logs.add_event("INFO", "ModelTracking", f"Runtime '{runtime}': '{previous}' -> '{model_id}'.")
        else:
            self.logs.add_event("INFO", "ModelTracking", f"Runtime '{runtime}': '{model_id}' marcado como ativo.")

    def _track_model_unloaded(self, runtime: str) -> None:
        previous = self._active_models.pop(runtime, None)
        if previous:
            self.logs.add_event("INFO", "ModelTracking", f"Runtime '{runtime}': '{previous}' descarregado.")

    def get_active_models(self) -> dict:
        """Snapshot de {runtime: model_id} de tudo que este ResidentManager
        rastreou como carregado. Não é uma verdade absoluta (nada aqui
        consulta o SO pra confirmar que o processo realmente está de pé -
        é só o que ELE mesmo pediu pra carregar/descarregar), mas é a
        única fonte melhor que "nada" que existia antes da Fase 3."""
        return dict(self._active_models)

    def _get_vram_budget_mb(self) -> tuple[int | None, int | None]:
        """Lê (vram_total_mb, vram_used_mb) dos snapshots do AHDE.

        Nomes de campo confirmados auditando contracts.py + kernel.py de verdade:
        - HardwareSnapshot.hardware é o hw_data bruto do discovery (flat dict).
          VRAM total fica em hardware["gpus"][0]["vram_mb"] (discovery_core.py linha 89).
        - TelemetrySnapshot.telemetry é o dict mapeado por _map_telemetry_for_ahde().
          VRAM usada fica em telemetry["vram_used_mb"] (kernel.py linha 347:
          merged["vram_used_mb"] = live_metrics.get("gpu_vram_used")).

        Antes desta correção, o código buscava por atributos diretos no objeto
        snapshot (ex: snapshot.vram_mb) - mas HardwareSnapshot e TelemetrySnapshot
        não têm esses atributos: os dados ficam dentro dos campos .hardware e
        .telemetry (ambos Dict[str, Any], ver contracts.py). Resultado: total_mb
        e used_mb sempre voltavam None, o guard nunca protegia nada de verdade."""
        if self.ahde is None:
            return None, None

        total_mb = None
        used_mb = None
        try:
            # VRAM total: hardware["gpus"][0]["vram_mb"] (confirmado em
            # discovery_core.py e telemetry/core.py - campo "vram_mb" em MB)
            hw_snapshot = self.ahde.get_latest_hardware_snapshot()
            if hw_snapshot is not None:
                hw_dict = hw_snapshot.hardware if hasattr(hw_snapshot, "hardware") else {}
                gpus = hw_dict.get("gpus", []) if isinstance(hw_dict, dict) else []
                if gpus and isinstance(gpus[0], dict):
                    val = gpus[0].get("vram_mb")
                    if val is not None:
                        total_mb = int(val)

            # VRAM usada: telemetry["vram_used_mb"] (confirmado em
            # kernel._map_telemetry_for_ahde: merged["vram_used_mb"] =
            # live_metrics.get("gpu_vram_used"))
            tel_snapshot = self.ahde.get_latest_telemetry_snapshot()
            if tel_snapshot is not None:
                tel_dict = tel_snapshot.telemetry if hasattr(tel_snapshot, "telemetry") else {}
                if isinstance(tel_dict, dict):
                    val = tel_dict.get("vram_used_mb")
                    if val is not None:
                        used_mb = int(val)

        except Exception as e:
            logger.warning(f"ResidentManager: falha ao ler VRAM do AHDE - {e}")
            return None, None

        if total_mb is None or used_mb is None:
            logger.warning(
                f"ResidentManager: AHDE disponível mas não leu VRAM "
                f"(total_mb={total_mb}, used_mb={used_mb}). "
                f"Verifique se discovery e telemetry já rodaram ao menos um ciclo."
            )
        return total_mb, used_mb

    async def _vram_guard(self, context: str, target_runtime: str, target_model_id: str, vram_mb_needed: int) -> None:
        """Guarda de VRAM não-bloqueante (mesmo espírito do
        _thermal_guard: avisa, não impede - decidir travar de vez fica
        pra depois de observar isso em uso real). Se detectar que não
        cabe o modelo novo com o que já está ativo, tenta liberar espaço
        parando o que está rodando em runtimes GPU-pesados diferentes do
        alvo (hoje isso é só 'sdxl' - 'llama.cpp' e 'vision' ficam de fora
        de propósito, são CPU por decisão de design, nunca ocupam VRAM; ver
        catalog/models.json onde vram_mb_estimate=0 pros modelos de chat E
        pro minicpmv/vision).

        PHX-FIX (2026-08-28): 'vision' chegou a fazer parte de
        GPU_HEAVY_RUNTIMES (achado de 2026-08-20, quando minicpmv ainda
        declarava vram_mb_estimate=6500 no catálogo). Ficou desatualizado
        quando a Política de roteamento de hardware definitiva (ver README)
        passou a forçar -ngl 0 (CPU) no driver de visão, reservando 100% da
        GPU pra geração de imagem - o guard achava que precisava abrir
        ~6,5GB de VRAM pra descrever uma imagem e podia descarregar um
        modelo de imagem já carregado à toa, já que a análise nunca toca a
        GPU de verdade. Removido de GPU_HEAVY_RUNTIMES; catalog/models.json
        e este guard concordam agora: vision é CPU, vram_mb_needed=0 vira
        no-op abaixo, igual chat.

        Se vram_mb_needed for 0 (modelo roda em CPU, ex: chat/vision), a
        guarda nem executa - não há o que proteger."""
        if not vram_mb_needed:
            return
        if self.ahde is None:
            self.logs.add_event(
                "INFO", "VRAMGuard",
                f"{context}: AHDE não injetado ainda - seguindo sem checar VRAM livre."
            )
            return

        total_mb, used_mb = self._get_vram_budget_mb()
        if total_mb is None or used_mb is None:
            return  # já logou o motivo em _get_vram_budget_mb()

        free_mb = total_mb - used_mb
        if free_mb >= vram_mb_needed:
            self.logs.add_event(
                "INFO", "VRAMGuard",
                f"{context}: {free_mb}MB livres, precisa de ~{vram_mb_needed}MB pra '{target_model_id}'. OK."
            )
            return

        # Não cabe do jeito que está - procura algo pra descarregar entre
        # os runtimes GPU-pesados que não sejam o próprio alvo.
        # PHX-FIX (2026-08-28): "vision" removido deste conjunto - ver
        # comentário completo no docstring de _vram_guard() acima.
        GPU_HEAVY_RUNTIMES = {"sdxl"}
        candidates = [
            (rt, model) for rt, model in self._active_models.items()
            if rt in GPU_HEAVY_RUNTIMES and rt != target_runtime
        ]

        if not candidates:
            self.logs.add_event(
                "INFO", "VRAMGuard",
                f"{context}: AHDE reporta {free_mb}MB livres para ~{vram_mb_needed}MB, "
                "mas o lifecycle cleanup já encerrou os runtimes gerenciados; "
                "a telemetria pode estar atrasada."
            )
            return

        for rt, model in candidates:
            self.logs.add_event(
                "WARNING", "VRAMGuard",
                f"{context}: só {free_mb}MB livres, precisa de ~{vram_mb_needed}MB pra '{target_model_id}'. "
                f"Descarregando '{model}' (runtime '{rt}') pra liberar espaço."
            )
            try:
                await self.runtime.stop(rt)
                self._track_model_unloaded(rt)
            except Exception as e:
                logger.warning(f"ResidentManager: VRAMGuard falhou ao parar runtime '{rt}' - {e}")

    # ============================================================
    # PHX-FIX: DESCOBERTA DE MODELO NO DISCO (não confia no LLM)
    # ============================================================
    #
    # Antes disso, GENERATE_IMAGE simplesmente pegava `step.target` — o
    # nome do modelo que o LLM colocou no plano — e mandava direto pro
    # SdCppDriver. Problema: o LLM "lembra" de modelos por texto, não vê
    # o disco. Ele podia planejar "sdxl" numa sessão onde o único modelo
    # de imagem baixado de verdade era FLUX (ou o contrário), e a missão
    # falhava tentando rodar um arquivo que nunca existiu.
    #
    # A regra nova é simples: ENXERGAR primeiro, SETAR depois.
    # 1. Escaneia a pasta de modelos de Imagem no disco de verdade.
    # 2. Se o que o LLM pediu bate com algo já baixado -> usa esse.
    # 3. Se não bate mas existe ALGO baixado -> usa o mais recente
    #    (assume que foi o último que o usuário baixou de propósito).
    # 4. Só se não tiver NADA no disco é que aciona o download.

    def _discover_installed_image_models(self) -> list[dict]:
        """Enxerga o que já foi baixado de verdade, escaneando o disco."""
        try:
            image_dir = PhoenixPaths.get_category_path("Image")
        except Exception as e:
            logger.warning(f"ResidentManager: falha ao resolver pasta 'Image' - {e}")
            return []

        if not image_dir.exists():
            return []

        # PHX-FIX (achado real investigando "onde o py baixa cada modelo de
        # imagem?" do usuário): este scan só olhava "*.gguf" - mas o
        # download DEFAULT de SDXL no catálogo (catalog/assets/sdxl.json,
        # "sd_xl_base_1.0.safetensors") e o de DreamShaper XL
        # (catalog/assets/dreamshaperXL_v2Turbo.json) são os DOIS em
        # .safetensors, não .gguf. SdCppDriver._find_model_file() (sd_cpp.py)
        # já procura ".gguf" E ".safetensors" no disco - mas esta função,
        # usada tanto pela ponte direta do chat quanto pelo passo
        # GENERATE_IMAGE de missão pra decidir "já tem algo instalado?",
        # nunca via os arquivos .safetensors. Resultado prático: baixar o
        # SDXL Base 1.0 (ou o DreamShaper XL) do jeito que o próprio
        # catálogo oferece deixaria o modelo PARA SEMPRE invisível pra
        # _resolve_image_model_target() - "Nenhum modelo de imagem
        # instalado no disco ainda" mesmo com o arquivo genuinamente lá,
        # baixado com sucesso. Agora escaneia as duas extensões, igual o
        # driver que de fato carrega o arquivo.
        found = []
        for model_file in list(image_dir.rglob("*.gguf")) + list(image_dir.rglob("*.safetensors")):
            name_lower = model_file.stem.lower()
            arch = "unknown"
            for arch_name, keywords in _IMAGE_ARCH_PATTERNS.items():
                if any(kw in name_lower for kw in keywords):
                    arch = arch_name
                    break
            try:
                mtime = model_file.stat().st_mtime
            except OSError:
                mtime = 0.0
            found.append({"path": model_file, "name": model_file.stem, "architecture": arch, "mtime": mtime})

        # Mais recente primeiro - se tem mais de um modelo de imagem
        # instalado, o mais recentemente baixado é o candidato mais provável
        # a ser "o que o usuário quer usar agora".
        found.sort(key=lambda f: f["mtime"], reverse=True)
        return found

    def _resolve_image_model_target(self, step_target: str) -> tuple[str | None, str]:
        """Decide qual modelo de imagem vai ser usado de verdade.

        Retorna (nome_do_modelo_ou_None, mensagem_explicando_a_decisão).
        `None` significa "nada disso está instalado, alguém precisa baixar".
        """
        # PHX-FIX: arquivos de componente (vae/clip/text-encoder) nunca são
        # candidatos a "o modelo principal" - ver _looks_like_component_file
        # acima. Sem este filtro, "sdxl_vae-fp16-fix" (o VAE) podia ser
        # escolhido como "o modelo" no lugar do checkpoint real.
        installed = [
            m for m in self._discover_installed_image_models()
            if not _looks_like_component_file(m["name"].lower())
        ]
        clean_target = (step_target or "").split(":")[0].replace("/", "-").lower()

        # 1. O que o plano pediu já está instalado? Usa sem drama.
        # PHX-FIX: aceita match tanto por substring cru no nome do arquivo
        # (comportamento antigo - cobre hints tipo "dreamshaper" que batem
        # direto num nome de arquivo) QUANTO pela arquitetura já
        # classificada em _IMAGE_ARCH_PATTERNS (cobre hints que são um id
        # de catálogo, tipo "sdxl", que não bate como substring cru no
        # nome real do arquivo baixado - "sd_xl_base_1.0" tem underscore,
        # "sdxl" não - mas _IMAGE_ARCH_PATTERNS já reconhece isso via a
        # keyword "xl_base").
        for model in installed:
            if clean_target and (clean_target in model["name"].lower() or clean_target == model["architecture"]):
                return model["name"], f"'{model['name']}' já está instalado e bate com o plano."

        # 2. Não bate, mas existe ALGUMA coisa de imagem já baixada no disco.
        # Em vez de tentar rodar um arquivo fantasma que o LLM inventou,
        # usa o que realmente existe.
        if installed:
            chosen = installed[0]
            return chosen["name"], (
                f"plano pedia '{step_target}', mas isso não está no disco. "
                f"Usando '{chosen['name']}' (modelo de imagem já instalado, mais recente) em vez disso."
            )

        # 3. Nada instalado de verdade. Quem chamou decide se baixa.
        return None, f"nenhum modelo de imagem encontrado no disco (plano pedia '{step_target}')."

    # PHX-FIX (2026-08-22, achado real: usuário reportou "foi usado
    # somente flux porque é o unico modelo baixado" - queria saber por que
    # o seletor "IMAGEM" do chat (ChatView.tsx) não refletia o que
    # realmente está no disco): o backend JÁ sabia enxergar o disco de
    # verdade (_discover_installed_image_models(), usado desde a resolução
    # automática em _resolve_image_model_target()) - mas nada expunha essa
    # lista pro frontend. O seletor da UI continuava sendo 3 opções FIXAS
    # e hardcoded ("Auto (Flux)"/"SDXL"/"SD 1.5", ver ChatView.tsx ~linha
    # 374), escritas quando o usuário só tinha esses 3 baixados - qualquer
    # outro modelo de imagem (Kontext, Flux2, Juggernaut, DreamShaper,
    # etc. - o SdCppDriver/sd_cpp.py já tem perfis pra vários desses) fica
    # invisível na UI mesmo estando genuinamente baixado e utilizável.
    # Este método é a versão PÚBLICA e "limpa" (sem Path, só o que a UI
    # precisa) da mesma descoberta - reaproveita _discover_installed_image_models()
    # e o mesmo filtro de arquivo-de-componente (vae/clip/text-encoder) já
    # usado por _resolve_image_model_target(), pra nunca listar um VAE como
    # se fosse "um modelo".
    def list_installed_image_models(self) -> list[dict]:
        """Lista os modelos de imagem realmente encontrados em disco (mais
        recente primeiro), no formato que a UI precisa: nome do arquivo
        (sem extensão) e a arquitetura já classificada (flux/sdxl/sd15/
        unknown). Nunca inclui arquivo de componente (vae/clip/t5xxl)."""
        installed = [
            m for m in self._discover_installed_image_models()
            if not _looks_like_component_file(m["name"].lower())
        ]
        return [{"name": m["name"], "architecture": m["architecture"]} for m in installed]

    # ============================================================
    # DESCOBERTA DE VOZES INSTALADAS (Piper) — mesmo padrão do bloco
    # de imagem acima: ENXERGAR o disco primeiro, nunca assumir.
    # ============================================================

    def _discover_installed_voices(self) -> list[dict]:
        """Enxerga quais vozes Piper (.onnx + .onnx.json) já foram
        baixadas de verdade, escaneando o disco."""
        try:
            voice_dir = PhoenixPaths.get_category_path("Voice", "Piper")
        except Exception as e:
            logger.warning(f"ResidentManager: falha ao resolver pasta 'Voice/Piper' - {e}")
            return []

        if not voice_dir.exists():
            return []

        found = []
        for onnx_file in voice_dir.rglob("*.onnx"):
            config_path = onnx_file.with_suffix(onnx_file.suffix + ".json")
            if not config_path.exists():
                continue  # par incompleto - piper exige os dois arquivos
            try:
                mtime = onnx_file.stat().st_mtime
            except OSError:
                mtime = 0.0
            found.append({"path": onnx_file, "name": onnx_file.stem, "mtime": mtime})

        found.sort(key=lambda f: f["mtime"], reverse=True)
        return found

    def _resolve_voice_target(self, voice_hint: str) -> tuple[str | None, str]:
        """Decide qual voz Piper vai ser usada de verdade — mesma lógica de
        3 passos de _resolve_image_model_target (bate com o pedido -> usa;
        não bate mas tem algo instalado -> usa o mais recente; nada
        instalado -> None pra quem chamou decidir)."""
        installed = self._discover_installed_voices()
        clean_hint = (voice_hint or "").split(":")[0].lower()

        for voice in installed:
            if clean_hint and clean_hint in voice["name"].lower():
                return voice["name"], f"'{voice['name']}' já está instalada e bate com o pedido."

        if installed:
            chosen = installed[0]
            return chosen["name"], (
                f"pedido era '{voice_hint}', mas essa voz não está no disco. "
                f"Usando '{chosen['name']}' (voz Piper mais recente instalada) em vez disso."
            )

        return None, f"nenhuma voz Piper encontrada no disco (pedido era '{voice_hint}')."

    # ============================================================
    # INTEGRAÇÃO REASONING ENGINE (O CÉREBRO)
    # ============================================================

    async def process_intent(self, intent: str) -> dict:
        """Recebe a intenção do usuário, pede ao LLM para pensar e devolve o plano."""
        mission = await self.reasoning.plan_mission(intent)

        if not mission:
            # PHX-NEW: sem missão, mas o LLM gerou uma resposta direta
            # (campo "response" do JSON - ver reasoning_engine.py). Enfileira
            # pro Chat WebUI (porta 3000) consumir via /api/chat/pending, em
            # vez de tratar como erro.
            direct_response = getattr(self.reasoning, "last_response", None)
            if direct_response:
                self.pending_chat_messages.append({"content": direct_response, "model": "phoenix-resident"})
                self.logs.add_event("INFO", "ResidentManager", "Resposta direta enfileirada para o Chat WebUI.")
                return {"output": direct_response}

            # PHX-FIX: Expõe o motivo real (guardado pelo ReasoningEngine em
            # last_error) em vez da mensagem genérica que escondia se o
            # llama-cli realmente falhou, deu timeout, ou devolveu algo que
            # não era JSON.
            detail = getattr(self.reasoning, "last_error", None) or "motivo desconhecido"
            return {"output": f"[ERRO] O cérebro (LLM) não respondeu: {detail}"}

        self._mission_kernel.register(mission)
        self._active_mission = mission  # espelho para get_status()

        return {
            "output": f"Plano criado: {mission.metadata.get('llm_reasoning', '')}\nAguardando aprovação.",
            "mission": mission.to_dict()
        }

    async def approve_and_execute(self) -> dict:
        """Aprova a missão pendente e aciona a execução em Background."""
        try:
            mission = self._mission_kernel.approve_active_mission()
        except NoActiveMissionError:
            return {"output": "Nenhuma missão pendente para aprovação."}

        mission.status = MissionStatus.RUNNING

        # Dispara a execução em segundo plano para não travar o terminal do painel
        asyncio.create_task(self._execute_mission_background(mission))

        self._active_mission = None
        self._mission_kernel._active = None  # limpa o portao apos despachar

        return {
            "output": f"✅ Missão aprovada! O Kernel iniciou a execução de {len(mission.steps)} passo(s) em segundo plano.\nDigite 'logs' para acompanhar o progresso."
        }

    async def _execute_mission_background(self, mission):
        """Executa os passos da missão acionando o ServicesEngine real."""
        mission_start = time.monotonic()
        self.logs.add_event("INFO", "MissionKernel", f"Iniciando execução da missão: {mission.intent}")

        for step in mission.steps:
            step_start = time.monotonic()
            step_log_msg = f"[Passo {step.step}] {step.description} (Ação: {step.action.value}, Alvo: {step.target})"
            self.logs.add_event("INFO", "MissionExecutor", step_log_msg)
            logger.info(f"[MissionExecutor] {step_log_msg}")

            try:
                if step.action == MissionAction.VALIDATE_ENVIRONMENT:
                    env_status = await self.services.get_environment_status()
                    is_ok = env_status.get(step.target.lower(), False)
                    if not is_ok:
                        self.logs.add_event("WARNING", "MissionExecutor", f"Alvo '{step.target}' não está pronto. Tentando instalar...")
                        await self.services.install_service(step.target.lower())

                elif step.action == MissionAction.INSTALL_PACKAGE:
                    result = await self.services.install_service(step.target.lower())
                    self.logs.add_event("INFO", "MissionExecutor", f"Resultado: {result}")

                elif step.action == MissionAction.DOWNLOAD_MODEL:
                    # PHX-FIX: só baixa se REALMENTE não tiver nada
                    # equivalente já instalado. Antes ele baixava sem
                    # checar disco, então rodar a mesma missão duas vezes
                    # baixava o mesmo modelo duas vezes.
                    if _is_image_model_target(step.target):
                        resolved, note = self._resolve_image_model_target(step.target)
                        self.logs.add_event("INFO", "MissionExecutor", f"Verificação no disco: {note}")
                        if resolved is not None:
                            self.logs.add_event("INFO", "MissionExecutor", f"'{resolved}' já está instalado. Pulando download.")
                            step_elapsed = time.monotonic() - step_start
                            self.logs.add_event("INFO", "MissionExecutor", f"[Passo {step.step}] concluído em {step_elapsed:.1f}s.")
                            continue

                    self.logs.add_event("INFO", "MissionExecutor", f"AssetManager: Baixando modelo '{step.target}'...")
                    result = await asyncio.to_thread(self.asset_manager.get_asset, step.target)
                    if result is None:
                        # PHX-FIX (auditoria 2026-08-20, Seção 14): antes só
                        # dizia "falha ao baixar" - agora inclui o motivo
                        # classificado (401/403 exige autenticação, 404 link
                        # morto, etc.) que o AssetManager guardou em
                        # last_error, então dá pra saber SEM abrir log em
                        # nível DEBUG o que realmente aconteceu.
                        reason = self.asset_manager.last_error or f"(ver catalog/assets/{step.target}.json)"
                        self.logs.add_event("ERROR", "MissionExecutor", f"AssetManager: falha ao baixar '{step.target}' - {reason}. Missão interrompida neste passo.")
                        break
                    self.logs.add_event("INFO", "MissionExecutor", f"Resultado: {result}")

                elif step.action == MissionAction.SWITCH_RUNTIME:
                    target_runtime = step.target.lower() if step.target else "llama.cpp"
                    from_runtime = step.metadata.get("from_runtime") if hasattr(step, "metadata") and step.metadata else None

                    if from_runtime:
                        self.logs.add_event("INFO", "MissionExecutor", f"RuntimeEngine: Parando '{from_runtime}'...")
                        await self.runtime.stop(from_runtime)
                        self._track_model_unloaded(from_runtime)

                    plan_params = step.metadata.get("plan") if hasattr(step, "metadata") and step.metadata else None
                    self.logs.add_event("INFO", "MissionExecutor", f"RuntimeEngine: Iniciando '{target_runtime}'...")
                    success = await self.runtime.start(target_runtime, plan_params)

                    if not success:
                        self.logs.add_event("ERROR", "MissionExecutor", f"Falha ao iniciar '{target_runtime}'. Missão interrompida neste passo.")
                        break
                    self._track_model_loaded(target_runtime, (plan_params or {}).get("model", target_runtime) if isinstance(plan_params, dict) else target_runtime)
                    self.logs.add_event("INFO", "MissionExecutor", f"RuntimeEngine: '{target_runtime}' ativo com sucesso.")

                elif step.action == MissionAction.LOAD_MODEL:
                    # PHX-NEW: troca o modelo de TEXTO carregado no mesmo
                    # runtime (llama.cpp), diferente de SWITCH_RUNTIME (que
                    # troca de MOTOR - llama.cpp vs sdxl vs piper). Depende
                    # do fix em LlamaCppDriver.start() que agora compara o
                    # arquivo do modelo pedido com o que já está carregado
                    # antes de decidir se recarrega - sem isso, esta ação
                    # seria um no-op se já houvesse qualquer processo de pé.
                    if self.runtime is None:
                        self.logs.add_event("ERROR", "MissionExecutor", "RuntimeEngine não disponível (não injetado no ResidentManager). Troca de modelo abortada.")
                        break

                    target_model = step.target
                    target_runtime = (step.parameters or {}).get("runtime", "llama.cpp")

                    plan = ExecutionPlan(
                        runtime=target_runtime, model=target_model, parameters={},
                        reasoning=step.description or f"Carregar modelo '{target_model}'",
                    )
                    self.logs.add_event("INFO", "MissionExecutor", f"RuntimeEngine: carregando modelo '{target_model}' em '{target_runtime}'...")
                    success = await self.runtime.start(target_runtime, plan)

                    if not success:
                        self.logs.add_event("ERROR", "MissionExecutor", f"Falha ao carregar modelo '{target_model}'. Missão interrompida neste passo.")
                        break
                    self._track_model_loaded(target_runtime, target_model)
                    self.logs.add_event("INFO", "MissionExecutor", f"Modelo '{target_model}' carregado com sucesso em '{target_runtime}'.")

                elif step.action == MissionAction.UNLOAD_MODEL:
                    # PHX-NEW: libera o modelo de texto atualmente carregado
                    # (RAM/VRAM) sem carregar outro no lugar - útil quando a
                    # missão termina uma tarefa pesada e não precisa manter
                    # nada residente até a próxima intenção do usuário.
                    if self.runtime is None:
                        self.logs.add_event("ERROR", "MissionExecutor", "RuntimeEngine não disponível (não injetado no ResidentManager). Descarregar modelo abortado.")
                        break

                    target_runtime = step.target.lower() if step.target else "llama.cpp"
                    self.logs.add_event("INFO", "MissionExecutor", f"RuntimeEngine: descarregando '{target_runtime}'...")
                    await self.runtime.stop(target_runtime)
                    self._track_model_unloaded(target_runtime)
                    self.logs.add_event("INFO", "MissionExecutor", f"'{target_runtime}' descarregado - memória liberada.")

                elif step.action == MissionAction.GENERATE_IMAGE:
                    if self.runtime is None:
                        self.logs.add_event("ERROR", "MissionExecutor", "RuntimeEngine não disponível (não injetado no ResidentManager). Geração de imagem abortada.")
                        break

                    # PHX-FIX: checa temperatura/carga da GPU antes de disparar
                    # a etapa mais pesada da missão (não bloqueia, só avisa).
                    await self._thermal_guard("Antes de gerar imagem")

                    # PHX-FIX (o núcleo desta mudança): não confia mais
                    # cegamente em `step.target`. Enxerga o disco primeiro.
                    # Isso resolve o caso "baixou FLUX, plano ainda quer
                    # rodar sdxl/SD1.5" (ou o oposto) - o Executor agora usa
                    # o que está de fato instalado, e só chama o
                    # ModelManager se realmente não achar nada.
                    resolved_model, resolution_note = self._resolve_image_model_target(step.target)
                    self.logs.add_event("INFO", "MissionExecutor", f"Resolução de modelo de imagem: {resolution_note}")

                    if resolved_model is None:
                        self.logs.add_event(
                            "WARNING", "MissionExecutor",
                            f"Nenhum modelo de imagem instalado. Baixando '{step.target}' antes de gerar..."
                        )
                        download_result = await asyncio.to_thread(self.asset_manager.get_asset, step.target)
                        if download_result is None:
                            # PHX-FIX (auditoria 2026-08-20, Seção 14): mesmo
                            # motivo classificado de last_error usado acima
                            # em DOWNLOAD_MODEL.
                            reason = self.asset_manager.last_error or f"(ver catalog/assets/{step.target}.json)"
                            self.logs.add_event("ERROR", "MissionExecutor", f"AssetManager: falha ao baixar '{step.target}' - {reason}. Geração de imagem abortada.")
                            break
                        resolved_model = step.target

                    # PHX-NEW (Fase 3 - Hot-Swap): checa VRAM livre e libera
                    # espaço de outro runtime GPU-pesado se precisar, ANTES
                    # de disparar a geração (guarda não-bloqueante - só avisa
                    # se não conseguir liberar o suficiente).
                    _image_capacity = self.registry.resolve("image_generation", hint=resolved_model)

                    # Cleanup vem ANTES da telemetria/VRAMGuard.
                    if hasattr(self.runtime, "prepare_exclusive"):
                        await self.runtime.prepare_exclusive("sdxl")

                    await self._vram_guard(
                        "Antes de gerar imagem (missão)", "sdxl", resolved_model,
                        _image_capacity.vram_mb_estimate if _image_capacity else 0,
                    )

                    prompt = (step.parameters or {}).get("prompt", "A beautiful cyberpunk city, highly detailed")
                    plan = ExecutionPlan(
                        runtime="sdxl",  # Chama o SdCppDriver (Stable Diffusion), NÃO o llama.cpp
                        model=resolved_model,
                        parameters={"prompt": prompt},
                        reasoning=step.description,
                    )
                    # Log explícito para provar que não está usando o LLM (llama.cpp) para gerar imagem
                    self.logs.add_event("INFO", "MissionExecutor", f"RuntimeEngine (Stable Diffusion): gerando imagem com '{resolved_model}' na GPU (prompt: \"{prompt}\")...")
                    result = await self.runtime.execute(plan)

                    if result.status != ExecutionStatus.SUCCESS:
                        self.logs.add_event("ERROR", "MissionExecutor", f"Falha ao gerar imagem: {result.errors}. Missão interrompida neste passo.")
                        break
                    self._track_model_loaded("sdxl", resolved_model)
                    self.logs.add_event("INFO", "MissionExecutor", f"Resultado: {result.output}")

                else:
                    self.logs.add_event("WARNING", "MissionExecutor", f"Ação {step.action.value} ainda não implementada no Executor.")

            except Exception as e:
                err_msg = f"Falha crítica no passo {step.step}: {str(e)}"
                self.logs.add_event("ERROR", "MissionExecutor", err_msg)
                logger.error(f"[MissionExecutor] {err_msg}")
                break

            # PHX-FIX: telemetria de duração por passo - antes não dava pra
            # saber quanto cada etapa custou, só que "rodou".
            step_elapsed = time.monotonic() - step_start
            self.logs.add_event("INFO", "MissionExecutor", f"[Passo {step.step}] concluído em {step_elapsed:.1f}s.")

        mission_elapsed = time.monotonic() - mission_start
        self.logs.add_event("INFO", "MissionKernel", f"Execução da missão concluída em {mission_elapsed:.1f}s.")

    # ============================================================
    # PONTE DIRETA (Opção B2): geração de imagem síncrona, sem passar
    # pelo Mission Kernel / aprovação. Chamada pelo endpoint HTTP
    # POST /api/generate-image, usado pelo Chat WebUI do Phoenix Aviary.
    #
    # Reaproveita a MESMA lógica do passo GENERATE_IMAGE de dentro de uma
    # missão normal (_resolve_image_model_target, _thermal_guard,
    # runtime.execute) — não duplica regra nenhuma, só pula o
    # think/aprovar/rejeitar pra ficar síncrono o suficiente pra um chat.
    # ============================================================
    async def generate_image_direct(self, prompt: str, model_hint: str = "") -> dict:
        """Gera uma imagem AGORA, sem aprovação de missão. Retorna um dict
        com sucesso/erro e o caminho do arquivo gerado (se houver)."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "Prompt vazio."}

        await self._thermal_guard("Antes de gerar imagem (ponte direta)")

        # PHX-NEW (Fase 2): "flux" hardcoded virou registry.resolve() -
        # ainda cai no mesmo default (Flux é default_for_roles de
        # image_generation no catalog/models.json), mas agora é
        # declarativo, não um literal solto no meio da lógica.
        default_image_model = self.registry.resolve("image_generation", hint=model_hint)
        # PHX-FIX (2026-08-22, achado real ao investigar "foi usado somente
        # flux porque é o unico modelo baixado"): `registry.resolve()`
        # NUNCA devolve None enquanto o catálogo tiver pelo menos um modelo
        # pra role 'image_generation' (e sempre tem - flux/sdxl/sd15) -
        # então a linha antiga `default_image_model.id if default_image_model
        # else (model_hint or "flux")` na prática SEMPRE usava
        # `default_image_model.id`, nunca o `model_hint` cru. Resultado:
        # se o usuário escolhesse um modelo de imagem que existe de
        # verdade no disco mas cujo nome de arquivo não bate com nenhum
        # `file_patterns` do catálogo (ex: um modelo baixado manualmente,
        # ou qualquer arquitetura fora de flux/sdxl/sd15), o
        # `ModelRegistry.resolve()` caía no `default_for_roles` (Flux) - a
        # escolha do usuário era descartada silenciosamente, e o alvo da
        # busca em disco virava sempre "flux", nunca o hint pedido. Como
        # `_resolve_image_model_target()` já faz sozinho o trabalho de
        # "bate com o hint? usa. não bate mas tem algo instalado? usa o
        # mais recente" (ver comentário lá embaixo), o jeito certo é
        # mandar pra ele o HINT CRU do usuário sempre que ele mandar um -
        # nunca substituir pelo id do catálogo. O catálogo continua sendo
        # usado só pra estimar VRAM (`default_image_model.vram_mb_estimate`
        # abaixo), nunca mais pra decidir QUAL arquivo procurar no disco.
        raw_hint = (model_hint or "").strip()
        target_for_disk_scan = raw_hint or (default_image_model.id if default_image_model else "flux")
        resolved_model, resolution_note = self._resolve_image_model_target(target_for_disk_scan)
        self.logs.add_event("INFO", "DirectImageBridge", f"Resolução de modelo de imagem: {resolution_note}")

        if resolved_model is None:
            self.logs.add_event(
                "WARNING", "DirectImageBridge",
                f"Nenhum modelo de imagem instalado no disco. Baixe um modelo antes de gerar pela ponte direta "
                f"(essa ponte não baixa modelo sozinha — só a missão completa com aprovação faz isso)."
            )
            return {
                "ok": False,
                "error": "Nenhum modelo de imagem instalado no disco ainda. Rode uma missão de 'Criar Imagens' "
                         "e aprove o download primeiro — a ponte direta do chat só gera com o que já existe local.",
            }

        plan = ExecutionPlan(
            runtime="sdxl",  # Mesmo alias usado pelo Mission Executor -> roteia pro SdCppDriver
            model=resolved_model,
            parameters={"prompt": prompt},
            reasoning=f"Ponte direta (chat Aviary): {prompt}",
        )

        # Cleanup vem ANTES da telemetria/VRAMGuard.
        # O prompt não é reescrito aqui: segue literal para o SdCppDriver.
        if hasattr(self.runtime, "prepare_exclusive"):
            await self.runtime.prepare_exclusive("sdxl")

        await self._vram_guard(
            "Antes de gerar imagem (ponte direta)", "sdxl", resolved_model,
            default_image_model.vram_mb_estimate if default_image_model else 0,
        )

        self.logs.add_event(
            "INFO", "DirectImageBridge",
            f"Gerando imagem com '{resolved_model}' na GPU (prompt: \"{prompt}\")..."
        )
        result = await self.runtime.execute(plan)

        if result.status != ExecutionStatus.SUCCESS:
            self.logs.add_event("ERROR", "DirectImageBridge", f"Falha ao gerar imagem: {result.errors}")
            return {"ok": False, "error": "; ".join(result.errors) if result.errors else "Falha desconhecida na geração."}

        self._track_model_loaded("sdxl", resolved_model)
        self.logs.add_event("INFO", "DirectImageBridge", f"Resultado: {result.output}")
        # PHX-FIX (achado real via screenshot do usuário: "Falha ao gerar a
        # imagem - Driver reportou sucesso mas o arquivo não existe em
        # disco: C:\...\phoenix_174613.png (perfil: flux1-schnell)", MESMO
        # com o SdCppDriver tendo validado returncode+tamanho do arquivo
        # antes de declarar sucesso - ver PHX-FIX em sd_cpp.py): o código
        # antigo extraía o caminho fazendo `result.output.replace("Imagem
        # salva em:", "").strip()` - `result.output` é uma string decorada
        # PRA LOG ("Imagem salva em: <path> (perfil: <nome>)"), e o
        # `.replace()` só tira o prefixo, deixando " (perfil: <nome>)"
        # grudado no final do "caminho" extraído. Esse "path" com lixo no
        # final nunca existe em disco - daí o 500 mesmo com o arquivo
        # genuinamente lá. Agora lê `result.metrics["output_file"]`, o
        # campo estruturado que o SdCppDriver preenche com o Path() real,
        # sem nenhuma dependência do formato do texto de log.
        file_path = (result.metrics or {}).get("output_file")
        if not file_path:
            # Fallback só pra não quebrar se algum driver antigo/futuro não
            # preencher metrics - loga como aviso porque não deveria
            # acontecer mais depois do fix acima.
            self.logs.add_event(
                "WARNING", "DirectImageBridge",
                "result.metrics['output_file'] ausente - caindo pro parsing de texto antigo (frágil)."
            )
            file_path = result.output.replace("Imagem salva em:", "").split(" (perfil:")[0].strip()
        return {"ok": True, "path": file_path, "model": resolved_model}

    # ============================================================
    # AUTO-RECUPERAÇÃO DE RUNTIME DE TEXTO (achado real via screenshot do
    # usuário: selecionar "[LLAMA-SERVER] qwen3-8b-q4_k_m" e mandar
    # QUALQUER mensagem - até um "ola" sem nada a ver com troca de modelo -
    # falhava com 404 "File Not Found" do próprio llama-server, na cara do
    # usuário, sem nenhuma tentativa de recuperação. Pedido explícito do
    # usuário: "qualquer comando deveria matar processo e subir modelo
    # padrao e nao dar erro" - ou seja, uma falha no runtime nativo não
    # deveria virar erro cru pro usuário resolver na mão; o sistema deveria
    # tentar se recuperar sozinho primeiro (matar o processo travado/
    # desalinhado e subir de novo com o modelo DEFAULT do catálogo, que é o
    # estado mais previsível de se recuperar), e só then repassar a
    # mensagem de erro se a própria recuperação falhar.
    #
    # Isolado num método próprio (mesmo padrão de generate_image_direct/
    # transcribe_direct acima) pra ser chamado tanto por um endpoint HTTP
    # dedicado (POST /api/engine/runtime/recover, ver api_server.py) quanto,
    # no futuro, por qualquer outro caminho interno que precise do mesmo
    # "reset pro estado conhecido-bom" sem duplicar a lógica.
    # ============================================================
    async def recover_text_runtime(self, runtime: str = "llama.cpp") -> dict:
        """Mata o processo do runtime de texto nativo (se estiver de pé) e
        sobe de novo com o modelo DEFAULT do catálogo (catalog/models.json,
        default_for_roles de 'chat'). Usado como recuperação automática
        quando um request de chat falha contra esse runtime - nunca
        assume que "matar e subir de novo" vai resolver sozinho: devolve
        ok=False com o erro real se o restart também falhar."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        default_model = self.registry.resolve("chat")
        if default_model is None:
            return {"ok": False, "error": "Nenhum modelo de chat default configurado em catalog/models.json."}

        self.logs.add_event(
            "WARNING", "RuntimeRecovery",
            f"Recuperação automática acionada pro runtime '{runtime}' - matando processo e "
            f"subindo de novo com o modelo default '{default_model.id}'."
        )

        try:
            await self.runtime.stop(runtime)
        except Exception as e:
            # Mesmo que o stop() falhe (ex: processo já morto sozinho), tenta
            # subir de novo - a maior parte dos drivers trata "já não tá
            # rodando" como um caso normal do stop(), não uma exceção real.
            logger.warning(f"ResidentManager: stop('{runtime}') levantou durante recuperação (seguindo mesmo assim): {e}")

        plan = ExecutionPlan(
            runtime=runtime,
            model=default_model.id,
            parameters={},
            reasoning="Auto-recuperação: modelo default depois de falha reportada pelo chat.",
        )
        success = await self.runtime.start(runtime, plan)

        if not success:
            self.logs.add_event("ERROR", "RuntimeRecovery", f"Recuperação automática falhou - runtime '{runtime}' não subiu com '{default_model.id}'.")
            return {"ok": False, "error": f"Não consegui subir '{runtime}' de novo com o modelo default '{default_model.id}'."}

        self._track_model_loaded(runtime, default_model.id)
        self.logs.add_event("INFO", "RuntimeRecovery", f"Runtime '{runtime}' recuperado - rodando '{default_model.id}'.")
        return {"ok": True, "runtime": runtime, "model": default_model.id}

    # ============================================================
    # PONTE DIRETA (auditoria 2026-08-20, "ResidentManager não pode ser
    # contornado" - Seção 3): descrição de imagem síncrona (MiniCPM-V/
    # vision), sem passar pelo Mission Kernel/aprovação. Antes desta
    # ponte, POST /api/describe-image em api_server.py só usava
    # resident.registry.resolve("vision") pra decidir QUAL modelo citar
    # no plan, mas executava com kernel.runtime.execute() DIRETO - sem
    # _thermal_guard e, mais importante, sem _vram_guard - na época deste
    # achado, "vision" era tratado como runtime GPU-pesado por _vram_guard()
    # (GPU_HEAVY_RUNTIMES = {"vision", "sdxl"}), mas essa guarda nunca
    # rodava de verdade nesse caminho porque nada chamava o Resident.
    # PHX-FIX (2026-08-28): "vision" saiu de GPU_HEAVY_RUNTIMES (ver
    # _vram_guard() acima) porque o driver força -ngl 0 (CPU) por política
    # definitiva de roteamento de hardware - a chamada abaixo continua
    # existindo por consistência com generate_image_direct/thermal_guard,
    # mas hoje vira no-op (vram_mb_needed=0), igual chat. Ainda vale rodar
    # o _thermal_guard antes de qualquer inferência, e manter a chamada
    # aqui deixa o código pronto caso o driver ganhe offload de GPU no
    # futuro. Mesmo padrão de generate_image_direct acima; mais simples que ele
    # porque o MiniCPM-V driver resolve o próprio arquivo de peso sozinho
    # (não há disk-scan de resolução aqui, só o id/runtime pro plan e pro
    # tracking - mesmo espírito de transcribe_direct pro Whisper).
    # ============================================================
    async def describe_image_direct(self, image_path: str, prompt: str, model_hint: str = "") -> dict:
        """Descreve uma imagem AGORA (MiniCPM-V), sem aprovação de missão.
        `image_path` deve ser um caminho de arquivo já existente em disco
        (o endpoint HTTP grava o upload num arquivo temporário antes de
        chamar isto). Retorna dict com sucesso/erro e o texto descrito."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        image_path = (image_path or "").strip()
        if not image_path:
            return {"ok": False, "error": "Caminho de imagem vazio."}
        if not Path(image_path).exists():
            return {"ok": False, "error": f"Arquivo de imagem não encontrado: {image_path}"}

        await self._thermal_guard("Antes de descrever imagem (ponte direta)")

        resolved_vision = self.registry.resolve("vision", hint=model_hint)
        vision_runtime = resolved_vision.runtime if resolved_vision else "vision"
        vision_model = resolved_vision.id if resolved_vision else "minicpmv"

        await self._vram_guard(
            "Antes de descrever imagem (ponte direta)", vision_runtime, vision_model,
            resolved_vision.vram_mb_estimate if resolved_vision else 0,
        )

        plan = ExecutionPlan(
            runtime=vision_runtime,
            model=vision_model,
            parameters={"image_path": image_path, "prompt": prompt},
            reasoning=f"Ponte direta (chat Aviary): análise de imagem via {vision_model}",
        )

        self.logs.add_event(
            "INFO", "DirectVisionBridge",
            f"Descrevendo '{Path(image_path).name}' com '{vision_model}'...",
        )
        result = await self.runtime.execute(plan)

        if result.status != ExecutionStatus.SUCCESS:
            self.logs.add_event("ERROR", "DirectVisionBridge", f"Falha ao descrever imagem: {result.errors}")
            return {"ok": False, "error": "; ".join(result.errors) if result.errors else "Falha desconhecida na análise de imagem."}

        self._track_model_loaded(vision_runtime, vision_model)
        self.logs.add_event("INFO", "DirectVisionBridge", f"Descrição concluída ({len(result.output or '')} chars).")
        return {"ok": True, "text": result.output, "model": vision_model}

    # ============================================================
    # PONTE DIRETA: OCR real de uma imagem via visão nativa (MiniCPM-V).
    # PHX-NEW (pedido do usuário 2026-08-22): mesmo modelo/runtime de
    # describe_image_direct acima, mas com um prompt FIXO (não aceita
    # prompt livre - garante que o modelo sempre tenta transcrever, nunca
    # "descrever" por engano) e limites próprios de tokens/timeout (uma
    # página de texto real facilmente passa dos 256 tokens que
    # describe_image_direct usa para uma legenda curta - ver PHX-NEW em
    # mtmd_driver.py). Endpoint HTTP: POST /api/describe-image com
    # mode=ocr (ver api_server.py) - usado tanto para imagem anexada
    # direto no chat quanto como base de _ocr_scanned_pdf() logo abaixo
    # (página de PDF renderizada como imagem).
    # ============================================================
    async def ocr_image_direct(self, image_path: str, model_hint: str = "") -> dict:
        """Transcreve o texto visível de uma imagem AGORA (MiniCPM-V), sem
        aprovação de missão. Mesma convenção de describe_image_direct:
        `image_path` já deve existir em disco."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        image_path = (image_path or "").strip()
        if not image_path:
            return {"ok": False, "error": "Caminho de imagem vazio."}
        if not Path(image_path).exists():
            return {"ok": False, "error": f"Arquivo de imagem não encontrado: {image_path}"}

        await self._thermal_guard("Antes de rodar OCR em imagem (ponte direta)")

        resolved_vision = self.registry.resolve("vision", hint=model_hint)
        vision_runtime = resolved_vision.runtime if resolved_vision else "vision"
        vision_model = resolved_vision.id if resolved_vision else "minicpmv"

        await self._vram_guard(
            "Antes de rodar OCR em imagem (ponte direta)", vision_runtime, vision_model,
            resolved_vision.vram_mb_estimate if resolved_vision else 0,
        )

        ocr_prompt = (
            "Transcreva integralmente todo o texto visível nesta imagem, exatamente "
            "como está escrito, na ordem em que aparece. Não descreva a imagem, não "
            "resuma, não comente - apenas o texto transcrito. Se não houver nenhum "
            "texto visível, responda exatamente: (nenhum texto encontrado)"
        )

        plan = ExecutionPlan(
            runtime=vision_runtime,
            model=vision_model,
            parameters={
                "image_path": image_path,
                "prompt": ocr_prompt,
                "max_tokens": OCR_MAX_TOKENS_PER_PAGE,
                "timeout_seconds": OCR_PAGE_TIMEOUT_SECONDS,
            },
            reasoning=f"Ponte direta (chat Aviary): OCR de imagem via {vision_model}",
        )

        self.logs.add_event(
            "INFO", "DirectOcrBridge",
            f"Rodando OCR em '{Path(image_path).name}' com '{vision_model}'...",
        )
        result = await self.runtime.execute(plan)

        if result.status != ExecutionStatus.SUCCESS:
            self.logs.add_event("ERROR", "DirectOcrBridge", f"Falha no OCR: {result.errors}")
            return {"ok": False, "error": "; ".join(result.errors) if result.errors else "Falha desconhecida no OCR."}

        self._track_model_loaded(vision_runtime, vision_model)
        self.logs.add_event("INFO", "DirectOcrBridge", f"OCR concluído ({len(result.output or '')} chars).")
        return {"ok": True, "text": result.output, "model": vision_model}

    # ============================================================
    # PHX-NEW (2026-09-06, pedido do usuário: "quero saber se tesseract é
    # melhor que MiniCPM-V com confiança bem maior, ou se eles podem
    # trabalhar juntos" -> "faça, e não só pra planilhas, pra ler qualquer
    # coisa por ocr"): OCR híbrido de propósito geral.
    #
    # Por que os dois, nessa ordem: Tesseract é determinístico, rápido, não
    # gasta VRAM, e reporta confiança REAL por palavra (vem do próprio
    # motor LSTM) - quando erra, geralmente erra de forma visível (texto
    # quebrado, confiança baixa). MiniCPM-V é mais robusto a foto real de
    # celular (ângulo, luz, sombra) porque entende contexto, não só forma
    # de caractere - mas pode ALUCINAR: inventar um número plausível que
    # não está na imagem, com a MESMA confiança aparente de quando acerta.
    # Uma alucinação de LLM é categoricamente pior que uma falha visível do
    # Tesseract, porque passa despercebida.
    #
    # Por isso a ordem importa: tenta o determinístico primeiro; só escala
    # pro modelo (mais caro, mais lento, precisa VRAM) quando o
    # determinístico já sinalizou dúvida (confiança baixa, idioma ausente,
    # timeout, ou nenhum texto reconhecido) - nunca ao contrário.
    async def hybrid_ocr_direct(
        self, image_path: str, *, min_confidence: float = 70.0, lang: str | None = None,
    ) -> dict:
        """OCR de propósito geral (não específico de planilha/RAG) —
        Tesseract primeiro, MiniCPM-V como segunda opinião só quando
        necessário. Uso genérico: qualquer chamador que precise ler texto
        de uma imagem (RAG, PDF escaneado, chat) deveria passar por aqui,
        não chamar ocr_image_direct nem o OCREngine diretamente.

        Devolve:
            {"ok": bool, "text": str, "source": "tesseract"|"minicpmv",
             "confidence": float|None, "fallback_reason": str|None,
             "tesseract_confidence": float|None, "error": str|None}
        `confidence` é None quando a fonte final foi o MiniCPM-V (o modelo
        de visão não reporta confiança por palavra como o Tesseract).
        `fallback_reason` fica None quando o Tesseract bastou sozinho -
        presente sempre que a segunda opinião foi acionada, explicando por
        quê (auditável, nunca silencioso)."""
        from phoenix_kernel.services.ocr_engine import OCREngine, DEFAULT_OCR_LANG

        lang = lang or DEFAULT_OCR_LANG
        tess_result = await OCREngine().extract_text_with_confidence(image_path, lang=lang)

        fallback_reason: str | None = None
        if not tess_result["ok"]:
            fallback_reason = f"Tesseract falhou: {tess_result['error']}"
        elif not tess_result["text"].strip():
            fallback_reason = "Tesseract não reconheceu nenhum texto na imagem"
        elif tess_result["confidence"] is not None and tess_result["confidence"] < min_confidence:
            fallback_reason = (
                f"confiança do Tesseract abaixo do limite "
                f"({tess_result['confidence']:.1f} < {min_confidence:.1f})"
            )

        if fallback_reason is None:
            return {
                "ok": True, "text": tess_result["text"], "source": "tesseract",
                "confidence": tess_result["confidence"], "fallback_reason": None,
                "tesseract_confidence": tess_result["confidence"], "error": None,
            }

        self.logs.add_event(
            "INFO", "HybridOcrBridge",
            f"Tesseract insuficiente ({fallback_reason}) - buscando segunda opinião via MiniCPM-V...",
        )
        vision_result = await self.ocr_image_direct(image_path)
        if not vision_result.get("ok"):
            return {
                "ok": False, "text": "", "source": "minicpmv",
                "confidence": None, "fallback_reason": fallback_reason,
                "tesseract_confidence": tess_result.get("confidence"),
                "error": vision_result.get("error"),
            }
        return {
            "ok": True, "text": vision_result.get("text", ""), "source": "minicpmv",
            "confidence": None, "fallback_reason": fallback_reason,
            "tesseract_confidence": tess_result.get("confidence"), "error": None,
        }

    # ============================================================
    # PHX-NEW (pedido do usuário 2026-08-22): orquestra OCR de várias
    # páginas de um PDF escaneado, reaproveitando ocr_image_direct() acima
    # por página. Chamada automaticamente por read_document_direct()/
    # edit_document_direct() SÓ quando extract_text() já confirmou que o
    # PDF não tem texto nativo nenhum - nunca "por via das dúvidas" em
    # cima de um PDF que já tem texto (isso reintroduziria o problema que
    # o `use_ocr=OCRMode.NEVER` de documents/engine.py corrigiu: OCR lento
    # demais para o caso comum). Orçamento de tempo total
    # (OCR_TOTAL_BUDGET_SECONDS) é checado ENTRE páginas - se estourar,
    # para de processar páginas novas e devolve o que já tem, reportando
    # honestamente quantas páginas ficaram de fora (nunca um corte
    # silencioso).
    # ============================================================
    async def _ocr_scanned_pdf(self, pdf_path: Path, display_name: str) -> dict:
        from phoenix_kernel.documents.engine import render_pdf_pages_to_images, DocumentEngineError

        ocr_temp_dir = Path("temp/documents/ocr") / uuid.uuid4().hex[:12]
        try:
            page_paths, total_pages = await asyncio.get_event_loop().run_in_executor(
                None, lambda: render_pdf_pages_to_images(pdf_path, ocr_temp_dir, max_pages=OCR_MAX_PAGES)
            )
        except DocumentEngineError as e:
            return {"ok": False, "error": str(e)}

        if not page_paths:
            return {"ok": False, "error": "PDF não tem nenhuma página para renderizar."}

        self.logs.add_event(
            "INFO", "DirectOcrBridge",
            f"'{display_name}' não tem texto nativo - iniciando OCR real via visão em "
            f"{len(page_paths)} de {total_pages} página(s)...",
        )

        started = time.monotonic()
        page_texts: list[str] = []
        pages_processed = 0
        try:
            for page_path in page_paths:
                if time.monotonic() - started > OCR_TOTAL_BUDGET_SECONDS:
                    self.logs.add_event(
                        "WARNING", "DirectOcrBridge",
                        f"Orçamento de tempo de OCR ({OCR_TOTAL_BUDGET_SECONDS:.0f}s) esgotado após "
                        f"{pages_processed} página(s) - parando antes de processar as demais.",
                    )
                    break
                # PHX-UPDATE (2026-09-06): Tesseract primeiro (rápido,
                # determinístico), MiniCPM-V só como segunda opinião quando
                # necessário - ver hybrid_ocr_direct acima.
                result = await self.hybrid_ocr_direct(str(page_path))
                if not result.get("ok"):
                    page_texts.append(
                        f"## Página {pages_processed + 1}\n(falha no OCR desta página: {result.get('error', 'erro desconhecido')})"
                    )
                else:
                    page_texts.append(f"## Página {pages_processed + 1}\n{(result.get('text') or '').strip()}")
                pages_processed += 1
        finally:
            for page_path in page_paths:
                page_path.unlink(missing_ok=True)
            try:
                ocr_temp_dir.rmdir()
            except OSError:
                pass  # não vazio ou já removido - não é crítico limpar isso

        combined_text = "\n\n".join(page_texts).strip()
        if not combined_text:
            return {"ok": False, "error": "OCR não encontrou texto em nenhuma página do PDF."}

        pages_skipped = max(0, total_pages - pages_processed)
        return {
            "ok": True,
            "text": combined_text,
            "pages_processed": pages_processed,
            "pages_total": total_pages,
            "truncated": pages_skipped > 0,
        }

    # ============================================================
    # PONTE DIRETA: síntese de voz síncrona, sem passar pelo Mission Kernel /
    # aprovação. Chamada pelos endpoints HTTP POST /api/synthesize-speech e
    # (via proxy rápido) POST /api/tts/piper, usados pelo botão "Voz" do
    # chat do Aviary e pela ferramenta "Texto Livre" em vez da API paga da
    # OpenAI/ElevenLabs.
    #
    # PHX-NEW (2026-08-23, pedido do usuário: "kokoro será motor pra
    # transformar texto em áudio, assim como whisper é motor de áudio pra
    # texto e piper lê texto que llm cospe" - ou seja, Kokoro-82M substitui
    # o Piper como motor de voz PADRÃO de toda a Phoenix, não só do
    # audiolivro). Antes esta ponte rodava `ExecutionPlan(runtime="piper")`
    # via `self.runtime.execute()` (PiperDriver, precisa de um par de
    # arquivos .onnx/.onnx.json por voz baixado manualmente). Agora chama
    # `kokoro_tts.get_kokoro_engine()` direto (mesmo motor e mesmo driver já
    # usado por generate_audiobook_direct(), sem passar pelo RuntimeEngine
    # genérico - Kokoro não precisa dele, é um único arquivo de modelo
    # compartilhado entre todas as vozes/idiomas, diferente do Piper que
    # tinha um par de arquivos por voz).
    #
    # `voice_hint` agora aceita 3 formatos: (a) vazio/"auto" -> detecta o
    # idioma do próprio texto (phoenix_kernel/documents/audiobook.py,
    # py3langid real, mesma detecção do audiolivro) e escolhe a voz Kokoro
    # correspondente; (b) um código de idioma direto ("pt", "en", "es"...);
    # (c) um ID de voz Kokoro direto ("pf_dora", "af_heart"...), pra quando
    # o usuário escolhe manualmente no seletor da UI em vez de confiar na
    # detecção automática.
    #
    # PHX-FIX (achado real do usuário 2026-08-24, "se piper nao funciona e
    # kokoro é melhor, jogar fora o piper de vez"): o Piper NÃO existe mais
    # no código - `runtime/drivers/piper.py` foi apagado e o registro em
    # `runtime/engine.py` removido (o driver já estava morto, nada o
    # chamava desde a troca pro Kokoro em 2026-08-23; ver também
    # catalog/models.json, catalog/studios/voice.json e
    # install/common.ps1, todos atualizados na mesma versão).
    # ============================================================
    async def generate_speech_direct(self, text: str, voice_hint: str = "") -> dict:
        """Sintetiza fala AGORA com o motor Kokoro-82M, sem aprovação de
        missão. Retorna um dict com sucesso/erro e o caminho do .wav gerado
        (se houver)."""
        text = (text or "").strip()
        if not text:
            return {"ok": False, "error": "Texto vazio."}

        await self._thermal_guard("Antes de sintetizar voz (ponte direta)")

        from phoenix_kernel.runtime.drivers.kokoro_tts import get_kokoro_engine, LANGUAGE_VOICE_MAP, describe_synthesis_error
        from phoenix_kernel.documents.audiobook import detect_language

        engine = get_kokoro_engine()
        if not engine.is_installed():
            self.logs.add_event(
                "WARNING", "DirectSpeechBridge",
                "Modelo de voz neural Kokoro não está instalado no disco.",
            )
            return {
                "ok": False,
                "error": (
                    "Modelo de voz neural Kokoro não está instalado no disco. Abra a aba "
                    "\"Texto → Áudio\" e use o botão \"Baixar Voz Kokoro Agora\" para a Phoenix "
                    "baixar e instalar sozinha (~340MB), ou baixe manualmente 'kokoro-v1.0.onnx' "
                    "e 'voices-v1.0.bin' em https://github.com/thewh1teagle/kokoro-onnx/releases "
                    "(tag model-files-v1.0) e coloque os dois em Workstations/Models/Voice/Kokoro/."
                ),
            }

        hint = (voice_hint or "").strip().lower()
        voice_ids_by_id = {voice_id: lang for lang, (voice_id, _espeak) in LANGUAGE_VOICE_MAP.items()}
        if hint in LANGUAGE_VOICE_MAP:
            lang = hint
        elif hint in voice_ids_by_id:
            lang = voice_ids_by_id[hint]
        else:
            # "" (chat sem seleção manual), "auto" (opção explícita da UI),
            # ou qualquer valor não reconhecido -> detecção automática real
            # do idioma do próprio texto, com fallback pra português.
            lang = detect_language(text) or "pt"
            if lang not in LANGUAGE_VOICE_MAP:
                lang = "pt"

        resolved_voice, _espeak_lang = engine.resolve_voice(lang)

        self.logs.add_event(
            "INFO", "DirectSpeechBridge",
            f"Sintetizando fala com Kokoro (voz='{resolved_voice}', idioma='{lang}', "
            f"{len(text)} caracteres de texto)...",
        )

        loop = asyncio.get_event_loop()
        t_start = time.monotonic()

        # PHX-FIX (2026-09-03, auditoria ChatGPT — "texto→áudio só funciona
        # com arquivo"): antes o texto livre ia num ÚNICO engine.synthesize()
        # com o texto inteiro — caminho diferente do audiolivro, que já
        # particiona com split_into_chunks() e sintetiza bloco a bloco. Um
        # texto longo digitado (um poema inteiro, uma página colada) nesse
        # caminho monolítico travava/estourava. Agora o texto livre usa o
        # MESMO particionamento do audiolivro: acima de um limite, quebra em
        # chunks, sintetiza cada um e concatena. Textos curtos seguem em uma
        # chamada só (sem overhead). O idioma detectado (lang) vale para todos
        # os chunks aqui — a detecção por-bloco fica no audiolivro, que lida
        # com documentos multilíngues.
        import numpy as np
        import soundfile as sf
        from phoenix_kernel.documents.audiobook import split_into_chunks, MAX_CHARS_PER_CHUNK

        try:
            if len(text) <= MAX_CHARS_PER_CHUNK:
                samples, sample_rate = await loop.run_in_executor(
                    None, engine.synthesize, text, lang
                )
            else:
                chunks = split_into_chunks(text)
                self.logs.add_event(
                    "INFO", "DirectSpeechBridge",
                    f"Texto longo ({len(text)} chars) — particionado em {len(chunks)} "
                    f"blocos (mesmo caminho do audiolivro).",
                )
                pieces = []
                sample_rate = None
                for i, chunk in enumerate(chunks, 1):
                    s, sr = await loop.run_in_executor(None, engine.synthesize, chunk, lang)
                    sample_rate = sr
                    pieces.append(s)
                    # pequeno silêncio entre blocos (0.25s) para prosódia natural
                    pieces.append(np.zeros(int(sr * 0.25), dtype=np.asarray(s).dtype))
                samples = np.concatenate(pieces) if pieces else np.zeros(0)
        except Exception as e:
            reason = describe_synthesis_error(e)
            elapsed = time.monotonic() - t_start
            self.logs.add_event(
                "ERROR", "DirectSpeechBridge",
                f"Falha ao sintetizar voz após {elapsed:.1f}s: {reason}",
            )
            return {"ok": False, "error": f"Falha na síntese de voz: {reason}"}

        elapsed = time.monotonic() - t_start
        self.logs.add_event(
            "INFO", "DirectSpeechBridge",
            f"Síntese concluída em {elapsed:.1f}s ({len(text)} caracteres, "
            f"~{(elapsed / max(len(text),1) * 1000):.1f}ms/caractere).",
        )

        out_wav = Path(tempfile.gettempdir()) / f"kokoro_out_{uuid.uuid4()}.wav"
        await loop.run_in_executor(None, sf.write, str(out_wav), samples, sample_rate)

        self._track_model_loaded("kokoro", resolved_voice)
        self.logs.add_event("INFO", "DirectSpeechBridge", f"Áudio salvo em: {out_wav}")
        return {"ok": True, "path": str(out_wav), "voice": resolved_voice}

    # ============================================================
    # PONTE DIRETA: documento longo (PDF/DOCX/PPTX/TXT/MD) -> audiolivro
    # em um único arquivo, com detecção automática de idioma por bloco e
    # troca de voz neural Kokoro-82M conforme o idioma detectado.
    #
    # PHX-NEW (pedido do usuário 2026-08-23: "pegar um arquivo doc, pdf de
    # 40 folhas e fazer áudio com voz neural com prosódia bacana tanto em
    # português qto em inglês ou outra língua e gerar os áudios"). Decisão
    # de escopo confirmada pelo usuário via pergunta explícita nesta sessão:
    # motor Kokoro-82M (investigado e testado de verdade contra XTTS-v2 e
    # Chatterbox antes de escolher - ver LEIA-ME desta versão), saída em UM
    # arquivo único (não dividido em partes), detecção automática de idioma
    # por trecho (não um seletor manual único pro documento inteiro).
    #
    # Reentrância: só uma geração de audiolivro por vez, mesmo padrão de
    # `_dual_collab_active` em run_dual_model_collaboration_direct() acima -
    # o hardware do usuário é o mesmo CPU compartilhado com todo o resto do
    # Phoenix Engine, e duas sínteses longas concorrentes só fariam as duas
    # demorarem o dobro sem nenhum ganho real.
    # ============================================================
    async def generate_audiobook_direct(self, file_path: str, original_name: str = "") -> dict:
        """Extrai o texto de um documento inteiro (SEM o corte de
        char_limit que extract_document_raw_direct aplica - um audiolivro
        precisa do documento COMPLETO, não de uma prévia), quebra em blocos
        sintetizáveis, detecta o idioma de cada bloco, sintetiza cada um com
        a voz Kokoro certa, concatena tudo num único arquivo de áudio e
        grava em Workstations/../Outputs/AudioBooks/.

        Bloqueante - pode legitimamente levar dezenas de minutos pra um
        documento de várias dezenas de páginas (ver
        AUDIOBOOK_TOTAL_TIME_BUDGET_SECONDS). Publica progresso ao vivo em
        `self._audiobook_progress` a cada bloco sintetizado, pra quem faz
        polling via get_audiobook_progress() (chamado por
        GET /api/documents/synthesize-audiobook/progress) acompanhar sem
        esperar o fim - mesmo padrão de `_dual_collab_progress`."""
        if getattr(self, "_audiobook_active", False):
            return {
                "ok": False,
                "error": (
                    "Já existe uma geração de audiolivro em andamento - espere "
                    "ela terminar antes de iniciar outra."
                ),
            }
        self._audiobook_active = True
        self._audiobook_progress = {
            "phase": "iniciando", "current_chunk": 0, "total_chunks": 0, "percent": 0.0,
        }
        try:
            path_obj = Path(file_path)
            if not path_obj.exists():
                return {"ok": False, "error": f"Arquivo não encontrado: {file_path}"}
            display_name = (original_name or "").strip() or path_obj.name

            from phoenix_kernel.runtime.drivers.kokoro_tts import get_kokoro_engine, describe_synthesis_error
            engine = get_kokoro_engine()
            if not engine.is_installed():
                return {
                    "ok": False,
                    "error": (
                        "Modelo de voz neural Kokoro não está instalado no disco. Abra a aba "
                        "\"Texto → Áudio\" e use o botão \"Baixar Voz Kokoro Agora\" para a Phoenix "
                        "baixar e instalar sozinha (~340MB), ou baixe manualmente 'kokoro-v1.0.onnx' "
                        "e 'voices-v1.0.bin' em https://github.com/thewh1teagle/kokoro-onnx/releases "
                        "(tag model-files-v1.0) e coloque os dois em Workstations/Models/Voice/Kokoro/."
                    ),
                }

            self._audiobook_progress["phase"] = "extraindo texto do documento"
            extraction = await self._extract_document_text_with_ocr_fallback(path_obj, display_name)
            if not extraction["ok"]:
                return {"ok": False, "error": extraction["error"]}

            full_text = extraction["extracted"]
            if not full_text or not full_text.strip():
                return {"ok": False, "error": f"'{display_name}' não contém texto extraível (documento vazio ou só com imagens sem OCR)."}

            from phoenix_kernel.documents.audiobook import (
                split_into_chunks, resolve_chunk_language, detect_document_language,
            )
            chunks = split_into_chunks(full_text)
            if not chunks:
                return {
                    "ok": False,
                    "error": f"Nenhum texto sintetizável sobrou em '{display_name}' depois de remover imagens/tabelas/separadores.",
                }

            self._audiobook_progress["phase"] = "detectando idioma predominante"
            doc_lang = detect_document_language(chunks)
            self._audiobook_progress.update({"phase": "sintetizando", "total_chunks": len(chunks)})

            self.logs.add_event(
                "INFO", "AudiobookBridge",
                f"Iniciando audiolivro de '{display_name}': {len(chunks)} blocos, "
                f"idioma predominante detectado: '{doc_lang}'.",
            )

            loop = asyncio.get_event_loop()
            all_audio = []
            sample_rate = None
            languages_used: dict = {}
            prev_lang = None
            t_start = time.monotonic()
            timed_out = False

            for i, chunk in enumerate(chunks):
                elapsed = time.monotonic() - t_start
                if elapsed > AUDIOBOOK_TOTAL_TIME_BUDGET_SECONDS:
                    timed_out = True
                    self.logs.add_event(
                        "WARNING", "AudiobookBridge",
                        f"Orçamento de tempo ({AUDIOBOOK_TOTAL_TIME_BUDGET_SECONDS:.0f}s) "
                        f"esgotado no bloco {i}/{len(chunks)} - finalizando com o áudio já "
                        "sintetizado até aqui, em vez de descartar tudo.",
                    )
                    break

                lang = resolve_chunk_language(chunk, prev_lang, doc_lang)
                prev_lang = lang
                languages_used[lang] = languages_used.get(lang, 0) + 1

                try:
                    samples, sr = await loop.run_in_executor(None, engine.synthesize, chunk, lang)
                except Exception as e:
                    reason = describe_synthesis_error(e)
                    self.logs.add_event("WARNING", "AudiobookBridge", f"Bloco {i} falhou na síntese ({reason}) - pulado, resto do documento continua.")
                    continue

                sample_rate = sr
                all_audio.append(samples)
                self._audiobook_progress.update({
                    "current_chunk": i + 1,
                    "percent": round((i + 1) / len(chunks) * 100, 1),
                    "elapsed_seconds": round(elapsed, 1),
                })

            if not all_audio:
                return {"ok": False, "error": "Nenhum bloco de texto foi sintetizado com sucesso (todos falharam)."}

            self._audiobook_progress["phase"] = "concatenando áudio final"
            import numpy as np
            final_audio = np.concatenate(all_audio)
            duration_seconds = len(final_audio) / sample_rate

            output_dir = PhoenixPaths.get_outputs_dir() / "AudioBooks"
            output_dir.mkdir(parents=True, exist_ok=True)
            base_name = Path(display_name).stem or "documento"
            safe_name = re.sub(r"[^\w\-. ]", "_", base_name)[:80]
            wav_path = output_dir / f"{safe_name}_{uuid.uuid4().hex[:8]}.wav"

            import soundfile as sf
            await loop.run_in_executor(None, sf.write, str(wav_path), final_audio, sample_rate)

            final_path = wav_path
            mime_type = "audio/wav"
            self._audiobook_progress["phase"] = "convertendo para mp3 (menor pra baixar)"
            mp3_path = wav_path.with_suffix(".mp3")
            if await self._try_encode_audiobook_mp3(wav_path, mp3_path):
                final_path = mp3_path
                mime_type = "audio/mpeg"
                wav_path.unlink(missing_ok=True)

            self._audiobook_progress.update({"phase": "concluído", "percent": 100.0})

            return {
                "ok": True,
                "path": str(final_path),
                "mime_type": mime_type,
                "duration_seconds": round(duration_seconds, 1),
                "chunks_synthesized": len(all_audio),
                "chunks_total": len(chunks),
                "languages_used": languages_used,
                "document_language": doc_lang,
                "timed_out": timed_out,
            }
        finally:
            self._audiobook_active = False

    async def _try_encode_audiobook_mp3(self, wav_path: Path, mp3_path: Path) -> bool:
        """Converte o WAV final do audiolivro pra MP3 via ffmpeg, SE
        estiver instalado no PATH - reduz bastante o tamanho do download
        (um audiolivro de 1h em WAV passa de 100MB; em MP3 mono a 96kbps,
        fica bem mais leve pra sair pela ponte base64/JSON que a rota HTTP
        usa). Mesmo padrão de checagem opcional já usado em
        `phoenix_kernel/runtime/drivers/whisper.py` (`_convert_to_wav`) -
        nunca trava o pipeline se o ffmpeg não estiver instalado, só
        mantém o WAV (maior) como resultado final."""
        import shutil
        if not shutil.which("ffmpeg"):
            self.logs.add_event("INFO", "AudiobookBridge", "ffmpeg não encontrado no PATH - audiolivro final ficará em .wav (maior). Instale ffmpeg pra downloads menores em .mp3.")
            return False
        try:
            loop = asyncio.get_event_loop()

            def _run_ffmpeg():
                import subprocess
                return subprocess.run(
                    ["ffmpeg", "-y", "-i", str(wav_path), "-ac", "1", "-b:a", "96k", str(mp3_path)],
                    capture_output=True, timeout=600,
                )

            r = await loop.run_in_executor(None, _run_ffmpeg)
            return r.returncode == 0 and mp3_path.exists() and mp3_path.stat().st_size > 0
        except Exception as e:
            self.logs.add_event("WARNING", "AudiobookBridge", f"Conversão do audiolivro pra MP3 falhou ({e}) - mantendo .wav.")
            return False

    def get_audiobook_progress(self) -> dict:
        """Leitura RÁPIDA e sempre não-bloqueante do progresso do
        audiolivro em andamento - pensada pra ser chamada em POLLING pelo
        frontend enquanto generate_audiobook_direct() (bloqueante, pode
        levar dezenas de minutos) ainda está rodando. Mesmo padrão de
        get_dual_collab_progress() acima. Nunca inicia nem cancela nada -
        só lê o que já está publicado."""
        return dict(getattr(self, "_audiobook_progress", {
            "phase": "ocioso", "current_chunk": 0, "total_chunks": 0, "percent": 0.0,
        }))

    # ============================================================
    # PONTE DIRETA (auditoria completa, achado #4 do LEIA-ME): transcrição
    # de áudio síncrona (Whisper), sem passar pelo Mission Kernel/aprovação.
    # Mesmo padrão de generate_image_direct/generate_speech_direct acima.
    # Antes desta ponte, o WhisperDriver estava registrado em
    # runtime/engine.py e no catalog/models.json (role speech_to_text), e o
    # common.ps1 até compilava o binário (fix desta mesma auditoria) - mas
    # NADA no projeto chamava runtime="whisper" em lugar nenhum: nem
    # resident_manager.py, nem api_server.py, nem server.ts. STT ficava
    # inacessível pela UI mesmo com tudo compilado. Diferente de
    # generate_image_direct/generate_speech_direct, o WhisperDriver resolve
    # o próprio arquivo de modelo sozinho via _find_model() (não recebe
    # model id no plan) - então aqui não há um "_resolve_stt_target"
    # análogo; o registry.resolve() abaixo serve só pra log/telemetria
    # consistente com as outras pontes diretas.
    # ============================================================
    async def transcribe_direct(self, audio_path: str, language: str = "pt") -> dict:
        """Transcreve um arquivo de áudio AGORA, sem aprovação de missão.
        `audio_path` deve ser um caminho de arquivo já existente em disco
        (o endpoint HTTP grava o upload num arquivo temporário antes de
        chamar isto). Retorna dict com sucesso/erro e o texto transcrito."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        audio_path = (audio_path or "").strip()
        if not audio_path:
            return {"ok": False, "error": "Caminho de áudio vazio."}
        if not Path(audio_path).exists():
            return {"ok": False, "error": f"Arquivo de áudio não encontrado: {audio_path}"}

        await self._thermal_guard("Antes de transcrever áudio (ponte direta)")

        resolved_stt = self.registry.resolve("speech_to_text")
        model_label = resolved_stt.id if resolved_stt else "whisper"

        plan = ExecutionPlan(
            runtime="whisper",  # Mesmo alias registrado em runtime/engine.py -> roteia pro WhisperDriver
            model=model_label,
            parameters={"audio_path": audio_path, "language": language or "pt"},
            reasoning=f"Ponte direta (chat Aviary): transcrição de áudio ({Path(audio_path).name})",
        )

        self.logs.add_event(
            "INFO", "DirectTranscribeBridge",
            f"Transcrevendo '{Path(audio_path).name}' (idioma: {language or 'pt'})...",
        )
        result = await self.runtime.execute(plan)

        if result.status != ExecutionStatus.SUCCESS:
            self.logs.add_event("ERROR", "DirectTranscribeBridge", f"Falha ao transcrever: {result.errors}")
            return {"ok": False, "error": "; ".join(result.errors) if result.errors else "Falha desconhecida na transcrição."}

        self._track_model_loaded("whisper", model_label)
        self.logs.add_event("INFO", "DirectTranscribeBridge", f"Transcrição concluída ({len(result.output or '')} chars).")
        return {"ok": True, "text": result.output, "model": model_label, "metrics": result.metrics or {}}

    # ============================================================
    # PONTE DIRETA (auditoria 2026-08-20): leitura e edição de documento
    # (PDF/DOCX/XLSX/PPTX/TXT/MD), sem passar pelo Mission Kernel/aprovação.
    # Mesmo padrão de generate_image_direct/generate_speech_direct/
    # transcribe_direct acima. Antes desta ponte, /api/documents/read e
    # /api/documents/edit em api_server.py chamavam
    # `resident.registry.resolve(...)` só pra escolher o modelo, mas depois
    # executavam com `kernel.runtime.execute(plan)` DIRETO - documento era a
    # única capacidade multimodal que não passava pelo Resident de verdade:
    # sem _thermal_guard, sem _track_model_loaded (o Resident nunca ficava
    # sabendo que um modelo de texto tinha sido usado pra isso), e sem
    # nenhum lugar central pra aplicar política de recurso no futuro. Segue
    # a arquitetura das outras pontes: API grava o upload num arquivo
    # temporário e só chama o Resident, que faz extração + resolução de
    # modelo + execução + rastreamento.
    # ============================================================
    async def _extract_document_text_with_ocr_fallback(self, path_obj: Path, display_name: str, char_limit: int = 12000) -> dict:
        """PHX-REFACTOR (pedido do usuário 2026-08-22, anexo de arquivo na
        colaboração do Arena): núcleo de extração + fallback de OCR
        compartilhado, extraído de dentro de read_document_direct pra não
        duplicar essa lógica (inclusive o OCR automático de PDF escaneado)
        em extract_document_raw_direct() (usada pelo anexo de arquivo do
        Arena, que injeta o texto extraído no "topic" da colaboração SEM
        gastar uma chamada de LLM só pra resumir - ao contrário de
        read_document_direct, que sempre pergunta pra um modelo). Não faz
        nenhuma chamada de LLM/runtime - só extração local + OCR quando
        aplicável. `char_limit` corta o texto que sai em `content_for_prompt`
        (a extração completa, sem corte, sempre vem em `extracted`).

        Devolve {"ok": True, "content_for_prompt", "extracted", "ocr_used",
        "ocr_meta"} em caso de sucesso, ou {"ok": False, "error"} em caso de
        falha - EXATAMENTE os mesmos textos de erro que read_document_direct
        já devolvia antes deste refactor (nenhuma mudança de comportamento
        pra quem já usa o chat/leitura de documento)."""
        # PHX-NEW (auditoria 2026-08-20, "XLSX timeout" - Seção 13): XLSX
        # tinha dois problemas empilhados: (1) extract_text()/_extract_xlsx()
        # despeja TODAS as linhas de TODAS as planilhas antes de truncar em
        # [:char_limit] - pra planilha grande isso é lento e desperdiça tempo/
        # memória construindo uma string gigante só pra jogar quase tudo
        # fora; (2) o corte é arbitrário (bruto, sem estrutura - pode cortar
        # no meio de uma linha, não mostra contagem real de linhas nem tipo
        # de coluna). Pra .xlsx especificamente, usamos
        # summarize_xlsx_structure() (planilhas, dimensões, cabeçalho,
        # amostra, tipos de coluna, contagem real de linhas) - já sai
        # compacto, então NÃO precisa do corte em cima.
        from phoenix_kernel.documents.engine import extract_text, DocumentEngineError
        is_xlsx = path_obj.suffix.lower() == ".xlsx"
        ocr_used = False
        ocr_meta: dict | None = None
        try:
            if is_xlsx:
                from phoenix_kernel.documents.engine import summarize_xlsx_structure
                extracted = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, summarize_xlsx_structure, path_obj),
                    timeout=DOCUMENT_EXTRACT_TIMEOUT_SECONDS,
                )
                content_for_prompt = extracted
            else:
                extracted = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, extract_text, path_obj),
                    timeout=DOCUMENT_EXTRACT_TIMEOUT_SECONDS,
                )
                content_for_prompt = extracted[:char_limit]
        except DocumentEngineError as e:
            # PHX-NEW (pedido do usuário 2026-08-22, OCR real): a mensagem
            # de erro de _extract_pdf() (documents/engine.py) sinaliza um
            # PDF sem texto nativo com a palavra "escaneado" - condição
            # exata (e só ela) que aciona o fallback de OCR explícito
            # abaixo. Qualquer outro DocumentEngineError (biblioteca
            # ausente, arquivo corrompido, formato não suportado) continua
            # falhando direto, sem tentar OCR à toa.
            is_scanned_pdf_signal = path_obj.suffix.lower() == ".pdf" and "escaneado" in str(e)
            if not is_scanned_pdf_signal:
                return {"ok": False, "error": str(e)}

            self.logs.add_event(
                "INFO", "DirectOcrBridge",
                f"'{display_name}' extraído sem texto nativo (provável PDF escaneado) - "
                "tentando OCR real via visão automaticamente...",
            )
            try:
                ocr_result = await asyncio.wait_for(
                    self._ocr_scanned_pdf(path_obj, display_name), timeout=OCR_EXTRACT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                self.logs.add_event(
                    "ERROR", "DirectOcrBridge",
                    f"Timeout ({OCR_EXTRACT_TIMEOUT_SECONDS:.0f}s) no OCR automático de '{display_name}'.",
                )
                return {
                    "ok": False,
                    "error": (
                        f"{e} A tentativa automática de OCR também excedeu "
                        f"{OCR_EXTRACT_TIMEOUT_SECONDS:.0f}s - PDF com páginas demais/muito "
                        "complexas para OCR síncrono."
                    ),
                }
            if not ocr_result.get("ok"):
                return {
                    "ok": False,
                    "error": f"{e} A tentativa automática de OCR também falhou: {ocr_result.get('error', 'erro desconhecido')}",
                }

            extracted = ocr_result["text"]
            content_for_prompt = extracted[:char_limit]
            ocr_used = True
            ocr_meta = {
                "pages_processed": ocr_result.get("pages_processed"),
                "pages_total": ocr_result.get("pages_total"),
                "truncated": ocr_result.get("truncated", False),
            }
        except asyncio.TimeoutError:
            self.logs.add_event(
                "ERROR", "DirectDocumentBridge",
                f"Timeout ({DOCUMENT_EXTRACT_TIMEOUT_SECONDS}s) extraindo texto de '{display_name}' - "
                "documento grande/complexo demais pra extração síncrona atual.",
            )
            return {
                "ok": False,
                "error": (
                    f"A extração de texto de '{display_name}' demorou mais que "
                    f"{DOCUMENT_EXTRACT_TIMEOUT_SECONDS}s (etapa ANTES do modelo de IA "
                    "entrar em ação - documento grande/complexo demais). Tente um "
                    "arquivo menor ou divida-o em partes."
                ),
            }

        return {
            "ok": True, "content_for_prompt": content_for_prompt, "extracted": extracted,
            "ocr_used": ocr_used, "ocr_meta": ocr_meta,
        }

    async def extract_document_full_text_direct(self, file_path: str, original_name: str = "") -> dict:
        """Extrai o conteúdo completo para ingestão RAG, sem chamada de LLM.

        Diferente de extract_document_raw_direct(), não aplica corte de caracteres.
        PDFs escaneados reutilizam o OCR explícito já existente; nesse caso os limites
        atuais de OCR (páginas/tempo) continuam sendo reportados honestamente.
        """
        file_path = (file_path or "").strip()
        if not file_path:
            return {"ok": False, "error": "Caminho de documento vazio."}
        path_obj = Path(file_path)
        if not path_obj.exists() or not path_obj.is_file():
            return {"ok": False, "error": f"Documento não encontrado: {file_path}"}

        display_name = original_name or path_obj.name

        # PHX-NEW (2026-09-06): imagem solta (foto/print de documento) vira
        # texto via OCR híbrido (Tesseract primeiro, MiniCPM-V como segunda
        # opinião — ver hybrid_ocr_direct) — mesmo motor já usado no
        # /api/describe-image?mode=ocr e no OCR de PDF escaneado logo
        # abaixo. Curto-circuita ANTES do extrator de documento (que só
        # entende pdf/docx/xlsx/pptx/txt/md) — nunca tenta extrair "texto
        # nativo" de um arquivo de imagem, que sempre falharia.
        if path_obj.suffix.lower() in RAG_IMAGE_EXTENSIONS:
            try:
                ocr_result = await asyncio.wait_for(
                    self.hybrid_ocr_direct(str(path_obj.resolve())),
                    timeout=OCR_EXTRACT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return {"ok": False, "error": f"OCR de '{display_name}' excedeu {OCR_EXTRACT_TIMEOUT_SECONDS:.0f}s."}
            if not ocr_result.get("ok"):
                return {"ok": False, "error": ocr_result.get("error", "Falha no OCR da imagem.")}
            texto = str(ocr_result.get("text") or "").strip()
            if not texto or texto == "(nenhum texto encontrado)":
                return {"ok": False, "error": f"Nenhum texto encontrado em '{display_name}'."}
            return {"ok": True, "text": texto, "file": display_name, "ocr_used": True}

        from phoenix_kernel.documents.engine import extract_text, DocumentEngineError
        try:
            extracted = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, extract_text, path_obj),
                timeout=RAG_DOCUMENT_EXTRACT_TIMEOUT_SECONDS,
            )
            return {"ok": True, "text": extracted, "file": display_name, "ocr_used": False}
        except DocumentEngineError as e:
            is_scanned_pdf = path_obj.suffix.lower() == ".pdf" and "escaneado" in str(e)
            if not is_scanned_pdf:
                return {"ok": False, "error": str(e)}
            try:
                ocr_result = await asyncio.wait_for(
                    self._ocr_scanned_pdf(path_obj, display_name),
                    timeout=OCR_EXTRACT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                return {"ok": False, "error": f"OCR de '{display_name}' excedeu {OCR_EXTRACT_TIMEOUT_SECONDS:.0f}s."}
            if not ocr_result.get("ok"):
                return {"ok": False, "error": ocr_result.get("error", "Falha no OCR.")}
            return {
                "ok": True,
                "text": ocr_result.get("text", ""),
                "file": display_name,
                "ocr_used": True,
                "ocr_pages_processed": ocr_result.get("pages_processed"),
                "ocr_pages_total": ocr_result.get("pages_total"),
                "ocr_truncated": ocr_result.get("truncated", False),
            }
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error": f"Extração RAG de '{display_name}' excedeu {RAG_DOCUMENT_EXTRACT_TIMEOUT_SECONDS}s.",
            }

    async def extract_document_raw_direct(self, file_path: str, original_name: str = "") -> dict:
        """PHX-NEW (pedido do usuário 2026-08-22: "pode por o clip igual no
        chatbot pra usuário subir (pescar) qualquer arquivo compatível como
        ja funciona no chatbot" - dentro da aba Colaboração do Arena):
        extração de texto CRUA de um documento (pdf/docx/xlsx/pptx), SEM
        nenhuma chamada de LLM - ao contrário de read_document_direct (que
        SEMPRE pergunta pra um terceiro modelo o que fazer com o conteúdo,
        gastando uma chamada de IA inteira só pra ler o arquivo). Isso serve
        pra injetar o texto do anexo direto no "topic" de uma colaboração
        entre dois modelos (ver run_dual_model_collaboration_direct), sem
        essa chamada extra - os dois modelos da colaboração já vão ler o
        texto extraído como parte do próprio tema/prompt deles.

        Usa char_limit=6000 (menor que os 12000 de read_document_direct) de
        propósito: esse texto ainda vai ser concatenado dentro de um "topic"
        que já cresce a cada rodada de colaboração (ver dual_collab.py) -
        um documento grande inteiro ali estouraria o contexto rápido demais.

        Não chama _thermal_guard nem toca em nenhum runtime/modelo - é só
        extração local (CPU, biblioteca de documento) + OCR quando
        aplicável, então não compete por VRAM/RAM com nada."""
        file_path = (file_path or "").strip()
        if not file_path:
            return {"ok": False, "error": "Caminho de documento vazio."}
        path_obj = Path(file_path)
        if not path_obj.exists():
            return {"ok": False, "error": f"Arquivo não encontrado: {file_path}"}

        display_name = (original_name or "").strip() or path_obj.name

        extraction = await self._extract_document_text_with_ocr_fallback(path_obj, display_name, char_limit=6000)
        if not extraction["ok"]:
            return {"ok": False, "error": extraction["error"]}

        return {
            "ok": True,
            "text": extraction["content_for_prompt"],
            "file": display_name,
            "ocr_used": extraction["ocr_used"],
            "ocr_meta": extraction["ocr_meta"],
        }

    def _log_arbiter_decision(self, decision: IntentDecision, context: str) -> None:
        if decision.claimed:
            self.logs.add_event(
                "INFO", "ExecutionArbiter",
                f"{context}: CLAIMED intent={decision.intent} executor={decision.executor} "
                f"grounding={decision.grounding} resource={decision.resource_policy.value} "
                f"subject={decision.subject} ({decision.reason})",
            )
        elif decision.legacy_allowed:
            self.logs.add_event(
                "INFO", "ExecutionArbiter",
                f"{context}: NOT_CLAIMED — podem usar o fluxo legado porque o árbitro não foi requisitado/chamado. "
                f"Motivo: {decision.reason}",
            )
        else:
            self.logs.add_event("WARNING", "ExecutionArbiter", f"{context}: REJECTED — {decision.reason}")

    def _resolve_document_decision(
        self,
        *,
        operation: str,
        instruction: str = "",
        source_file_path: str | None = None,
        source_chars: int = 0,
        plan: ExecutionPlan | None = None,
        output_format: str = "",
        use_web: bool = False,
        intent_decision: IntentDecision | dict | None = None,
    ) -> IntentDecision:
        """Obtém a decisão do árbitro; nunca decide CPU/GPU localmente."""
        if isinstance(intent_decision, IntentDecision):
            decision = intent_decision
        else:
            params = (plan.parameters or {}) if plan is not None else {}
            max_tokens = params.get("max_tokens")
            unlimited = bool(params.get("unlimited_output"))
            runtime_hint = plan.runtime if plan is not None else "llama.cpp"
            attachments = [source_file_path] if source_file_path else []
            decision = self.execution_arbiter.intercept(
                instruction,
                attachments=attachments,
                requested_operation=operation,
                output_format=output_format,
                source_chars=source_chars,
                max_tokens=max_tokens if isinstance(max_tokens, int) else None,
                unlimited_output=unlimited,
                use_web=use_web,
                runtime_hint=runtime_hint,
            )
        self._log_arbiter_decision(decision, f"document:{operation}")
        return decision

    def _build_phoenix_self_context(self) -> str:
        """Grounding conservador para pedidos sobre ESTE projeto Phoenix."""
        lines = [
            "IDENTIDADE DO PROJETO:",
            "- Phoenix Engine é o backend/core local desta estação de trabalho de IA.",
            "- Phoenix Aviary Platform é a interface/plataforma que consome os serviços da Phoenix Engine.",
            "- AIVisionsLab é o projeto/organização associado a esta Phoenix.",
            "- NÃO confunda Phoenix Engine com engine de jogos, motor gráfico ou produto homônimo externo.",
            "",
            "CAPACIDADES CONFIRMADAS NESTA BASE DE CÓDIGO:",
            "- LLMs locais via llama.cpp e opção Ollama.",
            "- Chat e raciocínio local.",
            "- Geração local de imagens.",
            "- Visão/OCR e descrição de imagens.",
            "- Leitura, criação, edição e transformação de PDF/DOCX/XLSX/PPTX/TXT/MD.",
            "- Pipeline documental com parser/normalização/evidência e etapas semânticas.",
            "- RAG/busca de conhecimento e pesquisa web quando solicitada.",
            "- Transcrição de áudio e síntese/audiolivro.",
            "- Benchmark, gerenciamento e troca de modelos.",
            "- Detecção/telemetria de hardware e políticas de execução CPU/GPU.",
            "- Worker LLM documental GPU temporário com self-test de correctness e fallback seguro para CPU.",
            "",
            "REGRAS DE VERDADE:",
            "- Só afirme recursos sustentados por este contexto, arquivo anexado ou fontes web reais fornecidas.",
            "- Não invente renderização 3D, física de jogos, multiplayer, consoles, VR/AR, Oculus/HTC Vive, taxa de quadros ou texturas.",
        ]
        try:
            lines.append(f"- Engine de texto selecionada: {self._text_engine_preference}.")
        except Exception:
            pass
        try:
            active = self.get_active_models()
            if active:
                lines.append("- Runtimes/modelos rastreados como ativos: " + json.dumps(active, ensure_ascii=False))
        except Exception:
            pass
        return "\n".join(lines)

    @staticmethod
    def _phoenix_confusion_terms() -> tuple[str, ...]:
        return (
            "oculus rift", "htc vive", "engine de jogos", "motor gráfico", "motor grafico",
            "renderização em tempo real", "renderizacao em tempo real", "jogos multiplayer",
            "taxa de quadros", "compressão de texturas", "compressao de texturas",
        )

    def _detect_phoenix_self_confusion(self, text: str, instruction: str) -> list[str]:
        out = (text or "").lower()
        req = (instruction or "").lower()
        return [term for term in self._phoenix_confusion_terms() if term in out and term not in req]

    def _document_prefers_gpu(self, operation: str, source_chars: int, plan: ExecutionPlan) -> bool:
        """Compatibilidade: delega a decisão exclusivamente ao ExecutionArbiter."""
        decision = self._resolve_document_decision(
            operation=operation, source_chars=source_chars, plan=plan,
        )
        return decision.resource_policy in {
            ResourcePolicy.GPU, ResourcePolicy.GPU_WITH_CPU_FALLBACK,
            ResourcePolicy.HYBRID, ResourcePolicy.CPU_WITH_GPU_BURST,
        }

    async def _execute_document_plan_routed(
        self,
        plan: ExecutionPlan,
        *,
        operation: str,
        source_chars: int,
        timeout: float,
        intent_decision: IntentDecision | None = None,
    ) -> ExecutionResult:
        """Executa a resource policy escolhida pelo árbitro; não escolhe política."""
        if self.runtime is None:
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=["RuntimeEngine não disponível"])

        decision = intent_decision or self._resolve_document_decision(
            operation=operation, source_chars=source_chars, plan=plan,
        )
        if decision.rejected:
            return ExecutionResult(plan_id=plan.id, status=ExecutionStatus.FAILED, errors=[decision.reason])
        if decision.legacy_allowed:
            self._log_arbiter_decision(decision, f"execute:{operation}")
            return await asyncio.wait_for(self.runtime.execute(plan), timeout=timeout)

        policy = decision.resource_policy
        if plan.runtime != "llama.cpp" or policy == ResourcePolicy.CPU:
            return await asyncio.wait_for(self.runtime.execute(plan), timeout=timeout)

        if policy not in {ResourcePolicy.GPU, ResourcePolicy.GPU_WITH_CPU_FALLBACK, ResourcePolicy.HYBRID, ResourcePolicy.CPU_WITH_GPU_BURST}:
            return await asyncio.wait_for(self.runtime.execute(plan), timeout=timeout)

        try:
            from phoenix_kernel.runtime.drivers.llama_cpp import LlamaCppDriver, find_free_local_port
            gpu_port = find_free_local_port(8095, 8110)
            # PHX-FIX (31/08): default estava "999" (full offload) com
            # overrides vazio - a combinação que document_llm_worker.py
            # documenta (e este mesmo módulo replica) como tendo restaurado
            # correctness na RX 580 é ngl=1 + output.weight=CPU; ngl=999
            # sozinho já foi confirmado como ainda corrompendo a geração.
            # O self-test abaixo continua sendo o gate real de qualquer
            # forma - isto só evita gastar uma tentativa GPU inteira numa
            # configuração já sabida como pior.
            gpu_ngl = os.environ.get("PHOENIX_DOCUMENT_GPU_NGL", "1").strip() or "1"
            gpu_device = os.environ.get("PHOENIX_DOCUMENT_GPU_DEVICE", "Vulkan0").strip() or None
            gpu_context = int(os.environ.get("PHOENIX_DOCUMENT_GPU_CONTEXT", "16384") or 16384)
            overrides = {"output.weight": "CPU"}
            gpu_driver = LlamaCppDriver(
                port=gpu_port, force_ngl=gpu_ngl, device=gpu_device,
                tensor_overrides=overrides, context_size=gpu_context,
                no_op_offload=False,
            )
            if hasattr(self.runtime, "stop_all"):
                await self.runtime.stop_all()
            started = await gpu_driver.start(plan)
            if not started:
                await gpu_driver.stop()
                raise RuntimeError("worker GPU não iniciou")
            try:
                sanity_ok, sanity_detail = await gpu_driver.sanity_check(timeout=min(90.0, timeout))
                if not sanity_ok:
                    raise RuntimeError("self-test Vulkan rejeitou backend: " + sanity_detail)
                self.logs.add_event(
                    "INFO", "ExecutionArbiter",
                    f"{operation}: executor GPU autorizado pelo plano do árbitro (porta {gpu_port}, NGL={gpu_ngl}).",
                )
                return await asyncio.wait_for(gpu_driver.execute(plan), timeout=timeout)
            finally:
                await gpu_driver.stop()
        except Exception as exc:
            if decision.allows_cpu_fallback:
                self.logs.add_event(
                    "WARNING", "ExecutionArbiter",
                    f"{operation}: GPU falhou/rejeitada ({type(exc).__name__}: {exc}); "
                    "o plano AUTORIZA fallback para CPU compartilhada.",
                )
                return await asyncio.wait_for(self.runtime.execute(plan), timeout=timeout)
            return ExecutionResult(
                plan_id=plan.id, status=ExecutionStatus.FAILED,
                errors=[f"GPU exigida pelo árbitro e fallback CPU não autorizado: {type(exc).__name__}: {exc}"],
            )

    async def read_document_direct(self, file_path: str, question: str = "", original_name: str | None = None, model_hint: str = "") -> dict:
        """Lê um documento AGORA e responde à pergunta (ou resume, se vazia).
        `file_path` deve ser um caminho de arquivo já existente em disco (o
        endpoint HTTP grava o upload num arquivo temporário antes de chamar
        isto, mesmo padrão de transcribe_direct). `original_name`, quando
        fornecido, é o nome de arquivo REAL que o usuário enviou - ver
        PHX-FIX abaixo sobre `display_name`."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        file_path = (file_path or "").strip()
        if not file_path:
            return {"ok": False, "error": "Caminho de documento vazio."}
        path_obj = Path(file_path)
        if not path_obj.exists():
            return {"ok": False, "error": f"Arquivo não encontrado: {file_path}"}

        # PHX-FIX (achado real do usuário, testando ao vivo com
        # CATALOGO_FINAL_MARKETUP.xlsx): o resumo gerado pela IA veio
        # titulado com o UUID do arquivo TEMPORÁRIO em disco
        # ("# Resumo do Documento '94e7446d-...-e1.xlsx'") em vez do nome
        # real que o usuário enviou - porque `path_obj.name` (usado antes
        # deste fix no prompt mandado pro LLM, nos logs, e no "file"
        # devolvido) é o nome do arquivo temp (`_save_document_upload()` em
        # api_server.py sempre grava com `uuid.uuid4()` + extensão, pra
        # evitar colisão/path traversal), nunca o nome original do upload.
        # Isso valia pra TODOS os formatos igualmente, mas só ficava
        # visível pra XLSX: PDF/
        # DOCX normalmente têm um título de verdade dentro do próprio
        # conteúdo (a instrução pede "leia o documento" - o LLM prefere o
        # título real que está no texto), enquanto um resumo estrutural de
        # planilha não tem título nenhum pra "preferir", então o LLM caiu de
        # volta pro único nome disponível no prompt - o UUID. `display_name`
        # agora é o nome real do upload (passado pelo chamador HTTP) sempre
        # que disponível, com fallback pro nome do arquivo temp só se
        # ninguém informar (chamada interna/legado).
        display_name = (original_name or "").strip() or path_obj.name

        await self._thermal_guard("Antes de ler documento (ponte direta)")

        # PHX-REFACTOR (pedido do usuário 2026-08-22, anexo de arquivo na
        # colaboração do Arena): a extração de texto + fallback de OCR era
        # só código local aqui dentro. Extraí pra
        # _extract_document_text_with_ocr_fallback() (mesma classe, logo
        # abaixo) pra reaproveitar exatamente essa lógica (incluindo o OCR
        # automático de PDF escaneado) em extract_document_raw_direct(),
        # sem duplicar nem arriscar as duas cópias divergirem com o tempo.
        # Nenhum comportamento mudou aqui - é literalmente o mesmo código,
        # só movido pra um método próprio.
        extraction = await self._extract_document_text_with_ocr_fallback(path_obj, display_name, char_limit=12000)
        if not extraction["ok"]:
            return {"ok": False, "error": extraction["error"]}
        content_for_prompt = extraction["content_for_prompt"]
        extracted = extraction["extracted"]
        ocr_used = extraction["ocr_used"]
        ocr_meta = extraction["ocr_meta"]

        # PHX-FIX (auditoria completa 2026-08-28, achado crítico): esta linha
        # já referenciava `model_hint` sem que o parâmetro existisse na
        # assinatura do método nem em lugar nenhum da classe - NameError
        # garantido em TODA chamada de read_document_direct(), ou seja, todo
        # pedido de leitura/resumo de documento (PDF/DOCX/XLSX/TXT) quebrava.
        # `POST /api/documents/read` (api_server.py) nunca recebeu nem
        # repassou nenhuma preferência de modelo do cliente - só `file` e
        # `question` - então não existe hoje nenhum "LLM selecionado na
        # Aviary" chegando até aqui pra usar de verdade. Corrigido do jeito
        # mais conservador: `model_hint: str = ""` vira parâmetro de verdade
        # (mesmo padrão de describe_image_direct/generate_image_direct/
        # ocr_image_direct, logo acima nesta classe), preservando o
        # comportamento que o comentário original já descrevia como
        # intencional - sem hint (caso de hoje), cai direto no modelo padrão
        # de reasoning. Se no futuro a Aviary passar a enviar o modelo
        # selecionado pra esta rota, basta a API repassar esse valor aqui -
        # a lógica de resolução abaixo já está pronta pra isso.
        resolved = self.registry.resolve("chat", hint=(model_hint or "").strip()) if (model_hint or "").strip() else None
        if resolved is None:
            resolved = self.registry.resolve("reasoning")
        doc_runtime = resolved.runtime if resolved else "llama.cpp"
        doc_model = resolved.id if resolved else "qwen3:8b"

        # PHX-NEW (pedido do usuário 2026-08-22, OCR real): quando o texto
        # veio de OCR (não da camada nativa do PDF), isso é dito EXPLICITAMENTE
        # tanto pro LLM (pra ele calibrar confiança/citar isso se relevante)
        # quanto na resposta final (`ocr_used` etc.) - nunca silencioso, ao
        # contrário do OCR "escondido" que documents/engine.py já bloqueou
        # de propósito (ver OCRMode.NEVER lá).
        ocr_note = ""
        if ocr_used and ocr_meta:
            ocr_note = (
                f"(Texto obtido via OCR automático - este PDF é escaneado, sem camada de "
                f"texto nativa. {ocr_meta['pages_processed']} de {ocr_meta['pages_total']} "
                f"página(s) processada(s)"
                + (", as demais não foram processadas por limite de tempo/páginas" if ocr_meta["truncated"] else "")
                + ". O OCR pode conter pequenos erros de reconhecimento de caractere.)\n\n"
            )

        plan = ExecutionPlan(
            runtime=doc_runtime,
            model=doc_model,
            parameters={
                "system_prompt": "Você é o Phoenix Document Engine. Leia o documento e responda com precisão em português, formatado em Markdown.",
                "user_prompt": f"Analise o documento '{display_name}'.\n\n{ocr_note}Pergunta: {question.strip() or 'Faça um resumo claro dos pontos principais.'}\n\n--- CONTEÚDO ---\n{content_for_prompt}",
            },
            reasoning=f"Ponte direta (chat Aviary): leitura de documento ({display_name})",
        )

        self.logs.add_event(
            "INFO", "DirectDocumentBridge",
            f"Lendo '{display_name}' com '{doc_model}' ({doc_runtime})...",
        )
        # PHX-NEW (auditoria 2026-08-20, "XLSX timeout" - Seção 13): antes,
        # nada aqui limitava o tempo do runtime.execute() - quem cortava a
        # espera era só o AbortController de 5min do lado do Node
        # (platform_source/server.ts), que aborta a CONEXÃO HTTP e devolve
        # um erro genérico de rede pro usuário, sem o Phoenix Engine nunca
        # ficar sabendo que devia ter parado. Com DOCUMENT_EXECUTE_TIMEOUT_SECONDS
        # bem abaixo dos 300s do Node, o próprio Engine desiste primeiro e
        # devolve um erro controlado e específico - o timeout de 5min do
        # Node vira uma rede de segurança que nunca deveria disparar na
        # prática, em vez de ser o único mecanismo de corte.
        try:
            result = await self._execute_document_plan_routed(
                plan, operation="read", source_chars=len(content_for_prompt),
                timeout=DOCUMENT_EXECUTE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self.logs.add_event(
                "ERROR", "DirectDocumentBridge",
                f"Timeout ({DOCUMENT_EXECUTE_TIMEOUT_SECONDS}s) ao ler documento '{display_name}'.",
            )
            return {
                "ok": False,
                "error": (
                    f"O modelo demorou mais que {DOCUMENT_EXECUTE_TIMEOUT_SECONDS}s para "
                    f"analisar '{display_name}' e a leitura foi cancelada. Tente um "
                    "documento menor, uma pergunta mais específica, ou verifique se o "
                    "runtime de IA está respondendo."
                ),
            }

        if result.status != ExecutionStatus.SUCCESS:
            self.logs.add_event("ERROR", "DirectDocumentBridge", f"Falha ao ler documento: {result.errors}")
            return {"ok": False, "error": "; ".join(result.errors) if result.errors else "Falha desconhecida na leitura."}

        self._track_model_loaded(doc_runtime, doc_model)
        response = {"ok": True, "text": result.output, "extracted_length": len(extracted), "file": display_name, "ocr_used": ocr_used}
        if ocr_used and ocr_meta:
            response["ocr_pages_processed"] = ocr_meta["pages_processed"]
            response["ocr_pages_total"] = ocr_meta["pages_total"]
            response["ocr_truncated"] = ocr_meta["truncated"]
        return response

    async def edit_document_direct(
        self,
        file_path: str,
        instruction: str,
        original_name: str | None = None,
        reference_file_path: str | None = None,
        reference_name: str | None = None,
    ) -> dict:
        """Edita um documento AGORA conforme `instruction` e devolve o
        caminho do arquivo reconstruído em disco. `file_path` segue a mesma
        convenção de read_document_direct (upload já salvo em disco).
        `original_name`: ver PHX-FIX em read_document_direct - mesmo
        conserto aplicado aqui (prompt/logs usam o nome real do upload, não
        o UUID do arquivo temp).

        `reference_file_path` (PHX-NEW, pedido do usuário 2026-08-28):
        opcional - um SEGUNDO arquivo (qualquer formato que a Document
        Engine já extrai) cujo conteúdo é dobrado na instrução de edição
        como dado de referência (ex: "copie os valores deste PDF pra este
        contrato"). Diferente de fill_spreadsheet_template_direct() (que
        preserva estruturalmente um .xlsx-alvo abrindo-o com openpyxl),
        aqui o documento principal continua passando pelo pipeline de
        sempre (extrai -> LLM reescreve como texto -> rebuild_document()
        materializa um arquivo NOVO) - ou seja, formatação original do
        documento principal não é preservada, exatamente como já não era
        preservada antes desta mudança. `reference_file_path` só evita que
        o usuário precise colar manualmente o conteúdo do outro arquivo na
        instrução."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        file_path = (file_path or "").strip()
        instruction = (instruction or "").strip()
        if not file_path:
            return {"ok": False, "error": "Caminho de documento vazio."}
        if not instruction:
            return {"ok": False, "error": "Instrução de edição vazia."}
        path_obj = Path(file_path)
        if not path_obj.exists():
            return {"ok": False, "error": f"Arquivo não encontrado: {file_path}"}
        display_name = (original_name or "").strip() or path_obj.name

        reference_file_path = (reference_file_path or "").strip()
        reference_block = ""
        if reference_file_path:
            reference_obj = Path(reference_file_path)
            if not reference_obj.exists():
                return {"ok": False, "error": f"Arquivo de referência não encontrado: {reference_file_path}"}
            reference_label = (reference_name or "").strip() or reference_obj.name
            ref_extraction = await self._extract_document_text_with_ocr_fallback(
                reference_obj, reference_label, char_limit=8000,
            )
            if not ref_extraction.get("ok"):
                return {"ok": False, "error": f"Falha ao ler o arquivo de referência '{reference_label}': {ref_extraction.get('error')}"}
            reference_block = (
                f"\n\n--- DADOS DE REFERÊNCIA (arquivo separado: {reference_label}) ---\n"
                f"{ref_extraction.get('content_for_prompt', '')}\n--- FIM DOS DADOS DE REFERÊNCIA ---"
            )

        await self._thermal_guard("Antes de editar documento (ponte direta)")

        from phoenix_kernel.documents.engine import extract_text, rebuild_document, DocumentEngineError
        ocr_used = False
        ocr_meta: dict | None = None
        try:
            extracted = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, extract_text, path_obj),
                timeout=DOCUMENT_EXTRACT_TIMEOUT_SECONDS,
            )
        except DocumentEngineError as e:
            # PHX-NEW (pedido do usuário 2026-08-22, OCR real): mesmo
            # fallback explícito de read_document_direct() - ver comentário
            # completo lá. PDF também pode ser materializado como NOVO PDF;
            # não há mais proibição de formato de saída.
            is_scanned_pdf_signal = path_obj.suffix.lower() == ".pdf" and "escaneado" in str(e)
            if not is_scanned_pdf_signal:
                return {"ok": False, "error": str(e)}

            self.logs.add_event(
                "INFO", "DirectOcrBridge",
                f"'{display_name}' extraído sem texto nativo (provável PDF escaneado) - "
                "tentando OCR real via visão automaticamente (edição)...",
            )
            try:
                ocr_result = await asyncio.wait_for(
                    self._ocr_scanned_pdf(path_obj, display_name), timeout=OCR_EXTRACT_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                self.logs.add_event(
                    "ERROR", "DirectOcrBridge",
                    f"Timeout ({OCR_EXTRACT_TIMEOUT_SECONDS:.0f}s) no OCR automático de '{display_name}' (edição).",
                )
                return {
                    "ok": False,
                    "error": (
                        f"{e} A tentativa automática de OCR também excedeu "
                        f"{OCR_EXTRACT_TIMEOUT_SECONDS:.0f}s - PDF com páginas demais/muito "
                        "complexas para OCR síncrono."
                    ),
                }
            if not ocr_result.get("ok"):
                return {
                    "ok": False,
                    "error": f"{e} A tentativa automática de OCR também falhou: {ocr_result.get('error', 'erro desconhecido')}",
                }

            extracted = ocr_result["text"]
            ocr_used = True
            ocr_meta = {
                "pages_processed": ocr_result.get("pages_processed"),
                "pages_total": ocr_result.get("pages_total"),
                "truncated": ocr_result.get("truncated", False),
            }
        except asyncio.TimeoutError:
            self.logs.add_event(
                "ERROR", "DirectDocumentBridge",
                f"Timeout ({DOCUMENT_EXTRACT_TIMEOUT_SECONDS}s) extraindo texto de '{display_name}' "
                "(edição) - documento grande/complexo demais pra extração síncrona atual.",
            )
            return {
                "ok": False,
                "error": (
                    f"A extração de texto de '{display_name}' demorou mais que "
                    f"{DOCUMENT_EXTRACT_TIMEOUT_SECONDS}s (etapa ANTES do modelo de IA "
                    "entrar em ação - documento grande/complexo demais). Tente um "
                    "arquivo menor ou divida-o em partes."
                ),
            }

        resolved = self.registry.resolve("reasoning")
        doc_runtime = resolved.runtime if resolved else "llama.cpp"
        doc_model = resolved.id if resolved else "qwen3:8b"

        ocr_note = ""
        if ocr_used and ocr_meta:
            ocr_note = (
                f"(Texto obtido via OCR automático - este PDF é escaneado, sem camada de "
                f"texto nativa. {ocr_meta['pages_processed']} de {ocr_meta['pages_total']} "
                f"página(s) processada(s)"
                + (", as demais não foram processadas por limite de tempo/páginas" if ocr_meta["truncated"] else "")
                + ". O OCR pode conter pequenos erros de reconhecimento de caractere.)\n\n"
            )

        plan = ExecutionPlan(
            runtime=doc_runtime,
            model=doc_model,
            parameters={
                "system_prompt": "Você é o Phoenix Document Engine. Edite o documento conforme a instrução e devolva apenas o texto final, pronto para virar arquivo.",
                "user_prompt": f"Documento '{display_name}':\n\n{ocr_note}{extracted[:12000]}{reference_block}\n\nInstrução: {instruction}",
            },
            reasoning=f"Ponte direta (chat Aviary): edição de documento ({display_name})",
        )

        self.logs.add_event(
            "INFO", "DirectDocumentBridge",
            f"Editando '{display_name}' com '{doc_model}' ({doc_runtime})...",
        )
        # PHX-NEW (auditoria 2026-08-20, "XLSX timeout" - Seção 13): mesmo
        # timeout interno controlado aplicado em read_document_direct()
        # acima - ver comentário lá pro racional completo.
        try:
            # PHX-FIX (31/08): `content_for_prompt` nunca é definida nesta
            # função (só existe em read_document_direct) - NameError em
            # 100% das chamadas de edição de documento. A variável certa,
            # já usada no mesmo prompt f-string acima, é `extracted`.
            result = await self._execute_document_plan_routed(
                plan, operation="edit", source_chars=len(extracted),
                timeout=DOCUMENT_EXECUTE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self.logs.add_event(
                "ERROR", "DirectDocumentBridge",
                f"Timeout ({DOCUMENT_EXECUTE_TIMEOUT_SECONDS}s) ao editar documento '{display_name}'.",
            )
            return {
                "ok": False,
                "error": (
                    f"O modelo demorou mais que {DOCUMENT_EXECUTE_TIMEOUT_SECONDS}s para "
                    f"editar '{display_name}' e a edição foi cancelada. Tente uma "
                    "instrução mais simples/específica, ou verifique se o runtime de "
                    "IA está respondendo."
                ),
            }

        if result.status != ExecutionStatus.SUCCESS:
            self.logs.add_event("ERROR", "DirectDocumentBridge", f"Falha ao editar documento: {result.errors}")
            return {"ok": False, "error": "; ".join(result.errors) if result.errors else "Falha desconhecida na edição."}

        self._track_model_loaded(doc_runtime, doc_model)

        out_ext = path_obj.suffix.lower()
        out_dir = PhoenixPaths.get_documents_dir("Edited")
        # PHX-FIX: mesma classe do achado acima (UUID vazando pro usuário) -
        # `path_obj.stem` aqui é o stem do arquivo TEMP (UUID), então o
        # arquivo editado que o usuário baixa se chamaria
        # "94e7446d-..._editado_a1b2c3d4.xlsx" em vez de algo reconhecível
        # como "CATALOGO_FINAL_MARKETUP_editado_a1b2c3d4.xlsx". `display_name`
        # já é o nome original (sanitizado - sem componentes de diretório,
        # ver _save_document_upload() em api_server.py), então só extrair o
        # stem dele é seguro.
        out_path = out_dir / f"{Path(display_name).stem}_editado_{uuid.uuid4().hex[:8]}{out_ext}"
        try:
            await asyncio.get_event_loop().run_in_executor(None, rebuild_document, str(result.output).strip(), out_path)
        except DocumentEngineError as e:
            return {"ok": False, "error": str(e)}

        edit_response = {"ok": True, "file_name": out_path.name, "file_path": str(out_path), "ocr_used": ocr_used}
        if ocr_used and ocr_meta:
            edit_response["ocr_pages_processed"] = ocr_meta["pages_processed"]
            edit_response["ocr_pages_total"] = ocr_meta["pages_total"]
            edit_response["ocr_truncated"] = ocr_meta["truncated"]
        return edit_response

    async def create_document_direct(
        self,
        instruction: str,
        output_format: str,
        filename: str = "",
        source_file_path: str | None = None,
        source_name: str | None = None,
        use_web: bool = False,
        web_query: str = "",
        model_hint: str = "",
    ) -> dict:
        """Cria ou transforma um documento em qualquer formato suportado.

        Sem `source_file_path`: cria do zero.
        Com `source_file_path`: usa PDF/DOCX/XLSX/PPTX/TXT/MD como base e
        materializa um NOVO PDF/DOCX/XLSX/PPTX/TXT/MD.

        Quando `use_web` (ou uma intenção explícita de pesquisa no prompt)
        estiver ativo, pesquisa via SearXNG antes da geração e injeta os
        resultados no contexto do LLM.
        """
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        instruction = (instruction or "").strip()
        output_format = (output_format or "").strip().lower().lstrip(".")
        filename = Path((filename or "").strip()).name
        allowed = {"pdf", "docx", "xlsx", "pptx", "txt", "md"}

        if not instruction:
            return {"ok": False, "error": "Instrução de criação/transformação vazia."}
        if output_format not in allowed:
            return {"ok": False, "error": f"Formato de saída '{output_format}' não suportado. Use: {', '.join(sorted(allowed))}."}

        await self._thermal_guard("Antes de criar/transformar documento")

        source_text = ""
        source_label = ""
        ocr_used = False
        ocr_meta = None
        if source_file_path:
            source_obj = Path(source_file_path)
            if not source_obj.exists():
                return {"ok": False, "error": f"Documento-base não encontrado: {source_file_path}"}
            source_label = (source_name or "").strip() or source_obj.name
            extraction = await self._extract_document_text_with_ocr_fallback(source_obj, source_label, char_limit=18000)
            if not extraction.get("ok"):
                return {"ok": False, "error": extraction.get("error", "Falha ao extrair o documento-base.")}
            source_text = extraction.get("content_for_prompt", "")
            ocr_used = bool(extraction.get("ocr_used"))
            ocr_meta = extraction.get("ocr_meta")

        # Pesquisa é parte nativa do pipeline documental quando explicitamente
        # pedida: "pesquise...", "busque na internet...", "use dados atuais...".
        web_requested = bool(use_web) or bool(re.search(
            r"\b(pesquis\w*|busqu\w*|procure\w*|search\b|web\b|internet\b|dados\s+atuais|informa[cç][oõ]es\s+atuais)\b",
            instruction,
            flags=re.IGNORECASE,
        ))

        # O árbitro resolve o ASSUNTO/GROUNDING antes da pesquisa e antes do LLM.
        # Isto é independente da escolha CPU/GPU: trocar recurso nunca troca a verdade.
        document_decision = self._resolve_document_decision(
            operation="transform" if source_file_path else "create",
            instruction=instruction,
            source_file_path=source_file_path,
            source_chars=len(source_text),
            output_format=output_format,
            use_web=web_requested,
        )
        if document_decision.rejected:
            return {"ok": False, "error": document_decision.reason}
        self_context = self._build_phoenix_self_context() if document_decision.subject == "phoenix_self" else ""

        web_context = ""
        web_sources: list[dict[str, str]] = []
        allowed_source_urls: set[str] = set()

        if web_requested:
            try:
                from phoenix_kernel.intelligence.web_search import search_web
                query = (web_query or instruction).strip()
                # Remove a parte de materialização do pedido para a busca receber
                # o ASSUNTO, não "crie um PDF/Excel..." junto com a consulta.
                query = re.split(
                    r"\b(?:e\s+)?(?:crie|gere|fa[çc]a|produza|monte|salve|exporte)\s+(?:um|uma)?\s*(?:arquivo\s+)?(?:pdf|word|docx|excel|xlsx|planilha|powerpoint|pptx|markdown|md|txt)\b",
                    query, maxsplit=1, flags=re.IGNORECASE,
                )[0].strip() or query

                # PHX-GROUNDING V1: recebe URL real do SearXNG. Antes search_web()
                # devolvia só título+snippet; o modelo era instruído a "citar fontes"
                # sem nunca receber as URLs e acabava inventando domínios.
                raw_sources = await search_web(query, max_results=8, structured=True)
                web_sources = [
                    s for s in (raw_sources or [])
                    if isinstance(s, dict) and str(s.get("url") or "").strip()
                ]

                if not web_sources:
                    return {
                        "ok": False,
                        "error": (
                            "Pesquisa web solicitada, mas o SearXNG não retornou nenhuma "
                            "fonte com URL verificável. O documento não será gerado com "
                            "fontes inventadas."
                        ),
                    }

                allowed_source_urls = {
                    str(s["url"]).strip() for s in web_sources if s.get("url")
                }

                source_chunks = []
                for source in web_sources:
                    sid = str(source.get("source_id") or "").strip()
                    title = str(source.get("title") or "").strip()
                    url = str(source.get("url") or "").strip()
                    snippet = str(source.get("snippet") or "").strip()
                    source_chunks.append(
                        f"[{sid}]\nTítulo: {title}\nURL: {url}\nTrecho: {snippet}"
                    )
                web_context = "\n\n".join(source_chunks)
            except Exception as e:
                return {"ok": False, "error": f"Pesquisa web solicitada, mas falhou antes da criação do documento: {e}"}

        resolved = self.registry.resolve("reasoning")
        doc_runtime = resolved.runtime if resolved else "llama.cpp"
        doc_model = resolved.id if resolved else "qwen3:8b"

        format_rules = {
            "xlsx": (
                "A saída será materializada como XLSX. Estruture dados tabulares com uma linha por registro "
                "e colunas separadas por ' | '. Não use tabela Markdown com linhas de traços. "
                "Pode incluir uma primeira linha de cabeçalho."
            ),
            "pptx": (
                "A saída será materializada como PPTX. Separe slides usando exatamente cabeçalhos "
                "'## Slide 1', '## Slide 2', etc. Cada bloco deve conter texto curto e apresentável."
            ),
            "pdf": (
                "A saída será materializada como um NOVO PDF. Organize em títulos, subtítulos, parágrafos "
                "e listas legíveis. Não diga que não pode gerar PDF."
            ),
            "docx": (
                "A saída será materializada como DOCX. Organize em títulos, subtítulos, parágrafos e listas."
            ),
            "md": "A saída será Markdown. Use Markdown limpo e semanticamente estruturado.",
            "txt": "A saída será texto puro. Não use marcação que dependa de Markdown.",
        }

        source_block = (
            f"\n\n--- DOCUMENTO-BASE: {source_label} ---\n{source_text}\n--- FIM DO DOCUMENTO-BASE ---"
            if source_text else ""
        )
        web_block = (
            f"\n\n--- PESQUISA WEB REAL ---\n{web_context}\n--- FIM DA PESQUISA WEB ---"
            if web_requested else ""
        )
        self_block = (
            f"\n\n--- PHOENIX SELF CONTEXT (FONTE INTERNA PRIORITÁRIA) ---\n{self_context}\n"
            "--- FIM DO PHOENIX SELF CONTEXT ---"
            if self_context else ""
        )

        plan = ExecutionPlan(
            runtime=doc_runtime,
            model=doc_model,
            parameters={
                "system_prompt": (
                    "Você é o Phoenix Document Composer. Produza o CONTEÚDO FINAL do arquivo solicitado, "
                    "sem explicar o processo, sem dizer que não consegue criar arquivos e sem envolver o "
                    "usuário em etapas manuais. O Phoenix Document Engine materializará sua saída. "
                    "Respeite a decisão de intenção/grounding fornecida pelo Phoenix Execution Arbiter. "
                    "Quando houver PHOENIX SELF CONTEXT, ele descreve ESTE projeto local e é a fonte prioritária; "
                    "não substitua Phoenix Engine por conhecimento paramétrico sobre produtos homônimos. "
                    "Quando houver PESQUISA WEB REAL no contexto, use somente fatos sustentados pelos resultados. "
                    "As fontes autorizadas são identificadas como [S1], [S2], etc. Você só pode citar URLs que apareçam "
                    "literalmente nessas fontes autorizadas. NUNCA invente, complete, adivinhe ou reconstrua uma URL. "
                    "Não atribua a uma fonte um fato que não esteja sustentado pelo trecho fornecido. "
                    "Não invente preços, versões, especificações, benchmarks, requisitos de hardware ou fontes. "
                    "Se um dado não estiver sustentado pelas fontes fornecidas, marque-o como 'Não verificado nas fontes consultadas' "
                    "ou omita-o. Em tarefas de pesquisa, cite [Sx] junto das afirmações relevantes e inclua ao final somente "
                    "as URLs autorizadas realmente utilizadas. "
                    + format_rules[output_format]
                ),
                "user_prompt": (
                    f"Instrução do usuário:\n{instruction}\n"
                    f"Decisão do árbitro: intent={document_decision.intent}; subject={document_decision.subject}; "
                    f"grounding={document_decision.grounding}; resource={document_decision.resource_policy.value}."
                    f"{source_block}{self_block}{web_block}\n\n"
                    "Entregue somente o conteúdo final pronto para materialização. "
                    "Complete todas as seções solicitadas e nunca termine no meio de uma frase."
                ),
                # PHX-FIX V6: documentos não têm teto artificial de tokens imposto
                # pela Phoenix. O driver recebe este sinal e NÃO envia max_tokens
                # ao llama-server. A geração termina por EOS do modelo ou pelo limite
                # físico de contexto/runtime; timeouts continuam sendo apenas proteção
                # contra execução realmente travada.
                "unlimited_output": True,
                "temperature": 0.15,
            },
            reasoning=f"Document Transform -> {output_format.upper()}",
        )

        self.logs.add_event(
            "INFO", "DirectDocumentBridge",
            f"Criando/transformando documento para {output_format.upper()} com '{doc_model}' ({doc_runtime})"
            + (f" usando base '{source_label}'" if source_label else "")
            + (" + pesquisa web" if web_requested else ""),
        )

        # Timeout adaptativo de SEGURANÇA. Isto NÃO limita a quantidade de
        # tokens: documentos usam unlimited_output=True e o modelo gera até EOS
        # ou até o limite físico do contexto. O relógio existe apenas para impedir
        # que uma inferência realmente travada fique presa indefinidamente.
        # A pesquisa web ocorre antes da inferência e não consome este orçamento.
        _model_lower = str(doc_model or "").lower()
        _large_model_markers = ("12b", "14b", "20b", "27b", "30b", "32b", "35b", "70b")
        document_timeout = (
            DOCUMENT_CREATE_TIMEOUT_LARGE_SECONDS
            if any(marker in _model_lower for marker in _large_model_markers)
            else DOCUMENT_CREATE_TIMEOUT_MEDIUM_SECONDS
        )

        self.logs.add_event(
            "INFO", "DirectDocumentBridge",
            f"Timeout documental selecionado: {document_timeout}s para '{doc_model}'."
        )

        try:
            result = await self._execute_document_plan_routed(
                plan, operation="create" if not source_text else "transform",
                source_chars=len(source_text) + len(web_context) + len(self_context),
                timeout=document_timeout,
                intent_decision=document_decision,
            )
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error": (
                    f"O modelo excedeu {document_timeout}s ao preparar o conteúdo do documento. "
                    "A Phoenix não aplicou limite de tokens; este é apenas o timeout de segurança "
                    "para uma execução que não concluiu dentro do orçamento do runtime."
                ),
            }

        if result.status != ExecutionStatus.SUCCESS:
            return {"ok": False, "error": "; ".join(result.errors) if result.errors else "Falha desconhecida ao preparar o documento."}

        # PHX-FIX (2026-09-06, achado real do usuário, com print de tela: o
        # documento "criado" era literalmente o raciocínio interno do
        # modelo em inglês - "Okay, I need to convert the given content...")
        # - `llama_cpp.py` tem um fallback antigo (PHX-FIX 22/08) que, quando
        # o campo `content` volta vazio mas `reasoning_content` tem texto,
        # usa o raciocínio como se fosse a resposta - pensado pra outro
        # cenário (comparação CPU/GPU), mas nunca antes verificado aqui.
        # Resultado: quando o modelo fica "pensando" até esgotar o espaço
        # (ou o parser de --jinja não fecha o bloco a tempo) sem nunca
        # produzir uma resposta final de verdade, esse fallback devolvia
        # "sucesso" com o pensamento bruto como corpo do arquivo - status
        # SUCCESS, sem erro nenhum, documento tecnicamente gerado mas
        # semanticamente lixo. Detectado agora ANTES de materializar
        # qualquer arquivo com esse conteúdo.
        if result.metrics.get("used_reasoning_fallback"):
            return {
                "ok": False,
                "error": (
                    "O modelo ficou 'pensando' até esgotar o espaço disponível, "
                    "sem produzir uma resposta final para o documento. Tente "
                    "novamente, simplifique o pedido ou reduza o tamanho do "
                    "documento-base."
                ),
            }

        # Self-grounding fail-closed: o caso real "Phoenix Engine = engine de jogos"
        # não pode virar um arquivo tecnicamente válido porém semanticamente falso.
        if document_decision.subject == "phoenix_self":
            confusion = self._detect_phoenix_self_confusion(str(result.output or ""), instruction)
            if confusion:
                self.logs.add_event(
                    "WARNING", "ExecutionArbiter",
                    "Self-grounding detectou confusão de entidade: " + ", ".join(confusion) + ". Reescrevendo uma vez.",
                )
                repair_plan = ExecutionPlan(
                    runtime=doc_runtime, model=doc_model,
                    parameters={
                        "system_prompt": (
                            "Corrija o documento sobre o PRÓPRIO projeto Phoenix. Use PHOENIX SELF CONTEXT como fonte "
                            "prioritária. Remova capacidades sem evidência e nunca trate Phoenix Engine como engine de jogos. "
                            + format_rules[output_format]
                        ),
                        "user_prompt": (
                            f"Instrução original:\n{instruction}{self_block}{source_block}{web_block}\n\n"
                            f"Primeira saída incorreta:\n{result.output}\n\n"
                            "Reescreva integralmente o conteúdo correto e factual."
                        ),
                        "unlimited_output": True, "temperature": 0.05,
                    },
                    reasoning=f"Phoenix Self-Grounding Repair -> {output_format.upper()}",
                )
                repaired = await self._execute_document_plan_routed(
                    repair_plan, operation="create" if not source_text else "transform",
                    source_chars=len(source_text) + len(web_context) + len(self_context),
                    timeout=document_timeout, intent_decision=document_decision,
                )
                if repaired.status != ExecutionStatus.SUCCESS:
                    return {"ok": False, "error": "; ".join(repaired.errors) if repaired.errors else "Falha na correção de self-grounding."}
                still = self._detect_phoenix_self_confusion(str(repaired.output or ""), instruction)
                if still:
                    return {
                        "ok": False,
                        "error": "O modelo continuou confundindo a Phoenix Engine deste projeto com uma entidade externa "
                                 f"({', '.join(still)}). O documento foi BLOQUEADO para não materializar conteúdo inventado.",
                    }
                result = repaired

        self._track_model_loaded(doc_runtime, doc_model)

        # PHX-GROUNDING V1: valida URLs tecnicamente ANTES de materializar.
        # Instrução no prompt não é segurança: se o modelo citar uma URL que não
        # veio do SearXNG, a geração é corrigida uma vez; se reincidir, falha e
        # nenhum PDF/DOCX/XLSX/etc é criado.
        def _extract_generated_urls(text: str) -> set[str]:
            urls = set(re.findall(r"https?://[^\\s\\]\\)\\}>\"']+", str(text or ""), flags=re.IGNORECASE))
            return {u.rstrip(".,;:!?") for u in urls}

        def _normalize_grounding_url(url: str) -> str:
            return str(url or "").strip().rstrip("/").lower()

        if web_requested:
            allowed_normalized = {
                _normalize_grounding_url(url) for url in allowed_source_urls
            }
            generated_urls = _extract_generated_urls(result.output or "")
            invalid_urls = {
                url for url in generated_urls
                if _normalize_grounding_url(url) not in allowed_normalized
            }

            if invalid_urls:
                invalid_list = "\n".join(f"- {u}" for u in sorted(invalid_urls))
                self.logs.add_event(
                    "WARNING", "WebGrounding",
                    f"Document Composer citou {len(invalid_urls)} URL(s) fora da allowlist. "
                    "Executando uma correção automática antes de materializar."
                )

                repair_plan = ExecutionPlan(
                    runtime=doc_runtime,
                    model=doc_model,
                    parameters={
                        "system_prompt": (
                            "Você é o Phoenix Document Composer em modo de CORREÇÃO DE GROUNDING. "
                            "Reescreva integralmente o conteúdo final solicitado usando SOMENTE as fontes "
                            "[S1]...[Sn] fornecidas abaixo. É proibido inventar, completar ou citar qualquer "
                            "URL fora da lista autorizada. Se não houver evidência suficiente para uma afirmação, "
                            "marque 'Não verificado nas fontes consultadas' ou omita a afirmação. "
                            + format_rules[output_format]
                        ),
                        "user_prompt": (
                            f"Instrução original:\n{instruction}"
                            f"{source_block}{web_block}\n\n"
                            "A primeira tentativa foi rejeitada porque citou estas URLs não autorizadas:\n"
                            f"{invalid_list}\n\n"
                            "Produza novamente SOMENTE o conteúdo final, completo, usando apenas as URLs "
                            "presentes em [S1]...[Sn]."
                        ),
                        "unlimited_output": True,
                        "temperature": 0.10,
                    },
                    reasoning=f"Document Grounding Repair -> {output_format.upper()}",
                )

                try:
                    repaired_result = await asyncio.wait_for(
                        self.runtime.execute(repair_plan), timeout=document_timeout
                    )
                except asyncio.TimeoutError:
                    return {
                        "ok": False,
                        "error": (
                            "A correção automática de grounding excedeu o timeout de segurança. "
                            "Nenhum documento foi materializado."
                        ),
                    }

                if repaired_result.status != ExecutionStatus.SUCCESS:
                    return {
                        "ok": False,
                        "error": (
                            "A correção automática de grounding falhou: "
                            + ("; ".join(repaired_result.errors) if repaired_result.errors else "erro desconhecido")
                        ),
                    }

                generated_urls = _extract_generated_urls(repaired_result.output or "")
                invalid_urls = {
                    url for url in generated_urls
                    if _normalize_grounding_url(url) not in allowed_normalized
                }
                if invalid_urls:
                    return {
                        "ok": False,
                        "error": (
                            "Grounding rejeitado: o modelo voltou a citar URL(s) que não vieram "
                            "do SearXNG. Nenhum documento foi materializado. URLs rejeitadas: "
                            + ", ".join(sorted(invalid_urls))
                        ),
                    }

                result = repaired_result
                self.logs.add_event(
                    "INFO", "WebGrounding",
                    "Correção automática aprovada: todas as URLs do documento pertencem à allowlist do SearXNG."
                )
            else:
                self.logs.add_event(
                    "INFO", "WebGrounding",
                    "Grounding aprovado: nenhuma URL fora da allowlist do SearXNG."
                )

        from phoenix_kernel.documents.engine import rebuild_document, DocumentEngineError
        from phoenix_kernel.paths import PhoenixPaths

        if not filename:
            stem = Path(source_label).stem if source_label else "documento_phoenix"
            filename = f"{stem}_{uuid.uuid4().hex[:8]}.{output_format}"
        else:
            stem = Path(filename).stem or "documento_phoenix"
            filename = f"{stem}.{output_format}"

        bucket = "Transformed" if source_file_path else "Created"
        out_dir = PhoenixPaths.get_documents_dir(bucket)
        out_path = out_dir / filename

        try:
            await asyncio.get_event_loop().run_in_executor(
                None, rebuild_document, str(result.output).strip(), out_path
            )
        except DocumentEngineError as e:
            return {"ok": False, "error": str(e)}

        response = {
            "ok": True,
            "file_name": out_path.name,
            "file_path": str(out_path),
            "format": output_format,
            "source_file": source_label or None,
            "web_used": web_requested,
            "web_grounded": bool(web_requested),
            "web_sources_count": len(web_sources) if web_requested else 0,
            "web_source_urls": sorted(allowed_source_urls) if web_requested else [],
            "model": doc_model,
            "runtime": doc_runtime,
            "ocr_used": ocr_used,
        }
        if ocr_used and ocr_meta:
            response["ocr_pages_processed"] = ocr_meta.get("pages_processed")
            response["ocr_pages_total"] = ocr_meta.get("pages_total")
            response["ocr_truncated"] = ocr_meta.get("truncated", False)
        return response

    # ============================================================
    # PONTE DIRETA: preenchimento de TEMPLATE de planilha existente.
    # PHX-NEW (pedido do usuário 2026-08-28: "aceitar dois arquivos - um
    # fonte, um template alvo - e editar o segundo em vez de gerar do
    # zero, pra qualquer documento que a Phoenix já lê e edita").
    #
    # Diferente de create_document_direct/edit_document_direct acima
    # (ambos sempre MATERIALIZAM UM ARQUIVO NOVO a partir de texto puro
    # via rebuild_document() - perdendo formatação, outras planilhas e
    # fórmulas do original), este bridge é o único que preserva o
    # arquivo-alvo de verdade: abre o .xlsx template com openpyxl e só
    # ACRESCENTA linhas nas colunas reais dele (ver
    # documents/engine.py::fill_xlsx_template). Por isso, hoje, só
    # aceita .xlsx como TEMPLATE - PDF/DOCX/PPTX não têm um conceito
    # equivalente de "coluna nomeada" pra mapear com segurança. Pra usar
    # um segundo arquivo como REFERÊNCIA ao editar esses outros formatos
    # (dobra o conteúdo na instrução, não faz merge estrutural), ver
    # `reference_file_path` em edit_document_direct() acima.
    #
    # Sem grounding de busca web tão elaborado quanto
    # create_document_direct (allowlist de URL + correção automática):
    # preencher células de planilha com dados extraídos raramente
    # precisa de citação embutida no texto - a pesquisa aqui só entra
    # como contexto extra pro LLM, e web_used no retorno já deixa claro
    # quando isso aconteceu.
    # ============================================================
    async def fill_spreadsheet_template_direct(
        self,
        source_file_path: str,
        template_file_path: str,
        instruction: str = "",
        source_name: str | None = None,
        template_name: str | None = None,
        use_web: bool = False,
        web_query: str = "",
        model_hint: str = "",
    ) -> dict:
        """Lê `source_file_path` (qualquer formato que a Document Engine já
        extrai: PDF/DOCX/XLSX/PPTX/TXT/MD) e usa o LLM pra mapear as
        informações encontradas nas colunas REAIS de `template_file_path`
        (um .xlsx já existente), devolvendo um NOVO arquivo com o template
        preenchido - o original nunca é sobrescrito."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        source_file_path = (source_file_path or "").strip()
        template_file_path = (template_file_path or "").strip()
        if not source_file_path:
            return {"ok": False, "error": "Caminho do documento-fonte vazio."}
        if not template_file_path:
            return {"ok": False, "error": "Caminho do template-alvo vazio."}

        source_obj = Path(source_file_path)
        template_obj = Path(template_file_path)
        if not source_obj.exists():
            return {"ok": False, "error": f"Documento-fonte não encontrado: {source_file_path}"}
        if not template_obj.exists():
            return {"ok": False, "error": f"Template-alvo não encontrado: {template_file_path}"}
        if template_obj.suffix.lower() != ".xlsx":
            return {
                "ok": False,
                "error": (
                    f"Template-alvo precisa ser .xlsx (recebido: '{template_obj.suffix}'). "
                    "Preenchimento estrutural preservando formatação só é suportado pra "
                    "planilhas hoje - pra editar um PDF/DOCX/PPTX/TXT/MD usando outro arquivo "
                    "como referência, use a edição de documento normal."
                ),
            }

        source_label = (source_name or "").strip() or source_obj.name
        template_label = (template_name or "").strip() or template_obj.name

        await self._thermal_guard("Antes de preencher template de planilha")

        from phoenix_kernel.documents.engine import (
            DocumentEngineError, fill_xlsx_template, read_xlsx_template_structure,
        )

        extraction = await self._extract_document_text_with_ocr_fallback(source_obj, source_label, char_limit=18000)
        if not extraction.get("ok"):
            return {"ok": False, "error": extraction.get("error", "Falha ao extrair o documento-fonte.")}
        # PHX-FIX (ver comentário de _SPREADSHEET_FILL_CHUNK_CHAR_BUDGET
        # acima): usa o texto COMPLETO (extraction["extracted"], sem
        # corte) em vez de extraction["content_for_prompt"] (cortado em
        # 18000 caracteres) - o corte acontecia bem antes do JSON chegar
        # a existir, então nenhuma quantidade de retry ou de correção no
        # parser do JSON conseguiria recuperar dados que nunca chegaram a
        # sair da extração. A divisão em pedaços abaixo é o que garante
        # que o documento inteiro seja considerado.
        source_text = extraction.get("extracted", "") or extraction.get("content_for_prompt", "")
        ocr_used = bool(extraction.get("ocr_used"))
        ocr_meta = extraction.get("ocr_meta")

        source_chunks = _split_text_into_chunks(source_text, _SPREADSHEET_FILL_CHUNK_CHAR_BUDGET)
        if not source_chunks:
            source_chunks = [""]
        source_truncated_extra_parts = 0
        if len(source_chunks) > _SPREADSHEET_FILL_MAX_CHUNKS:
            source_truncated_extra_parts = len(source_chunks) - _SPREADSHEET_FILL_MAX_CHUNKS
            source_chunks = source_chunks[:_SPREADSHEET_FILL_MAX_CHUNKS]
        num_chunks = len(source_chunks)

        loop = asyncio.get_event_loop()
        try:
            structure = await asyncio.wait_for(
                loop.run_in_executor(None, read_xlsx_template_structure, template_obj),
                timeout=DOCUMENT_EXTRACT_TIMEOUT_SECONDS,
            )
        except DocumentEngineError as e:
            return {"ok": False, "error": f"Falha ao ler a estrutura do template: {e}"}
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "error": (
                    f"Timeout ({DOCUMENT_EXTRACT_TIMEOUT_SECONDS}s) lendo a estrutura de "
                    f"'{template_label}' - planilha grande/complexa demais."
                ),
            }

        sheets = structure.get("sheets", [])
        if not sheets:
            return {"ok": False, "error": f"Template '{template_label}' não tem nenhuma planilha."}

        def _describe_sheet(s: dict) -> str:
            headers_desc = s["headers"] or "(planilha vazia, sem cabeçalho ainda)"
            line = f"- Planilha \"{s['name']}\": colunas = {headers_desc}"
            if s["last_row"]:
                line += f", já tem {s['last_row']} linha(s) preenchida(s)"
            return line

        sheets_description = "\n".join(_describe_sheet(s) for s in sheets)

        web_requested = bool(use_web) or bool(re.search(
            r"\b(pesquis\w*|busqu\w*|procure\w*|search\b|web\b|internet\b|dados\s+atuais)\b",
            instruction, flags=re.IGNORECASE,
        ))
        web_block = ""
        if web_requested:
            try:
                from phoenix_kernel.intelligence.web_search import search_web
                query = (web_query or instruction or source_label).strip()
                web_results = await search_web(query, max_results=5)
                if web_results:
                    web_block = f"\n\n--- PESQUISA WEB (contexto extra, use se ajudar a completar dados) ---\n{web_results}\n--- FIM DA PESQUISA WEB ---"
            except Exception as e:
                # Diferente de create_document_direct (que FALHA a geração
                # inteira se a pesquisa pedida não retornar nada, porque lá
                # a busca é o conteúdo principal): aqui a pesquisa é só
                # contexto auxiliar pra preencher células - uma falha nela
                # não deveria impedir de preencher o que já dá pra extrair
                # do documento-fonte sozinho.
                self.logs.add_event("WARNING", "DirectSpreadsheetFillBridge", f"Pesquisa web falhou (ignorada): {e}")

        ocr_note = ""
        if ocr_used and ocr_meta:
            ocr_note = (
                f"(Texto obtido via OCR automático - documento escaneado, sem camada de texto "
                f"nativa. {ocr_meta.get('pages_processed')} de {ocr_meta.get('pages_total')} "
                "página(s) processada(s).)\n\n"
            )

        resolved = self.registry.resolve("reasoning", hint=model_hint)
        doc_runtime = resolved.runtime if resolved else "llama.cpp"
        doc_model = resolved.id if resolved else "qwen3:8b"

        # PHX-FIX (achado real do usuário 2026-08-28, verificando os
        # próprios "30 minutos" espalhados pelo código depois do fix de
        # chunking): create_document_direct (função irmã, ver
        # DOCUMENT_CREATE_TIMEOUT_LARGE_SECONDS/MEDIUM_SECONDS acima)
        # escolhe o orçamento de timeout por TAMANHO do modelo (12b+ usa
        # o teto LARGE, calibrado pra bater com o piso que llama_cpp.py
        # aplica pra modelo grande - ver comentário "Resident corta em
        # 60 min" no driver, DOCUMENT_CREATE_TIMEOUT_LARGE_SECONDS foi
        # pra 3600s/1h a pedido do usuário testando Gemma 4 12B).
        # fill_spreadsheet_template_direct nunca fazia essa mesma escolha
        # - usava sempre o teto MEDIUM (20min) por pedaço, não importa o
        # modelo. Com o modelo padrão (qwen3-8b, "8b" não entra na lista
        # de "modelo grande"), isso nunca deu problema visível (o driver
        # também cai no mesmo teto de 20min pra esse caso). Mas se
        # alguém trocar de modelo pra um de 12b+ pra esse recurso, o
        # driver calcularia um piso bem maior (calibrado pro orçamento
        # LARGE) enquanto o loop de pedaços aqui ainda cancelaria a
        # chamada no teto MEDIUM - a chamada seria cortada ANTES do
        # próprio piso que o driver escolheu pra ela, um descompasso
        # real, só que hoje adormecido (não afeta o modelo realmente em
        # uso). Corrigido preventivamente usando a MESMA lista/constantes
        # já usadas em create_document_direct, pra não reintroduzir esse
        # descompasso quando o modelo mudar - e pra herdar automaticamente
        # qualquer ajuste futuro nos dois tetos (como este mesmo aumento
        # pra 1h), sem precisar lembrar de mexer em dois lugares.
        _large_model_markers = ("12b", "14b", "20b", "27b", "30b", "32b", "35b", "70b")
        _chunk_document_timeout = (
            DOCUMENT_CREATE_TIMEOUT_LARGE_SECONDS
            if any(marker in doc_model.lower() for marker in _large_model_markers)
            else DOCUMENT_CREATE_TIMEOUT_MEDIUM_SECONDS
        )

        system_prompt = (
            "Você é o Phoenix Spreadsheet Filler. Sua única tarefa é ler o DOCUMENTO-FONTE e "
            "devolver os dados encontrados nele como linhas para inserir numa planilha existente, "
            "usando EXATAMENTE os nomes de coluna do TEMPLATE informado abaixo - nunca invente "
            "nomes de coluna novos a menos que o dado realmente não caiba em nenhuma coluna "
            "existente. Responda SOMENTE com um objeto JSON no formato "
            '{"sheet": "<nome exato de uma das planilhas do template>", '
            '"rows": [{"<Coluna>": "<valor>", ...}, ...]}. '
            "Uma linha por registro/pessoa/item encontrado no documento-fonte. Nunca invente "
            "dado que não esteja no documento-fonte - use string vazia quando não souber um "
            "valor. Nunca inclua explicação, markdown ou texto fora do JSON. "
            # PHX-FIX (achado do usuário 2026-08-28: "modelo não devolveu um
            # JSON válido... mesmo após 2 tentativas" com qwen3-8b): modelos
            # "de raciocínio" gastam uma parte do orçamento de max_tokens
            # "pensando" antes de responder - numa extração com várias
            # linhas (catálogo inteiro), isso podia consumir o max_tokens
            # inteiro antes do JSON de verdade começar, cortando a resposta
            # no meio do raciocínio (nunca chegava a existir JSON nenhum pra
            # extrair). "/no_think" é a marcação documentada do Qwen3 pra
            # pular a etapa de raciocínio - inofensiva pra outros modelos
            # (só um pedido em texto que eles ignoram)."
            "Vá direto para a resposta em JSON, sem escrever seu raciocínio antes. /no_think"
        )
        # PHX-FIX (mesmo achado - processamento em pedaços): quando o
        # documento precisou ser dividido, o modelo só enxerga UM pedaço
        # de cada vez - sem este aviso, ele podia tentar "adivinhar" itens
        # de partes que não viu, ou reclamar que a lista está incompleta.
        # Pra um documento pequeno (num_chunks == 1, o caso mais comum),
        # o system_prompt fica BYTE-A-BYTE igual ao de antes desta
        # correção.
        if num_chunks > 1:
            system_prompt += (
                " O documento-fonte foi dividido em partes por limite de tamanho do modelo - "
                "extraia SOMENTE os itens presentes NESTA parte, não invente itens de outras "
                "partes nem tente adivinhar o que vem antes ou depois."
            )

        def _build_user_prompt(chunk_text: str, part_note: str) -> str:
            return (
                f"TEMPLATE \"{template_label}\" - planilhas e colunas disponíveis:\n{sheets_description}\n\n"
                f"DOCUMENTO-FONTE \"{source_label}\"{part_note}:\n\n{ocr_note}{chunk_text}"
                f"{web_block}\n\n"
                f"Instrução adicional do usuário: {instruction.strip() or '(nenhuma - use seu melhor julgamento pra mapear os dados nas colunas certas)'}"
            )

        from phoenix_kernel.intelligence.reasoning_engine import _extract_json_object

        retry_attempts = 2

        async def _run_extraction_for_chunk(chunk_text: str, part_note: str) -> tuple[list[dict] | None, str, str | None]:
            """Roda o loop de tentativa+retry (JSON inválido -> 1 retry,
            comportamento idêntico ao de antes desta correção) pra UM
            pedaço do documento-fonte. Devolve (rows, sheet_pedida, erro):
            `rows` é uma lista (possivelmente vazia - um pedaço sem nenhum
            item relevante é normal, não é erro) quando a chamada teve
            sucesso, ou None quando nenhuma tentativa teve sucesso pra
            este pedaço especificamente (erro descreve o motivo)."""
            prompt_base = _build_user_prompt(chunk_text, part_note)
            last_raw_local = ""
            for attempt in range(1, retry_attempts + 1):
                prompt = prompt_base if attempt == 1 else (
                    f"{prompt_base}\n\nATENÇÃO: sua resposta anterior não pôde ser lida como JSON "
                    f"(início do que você respondeu: {last_raw_local[:300]!r}). Responda OBRIGATORIAMENTE "
                    "com um único objeto JSON válido, sem texto antes ou depois, sem bloco de código "
                    "markdown."
                )
                plan = ExecutionPlan(
                    runtime=doc_runtime, model=doc_model,
                    parameters={
                        "system_prompt": system_prompt, "user_prompt": prompt, "json_format": True,
                        # PHX-FIX (achado do usuário 2026-08-28: "Erro na
                        # inferência do llama.cpp:" sem detalhe nenhum, numa
                        # máquina rodando o modelo bastante em CPU): sem isso, o
                        # LlamaCppDriver aplicava seu próprio piso de 600s pra
                        # esse modelo (não é "grande", max_tokens padrão) mesmo
                        # este método já orçando até _chunk_document_timeout
                        # (ver comentário completo onde a variável é calculada,
                        # acima - escala com o tamanho do modelo, igual
                        # create_document_direct já fazia) pra si mesmo - a
                        # inferência podia estourar 600s (prompt de entrada
                        # grande) bem antes de chegar no teto que já era
                        # considerado aceitável aqui. -60s de margem pra o
                        # timeout do driver sempre disparar (com mensagem
                        # específica) antes do asyncio.wait_for abaixo cancelar
                        # a chamada.
                        "timeout_seconds": _chunk_document_timeout - 60,
                        # PHX-FIX (mesmo achado, segunda causa): sem isso,
                        # max_tokens ficava no padrão de LlamaCppDriver (1024) -
                        # pouco pra mapear várias linhas de um catálogo inteiro
                        # (cada linha vira um objeto JSON), ainda mais com um
                        # modelo de raciocínio gastando parte do orçamento
                        # "pensando" antes de responder. 6144 dá margem real pro
                        # JSON de saída sem estourar o contexto de 32768 tokens
                        # do llama-server (aumentado de 16384 em 2026-09-06 -
                        # ver nota em _SPREADSHEET_FILL_CHUNK_CHAR_BUDGET sobre
                        # esse orçamento ainda não ter sido recalibrado pro
                        # contexto novo) (cada PEDAÇO já é limitado a
                        # _SPREADSHEET_FILL_CHUNK_CHAR_BUDGET caracteres).
                        "max_tokens": 6144,
                    },
                    reasoning=f"Preencher template de planilha ({template_label}) a partir de ({source_label}){part_note}",
                )
                try:
                    result = await asyncio.wait_for(
                        self.runtime.execute(plan), timeout=_chunk_document_timeout,
                    )
                except asyncio.TimeoutError:
                    return None, "", (
                        f"O modelo excedeu {_chunk_document_timeout}s ao mapear os "
                        f"dados do documento-fonte pras colunas do template{part_note}."
                    )
                if result.status != ExecutionStatus.SUCCESS:
                    return None, "", (
                        "; ".join(result.errors) if result.errors else f"Falha desconhecida ao mapear os dados{part_note}."
                    )

                last_raw_local = result.output or ""
                parsed = _extract_json_object(last_raw_local)
                if parsed is not None:
                    rows_local = parsed.get("rows")
                    sheet_local = str(parsed.get("sheet") or "").strip()
                    if isinstance(rows_local, list):
                        return [r for r in rows_local if isinstance(r, dict)], sheet_local, None
                    # JSON válido mas "rows" não é uma lista - trata como
                    # zero itens NESTE pedaço (não aborta o documento
                    # inteiro por causa de um pedaço malformado).
                    return [], sheet_local, None

            return None, "", (
                f"O modelo não devolveu um JSON válido mapeando os dados, mesmo após "
                f"{retry_attempts} tentativa(s){part_note}."
            )

        rows_by_chunk: list[list[dict]] = []
        sheet_votes: dict[str, int] = {}
        chunk_errors: list[str] = []
        for idx, chunk_text in enumerate(source_chunks, start=1):
            part_note = f" (parte {idx} de {num_chunks})" if num_chunks > 1 else ""
            chunk_rows, chunk_sheet, chunk_error = await _run_extraction_for_chunk(chunk_text, part_note)
            if chunk_error is not None:
                chunk_errors.append(chunk_error)
                self.logs.add_event(
                    "WARNING", "DirectSpreadsheetFillBridge",
                    f"Pedaço {idx}/{num_chunks} do documento-fonte falhou (ignorado, seguindo com o resto): {chunk_error}",
                )
                continue
            rows_by_chunk.append(chunk_rows)
            if chunk_sheet:
                sheet_votes[chunk_sheet] = sheet_votes.get(chunk_sheet, 0) + 1

        if not rows_by_chunk and chunk_errors:
            # Nenhum pedaço teve sucesso - no caso comum (documento pequeno,
            # um pedaço só), esse é o único erro mesmo, mensagem idêntica à
            # de antes desta correção.
            return {"ok": False, "error": chunk_errors[0] + " Nenhum arquivo foi preenchido."}

        self._track_model_loaded(doc_runtime, doc_model)

        rows = _merge_and_dedupe_rows(rows_by_chunk)
        if not rows:
            return {"ok": False, "error": "O modelo não encontrou nenhuma linha de dados pra inserir no template."}

        requested_sheet = max(sheet_votes, key=sheet_votes.get) if sheet_votes else ""
        valid_sheet_names = {s["name"] for s in sheets}
        target_sheet = requested_sheet if requested_sheet in valid_sheet_names else sheets[0]["name"]

        out_dir = PhoenixPaths.get_documents_dir("Filled")
        out_path = out_dir / f"{Path(template_label).stem}_preenchido_{uuid.uuid4().hex[:8]}.xlsx"

        try:
            fill_report = await loop.run_in_executor(
                None, fill_xlsx_template, template_obj, {target_sheet: rows}, out_path,
            )
        except DocumentEngineError as e:
            return {"ok": False, "error": str(e)}

        response = {
            "ok": True,
            "file_name": out_path.name,
            "file_path": str(out_path),
            "rows_written": fill_report["rows_written"],
            "sheet_used": fill_report["sheets_used"][0] if fill_report["sheets_used"] else target_sheet,
            "auto_created_columns": fill_report["auto_created_columns"],
            "source_file": source_label,
            "template_file": template_label,
            "web_used": web_requested,
            "model": doc_model,
            "runtime": doc_runtime,
            "ocr_used": ocr_used,
            # PHX-FIX (ver comentário de _SPREADSHEET_FILL_CHUNK_CHAR_BUDGET
            # acima): antes, um documento grande sendo cortado em silêncio
            # não deixava rastro nenhum na resposta - "sucesso" e "só
            # capturou 15% do documento" pareciam idênticos pra quem
            # chamou a API. Estes campos dão visibilidade real: quantos
            # pedaços existiam, quantos falharam (e por quê, no log), e se
            # o documento era tão grande que nem todos os pedaços couberam
            # no teto de segurança (_SPREADSHEET_FILL_MAX_CHUNKS).
            "chunks_processed": len(rows_by_chunk),
            "chunks_total": num_chunks,
        }
        if chunk_errors:
            response["chunks_failed"] = len(chunk_errors)
            response["chunks_failed_errors"] = chunk_errors
        if source_truncated_extra_parts:
            response["source_truncated_extra_parts"] = source_truncated_extra_parts
        if ocr_used and ocr_meta:
            response["ocr_pages_processed"] = ocr_meta.get("pages_processed")
            response["ocr_pages_total"] = ocr_meta.get("pages_total")
            response["ocr_truncated"] = ocr_meta.get("truncated", False)
        return response

    # ============================================================
    # PONTE DIRETA: colaboração real entre DOIS modelos de texto - pedido
    # do usuário 2026-08-22: "dois modelos de texto conversando num
    # projeto (um na cpu e outro na gpu), debatendo sobre qualquer
    # assunto e aprendendo um com o outro ou trocando ideias até
    # finalizarem um projeto... sempre usar llama.cpp pra tudo com vulkan
    # nativos... acesso a internet sem restrições". Um lado roda inteiro
    # na CPU (o motor de chat PADRÃO, porta 8081, -ngl 0 - o mesmo já
    # usado no chat normal, não sobe processo novo); o outro roda inteiro
    # na GPU via Vulkan (uma SEGUNDA instância dedicada do llama-server,
    # porta própria, offload total -ngl 999) - nunca split de camadas
    # entre os dois (ver hardware_fit.py). A lógica pura de turnos/busca/
    # conclusão vive em dual_collab.py; este método só cuida das decisões
    # de HARDWARE (qual porta, qual guarda de memória, subir/derrubar a
    # instância de GPU).
    #
    # Diferente de _thermal_guard/_vram_guard acima (avisam mas deixam
    # continuar, de propósito): aqui o usuário pediu um bloqueio de
    # verdade - se o modelo não cabe INTEIRO no hardware que vai rodá-lo,
    # a colaboração nem começa.
    # ============================================================
    # ============================================================
    # PHX-NEW (2026-09-03, achado real do usuário: fill via LLM demorou
    # >90min e o processo virou órfão): caminho DETERMINÍSTICO de
    # preenchimento de planilha. Diferente de
    # fill_spreadsheet_template_direct (que usa o LLM chunk a chunk, lento e
    # caro em CPU), este roda o Document Pipeline V2 (parser -> candidates ->
    # segmenter -> identity) + Smart Filler (regras + geração + guarda-fiscal)
    # 100% em Python, sem inferência. Nos catálogos reais do usuário: segundos
    # em vez de >90min. Não usa LLM, então não há o que travar.
    # ============================================================
    async def _enhance_sales_triggers_with_llm(
        self, xlsx_path: str, quadrants: list, *, max_calls: int = 20,
    ) -> int:
        """Passo 3: reescreve o gatilho de venda ("Descrição do Produto")
        com o LLM, SÓ para produtos casados com um quadrante de estratégia
        capturado (Passos 1/2) — cirúrgico, nunca o catálogo inteiro.
        Roda no contexto assíncrono do chamador (nunca dentro de um
        run_in_executor), para nunca precisar criar um event loop novo numa
        thread separada. Se o LLM falhar/estourar tempo num produto, esse
        produto MANTÉM o gatilho determinístico que o Smart Filler já
        escreveu — nunca apaga, nunca trava o restante. Devolve quantos
        produtos foram reescritos."""
        import openpyxl
        from phoenix_kernel.documents.cross_sell_suggester import match_product_to_quadrant

        wb = openpyxl.load_workbook(xlsx_path)
        ws = wb.active
        headers = [c.value for c in ws[1]]
        desc_col = next((headers.index(h) + 1 for h in ("Descrição", "DESCRIÇÃO") if h in headers), None)
        trigger_col = next(
            (headers.index(h) + 1 for h in ("Descrição do Produto", "DESCRIÇÃO DO PRODUTO") if h in headers),
            None,
        )
        if desc_col is None or trigger_col is None:
            return 0

        resolved = self.registry.resolve("chat") or self.registry.resolve("reasoning")
        doc_runtime = resolved.runtime if resolved else "llama.cpp"
        doc_model = resolved.id if resolved else "qwen3:8b"

        written = 0
        for r in range(2, ws.max_row + 1):
            if written >= max_calls:
                break
            nome = ws.cell(r, desc_col).value
            if not nome:
                continue
            match = match_product_to_quadrant(str(nome), quadrants)
            if match is None:
                continue  # sem quadrante -> mantém o texto determinístico
            q, _score = match

            prompt = (
                f"Escreva UMA frase curta e persuasiva (gatilho de venda) para o "
                f"produto \"{nome}\", em português, tom de loja de conveniência. "
                f"Contexto de estratégia comercial: este produto está na categoria "
                f"\"{q.name}\" ({q.margin_label or 'sem rótulo de margem'}"
                + (f", margem de {q.margin_min_pct:.0f}% a {q.margin_max_pct:.0f}%"
                   if q.margin_min_pct is not None else "")
                + f"). Papel do produto: {q.role or 'não especificado'}. "
                "Responda SÓ a frase final, sem aspas, sem explicações, sem markdown."
            )
            plan = ExecutionPlan(
                runtime=doc_runtime, model=doc_model,
                parameters={
                    "system_prompt": "Você é um redator de marketing para varejo de conveniência.",
                    "user_prompt": prompt, "json_format": False,
                    "timeout_seconds": 60, "max_tokens": 120,
                },
                reasoning=f"Gatilho de venda (Passo 3) para {str(nome)[:40]}",
            )
            try:
                result = await asyncio.wait_for(self.runtime.execute(plan), timeout=65)
            except asyncio.TimeoutError:
                continue  # mantém o determinístico, segue pro próximo produto
            if result.status != ExecutionStatus.SUCCESS:
                continue
            texto = (result.output or "").strip()
            if not texto:
                continue
            ws.cell(r, trigger_col).value = f"<p>{texto}</p>"
            written += 1

        if written:
            wb.save(xlsx_path)
        return written

    async def pipeline_fill_xlsx_direct(
        self,
        source_file_path: str,
        template_file_path: str,
        source_name: str | None = None,
        template_name: str | None = None,
        smart_fill: bool = True,
        use_llm_for_sales_trigger: bool = False,
        max_llm_sales_trigger_calls: int = 20,
    ) -> dict:
        """Preenche um template .xlsx a partir de um documento-fonte usando o
        pipeline DETERMINÍSTICO (sem LLM). Extrai os produtos do documento,
        casa cada dado na coluna certa por header, e — se smart_fill — aplica
        as regras de derivação/geração/guarda-fiscal do Smart Filler nas
        células ainda vazias. Preserva tudo que o template já tem.

        `use_llm_for_sales_trigger` (Passo 3, opt-in — desligado por padrão,
        respeitando "determinístico é o default"): depois do preenchimento
        determinístico (que já gera um gatilho de venda simples em
        "Descrição do Produto", com tom âncora/complementar se o documento
        tinha uma estratégia de margem capturada — Passos 1/2), reescreve
        esse texto com o LLM para produtos casados com um quadrante,
        limitado a `max_llm_sales_trigger_calls` (cirúrgico — não roda no
        catálogo inteiro, só numa amostra, respeitando o custo real de
        rodar LLM em CPU nesta máquina)."""
        source_obj = Path((source_file_path or "").strip())
        template_obj = Path((template_file_path or "").strip())
        if not source_obj.exists():
            return {"ok": False, "error": f"Documento-fonte não encontrado: {source_file_path}"}
        if not template_obj.exists():
            return {"ok": False, "error": f"Template-alvo não encontrado: {template_file_path}"}
        if template_obj.suffix.lower() != ".xlsx":
            return {"ok": False, "error": f"Template precisa ser .xlsx (recebido '{template_obj.suffix}')."}

        source_label = (source_name or "").strip() or source_obj.name
        template_label = (template_name or "").strip() or template_obj.name

        await self._thermal_guard("Antes do preenchimento determinístico de planilha")

        import asyncio
        loop = asyncio.get_event_loop()

        # 1) NormalizedDocument: PHX-FIX (2026-09, achado na integração final —
        # o caminho de produção usava parse_docx_to_normalized_document (só
        # para .docx) e normalized_document_from_text (ingênuo, quebra por
        # parágrafo) para o resto. NENHUM dos dois passava pela detecção de
        # formato genérica (structure_detector/name_detector) que validamos
        # com 642 testes e com os documentos reais do usuário — toda aquela
        # sofisticação ficava testada mas nunca rodava na rota real. Agora
        # TODO formato usa o mesmo caminho: extract_text (genérico, já lida
        # com docx/pdf/etc.) -> format_aware_document_from_text (detecta o
        # formato, segmenta por produto, resolve o nome). Medido nos 2
        # documentos reais: conveniência 231/231 com nome, construção
        # 129/147 — a mesma qualidade que a validação isolada já mostrava.
        try:
            from phoenix_kernel.documents.engine import extract_text
            from phoenix_kernel.documents.format_aware_parser import format_aware_document_from_text

            if source_obj.suffix.lower() in (".txt", ".md"):
                text = await loop.run_in_executor(None, extract_text, source_obj)
            else:
                extraction = await self._extract_document_text_with_ocr_fallback(
                    source_obj, source_label, char_limit=10_000_000,
                )
                if not extraction.get("ok"):
                    return {"ok": False, "error": extraction.get("error", "Falha ao extrair o documento-fonte.")}
                text = extraction.get("extracted", "") or extraction.get("content_for_prompt", "")

            document, format_info = await loop.run_in_executor(
                None, format_aware_document_from_text, text, source_label,
                source_obj.suffix.lower().lstrip(".") or "txt",
            )
            self.logs.add_event(
                "INFO", "FormatAwareParser",
                f"Formato detectado em '{source_label}': {format_info['format']} "
                f"({format_info['blocks_kept']} produtos, {format_info['blocks_named']} com nome).",
            )
        except Exception as e:
            return {"ok": False, "error": f"Falha ao normalizar o documento-fonte: {e}"}

        # 2) roda o pipeline determinístico (CPU-bound, fora do event loop)
        from phoenix_kernel.paths import PhoenixPaths
        import uuid as _uuid
        out_dir = PhoenixPaths.get_documents_dir("Filled")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{template_obj.stem}_pipeline_{_uuid.uuid4().hex[:8]}.xlsx"

        def _run():
            from phoenix_kernel.documents.pipeline_orchestrator import run_pipeline_docx_to_xlsx
            result = run_pipeline_docx_to_xlsx(
                document=document, template_path=str(template_obj), output_path=str(out_path),
            )
            # 3) Smart Filler nas células ainda vazias (regras + geração).
            # row_enricher casa cada produto com um quadrante de estratégia
            # (se o documento tinha esse padrão — Passos 1/2), para o
            # gatilho de venda gerado ("Descrição do Produto") escolher o
            # tom certo (âncora vs. complementar) mesmo sem LLM.
            smart_report = None
            if smart_fill and out_path.exists():
                from phoenix_kernel.documents.smart_filler import smart_fill_xlsx
                row_enricher_cb = None
                if format_info.get("pricing_quadrants"):
                    from phoenix_kernel.documents.cross_sell_suggester import make_quadrant_row_enricher
                    row_enricher_cb = make_quadrant_row_enricher(format_info["pricing_quadrants"])
                smart_report = smart_fill_xlsx(
                    str(out_path), str(out_path), row_enricher=row_enricher_cb,
                )
            # 4) estratégia comercial capturada do documento (se houver) vira
            # uma aba extra — nunca descartada, nunca inventada (lista vazia
            # se o documento não tinha esse padrão).
            strategy_written = False
            crosssell_written = False
            if out_path.exists() and format_info.get("pricing_quadrants"):
                from phoenix_kernel.documents.format_aware_parser import (
                    write_pricing_strategy_sheet, write_cross_sell_sheet,
                )
                strategy_written = write_pricing_strategy_sheet(
                    str(out_path), format_info["pricing_quadrants"]
                )
                # 5) Passo 2: cruza os produtos JÁ ESCRITOS na planilha (lidos
                # de volta do próprio arquivo, para usar exatamente o que
                # ficou na coluna Descrição) com os quadrantes capturados, e
                # sugere combos de cross-sell — sem LLM, determinístico.
                if strategy_written:
                    import openpyxl as _openpyxl
                    _wb = _openpyxl.load_workbook(out_path, data_only=True)
                    _ws = _wb[_wb.sheetnames[0]]
                    _headers = [c.value for c in _ws[1]]
                    _desc_col = None
                    for _cand in ("Descrição", "DESCRIÇÃO"):
                        if _cand in _headers:
                            _desc_col = _headers.index(_cand) + 1
                            break
                    if _desc_col:
                        _produtos = [
                            {"Descrição": _ws.cell(r, _desc_col).value}
                            for r in range(2, _ws.max_row + 1)
                            if _ws.cell(r, _desc_col).value
                        ]
                        crosssell_written = write_cross_sell_sheet(
                            str(out_path), _produtos, format_info["pricing_quadrants"]
                        )
            return result, smart_report, strategy_written, crosssell_written

        try:
            result, smart_report, strategy_written, crosssell_written = await loop.run_in_executor(None, _run)
        except Exception as e:
            return {"ok": False, "error": f"Falha no pipeline determinístico: {e}"}

        # 6) Passo 3 (opt-in): reescreve o gatilho de venda com o LLM para os
        # produtos casados com um quadrante — rodando aqui, no contexto
        # assíncrono principal (não dentro do executor), para nunca precisar
        # misturar event loops entre threads. Cirúrgico: no máximo
        # `max_llm_sales_trigger_calls` chamadas, nunca o catálogo inteiro —
        # LLM em CPU nesta máquina é caro por chamada (ver a conversa sobre
        # viabilidade de modelos grandes).
        sales_triggers_llm_written = 0
        if (use_llm_for_sales_trigger and out_path.exists()
                and format_info.get("pricing_quadrants") and self.runtime is not None):
            try:
                sales_triggers_llm_written = await self._enhance_sales_triggers_with_llm(
                    str(out_path), format_info["pricing_quadrants"],
                    max_calls=max_llm_sales_trigger_calls,
                )
            except Exception as e:
                self.logs.add_event(
                    "WARNING", "SalesTriggerLLM",
                    f"Aprimoramento por LLM dos gatilhos de venda falhou (mantido o "
                    f"determinístico): {e}",
                )

        self.logs.add_event(
            "INFO", "PipelineFillBridge",
            f"Preenchimento determinístico: {result.records_total} registros -> "
            f"{result.rows_written} linhas em '{template_label}' (sem LLM).",
        )

        resp = {
            "ok": True,
            "file_path": str(out_path),
            "file_name": out_path.name,
            "rows_written": result.rows_written,
            "records_total": result.records_total,
            "columns_mapped": result.columns_mapped,
            "source_file": source_label,
            "template_file": template_label,
            "method": "deterministic_pipeline_v2",
        }
        if smart_report is not None:
            resp["smart_fill"] = {
                "by_rule": sum(smart_report.filled_by_rule.values()),
                "by_generation": sum(smart_report.filled_by_generation.values()),
                "fiscal_blank": sum(smart_report.left_blank_fiscal.values()),
                "pending": len(smart_report.pending),
            }
        return resp

    async def run_dual_model_collaboration_direct(
        self, topic: str, max_rounds: int = 6,
        cpu_model_hint: str = "", gpu_model_hint: str = "",
    ) -> dict:
        """Roda uma colaboração completa entre os dois modelos AGORA (sem
        aprovação de missão) e devolve o transcript inteiro quando
        terminar. Bloqueante - pode levar vários minutos (ver
        dual_collab.TOTAL_TIME_BUDGET_SECONDS).

        PHX-NEW (pedido do usuário 2026-08-22, depois de descobrir que o
        modelo de raciocínio padrão da instalação - qwen3-8b-q4_k_m,
        ~5GB de arquivo - não cabe na VRAM útil da RX 580 8GB dele com a
        margem de segurança da trava): `cpu_model_hint`/`gpu_model_hint`
        agora são INDEPENDENTES - cada lado pode usar um modelo .gguf
        diferente (ex: um modelo pequeno na GPU que caiba na VRAM
        disponível, outro maior/mais forte na CPU que só precisa caber na
        RAM, bem mais folgada). Vazios (padrão) preservam o comportamento
        ORIGINAL: os dois lados usam o mesmo modelo de raciocínio padrão da
        Phoenix - só muda o hardware."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        topic = (topic or "").strip()
        if not topic:
            return {"ok": False, "error": "Tema da colaboração vazio."}

        # PHX-NEW (pedido do usuario 2026-08-22, apos o usuario perguntar se
        # chat e Arena "funcionam em paralelo"): descoberto durante essa
        # pergunta que NAO havia nenhuma trava contra duas colaboracoes
        # simultaneas (uma pelo comando /colaborar do chat, outra pela aba
        # Colaboracao do Arena, ou duas abas do navegador) - as duas tentariam
        # reaproveitar/trocar o MESMO motor compartilhado de CPU (porta 8081) e
        # subir a MESMA porta dedicada de GPU (8090), corrompendo o estado uma
        # da outra. Guarda simples de reentrancia: uma colaboracao por vez.
        if getattr(self, "_dual_collab_active", False):
            return {
                "ok": False,
                "error": (
                    "Ja existe uma colaboracao entre dois modelos em andamento - "
                    "espere ela terminar (ou pare) antes de iniciar outra. O chat "
                    "(/colaborar) e o Arena (aba Colaboracao) usam a mesma ponte por "
                    "baixo, entao nao da pra rodar duas ao mesmo tempo."
                ),
            }
        self._dual_collab_active = True
        # PHX-NEW (2026-08-22, pedido do usuário depois de ver a Arena com a
        # ampulheta piscando o tempo inteiro até as 6 rodadas terminarem,
        # dando a impressão de que travou): buffer ao vivo do progresso
        # desta colaboração - reiniciado aqui, no COMEÇO de uma rodada nova
        # (não no final), pra quem faz polling durante a corrida anterior
        # continuar vendo o último resultado completo até a próxima começar
        # de verdade, em vez de ver a lista sumir de repente.
        self._dual_collab_progress = []
        self._dual_collab_topic_live = topic
        try:
            from phoenix_kernel.models import hardware_fit
            from phoenix_kernel.intelligence import dual_collab
            from phoenix_kernel.intelligence.web_search import search_web
            from phoenix_kernel.runtime.drivers.llama_cpp import LlamaCppDriver, find_free_local_port

            resolved = self.registry.resolve("reasoning")
            default_hint = resolved.id if resolved else "qwen3:8b"
            cpu_model_hint = (cpu_model_hint or "").strip() or default_hint
            gpu_model_hint = (gpu_model_hint or "").strip() or default_hint

            # Localiza os arquivos .gguf de cada lado (podem ser o MESMO arquivo
            # ou dois diferentes) - reaproveita a busca em disco do próprio
            # driver (find_model_file_path, wrapper público) em vez de duplicar
            # essa lógica aqui. Uma única instância "sonda" (sem processo
            # próprio) resolve os dois.
            probe_driver = LlamaCppDriver()
            cpu_model_path = probe_driver.find_model_file_path(cpu_model_hint)
            if not cpu_model_path:
                return {"ok": False, "error": f"Modelo do lado CPU ('{cpu_model_hint}') não encontrado em disco - baixe-o antes de colaborar."}
            gpu_model_path = probe_driver.find_model_file_path(gpu_model_hint)
            if not gpu_model_path:
                return {"ok": False, "error": f"Modelo do lado GPU ('{gpu_model_hint}') não encontrado em disco - baixe-o antes de colaborar."}

            # As duas checagens agora são INDEPENDENTES - um modelo grande do
            # lado CPU não é penalizado pela VRAM da GPU, e vice-versa.
            cpu_required_mb = hardware_fit.estimate_model_memory_mb(cpu_model_path)
            ram_check = hardware_fit.check_ram_fit(cpu_required_mb)
            if not ram_check.fits:
                self.logs.add_event("ERROR", "DualCollabBridge", f"Bloqueado (RAM insuficiente para o lado CPU, modelo '{cpu_model_hint}'): {ram_check.detail}")
                return {"ok": False, "error": f"Modelo do lado CPU ('{cpu_model_hint}') não cabe inteiro na RAM disponível ({ram_check.detail})."}

            gpu_required_mb = hardware_fit.estimate_model_memory_mb(gpu_model_path)
            vram_total_mb, vram_used_mb = self._get_vram_budget_mb()
            vram_check = hardware_fit.check_vram_fit(gpu_required_mb, vram_total_mb, vram_used_mb)
            if not vram_check.fits:
                self.logs.add_event("ERROR", "DualCollabBridge", f"Bloqueado (VRAM insuficiente para o lado GPU, modelo '{gpu_model_hint}'): {vram_check.detail}")
                return {"ok": False, "error": f"Modelo do lado GPU ('{gpu_model_hint}') não cabe inteiro na VRAM disponível ({vram_check.detail})."}

            self.logs.add_event(
                "INFO", "DualCollabBridge",
                f"Checagem de memória OK - CPU ('{cpu_model_hint}'): {ram_check.detail} | GPU ('{gpu_model_hint}'): {vram_check.detail}",
            )

            await self._thermal_guard("Antes de iniciar colaboração de dois modelos")

            # Lado CPU: reaproveita o llama-server PADRÃO (porta 8081, o mesmo
            # motor do chat normal) - mas se o modelo pedido pro lado CPU for
            # DIFERENTE do que já estava carregado nele, troca temporariamente.
            # Guarda o plano ORIGINAL (get_last_plan, o mesmo estado que o
            # watchdog usa pra restaurar depois de uma queda) pra devolver o
            # motor compartilhado exatamente como estava quando a colaboração
            # terminar - o chat normal não pode ficar "preso" no modelo da
            # colaboração depois dela acabar.
            previous_cpu_plan = self.runtime.get_last_plan("llama.cpp")
            cpu_load_plan = ExecutionPlan(runtime="llama.cpp", model=cpu_model_hint, parameters={})
            cpu_started_ok = await self.runtime.start("llama.cpp", cpu_load_plan)
            if not cpu_started_ok:
                self.logs.add_event("ERROR", "DualCollabBridge", f"Falha ao carregar o modelo do lado CPU ('{cpu_model_hint}').")
                return {"ok": False, "error": f"Falha ao carregar o modelo do lado CPU ('{cpu_model_hint}') - veja os logs do Engine."}

            async def _restore_cpu_model() -> None:
                if previous_cpu_plan is not None:
                    await self.runtime.start("llama.cpp", previous_cpu_plan)

            async def cpu_execute(system_prompt: str, user_prompt: str) -> str:
                plan = ExecutionPlan(
                    runtime="llama.cpp", model=cpu_model_hint,
                    parameters={"system_prompt": system_prompt, "user_prompt": user_prompt, "max_tokens": 1024},
                    reasoning="Ponte direta (chat Aviary): colaboração de dois modelos (lado CPU)",
                )
                result = await asyncio.wait_for(self.runtime.execute(plan), timeout=dual_collab.TURN_EXECUTE_TIMEOUT_SECONDS)
                if result.status != ExecutionStatus.SUCCESS:
                    raise RuntimeError("; ".join(result.errors) if result.errors else "Falha desconhecida no lado CPU.")
                raw_output = result.output or ""
                # PHX-NEW (2026-08-22, achado real do usuário: lado CPU voltou
                # vazio em 6 rodadas seguidas de uma colaboração real) - log
                # visível no painel de eventos do Engine (não só no
                # logger/stderr do llama_cpp.py) com o tamanho de verdade da
                # resposta, pra confirmar com evidência (não suposição) se o
                # fallback de reasoning_content em llama_cpp.py resolveu, ou
                # se o problema é outro (ver PHX-FIX em llama_cpp.py:execute).
                self.logs.add_event(
                    "INFO" if raw_output.strip() else "WARNING", "DualCollabBridge",
                    f"Lado CPU ('{cpu_model_hint}') respondeu: {len(raw_output)} caractere(s)"
                    + ("" if raw_output.strip() else " - RESPOSTA VAZIA (ver PHX-FIX/reasoning_content em llama_cpp.py)"),
                )
                return raw_output

            # Lado GPU: instância SEPARADA e dedicada. A porta 8090 deixou
            # de ser hardcoded depois de um achado real no Windows: ela já
            # estava ocupada por WsToastNotification. Selecionamos uma porta
            # livre da faixa reservada e, MAIS IMPORTANTE, fazemos um self-test
            # de correctness antes de entregar o backend à Arena. Em Polaris,
            # /health=200 + VRAM ocupada + throughput normal NÃO garantiram
            # resposta correta (saída degenerada "????"/tokens repetidos).
            gpu_port = find_free_local_port(8095, 8110)
            gpu_driver = LlamaCppDriver(
                port=gpu_port,
                force_ngl="999",
                device="Vulkan0",
                context_size=16384,
            )
            started_ok = await gpu_driver.start(ExecutionPlan(runtime="llama.cpp", model=gpu_model_hint, parameters={}))
            if not started_ok:
                await gpu_driver.stop()
                self.logs.add_event("ERROR", "DualCollabBridge", f"Falha ao iniciar a instância dedicada de GPU do llama-server na porta {gpu_port}.")
                await _restore_cpu_model()
                return {"ok": False, "error": "Falha ao iniciar a instância dedicada de GPU do llama-server (ver logs do Engine)."}

            sanity_ok, sanity_detail = await gpu_driver.sanity_check(timeout=90.0)
            if not sanity_ok:
                await gpu_driver.stop()
                self.logs.add_event(
                    "ERROR", "DualCollabBridge",
                    "Worker Vulkan REJEITADO pelo self-test de correctness: " + sanity_detail,
                )
                await _restore_cpu_model()
                return {
                    "ok": False,
                    "error": (
                        "A GPU/Vulkan foi detectada, mas a inferência não passou no self-test de correctness. "
                        "A Arena não vai usar uma GPU que responde HTTP 200 mas gera saída corrompida. "
                        f"Detalhe: {sanity_detail}"
                    ),
                }

            self._track_model_loaded("llama.cpp-gpu-collab", gpu_model_hint)

            async def gpu_execute(system_prompt: str, user_prompt: str) -> str:
                plan = ExecutionPlan(
                    runtime="llama.cpp", model=gpu_model_hint,
                    parameters={"system_prompt": system_prompt, "user_prompt": user_prompt, "max_tokens": 1024},
                    reasoning="Ponte direta (chat Aviary): colaboração de dois modelos (lado GPU)",
                )
                result = await asyncio.wait_for(gpu_driver.execute(plan), timeout=dual_collab.TURN_EXECUTE_TIMEOUT_SECONDS)
                if result.status != ExecutionStatus.SUCCESS:
                    raise RuntimeError("; ".join(result.errors) if result.errors else "Falha desconhecida no lado GPU.")
                raw_output = result.output or ""
                self.logs.add_event(
                    "INFO" if raw_output.strip() else "WARNING", "DualCollabBridge",
                    f"Lado GPU ('{gpu_model_hint}') respondeu: {len(raw_output)} caractere(s)"
                    + ("" if raw_output.strip() else " - RESPOSTA VAZIA (ver PHX-FIX/reasoning_content em llama_cpp.py)"),
                )
                return raw_output

            async def search_fn(query: str) -> str:
                return await search_web(query, max_results=5)

            # PHX-NEW (2026-08-22, achado real do usuário: 6 rodadas de
            # "corrigi o bug de performance" que nunca corrigiam nada de
            # verdade - cache declarado dentro da função, recriado a cada
            # chamada) - roda o código proposto em cada rodada, de verdade,
            # num subprocesso isolado com timeout (ver patch_verification.py)
            # em vez de aceitar a explicação em texto do modelo. Escopo
            # honesto: só produz uma nota quando o TEMA da colaboração é
            # sobre corrigir uma função nomeada específica e a rodada propõe
            # um bloco de código Python que redefine essa mesma função - fora
            # disso, devolve None e nenhuma alegação extra é feita.
            from phoenix_kernel.intelligence import patch_verification

            async def verify_fn(collab_topic: str, turn_text: str) -> str | None:
                return await patch_verification.verify_lookup_cache_patch(collab_topic, turn_text)

            # PHX-NEW (2026-08-23, achado real do usuário: uma colaboração
            # fechou como "✅ Concluída" com a única verificação objetiva que
            # rodou tendo dado FALHOU - ver dual_collab.py::topic_is_verifiable
            # pro racional completo) - responde só "este tópico DESCREVE uma
            # função com nome extraível?" (propriedade do TÓPICO, igual
            # extract_function_name já faz pra achar o nome a verificar) -
            # não roda nenhum código, não sabe nada sobre o que os modelos
            # respondem, só diz se existe algo objetivo pra checar aqui.
            def topic_is_verifiable(collab_topic: str) -> bool:
                return patch_verification.extract_function_name(collab_topic) is not None

            # PHX-NEW (2026-08-22, ver "_dual_collab_progress" acima): publica
            # cada turno assim que termina (já com objective_check, se
            # houver - on_turn roda DEPOIS da checagem em dual_collab.py) no
            # mesmo formato de dict que o resultado final usa, pra
            # get_dual_collab_progress() (chamado por /api/dual-collab/progress)
            # devolver algo útil ENQUANTO esta função ainda está bloqueada
            # rodando as rodadas seguintes.
            async def on_turn(turn: "dual_collab.TurnRecord") -> None:
                self._dual_collab_progress.append({
                    "round": turn.round_number, "speaker": turn.speaker, "engine_label": turn.engine_label,
                    "text": turn.text, "searches": turn.searches, "objective_check": turn.objective_check,
                })

            try:
                collab_result = await dual_collab.run_dual_model_collaboration(
                    topic=topic, cpu_execute=cpu_execute, gpu_execute=gpu_execute,
                    search_fn=search_fn, logs_event=self.logs.add_event, max_rounds=max_rounds,
                    verify_fn=verify_fn, on_turn=on_turn, topic_is_verifiable=topic_is_verifiable,
                )
            except Exception as e:
                self.logs.add_event("ERROR", "DualCollabBridge", f"Colaboração abortada por erro: {e}")
                await gpu_driver.stop()
                self._track_model_unloaded("llama.cpp-gpu-collab")
                await _restore_cpu_model()
                return {"ok": False, "error": f"Colaboração abortada: {e}"}

            await gpu_driver.stop()
            self._track_model_unloaded("llama.cpp-gpu-collab")
            await _restore_cpu_model()

            return {
                "ok": True,
                "topic": topic,
                "cpu_model": cpu_model_hint,
                "gpu_model": gpu_model_hint,
                "concluded": collab_result.concluded,
                "stopped_reason": collab_result.stopped_reason,
                "rounds_completed": collab_result.rounds_completed,
                "transcript": [
                    {
                        "round": t.round_number, "speaker": t.speaker, "engine_label": t.engine_label,
                        "text": t.text, "searches": t.searches,
                        "objective_check": t.objective_check,
                    }
                    for t in collab_result.transcript
                ],
            }

        finally:
            self._dual_collab_active = False

    def get_dual_collab_progress(self) -> dict:
        """PHX-NEW (2026-08-22, pedido do usuário: "seria interessante a
        CPU responder e aparecer num terminal, e aí depois aparecer a GPU
        respondendo... não [esperar] até o final das sessões" - a Arena
        hoje só mostra a ampulheta girando, sem nenhuma pista visível, até
        as `max_rounds` rodadas terminarem TODAS de uma vez, o que dá a
        impressão de que travou): leitura RÁPIDA e NÃO-BLOQUEANTE do
        progresso da colaboração em andamento (ou da última que rodou, até
        a próxima começar) - só devolve o que já está guardado no buffer
        ao vivo (`_dual_collab_progress`, atualizado turno a turno via o
        `on_turn` passado pra `dual_collab.run_dual_model_collaboration`),
        nunca inicia nem espera nada. Pensado pra `/api/dual-collab/progress`
        ser chamado em polling (a cada 1-2s, mesmo padrão que o painel do
        Engine já usa pra `/api/state`) ENQUANTO a chamada bloqueante
        `/api/dual-collab` ainda está rodando."""
        return {
            "active": bool(getattr(self, "_dual_collab_active", False)),
            "topic": getattr(self, "_dual_collab_topic_live", ""),
            "transcript": list(getattr(self, "_dual_collab_progress", [])),
        }

    # ============================================================
    # PONTE DIRETA: troca de modelo de texto síncrona, sem passar pelo
    # Mission Kernel / aprovação. Mesmo padrão de generate_image_direct/
    # generate_speech_direct acima - útil pro Resident (ou uma missão)
    # trocar de modelo no meio de uma tarefa sem precisar montar uma
    # missão completa só pra isso (ex: detectou tarefa de código, quer
    # subir o Qwen2.5-Coder na hora em vez do modelo de chat padrão).
    # ============================================================
    async def load_model_direct(self, model_name: str, runtime: str = "llama.cpp") -> dict:
        """Carrega `model_name` no `runtime` indicado AGORA. Se já for o
        modelo certo, LlamaCppDriver.start() detecta isso e não recarrega
        à toa (ver PHX-FIX no llama_cpp.py). Retorna dict com sucesso/erro."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        model_name = (model_name or "").strip()
        if not model_name:
            return {"ok": False, "error": "Nome do modelo vazio."}

        plan = ExecutionPlan(
            runtime=runtime, model=model_name, parameters={},
            reasoning=f"Ponte direta: carregar '{model_name}'",
        )
        self.logs.add_event("INFO", "DirectModelBridge", f"Carregando modelo '{model_name}' em '{runtime}'...")
        success = await self.runtime.start(runtime, plan)

        if not success:
            self.logs.add_event("ERROR", "DirectModelBridge", f"Falha ao carregar '{model_name}'.")
            return {"ok": False, "error": f"Falha ao carregar modelo '{model_name}' em '{runtime}'."}

        self._track_model_loaded(runtime, model_name)
        self.logs.add_event("INFO", "DirectModelBridge", f"Modelo '{model_name}' ativo em '{runtime}'.")
        return {"ok": True, "model": model_name, "runtime": runtime}

    async def unload_model_direct(self, runtime: str = "llama.cpp") -> dict:
        """Descarrega o modelo atualmente ativo em `runtime`, liberando
        RAM/VRAM sem carregar nada no lugar."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        self.logs.add_event("INFO", "DirectModelBridge", f"Descarregando '{runtime}'...")
        success = await self.runtime.stop(runtime)
        if not success:
            return {"ok": False, "error": f"Falha ao descarregar '{runtime}' (talvez já estivesse parado)."}

        self._track_model_unloaded(runtime)
        self.logs.add_event("INFO", "DirectModelBridge", f"'{runtime}' descarregado - memória liberada.")
        return {"ok": True, "runtime": runtime}

    # ============================================================
    # PONTE DIRETA (auditoria 2026-08-20, "ResidentManager não pode ser
    # contornado" - Seção 3): benchmark real de token/s, sem passar pelo
    # Mission Kernel/aprovação. Antes desta ponte, POST /api/benchmark em
    # api_server.py resolvia o modelo via resident.registry.resolve("chat")
    # só pra citar no plan, mas executava com kernel.runtime.execute()
    # DIRETO - sem _thermal_guard e sem _track_model_loaded, mesmo
    # anti-padrão já corrigido pra imagem/voz/visão acima. Mede throughput
    # real de geração de tokens (não fabrica TFLOPs/largura de banda/
    # latência de shader Vulkan - isso continua fora do escopo, ver
    # comentário em api_server.py sobre isso).
    # ============================================================
    async def run_token_benchmark_direct(self) -> dict:
        """Roda uma inferência curta real no runtime de chat resolvido e
        devolve as métricas reais de tokens/s do ExecutionResult. Nunca
        fabrica número nenhum - se a execução falhar, devolve o erro real."""
        if self.runtime is None:
            return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

        await self._thermal_guard("Antes de rodar benchmark de tokens (ponte direta)")

        resolved = self.registry.resolve("chat")
        bench_runtime = resolved.runtime if resolved else "llama.cpp"
        bench_model = resolved.id if resolved else "qwen3:8b"

        plan = ExecutionPlan(
            runtime=bench_runtime,
            model=bench_model,
            parameters={
                "system_prompt": "Responda de forma extremamente breve.",
                "user_prompt": "Diga 'Phoenix Engine operacional' e conte de 1 a 5.",
                "max_tokens": 64,
            },
            reasoning="Ponte direta: benchmark real de throughput de tokens",
        )

        self.logs.add_event("INFO", "DirectBenchmarkBridge", f"Rodando benchmark de tokens em '{bench_runtime}'/'{bench_model}'...")
        # PHX-FIX (auditoria 2026-08-21, "corrigir tudo" - ver comentário de
        # BENCHMARK_EXECUTE_TIMEOUT_SECONDS no topo do arquivo): antes,
        # `self.runtime.execute(plan)` era chamado sem nenhum teto próprio -
        # só o timeout interno de cada driver (600s) limitava, bem acima dos
        # 60s que o Node esperava. Mesmo padrão de read_document_direct/
        # edit_document_direct: o Engine precisa desistir e devolver um erro
        # controlado ANTES do Node abortar a conexão.
        try:
            result = await asyncio.wait_for(
                self.runtime.execute(plan), timeout=BENCHMARK_EXECUTE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            self.logs.add_event(
                "ERROR", "DirectBenchmarkBridge",
                f"Timeout ({BENCHMARK_EXECUTE_TIMEOUT_SECONDS}s) ao rodar benchmark de tokens.",
            )
            return {
                "ok": False,
                "error": (
                    f"O benchmark não terminou em {BENCHMARK_EXECUTE_TIMEOUT_SECONDS}s. "
                    f"Isso costuma acontecer no primeiro benchmark depois do boot (o runtime "
                    f"'{bench_runtime}' ainda estava carregando o modelo '{bench_model}' - "
                    "cold start). Tente de novo agora que o modelo já deve estar carregado."
                ),
            }

        if result.status != ExecutionStatus.SUCCESS:
            self.logs.add_event("ERROR", "DirectBenchmarkBridge", f"Falha no benchmark: {result.errors}")
            return {"ok": False, "error": "; ".join(result.errors) if result.errors else "Benchmark falhou."}

        self._track_model_loaded(bench_runtime, bench_model)
        return {"ok": True, "runtime": bench_runtime, "model": bench_model, "metrics": result.metrics or {}}

    # ============================================================
    # PONTE DIRETA (auditoria 2026-08-20, "ResidentManager não pode ser
    # contornado" - Seção 3, achado mais grave desta rodada): o comando
    # `infer <prompt>` (ApiEngine.process_command() em
    # phoenix_kernel/api/engine.py, acionado por POST /api/command - o
    # caminho de inferência de texto crua mais usado, fora do chat da
    # Aviary) montava o plano via RuleEvaluator (planner.plan_inference,
    # que já resolve o modelo certo/hint de Ollama) mas EXECUTAVA com
    # `self.runtime.execute(plan)` DIRETO dentro do próprio ApiEngine -
    # `self.runtime` ali é o RuntimeEngine cru injetado no ApiEngine, não
    # o ResidentManager. Isso pulava _thermal_guard e _track_model_loaded
    # por completo nesse caminho - o único dos 8 itens da Seção 3 que
    # ainda bypassava o Resident depois dos fixes de imagem/voz/visão/
    # benchmark acima.
    #
    # Diferente das outras pontes diretas, esta recebe um ExecutionPlan JÁ
    # PRONTO (a resolução de modelo continua 100% no RuleEvaluator - não
    # duplica essa lógica aqui) e devolve o ExecutionResult bruto, não um
    # dict {"ok":...} - pra não mudar o contrato que ApiEngine.
    # process_command() já espera (result.status.value, result.errors,
    # plan.model/plan.runtime pra montar a mensagem de saída). Sem
    # _vram_guard de propósito: "chat"/"reasoning" são modelos de CPU por
    # decisão de design (vram_mb_estimate=0 no catalog/models.json, GPU
    # fica livre pra imagem) - mesmo motivo de read_document_direct/
    # edit_document_direct/transcribe_direct acima só chamarem
    # _thermal_guard, sem _vram_guard.
    # ============================================================
    async def run_inference_direct(self, plan: ExecutionPlan) -> ExecutionResult:
        """Executa um ExecutionPlan de inferência de texto já resolvido
        (ex: pelo comando 'infer', via RuleEvaluator), passando pelas
        mesmas guardas que toda outra ponte direta usa. Levanta
        RuntimeError se o RuntimeEngine não estiver disponível - o
        chamador (ApiEngine.process_command) já envolve isso num
        try/except genérico."""
        if self.runtime is None:
            raise RuntimeError("RuntimeEngine não disponível (não injetado no ResidentManager).")

        await self._thermal_guard("Antes de inferência de texto (comando 'infer')")

        self.logs.add_event("INFO", "DirectInferenceBridge", f"Executando inferência com '{plan.model}' ({plan.runtime})...")
        result = await self.runtime.execute(plan)

        if result.status == ExecutionStatus.SUCCESS:
            self._track_model_loaded(plan.runtime, plan.model)
        else:
            self.logs.add_event("ERROR", "DirectInferenceBridge", f"Falha na inferência: {result.errors}")

        return result

    # ============================================================
    # PONTE DIRETA: Aviary Swarm (painel AviarySwarmPanel.tsx, Port 3000)
    # despacha uma tarefa pra uma das 4 personas de agente. Antes desta
    # ponte, POST /api/agents/dispatch não existia em api_server.py e o
    # painel inteiro (thoughts, tasksCompleted, status ACTIVE/THINKING)
    # era estado estático da UI, nunca tocado por nenhuma chamada real -
    # ver LEIA-ME. Cada persona aqui é só uma etiqueta sobre uma
    # capacidade que já existe e já é real no kernel: nenhuma "IA"
    # nova foi inventada, nenhum resultado é fabricado. Mesmo padrão de
    # generate_image_direct/generate_speech_direct/transcribe_direct
    # acima - síncrono o bastante pro painel, sem gate de aprovação de
    # missão.
    # ============================================================
    async def dispatch_agent_task_direct(self, agent_id: str, task: str) -> dict:
        """Executa `task` através da persona `agent_id` do Aviary Swarm.
        Devolve {"ok": True, "output": str, ...} em sucesso ou
        {"ok": False, "error": str} em falha real - nunca fabrica um
        "pensamento" ou resultado quando a capacidade por trás falha ou
        não está disponível."""
        agent_id = (agent_id or "").strip()
        task = (task or "").strip()
        if not task:
            return {"ok": False, "error": "Tarefa vazia."}

        if agent_id == "agent-sentinel":
            # Phoenix Sentinel: monitoramento de hardware -> reaproveita
            # analyze_machine() (o mesmo método que 'manager analyze' no
            # CLI já chama) - sensores reais, alertas reais, RAG real.
            try:
                report = await self.analyze_machine()
            except Exception as e:
                logger.warning(f"AviarySwarmBridge: Sentinel falhou - {e}")
                return {"ok": False, "error": f"Falha na análise de hardware: {e}"}
            return {"ok": True, "output": report, "agent_id": agent_id}

        if agent_id == "agent-architect":
            # Aviary Architect: planejamento -> reaproveita process_intent()
            # (o mesmo método que 'resident research <intencao>' no CLI já
            # chama) - aciona o ReasoningEngine (LLM) de verdade. Só relata
            # o plano ou o erro real; não auto-aprova a missão.
            try:
                result = await self.process_intent(task)
            except Exception as e:
                logger.warning(f"AviarySwarmBridge: Architect falhou - {e}")
                return {"ok": False, "error": f"Falha no planejamento: {e}"}
            output = result.get("output", "")
            ok = not output.startswith("[ERRO]")
            return {"ok": ok, "output": output, "agent_id": agent_id, "mission": result.get("mission")}

        if agent_id == "agent-synthesizer":
            # Code Synthesizer: geração de código -> ponte direta de
            # inferência de texto, travada na role "code" do
            # catalog/models.json (default: qwen2.5-coder:32b, "ainda não
            # baixada por padrão" - se o .gguf não estiver no disco,
            # LlamaCppDriver.start() falha e isso vira erro real aqui
            # embaixo, não código inventado).
            if self.runtime is None:
                return {"ok": False, "error": "RuntimeEngine não disponível (não injetado no ResidentManager)."}

            resolved = self.registry.resolve("code")
            if resolved is None:
                return {"ok": False, "error": "Nenhum modelo cobre a role 'code' em catalog/models.json."}

            await self._thermal_guard("Antes de sintetizar código (Aviary Swarm)")
            await self._vram_guard(
                "Antes de sintetizar código (Aviary Swarm)", resolved.runtime, resolved.id, resolved.vram_mb_estimate,
            )

            plan = ExecutionPlan(
                runtime=resolved.runtime,
                model=resolved.id,
                parameters={
                    "prompt": task,
                    "system_prompt": "Você é um engenheiro de software sênior. Gere código correto e direto "
                                      "para a tarefa pedida, com comentários mínimos.",
                },
                reasoning=f"Aviary Swarm (Code Synthesizer): {task}",
            )
            self.logs.add_event("INFO", "AviarySwarmBridge", f"Code Synthesizer despachado com '{resolved.id}': \"{task}\"")
            result = await self.runtime.execute(plan)
            if result.status != ExecutionStatus.SUCCESS:
                self.logs.add_event("ERROR", "AviarySwarmBridge", f"Falha no Code Synthesizer: {result.errors}")
                return {
                    "ok": False,
                    "error": "; ".join(result.errors) if result.errors else "Falha desconhecida na inferência de código.",
                }
            self._track_model_loaded(resolved.runtime, resolved.id)
            return {
                "ok": True, "output": result.output, "model": resolved.id,
                "metrics": result.metrics or {}, "agent_id": agent_id,
            }

        if agent_id == "agent-rag":
            # Vector Navigator: busca vetorial -> query_knowledge() real
            # (o mesmo backend RAG que analyze_machine() já consulta),
            # síncrono, sem LLM envolvido.
            try:
                hits = self.planner.knowledge.query_knowledge(task)
            except Exception as e:
                logger.warning(f"AviarySwarmBridge: Navigator falhou - {e}")
                return {"ok": False, "error": f"Falha na consulta RAG: {e}"}
            if hits:
                output = "Resultados encontrados na base RAG:\n" + "\n".join(f"- {h}" for h in hits)
            else:
                output = "Nenhum resultado encontrado na base RAG para essa consulta."
            return {"ok": True, "output": output, "hits": hits, "agent_id": agent_id}

        return {
            "ok": False,
            "error": f"Agente desconhecido: '{agent_id}'. Agentes válidos: agent-sentinel, agent-architect, "
                     f"agent-synthesizer, agent-rag.",
        }

    # ============================================================
    # MÉTODOS DA INTERFACE (Stubs para satisfazer o contrato)
    # ============================================================

    async def get_status(self) -> dict:
        return {"status": "ONLINE", "active_mission": self._active_mission is not None}

    async def execute_plan(self, plan: dict) -> dict:
        # PHX-FIX (auditoria 2026-08-09): este método sempre devolveu
        # {"output": "Execução delegada para o Mission Kernel."} sem
        # delegar nada de verdade - é o mesmo padrão do bug de "fake
        # success" já corrigido antes no MissionExecutor, só que aqui.
        # Nada no projeto chama execute_plan() hoje (só existe pra
        # satisfazer IResidentManager), então em vez de inventar uma
        # implementação não testada que constrói um Mission() a partir de
        # um dict solto - risco real de bug silencioso pior que o stub -
        # ele agora falha de forma explícita. O fluxo real e testado pra
        # rodar uma missão continua sendo process_intent() (cria e registra
        # a missão) seguido de approve_and_execute() (aprova e dispara a
        # execução em background), exatamente como o ApiEngine já usa.
        raise NotImplementedError(
            "execute_plan() não está implementado. Use process_intent(intent) "
            "para criar e registrar uma missão, depois approve_and_execute() "
            "para aprová-la e executá-la - esse é o fluxo real e testado."
        )


def _is_image_model_target(target: str) -> bool:
    """Heurística simples: o alvo do DOWNLOAD_MODEL parece ser um modelo
    de imagem (flux/sd15/sdxl)? Usado só pra decidir se vale a pena checar
    a pasta 'Image' antes de baixar de novo."""
    if not target:
        return False
    t = target.lower()
    return any(kw in t for arch_kws in _IMAGE_ARCH_PATTERNS.values() for kw in arch_kws)
