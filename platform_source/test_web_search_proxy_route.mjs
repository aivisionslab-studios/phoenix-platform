// test_web_search_proxy_route.mjs
//
// Teste de integração real (sobe o dist/server.cjs de verdade, igual
// test_server_json_error_handling.mjs ao lado) pra nova rota
// POST /api/web-search em server.ts - a ponte que faltava entre o chat
// normal da Aviary e o search_web() (SearXNG) real do Phoenix Engine (ver
// test_web_search_route.py pro lado Python, e test_web_search_intent.mjs
// pra detecção de intenção no frontend).
//
// Sobe um Phoenix Engine FALSO (Express mínimo) na porta 8000 pra provar
// que o proxy de fato encaminha query/max_results e devolve o corpo real,
// e testa o caso de erro (engine fora do ar) devolvendo JSON de erro real,
// nunca um "ok:true" fabricado.
//
// Rodar: cd platform_source && npm run build && node test_web_search_proxy_route.mjs

import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";

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
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => handler(req, res, body));
  });
  return new Promise((resolve) => server.listen(FAKE_ENGINE_PORT, () => resolve(server)));
}

async function main() {
  // --- Caso 1: Phoenix Engine (fake) responde com sucesso real ---
  let lastReceivedBody = null;
  const fakeEngineOk = await startFakeEngine((req, res, body) => {
    if (req.url === "/api/web-search" && req.method === "POST") {
      lastReceivedBody = JSON.parse(body);
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true, query: lastReceivedBody.query, results: "- Resultado real A\n- Resultado real B" }));
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
    const r1 = await fetch(`http://localhost:${AVIARY_PORT}/api/web-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "acidente com 2 helicópteros no rj em 2026", max_results: 5 }),
    });
    const data1 = await r1.json();
    check("status 200 quando o Phoenix Engine responde com sucesso", r1.status === 200);
    check("corpo repassado de verdade (contém 'Resultado real A')", (data1.results || "").includes("Resultado real A"));
    check("query real chegou no Phoenix Engine (não vazia/adulterada)", lastReceivedBody?.query === "acidente com 2 helicópteros no rj em 2026");
    check("max_results real chegou no Phoenix Engine", lastReceivedBody?.max_results === 5);

    // --- Caso 2: query vazia é rejeitada ANTES de chamar o Phoenix Engine ---
    const r2 = await fetch(`http://localhost:${AVIARY_PORT}/api/web-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "   " }),
    });
    check("query vazia -> 400 (nunca chega a chamar o Engine)", r2.status === 400);

    fakeEngineOk.close();
    await sleep(200);

    // --- Caso 3: Phoenix Engine fora do ar -> erro real, nunca sucesso fabricado ---
    const r3 = await fetch(`http://localhost:${AVIARY_PORT}/api/web-search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: "teste com engine offline" }),
    });
    const data3 = await r3.json().catch(() => null);
    check("Engine offline -> status de erro real (nunca 200 com ok:true fabricado)", r3.status >= 500);
    check("corpo de erro é JSON com campo 'error'", !!(data3 && data3.error));
  } finally {
    child.kill();
  }

  console.log(`\n${passed} passaram, ${failed} falharam.`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
