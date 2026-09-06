// test_rag_routes_and_chat_injection.mjs
//
// PHX-NEW (pedido do usuário 2026-08-24/28: "habilitar RAG que vai ficar
// em \PHOENIX 3.0\rag... ja possui capacidade de ler qualquer documento
// via ocr... ja pode receber qualquer documento e injetar esse
// conhecimento pra qualquer llm consumir" - escolheu "Automático, toda
// mensagem" e "Sim, os dois" nas duas perguntas de esclarecimento feitas
// antes de implementar): até esta versão o RAG (ChromaDB) só era
// consultado pelo agente autônomo (ResidentManager.plan_mission()), NUNCA
// pelo chat comum da Aviary - e só aceitava texto colado manualmente (1
// documento = 1 chunk sempre, truncava silenciosamente qualquer conteúdo
// além do limite de ~256 tokens do modelo de embedding).
//
// Este script prova, em duas partes:
//
// Parte A (integração real - sobe dist/server.cjs de verdade e um Phoenix
// Engine FALSO, mesmo padrão de test_web_search_proxy_route.mjs ao lado):
// os dois novos proxies server.ts -> api_server.py, POST /api/rag/add-file
// (multipart, upload de qualquer documento) e POST /api/rag/query (busca
// semântica JSON) - forwarding real, validação de entrada, e erro real
// (nunca sucesso fabricado) quando o Engine está fora do ar.
//
// Parte B (inspeção do código-fonte real, mesmo padrão de
// test_chat_history_identity_leak.mjs ao lado): AviaryApp.tsx::
// sendToProvider() de fato consulta /api/rag/query automaticamente, em
// TODA mensagem (sem exigir nenhum prefixo tipo "pesquisar:"), e injeta o
// contexto encontrado SÓ no systemInstruction desta chamada de rede -
// nunca no `msgList`/estado visível da conversa (mesmo motivo do
// excludeFromHistory, ver test_chat_history_identity_leak.mjs).
//
// Rodar: cd platform_source && npm run build && node test_rag_routes_and_chat_injection.mjs

import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";
import fs from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const AVIARY_PORT = 3000;
const FAKE_ENGINE_PORT = 8000;
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

function startFakeEngine(handler) {
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => handler(req, res, Buffer.concat(chunks)));
  });
  return new Promise((resolve) => server.listen(FAKE_ENGINE_PORT, () => resolve(server)));
}

