# Phoenix Shadow Tree Verifier V1

Ferramenta read-only para provar se:

`phoenix_project\phoenix_kernel\`

é cópia shadow/legada de:

`phoenix_kernel\`

Ela compara SHA-256 e tamanho de cada arquivo e procura referências externas à shadow tree.

Saídas:
- PHOENIX_SHADOW_TREE_SUMMARY.json
- PHOENIX_SHADOW_TREE_FILE_DIFF.json
- PHOENIX_SHADOW_TREE_EXTERNAL_REFERENCES.json
- PHOENIX_SHADOW_TREE_ASSESSMENT.json
- PHOENIX_SHADOW_TREE_REPORT.md

Classificações:
- HIGH_CONFIDENCE_REDUNDANT_COPY
- DIVERGENT_SHADOW_COPY
- REFERENCED_SHADOW_COMPONENT
- SHADOW_ONLY_COMPONENT

Nenhuma classificação autoriza DELETE.
