"""
Testes de regressão pra auditoria 2026-08-20, "áudio no ChatView/Aviary"
(frente aberta a pedido do usuário depois da Rodada 18, investigada por um
agente com Playwright real - não só leitura de código).

Dois achados reais:

1. `platform_source/src/components/aviary/ChatView.tsx` roteia áudio
   (.mp3/.wav/.m4a/.ogg/.flac/.aac/.webm) pro /api/transcribe desde uma
   correção anterior ("Aviary Chat audio routing"), mas o atributo `accept`
   do <input type="file"> nunca tinha sido atualizado - o diálogo NATIVO de
   seleção de arquivo do navegador filtra por padrão só pros tipos listados
   em `accept`, então um usuário clicando no clipe de anexo não via os
   arquivos de áudio no seletor (só apareceria manualmente trocando pra
   "Todos os arquivos"). Um teste com Playwright usando
   `page.setInputFiles()` mascarava esse gap porque essa API contorna o
   filtro do SO inteiramente - só apareceu dirigindo a UI de verdade e
   inspecionando o próprio atributo.
2. O frontend (ChatView.tsx/AviaryApp.tsx, mesma regex nos dois arquivos)
   aceita ".aac" como áudio, mas `api_server.py::_ALLOWED_AUDIO_EXTS` não
   incluía ".aac" - um .aac passava pelo roteamento do frontend, chegava em
   /api/transcribe, e tomava 422 "Extensão não suportada" do backend, apesar
   do WhisperDriver não ter nenhuma restrição própria de formato (converte
   qualquer coisa não-.wav via ffmpeg, sem checar extensão).

Uma auditoria externa posterior (leitura de código, sem execução) achou mais
dois problemas reais na mesma área:

3. `platform_source/src/components/ProcessLauncherBar.tsx` (botão de ação
   rápida "Transcrever Áudio", um caminho INDEPENDENTE de anexar áudio no
   chat) tinha seu próprio `accept=".wav,.mp3,.ogg,.m4a,.flac,.webm"` -
   também sem ".aac", divergindo da lista de ChatView.tsx/AviaryApp.tsx.
4. `AviaryApp.tsx`: ao anexar áudio no chat, a ÚNICA instrução do usuário
   que sobrevivia era o keyword `resum*/summar*` - qualquer outra coisa
   digitada junto ("traduza pro inglês", "responda a pergunta feita no
   áudio") era descartada silenciosamente, e o pedido de resumo em si era
   um texto HARDCODED ("Resuma o áudio transcrito acima em português."),
   nunca a instrução real do usuário. Generalizado: agora qualquer texto
   digitado junto do áudio é reenviado de verdade pro provedor.

Esta bateria não tenta rodar um browser de verdade (isso já foi feito uma
vez pelo agente de investigação) - garante que as listas de extensão
(regex do frontend, "accept" dos dois inputs de áudio, allowlist do
backend) nunca voltam a divergir silenciosamente, e que o texto do usuário
não é mais descartado no fluxo de áudio, lendo o código-fonte real de cada
lugar.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CHATVIEW = _PROJECT_ROOT / "platform_source" / "src" / "components" / "aviary" / "ChatView.tsx"
_AVIARYAPP = _PROJECT_ROOT / "platform_source" / "src" / "components" / "aviary" / "AviaryApp.tsx"
_PROCESS_LAUNCHER_BAR = _PROJECT_ROOT / "platform_source" / "src" / "components" / "ProcessLauncherBar.tsx"
_API_SERVER = _PROJECT_ROOT / "api_server.py"

_AUDIO_REGEX_RE = re.compile(r"isAudio\s*=\s*/\\\.\(([a-z0-9|]+)\)\$/i", re.IGNORECASE)
# AviaryApp.tsx tem mais de uma regex de extensão (documento, imagem,
# áudio) - ancora especificamente na variável "audioFile" pra não pegar a
# regex errada (ex: a de documento, que aparece antes no arquivo).
_AUDIO_REGEX_AVIARY_RE = re.compile(r"audioFile\s*=.*?/\\\.\(([a-z0-9|]+)\)\$/i", re.IGNORECASE)
_ACCEPT_ATTR_RE = re.compile(r'accept="([^"]+)"')
_BACKEND_EXTS_RE = re.compile(r'_ALLOWED_AUDIO_EXTS\s*=\s*\{([^}]+)\}')


def _frontend_audio_extensions_chatview() -> set[str]:
    src = _CHATVIEW.read_text(encoding="utf-8")
    m = _AUDIO_REGEX_RE.search(src)
    assert m, "não achei a regex isAudio em ChatView.tsx - o padrão do código mudou?"
    return {ext.lower() for ext in m.group(1).split("|")}


def _aviaryapp_audio_extensions() -> set[str]:
    src = _AVIARYAPP.read_text(encoding="utf-8")
    m = _AUDIO_REGEX_AVIARY_RE.search(src)
    assert m, "não achei a regex de extensão de áudio em AviaryApp.tsx - o padrão do código mudou?"
    return {ext.lower() for ext in m.group(1).split("|")}


def _chatview_accept_attribute() -> str:
    src = _CHATVIEW.read_text(encoding="utf-8")
    m = _ACCEPT_ATTR_RE.search(src)
    assert m, "não achei o atributo accept= no <input type='file'> de ChatView.tsx"
    return m.group(1)


def _backend_allowed_audio_extensions() -> set[str]:
    src = _API_SERVER.read_text(encoding="utf-8")
    m = _BACKEND_EXTS_RE.search(src)
    assert m, "não achei _ALLOWED_AUDIO_EXTS em api_server.py"
    return {ext.strip().strip('"').strip("'").lower() for ext in m.group(1).split(",") if ext.strip()}


def test_chatview_and_aviaryapp_use_the_same_audio_extension_set():
    # As duas regex (ChatView.tsx guarda o File bruto; AviaryApp.tsx decide
    # se monta multipart pro /api/transcribe) precisam concordar - se
    # divergirem, um arquivo passa por um lado e não pelo outro.
    assert _frontend_audio_extensions_chatview() == _aviaryapp_audio_extensions()


def test_file_input_accept_attribute_includes_every_audio_extension_the_js_handles():
    # Regressão do achado #1: toda extensão que o handler JS trata como
    # áudio precisa também aparecer no atributo accept do <input>, senão o
    # diálogo nativo do navegador esconde esses arquivos do usuário.
    audio_exts = _frontend_audio_extensions_chatview()
    accept_attr = _chatview_accept_attribute().lower()

    missing = {ext for ext in audio_exts if f".{ext}" not in accept_attr}
    assert not missing, (
        f"extensões de áudio tratadas pelo JS mas ausentes do accept= do <input>: {missing} "
        f"(accept atual: {accept_attr!r})"
    )


def test_backend_allows_every_audio_extension_the_frontend_routes_to_transcribe():
    # Regressão do achado #2: toda extensão que o frontend roteia pro
    # /api/transcribe precisa ser aceita pelo backend, senão o usuário
    # recebe 422 depois de já ter passado pelo fluxo de upload inteiro.
    frontend_exts = _frontend_audio_extensions_chatview()
    backend_exts = _backend_allowed_audio_extensions()

    missing = {f".{ext}" for ext in frontend_exts} - backend_exts
    assert not missing, (
        f"extensões que o frontend roteia pro /api/transcribe mas o backend rejeita: {missing} "
        f"(backend aceita: {sorted(backend_exts)})"
    )


def test_aac_specifically_is_allowed_end_to_end():
    # O achado #2 nomeado especificamente - .aac era o caso concreto que
    # falhava (frontend aceitava, backend rejeitava com 422).
    assert "aac" in _frontend_audio_extensions_chatview()
    assert ".aac" in _backend_allowed_audio_extensions()


def test_process_launcher_bar_no_longer_has_its_own_duplicate_audio_input():
    # PHX-FIX (auditoria completa 2026-08-28): o achado #3 original (o botão
    # de ação rápida "Transcrever Áudio" tinha seu PRÓPRIO accept=, uma
    # segunda lista de extensões pra manter em sincronia manual com
    # ChatView.tsx/AviaryApp.tsx) não existe mais - o botão inteiro
    # (`handleAudioFileSelected`, `audioInputRef`, `isTranscribing` e o
    # `<input type="file">` oculto que só serviam a ele) foi removido de
    # propósito nesta mesma sessão de trabalho, exatamente por ser uma fonte
    # de bug se alguém esquecesse de atualizar as duas listas juntas (ver
    # comentário no próprio ProcessLauncherBar.tsx). O caminho ÚNICO de
    # upload de áudio agora é o anexo no chat (ChatView.tsx), já coberto
    # pelos testes acima. Este teste passa a confirmar a ausência do input
    # duplicado, não a sincronia de um accept= que não existe mais - se
    # algum dia reaparecer um <input type="file"> com accept= aqui, é sinal
    # de que a duplicação voltou e precisa ser reavaliada.
    src = _PROCESS_LAUNCHER_BAR.read_text(encoding="utf-8")
    # "audioInputRef" ainda aparece no comentário que documenta a remoção
    # (histórico, não código) - checa a DECLARAÇÃO/uso real, não a
    # substring crua, senão o próprio comentário explicativo faria o teste
    # falhar pra sempre.
    assert not re.search(r"\baudioInputRef\s*=\s*useRef", src), (
        "ProcessLauncherBar.tsx voltou a declarar seu próprio audioInputRef - a duplicação de "
        "upload de áudio (e o risco de accept= divergente) que foi removida de propósito voltou"
    )
    assert "ref={audioInputRef}" not in src
    assert not _ACCEPT_ATTR_RE.search(src), (
        "ProcessLauncherBar.tsx voltou a ter um <input accept=...> próprio - "
        "verifique se não é uma reintrodução do upload de áudio duplicado"
    )


def test_aviaryapp_no_longer_discards_user_text_after_audio_transcription():
    # Regressão do achado #4 (auditoria externa, leitura de código): a
    # instrução real do usuário ("traduza pro inglês", "responda X") não
    # pode mais ser substituída por um pedido de resumo hardcoded em
    # português - o texto que segue a transcrição pro provedor de texto
    # precisa ser o `text` de verdade que o usuário digitou.
    src = _AVIARYAPP.read_text(encoding="utf-8")
    assert "Resuma o áudio transcrito acima em português." not in src, (
        "AviaryApp.tsx ainda manda um pedido de resumo hardcoded em vez da "
        "instrução real do usuário depois de transcrever áudio"
    )

    # A checagem de "o usuário digitou alguma instrução junto do áudio"
    # precisa existir (não importa o nome exato da variável) e não pode
    # mais estar restrita a um keyword de resumo/summarize.
    assert "audioFile" in src
    audio_block_start = src.index("if (audioFile && rawFiles?.has(audioFile.id))")
    # PHX-FIX (auditoria completa 2026-08-28): janela era 4000 chars - a
    # extração de instrução ganhou mais lógica (TRANSCRIPTION_TRIGGER_WORDS/
    # TRANSCRIPTION_FILLER_WORDS/isBareTranscriptionRequest) desde que este
    # teste foi escrito, e o `content: text,` real (a asserção abaixo) ficou
    # a ~6400 chars do início do bloco - fora da janela antiga, causando
    # falso-negativo (o código está correto, só a janela ficou curta demais).
    # 12000 dá margem confortável pro bloco crescer mais sem quebrar de novo.
    audio_block = src[audio_block_start:audio_block_start + 12000]
    assert re.search(r"\bresum\\w\*\|summar\\w\*\b", audio_block) is None, (
        "o bloco de tratamento de áudio ainda restringe a instrução do "
        "usuário a um keyword resum*/summar* - deveria aceitar qualquer texto"
    )
    assert "content: text," in audio_block, (
        "o bloco de tratamento de áudio precisa reenviar o `text` real do "
        "usuário pro provedor, não um texto hardcoded"
    )
