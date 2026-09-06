// test_chat_headers_timeout.mjs
//
// Teste pro achado real do usuário 2026-08-24: perguntou algo amplo
// ("é possível rodar ia local com hardware legado?...") e recebeu "Falha ao
// obter resposta do modelo. Proxy request failed: fetch failed (causa:
// Headers Timeout Error)". Investigação encontrou que /api/proxy/chat era a
// ÚNICA rota deste arquivo (de todas as que fazem fetch() de longa duração
// pro Phoenix Engine/llama-server) que nunca tinha ganho `dispatcher` nem
// `AbortController` na varredura de 2026-08-21/22 que corrigiu esse mesmo
// bug (UND_ERR_HEADERS_TIMEOUT - undici derruba a conexão sozinho depois de
// 300s por padrão, TOTALMENTE independente de qualquer timeout do nosso
// próprio código) em outras 7 rotas. Como o payload do chat manda
// `stream: false`, o llama-server não manda nenhum byte até terminar de
// gerar a resposta INTEIRA - uma resposta longa (o usuário pediu "as mais
// longas e coerentes", e a v54 aumentou o contexto de 8192 pra 16384) em CPU
// pura (~4.6 tok/s medido de verdade nesta máquina) passa fácil dos 300s.
//
// Corrigido: dispatcher próprio (longRunningDispatcher, já usado em outras 7
// rotas) + AbortController dinâmico escalado por `maxTokens` do pedido
// (mesmo método do timeout do Kokoro TTS) adicionados ao fetch() de
// /api/proxy/chat - ver PHX-FIX completo em server.ts.
//
// Três partes:
//   1. Fórmula/fiação (rápido): extrai as constantes reais do código-fonte,
//      confere o cálculo do timeout, confere que o dispatcher e o
//      AbortController estão de fato conectados ao fetch() da rota, e que o
//      teto do longRunningDispatcher tem folga sobre o pior caso do chat E
//      sobre o AbortController do audiolivro (achado adjacente, ver abaixo).
//   2. Integração REAL rápida (poucos segundos, não 300s): reproduz o
//      MESMO mecanismo do bug real, só que com um teto "global" do undici
//      encolhido de propósito pra segundos em vez de 5 minutos (via um
//      processo-wrapper que chama `setGlobalDispatcher` ANTES de carregar
//      dist/server.cjs) - prova que mesmo com um "padrão global" bem curto,
//      o /api/proxy/chat com a correção continua respondendo com sucesso
//      (porque agora passa seu PRÓPRIO dispatcher/signal, que sobrepõe o
//      global), enquanto sem a correção (controle negativo) o mesmo caso
//      falha exatamente como o usuário relatou.
//
// Rodar: cd platform_source && npm run build && node test_chat_headers_timeout.mjs

import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";
import fs from "node:fs";
import { execSync } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SERVER_TS_PATH = path.join(__dirname, "server.ts");
// PORT em server.ts é fixo em 3000 (não lê variável de ambiente) - mesma
// porta usada pelos outros testes .mjs deste diretório (rodam em sequência,
// nunca em paralelo, então não há conflito real).
const AVIARY_PORT = 3000;
const FAKE_LLAMA_PORT = 8091;
let passed = 0;
let failed = 0;

function check(label, cond) {
  if (cond) {
    console.log(`  OK   ${label}`);
    passed++;
  } else {
    console.log(`  FALHOU ${label}`);
    failed++;
  }
}

function extractRouteBlock(source) {
  const start = source.indexOf('app.post("/api/proxy/chat"');
  if (start === -1) throw new Error('rota /api/proxy/chat não encontrada em server.ts');
  // A próxima rota (`app.post(` ou `app.get(`) depois desta marca o fim do bloco.
  const nextRoute = source.indexOf("\n  app.", start + 10);
  return source.slice(start, nextRoute === -1 ? source.length : nextRoute);
}

function extractConst(source, name) {
  const m = source.match(new RegExp(`const ${name}\\s*=\\s*([\\d_]+)\\s*;`));
  if (!m) throw new Error(`Constante ${name} não encontrada em server.ts`);
  return Number(m[1].replace(/_/g, ""));
}

