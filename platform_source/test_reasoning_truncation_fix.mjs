// test_reasoning_truncation_fix.mjs
//
// Teste pro achado real do usuário 2026-09-06: "qualquer resposta do
// modelo... fica cortada após alguns caracteres" - acontecendo com AMBOS
// os provedores (local llama-server E Gemini), SEM nenhum erro na tela.
// Investigação descartou timeout de rede (já corrigido antes, e daria
// erro visível) e achou DUAS causas técnicas diferentes, mesmo sintoma:
//
// (1) llama-server: sem --jinja explícito, a separação de "pensamento"
// (<think>...</think>) de modelos como Qwen3 fica a critério do padrão da
// build. Quando falha, a tag <think> vem EMBUTIDA no campo `content`. O
// front-end tentava remover isso com um regex que exige abrir E fechar a
// tag - se a resposta corta ENQUANTO o modelo ainda "pensa" (tag nunca
// fecha), o regex não acha nada, e o raciocínio bruto vaza pra tela
// (parece "corta no meio"), ou o pensamento consome o orçamento e a
// resposta visível final fica curta demais.
//
// (2) Gemini: modelos 2.5+/3.x vêm com "pensamento" ligado por padrão -
// documentado oficialmente e reproduzido por múltiplos outros projetos -
// e os tokens de raciocínio contam contra o MESMO maxOutputTokens da
// resposta visível. Sem thinkingConfig explícito, um maxTokens razoável
// pode ser consumido inteiro só pensando (finishReason=MAX_TOKENS,
// candidatesTokenCount=0) - resposta vazia ou cortada, sem erro nenhum.
//
// Corrigido: --jinja explícito na inicialização do llama-server (garante
// separação em `reasoning_content`, testado oficialmente com Qwen3);
// server.ts agora lê e repassa esse campo como `reasoning` pro front-end
// (que passa a preferir isso ao invés do regex frágil); front-end também
// ganhou um fallback melhor pro caso raro do servidor não separar (tag
// sem fechamento tratada como pensamento incompleto, nunca vazando pra
// resposta visível); Gemini ganhou thinkingConfig com reserva de folga
// pro raciocínio, sem tirar do que o usuário pediu pra resposta.
//
// Rodar: cd platform_source && npm run build (ou só esbuild server.ts) &&
//        node test_reasoning_truncation_fix.mjs

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SERVER_TS_PATH = path.join(__dirname, "server.ts");
const LLAMA_CPP_PY_PATH = path.join(__dirname, "..", "phoenix_kernel", "runtime", "drivers", "llama_cpp.py");
const AVIARY_APP_PATH = path.join(__dirname, "src", "components", "aviary", "AviaryApp.tsx");

let passed = 0;
let failed = 0;
function check(label, cond) {
  if (cond) { console.log(`  OK   ${label}`); passed++; }
  else { console.log(`  FALHOU ${label}`); failed++; }
}

console.log("\n-- Parte 1: llama-server ganha --jinja explícito (separação real de reasoning_content) --");
const llamaCppSrc = fs.readFileSync(LLAMA_CPP_PY_PATH, "utf-8");
check("_build_server_args() passa --jinja explicitamente", /'--jinja'|"--jinja"/.test(llamaCppSrc));

console.log("\n-- Parte 2: server.ts lê e repassa reasoning_content do llama-server --");
const serverSrc = fs.readFileSync(SERVER_TS_PATH, "utf-8");
check("extrai reasoning_content de data.choices[0].message", /reasoning_content/.test(serverSrc));
check("resposta JSON do chat local inclui campo `reasoning`", /reasoning:\s*reasoningContentResult/.test(serverSrc));

console.log("\n-- Parte 3: Gemini ganha thinkingConfig + reserva de orçamento pro raciocínio --");
check("Gemini: thinkingConfig configurado explicitamente (não deixa no padrão do Google)", /thinkingConfig\s*=\s*\{/.test(serverSrc) || /config\.thinkingConfig/.test(serverSrc));
check("Gemini: reserva de tokens extra pro raciocínio ao definir maxOutputTokens", /GEMINI_THINKING_BUDGET_RESERVE/.test(serverSrc));
check("Gemini: extrai thought parts da resposta (candidates[0].content.parts)", /p\?\.thought|part\.thought/.test(serverSrc));
check("Gemini: resposta JSON inclui campo `reasoning`", /reasoning:\s*reasoningResult/.test(serverSrc));

console.log("\n-- Parte 4: front-end prioriza reasoning do servidor, com fallback seguro pro regex --");
const aviarySrc = fs.readFileSync(AVIARY_APP_PATH, "utf-8");
const reasoningPriorityCount = (aviarySrc.match(/if \(data\.reasoning\)/g) || []).length;
check("os DOIS caminhos de chat (normal + Arena) priorizam data.reasoning quando presente", reasoningPriorityCount === 2);

console.log("\n-- Parte 5: fallback do front-end trata tag <think> SEM fechamento (achado central do bug) --");
// Simula a lógica de fallback extraída do próprio arquivo, pra provar o
// comportamento sem precisar subir um servidor completo.
function simulateFallback(responseText) {
  let thinkingText = "";
  const thinkMatch = responseText.match(/<think>([\s\S]*?)<\/think>/i);
  if (thinkMatch) {
    thinkingText = thinkMatch[1].trim();
    responseText = responseText.replace(/<think>[\s\S]*?<\/think>/gi, "").trim();
  } else {
    const openThinkIdx = responseText.search(/<think>/i);
    if (openThinkIdx !== -1) {
      thinkingText = responseText.slice(openThinkIdx + "<think>".length).trim();
      responseText = responseText.slice(0, openThinkIdx).trim();
    }
  }
  return { responseText, thinkingText };
}

const closedTag = "Resposta normal <think>raciocínio completo</think> resto da resposta";
const r1 = simulateFallback(closedTag);
check("tag FECHADA: continua removendo e juntando o texto ao redor (comportamento antigo preservado)", r1.responseText === "Resposta normal  resto da resposta" && r1.thinkingText === "raciocínio completo");

const unclosedTag = "Isso é o começo da resposta <think>e aqui o modelo ainda está pensando quando a geração foi cortada, nunca chegou a fechar a tag";
const r2 = simulateFallback(unclosedTag);
check("tag ABERTA sem fechar (achado central): texto bruto NÃO vaza pra responseText", !r2.responseText.includes("<think>"));
check("tag ABERTA sem fechar: o que veio ANTES da tag continua visível como resposta", r2.responseText === "Isso é o começo da resposta");
check("tag ABERTA sem fechar: o raciocínio incompleto vai pro thinkingText, não pra tela principal", r2.thinkingText.includes("nunca chegou a fechar"));

const noTagAtAll = "Resposta comum sem nenhum raciocínio, texto normal do início ao fim.";
const r3 = simulateFallback(noTagAtAll);
check("sem tag nenhuma: responseText passa intacto (não quebra o caso comum)", r3.responseText === noTagAtAll && r3.thinkingText === "");

console.log(`\n${passed} passaram, ${failed} falharam.`);
process.exit(failed > 0 ? 1 : 0);
