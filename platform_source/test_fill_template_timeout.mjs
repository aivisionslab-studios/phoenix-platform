// test_fill_template_timeout.mjs
//
// Teste pra correção do achado real do usuário 2026-08-28: depois que
// phoenix_kernel/resident/resident_manager.py passou a dividir o
// documento-fonte em pedaços (fix de truncamento silencioso - ver
// TESTS/test_fill_spreadsheet_template_chunking.py do lado Python), o
// mesmo request de /api/documents/fill-template passou a fazer várias
// chamadas SEQUENCIAIS ao modelo em vez de uma só (o documento real que
// motivou a correção precisa de 21 pedaços). O proxy Node em server.ts
// herdava o teto de 31min calculado pra UMA chamada só - o usuário
// reproduziu na prática: "Falha ao preencher a planilha a partir do
// documento-fonte. Tempo esgotado esperando o preenchimento da planilha
// (31min)." mesmo com o Phoenix Engine ainda processando pedaços
// normalmente por trás.
//
// Corrigido: o timer do AbortController da rota fill-template agora usa
// a constante nomeada FILL_TEMPLATE_TIMEOUT_MS = 5_400_000 (90min) em vez
// do literal antigo de 1_860_000 (31min) - a mesma ordem de grandeza já
// usada em produção pro audiolivro (AUDIOBOOK_TOTAL_TIME_BUDGET_SECONDS =
// 5400s = 90min), outra tarefa sabidamente longa. Na época deste fix, o
// teto de /api/documents/create (rota IRMÃ, que não sofre chunking) foi
// deliberadamente MANTIDO em 31min - só fill-template precisava mudar.
//
// PHX-FIX (rodada seguinte, pedido explícito do usuário testando Gemma 4
// 12B): /api/documents/create acabou ganhando seu PRÓPRIO motivo real pra
// mudar (não relacionado a chunking) - llama-server sem streaming +
// modelo grande gerando relatório longo em CPU passava dos 31min sem
// estar travado. Foi pra 3_660_000 (61min), acompanhando o novo
// DOCUMENT_CREATE_TIMEOUT_LARGE_SECONDS=3600s do Resident. As checagens
// da Parte 1 abaixo já refletem esse valor novo - os dois tetos (fill-
// template e create) continuam INDEPENDENTES um do outro, só aconteceu
// de os dois precisarem crescer, em momentos e por motivos diferentes.
//
// Duas partes:
//   1. Teste de código-fonte (rápido) - confere as constantes reais.
//   2. Teste de integração REAL, em escala reduzida - prova que é a
//      constante FILL_TEMPLATE_TIMEOUT_MS (não outro número solto) que de
//      fato governa o abort, temporariamente reduzindo seu valor pra um
//      teste rápido (não dá pra esperar 90min de verdade num teste).
//
// Rodar: cd platform_source && npm run build && node test_fill_template_timeout.mjs

import { setTimeout as sleep } from "node:timers/promises";
import { spawn, execSync } from "node:child_process";
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
// Parte 1: código-fonte real
// ---------------------------------------------------------------------
function testSource() {
  console.log("\n-- Parte 1: constantes reais em server.ts --");
  const source = fs.readFileSync(SERVER_TS_PATH, "utf-8");

  check("rota /api/documents/fill-template ainda existe", source.includes('"/api/documents/fill-template"'));

  const fillTemplateBlockStart = source.indexOf('"/api/documents/fill-template"');
  const createBlockStart = source.indexOf('app.post("/api/documents/create"');
  const nextRouteAfterFillTemplate = source.indexOf("app.post(", source.indexOf("app.post(\n    \"/api/documents/fill-template\"") + 50);

  const m = source.match(/const FILL_TEMPLATE_TIMEOUT_MS\s*=\s*([\d_]+)\s*;/);
  check("constante FILL_TEMPLATE_TIMEOUT_MS existe", !!m);
  const fillTemplateMs = m ? Number(m[1].replace(/_/g, "")) : 0;

  check("FILL_TEMPLATE_TIMEOUT_MS = 5.400.000ms (90min)", fillTemplateMs === 5_400_000);
  check("90min é maior que o antigo teto de 31min (senão a correção não muda nada)", fillTemplateMs > 1_860_000);

  check(
    "a declaração da constante fica DEPOIS do início da rota fill-template (escopo certo, não vazou pra outra rota)",
    m && m.index > fillTemplateBlockStart,
  );
  if (nextRouteAfterFillTemplate > -1) {
    check(
      "a declaração da constante fica ANTES da próxima rota (não é a rota errada)",
      m && m.index < nextRouteAfterFillTemplate,
    );
  }

  check(
    "o timer da rota fill-template usa a constante nomeada (não mais o literal 1_860_000)",
    /setTimeout\(\(\) => controller\.abort\(\), FILL_TEMPLATE_TIMEOUT_MS\)/.test(source),
  );

  // PHX-FIX (pedido explícito do usuário 2026-08-28, testando Gemma 4 12B
  // com relatório longo via pesquisa web + PDF): esta rota IRMÃ não fazia
  // parte do bug de CHUNKING (não sofre chunking, nunca precisou), mas
  // tinha seu PRÓPRIO problema real e independente - o llama-server não
  // faz streaming, então um modelo grande gerando um documento longo em
  // CPU pode legitimamente passar dos 31min que este teto tinha. Foi pra
  // 61min (Resident LARGE=3600s + margem) nesta rodada - por isso as
  // checagens abaixo esperam o valor NOVO, não mais "continua igual".
  check("/api/documents/create existe e agora usa o teto novo de 3_660_000ms (61min)", createBlockStart > -1);
  const createSlice = source.slice(createBlockStart, createBlockStart + 2500);
  check(
    "o timer de /api/documents/create usa o literal 3_660_000 (61min, subiu junto com o Resident/driver)",
    /setTimeout\(\(\) => controller\.abort\(\), 3_660_000\)/.test(createSlice),
  );
  check(
    "a mensagem de erro de /api/documents/create agora diz 61min (não mente mais sobre quanto tempo esperou)",
    createSlice.includes("criação/transformação do documento (61min)"),
  );
  check(
    "o literal antigo de 31min (1_860_000) não sobrou solto na rota /api/documents/create",
    !/setTimeout\(\(\) => controller\.abort\(\), 1_860_000\)/.test(createSlice),
  );

  check(
    "a mensagem de erro de fill-template agora diz 90min (não mente mais sobre quanto tempo esperou)",
    source.includes("Tempo esgotado esperando o preenchimento da planilha (90min)"),
  );
}

