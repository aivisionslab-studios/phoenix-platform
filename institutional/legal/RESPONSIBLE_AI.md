# Uso Responsável de IA — AIVisions Phoenix Engine

## 1. Filosofia

A Phoenix é uma ferramenta de orquestração, não um agente de decisão autônomo com autoridade final. Toda ação com impacto significativo passa por um fluxo de aprovação humana (ver [RESIDENT_MANAGER.md](../docs/RESIDENT_MANAGER.md)).

## 2. Limitações declaradas

A Phoenix, e os modelos de IA que ela orquestra:

- **Não tomam decisões jurídicas** vinculantes;
- **Não substituem diagnóstico médico** ou aconselhamento de saúde;
- **Não substituem engenheiros** responsáveis técnicos em projetos críticos;
- **Não garantem precisão** factual das saídas geradas por modelos de terceiros.

A Phoenix é, e deve ser tratada como, **uma ferramenta de apoio**, não uma autoridade decisória.

## 3. Neutralidade

A Phoenix, como orquestrador, não impõe agenda política ou ideológica, não censura conteúdo arbitrariamente, e permite o uso de modelos locais escolhidos pelo usuário. A responsabilidade pelo comportamento e viés de cada modelo é do respectivo criador/distribuidor do modelo, não da Phoenix.

## 4. Transparência sobre automação

O Resident Manager distingue explicitamente entre:
- **Decisões automáticas** (baixo risco, pré-aprovadas por regra);
- **Decisões assistidas** (sugeridas pela IA, aguardando confirmação);
- **Decisões manuais** (exigem aprovação explícita do usuário via comando `aprovar`/`rejeitar`).

Essa distinção fica registrada em log, permitindo auditoria posterior de quais ações foram automáticas e quais tiveram intervenção humana.

## 5. Responsabilidade do usuário final

O usuário é responsável pelo uso ético e legal dos modelos de IA executados através da Phoenix, incluindo conteúdo gerado, decisões tomadas com base nas saídas do sistema, e conformidade com leis locais aplicáveis a sistemas de IA.
