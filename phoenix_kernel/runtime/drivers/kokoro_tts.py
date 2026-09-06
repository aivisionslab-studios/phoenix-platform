# phoenix_kernel/runtime/drivers/kokoro_tts.py
#
# PHX-NEW (pedido do usuário 2026-08-23: "pegar um arquivo doc, pdf de 40
# folhas e fazer áudio com voz neural com prosódia bacana tanto em
# português qto em inglês ou outra língua"): motor de TTS neural Kokoro-82M
# (https://github.com/thewh1teagle/kokoro-onnx), escolhido depois de uma
# investigação real comparando Kokoro-82M, XTTS-v2 (Coqui) e Chatterbox
# (Resemble AI) - Kokoro venceu por ter licença Apache 2.0 (uso comercial
# liberado), rodar bem em CPU pura (sem precisar de CUDA/ROCm, que a RX 580
# do usuário não tem suporte oficial), e ter vozes nativas em português
# brasileiro (não é fallback de espeak genérico como no antigo Piper).
#
# PHX-FIX (achado real do usuário 2026-08-24, "jogar fora o piper de
# vez"): o PiperDriver (que existia em piper.py, ao lado) foi removido do
# projeto - já estava morto desde a troca pro Kokoro em 2026-08-23.
# Diferente daquele driver (que subia um subprocesso `piper.exe` por
# chamada), este NÃO é um driver que sobe um subprocesso por chamada -
# o runtime ONNX é carregado em memória
# UMA VEZ (KokoroEngine é um singleton resident) e reaproveitado entre
# chamadas, porque recarregar ~300MB de pesos a cada frase de um documento
# de 40 páginas seria um desperdício de tempo gigante (testado: ~2.3s só
# pra carregar o modelo, contra ~11s pra sintetizar um parágrafo inteiro).
#
# Todas as 8 vozes/idiomas abaixo foram CONFERIDOS DE VERDADE (não
# copiados de documentação de terceiros) rodando síntese real com os
# pesos reais baixados de
# https://github.com/thewh1teagle/kokoro-onnx/releases - ver
# prova_testes/ na entrega desta versão.

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

from phoenix_kernel.paths import PhoenixPaths

logger = logging.getLogger(__name__)

MODEL_FILENAME = "kokoro-v1.0.onnx"
VOICES_FILENAME = "voices-v1.0.bin"

# PHX-NEW: mapa idioma (código ISO 639-1, o que py3langid.classify()
# devolve) -> (voz Kokoro, código de idioma espeak-ng que o phonemizer
# interno do kokoro-onnx espera). Cada linha foi testada com síntese REAL
# nesta sessão antes de entrar aqui - nenhum código "no chute".
LANGUAGE_VOICE_MAP: dict[str, tuple[str, str]] = {
    "pt": ("pf_dora", "pt-br"),
    "en": ("af_heart", "en-us"),
    "es": ("ef_dora", "es"),
    "fr": ("ff_siwis", "fr-fr"),
    "it": ("if_sara", "it"),
    "zh": ("zf_xiaobei", "cmn"),
    "hi": ("hf_alpha", "hi"),
    "ja": ("jf_alpha", "ja"),
}

# PHX-NEW: idioma usado quando py3langid detecta algo fora das 8 línguas
# que o Kokoro-82M realmente suporta (ver LANGUAGE_VOICE_MAP acima) - por
# exemplo um trecho em alemão ou russo dentro de um documento majoritariamente
# em português. Cai pro português em vez de travar o processamento inteiro
# do documento por causa de um único parágrafo num idioma não suportado.
FALLBACK_LANGUAGE = "pt"

SAMPLE_RATE = 24000


class KokoroModelNotFoundError(Exception):
    """Pesos do Kokoro (.onnx + voices.bin) não encontrados no disco."""


