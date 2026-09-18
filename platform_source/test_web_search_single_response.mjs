import fs from "node:fs";

const source = fs.readFileSync("src/components/aviary/AviaryApp.tsx", "utf8");
const failures = [];

function check(condition, message) {
  if (!condition) failures.push(message);
}

check(
  source.includes("hiddenMessageIds: Set<string> = new Set()"),
  "sendToProvider precisa aceitar mensagens internas ocultas"
);
check(
  !/messagesWithSearch\s*}\s*:\s*c\)\)\);/.test(source),
  "resultado bruto da busca não pode ser gravado como resposta visível"
);
check(
  source.includes("webSources.length === 0"),
  "zero fontes deve bloquear a inferência"
);
check(
  source.includes("impedir que o modelo invente notícias, datas ou URLs"),
  "bloqueio precisa explicar a proteção contra fontes fabricadas"
);
check(
  /new Set\(\[searchResultsMsg\.id, webPromptMsg\.id\]\)/.test(source),
  "contexto web e prompt interno devem ficar ocultos da conversa"
);

if (failures.length) {
  for (const failure of failures) console.error(`FALHOU: ${failure}`);
  process.exit(1);
}
console.log("web-search-single-response: PASS");
