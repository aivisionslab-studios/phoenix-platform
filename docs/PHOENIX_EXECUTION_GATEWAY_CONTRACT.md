# PHX-PHASE6C — Execution Gateway Contract

## Propósito

`ExecutionGateway` é uma **ponte fina de execução**, compartilhada pelo Kernel,
ResidentManager, ReasoningEngine e serviços de domínio. Ela existe para impedir
que cada workflow implemente novamente a regra:

```text
ExecutionOrchestrator disponível? -> use-o
senão -> RuntimeEngine (compatibilidade isolada)
```

## O que ela NÃO é

A Gateway não é scheduler, não é manager de modelos e não é uma nova autoridade.
Ela não mantém estado de residência, leases, hardware, AUTO ou compatibilidade.

| Responsabilidade | Autoridade |
|---|---|
| ciclo de vida geral | PhoenixKernel |
| coordenação/logística de workflows | ResidentManager / Domain Services |
| placement, correctness, coordenação de recursos | ExecutionOrchestrator |
| ownership, leases e fila | ResourceLedger |
| processo/instância física | RuntimeEngine |
| identidade validada residente | ResidencyRegistry |
| mecanismo nativo | Drivers / Phoenix runtimes |
| roteamento fino Orchestrator→fallback legado | ExecutionGateway |

## Regra de produção

Com o PhoenixKernel completo, a Gateway sempre possui um `ExecutionOrchestrator`.
Logo, `execute`, `ensure_runtime` e `stop_runtime` sempre delegam ao Orchestrator.

O acesso direto ao `RuntimeEngine` dentro da Gateway existe somente para:

- testes unitários isolados;
- plugins antigos;
- componentes construídos fora do PhoenixKernel completo.

Uma falha do Orchestrator **nunca** dispara fallback silencioso para RuntimeEngine.
Isso impediria a Phoenix de executar com outro placement/modelo depois que a
autoridade computacional já rejeitou a operação.

## Fronteira estrutural

A partir da Phase 6C, workflows não devem chamar diretamente:

```python
self.runtime.start(...)
self.runtime.stop(...)
self.runtime.execute(...)
```

Essas chamadas ficam restritas ao `ExecutionOrchestrator` e à
`ExecutionGateway` (fallback de compatibilidade).

Essa regra é protegida por teste AST para evitar regressão arquitetural.

## Phase 6D — Managed workflow leases

A Gateway também é a fronteira para workflows compostos que precisam manter
recursos por vários passos (Arena, workers documentais etc.). Isso NÃO transfere
autoridade para a Gateway: ela apenas encapsula o contrato operacional do
ExecutionOrchestrator.

Contratos novos:

- `reserve_workflow_resources(...)` → devolve `ManagedResourceReservation`;
- `resource_reservation(...)` → contexto que sempre libera a reserva;
- `open_dedicated_llama(...)` → devolve `ManagedDedicatedRuntime`;
- `dedicated_llama(...)` → contexto que sempre encerra o worker dedicado.

O handle dedicado expõe apenas a identidade observada, o perfil validado e
`execute(plan)`. Ele não escolhe placement, porta, NGL ou correctness.

Regra:

```text
Workflow (Resident/Service)
    ↓ descreve necessidade
ExecutionGateway
    ↓ delega
ExecutionOrchestrator
    ↓ ownership / correctness / residency
RuntimeEngine
    ↓ processo/instância
Driver
```

Workflows não devem manipular diretamente `RuntimeLease`, `driver.stop()`,
`RuntimeEngine.execute_instance()` ou `release_dedicated_runtime()`.
