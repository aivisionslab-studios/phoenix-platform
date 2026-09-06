# PHOENIX ENGINE 5.0 — ARQUITETURA MESTRE (V1)

**Status:** Congelado para Implementação  

## 1. O Pipeline e Seus Componentes

### Fase 1: Knowledge (Conhecer)
*   **Discovery:** Varredura estática (CPU, GPU, Discos, SO, Drivers). Roda no boot.
*   **Telemetry:** Sensores em tempo real (Temperatura, Carga, VRAM). Estado volátil.
*   **State Engine:** Estado **instantâneo** em memória RAM.
*   **Machine Knowledge Base:** Estado **persistente** e histórico.

### Fase 2: Policy Engine (Regras de Segurança)
Fica entre o Conhecimento e o Raciocínio. Impõe limites de segurança.

### Fase 3: Reasoning (Pensar)
*   **Reasoning Engine:** O cérebro (Agnóstico ao LLM). Nunca acessa o SO.

### Fase 4: Planning (Planejar a Ação)
*   **Blueprint Catalog:** Diretório `missions/catalog/`. Contém arquivos JSON que são *templates* (receitas) de ambientes.
*   **Mission Planner:** Monta um objeto `Mission` estruturado com `MissionSteps` abstratos.
*   **Mission Kernel:** Gerencia o ciclo de vida da Missão. Contém o **Execution Guard**.

### Fase 5: Provisioning (Adaptar ao SO)
*   **Provision Planner:** Gera um **Execution Plan** concreto baseado no SO.
*   **Provision Executor:** Roda os comandos no `Services Engine`.

### Fase 6: Execution (Fazer)
*   **Services Engine:** Camada que encapsula `winget`, `apt`, `git clone`, `docker run`.
