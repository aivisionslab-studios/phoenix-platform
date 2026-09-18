# Phoenix Health Probe Contract — PHX-PHASE6O

## Scope

Health da ponte 3000 -> 8000 é uma preocupação de transporte da Aviary Platform.
Não pertence ao ExecutionOrchestrator, RuntimeEngine, StateEngine ou ObservabilityService.

## Responsibilities

- `/api/ping`: prova local da porta 3000; não toca o Engine Python.
- `probePhoenixEngineHealth()`: sonda funcional curta da porta 8000.
- `/api/health`: compõe o estado da Aviary + última prova funcional do Engine.
- `?fresh=1`: força uma sonda nova e é usado pelo ping manual.

## Coalescing

Chamadas simultâneas compartilham a mesma Promise de probe. A última prova pode ser
reutilizada por `PHOENIX_ENGINE_HEALTH_CACHE_MS` (default 1250 ms).

A janela curta existe apenas para desacoplar refresh visual de sonda funcional. Não é
um cache de telemetry/state.

## Latency semantics

`engineLatencyMs` é a latência da sonda real ao Phoenix Engine, não a duração da chamada
browser -> `/api/health` quando a resposta veio do cache curto.

## Non-goals

Este mecanismo não:
- substitui `/api/state`;
- substitui AHDE/Telemetry;
- decide runtime/placement;
- altera jobs, leases ou residency;
- substitui os progress channels de Arena/audiobook.
