// test_rag_context_reaches_local_providers.mjs
//
// PHX-FIX (achado real do usuário 2026-08-28, ao comparar esta base — o
// repositório real no GitHub, com a implementação própria "PHX-RAG v57" já
// existente em chroma_rag_backend.py/api_server.py/AviaryApp.tsx — com uma
// linha de trabalho paralela): dentro de sendToProvider() (AviaryApp.tsx),
// o contexto do RAG (`ragSystemContext`, resultado de POST /api/rag/query
// disparado automaticamente em toda mensagem, ver bloco logo acima do
// bug) só era anexado ao systemInstruction no branch do endpoint Gemini
// ('/api/gemini/chat'). O branch usado por QUALQUER provedor local (Ollama,
// llama-server, LM Studio — endpoint '/api/proxy/chat', o caso de uso
// principal da Phoenix rodando 100% local) continuava montando o payload
// com `systemInstruction: parameters.systemInstruction` cru, sem o
// `ragSystemContext`. Resultado prático: a consulta ao RAG rodava (gastando
// uma chamada de rede) em toda mensagem, não importa o provedor escolhido,
// mas o resultado da busca era silenciosamente descartado sempre que o
// modelo selecionado não era Gemini — ou seja, na prática, para o público-
// alvo real deste projeto (hardware local, RX 580 + Xeon, sem depender de
// nuvem), o RAG nunca alimentava o LLM de verdade.
//
// Este script prova, por inspeção do código-fonte real de sendToProvider()
// em AviaryApp.tsx (mesmo padrão dos outros test_*.mjs deste diretório —
// não há vitest/jest configurado em platform_source/):
//
// 1. ragSystemContext é calculado uma única vez, ANTES dos dois branches
//    (Gemini e /api/proxy/chat) — não é uma variável recalculada/duplicada
//    por branch, o que poderia mascarar uma correção parcial.
// 2. O branch Gemini usa `parameters.systemInstruction + ragSystemContext`.
// 3. O branch /api/proxy/chat (endpoint usado por todo provedor local)
//    TAMBÉM usa `parameters.systemInstruction + ragSystemContext` — este é
//    o achado real: antes da correção, esta linha usava só
//    `parameters.systemInstruction`, sem o `+ ragSystemContext`.
// 4. Nenhum dos dois branches de sendToProvider() voltou a usar
//    `systemInstruction: parameters.systemInstruction,` cru (sem o RAG).
// 5. Controle negativo explícito: reproduz o bug real aplicando a MESMA
//    extração de regex numa cópia do texto anterior à correção (o literal
//    duas linhas acima do achado, sem "+ ragSystemContext") — confirma que
//    o teste de fato é capaz de detectar o bug, não só de confirmar a
//    correção por acaso.
// 6. Escopo: handleExecuteArena() (feature separada, "Arena"/comparação de
//    modelos) nunca calculou ragSystemContext em nenhum dos dois branches —
//    non-bug, fora do escopo dos 3 achados combinados com o usuário — o
//    teste apenas confirma que essa função não foi tocada por engano.
//
// Rodar: cd platform_source && node test_rag_context_reaches_local_providers.mjs

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

const sendToProviderStart = appSrc.indexOf("const sendToProvider = async (msgList: ChatMessage[]) => {");
check("sendToProvider() encontrado em AviaryApp.tsx", sendToProviderStart >= 0);

// handleExecuteArena vem depois de sendToProvider neste arquivo - usamos
// esse limite pra nunca acidentalmente casar um regex dentro da função
// errada.
const handleExecuteArenaStart = appSrc.indexOf("const handleExecuteArena = async (");
check("handleExecuteArena() encontrado (delimita o fim do trecho de sendToProvider a inspecionar)", handleExecuteArenaStart > sendToProviderStart);

const chunk = appSrc.slice(sendToProviderStart, handleExecuteArenaStart > 0 ? handleExecuteArenaStart : sendToProviderStart + 8000);

