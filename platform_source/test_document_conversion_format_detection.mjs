// test_document_conversion_format_detection.mjs
//
// Teste pro achado real do usuário 2026-09-06: "a phoenix nao muda o
// formato de nenhum arquivo. por exemplo: de excel pra md, pdf pra
// excel, doc pra pdf etc..."
//
// Investigação encontrou que a funcionalidade de conversão JÁ EXISTIA no
// backend (/api/documents/create, docstring: "Cria documento do zero OU
// transforma um documento-base... Fonte opcional: PDF/DOCX/XLSX/PPTX/
// TXT/MD. Saída: PDF/DOCX/XLSX/PPTX/TXT/MD.") - só era acionada por
// DETECÇÃO DE INTENÇÃO no texto do chat, não por um botão dedicado.
//
// Dois bugs reais achados na detecção (não no backend):
//
// (1) `detectDocumentOutputFormat` pegava o PRIMEIRO formato mencionado
// na frase inteira, em ordem fixa - sem distinguir formato de ORIGEM
// (o arquivo já anexado) do formato de DESTINO (o que o usuário quer).
// "converta esse excel pra markdown" detectava xlsx (a origem) em vez de
// md (o destino de verdade) - o sistema tentava "converter" pro MESMO
// formato do arquivo, parecendo não fazer nada.
//
// (2) `DOCUMENT_ACTION_PATTERN` só reconhecia verbos "formais"
// (converta/converter/transforme) - verbos coloquiais comuns em
// português ("passa esse doc pra pdf", "muda pra excel", "troque por
// word") nunca disparavam a ação.
//
// Corrigido: formato-alvo priorizado quando precedido de uma preposição
// de destino ("pra"/"para"/"em"/"como"/"por"); verbos trocados por
// radicais de palavra (cobrem conjugações automaticamente), incluindo a
// troca ortográfica c->qu de "trocar" (troco/trocar, mas troQUE).
//
// Rodar: cd platform_source && node test_document_conversion_format_detection.mjs

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const AVIARY_APP_PATH = path.join(__dirname, "src", "components", "aviary", "AviaryApp.tsx");
const src = fs.readFileSync(AVIARY_APP_PATH, "utf-8");

let passed = 0;
let failed = 0;
function check(label, cond) {
  if (cond) { console.log(`  OK   ${label}`); passed++; }
  else { console.log(`  FALHOU ${label}`); failed++; }
}

// Extrai as duas funções reais do arquivo-fonte (não reimplementa do
// zero) - prova que o teste valida o código de PRODUÇÃO, não uma cópia.
function extractFunctionBody(name) {
  const start = src.indexOf(`const ${name} =`);
  if (start === -1) throw new Error(`${name} não encontrado em AviaryApp.tsx`);
  // Encontra o `};` que fecha a função (primeiro no mesmo nível de indentação)
  const bodyStart = src.indexOf("=>", start) + 2;
  let depth = 0;
  let i = src.indexOf("{", bodyStart);
  const braceStart = i;
  for (; i < src.length; i++) {
    if (src[i] === "{") depth++;
    if (src[i] === "}") { depth--; if (depth === 0) break; }
  }
  return src.slice(start, i + 1);
}

console.log("\n-- Parte 1: detectDocumentOutputFormat distingue origem de destino --");
const detectFnSrcTs = extractFunctionBody("detectDocumentOutputFormat");
const { execSync } = await import("node:child_process");
function transpileTs(tsSnippet) {
  const tmpFile = path.join(__dirname, "_test_ts_snippet_tmp.ts");
  fs.writeFileSync(tmpFile, tsSnippet);
  try {
    return execSync(`npx esbuild "${tmpFile}"`, { cwd: __dirname }).toString();
  } finally {
    fs.rmSync(tmpFile, { force: true });
  }
}
const detectFnSrc = transpileTs(detectFnSrcTs);
// eslint-disable-next-line no-new-func
const detectDocumentOutputFormat = new Function(`${detectFnSrc}; return detectDocumentOutputFormat;`)();

check("'converta esse excel pra markdown' -> md (destino), não xlsx (origem)", detectDocumentOutputFormat("converta esse excel pra markdown") === "md");
check("'transforme esse pdf em word' -> docx (destino), não pdf (origem)", detectDocumentOutputFormat("transforme esse pdf em word") === "docx");
check("'exporte essa planilha como pdf' -> pdf (destino), não xlsx (origem)", detectDocumentOutputFormat("exporte essa planilha como pdf") === "pdf");
check("'converte esse arquivo de excel pra md' -> md", detectDocumentOutputFormat("converte esse arquivo de excel pra md") === "md");
check("'muda esse pdf pra excel' -> xlsx (destino), não pdf (origem)", detectDocumentOutputFormat("muda esse pdf pra excel") === "xlsx");
check("sem preposição de destino: cai pro fallback (primeiro formato mencionado)", detectDocumentOutputFormat("preciso desse pdf urgente") === "pdf");
check("nenhum formato mencionado: null", detectDocumentOutputFormat("bom dia, tudo bem?") === null);

console.log("\n-- Parte 2: DOCUMENT_ACTION_PATTERN reconhece verbos coloquiais --");
const actionPatternMatch = src.match(/const DOCUMENT_ACTION_PATTERN =\s*\n?\s*(\/[\s\S]*?\/[a-z]*);/);
if (!actionPatternMatch) throw new Error("DOCUMENT_ACTION_PATTERN não encontrado em AviaryApp.tsx");
// eslint-disable-next-line no-eval
const DOCUMENT_ACTION_PATTERN = eval(actionPatternMatch[1]);

check("'converta' (formal, já funcionava) continua reconhecido", DOCUMENT_ACTION_PATTERN.test("converta isso"));
check("'passa esse doc pra pdf' (coloquial) agora reconhecido", DOCUMENT_ACTION_PATTERN.test("passa esse doc pra pdf"));
check("'muda esse pdf pra excel' (coloquial) agora reconhecido", DOCUMENT_ACTION_PATTERN.test("muda esse pdf pra excel"));
check("'troque esse word por pdf' (troca c->qu, ortografia) agora reconhecido", DOCUMENT_ACTION_PATTERN.test("troque esse word por pdf"));
check("'trocar esse pdf por word' (infinitivo) reconhecido", DOCUMENT_ACTION_PATTERN.test("trocar esse pdf por word"));
check("'vira isso pra pdf' (bem coloquial) reconhecido", DOCUMENT_ACTION_PATTERN.test("vira isso pra pdf"));

console.log("\n-- Parte 3: combinação completa (formato + ação) para os casos reais do usuário --");
const casosReais = [
  ["converta esse excel pra markdown", "md"],
  ["transforme esse pdf em word", "docx"],
  ["muda esse pdf pra excel", "xlsx"],
  ["passa esse documento word pra pdf", "pdf"],
];
for (const [frase, esperado] of casosReais) {
  const fmt = detectDocumentOutputFormat(frase);
  const acao = DOCUMENT_ACTION_PATTERN.test(frase);
  check(`"${frase}" -> dispara com formato correto (${esperado})`, acao && fmt === esperado);
}

console.log(`\n${passed} passaram, ${failed} falharam.`);
process.exit(failed > 0 ? 1 : 0);
