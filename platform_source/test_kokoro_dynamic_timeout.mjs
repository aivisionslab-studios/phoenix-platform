// test_kokoro_dynamic_timeout.mjs
//
// Teste pra correção do achado real do usuário 2026-08-24: "investigar
// kokoro como narrador neural dos textos cuspidos pelos modelos... ora
// funcionam e ora nao funcionam" - o timeout do proxy /api/tts/piper em
// server.ts era FIXO em 15s, calibrado só pra texto de tamanho de resposta
// curta. Respostas de chat mais longas (o próprio usuário pediu "as mais
// longas e coerentes" na mesma mensagem) podiam estourar esse timeout fixo
// dependendo do tamanho e da carga da CPU - intermitente por natureza.
//
// Corrigido: o timeout agora escala com o tamanho do texto (30ms/caractere,
// piso de 15s, teto de 120s - ver comentário completo em server.ts).
//
// Duas partes:
//   1. Teste de fórmula (rápido, extrai as constantes reais do código-fonte
//      e confere o cálculo pra alguns tamanhos de texto).
//   2. Teste de integração REAL (sobe o dist/server.cjs de verdade com um
//      Phoenix Engine falso que demora um tempo controlado pra responder) -
//      prova que um texto longo com uma síntese demorada (mais que os 15s
//      antigos, mas dentro do novo timeout calculado) TERMINA COM SUCESSO,
//      em vez de cair no fallback do navegador. Controle negativo: reverte
//      o timeout pro fixo de 15s, confirma que o MESMO caso passa a falhar,
//      restaura, confirma que volta a passar.
//
// Rodar: cd platform_source && npm run build && node test_kokoro_dynamic_timeout.mjs

import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";
import fs from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SERVER_TS_PATH = path.join(__dirname, "server.ts");
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

// ---------------------------------------------------------------------
// Parte 1: fórmula extraída do código-fonte real (não reimplementada à
// mão - se alguém mudar as constantes em server.ts sem atualizar este
// teste, o teste ainda usa os valores REAIS, só confere a matemática do
// clamp em si).
// ---------------------------------------------------------------------
function extractConst(source, name) {
  const m = source.match(new RegExp(`const ${name}\\s*=\\s*(\\d+)\\s*;`));
  if (!m) throw new Error(`Constante ${name} não encontrada em server.ts`);
  return Number(m[1]);
}

function testFormula() {
  console.log("\n-- Parte 1: fórmula do timeout dinâmico --");
  const source = fs.readFileSync(SERVER_TS_PATH, "utf-8");

  check("rota /api/tts/piper ainda existe", source.includes('app.post("/api/tts/piper"'));
  check("timer usa kokoroTimeoutMs (não mais um literal fixo)", /setTimeout\(\(\) => controller\.abort\(\), kokoroTimeoutMs\)/.test(source));

  const msPerChar = extractConst(source, "KOKORO_MS_PER_CHAR");
  const minMs = extractConst(source, "KOKORO_MIN_TIMEOUT_MS");
  const maxMs = extractConst(source, "KOKORO_MAX_TIMEOUT_MS");

  check("piso continua em 15000ms (preserva comportamento já calibrado pra texto curto)", minMs === 15000);
  check("teto é maior que o piso antigo (senão a correção não muda nada)", maxMs > 15000);

  function computeTimeout(len) {
    return Math.min(maxMs, Math.max(minMs, len * msPerChar));
  }

  check("texto curtíssimo (10 chars) usa o piso de 15s", computeTimeout(10) === minMs);
  check("texto de ~400 chars (resposta curta típica) fica perto dos 15s já calibrados manualmente", Math.abs(computeTimeout(400) - 15000) <= 5000);
  check("texto de 1200 chars pede MAIS que os 15s antigos (prova que a escala é real)", computeTimeout(1200) > 15000);
  check("texto enorme (10000 chars) é limitado pelo teto de 120s, não cresce sem limite", computeTimeout(10000) === maxMs);
}

