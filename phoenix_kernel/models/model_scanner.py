"""
ModelScanner — Varre Models/ e constrói inventário.
"""
from __future__ import annotations
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    from phoenix_kernel.paths import PhoenixPaths
except ImportError:
    PhoenixPaths = None

SUPPORTED = {
    ".gguf": "GGUF",
    ".safetensors": "Safetensors",
    ".onnx": "ONNX",
    ".mlx": "MLX",
    ".bin": "Bin",
    ".pt": "PyTorch",
    ".ckpt": "Checkpoint",
}

# PHX-FIX (2026-08-22, pedido direto do usuário: "pasta voz nem era pra
# ser catalogada na phoenix"): "Voice" guarda pacotes de voz Piper
# (pares .onnx + .onnx.json) - não são "modelos" no sentido que este
# inventário existe pra servir (LLMs de chat, checkpoints de imagem,
# modelos de Whisper). A descoberta de vozes já tem seu PRÓPRIO mecanismo
# dedicado (ResidentManager._discover_installed_voices(), que varre
# Voice/Piper diretamente) - nunca passou por aqui e nunca precisou. Antes
# desta mudança, ModelScanner ainda entrava em "Voice" só pra descartar
# tudo de lá no final (nenhum consumidor real usa `category == "Voice"`) -
# um desperdício, e pior: no Windows, nomes de arquivo de pacote de voz
# tendem a ser longos o bastante pra estourar o limite de 260 caracteres
# sem suporte a caminho longo, o que já causou um erro real ao listar essa
# pasta (contornado por outro fix nesta mesma sessão, que isola falhas por
# categoria) - a forma mais correta de resolver isso não é só "sobreviver
# ao erro", é nem tentar escanear uma pasta que nunca deveria fazer parte
# deste inventário.
EXCLUDED_CATEGORIES = {"voice"}


