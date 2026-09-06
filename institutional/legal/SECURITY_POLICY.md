# Política de Segurança — AIVisions Phoenix Engine

## 1. Reportando vulnerabilidades

Se você identificar uma vulnerabilidade de segurança na Phoenix Engine, reporte de forma responsável antes de divulgar publicamente:

- **Canal:** [issues do repositório oficial](https://github.com/aivisionslab-studios/phoenix-engine/issues) (marcar como reporte sensível/privado quando o GitHub permitir) ou security advisory do repositório
- **Informações úteis:** versão da Phoenix, sistema operacional (Windows 10/11 ou distro Linux), hardware (CPU/GPU), passos para reprodução, impacto estimado

## 2. Tempo de resposta

O objetivo é confirmar o recebimento do reporte e iniciar triagem dentro de um prazo razoável. Como projeto mantido majoritariamente por um núcleo pequeno (AIVisionsLab Studio Group), prazos formais de SLA ainda não são garantidos (ver [DISCLAIMER.md](./DISCLAIMER.md)).

## 3. Versões suportadas

Correções de segurança são priorizadas para a versão estável mais recente do repositório [`phoenix-engine`](https://github.com/aivisionslab-studios/phoenix-engine). Versões antigas podem não receber patches retroativos.

## 4. Divulgação responsável

Pede-se que vulnerabilidades não sejam divulgadas publicamente antes de uma correção estar disponível, para proteger usuários que executam a Phoenix em produção ou em ambientes sensíveis.

## 5. Escopo

Esta política cobre o código da própria Phoenix (`phoenix_kernel/`, `api_server.py`, scripts de instalação em `install/`). Vulnerabilidades em tecnologias de terceiros integradas (Docker, llama.cpp, LibreHardwareMonitor etc.) devem ser reportadas diretamente aos respectivos projetos.