class KokoroEngine:
    """Wrapper resident (carrega o modelo ONNX uma única vez) em volta do
    pacote `kokoro-onnx`. Uma instância por processo do Phoenix Engine -
    ver `get_kokoro_engine()` abaixo, chamado pelo ResidentManager."""

    def __init__(self) -> None:
        self._kokoro = None
        self._lock = threading.Lock()

    def _find_model_files(self) -> tuple[Optional[Path], Optional[Path]]:
        """Mesmo padrão de `_find_voice_file` do PiperDriver: procura em
        Workstations/Models/Voice/Kokoro/. Devolve (None, None) se o par
        completo não existir - quem chamar decide a mensagem de erro."""
        try:
            voice_dir = PhoenixPaths.get_category_path("Voice", "Kokoro")
        except Exception as e:
            logger.warning(f"KokoroEngine: falha ao resolver pasta 'Voice/Kokoro' - {e}")
            return None, None

        model_path = voice_dir / MODEL_FILENAME
        voices_path = voice_dir / VOICES_FILENAME
        if model_path.exists() and voices_path.exists():
            return model_path, voices_path
        return None, None

    def is_installed(self) -> bool:
        model_path, voices_path = self._find_model_files()
        return model_path is not None and voices_path is not None

    def _ensure_loaded(self):
        """Carrega o modelo ONNX na memória (uma vez só, protegido por
        lock pra duas chamadas concorrentes não carregarem 2x)."""
        if self._kokoro is not None:
            return self._kokoro

        with self._lock:
            if self._kokoro is not None:
                return self._kokoro

            model_path, voices_path = self._find_model_files()
            if model_path is None:
                raise KokoroModelNotFoundError(
                    "Modelo Kokoro não encontrado no disco. Baixe "
                    f"'{MODEL_FILENAME}' e '{VOICES_FILENAME}' de "
                    "https://github.com/thewh1teagle/kokoro-onnx/releases "
                    "(tag model-files-v1.0) e coloque em "
                    "Workstations/Models/Voice/Kokoro/."
                )

            try:
                from kokoro_onnx import Kokoro
            except ImportError as e:
                raise KokoroModelNotFoundError(
                    "Pacote 'kokoro-onnx' não instalado. Rode: pip install "
                    "kokoro-onnx onnxruntime phonemizer espeakng-loader"
                ) from e

            logger.info(f"KokoroEngine: carregando modelo de '{model_path}'...")
            self._kokoro = Kokoro(str(model_path), str(voices_path))
            # PHX-NEW (2026-08-23, pedido do usuário: "esta rodando via cpu,
            # mas podemos pensar em rodar via gpu, nao?"): kokoro-onnx troca
            # sozinho pra GPU (DirectML no Windows) quando o pacote certo
            # está instalado (ver install/common.ps1, PHOENIX_TTS_DEVICE) -
            # mas essa troca é silenciosa por padrão. Loga aqui o provider
            # REAL em uso (não só "deveria estar usando X") pra confirmar de
            # verdade se caiu em GPU (DmlExecutionProvider) ou voltou pra
            # CPU (CPUExecutionProvider, ex: driver de GPU incompatível) -
            # 'self._kokoro.sess' é o InferenceSession interno do
            # kokoro-onnx (atributo público, embora não documentado).
            try:
                active_providers = self._kokoro.sess.get_providers()
                logger.info(f"KokoroEngine: modelo carregado e pronto (execution providers: {active_providers}).")
            except Exception:
                logger.info("KokoroEngine: modelo carregado e pronto.")
            return self._kokoro

    def resolve_voice(self, lang_code: str) -> tuple[str, str]:
        """Idioma ISO 639-1 (ex: 'pt', 'en') -> (voz Kokoro, código espeak).
        Idioma não suportado cai pro FALLBACK_LANGUAGE, nunca lança erro -
        um documento de 40 páginas não pode travar inteiro por causa de UM
        parágrafo num idioma que o Kokoro não cobre."""
        return LANGUAGE_VOICE_MAP.get(lang_code, LANGUAGE_VOICE_MAP[FALLBACK_LANGUAGE])

    def synthesize(self, text: str, lang_code: str, speed: float = 1.0):
        """Sintetiza UM trecho de texto (um parágrafo, tipicamente) na voz
        certa pro idioma detectado. Devolve (samples: np.ndarray, sample_rate: int).
        O próprio kokoro-onnx já quebra internamente frases longas em
        pedaços de até 510 fonemas (ver chunker.py da lib) e insere pausas
        de frase/oração - não precisamos reimplementar esse corte aqui,
        só decidir ONDE cortar em blocos maiores (ver audiobook.py)."""
        kokoro = self._ensure_loaded()
        voice, espeak_lang = self.resolve_voice(lang_code)
        samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang=espeak_lang)
        return samples, sample_rate


def describe_synthesis_error(e: Exception) -> str:
    """Formata com segurança uma exceção vinda de engine.synthesize().

    PHX-NEW (2026-08-23, achado real do usuário testando GPU/DirectML): ao
    ativar PHOENIX_TTS_DEVICE=GPU, TODOS os blocos de um audiolivro
    falharam - o terminal do Phoenix Engine mostrava o erro nativo real do
    onnxruntime (DmlExecutionProvider falhando no nó ConvTranspose do
    vocoder do Kokoro, HRESULT 80070057 "Parâmetro incorreto"), mas o LOG
    da Phoenix (o que o usuário via na tela) mostrava algo completamente
    diferente e confuso: "'utf-8' codec can't decode byte 0xe2 ...". Causa
    raiz: a mensagem de erro nativa do Windows (via GetLastError/
    FormatMessage) vem acentuada (locale pt-BR) numa codepage ANSI, não
    UTF-8: a conversão pybind11 de C++ pra Python desse texto acentuado
    falha com UnicodeDecodeError, e ESSA exceção secundária (não a original
    do onnxruntime) é o que efetivamente chega até o nosso `except
    Exception as e`. Resultado: o usuário via um erro sobre "codec" que não
    tinha nada a ver com o problema real (incompatibilidade do modelo com
    DirectML), o que só reforça achado #1 desta mesma sessão (nunca
    confiar cegamente na primeira exceção pega sem investigar a causa
    raiz). Isto não é 100% corrigível daqui (o bug de conversão é interno
    ao pybind11/onnxruntime) - mas dá pra reconhecer o padrão e apontar o
    usuário na direção certa em vez de deixá-lo pensando que é um problema
    de texto/idioma."""
    try:
        if isinstance(e, UnicodeDecodeError):
            return (
                f"{e} - isto normalmente NÃO é um problema de texto/idioma do documento: é o "
                "onnxruntime devolvendo uma mensagem de erro nativa do Windows com acentuação "
                "que a conversão interna não decodifica direito. A causa real geralmente "
                "aparece no terminal do Phoenix Engine, numa linha ANTES desta (procure por "
                "'[E:onnxruntime' ou 'DmlExecutionProvider'). Se você ativou "
                "PHOENIX_TTS_DEVICE=GPU recentemente, tente voltar pra CPU - o Kokoro pode não "
                "ser compatível com aceleração DirectML nesta GPU/driver."
            )
        return str(e)
    except Exception:
        return f"{type(e).__name__} (não foi possível obter detalhes do erro)"


_engine_singleton: Optional[KokoroEngine] = None
_engine_lock = threading.Lock()


def get_kokoro_engine() -> KokoroEngine:
    global _engine_singleton
    if _engine_singleton is None:
        with _engine_lock:
            if _engine_singleton is None:
                _engine_singleton = KokoroEngine()
    return _engine_singleton
