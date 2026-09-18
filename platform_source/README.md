# Phoenix Aviary Platform

Frontend + servidor Node/Express da Phoenix (`platform_source/`) — a UI de chat, dashboard
de Engine e Aviary Swarm que fala com o **Phoenix Engine** (`api_server.py`, FastAPI,
porta 8000 por padrão) e, opcionalmente, com provedores de IA em nuvem (Gemini) ou locais
(Ollama, LM Studio, llama-server).

> PHX-FIX (auditoria platform_source 2026-08-20, achado A1): este README ainda era o
> template genérico gerado pelo Google AI Studio ("Run and deploy your AI Studio app",
> instruções pra configurar só `GEMINI_API_KEY` como se o projeto fosse somente um app
> Gemini). Documentação real do Aviary abaixo.

## Arquitetura em duas portas

- **Porta 8000 — Phoenix Engine** (`api_server.py`, fora desta pasta): processo Python/
  FastAPI que fala de verdade com llama.cpp/Ollama/Whisper/Kokoro/Phoenix Diffusion,
  Model Registry, Document Engine, AHDE (hardware discovery) etc.
- **Porta 3000 — Phoenix Aviary Platform** (esta pasta, `platform_source/`): servidor
  Node/Express que serve o frontend React (Vite) e faz proxy das rotas de IA local pro
  Engine na porta 8000, além de falar direto com a API do Gemini quando configurado.

Rodando os dois no modo padrão ("mesma máquina"), o Aviary aponta pra
`http://localhost:8000` sozinho. No modo "split" (Engine numa máquina, Aviary em outra —
ex: Engine numa workstation com GPU, Aviary acessado de um notebook na mesma rede), aponte
`PHOENIX_ENGINE_URL` pro endereço real do Engine (ver abaixo).

## Rodando localmente

**Pré-requisitos:** Node.js 18+, e o Phoenix Engine (`api_server.py`) rodando em algum
lugar acessível (padrão: `http://localhost:8000` na mesma máquina).

1. Instalar dependências:
   ```
   npm install
   ```
2. Copiar `.env.example` para `.env` e ajustar o que for necessário (ver seção
   "Variáveis de ambiente" abaixo — na prática, o padrão já funciona se o Engine estiver
   rodando em `localhost:8000`):
   ```
   cp .env.example .env
   ```
3. Rodar em modo desenvolvimento (hot reload via `tsx`):
   ```
   npm run dev
   ```
   Acesse `http://localhost:3000`.

## Build de produção

```
npm run build   # gera dist/server.cjs (esbuild) + dist/assets/*.js (vite build)
npm start       # roda o build: node dist/server.cjs
```

Outros scripts úteis: `npm run lint` (`tsc --noEmit`, checagem de tipos sem gerar
arquivo), `npm run clean` (remove `dist/`).

## Variáveis de ambiente

Ver `.env.example` para a lista completa e comentada. Resumo:

| Variável | Obrigatória? | Para quê |
|---|---|---|
| `PHOENIX_ENGINE_URL` | Não (padrão `http://localhost:8000`) | Endereço do Phoenix Engine. Só muda em setup "split" (Engine em outra máquina/porta). |
| `GEMINI_API_KEY` | Não | Só necessária se você quiser usar modelos Gemini (nuvem) na aba de provedores. Sem ela, `/api/gemini/chat` devolve erro real e claro — nunca finge sucesso. |
| `NODE_ENV` | Não (padrão `development`) | `production` ao rodar o build (`npm start`). |

## Quando usar qual provedor

- **Phoenix Engine (padrão, local, porta 8000):** motor principal — llama.cpp (Vulkan) ou
  Ollama como segunda opção pra chat/raciocínio, MiniCPM-V pra visão, Document Engine pra
  PDF/DOCX/XLSX/PPTX, Piper/Whisper pra voz. Não precisa de chave nenhuma.
- **Ollama / LM Studio / llama-server (locais, via `/api/proxy/chat`):** use se você já
  tem um desses servidores rodando separadamente e quer apontar o Aviary pra ele em vez do
  Phoenix Engine embutido — útil pra comparar modelos ou rodar em outra máquina da rede
  local.
- **Gemini (nuvem):** use se quiser um modelo de nuvem além dos locais — precisa de
  `GEMINI_API_KEY`. Não é obrigatório pro Aviary funcionar; o Engine local cobre o fluxo
  principal (chat, documentos, imagem, voz, visão) sem depender de rede externa.