function extractDispatcherCeiling(source) {
  // A definição de longRunningDispatcher usa `headersTimeout: N,` (objeto
  // literal do UndiciAgent), não `const headersTimeout = N;` - extração
  // separada da de extractConst() por causa dessa sintaxe diferente.
  const m = source.match(/const longRunningDispatcher = new UndiciAgent\(\{\s*headersTimeout:\s*([\d_]+)/);
  if (!m) throw new Error("headersTimeout de longRunningDispatcher não encontrado em server.ts");
  return Number(m[1].replace(/_/g, ""));
}

// ---------------------------------------------------------------------
// Parte 1: fórmula + fiação real extraídas do código-fonte
// ---------------------------------------------------------------------
function testFormulaAndWiring() {
  console.log("\n-- Parte 1: fórmula do timeout dinâmico e fiação real --");
  const source = fs.readFileSync(SERVER_TS_PATH, "utf-8");
  const routeBlock = extractRouteBlock(source);

  check("rota /api/proxy/chat passa dispatcher: longRunningDispatcher no fetch()", /dispatcher:\s*longRunningDispatcher/.test(routeBlock));
  check("rota /api/proxy/chat cria um AbortController de verdade", /new AbortController\(\)/.test(routeBlock));
  check("o fetch() da rota usa signal: controller.signal", /signal:\s*controller\.signal/.test(routeBlock));
  check("existe tratamento isAbort -> 504 (distingue timeout de outros erros de rede)", /isAbort[\s\S]{0,200}504/.test(routeBlock));

  const msPerToken = extractConst(source, "CHAT_MS_PER_TOKEN");
  const minMs = extractConst(source, "CHAT_MIN_TIMEOUT_MS");
  const maxMs = extractConst(source, "CHAT_MAX_TIMEOUT_MS");
  const dispatcherCeiling = extractDispatcherCeiling(source);

  // PHX-FIX (2026-09-06, mesma rodada do aumento de contexto 16384->32768 e
  // do checkbox "Sem limite" - maxTokens===0 - em ParametersDrawer.tsx):
  // esta função espelha a lógica REAL de `effectiveMaxTokens` em server.ts,
  // que passou a tratar maxTokens===0 como "sem limite" (orça pelo
  // contexto cheio, 32768) em vez de um número literal (0*300ms=0ms, que
  // tornaria toda resposta "sem limite" abortada em ~60s - o exato bug que
  // o checkbox deveria resolver).
  function computeTimeout(maxTokens) {
    const effective =
      typeof maxTokens === "number" && maxTokens > 0
        ? maxTokens
        : maxTokens === 0
          ? 32768
          : 2048;
    return Math.min(maxMs, Math.max(minMs, effective * msPerToken));
  }

  check("maxTokens ausente (default 2048, mesmo fallback do payload) fica acima do piso", computeTimeout(undefined) > minMs);
  check("maxTokens bem pequeno (50, 50*300ms=15s < piso) usa o piso de 60s", computeTimeout(50) === minMs);
  check("maxTokens default do slider (4096) pede bem mais que o antigo teto global de 300s do undici (prova que a correção muda algo real)", computeTimeout(4096) > 300_000);
  check("maxTokens máximo do slider (32768, ParametersDrawer.tsx) fica ABAIXO do teto do dispatcher compartilhado", computeTimeout(32768) < dispatcherCeiling);
  check("maxTokens===0 ('Sem limite') NÃO usa o piso de 60s - orça pelo contexto cheio (32768), não por zero", computeTimeout(0) > 300_000);
  check("maxTokens===0 ('Sem limite') e maxTokens=32768 (slider no máximo) dão o MESMO timeout (mesmo pior caso: contexto cheio)", computeTimeout(0) === computeTimeout(32768));

  const audiobookAbortMs = 5_520_000; // valor fixo já documentado na rota de audiolivro
  check("teto do dispatcher compartilhado tem folga sobre o MAIOR AbortController que o usa (audiolivro, 92min)", dispatcherCeiling > audiobookAbortMs);
  check("teto do dispatcher compartilhado também tem folga sobre o pior caso do chat (32768 tokens, ou 'Sem limite')", dispatcherCeiling > computeTimeout(32768));
}

// ---------------------------------------------------------------------
// Parte 2: integração real - reproduz o MESMO mecanismo do bug (dispatcher
// global do undici derrubando a conexão antes do timeout da própria rota),
// só que com o "padrão global" encolhido pra segundos via um wrapper que
// roda setGlobalDispatcher() ANTES de carregar dist/server.cjs - assim o
// teste prova o bug/a correção de verdade em segundos, não em 5 minutos.
// ---------------------------------------------------------------------
const WRAPPER_PATH = path.join(__dirname, "_test_chat_timeout_wrapper.cjs");
const GLOBAL_HEADERS_TIMEOUT_MS = 3000; // "padrão global" artificialmente curto só pro teste

function writeWrapper() {
  fs.writeFileSync(
    WRAPPER_PATH,
    `const { Agent, setGlobalDispatcher } = require("undici");
setGlobalDispatcher(new Agent({ headersTimeout: ${GLOBAL_HEADERS_TIMEOUT_MS}, bodyTimeout: ${GLOBAL_HEADERS_TIMEOUT_MS}, connectTimeout: 10000 }));
require("./dist/server.cjs");
`
  );
}

function startFakeLlamaServer(delayMs) {
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", async () => {
      if (req.url === "/v1/chat/completions" && req.method === "POST") {
        await sleep(delayMs);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
          choices: [{ message: { content: "Resposta fake, gerada depois do delay controlado do teste." } }],
          usage: { prompt_tokens: 10, completion_tokens: 20 },
        }));
        return;
      }
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "not found" }));
    });
  });
  return new Promise((resolve) => server.listen(FAKE_LLAMA_PORT, "127.0.0.1", () => resolve(server)));
}

