# Filosofia — AIVisions Phoenix Engine

> "Hardware não morre — só espera o software certo."

## Princípios fundamentais

**1. Hardware não deve ser descartado por falta de software.**
Máquinas antigas — CPUs de servidor, GPUs de geração passada — continuam capazes de rodar IA local. A Phoenix existe para provar isso, detectando a melhor estratégia de execução (CPU, GPU ou híbrida) para o hardware que você já tem.

**2. IA local, por padrão.**
Execução local não é uma feature opcional — é a arquitetura padrão. A nuvem é exceção, não regra.

**3. Privacidade como arquitetura, não como promessa.**
Prompts, documentos e conteúdo gerado permanecem no seu sistema. Não porque uma política diz isso, mas porque o software foi desenhado assim.

**4. Transparência e auditabilidade.**
Toda decisão automática do Resident Manager é logada. O usuário pode sempre ver o que foi decidido, por que, e reverter.

**5. Sem dependência obrigatória da nuvem.**
Serviços externos (download de modelos, busca web, telemetria) são complementos opcionais, nunca pré-requisitos para o funcionamento básico.

**6. O usuário não deve precisar conhecer flags, compiladores ou backends.**
A complexidade de compilar llama.cpp para uma GPU específica, configurar Docker ou escolher entre CPU/Vulkan/CUDA é absorvida pela Phoenix. O usuário decide *o quê*, a Phoenix decide *como*.

**7. Integrar em vez de reinventar.**
llama.cpp, stable-diffusion.cpp, Whisper, ComfyUI, Open WebUI já resolvem seus respectivos problemas bem. A Phoenix orquestra essas tecnologias consolidadas em vez de recriá-las.

**8. Aproveitar hardware legado antes de exigir upgrade.**
A estratégia padrão de provisionamento sempre considera primeiro o que já está disponível na máquina do usuário.

**9. IA como ferramenta de orquestração, não substituta do controle do usuário.**
O Resident Manager sugere e prepara; ações destrutivas ou de alto impacto aguardam aprovação humana explícita.

**10. Arquitetura modular, transparente e auditável.**
Kernel, Resident Manager, Planner e Runtime são componentes desacoplados, conectados por contratos públicos — não por acoplamento implícito.

**11. Democratização da IA.**
O objetivo de longo prazo é reduzir a barreira técnica entre "ter hardware capaz de rodar IA" e "efetivamente rodar IA local com qualidade".

## Errata Evolutiva

A Phoenix adota uma metodologia de **correção transparente de erros documentados ao longo do tempo** ("Errata Evolutiva"): mudanças que quebram compatibilidade são registradas e explicadas no `CHANGELOG.md`, em vez de silenciosamente sobrescritas.
