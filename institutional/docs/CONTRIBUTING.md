# Como Contribuir — AIVisions Phoenix Engine

## Antes de começar

Leia [PHILOSOPHY.md](./PHILOSOPHY.md) para entender os princípios de design do projeto — isso ajuda a alinhar contribuições com a visão da Phoenix antes mesmo de mexer no código.

## Fluxo de contribuição

1. Fork do repositório;
2. Crie uma branch descritiva (`feature/nome-da-feature`, `fix/nome-do-bug`);
3. Siga o padrão de commits do repositório (mensagens claras e objetivas, em português ou inglês);
4. Abra um Pull Request descrevendo o que foi alterado e por quê;
5. Aguarde revisão — mudanças que quebram compatibilidade devem seguir a metodologia de "Errata Evolutiva" (documentar no `CHANGELOG.md`).

## Estilo de código

- Priorize módulos desacoplados, comunicando-se por contratos públicos (ver [ARCHITECTURE_CURRENT.md](./ARCHITECTURE_CURRENT.md));
- Scripts de instalação devem manter a separação por sistema operacional (`windows.ps1` / `linux.ps1` / `common.ps1`);
- Novos modelos devem ser adicionados via catálogo em `catalog/`, não hardcoded no kernel; novas tecnologias integradas via `install/common.ps1` (dicionário `$Repos`).

## Issues e bugs

Use as issues do repositório oficial para reportar bugs (não relacionados a segurança — para vulnerabilidades, ver [SECURITY_POLICY.md](../legal/SECURITY_POLICY.md)) ou sugerir melhorias.

## Código de conduta

Contribuições devem manter um ambiente respeitoso e colaborativo. Comportamento abusivo ou discriminatório não é tolerado.
