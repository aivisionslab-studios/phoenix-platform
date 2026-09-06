# PHOENIX ENGINE — Visão Geral (Vision)

## O que é a Phoenix?
A Phoenix não é um instalador de programas, nem um simples painel de telemetria. Ela é um **Sistema Operacional de IA Local**. 

Sua função é atuar como um orquestrador inteligente que compreende completamente o hardware e o software do computador onde está instalada, para provisionar, gerenciar e otimizar ambientes de Inteligência Artificial de forma autônoma.

## O Pipeline Central
Toda a plataforma opera sobre um pipeline de 5 fases, estritamente separado por responsabilidades:

1. **Knowledge (Conhecer):** Descobrir o hardware, medir sensores e persistir o estado da máquina.
2. **Reasoning (Pensar):** Interpretar a intenção do usuário (via LLM ou regras) baseando-se no conhecimento da máquina.
3. **Planning (Planejar):** Transformar a intenção em um objeto estruturado (Mission) com passos abstratos.
4. **Provisioning (Adaptar):** Traduzir os passos abstratos para comandos reais do Sistema Operacional (Windows/Linux).
5. **Execution (Fazer):** Executar os comandos via Drivers (Winget, APT, Docker, Git) e reportar o resultado.

## Filosofia
- **Hardware Revival:** Provar que hardware legado (como a RX 580) ainda é capaz de rodar IA moderna de ponta usando backends abertos como o Vulkan.
- **Segurança e Aprovação:** A IA nunca executa ações no sistema operacional diretamente. Ela apenas cria "Missões" que exigem aprovação humana (Execution Guard).
- **Independência de SO:** O cérebro da Phoenix não sabe se está rodando no Windows ou no Ubuntu. Apenas os executores finais conhecem o SO.
