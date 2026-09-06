// test_server_json_error_handling.mjs
//
// PHX-NEW (auditoria 2026-08-20, "Frontend JSON error handling" / Seções
// 10-11): script standalone (mesmo padrão dos test_*.py na raiz do
// projeto Python - não há vitest/jest configurado em platform_source/,
// então este script sobe o server.cjs de verdade, buildado, e bate nele
// com fetch real, igual os scripts standalone do lado Python).
//
// Prova em execução (não só leitura de código) de que:
//   1. Uma rota /api/* sem handler correspondente devolve 404 JSON, nunca
//      o fallback HTML do SPA (causa raiz confirmada do bug relatado:
//      "Unexpected token '<', <!DOCTYPE..." quando o frontend esperava JSON).
//   2. Um corpo JSON maior que o limite de 25MB devolve 413 JSON, nunca a
//      página de erro HTML padrão do Express.
//   3. Um corpo JSON malformado devolve 400 JSON, nunca HTML.
//   4. Rotas normais (API existente, e navegação SPA fora de /api) continuam
//      se comportando exatamente como antes - sem regressão.
//
// Rodar: cd platform_source && npm run build && node test_server_json_error_handling.mjs

import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// PHX-NOTE: server.ts fixa `const PORT = 3000` (não lê process.env.PORT) -
// é o porto Golden Baseline da Aviary Platform (Seção 4), então o teste
// sobe na mesma porta real em vez de tentar sobrescrever via env.
const PORT = 3000;
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

async function main() {
  const serverPath = path.join(__dirname, "dist", "server.cjs");
  const child = spawn("node", [serverPath], {
    cwd: __dirname,
    env: { ...process.env, NODE_ENV: "production", PORT: String(PORT) },
    stdio: ["ignore", "pipe", "pipe"],
  });

  let ready = false;
  child.stdout.on("data", (d) => {
    if (d.toString().includes("online at")) ready = true;
  });
  child.stderr.on("data", () => {});

  for (let i = 0; i < 50 && !ready; i++) await sleep(100);
  if (!ready) {
    console.error("Servidor não subiu a tempo.");
    child.kill();
    process.exit(1);
  }

  const base = `http://localhost:${PORT}`;

  try {
    console.log("== 1. /api/rota-inexistente -> 404 JSON, nunca HTML do SPA ==");
    {
      const r = await fetch(`${base}/api/rota-que-nao-existe-de-jeito-nenhum`);
      const ct = r.headers.get("content-type") || "";
      check("status é 404", r.status === 404);
      check("content-type é application/json", ct.includes("application/json"));
      const data = await r.json().catch(() => null);
      check("corpo é JSON parseável com campo 'error'", !!data && typeof data.error === "string");
    }

    console.log("== 2. corpo JSON > 25MB -> 413 JSON, nunca a página de erro HTML padrão do Express ==");
    {
      const bigPayload = JSON.stringify({ messages: [{ role: "user", content: "X".repeat(26 * 1024 * 1024) }] });
      const r = await fetch(`${base}/api/gemini/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: bigPayload,
      });
      const ct = r.headers.get("content-type") || "";
      check("status é 413", r.status === 413);
      check("content-type é application/json (não text/html)", ct.includes("application/json"));
      const data = await r.json().catch(() => null);
      check("corpo é JSON parseável com campo 'error'", !!data && typeof data.error === "string");
    }

    console.log("== 3. corpo JSON malformado -> 400 JSON ==");
    {
      const r = await fetch(`${base}/api/gemini/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{not valid json",
      });
      const ct = r.headers.get("content-type") || "";
      check("status é 400", r.status === 400);
      check("content-type é application/json", ct.includes("application/json"));
      const data = await r.json().catch(() => null);
      check("corpo é JSON parseável com campo 'error'", !!data && typeof data.error === "string");
    }

    console.log("== 4. regressão: /api/transcribe sem arquivo continua JSON 400 normal ==");
    {
      const r = await fetch(`${base}/api/transcribe`, { method: "POST" });
      const ct = r.headers.get("content-type") || "";
      check("status é 400", r.status === 400);
      check("content-type é application/json", ct.includes("application/json"));
    }

    console.log("== 5. regressão: /api/ping continua respondendo normal (200 JSON) ==");
    {
      const r = await fetch(`${base}/api/ping`);
      check("status é 200", r.status === 200);
      const data = await r.json().catch(() => null);
      check("corpo tem ok:true", !!data && data.ok === true);
    }

    console.log("== 6. regressão: navegação fora de /api continua caindo no SPA (HTML), sem quebrar ==");
    {
      const r = await fetch(`${base}/qualquer/rota/de/frontend`);
      const ct = r.headers.get("content-type") || "";
      check("status é 200", r.status === 200);
      check("content-type é text/html (SPA fallback intacto)", ct.includes("text/html"));
    }
  } finally {
    child.kill();
  }

  console.log(`\n${passed} passaram, ${failed} falharam`);
  process.exit(failed === 0 ? 0 : 1);
}

main();