// ---------------------------------------------------------------------
// Parte 2: integração real - sobe dist/server.cjs de verdade
// ---------------------------------------------------------------------
function startFakeEngine(delayMs) {
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", async () => {
      if (req.url === "/api/synthesize-speech" && req.method === "POST") {
        await sleep(delayMs);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, voice: "pf_dora", audio_base64: Buffer.from("fake-wav-bytes").toString("base64"), mime_type: "audio/wav" }));
        return;
      }
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "not found" }));
    });
  });
  return new Promise((resolve) => server.listen(FAKE_ENGINE_PORT, () => resolve(server)));
}

async function startAviaryServer() {
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
    child.kill();
    process.exit(1);
  }
  return child;
}

// Faz a chamada real (sobe engine falso + servidor Aviary, faz o POST) e
// devolve os fatos observados, SEM afirmar nada - quem chama decide o que
// esperar (o mesmo caso deve ter sucesso com a correção e falhar sem ela,
// então as asserções variam por chamador, não fazem sentido fixas aqui).
async function attemptLongTextSynthesis() {
  // Texto de 1200 caracteres -> timeout calculado = 1200*30 = 36000ms.
  // Engine falso demora 17s pra responder - MAIS que o antigo timeout fixo
  // de 15s, mas BEM dentro dos 36s do novo cálculo.
  const longText = "Detalhe relevante sobre o assunto pesquisado. ".repeat(26); // ~1200 chars
  const engine = await startFakeEngine(17000);
  const child = await startAviaryServer();
  try {
    const t0 = Date.now();
    const res = await fetch(`http://localhost:${AVIARY_PORT}/api/tts/piper`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: longText, voice: "" }),
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
  testFormula();

  console.log("\n-- Parte 2: integração real (proxy + engine falso lento) --");
  const withFix = await attemptLongTextSynthesis();
  check("com a correção: texto longo com síntese de 17s (> 15s antigo) responde com sucesso real (status 200)", withFix.status === 200);
  check("com a correção: engine reportado é o Kokoro real, não o fallback do navegador", !!(withFix.data && typeof withFix.data.engine === "string" && withFix.data.engine.includes("Kokoro")));
  check("com a correção: de fato esperou pela síntese real (não abortou antes dos ~17s)", withFix.elapsedMs >= 16000);

  // --- Controle negativo: reverte pro timeout fixo antigo (15000ms) ---
  console.log("\n-- Controle negativo: revertendo pro timeout fixo de 15s --");
  const original = fs.readFileSync(SERVER_TS_PATH, "utf-8");
  const broken = original.replace(
    "const timer = setTimeout(() => controller.abort(), kokoroTimeoutMs);",
    "const timer = setTimeout(() => controller.abort(), 15000);"
  );
  if (broken === original) {
    console.error("Controle negativo não pôde ser aplicado - âncora não encontrada no server.ts.");
    process.exit(1);
  }
  fs.writeFileSync(SERVER_TS_PATH, broken);

  try {
    const { execSync } = await import("node:child_process");
    execSync("npx esbuild server.ts --bundle --platform=node --format=cjs --packages=external --outfile=dist/server.cjs", { cwd: __dirname, stdio: "pipe" });

    const withoutFix = await attemptLongTextSynthesis();
    check(
      "controle negativo: com o timeout fixo de 15s, o MESMO caso (síntese de 17s) falha (não retorna 200 com Kokoro real, abortou antes)",
      withoutFix.status !== 200 && withoutFix.elapsedMs < 16000
    );
  } finally {
    fs.writeFileSync(SERVER_TS_PATH, original);
    const { execSync } = await import("node:child_process");
    execSync("npx esbuild server.ts --bundle --platform=node --format=cjs --packages=external --outfile=dist/server.cjs", { cwd: __dirname, stdio: "pipe" });
  }

  console.log("\n-- Confirmando que a correção real foi restaurada --");
  const restoredSource = fs.readFileSync(SERVER_TS_PATH, "utf-8");
  check("server.ts restaurado com kokoroTimeoutMs de volta", restoredSource.includes("setTimeout(() => controller.abort(), kokoroTimeoutMs)"));

  console.log(`\n${passed} passaram, ${failed} falharam.`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