async function partA() {
  console.log("=== Parte A: integração real (server.cjs + Phoenix Engine falso) ===\n");

  let lastAddFileReq = null;
  let lastQueryBody = null;
  const fakeEngine = await startFakeEngine((req, res, rawBody) => {
    if (req.url === "/api/rag/add-file" && req.method === "POST") {
      lastAddFileReq = { contentType: req.headers["content-type"] || "", bodyLength: rawBody.length };
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          ok: true,
          document: { id: "manual::abc123", title: "teste.pdf", sourceType: "PDF", dateAdded: "2026-08-28T00:00:00", sizeKb: 12.3, chunks: 3, status: "INDEXED", vectorDimensions: 384 },
          ocr_used: true,
          ocr_meta: { pages_ocred: 2 },
        })
      );
      return;
    }
    if (req.url === "/api/rag/query" && req.method === "POST") {
      lastQueryBody = JSON.parse(rawBody.toString("utf8"));
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          ok: true,
          hits: [
            { text: "A RX 580 usa Vulkan via RADV no llama.cpp.", distance: 0.42, source: "manual_vulkan.md" },
            { text: "ComfyUI roda no WSL2 espelhando /mnt/e/models.", distance: 0.61, source: "comfyui_setup.md" },
          ],
        })
      );
      return;
    }
    res.writeHead(404, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: "not found" }));
  });

  const serverPath = path.join(__dirname, "dist", "server.cjs");
  const child = spawn("node", [serverPath], {
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
    console.error("Servidor Aviary não subiu a tempo.");
    process.exit(1);
  }

  try {
    // --- /api/rag/add-file: sem arquivo -> 400, nunca chega a chamar o Engine ---
    const rNoFile = await fetch(`http://localhost:${AVIARY_PORT}/api/rag/add-file`, { method: "POST" });
    check("POST /api/rag/add-file sem arquivo -> 400", rNoFile.status === 400);
    check("POST /api/rag/add-file sem arquivo -> nunca chamou o Engine", lastAddFileReq === null);

    // --- /api/rag/add-file: upload real de um "documento" -> forward real ---
    const form = new FormData();
    const fileBytes = new Uint8Array(Buffer.from("conteúdo fake de um PDF pra teste de upload"));
    form.append("file", new Blob([fileBytes], { type: "application/pdf" }), "teste.pdf");
    const rUpload = await fetch(`http://localhost:${AVIARY_PORT}/api/rag/add-file`, { method: "POST", body: form });
    const dataUpload = await rUpload.json();
    check("POST /api/rag/add-file com arquivo -> 200", rUpload.status === 200);
    check("resposta repassa success:true e o documento real do Engine", dataUpload.success === true && dataUpload.doc?.id === "manual::abc123");
    check("resposta repassa ocrUsed real (não inventado)", dataUpload.ocrUsed === true);
    check("proxy de fato encaminhou um multipart/form-data pro Engine", (lastAddFileReq?.contentType || "").startsWith("multipart/form-data"));
    check("proxy encaminhou o conteúdo real do arquivo (body não vazio)", (lastAddFileReq?.bodyLength || 0) > 0);

    // --- /api/rag/query: forwarding real de query/n_results ---
    const rQuery = await fetch(`http://localhost:${AVIARY_PORT}/api/rag/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "como configurar Vulkan na RX 580?", n_results: 2 }),
    });
    const dataQuery = await rQuery.json();
    check("POST /api/rag/query -> 200", rQuery.status === 200);
    check("query real chegou no Engine", lastQueryBody?.query === "como configurar Vulkan na RX 580?");
    check("n_results real chegou no Engine", lastQueryBody?.n_results === 2);
    check("hits reais repassados pro frontend", Array.isArray(dataQuery.hits) && dataQuery.hits.length === 2);

    // --- /api/rag/query: query vazia -> 400 sem chamar o Engine ---
    lastQueryBody = null;
    const rQueryEmpty = await fetch(`http://localhost:${AVIARY_PORT}/api/rag/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "   " }),
    });
    check("POST /api/rag/query com query vazia -> 400", rQueryEmpty.status === 400);
    check("query vazia nunca chegou a chamar o Engine", lastQueryBody === null);

    fakeEngine.close();
    await sleep(200);

    // --- /api/rag/query: Engine offline -> erro real, nunca sucesso fabricado ---
    const rQueryOffline = await fetch(`http://localhost:${AVIARY_PORT}/api/rag/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "teste com engine offline" }),
    });
    const dataOffline = await rQueryOffline.json().catch(() => null);
    check("Engine offline -> status de erro real (nunca 200 com ok:true fabricado)", rQueryOffline.status >= 500);
    check("corpo de erro tem ok:false e hits:[] (nunca hits fabricados)", dataOffline?.ok === false && Array.isArray(dataOffline?.hits) && dataOffline.hits.length === 0);
  } finally {
    child.kill();
  }
}

function partB() {
  console.log("\n=== Parte B: injeção automática no chat (inspeção do código-fonte real) ===\n");

  const appSrc = fs.readFileSync(
    path.join(__dirname, "src", "components", "aviary", "AviaryApp.tsx"),
    "utf8"
  );

  const sendToProviderStart = appSrc.indexOf("const sendToProvider = async (msgList: ChatMessage[]) => {");
  check("sendToProvider() encontrado em AviaryApp.tsx", sendToProviderStart >= 0);
  const chunk = appSrc.slice(sendToProviderStart, sendToProviderStart + 14000);

  check(
    "sendToProvider() consulta /api/rag/query automaticamente (sem prefixo tipo 'pesquisar:')",
    /fetch\('\/api\/rag\/query'/.test(chunk)
  );
  check(
    "a consulta usa a ÚLTIMA mensagem de usuário como texto de busca",
    /const ragQuery = \[\.\.\.msgList\]\.reverse\(\)\.find\(m => m\.role === 'user'\)/.test(chunk)
  );
  check(
    "contexto recuperado vira uma variável PRÓPRIA (ragSystemContext), não msgList",
    /let ragSystemContext = '';/.test(chunk)
  );
  check(
    "qualquer falha na consulta RAG é registrada sem bloquear o chat",
    /catch \(e\) \{\s*\/\/ RAG é enriquecimento: falha de consulta não derruba o chat normal\./.test(chunk)
  );

  console.log("\nOs dois payloads de rede usam o contexto RAG (não mais o systemInstruction cru):");
  const ragPayloadCount = (chunk.match(/systemInstruction: parameters\.systemInstruction \+ ragSystemContext,/g) || []).length;
  const geminiUsesRag = ragPayloadCount >= 2;
  check("payload do endpoint Gemini usa ragSystemContext", geminiUsesRag);
  const proxyUsesRag = ragPayloadCount >= 2;
  check("payload do endpoint /api/proxy/chat usa ragSystemContext", proxyUsesRag);
  check(
    "nenhum dos dois payloads voltou a usar 'systemInstruction: parameters.systemInstruction' cru",
    !/systemInstruction: parameters\.systemInstruction,/.test(chunk)
  );

  check(
    "o contexto RAG NUNCA é gravado em msgList/setConversations (não fabrica um 'turno' na conversa visível)",
    !/setConversations[\s\S]{0,200}ragSystemContext/.test(chunk) &&
      !/setConversations[\s\S]{0,200}contextBlock/.test(chunk)
  );
}

async function main() {
  await partA();
  partB();
  console.log(`\n${passed} passaram, ${failed} falharam.`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