class ModelScanner:

    @staticmethod
    def scan_all(models_base: Path = None) -> list[dict]:
        if models_base is None:
            if PhoenixPaths:
                models_base = PhoenixPaths.get_models_base()
            else:
                models_base = Path("data/workstations/Models")
        if not models_base.exists():
            return []

        inventory = []

        # PHX-FIX (2026-08-22, segunda rodada do mesmo achado - "cai noutra
        # pasta de modelos de voz e nao de chatbot"): a primeira correção só
        # blindou o passeio DENTRO de cada subcategoria (ex: Chat/GGUF)
        # contra pasta oculta/arquivo instável. Mas os DOIS laços de fora -
        # listar as categorias (Chat, Image, Audio, Voice, ...) e listar as
        # subcategorias de cada uma - continuavam chamando `.iterdir()`/
        # `.is_dir()` sem nenhuma proteção. Voice guarda pacotes de voz
        # Piper com nomes de arquivo longos e aninhados - no Windows (sem
        # suporte a caminho longo habilitado) isso facilmente estoura o
        # limite de 260 caracteres e `.iterdir()` levanta OSError bem ali.
        # Como category="Chat" e category="Voice" são processadas no MESMO
        # laço `for cat_dir in ...`, um erro ao entrar em Voice quebrava o
        # `scan_all()` inteiro ANTES mesmo de chegar em Chat (ou depois,
        # dependendo da ordem alfabética) - escondendo os modelos de chat
        # de novo, mesmo já sem a pasta ".cache" (o usuário apagou ela por
        # conta própria depois da entrega anterior, sem efeito nenhum aqui
        # porque a causa desta vez é outra pasta, não aquela).
        #
        # Agora CADA categoria e CADA subcategoria é escaneada de forma
        # isolada - uma falha em "Voice" fica só ali (com aviso no log),
        # nunca impede "Chat" de aparecer.
        try:
            cat_dirs = sorted(models_base.iterdir())
        except OSError as e:
            logger.warning(f"ModelScanner: falha ao listar a pasta raiz de modelos '{models_base}': {e}")
            return []

        for cat_dir in cat_dirs:
            try:
                if not cat_dir.is_dir() or cat_dir.name.startswith("."):
                    continue
            except OSError as e:
                logger.warning(f"ModelScanner: pulando '{cat_dir}' (falha ao checar se é pasta: {e})")
                continue
            category = cat_dir.name
            if category.lower() in EXCLUDED_CATEGORIES:
                # PHX-FIX (achado acima): "Voice" nunca devia ter entrado
                # neste inventário - nem tenta listar o conteúdo dela.
                continue

            try:
                sub_dirs = sorted(cat_dir.iterdir())
            except OSError as e:
                logger.warning(f"ModelScanner: pulando a categoria '{category}' inteira (falha ao listar: {e}) - as outras categorias continuam sendo escaneadas normalmente")
                continue

            for sub_dir in sub_dirs:
                try:
                    if not sub_dir.is_dir() or sub_dir.name.startswith("."):
                        continue
                except OSError as e:
                    logger.warning(f"ModelScanner: pulando '{sub_dir}' (falha ao checar se é pasta: {e})")
                    continue
                subcategory = sub_dir.name
                # PHX-FIX (2026-08-22, achado real: usuário baixou modelos
                # novos pela própria Phoenix - feature desta mesma sessão -
                # e eles não apareciam em NENHUM seletor, nem o antigo
                # qwen3-8b que sempre funcionou por já estar carregado).
                # `sub_dir.rglob("*")` desce em QUALQUER subpasta, inclusive
                # ".cache" - e uma pasta ".cache/huggingface/..." dentro de
                # Models/Chat/GGUF é exatamente o que huggingface_hub cria
                # sozinho ao baixar um arquivo com `local_dir=...` (metadata,
                # locks, blobs parciais durante o download). Só os dois
                # primeiros níveis (categoria/subcategoria) eram checados
                # contra nome-começando-com-ponto - uma pasta oculta MAIS
                # FUNDA (como essa) nunca era pulada, e um arquivo de
                # metadata/lock ali dentro podia estar sendo escrito/
                # removido no exato momento do scan (corrida real com o
                # download em andamento) - `f.stat()` em `_record()` levanta
                # OSError/FileNotFoundError nesse caso, sem nenhum try/except
                # em volta, derrubando o `scan_all()` INTEIRO (não só aquele
                # arquivo) - o endpoint então caía no `except Exception`,
                # logava um aviso que ninguém via, e devolvia uma lista
                # vazia pra TODOS os modelos, escondendo até o que já
                # funcionava. Agora poda qualquer diretório oculto (nome
                # começando com ".") em qualquer profundidade, nunca só nos
                # dois primeiros níveis.
                for f in ModelScanner._walk_visible_files(sub_dir):
                    if f.suffix.lower() not in SUPPORTED:
                        continue
                    try:
                        inventory.append(ModelScanner._record(f, category, subcategory))
                    except OSError as e:
                        # PHX-FIX (mesmo achado acima): mesmo already evitando
                        # pastas ocultas, um único arquivo "de vida curta"
                        # (ex: sendo escrito por outro processo, um symlink
                        # quebrado, permissão negada num arquivo específico)
                        # não pode mais derrubar o inventário inteiro - pula
                        # só esse arquivo, com um aviso, e continua os outros.
                        logger.warning(f"ModelScanner: pulando '{f}' (falha ao ler metadados: {e})")
                        continue
        return inventory

    @staticmethod
    def _walk_visible_files(root: Path):
        """Gera todo arquivo dentro de `root`, descendo em subpastas, mas
        NUNCA entrando em (nem listando o conteúdo de) uma pasta cujo nome
        comece com "." - em qualquer profundidade, não só no topo. Evita
        varrer pastas de cache/metadata (".cache", ".git", etc.) que podem
        conter arquivos temporários/instáveis no meio de um download real."""
        try:
            entries = sorted(root.iterdir())
        except OSError as e:
            logger.warning(f"ModelScanner: pulando pasta '{root}' (falha ao listar: {e})")
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                is_dir = entry.is_dir()
            except OSError:
                continue
            if is_dir:
                yield from ModelScanner._walk_visible_files(entry)
            else:
                yield entry

    @staticmethod
    def _record(f: Path, category: str, subcategory: str) -> dict:
        st = f.stat()
        return {
            "name": f.stem,
            "filename": f.name,
            "relative_path": str(f.relative_to(PhoenixPaths.get_models_base())) if PhoenixPaths else str(f),
            "category": category,
            "subcategory": subcategory,
            "format": SUPPORTED.get(f.suffix.lower(), "Unknown"),
            "size_bytes": st.st_size,
            "size_mb": round(st.st_size / (1024 * 1024), 2),
            "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "sha256_prefix": ModelScanner._hash(f),
        }

    @staticmethod
    def _hash(f: Path) -> str:
        h = hashlib.sha256()
        try:
            with open(f, "rb") as fh:
                for _ in range(8):  # Apenas primeiros 64KB para velocidade
                    chunk = fh.read(8192)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()[:16]
        except OSError:
            return "unreadable"
