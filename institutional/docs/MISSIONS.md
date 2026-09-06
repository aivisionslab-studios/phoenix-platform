# Missões — AIVisions Phoenix Engine

## O que é uma Missão

Em vez de instalar peça por peça, a Phoenix oferece **missões** pelo App Store integrado: pacotes coerentes de ferramentas + modelos para um objetivo específico.

| Missão | O que provisiona | Tempo | Tamanho |
|---|---|---|---|
| 🧠 Assistente Pessoal | LLM + RAG para estudos e produtividade | 20–40 min | 15 GB |
| 💬 Conversar com IA | Stack completa de chat local | 15–30 min | 10 GB |
| 🖥️ Modo CPU Only | Para máquinas sem GPU dedicada | 10 min | 5 GB |
| 💻 Ambiente Dev | Ferramentas de programação + IA | 15–20 min | 10 GB |
| 🎨 Criar Imagens | Geração de imagens + workflows | 20–40 min | 25 GB |
| 🔍 Pesquisa Inteligente | Busca privada + RAG local | 10–15 min | 5 GB |
| 🎙️ Studio de Voz Offline | STT, TTS e clonagem de voz | 15–20 min | 8 GB |
| 🚀 Plataforma Completa | Tudo que o hardware suporta | 60+ min | 50+ GB |
| ⚡ RX 580 Revival | Otimizado para Polaris/GCN4 via Vulkan | 20–30 min | 15 GB |

## Ciclo de vida de uma missão

1. **Definição** — a missão existe como entrada de catálogo em `catalog/`;
2. **Intent** — o usuário solicita a execução via App Store ou Terminal Deck;
3. **Planner** — traduz a missão em plano de execução, aplicando a política de roteamento fixa (texto→CPU, imagem→GPU);
4. **Resident** — avalia risco e, se necessário, solicita aprovação;
5. **Runtime** — executa os passos (clonagem/compilação, containers, downloads);
6. **Logs** — cada etapa é registrada (`phoenix_kernel/logs/`, comando `logs`).

## Aprovação

Missões que envolvem ações de maior impacto aguardam aprovação explícita do usuário via Resident Manager.
