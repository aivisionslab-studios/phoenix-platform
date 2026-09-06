# Resident Manager — AIVisions Phoenix Engine

O Resident Manager (`phoenix_kernel/resident/`) é um dos principais diferenciais da Phoenix: um agente residente que observa o ambiente, propõe ações e executa fluxos completos, sempre respeitando limites definidos pelo usuário.

## Ciclo de decisão

```
Intent → Research → Decision → Approval → Execute
```

1. **Intent** — o usuário (ou uma missão do App Store) expressa uma intenção (ex.: "quero rodar geração de imagem nesta máquina").
2. **Research** — o Resident investiga o ambiente: hardware detectado, modelos já instalados, containers existentes, evitando downloads ou instalações desnecessárias.
3. **Decision** — com base na pesquisa, o Resident constrói um plano de ação, coordenando-se com o Planner.
4. **Approval** — ações classificadas como potencialmente destrutivas ou de alto impacto aguardam aprovação explícita do usuário.
5. **Execute** — após aprovação (ou automaticamente, para ações de baixo risco pré-classificadas), a ação é executada pelo Runtime.

## Interface

O agente é acessado via **Terminal Deck** do dashboard Mission Control (`phoenix> infer <pergunta>`, `phoenix> ocr <caminho>`, `phoenix> search <busca>`) e pela API (`POST /api/command`, dispatcher em `phoenix_kernel/api/engine.py`).

## Limites que o Resident respeita

- Não executa ações destrutivas sem aprovação explícita;
- Não sobrescreve configurações do usuário sem confirmação;
- Registra em log toda decisão (motor de eventos em `phoenix_kernel/logs/`, comando `logs`);
- Segue as regras de segurança definidas em `phoenix_kernel/security/`.

## Integração com Planner e Runtime

O Resident não executa ações diretamente — ele delega ao **Planner** a construção do plano detalhado, e ao **Runtime** a execução efetiva, mantendo a separação de responsabilidades da arquitetura modular da Phoenix.
