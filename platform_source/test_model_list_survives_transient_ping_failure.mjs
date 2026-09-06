// test_model_list_survives_transient_ping_failure.mjs
//
// Teste pro achado real do usuário (print de tela): o dropdown de modelo
// mostrou SÓ Gemini, sumindo com Qwen3-4B-Q4_K_M que funcionava minutos
// antes na mesma sessão. Logs mostravam o sistema sob carga pesada (GPU a
// 99%, descrição de imagem + geração de documento rodando junto) - o
// llama-server estava vivo, só ocupado.
//
// Causa raiz: o ping ao vivo (handleTestProvider, timeout de 2.5s) marca
// `status: 'error'` quando um servidor OCUPADO (não morto) demora mais
// que isso pra responder um GET /v1/models simples. availableModels
// escondia TODOS os modelos desse provedor sempre que status !==
// 'connected' - mesmo que `p.models` já tivesse a lista real de um scan
// bem-sucedido minutos antes na mesma sessão (o ping falho preserva
// `p.models`, só muda o status).
//
// Corrigido: distingue 'disconnected' com models=[] (nunca conectou -
// continua excluído, protege a correção original de 2026-08-20 contra
// nomes fabricados) de 'error' com models.length>0 (falha do ping mais
// recente, não da existência do provedor - não esconde mais).

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const AVIARY_APP_PATH = path.join(__dirname, "src", "components", "aviary", "AviaryApp.tsx");
const SERVER_TS_PATH = path.join(__dirname, "server.ts");

let passed = 0;
let failed = 0;
function check(label, cond) {
  if (cond) { console.log(`  OK   ${label}`); passed++; }
  else { console.log(`  FALHOU ${label}`); failed++; }
}

const aviarySrc = fs.readFileSync(AVIARY_APP_PATH, "utf-8");
const serverSrc = fs.readFileSync(SERVER_TS_PATH, "utf-8");

console.log("\n-- Parte 1: server.ts - timeout do ping aumentado --");
check("timeout do ping NÃO é mais 2500ms (curto demais pra servidor ocupado)", !/setTimeout\(\(\) => controller\.abort\(\), 2500\)/.test(serverSrc));
check("timeout do ping é 6000ms (folga real pra processo local sob carga)", /setTimeout\(\(\) => controller\.abort\(\), 6000\)/.test(serverSrc));

console.log("\n-- Parte 2: AviaryApp.tsx - simula a lógica real de availableModels --");

// Extrai e testa a lógica de filtro de disponibilidade diretamente do
// código de produção (mesmo espírito do já usado em outros testes desta
// sessão) - aqui simulada inline pela clareza do cenário, já que a
// condição é uma expressão simples de uma linha.
function isUsable(p) {
  return p.type === "gemini" || p.status === "connected" || (p.status === "error" && p.models.length > 0);
}

check("a condição isUsable está presente no arquivo real (não uma reimplementação solta)",
  /const isUsable = p\.type === 'gemini' \|\| p\.status === 'connected' \|\| \(p\.status === 'error' && p\.models\.length > 0\)/.test(aviarySrc));

// Cenário exato do print de tela: llama-server confirmou Qwen3-4B-Q4_K_M
// minutos antes, depois um ping sob carga falha e marca 'error'.
const llamaServerAposFalhaTransitoria = {
  type: "llama-server", status: "error", models: ["Qwen3-4B-Q4_K_M"],
};
check("llama-server com modelos confirmados + ping falho transitório: continua USÁVEL (achado central)", isUsable(llamaServerAposFalhaTransitoria));

// Regressão: nunca conectou nesta sessão - protege a correção original
// de 2026-08-20 (nomes fabricados/placeholder nunca deveriam aparecer).
const llamaServerNuncaConectado = {
  type: "llama-server", status: "disconnected", models: [],
};
check("llama-server nunca conectado (models vazio): continua EXCLUÍDO (regressão da correção de 20/08)", !isUsable(llamaServerNuncaConectado));

// Gemini sempre passa, independente de status (comportamento já existente).
const geminiQualquerStatus = { type: "gemini", status: "error", models: [] };
check("Gemini sempre usável, independente de status (comportamento já existente preservado)", isUsable(geminiQualquerStatus));

// Provedor conectado normalmente (caminho feliz, sem falha nenhuma).
const conectadoNormal = { type: "ollama", status: "connected", models: ["qwen3:8b"] };
check("provedor status=connected normal: continua usável (caminho feliz intacto)", isUsable(conectadoNormal));

// Edge case: status='error' mas SEM modelos confirmados (ping falhou e
// nunca teve sucesso antes) - não deveria virar usável só por estar
// 'error' em vez de 'disconnected'.
const errorSemModelos = { type: "llama-server", status: "error", models: [] };
check("status=error MAS sem modelos confirmados: continua EXCLUÍDO (não abre brecha nova)", !isUsable(errorSemModelos));

console.log(`\n${passed} passaram, ${failed} falharam.`);
process.exit(failed > 0 ? 1 : 0);
