# phoenix_kernel/documents/audiobook.py
#
# PHX-NEW (pedido do usuário 2026-08-23): quebra o texto extraído de um
# documento (via documents/engine.py) em blocos sintetizáveis, detecta o
# idioma de CADA bloco (pra documentos que misturam português/inglês/outra
# língua no mesmo arquivo, ex: um relatório técnico com trechos citados em
# inglês) e concatena os áudios gerados por runtime/drivers/kokoro_tts.py
# num único arquivo final.
#
# PHX-NEW (2026-08-23, pedido do usuário: "que o áudio fale bem o português
# e outras línguas qdo houver textos em línguas misturadas... ótima
# prosódia"): a quebra em blocos era só por PARÁGRAFO - um parágrafo que
# mistura duas línguas em frases diferentes (comum: um parágrafo em
# português citando uma frase inteira em inglês no meio) ficava inteiro
# num bloco só, e só um idioma era detectado pra ele. Agora a quebra
# acontece por FRASE dentro do parágrafo: um bloco novo começa sempre que
# o idioma da próxima frase muda de verdade (detecção confiável) OU o
# bloco atual estouraria max_chars - o que vier primeiro. Isso é uma
# melhoria real, não mágica: o Kokoro continua sendo várias vozes
# monolíngues (uma por idioma), não um motor multilíngue único como o
# ElevenLabs que troca de idioma no meio da MESMA frase - uma palavra ou
# termo técnico isolado em outro idioma dentro de uma frase ainda sai com
# o sotaque da frase inteira (mesma limitação que já existia pra títulos
# curtos, ver resolve_chunk_language). O que melhora aqui é o caso de
# FRASES INTEIRAS em idiomas diferentes dentro do mesmo parágrafo.
#
# Este módulo é PURO (funções sem I/O de rede/GPU) de propósito - só texto
# entra, texto/decisões saem. Isso é o que permite testar a lógica de
# quebra em blocos e escolha de idioma com um teste extraído do código
# real, sem precisar do modelo Kokoro carregado (~300MB) rodando.

from __future__ import annotations

import re

# PHX-NEW: teto de caracteres por bloco antes de mandar pro Kokoro. Não é
# o limite de fonemas do modelo (isso o kokoro-onnx já resolve sozinho,
# internamente) - é o tamanho de bloco usado pra DUAS coisas: (1) progresso
# granular o suficiente pra a UI mostrar "bloco 47 de 312" em vez de travar
# minutos num "bloco 1 de 3"; (2) a detecção de idioma (py3langid) funciona
# melhor em blocos de tamanho "frase/parágrafo" do que em documentos
# inteiros de uma vez (um documento inteiro quase sempre detecta como um
# idioma só, mesmo tendo trechos citados em outro idioma no meio).
MAX_CHARS_PER_CHUNK = 600


