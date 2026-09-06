import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SEARXNG_URL = "http://localhost:8080/search"

# Cabeçalho para fingir ser um navegador real e bypassar o anti-bot (erro 403) do SearXNG
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "X-Real-IP": "127.0.0.1"  # Resolve o erro 'X-Forwarded-For nor X-Real-IP header is set!'
}


def _normalize_result(result: dict[str, Any], source_id: str) -> dict[str, str] | None:
    """Normaliza um resultado bruto do SearXNG.

    Grounding V1: URL passa a ser dado de primeira classe. Resultado sem URL
    não entra na lista estruturada porque não pode ser citado/verificado.
    """
    title = str(result.get("title") or "").strip()
    url = str(result.get("url") or "").strip()
    snippet = str(result.get("content") or "").strip()

    if not url:
        return None

    return {
        "source_id": source_id,
        "title": title or url,
        "url": url,
        "snippet": snippet,
    }


async def search_web(
    query: str,
    max_results: int = 3,
    *,
    structured: bool = False,
) -> str | list[dict[str, str]]:
    """Busca na internet usando a instância local do SearXNG.

    Compatibilidade:
    - structured=False (default): mantém o contrato legado e retorna string.
    - structured=True: retorna fontes verificáveis com source_id/title/url/snippet.

    O modo estruturado é usado pelo Grounding V1 de documentos e não altera os
    consumidores existentes que ainda esperam texto.
    """
    logger.info(f"[WebSearch] Buscando na internet: '{query}'")

    params = {"q": query, "format": "json", "categories": "general"}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(SEARXNG_URL, params=params, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()

        raw_results = data.get("results", [])
        if not raw_results:
            return [] if structured else "Nenhum resultado encontrado na web."

        normalized: list[dict[str, str]] = []
        for r in raw_results:
            if len(normalized) >= max_results:
                break
            item = _normalize_result(r, f"S{len(normalized) + 1}")
            if item is not None:
                normalized.append(item)

        if structured:
            logger.info(
                f"[WebSearch] Busca concluída via SearXNG local: "
                f"{len(normalized)} fonte(s) estruturada(s)."
            )
            return normalized

        if not normalized:
            return "Nenhum resultado encontrado na web."

        # Contrato legado preservado, agora enriquecido com URL real.
        # Isso melhora os consumidores antigos sem mudar o tipo de retorno.
        text_results = []
        for item in normalized:
            text_results.append(
                f"- {item['title']}: {item['snippet']}\n  URL: {item['url']}"
            )

        logger.info("[WebSearch] Busca concluída via SearXNG local.")
        return "\n".join(text_results)

    except Exception as e:
        logger.error(f"[WebSearch] Falha ao buscar no SearXNG: {e}")
        return [] if structured else f"Falha ao acessar a internet (SearXNG): {e}"
