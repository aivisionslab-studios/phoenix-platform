# phoenix_kernel/services/ocr_engine.py
"""OCR via Tesseract nativo — motor RÁPIDO e DETERMINÍSTICO, com confiança
real por palavra (não um "achismo").

PHX-UPDATE (2026-09-06, pedido do usuário): antes só extraía texto puro,
sem idioma configurável e sem nenhuma medida de confiança — impossível
saber se o resultado era bom sem olhar a imagem manualmente. Dois achados
reais corrigidos aqui:

1. IDIOMA AUSENTE: `extract_text()` chamava o tesseract sem `-l`, caindo no
   padrão "eng" (inglês) do binário — para documento em português (nota
   fiscal, boleto, etc.) isso reconhece mal acentos e palavras. Agora
   aceita `lang` (default "por+eng" - português E inglês juntos, comum em
   documento técnico/comercial brasileiro que mistura os dois). Se o
   pacote de idioma pedido não estiver instalado, o tesseract falha com
   erro CLARO (testado: "Failed loading language 'por'", exit code 1) -
   nunca finge que funcionou.

2. SEM CONFIANÇA: agora usa a saída `tsv` do tesseract (cada palavra
   reconhecida vem com uma confiança 0-100 na própria saída nativa - não
   é estimativa nossa, é o que o motor LSTM já calcula internamente) e
   devolve a confiança MÉDIA do documento, junto com o texto reconstruído.
   Isso é o que permite decidir automaticamente "esse resultado é bom o
   suficiente pra confiar, ou preciso de uma segunda opinião" (ver
   `resident_manager.hybrid_ocr_direct`, que usa esse número pra decidir
   se cai pro MiniCPM-V como segunda opinião).
"""
import asyncio
import logging
import os
import platform
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Idioma padrão: português + inglês juntos (documento comercial brasileiro
# comum mistura os dois - termos técnicos, marcas, siglas em inglês no meio
# de texto em português). Se "por" não estiver instalado, o tesseract falha
# de forma limpa (ver docstring acima) - hybrid_ocr_direct trata isso como
# motivo de cair pra segunda opinião, não como sucesso silencioso.
DEFAULT_OCR_LANG = "por+eng"


class OCREngine:
    def __init__(self):
        self._tesseract_path = self._find_tesseract()
        if not self._tesseract_path:
            logger.warning("OCREngine: Tesseract não encontrado. Instale com 'sudo apt install tesseract-ocr' (Linux) ou 'winget install tesseract' (Windows).")
        else:
            logger.info(f"OCREngine: Tesseract encontrado em {self._tesseract_path}")

    def _find_tesseract(self) -> str | None:
        """Encontra o executável do Tesseract no PATH ou em caminhos padrão do Windows."""
        tesseract_cmd = shutil.which("tesseract")
        if tesseract_cmd:
            return tesseract_cmd

        if platform.system() == "Windows":
            common_paths = [
                r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
            ]
            for path in common_paths:
                if os.path.exists(path):
                    return path

        return None

    @staticmethod
    def _parse_tsv(tsv_output: str) -> tuple[str, float | None]:
        """Reconstrói o texto e calcula a confiança média a partir da saída
        `tsv` do tesseract. Só as linhas de nível 5 (palavra individual) têm
        confiança real - níveis 1-4 (página/bloco/parágrafo/linha) vêm com
        conf=-1 (não aplicável nesse nível) e são ignoradas aqui."""
        linhas = tsv_output.strip().split("\n")
        if len(linhas) < 2:
            return "", None
        palavras: list[str] = []
        confiancas: list[float] = []
        for linha in linhas[1:]:  # pula o cabeçalho
            campos = linha.split("\t")
            if len(campos) < 12:
                continue
            nivel = campos[0]
            texto = campos[11]
            if nivel != "5" or not texto.strip():
                continue
            palavras.append(texto)
            try:
                conf = float(campos[10])
                if conf >= 0:
                    confiancas.append(conf)
            except ValueError:
                pass
        texto_completo = " ".join(palavras)
        confianca_media = sum(confiancas) / len(confiancas) if confiancas else None
        return texto_completo, confianca_media

    async def extract_text(self, image_path: str, lang: str = DEFAULT_OCR_LANG) -> str:
        """Extrai texto de uma imagem usando o binário tesseract nativo.
        Mantido por compatibilidade (só o texto, sem confiança) - ver
        `extract_text_with_confidence` para o resultado completo."""
        result = await self.extract_text_with_confidence(image_path, lang=lang)
        if not result["ok"]:
            return f"[Erro: {result['error']}]"
        return result["text"]

    async def extract_text_with_confidence(
        self, image_path: str, lang: str = DEFAULT_OCR_LANG,
    ) -> dict:
        """Extrai texto E confiança média (0-100, direto do motor LSTM do
        tesseract - não é estimativa nossa). Devolve:
            {"ok": bool, "text": str, "confidence": float|None, "error": str|None}
        `confidence=None` só acontece se o tesseract rodou (exit 0) mas não
        reconheceu nenhuma palavra (imagem em branco, por exemplo) - nesse
        caso `ok=True` e `text=""`, mas sem confiança pra reportar."""
        if not self._tesseract_path:
            return {"ok": False, "text": "", "confidence": None, "error": "Tesseract não instalado no servidor"}

        if not Path(image_path).exists():
            return {"ok": False, "text": "", "confidence": None, "error": "Arquivo de imagem não encontrado"}

        try:
            process = await asyncio.create_subprocess_exec(
                self._tesseract_path, str(image_path), "stdout", "-l", lang, "tsv",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30.0)

            if process.returncode != 0:
                err = stderr.decode("utf-8", errors="replace").strip()
                logger.error(f"OCREngine: Falha no Tesseract - {err}")
                return {"ok": False, "text": "", "confidence": None, "error": err or "Falha desconhecida no Tesseract"}

            tsv_output = stdout.decode("utf-8", errors="replace")
            texto, confianca = self._parse_tsv(tsv_output)
            logger.info(f"OCR concluído para {image_path}. {len(texto)} caracteres, confiança média {confianca}.")
            return {"ok": True, "text": texto, "confidence": confianca, "error": None}

        except asyncio.TimeoutError:
            logger.error("OCREngine: Timeout ao processar imagem.")
            return {"ok": False, "text": "", "confidence": None, "error": "Timeout no OCR"}
        except Exception as e:
            logger.error(f"OCREngine: Erro inesperado - {e}")
            return {"ok": False, "text": "", "confidence": None, "error": str(e)}