def split_into_chunks(markdown_text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> list[str]:
    """Quebra o texto (Markdown extraído de PDF/DOCX/PPTX, ou texto puro de
    TXT/MD) em blocos sintetizáveis, respeitando limites de parágrafo e,
    DENTRO de cada parágrafo, limites de frase E de idioma (nunca corta uma
    frase ao meio, o que soaria muito mal na síntese, e nunca mistura duas
    frases de idiomas diferentes confiavelmente detectados no mesmo bloco).

    Nunca devolve blocos vazios (parágrafos em branco, marcadores de
    imagem `![...]`, e separadores `---`/`===` de Markdown são
    descartados, já que não fazem sentido lidos em voz alta)."""
    if not markdown_text or not markdown_text.strip():
        return []

    raw_paragraphs = re.split(r"\n\s*\n", markdown_text)

    chunks: list[str] = []
    for para in raw_paragraphs:
        cleaned = _clean_paragraph_for_speech(para)
        if not cleaned:
            continue
        chunks.extend(_split_paragraph_by_language_and_size(cleaned, max_chars))

    return chunks


def _split_paragraph_by_language_and_size(paragraph: str, max_chars: int) -> list[str]:
    """Quebra UM parágrafo (já limpo) em um ou mais blocos por frase,
    abrindo um bloco novo sempre que (a) o idioma da frase muda de verdade
    (detecção confiável - frases curtas demais pra detectar não forçam
    quebra, só herdam o idioma do bloco atual) OU (b) o bloco atual
    estouraria `max_chars` com a próxima frase somada - o que vier
    primeiro. Um parágrafo curto e monolíngue continua virando um bloco
    só, exatamente como antes."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", paragraph) if s.strip()]
    if not sentences:
        return []

    groups: list[str] = []
    current: list[str] = []
    current_lang: str | None = None

    for sentence in sentences:
        lang = detect_language(sentence)
        current_text = " ".join(current)
        joined_len = len(current_text) + (1 if current else 0) + len(sentence)

        language_changed = bool(current) and lang is not None and current_lang is not None and lang != current_lang
        too_big = bool(current) and joined_len > max_chars

        if language_changed or too_big:
            groups.append(current_text)
            current = []
            current_lang = None

        current.append(sentence)
        if lang is not None:
            current_lang = lang

    if current:
        groups.append(" ".join(current))

    return groups


def _clean_paragraph_for_speech(paragraph: str) -> str:
    """Remove marcações Markdown que não fazem sentido faladas em voz alta:
    cabeçalhos (mantém o texto, tira os `#`), imagens (removidas por
    inteiro - não dá pra "ler" uma imagem), links (mantém só o texto
    visível), tabelas em pipe (`| a | b |` viraria um ruído de barras
    verticais lido literalmente por alguns back-ends de fonemização) e
    separadores horizontais (`---`, `===`, `***`)."""
    text = paragraph.strip()
    if not text:
        return ""

    # Separador horizontal puro (nada além de -, =, * e espaços)
    if re.fullmatch(r"[-=*_\s]+", text):
        return ""

    # Imagem Markdown sozinha na linha: ![alt](url)
    if re.fullmatch(r"!\[[^\]]*\]\([^)]*\)\s*", text):
        return ""

    text = re.sub(r"^#{1,6}\s*", "", text)  # cabeçalhos
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)  # imagens inline
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # links -> só o texto
    text = re.sub(r"[*_`]{1,3}", "", text)  # ênfase/código inline
    text = re.sub(r"\s{2,}", " ", text).strip()

    # Linha de tabela Markdown (começa E termina com |, ou é só
    # traços/pipes de separador de cabeçalho de tabela) - lida em voz alta
    # não comunica nada útil; pular é melhor que ler "barra a barra b barra".
    if text.startswith("|") and text.endswith("|"):
        return ""
    if re.fullmatch(r"[\s|:-]+", text):
        return ""

    return text


def detect_language(text: str) -> str:
    """Detecta o idioma (código ISO 639-1, ex: 'pt', 'en', 'es') de um
    bloco de texto usando py3langid - 100% offline, sem chamada de rede,
    roda em milissegundos. Textos muito curtos (menos de ~15 caracteres,
    ex: um número de seção sozinho tipo "3.2") têm detecção pouco confiável;
    nesses casos, devolve None e quem chamar decide o fallback (ver
    resolve_chunk_language abaixo)."""
    if not text or len(text.strip()) < 15:
        return None

    import py3langid as langid

    lang, _confidence = langid.classify(text)
    return lang


def resolve_chunk_language(text: str, previous_language: str, default_language: str) -> str:
    """Decide o idioma de UM bloco pra fins de escolha de voz. Regra:
    detecta o idioma do próprio bloco; se a detecção for pouco confiável
    (texto curto demais), REPETE o idioma do bloco anterior em vez de cair
    pro default - um título de seção curto ("Conclusão") no meio de um
    capítulo em inglês não deve, sozinho, trocar a voz pra português só
    porque "Conclusão" é uma palavra portuguesa isolada.

    `previous_language` é None no primeiro bloco do documento - nesse caso
    usa `default_language` (idioma predominante do documento, resolvido
    antes de começar a percorrer os blocos - ver detect_document_language)."""
    detected = detect_language(text)
    if detected is not None:
        return detected
    return previous_language or default_language


def detect_document_language(chunks: list[str], sample_size: int = 5, default: str = "pt") -> str:
    """Detecta o idioma PREDOMINANTE do documento amostrando os primeiros
    `sample_size` blocos "substanciais" (mais de 40 caracteres, pra não
    amostrar títulos curtos) - usado como idioma-base do documento
    (primeiro bloco, e fallback de blocos curtos demais pra detectar
    sozinhos). Nunca lança erro - documento sem texto suficiente pra
    amostrar cai no `default`."""
    substantial = [c for c in chunks if len(c) > 40][:sample_size]
    if not substantial:
        return default

    import py3langid as langid

    votes: dict[str, int] = {}
    for chunk in substantial:
        lang, _ = langid.classify(chunk)
        votes[lang] = votes.get(lang, 0) + 1

    return max(votes, key=votes.get)
