# Phoenix Capability V4 — integração concluída

## Arquitetura
- `commercial_guard.py` é a autoridade comercial local.
- `capability_client.py` negocia challenge-response com o servidor.
- `capability_protocol.py` valida assinatura Ed25519, expiração, nonce e machine binding.
- `plans.py` mantém a interface antiga `get_rag_limits()`, mas lê a Capability V4.
- `entitlements.py` virou fachada de compatibilidade; `entitlement.json` local não libera Pro.
- `rag_consensus.py` continua 4/4, agora com `authorization + registry + ledger + manifest`.
- `rag_integrity_manifest.py` V2 não prende o manifesto ao plano. Mudança legítima Free/Pro não quebra o RAG.
- `chroma_rag_backend.py` continua aplicando limites também no backend direto.
- removida validação duplicada de limites no `add_document_chunked()`.
- API ganhou `/api/licensing/status` e `/api/licensing/refresh`.

## Segurança
A chave privada Ed25519 NÃO está neste patch e nunca deve ir para o cliente.
Uma instalação sem servidor, sem token ou com token inválido permanece FREE.

## Antes de sobrescrever
Faça backup do projeto.

## Instalação
Extraia este ZIP sobre a raiz do Phoenix preservando as pastas.

## Configuração
Cliente:
- `PHOENIX_LICENSE_SERVER_URL=https://...`
- `PHOENIX_LICENSE_ID=...` ou `data/license_id.txt`
- `config/phoenix_capability_public_key.pem`

HTTP só é aceito para localhost durante desenvolvimento.

## Compatibilidade
Endpoints e campos antigos de limites foram preservados.
Os nomes `entitlement_valid` / `entitlement_reason` continuam na API para não quebrar UI antiga,
mas agora refletem a capability.

## Teste recomendado
1. Sem licença: `/api/rag/limits` => Free, 10 docs, 25 MB.
2. Token adulterado: continua Free.
3. Token de outra máquina: continua Free.
4. Token expirado: continua Free.
5. Capability Pro com `rag.pro`: Pro, 100 MB, sem teto artificial de documentos.
6. Remover `rag.pro` mesmo com `plan=pro`: volta a Free.
