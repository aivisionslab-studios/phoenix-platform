# Planner — AIVisions Phoenix Engine

O Planner (`phoenix_kernel/planner/`) traduz uma decisão do Resident Manager em um **plano de execução concreto**, considerando o hardware detectado, a política de roteamento e o RAG local.

## Responsabilidades

- Determinar a sequência de passos necessários para atingir uma intenção (ex.: instalar Docker → clonar/compilar motor → provisionar container → baixar modelo → validar);
- Aplicar a **política de roteamento fixa** da Phoenix: modelos de texto (LLM/chat) sempre em CPU via llama.cpp; modelos de imagem (SD 1.5/SDXL) sempre em GPU via stable-diffusion.cpp/Vulkan — evitando disputa de VRAM entre as duas cargas;
- Consultar o Model Catalog (`catalog/`) para recomendar modelos compatíveis com a Machine Class e o GPU Score detectados;
- Planejamento assistido por RAG local, usando a base de conhecimento indexada (`data/knowledge_base.json` → índice vetorial em `data/chroma_db/`).

## Relação com o Resident Manager

O Planner não decide *se* uma ação deve ocorrer — isso é papel do Resident Manager e da aprovação do usuário. O Planner decide *como* executá-la de forma consistente com a política de roteamento fixa e o hardware disponível.

## Relação com o Runtime

Uma vez que o plano está pronto, ele é repassado ao Runtime (`phoenix_kernel/runtime/`) para execução efetiva.
