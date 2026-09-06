# Phoenix — Universal Document Transform

Arquivos alterados:
- api_server.py
- phoenix_kernel/resident/resident_manager.py
- phoenix_kernel/documents/engine.py
- phoenix_kernel/paths.py
- platform_source/server.ts
- platform_source/src/components/aviary/AviaryApp.tsx
- platform_source/src/components/aviary/ChatView.tsx
- platform_source/src/types.ts

Capacidades:
- criar PDF/DOCX/XLSX/PPTX/MD/TXT do zero;
- usar PDF/DOCX/XLSX/PPTX/MD/TXT como documento-base;
- transformar qualquer formato suportado em qualquer outro;
- pesquisar na web dentro do mesmo pedido documental;
- materializar arquivos em Outputs/Documents/Created|Transformed|Edited;
- entregar download no chat usando downloadFile já existente;
- PDF deixa de ser proibido como formato de saída;
- validação real do arquivo gerado por reabertura.

A regra de honestidade permanece: reconstruir um documento gera um NOVO arquivo e não promete preservar layout pixel-perfect do original.


## CORREÇÃO V2 — caminho real do ResidentManager

O projeto real instancia:
`phoenix_kernel/resident/resident_manager.py`

O pacote V1 colocou esse arquivo incorretamente em:
`phoenix_kernel/resident_manager.py`

Isso fazia `/api/documents/create` existir, mas o objeto carregado pelo Kernel continuar
sem `create_document_direct()`, produzindo:
`'ResidentManager' object has no attribute 'create_document_direct'`.

Ao aplicar este V2:
1. substitua `phoenix_kernel/resident/resident_manager.py`;
2. se o V1 criou `phoenix_kernel/resident_manager.py`, apague esse arquivo órfão.


## V3 — qualidade documental e truncamento

- Corrigido PDF com linhas sobrepostas (bug de split de newline no gerador).
- Document Composer agora usa max_tokens=4096 (o driver llama.cpp usa 1024 por padrão).
- O LLM selecionado na Aviary é enviado como model_hint para criação/transformação de documentos.
- DOCX interpreta headings, listas e tabelas Markdown em estrutura Word real.
- XLSX ignora separadores Markdown, limpa marcação e ajusta cabeçalhos/larguras.
- Pesquisa web documental separa o assunto da instrução de materialização e exige não inventar dados ausentes.
- Saída deve completar todas as seções e não terminar no meio de frase.

Testes locais do Document Engine V3: PDF/DOCX/XLSX/PPTX/MD/TXT materializados e reabertos; PDF e DOCX renderizados visualmente sem sobreposição.
