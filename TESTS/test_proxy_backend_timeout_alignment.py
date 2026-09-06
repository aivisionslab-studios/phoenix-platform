"""
Teste de regressão pra auditoria 2026-08-21, "corrigir tudo" - resposta a um
achado real de uma auditoria externa independente (outra sessão do Claude,
lendo o `PHOENIX_3.0_RODADA21.zip` de fora): o AbortController do proxy Node
(`platform_source/server.ts`) e o timeout interno do driver/guard Python
correspondente, pra várias rotas que repassam pro Phoenix Engine, não tinham
margem nenhuma entre si (ou pior, o proxy era mais curto que o backend) -
nesse caso o Node aborta a conexão ANTES do Engine terminar de processar (ou
antes dele devolver seu próprio erro controlado e claro), trocando uma
mensagem específica por um 502/504 genérico, mesmo com o Engine são e ainda
trabalhando.

A auditoria externa flagrou isso originalmente só pra
`/api/documents/read`/`/edit` (proxy 300s vs guard interno 240s - só 60s de
margem). Investigando o resto do arquivo pra "corrigir tudo" de verdade,
achei mais três pontos com o mesmo problema, dois deles PIORES (margem
ZERO, não só apertada):

1. `/api/documents/read` e `/api/documents/edit`: proxy 300s vs
   DOCUMENT_EXECUTE_TIMEOUT_SECONDS 240s (60s de margem, apertado pro
   hardware relatado pelo usuário - Xeon E5-2690 v3 + RX 580 via Vulkan).
2. `/api/describe-image`: proxy 180s vs timeout do MtmdDriver 180.0s -
   MARGEM ZERO, corrida real.
3. `/api/transcribe`: proxy 600s vs timeout do WhisperDriver 600s -
   MARGEM ZERO, corrida real.
4. `/api/benchmark`: proxy 60s vs `run_token_benchmark_direct()`, que não
   tinha NENHUM teto próprio (só o timeout de 600s de cada driver por
   baixo) - gap de até 10x, sem nenhum guard interno pra devolver um erro
   controlado antes do Node desistir.

Fix, mesmo padrão em todo lugar - o Engine (Python) sempre desiste primeiro,
com uma mensagem clara; o Node é só uma rede de segurança que na prática
nunca deveria disparar:
- `DOCUMENT_EXECUTE_TIMEOUT_SECONDS`: 240s -> 480s; proxy correspondente:
  300s -> 540s.
- `/api/describe-image`: proxy 180s -> 240s (driver não mudou, só ganhou
  margem).
- `/api/transcribe`: proxy 600s -> 660s (driver não mudou, só ganhou
  margem).
- `/api/benchmark`: `run_token_benchmark_direct()` ganhou um teto próprio
  novo, `BENCHMARK_EXECUTE_TIMEOUT_SECONDS` = 300s; proxy: 60s -> 360s.

Esta bateria lê o código-fonte real dos dois lados (backend Python + proxy
Node) e confere que o proxy sempre tem uma margem de segurança POSITIVA
acima do teto real do backend - nunca igual, nunca menor.

Rodar com: pytest -q (de dentro de 'PHOENIX 3.0/')
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ROOT = Path(__file__).resolve().parent.parent
_SERVER_TS = _ROOT / "platform_source" / "server.ts"
_RESIDENT_MANAGER = _ROOT / "phoenix_kernel" / "resident" / "resident_manager.py"
_MTMD_DRIVER = _ROOT / "phoenix_kernel" / "runtime" / "drivers" / "mtmd_driver.py"
_WHISPER_DRIVER = _ROOT / "phoenix_kernel" / "runtime" / "drivers" / "whisper.py"

_MIN_MARGIN_SECONDS = 30  # qualquer margem positiva conta, mas exige pelo menos meio minuto de folga real


def _server_ts_source() -> str:
    return _SERVER_TS.read_text(encoding="utf-8")


def _resident_manager_source() -> str:
    return _RESIDENT_MANAGER.read_text(encoding="utf-8")


def _proxy_timeout_ms_near(src: str, route_marker: str, search_window: int = 2600) -> int:
    """Acha o app.post(route_marker...) e devolve o valor em ms do primeiro
    `setTimeout(() => ...abort(), N)` depois dele."""
    idx = src.index(route_marker)
    chunk = src[idx:idx + search_window]
    m = re.search(r"setTimeout\(\(\)\s*=>\s*\w+\.abort\(\),\s*(\d[\d_]*)\)", chunk)
    assert m, f"não achei setTimeout(...abort(), N) perto de {route_marker!r}"
    return int(m.group(1).replace("_", ""))


def test_documents_read_and_edit_proxy_has_margin_over_engine_guard():
    resident_src = _resident_manager_source()
    m = re.search(r"DOCUMENT_EXECUTE_TIMEOUT_SECONDS\s*=\s*(\d+)", resident_src)
    assert m, "não achei DOCUMENT_EXECUTE_TIMEOUT_SECONDS em resident_manager.py"
    backend_seconds = int(m.group(1))

    server_src = _server_ts_source()
    for route in ('app.post("/api/documents/read"', 'app.post("/api/documents/edit"'):
        proxy_ms = _proxy_timeout_ms_near(server_src, route)
        proxy_seconds = proxy_ms / 1000
        assert proxy_seconds > backend_seconds + _MIN_MARGIN_SECONDS, (
            f"{route}: proxy ({proxy_seconds}s) não tem margem suficiente sobre "
            f"DOCUMENT_EXECUTE_TIMEOUT_SECONDS ({backend_seconds}s)"
        )


def test_describe_image_proxy_has_margin_over_mtmd_driver_timeout():
    driver_src = _MTMD_DRIVER.read_text(encoding="utf-8")
    # PHX-FIX (auditoria completa 2026-08-28): o driver foi refatorado pra
    # usar `asyncio.wait_for(process.communicate(), timeout=timeout_seconds)`
    # com uma VARIÁVEL (configurável via `plan.parameters`), não mais um
    # número literal colado direto em `.communicate(..., timeout=180)`. O
    # valor por padrão (mesmo 180s de antes) agora mora no `.get(...)` que
    # popula essa variável - procura ali em vez do padrão antigo.
    m = re.search(r'timeout_seconds\s*=\s*float\(plan\.parameters\.get\("timeout_seconds",\s*(\d+(?:\.\d+)?)\)\)', driver_src)
    assert m, "não achei o timeout padrão (timeout_seconds) do MtmdDriver"
    backend_seconds = float(m.group(1))
    # Confirma que esse timeout_seconds é de fato usado no wait_for do
    # communicate() - não só declarado e ignorado.
    assert re.search(r"wait_for\(\s*process\.communicate\(\),\s*timeout=timeout_seconds\)", driver_src), (
        "timeout_seconds não está mais sendo usado no asyncio.wait_for(process.communicate(), ...) do MtmdDriver"
    )

    server_src = _server_ts_source()
    proxy_ms = _proxy_timeout_ms_near(server_src, 'app.post("/api/describe-image"')
    proxy_seconds = proxy_ms / 1000
    assert proxy_seconds > backend_seconds + _MIN_MARGIN_SECONDS, (
        f"/api/describe-image: proxy ({proxy_seconds}s) não tem margem suficiente "
        f"sobre o timeout do MtmdDriver ({backend_seconds}s)"
    )


def test_transcribe_proxy_has_margin_over_whisper_driver_timeout():
    driver_src = _WHISPER_DRIVER.read_text(encoding="utf-8")
    m = re.search(r"process\.communicate\(\)[^)]*,\s*timeout=(\d+(?:\.\d+)?)\)", driver_src)
    assert m, "não achei o timeout interno do WhisperDriver"
    backend_seconds = float(m.group(1))

    server_src = _server_ts_source()
    proxy_ms = _proxy_timeout_ms_near(server_src, 'app.post("/api/transcribe"')
    proxy_seconds = proxy_ms / 1000
    assert proxy_seconds > backend_seconds + _MIN_MARGIN_SECONDS, (
        f"/api/transcribe: proxy ({proxy_seconds}s) não tem margem suficiente "
        f"sobre o timeout do WhisperDriver ({backend_seconds}s)"
    )


def test_benchmark_has_its_own_engine_guard_and_proxy_has_margin_over_it():
    resident_src = _resident_manager_source()
    m = re.search(r"BENCHMARK_EXECUTE_TIMEOUT_SECONDS\s*=\s*(\d+)", resident_src)
    assert m, (
        "run_token_benchmark_direct() precisa de um teto próprio "
        "(BENCHMARK_EXECUTE_TIMEOUT_SECONDS) - sem isso o único limite é o "
        "timeout interno do driver (600s), bem acima do que o proxy espera"
    )
    backend_seconds = int(m.group(1))

    # A função precisa de fato usar a constante, não só declará-la.
    bench_start = resident_src.index("async def run_token_benchmark_direct")
    bench_chunk = resident_src[bench_start:bench_start + 2000]
    assert "asyncio.wait_for" in bench_chunk
    assert "BENCHMARK_EXECUTE_TIMEOUT_SECONDS" in bench_chunk

    server_src = _server_ts_source()
    proxy_ms = _proxy_timeout_ms_near(server_src, 'app.post("/api/benchmark"')
    proxy_seconds = proxy_ms / 1000
    assert proxy_seconds > backend_seconds + _MIN_MARGIN_SECONDS, (
        f"/api/benchmark: proxy ({proxy_seconds}s) não tem margem suficiente "
        f"sobre BENCHMARK_EXECUTE_TIMEOUT_SECONDS ({backend_seconds}s)"
    )


def test_benchmark_timeout_error_is_controlled_not_a_bare_exception():
    resident_src = _resident_manager_source()
    bench_start = resident_src.index("async def run_token_benchmark_direct")
    bench_chunk = resident_src[bench_start:bench_start + 2000]
    assert "except asyncio.TimeoutError" in bench_chunk
    assert '"ok": False' in bench_chunk
