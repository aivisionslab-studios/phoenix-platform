# Phoenix Forge 0.11.0 — Runtime Guard

## Integração real

A v0.11.0 conecta o Delivery Guard aos protocolos usados pela Phoenix Engine e Aviary:

- chat: API OpenAI-compatible do llama.cpp em `/v1/chat/completions`;
- imagem: API Stable Diffusion WebUI em `/sdapi/v1/txt2img`;
- qualidade: TrOCR, MiniCPM-V ou serviços compatíveis;
- segurança: GPU Health Ledger por placa, workload, backend, runtime e modelo.

Na instalação atual, o llama-server CPU está em `127.0.0.1:8081`. O padrão da v0.11.0 usa essa porta como controle CPU e reserva `8082` para uma eventual instância GPU separada. Para imagem, a GPU continua em `7860` e o controle CPU pode ser exposto em `7861`.

## Chat protegido

```powershell
.\.venv\Scripts\phoenix-forge.exe guarded-chat "Explique o estado da máquina." `
  --cpu-url "http://127.0.0.1:8081/v1" `
  --gpu-url "http://127.0.0.1:8082/v1" `
  --model "qwen3:8b" `
  --device-name "AMD Radeon RX 580 2048SP"
```

Como o ledger dessa RX 580 restringe LLM, o endpoint GPU não é chamado. A requisição vai diretamente ao servidor CPU.

## Imagem protegida

```powershell
.\.venv\Scripts\phoenix-forge.exe guarded-image "A phoenix rising from volcanic ashes" `
  --gpu-url "http://127.0.0.1:7860" `
  --cpu-url "http://127.0.0.1:7861" `
  --model "sd15" `
  --vision-url "http://127.0.0.1:8092" `
  --ocr-url "http://127.0.0.1:8091"
```

A saída é gravada no diretório de quarentena do estado Phoenix. Somente o caminho presente em `output` com `deliver: true` pode ser encaminhado ao usuário.

## API da Engine/Aviary

- `POST /api/runtime/guarded-chat`
- `POST /api/runtime/guarded-image`
- `POST /api/output/delivery-guard`
- `GET /api/route`

O endpoint de rota agora recebe também `backend`, `runtime` e `model`. Um bloqueio de `sd15` não bloqueia automaticamente `sdxl`, e uma falha do llama.cpp não condena a geração de imagens.

## Limite de rede

Por padrão, os adaptadores aceitam somente `localhost`, `127.0.0.1` e `::1`. Uma integração remota exige autorização explícita:

```powershell
$env:PHOENIX_ALLOW_REMOTE_RUNTIME="1"
```

Não habilite essa opção para endpoints não confiáveis, pois prompts e documentos podem conter dados privados.
