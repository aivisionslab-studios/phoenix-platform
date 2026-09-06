// test_web_search_intent.mjs
//
// PHX-NEW (achado real do usuário 2026-08-24, screenshot): digitou
// "pesquisar acidente com 2 helicópteros no rj em 2026" no chat de texto
// normal, e o qwen3-8b respondeu direto da própria memória de treino ("a
// data de 2026 ainda não chegou") - sem NUNCA acionar uma busca real. O
// Phoenix Engine já tinha busca real via SearXNG (web_search.py), só
// nunca conectada ao chat comum - ver test_web_search_route.py (lado
// Python) pra prova da rota nova /api/web-search. Este script prova o
// lado do FRONTEND: a detecção de intenção (WEB_SEARCH_TRIGGER_PATTERN /
// isWebSearchIntent) e a extração da query real, extraídas e executadas
// de verdade a partir do código-fonte de AviaryApp.tsx (não uma
// reimplementação) - mesmo padrão de test_chat_history_identity_leak.mjs
// ao lado.
//
// Não há vitest/jest configurado em platform_source/ (mesmo motivo dos
// outros test_*.mjs desta pasta).
//
// Rodar: cd platform_source && node test_web_search_intent.mjs

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
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

const appSrc = fs.readFileSync(
  path.join(__dirname, "src", "components", "aviary", "AviaryApp.tsx"),
  "utf8"
);

console.log("1. Rota nova /api/web-search é chamada pelo frontend:");
check("fetch('/api/web-search') presente em AviaryApp.tsx", /fetch\('\/api\/web-search'/.test(appSrc));

console.log("\n2. Extração real do padrão de detecção (WEB_SEARCH_TRIGGER_PATTERN) do arquivo-fonte:");
const patternMatch = appSrc.match(/const WEB_SEARCH_TRIGGER_PATTERN =\s*\n?\s*(\/.+\/[a-z]*);/);
check("WEB_SEARCH_TRIGGER_PATTERN encontrado no código real", !!patternMatch);

if (patternMatch) {
  // eslint-disable-next-line no-eval
  const WEB_SEARCH_TRIGGER_PATTERN = eval(patternMatch[1]);

  console.log("\n3. Controles positivos (devem disparar busca):");
  const positivos = [
    "pesquisar acidente com 2 helicópteros no rj em 2026", // a mensagem REAL do usuário
    "pesquise o preço do dólar hoje",
    "busca notícias sobre o Flux 1.1",
    "buscar quem é o presidente atual",
    "procure informações sobre a RX 580",
    "search for the latest news on AMD",
    "google isso pra mim",
  ];
  for (const msg of positivos) {
    check(`dispara em: "${msg}"`, WEB_SEARCH_TRIGGER_PATTERN.test(msg));
  }

  console.log("\n4. Controles negativos (NÃO devem disparar busca - conversa normal):");
  const negativos = [
    "onde eu procuro isso no menu da Phoenix?", // "procuro" no MEIO da frase, não como comando
    "qual a capital da frança?",
    "me explique como funciona o Vulkan",
    "gerar imagem de uma phoenix voando",
    "estou procurando um emprego na área de TI", // uso comum de "procurando", não comando de busca
  ];
  for (const msg of negativos) {
    check(`NÃO dispara em: "${msg}"`, !WEB_SEARCH_TRIGGER_PATTERN.test(msg));
  }

  console.log("\n5. Extração da query real (reproduz exatamente a mensagem do usuário):");
  const realUserMsg = "pesquisar acidente com 2 helicópteros no rj em 2026";
  const extractedQuery = realUserMsg.replace(WEB_SEARCH_TRIGGER_PATTERN, "").trim() || realUserMsg;
  check(
    `query extraída não contém mais o verbo de busca ("${extractedQuery}")`,
    extractedQuery === "acidente com 2 helicópteros no rj em 2026"
  );
} else {
  check("(pulado - padrão não encontrado, ver item 2 acima)", false);
}

console.log("\n6. Mensagem de resultados da busca NÃO tem excludeFromHistory (ao contrário do aviso de imagem gerada):");
const searchMsgMatch = appSrc.match(/Resultados da busca na web[\s\S]{0,400}/);
check("âncora da mensagem de resultados encontrada", !!searchMsgMatch);
if (searchMsgMatch) {
  const nextObjectBoundary = searchMsgMatch[0].indexOf("};");
  const objectText = nextObjectBoundary >= 0 ? searchMsgMatch[0].slice(0, nextObjectBoundary) : searchMsgMatch[0];
  check(
    "resultado da busca NÃO é marcado excludeFromHistory (o modelo precisa ver esse conteúdo pra responder)",
    !/excludeFromHistory:\s*true/.test(objectText)
  );
}

console.log("\n7. Depois de mostrar os resultados, a pergunta original é reenviada pro modelo de texto (sendToProvider):");
check(
  "sendToProvider() é chamado logo após montar messagesWithSearch",
  /messagesWithSearch[\s\S]{0,700}await sendToProvider\(/.test(appSrc)
);

console.log(`\n${passed} passaram, ${failed} falharam.`);
process.exit(failed > 0 ? 1 : 0);
