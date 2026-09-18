# Runtime — AIVisions Phoenix Engine

O Runtime (`phoenix_kernel/runtime/`) é o componente responsável pela **execução efetiva** dos planos aprovados, coordenando containers, processos e motores de inferência.

## Responsabilidades

- Executar os passos definidos pelo Planner na ordem correta;
- Gerenciar o ciclo de vida de containers Docker (Ollama, Open WebUI, SearXNG);
- Invocar os motores por capacidade; Phoenix Llama Runtime e Phoenix Diffusion escolhem o placement em AUTO conforme modelo, hardware, memória, compatibilidade e recursos ativos. CPU/GPU/HYBRID são overrides explícitos do usuário.
- Capturar logs e erros de execução para diagnóstico (`phoenix_kernel/logs/`);
- Reportar status de volta ao Resident Manager e ao dashboard Mission Control em tempo real (seção **Inference** e **System Telemetry**).

## Execução segura

- Ações com potencial destrutivo já passaram pelo fluxo de aprovação do Resident Manager antes de chegar ao Runtime;
- O Runtime não toma decisões de "o quê" fazer — apenas "como" executar o que já foi decidido e aprovado.

## Observabilidade

Toda execução do Runtime gera telemetria local (`phoenix_kernel/telemetry/`) consumida pelo dashboard: temperatura, carga de CPU/GPU, uso de VRAM ao vivo.


## Telemetria técnica

Métricas de execução, compatibilidade, erros, performance e comportamento técnico dos modelos/runtimes podem compor diagnósticos enviados aos serviços Phoenix/AIVisionsLab conforme a Política de Telemetria. Conteúdo integral de prompts/documentos não é objetivo da telemetria técnica normal.
