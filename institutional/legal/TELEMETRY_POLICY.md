# Política de Telemetria — AIVisions Phoenix Engine

## 1. Status padrão: desativada / opt-in

A telemetria remota é **desativada por padrão**. A Phoenix sempre coleta telemetria *local* de hardware (necessária para provisionamento e diagnóstico), mas o envio dessa telemetria para os servidores da AIVisionsLab (Firestore) exige ativação explícita pelo usuário.

## 2. O que é coletado localmente (sempre)

- CPU: modelo, núcleos, uso
- GPU: modelo, VRAM, uso, temperatura
- RAM: total e uso
- Armazenamento: espaço disponível
- Containers: estado (ativo/parado)
- Logs operacionais da Phoenix

Esses dados alimentam o dashboard local e o Resident Manager — nunca saem do seu sistema, a menos que o opt-in de telemetria remota esteja ativo.

## 3. O que é enviado, se o usuário optar por compartilhar

Se ativada, a telemetria remota envia um subconjunto agregado e anonimizado dos dados acima (hardware, versão do sistema, métricas de desempenho), **sem** prompts, documentos, imagens ou qualquer conteúdo gerado.

## 4. Por que compartilhar telemetria

O objetivo declarado é aprimorar a compatibilidade da Phoenix com diferentes configurações de hardware (por exemplo, otimizar estratégias de split GPU/CPU) em versões futuras.

## 5. Como ativar ou desativar

O compartilhamento de telemetria é controlado por duas rotas dedicadas do Phoenix Engine
(`POST /api/telemetry/consent/accept` e `POST /api/telemetry/consent/decline`), sem impacto na
funcionalidade principal do software caso esteja desligado — que é o estado padrão de qualquer
instalação nova.

> **Nota de status (2026-08-28):** essas rotas funcionam, mas ainda não há um botão/toggle
> dedicado nas interfaces (Aviary ou Mission Control) que as chame — hoje só são acionáveis via
> chamada direta à API. Na prática isso significa que a telemetria remota permanece desligada por
> padrão e nenhuma instalação comum a liga sozinha (nada no instalador nem no código a ativa
> automaticamente), mas também que um usuário que queira ativá-la ainda não encontra essa opção
> dentro do aplicativo — só via API direta. Conectar essas rotas a um controle visível nas
> configurações é trabalho pendente.

## 6. Transparência

Toda comunicação remota da Phoenix relacionada a telemetria é logada localmente e pode ser auditada pelo usuário.
