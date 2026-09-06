# Runtime — AIVisions Phoenix Engine

O Runtime (`phoenix_kernel/runtime/`) é o componente responsável pela **execução efetiva** dos planos aprovados, coordenando containers, processos e motores de inferência.

## Responsabilidades

- Executar os passos definidos pelo Planner na ordem correta;
- Gerenciar o ciclo de vida de containers Docker (Ollama, Open WebUI, SearXNG);
- Invocar os motores de inferência conforme a política de roteamento fixa: llama.cpp/Ollama (texto, CPU), stable-diffusion.cpp (imagem, GPU/Vulkan), whisper.cpp (áudio);
- Capturar logs e erros de execução para diagnóstico (`phoenix_kernel/logs/`);
- Reportar status de volta ao Resident Manager e ao dashboard Mission Control em tempo real (seção **Inference** e **System Telemetry**).

## Execução segura

- Ações com potencial destrutivo já passaram pelo fluxo de aprovação do Resident Manager antes de chegar ao Runtime;
- O Runtime não toma decisões de "o quê" fazer — apenas "como" executar o que já foi decidido e aprovado.

## Observabilidade

Toda execução do Runtime gera telemetria local (`phoenix_kernel/telemetry/`) consumida pelo dashboard: temperatura, carga de CPU/GPU, uso de VRAM ao vivo.
