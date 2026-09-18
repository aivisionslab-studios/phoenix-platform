# PHX-PHASE6E — Model Runtime Service Contract

## Papel

`ModelRuntimeService` é a ponte de control-plane para operações de modelo/runtime
solicitadas pelo usuário ou pela UI. Ele não é scheduler, não possui recursos e
não substitui o `ExecutionOrchestrator`.

## Responsabilidades do ModelRuntimeService

- persistir e expor a engine de texto escolhida (`llama.cpp` / Ollama);
- persistir e expor a preferência de execução (`default/AUTO`, CPU, GPU, HYBRID);
- sincronizar a escolha de engine com `ReasoningEngine`;
- solicitar load/unload/recovery por `ExecutionGateway`;
- executar benchmark real de tokens por `ExecutionGateway` com timeout próprio;
- observar `ResidencyRegistry`/RuntimeEngine apenas para descobrir qual modelo deve
  ser reconciliado depois de uma mudança explícita de preferência.

## O que ele NÃO pode fazer

- escolher algoritmo Phoenix AUTO;
- possuir ou criar `ResourceLedger`;
- criar uma segunda `ResidencyRegistry`;
- reservar CPU/GPU por conta própria;
- iniciar/parar `RuntimeEngine` diretamente em produção;
- implementar correctness gate;
- decidir regras Dense/MoE;
- possuir processo/PID/porta.

## Autoridades

```text
ResidentManager       -> coordenação/logística de workflows + wrappers legados
ModelRuntimeService   -> control-plane de modelos/preferências
ExecutionGateway      -> ponte fina para execução/lifecycle
ExecutionOrchestrator -> placement/correctness/coordenação de recursos
ResourceLedger        -> ownership, leases e fila
ResidencyRegistry     -> identidade validada residente
RuntimeEngine         -> processos/instâncias
Drivers               -> mecanismo nativo
```

## Compatibilidade

`ResidentManager` mantém wrappers:

- `get_text_engine_preference()`
- `set_text_engine_preference()`
- `get_text_execution_preference()`
- `set_text_execution_preference()`
- `recover_text_runtime()`
- `load_model_direct()`
- `unload_model_direct()`
- `run_token_benchmark_direct()`

Esses wrappers delegam ao `ModelRuntimeService`. O atributo legado
`ResidentManager._VALID_TEXT_ENGINES` continua disponível para plugins/testes
antigos, mas não é a fonte arquitetural da política.

## Regra de produção

A API moderna prefere `kernel.model_runtime_service`. O fallback para
`kernel.resident` existe apenas para compatibilidade durante inicialização parcial,
plugins e testes legados.
