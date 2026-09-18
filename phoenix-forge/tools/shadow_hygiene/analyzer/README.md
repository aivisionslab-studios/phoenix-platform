# Phoenix Shadow Tree Deep Analyzer V2

Próxima fase após o V1 ter encontrado divergência real.

Ele:
- compara SHA-256 e conteúdo;
- calcula similaridade textual;
- para Python, compara AST sem atributos de posição;
- compara funções/classes/imports/constantes;
- gera preview de unified diff;
- localiza evidência exata das referências externas;
- classifica cada shadow file sem mover nada.

Saídas:
- PHOENIX_SHADOW_DEEP_SUMMARY.json
- PHOENIX_SHADOW_DEEP_FILE_ANALYSIS.json
- PHOENIX_SHADOW_EXTERNAL_REFERENCE_EVIDENCE.json
- PHOENIX_SHADOW_DEEP_REPORT.md

Nenhum DELETE/MOVE/EDIT é executado.
