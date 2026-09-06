"""
phoenix_kernel/models/registry.py

Model Registry — Fase 2 da Abstração de Capacidades.

Antes: resident_manager.py, reasoning_engine.py e api_server.py tinham
nomes de modelo espalhados como string literal ("qwen3:8b", "minicpmv",
"flux", "pt_br-faber-medium") direto no meio da lógica de negócio.
Trocar o modelo padrão de qualquer capacidade exigia caçar e editar
código em 3 arquivos diferentes.

Depois: catalog/models.json declara "qual modelo cobre qual capacidade"
e "qual é o default de cada capacidade". Este módulo só lê esse JSON e
resolve `role -> modelo`. Nenhum outro arquivo do kernel conhece nomes
de modelo específicos - eles pedem uma CAPACIDADE ("vision",
"image_generation", "chat"...) e recebem de volta o modelo certo.

Isso é o mesmo princípio de abstração que phoenix_kernel/documents/
engine.py já aplica pra formato de arquivo: quem chama não sabe o
detalhe de implementação, só pede o que precisa.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_PATH = Path(__file__).parent.parent.parent / "catalog" / "models.json"


class ModelRegistryError(Exception):
    """Erro ao carregar ou consultar o catálogo de modelos."""


@dataclass(frozen=True)
class ResolvedModel:
    """Resultado de uma resolução de capacidade: qual modelo usar, em
    qual runtime (alias que o RuntimeEngine já sabe rotear), e quanto de
    VRAM ele estima consumir (vram_mb_estimate=0 significa "roda em CPU"
    ou "não medido ainda" - ver notes de cada entrada no catálogo).
    vram_mb_estimate existe desde a Fase 2 mas só passa a ser CONSUMIDO
    na Fase 3 (Hot-Swap) - deixar aqui agora evita reabrir este dataclass
    depois."""
    id: str
    runtime: str
    roles: tuple[str, ...]
    vram_mb_estimate: int = 0


class ModelRegistry:
    """Carrega catalog/models.json uma vez e resolve `role -> ResolvedModel`
    sob pedido. Se o catálogo não existir ou estiver malformado, o
    Registry não derruba a Phoenix - fica vazio e todo `resolve()` volta
    None, e quem chamou decide o que fazer (o comportamento anterior à
    Fase 2, com literal hardcoded, também não tinha rede de segurança
    melhor que essa - só que agora o problema fica visível no log em vez
    de espalhado pelo código)."""

    def __init__(self, catalog_path = DEFAULT_CATALOG_PATH):
        self._catalog_path = Path(catalog_path)
        self._models: list[dict] = []
        self._roles: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self._catalog_path.exists():
            logger.warning(
                f"ModelRegistry: catálogo não encontrado em '{self._catalog_path}'. "
                f"resolve() sempre devolverá None até o arquivo existir."
            )
            return
        try:
            data = json.loads(self._catalog_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error(f"ModelRegistry: falha ao ler/parsear '{self._catalog_path}': {e}")
            return

        models = data.get("models", [])
        if not isinstance(models, list):
            logger.error(f"ModelRegistry: 'models' em '{self._catalog_path}' não é uma lista. Ignorando catálogo.")
            return

        valid_models = []
        for i, m in enumerate(models):
            if not isinstance(m, dict) or "id" not in m or "runtime" not in m:
                logger.warning(f"ModelRegistry: entrada #{i} do catálogo inválida (faltando 'id' ou 'runtime'). Ignorada.")
                continue
            valid_models.append(m)

        self._models = valid_models
        self._roles = data.get("roles", [])
        logger.info(f"ModelRegistry: {len(self._models)} modelo(s) carregado(s) de '{self._catalog_path}'.")

    def reload(self) -> None:
        """Recarrega o catálogo do disco - útil se o arquivo for editado
        com a Phoenix já rodando (não é chamado automaticamente)."""
        self._models = []
        self._roles = []
        self._load()

    def known_roles(self) -> list[str]:
        return list(self._roles)

    def all_for_role(self, role: str) -> list[ResolvedModel]:
        """Todos os modelos que cobrem `role`, na ordem em que aparecem
        no catálogo (o default_for_roles vem primeiro por convenção, mas
        isso não é garantido por esta função - use resolve() se quiser
        especificamente o default)."""
        return [self._to_resolved(m) for m in self._models if role in m.get("roles", [])]

    def resolve(self, role: str, hint: str = "") -> ResolvedModel | None:
        """Resolve qual modelo usar para `role`. Se `hint` for passado
        (ex: o usuário pediu "gera com sdxl" ou model_hint="minicpmv"),
        tenta casar primeiro por id exato, depois por file_patterns
        (substring, case-insensitive). Sem match de hint, cai pro
        default_for_roles declarado no catálogo. Sem default declarado,
        usa o primeiro modelo que cobre a role (mais previsível que
        devolver None quando existe pelo menos uma opção real).

        Devolve None só quando NENHUM modelo do catálogo cobre `role` -
        nesse caso quem chamou deve tratar como "capacidade não
        configurada" (mensagem de erro clara pro usuário), nunca inventar
        um nome de modelo na hora."""
        candidates = [m for m in self._models if role in m.get("roles", [])]
        if not candidates:
            logger.warning(f"ModelRegistry: nenhum modelo no catálogo cobre a role '{role}'.")
            return None

        hint = (hint or "").strip().lower()
        if hint:
            # 1. match exato por id
            for m in candidates:
                if m["id"].lower() == hint:
                    return self._to_resolved(m)
            # 2. match por substring nos file_patterns (ex: hint="quero flux" casa com id="flux")
            for m in candidates:
                patterns = [p.lower() for p in m.get("file_patterns", [])]
                if any(p in hint or hint in p for p in patterns):
                    return self._to_resolved(m)
            logger.info(
                f"ModelRegistry: hint '{hint}' não bateu com nenhum modelo da role '{role}'. "
                f"Caindo pro default."
            )

        # 3. default declarado no catálogo
        for m in candidates:
            if role in m.get("default_for_roles", []):
                return self._to_resolved(m)

        # 4. sem default declarado - primeiro candidato é melhor que None
        logger.warning(
            f"ModelRegistry: role '{role}' não tem default_for_roles declarado. "
            f"Usando o primeiro modelo do catálogo que cobre essa role: '{candidates[0]['id']}'."
        )
        return self._to_resolved(candidates[0])

    @staticmethod
    def _to_resolved(m: dict) -> ResolvedModel:
        return ResolvedModel(
            id=m["id"],
            runtime=m["runtime"],
            roles=tuple(m.get("roles", [])),
            vram_mb_estimate=int(m.get("vram_mb_estimate", 0) or 0),
        )