console.log("\n1. ragSystemContext calculado uma única vez, antes dos dois branches:");
check(
  "declaração única 'let ragSystemContext ='",
  (chunk.match(/let ragSystemContext =/g) || []).length === 1
);
check(
  "consulta real a /api/rag/query (não um placeholder)",
  /fetch\('\/api\/rag\/query'/.test(chunk)
);
check(
  "cálculo do ragSystemContext vem ANTES do primeiro 'let endpoint'",
  chunk.indexOf("let ragSystemContext =") < chunk.indexOf("let endpoint = '/api/gemini/chat';")
);

console.log("\n2. Branch Gemini usa parameters.systemInstruction + ragSystemContext:");
const geminiBlockMatch = chunk.match(/let requestPayload: any = \{[\s\S]{0,400}?\n\s*\};/);
check("bloco requestPayload (Gemini, default) encontrado", !!geminiBlockMatch);
check(
  "requestPayload (Gemini) usa 'systemInstruction: parameters.systemInstruction + ragSystemContext,'",
  !!geminiBlockMatch && /systemInstruction: parameters\.systemInstruction \+ ragSystemContext,/.test(geminiBlockMatch[0])
);

console.log("\n3. Branch /api/proxy/chat (todo provedor local: Ollama, llama-server, LM Studio) — ESTE é o achado real:");
const proxyBlockMatch = chunk.match(/endpoint = '\/api\/proxy\/chat';\s*\n\s*requestPayload = \{[\s\S]{0,1600}?\n\s*\};/);
check("bloco requestPayload (endpoint /api/proxy/chat) encontrado", !!proxyBlockMatch);
check(
  "CORRIGIDO: requestPayload (/api/proxy/chat) agora também usa 'systemInstruction: parameters.systemInstruction + ragSystemContext,'",
  !!proxyBlockMatch && /systemInstruction: parameters\.systemInstruction \+ ragSystemContext,/.test(proxyBlockMatch[0])
);

console.log("\n4. Nenhum dos dois branches de sendToProvider() voltou a usar systemInstruction cru (sem RAG):");
check(
  "nenhuma ocorrência de 'systemInstruction: parameters.systemInstruction,' (sem + ragSystemContext) dentro de sendToProvider()",
  !/systemInstruction: parameters\.systemInstruction,\n/.test(chunk)
);

console.log("\n5. Contraprova - o mesmo teste DETECTARIA o bug original (reprodução do texto pré-correção):");
const bugPreCorrecao = `
        if (providerObj.type !== 'gemini') {
          endpoint = '/api/proxy/chat';
          requestPayload = {
            providerType: providerObj.type,
            baseUrl: providerObj.baseUrl,
            apiKey: providerObj.apiKey,
            model: selectedModelId,
            messages: historyForProvider,
            systemInstruction: parameters.systemInstruction,
            temperature: parameters.temperature,
            maxTokens: parameters.maxTokens,
          };
        }
`;
check(
  "reprodução fiel do texto anterior à correção NÃO passaria no regex usado acima (prova que o teste detecta o bug de verdade)",
  !/systemInstruction: parameters\.systemInstruction \+ ragSystemContext,/.test(bugPreCorrecao)
);
check(
  "e o padrão de detecção de regressão (systemInstruction cru) DE FATO bate nessa reprodução do bug",
  /systemInstruction: parameters\.systemInstruction,\n/.test(bugPreCorrecao)
);

console.log("\n6. Escopo: handleExecuteArena() é uma feature separada (comparação de modelos) — nunca teve ragSystemContext, e não foi alterada:");
const arenaChunk = appSrc.slice(handleExecuteArenaStart, handleExecuteArenaStart + 1200);
check(
  "handleExecuteArena() não calcula ragSystemContext (confirma que é código pré-existente, fora do escopo dos 3 achados combinados)",
  !/ragSystemContext/.test(arenaChunk)
);

console.log(`\n${passed} passaram, ${failed} falharam.`);
process.exit(failed > 0 ? 1 : 0);
