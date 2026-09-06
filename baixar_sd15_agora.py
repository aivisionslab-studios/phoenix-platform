#!/usr/bin/env python3
"""
baixar_sd15_agora.py
=====================
Baixa o checkpoint REAL do Stable Diffusion 1.5 (v1-5-pruned-emaonly,
~4.27GB) direto pra pasta de Imagem do Phoenix, com o nome de arquivo já
"blindado" pra ser reconhecido corretamente pelo Phoenix (ver LEIA-ME.txt).

Isso é um atalho pra quem quer o arquivo em disco AGORA, sem esperar uma
missão de "Criar Imagens" pela UI. É o MESMO arquivo/URL que
catalog/assets/sd15.json (desta entrega) já registra - rodar este script OU
rodar uma missão pela UI dão o mesmo resultado; use o que for mais rápido
pra você.

Uso (rode a partir da raiz do projeto Phoenix, onde fica api_server.py):
    python baixar_sd15_agora.py

Se preferir baixar manualmente (ex: navegador, gerenciador de download):
    URL:      https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors?download=true
    Salvar em: <seu workspace Phoenix>\\Models\\Image\\sd15-v1-5-pruned-emaonly.safetensors
    (o nome do arquivo IMPORTA - ver LEIA-ME.txt)
"""
import sys
import urllib.request
from pathlib import Path

URL = "https://huggingface.co/stable-diffusion-v1-5/stable-diffusion-v1-5/resolve/main/v1-5-pruned-emaonly.safetensors?download=true"
EXPECTED_SIZE_BYTES = 4_265_146_304  # confirmado via API do HuggingFace (não é chute)
FILENAME = "sd15-v1-5-pruned-emaonly.safetensors"


def _find_image_dir() -> Path:
    """Mesma resolução que PhoenixPaths.get_category_path('Image') faz -
    replicada aqui em miniatura pra este script rodar sozinho, sem precisar
    importar o projeto inteiro (evita risco de importar algo que dependa de
    um boot completo do Kernel só pra achar uma pasta)."""
    try:
        sys.path.insert(0, ".")
        from phoenix_kernel.paths import PhoenixPaths
        return PhoenixPaths.get_category_path("Image")
    except Exception:
        # Fallback: pergunta pro usuário se não conseguir importar o projeto
        # (ex: rodando este script fora da raiz do Phoenix).
        print("Não consegui importar phoenix_kernel.paths (rode este script a partir da raiz do projeto Phoenix).")
        manual = input("Cole o caminho completo da sua pasta Models\\Image: ").strip()
        return Path(manual)


def main() -> int:
    image_dir = _find_image_dir()
    image_dir.mkdir(parents=True, exist_ok=True)
    dest = image_dir / FILENAME
    tmp = dest.with_suffix(dest.suffix + ".part")

    if dest.exists() and dest.stat().st_size >= 3_500_000_000:
        print(f"Já existe e parece válido: {dest} ({dest.stat().st_size / 1e9:.2f} GB). Nada a fazer.")
        return 0

    print(f"Baixando SD1.5 (~4.27GB) de:\n  {URL}\npara:\n  {dest}\n")
    print("Isso pode levar alguns minutos dependendo da sua conexão...")

    def _progress(block_num, block_size, total_size):
        downloaded = block_num * block_size
        pct = min(100, downloaded * 100 // total_size) if total_size > 0 else 0
        print(f"\r  {pct}% ({downloaded / 1e9:.2f} GB / {total_size / 1e9:.2f} GB)", end="", flush=True)

    try:
        urllib.request.urlretrieve(URL, tmp, reporthook=_progress)
        print()
    except Exception as e:
        print(f"\nFalha no download: {e}")
        if tmp.exists():
            tmp.unlink()
        return 1

    size = tmp.stat().st_size
    if size < 3_500_000_000:
        print(f"Download terminou mas o arquivo ficou pequeno demais ({size} bytes) - descartando (provavelmente truncado).")
        tmp.unlink()
        return 1

    tmp.rename(dest)
    print(f"\nPronto: {dest} ({size / 1e9:.2f} GB).")
    print("Selecione 'SD 1.5' no seletor de imagem do chat - já deve funcionar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