// ---------------------------------------------------------------------
// Parte 2: integração real, em escala reduzida
// ---------------------------------------------------------------------
function startFakeEngine(delayMs) {
  const server = http.createServer((req, res) => {
    let chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", async () => {
      if (req.url === "/api/documents/fill-template" && req.method === "POST") {
        await sleep(delayMs);
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ ok: true, message: "fake-fill-template-ok" }));
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

async function attemptFillTemplate() {
  const engine = await startFakeEngine(globalThis.__FAKE_ENGINE_DELAY_MS ?? 3000);
  const child = await startAviaryServer();
  try {
    const form = new FormData();
    form.append("source", new Blob([Buffer.from("fonte de teste")], { type: "text/plain" }), "fonte.txt");
    form.append("template", new Blob([Buffer.from("PK fake xlsx bytes")], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }), "template.xlsx");
    form.append("instruction", "teste");

    const t0 = Date.now();
    const res = await fetch(`http://localhost:${AVIARY_PORT}/api/documents/fill-template`, {
      method: "POST",
      body: form,
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

async function rebuild() {
  execSync(
    "npx esbuild server.ts --bundle --platform=node --format=cjs --packages=external --outfile=dist/server.cjs",
    { cwd: __dirname, stdio: "pipe" },
  );
}

async function main() {
  testSource();

  console.log("\n-- Parte 2: integração real (constante reduzida temporariamente pra caber num teste rápido) --");
  const original = fs.readFileSync(SERVER_TS_PATH, "utf-8");

  try {
    // Fake engine demora 3s. Reduz FILL_TEMPLATE_TIMEOUT_MS pra 1500ms
    // (menor que os 3s) - prova que É essa constante que aborta a
    // conexão, não outro número solto no meio do código.
    const shrunkToFail = original.replace(
      "const FILL_TEMPLATE_TIMEOUT_MS = 5_400_000; // 90min",
      "const FILL_TEMPLATE_TIMEOUT_MS = 1500; // reduzido só pra este teste",
    );
    if (shrunkToFail === original) {
      console.error("Âncora da constante não encontrada em server.ts - teste não pôde ser aplicado.");
      process.exit(1);
    }
    fs.writeFileSync(SERVER_TS_PATH, shrunkToFail);
    await rebuild();
    const withShortTimeout = await attemptFillTemplate();
    check(
      "com o teto reduzido (1.5s) menor que a demora do engine (3s), o request FALHA com 504 (prova que a constante controla o abort)",
      withShortTimeout.status === 504 && withShortTimeout.elapsedMs < 3000,
    );
    check(
      "a mensagem de erro do timeout aparece corretamente",
      !!(withShortTimeout.data && String(withShortTimeout.data.error || "").includes("Tempo esgotado esperando o preenchimento da planilha")),
    );

    // Agora um teto MAIOR que a demora do engine - prova que dá pra
    // configurar pra ESPERAR o suficiente e ter sucesso (é exatamente
    // isso que os 90min de produção fazem pro caso real de 21 pedaços).
    const grownToSucceed = original.replace(
      "const FILL_TEMPLATE_TIMEOUT_MS = 5_400_000; // 90min",
      "const FILL_TEMPLATE_TIMEOUT_MS = 8000; // aumentado só pra este teste",
    );
    fs.writeFileSync(SERVER_TS_PATH, grownToSucceed);
    await rebuild();
    const withLongerTimeout = await attemptFillTemplate();
    check(
      "com o teto maior (8s) que a demora do engine (3s), o MESMO caso agora tem SUCESSO (200)",
      withLongerTimeout.status === 200 && withLongerTimeout.data?.ok === true,
    );
    check(
      "esperou de fato pela resposta real (não retornou antes dos ~3s do engine)",
      withLongerTimeout.elapsedMs >= 2800,
    );
  } finally {
    fs.writeFileSync(SERVER_TS_PATH, original);
    await rebuild();
    const restored = fs.readFileSync(SERVER_TS_PATH, "utf-8");
    check("server.ts restaurado com FILL_TEMPLATE_TIMEOUT_MS = 5_400_000 (90min) de produção", restored.includes("const FILL_TEMPLATE_TIMEOUT_MS = 5_400_000; // 90min"));
  }

  console.log(`\n${passed} passaram, ${failed} falharam.`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch(async (e) => {
  console.error(e);
  process.exit(1);
});
