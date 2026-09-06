// test_chat_history_identity_leak.mjs
//
// PHX-FIX (achado real do usuário 2026-08-24, via screenshots): pediu
// "gerar imagem" no chat (respondido com "Imagem gerada com
// **flux1-schnell-Q4_K_M**." - só um aviso de UI sobre o motor SDXL/Flux
// local, sd_cpp.py). Na mensagem SEGUINTE, na MESMA conversa, perguntou
// "ola, seu nome e modelo?" pro modelo de texto selecionado (qwen3-8b via
// llama-server) - e ele respondeu:
//
//   Nome: Phoenix Aviary Platform (AIVISIONSLAB STUDIO GROUP)
//   Modelo: Flux 1-Schnell (Q4_K_M)
//
// Causa raiz, confirmada lendo o código real de AviaryApp.tsx (sendToProvider)
// e server.ts (buildChatRequest): `messages: msgList` mandava o histórico
// INTEIRO da conversa pro provedor de texto sem filtro nenhum -
// `messages.map((m) => ({ role: m.role, content: m.content }))` em
// server.ts trata QUALQUER mensagem de role 'assistant' no array como se
// fosse uma fala real do próprio modelo, incluindo o aviso "Imagem gerada
// com flux1-schnell" (que na verdade veio do backend de imagem, não do
// LLM). Combinado com o system prompt padrão ("Você é a Phoenix Aviary
// Platform" / preset "Assistente Geral Conciso" em systemPrompts.ts), o
// qwen3-8b só sintetizou os dois fatos que via no próprio contexto - uma
// alucinação plausível, mas incorreta, de identidade. A mesma classe de
// mensagem "aviso de subsistema local, não fala do modelo" também existe
// pra colaboração entre dois outros modelos (dual-collab) e edição de
// documento - mesmo risco, mesma correção.
//
// Correção: novo campo ChatMessage.excludeFromHistory (types.ts), setado
// nas 5 mensagens de aviso (imagem gerada, colaboração x3, documento
// editado), e sendToProvider() em AviaryApp.tsx agora filtra por ele ANTES
// de montar o payload de rede - `historyForProvider = msgList.filter((m)
// => !m.excludeFromHistory)`. As mensagens continuam aparecendo
// normalmente na tela (React state não é filtrado, só o payload de rede).
//
// Não há vitest/jest configurado em platform_source/ (mesmo motivo do
// test_server_json_error_handling.mjs ao lado) - este script inspeciona o
// código-fonte REAL de AviaryApp.tsx e types.ts em disco (não uma cópia
// reescrita) e executa a expressão de filtro extraída dele de verdade
// contra uma reprodução fiel do histórico de conversa do bug relatado,
// provando o comportamento, não só a presença do texto.
//
// Rodar: cd platform_source && node test_chat_history_identity_leak.mjs

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
const typesSrc = fs.readFileSync(path.join(__dirname, "src", "types.ts"), "utf8");

console.log("1. Campo excludeFromHistory declarado em ChatMessage (types.ts):");
check(
  "types.ts declara 'excludeFromHistory?: boolean;'",
  /excludeFromHistory\?:\s*boolean;/.test(typesSrc)
);

console.log("\n2. As 5 mensagens de aviso de subsistema local marcam excludeFromHistory: true:");
const anchors = [
  ["Imagem gerada com \\*\\*\\$\\{data.model", "confirmação de imagem gerada (Flux/SDXL)"],
  ["Documento editado com sucesso", "confirmação de edição de documento"],
  ["Iniciando colaboração entre os dois modelos", "aviso de início da colaboração (dual-collab)"],
  ["Rodada \\$\\{t.round\\}", "turnos individuais da colaboração (fala de OUTROS 2 modelos)"],
  ["Colaboração concluída em|Colaboração parada", "resumo final da colaboração"],
];
for (const [anchorPattern, label] of anchors) {
  const anchorRe = new RegExp(anchorPattern);
  // Usa a ÚLTIMA ocorrência da âncora no arquivo - os comentários PHX-FIX
  // explicativos adicionados por esta própria correção citam o texto da
  // mensagem antiga como exemplo (ex: "respondeu 'Imagem gerada com
  // **flux1-schnell-Q4_K_M**.'" dentro do comentário), então a PRIMEIRA
  // ocorrência normalmente é a prosa do comentário, não o literal de
  // objeto ChatMessage real - a mensagem de código de fato vem depois.
  const allMatches = [...appSrc.matchAll(new RegExp(anchorPattern, "g"))];
  check(`âncora encontrada: ${label}`, allMatches.length > 0);
  if (allMatches.length > 0) {
    const anchorMatch = allMatches[allMatches.length - 1];
    // A flag deve aparecer antes do início do PRÓXIMO literal de
    // ChatMessage (`id: Math.random().toString(36).substring(2, 9)` é como
    // todo objeto ChatMessage novo começa neste arquivo - ver qualquer um
    // dos ~19 pontos de criação). Não dá pra usar só "próximo '};'" como
    // fronteira: campos como `image: \`data:${...};base64,...\`` têm um
    // "};" no MEIO de uma template string, bem antes do objeto realmente
    // terminar - já pegou um falso-negativo por causa disso.
    const start = anchorMatch.index;
    const rest = appSrc.slice(start);
    const nextObjectStart = rest.indexOf("id: Math.random().toString(36).substring(2, 9)", 1);
    const objectText = nextObjectStart >= 0 ? rest.slice(0, nextObjectStart) : rest.slice(0, 1500);
    check(`  -> excludeFromHistory: true dentro do mesmo objeto (${label})`, /excludeFromHistory:\s*true/.test(objectText));
  }
}