async function startAviaryServer() {
  const child = spawn("node", [WRAPPER_PATH], {
    cwd: __dirname,
    env: { ...process.env, NODE_ENV: "production", PORT: String(AVIARY_PORT) },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let ready = false;
  child.stdout.on("data", (d) => {
    if (d.toString().includes("online at")) ready = true;
  });
  for (let i = 0; i < 50 && !ready; i++) await sleep(100);
  if (!ready) {
    console.error("Servidor Aviary (wrapper) não subiu a tempo.");
    child.kill();
    process.exit(1);
  }
  return child;
}

async function attemptChatWithSlowBackend(delayMs) {
  const engine = await startFakeLlamaServer(delayMs);
  const child = await startAviaryServer();
  try {
    const t0 = Date.now();
    const res = await fetch(`http://localhost:${AVIARY_PORT}/api/proxy/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        providerType: "llama-server",
        baseUrl: `http://127.0.0.1:${FAKE_LLAMA_PORT}/v1`,
        apiKey: "",
        model: "test-model",
        messages: [{ role: "user", content: "pergunta de teste" }],
        temperature: 0.7,
        maxTokens: 512,
        systemInstruction: "",
      }),
    });
    const elapsedMs = Date.now() - t0;
    const data = await res.json().catch(() => null);
    return { status: res.status, elapsedMs, data };
  } finally {
    child.kill();
    engine.close();
    await sleep(300);
  }
}

async function main() {
  testFormulaAndWiring();

  console.log("\n-- Parte 2: integração real (mecanismo do bug reproduzido em segundos) --");
  writeWrapper();
  try {
    // Backend fake demora 5s pra responder - MAIS que o "padrão global"
    // encolhido pra 3s pro teste, mas dentro do dispatcher próprio da rota
    // (longRunningDispatcher, teto real de minutos) e do AbortController
    // dinâmico (maxTokens=512 -> bem acima de 5s).
    const withFix = await attemptChatWithSlowBackend(5000);
    check(
      "com a correção: backend lento (5s) que excede o 'padrão global' encolhido (3s) responde com sucesso (o dispatcher próprio da rota sobrepõe o global)",
      withFix.status === 200 && !!(withFix.data && typeof withFix.data.text === "string" && withFix.data.text.length > 0)
    );
    check("com a correção: de fato esperou o backend (não abortou antes dos ~5s)", withFix.elapsedMs >= 4500);

    // --- Controle negativo: remove dispatcher/signal do fetch() da rota,
    // reproduzindo exatamente o código de ANTES da correção. ---
    console.log("\n-- Controle negativo: revertendo pro fetch() sem dispatcher/AbortController --");
    const original = fs.readFileSync(SERVER_TS_PATH, "utf-8");
    const brokenFetchCall = `const response = await fetch(endpointUrl, { method: "POST", headers, body: JSON.stringify(payload) });`;
    const fixedFetchCallRegex = /const response = await fetch\(endpointUrl, \{[\s\S]*?\} as RequestInit & \{ dispatcher: UndiciAgent \}\);/;
    if (!fixedFetchCallRegex.test(original)) {
      console.error("Controle negativo não pôde ser aplicado - âncora do fetch() corrigido não encontrada no server.ts.");
      process.exit(1);
    }
    const broken = original.replace(fixedFetchCallRegex, brokenFetchCall);
    fs.writeFileSync(SERVER_TS_PATH, broken);

    try {
      execSync("npx esbuild server.ts --bundle --platform=node --format=cjs --packages=external --outfile=dist/server.cjs", { cwd: __dirname, stdio: "pipe" });

      const withoutFix = await attemptChatWithSlowBackend(5000);
      check(
        "controle negativo: SEM dispatcher/AbortController próprios, o MESMO backend lento (5s > 3s do 'padrão global') falha - reproduz o bug real relatado",
        withoutFix.status !== 200 && withoutFix.elapsedMs < 4500
      );
    } finally {
      fs.writeFileSync(SERVER_TS_PATH, original);
      execSync("npx esbuild server.ts --bundle --platform=node --format=cjs --packages=external --outfile=dist/server.cjs", { cwd: __dirname, stdio: "pipe" });
    }

    console.log("\n-- Confirmando que a correção real foi restaurada --");
    const restoredSource = fs.readFileSync(SERVER_TS_PATH, "utf-8");
    check("server.ts restaurado com dispatcher/AbortController de volta na rota /api/proxy/chat", fixedFetchCallRegex.test(restoredSource));
  } finally {
    fs.rmSync(WRAPPER_PATH, { force: true });
  }

  console.log(`\n${passed} passaram, ${failed} falharam.`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  try { fs.rmSync(WRAPPER_PATH, { force: true }); } catch {}
  process.exit(1);
});
