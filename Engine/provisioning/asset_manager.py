import json
import os
import re
import logging
from pathlib import Path
from .download_providers import ProviderFactory

_WINDOWS_ABS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")

try:
    from phoenix_kernel.paths import PhoenixPaths
except Exception:  # pragma: no cover - só falha se rodado fora do projeto
    PhoenixPaths = None

logger = logging.getLogger(__name__)

class AssetManager:
    def __init__(self, catalog_path: str = None):
        # PHX-FIX (auditoria completa): "catalog/assets" relativo dependia
        # do diretório de trabalho no momento em que o processo sobe - o
        # mesmo tipo de bug já visto no ModelRegistry (resolve certo só se
        # rodar exatamente da raiz do projeto, quebra silenciosamente
        # qualquer outro CWD). Agora calcula a raiz de verdade a partir de
        # __file__ (Engine/provisioning/asset_manager.py -> 2 níveis acima).
        if catalog_path is None:
            project_root = Path(__file__).resolve().parent.parent.parent
            catalog_path = project_root / "catalog" / "assets"
        self.catalog_path = Path(catalog_path)
        # PHX-NEW (auditoria 2026-08-20, Seção 14): get_asset() sempre
        # devolveu só 'str | None' - quando dava None, quem chamava (o
        # MissionExecutor em resident_manager.py) só sabia dizer "falha ao
        # baixar", sem saber se foi link morto (404), autenticação exigida
        # (401/403 - repo 'gated' no Hugging Face) ou outra coisa. Guarda o
        # motivo da última chamada aqui pra quem chamou poder logar algo
        # útil sem precisar mudar a assinatura de get_asset() (só um
        # chamador hoje, mas evita quebrar contrato pra quem já confia
        # que o retorno é 'str | None').
        self.last_error: str | None = None

    def _load_catalog(self, asset_name: str) -> dict:
        file_path = self.catalog_path / f"{asset_name}.json"
        if not file_path.exists(): return None
        with open(file_path, 'r', encoding='utf-8') as f: return json.load(f)

    def _resolve_target_dir(self, catalog: dict, asset_name: str) -> Path:
        """PHX-FIX (auditoria completa, pasta Engine/): a maioria dos
        catálogos (11 de 20 em catalog/assets/, ex: flux1-dev-*.json,
        flux_vae.json, sd35_medium.json) tinha target_dir RELATIVO
        (ex: "downloads/images/"). Path(target_dir) resolvia isso contra
        o diretório de trabalho do processo (CWD), gerando arquivos em
        <CWD>/downloads/images/ - mas os drivers que realmente procuram
        o modelo (sd_cpp.py._find_model_file/_find_component,
        whisper.py._find_model) NUNCA olham pra "downloads/" relativo:
        eles só buscam em PhoenixPaths.get_category_path(categoria) e,
        como fallback, pastas "models"/"image-models"/
        "Phoenix\\Workstations\\Models\\Image" na raiz de cada disco.
        Resultado: o download "funcionava" (HTTP 200, arquivo gravado)
        mas o arquivo nunca era encontrado - silencioso, sem exceção,
        exatamente o padrão de bug que essa auditoria vem caçando desde
        o início (a pasta downloads/images|vae|encoders vazia já
        confirma isso rodando no projeto real).

        Correção: target_dir relativo agora é resolvido como subpasta
        dentro de PhoenixPaths.get_category_path(category) - onde os
        drivers de fato procuram (eles usam rglob, então uma subpasta
        funciona). target_dir absoluto (ex: os catálogos de flux/sdxl/
        whisper já corrigidos manualmente com "B:\\Phoenix\\...") continua
        sendo respeitado como está, sem mudança de comportamento."""
        raw = catalog.get("target_dir", f"downloads/{asset_name}/")
        target_dir = Path(raw)

        # PHX-FIX: Path.is_absolute() só reconhece "C:\..." como absoluto
        # rodando em Windows (WindowsPath) - em Linux (comum.ps1 também
        # suporta $IsLinux) o mesmo Path("B:\\Phoenix\\...") vira
        # PosixPath e is_absolute() dá False, o que faria esse valor cair
        # no ramo "relativo" e ser colado por engano dentro do workspace
        # resolvido. Detecta "letra:\" por regex também, independente do
        # SO rodando o processo.
        if target_dir.is_absolute() or _WINDOWS_ABS_PATH_RE.match(raw):
            return target_dir

        if PhoenixPaths is None:
            # Sem PhoenixPaths disponível (uso isolado/teste) - mantém o
            # comportamento antigo em vez de quebrar o import.
            logger.warning(
                f"[AssetManager] PhoenixPaths indisponível - '{raw}' será "
                f"resolvido contra o CWD, pode não ser encontrado pelos drivers."
            )
            return target_dir

        category = catalog.get("category", "Image")
        subfolder = target_dir.name or (target_dir.parent.name if target_dir.parent.name else "")
        base = PhoenixPaths.get_category_path(category)
        return (base / subfolder) if subfolder else base

    def get_asset(self, asset_name: str) -> str:
        self.last_error = None
        catalog = self._load_catalog(asset_name)
        if not catalog:
            self.last_error = f"Catálogo não encontrado: catalog/assets/{asset_name}.json"
            return None

        # Um modelo modular pode declarar arquivos obrigatórios. Isso evita
        # baixar só o diffusion GGUF e descobrir no primeiro generate que o
        # VAE/encoder não existe (caso do Z-Image-Turbo).
        for dependency in catalog.get("dependencies", []):
            dependency_path = self.get_asset(str(dependency))
            if dependency_path is None:
                dependency_error = self.last_error or "erro desconhecido"
                self.last_error = (
                    f"Dependência '{dependency}' de '{asset_name}' falhou: "
                    f"{dependency_error}"
                )
                return None
        self.last_error = None

        target_dir = self._resolve_target_dir(catalog, asset_name)
        filename = catalog.get("filename")
        provider_name = catalog.get("provider", "http")
        provider_data = catalog.get("provider_data", {})

        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / filename

        # PHX-FIX: checa tamanho > 0, não só existência - um arquivo
        # truncado/corrompido (o próprio bug original do flux1-schnell no
        # início desta auditoria) fica "existindo" com 0 bytes ou
        # incompleto e seria tratado como cache válido pra sempre.
        if file_path.exists() and file_path.stat().st_size > 0:
            logger.info(f"[AssetManager] Reutilizando: {file_path}")
            return str(file_path)
        elif file_path.exists():
            logger.warning(f"[AssetManager] Arquivo existente está vazio/corrompido, rebaixando: {file_path}")
            try:
                file_path.unlink()
            except OSError:
                pass

        # PHX-NEW (auditoria 2026-08-20, Seção 14): "se a URL exige
        # autenticação -> não usar como download automático". Um catálogo
        # marcado 'requires_auth: true' nunca tenta a requisição HTTP - ela
        # sempre resultaria em 401/403 pra download automático sem sessão
        # de usuário, então nem vale desperdiçar a tentativa (nem arriscar
        # confundir um 401 de autenticação com outra falha de rede no log).
        # Nenhum catálogo hoje precisa dessa flag (flux_vae.json/
        # flux_vae_mirror.json foram corrigidos pra fontes não-gated), mas
        # o mecanismo fica pronto pro próximo caso assim.
        if catalog.get("requires_auth"):
            self.last_error = (
                f"'{catalog.get('name', asset_name)}' exige autenticação/licença aceita para "
                f"download - não é baixado automaticamente. Baixe manualmente (logado) em "
                f"{provider_data.get('url', '?')} e coloque o arquivo em: {file_path}"
            )
            logger.warning(f"[AssetManager] {self.last_error}")
            return None

        logger.info(f"[AssetManager] Baixando via {provider_name} -> {file_path}")
        provider = ProviderFactory.get_provider(provider_name)
        ok, reason = provider.download(provider_data, file_path)
        if ok:
            if file_path.exists() and file_path.stat().st_size > 0:
                return str(file_path)
            self.last_error = f"Download 'ok' mas arquivo final ausente/vazio: {file_path}"
            logger.error(f"[AssetManager] {self.last_error}")
            return None
        self.last_error = reason or f"Falha desconhecida ao baixar '{asset_name}'."
        return None