console.log("\n3. sendToProvider() filtra o histórico ANTES de montar os dois payloads de rede:");
const filterMatch = appSrc.match(/const historyForProvider = msgList\.filter\(([^;]+)\);/);
check("expressão de filtro 'historyForProvider = msgList.filter(...)' presente", !!filterMatch);

const geminiPayloadUsesFilter = /endpoint = '\/api\/gemini\/chat';[\s\S]{0,20}let requestPayload: any = \{[\s\S]{0,200}messages: historyForProvider,/.test(
  appSrc
);
check("payload do endpoint Gemini usa historyForProvider (não msgList cru)", geminiPayloadUsesFilter);

const proxyPayloadUsesFilter = /requestPayload = \{[\s\S]{0,200}messages: historyForProvider,/.test(appSrc);
check("payload do endpoint /api/proxy/chat usa historyForProvider (não msgList cru)", proxyPayloadUsesFilter);

check(
  "nenhum dos dois payloads de rede voltou a usar 'messages: msgList' diretamente",
  !/messages:\s*msgList,/.test(appSrc)
);

console.log("\n4. Execução real da expressão de filtro extraída do arquivo (reprodução fiel do bug relatado):");
if (filterMatch) {
  // Reproduz o predicado extraído de verdade do arquivo-fonte (não uma
  // reimplementação) contra uma sequência de mensagens que reproduz
  // exatamente a conversa do usuário: pediu uma imagem, recebeu o aviso
  // (marcado excludeFromHistory:true pela correção), e então perguntou
  // "seu nome e modelo?".
  const predicateBody = filterMatch[1]; // ex: "(m) => !m.excludeFromHistory"
  const predicate = new Function(`return (${predicateBody});`)();

  const conversaReal = [
    { role: "user", content: "gerar imagem de uma phoenix voando sob chamas" },
    {
      role: "assistant",
      content: "Imagem gerada com **flux1-schnell-Q4_K_M**.",
      excludeFromHistory: true, // setado pela correção no ponto de criação
    },
    { role: "user", content: "ola, seu nome e modelo?" },
  ];

  const historyEnviado = conversaReal.filter(predicate);

  check(
    "aviso 'Imagem gerada com flux1-schnell' NÃO está no histórico enviado pro provedor",
    !historyEnviado.some((m) => m.content.includes("flux1-schnell"))
  );
  check(
    "as duas mensagens reais do usuário continuam no histórico enviado",
    historyEnviado.length === 2 &&
      historyEnviado[0].content.includes("gerar imagem") &&
      historyEnviado[1].content.includes("seu nome e modelo")
  );

  // Controle negativo / regressão: uma mensagem SEM a flag (ex: resposta
  // normal de um turno de chat anterior) precisa continuar no histórico -
  // a correção não pode virar um filtro "exclui tudo" nem "exclui por
  // acidente" mensagens comuns de assistente.
  const comHistoricoNormal = [
    { role: "user", content: "qual a capital da frança?" },
    { role: "assistant", content: "Paris." },
    { role: "user", content: "e da alemanha?" },
  ];
  const historyNormalFiltrado = comHistoricoNormal.filter(predicate);
  check(
    "controle negativo: histórico sem nenhuma flag passa 100% intacto pelo filtro",
    historyNormalFiltrado.length === 3 && historyNormalFiltrado[1].content === "Paris."
  );
} else {
  check("(pulado - expressão de filtro não encontrada, ver item 3 acima)", false);
}

console.log(`\n${passed} passaram, ${failed} falharam.`);
process.exit(failed > 0 ? 1 : 0);
