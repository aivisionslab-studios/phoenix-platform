# Phoenix Model Policy

A Phoenix distingue quatro níveis de distribuição:

- **CORE**: baseline seguro, pode ser instalado automaticamente.
- **RECOMMENDED**: bom candidato, instalação por escolha do usuário.
- **LAB**: engine suporta, mas AUTO só deve usar após validação local ou escolha explícita.
- **EXPERIMENTAL**: conhecido por exigir hardware muito maior, ter falha observada ou ainda não possuir validação suficiente. AUTO nunca escolhe.

## Primeiro boot

O conjunto mínimo é deliberadamente pequeno. Texto usa o GGUF nativo do Phoenix Llama Runtime como caminho primário. Ollama é segunda engine opcional e mantém cópia própria apenas quando o usuário decidir usá-lo. Imagem usa SD 1.5 como safe baseline. Modelos de imagem maiores permanecem no Model Hub.

## Autoridades

- `model_distribution.json`: política universal de distribuição.
- `models.json`: roles/capacidades.
- `downloads.json`: downloads ModelManager.
- `assets/*.json`: downloads AssetManager.
- `CompatibilityStore`: aprendizado da máquina local.
- `ExecutionOrchestrator`: decisão de placement/residência.
- `Phoenix Diffusion`: mecânica fina de backend/params/auto-fit de imagem.

Nunca converter uma falha local em regra universal sem evidência. Nunca considerar `supported` como sinônimo de `validated`.
