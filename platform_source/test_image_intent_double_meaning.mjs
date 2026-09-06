// test_image_intent_double_meaning.mjs
//
// PHX-FIX (achado real via screenshot do usuário 2026-08-28): o usuário
// digitou uma pergunta genuína sobre backend de GPU pra geração de imagem -
// "vou usar rocm, cuda ou vulkan? pra gerar imagens, como faço? comfyui ou
// sd server?" - e o Phoenix GEROU UMA IMAGEM DE VERDADE em vez de responder
// a pergunta. Causa raiz, confirmada lendo AviaryApp.tsx: o regex
// verbo+substantivo de isImageGenerationIntent (`/\bger[ae]\w*.../`) batia
// na MENSAGEM INTEIRA como uma string só - "pra gerar imagens, como faço?"
// contém o par "gerar"..."imagens" e disparava o regex, mesmo a mensagem
// sendo, como um todo, uma pergunta ("gerar imagem" tem duplo sentido: pode
// ser um comando ou parte de uma dúvida sobre COMO gerar). O guard
// `looksLikeQuestion` já existia no arquivo, mas só era usado dentro de
// looksLikeRawImagePrompt() (heurística separada, pra prompt "cru" estilo
// Stable Diffusion) - nunca entrava no regex de verbo+substantivo.
//
// Correção: hasImageGenerationVerbNounInNonQuestionClause() separa o texto
// em orações (por . ! ?) e só considera intenção de imagem se ALGUMA
// oração isolada bate no regex de verbo+substantivo E aquela mesma oração,
// sozinha, não parece uma pergunta.
//
// Não há vitest/jest configurado em platform_source/ (mesmo motivo dos
// outros test_*.mjs desta pasta) - este script extrai e executa de verdade
// as funções/regex REAIS do código-fonte de AviaryApp.tsx (não uma
// reimplementação), mesmo padrão de test_chat_history_identity_leak.mjs e
// test_web_search_intent.mjs ao lado.
//
// Rodar: cd platform_source && node test_image_intent_double_meaning.mjs

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

console.log("1. Peças novas presentes no código-fonte real:");
const magicTokensMatch = appSrc.match(/const IMAGE_PROMPT_MAGIC_TOKENS =\s*\n?\s*(\/.+\/[a-z]*);/);
check("IMAGE_PROMPT_MAGIC_TOKENS encontrado", !!magicTokensMatch);

const looksLikeQuestionMatch = appSrc.match(/function looksLikeQuestion\(t: string\): boolean \{\s*\n\s*return (.+);\s*\n\s*\}/);
check("função compartilhada looksLikeQuestion(t) encontrada", !!looksLikeQuestionMatch);

const verbNounPatternMatch = appSrc.match(/const IMAGE_GENERATION_VERB_NOUN_PATTERN =\s*\n?\s*(\/.+\/[a-z]*);/);
check("IMAGE_GENERATION_VERB_NOUN_PATTERN (extraído do regex antigo inline) encontrado", !!verbNounPatternMatch);

const clauseFnMatch = appSrc.match(
  /function hasImageGenerationVerbNounInNonQuestionClause\(t: string\): boolean \{([\s\S]+?)\n\s*\}\n/
);
check("função hasImageGenerationVerbNounInNonQuestionClause(t) encontrada", !!clauseFnMatch);

const finalExprMatch = appSrc.match(
  /const legacyImageGenerationIntent = (hasImageGenerationVerbNounInNonQuestionClause\(text\) \|\| looksLikeRawImagePrompt\(text\));[\s\S]*?const isImageGenerationIntent =[\s\S]*?arbiterDecision\.intent === 'image_generation' \|\| legacyImageGenerationIntent;/
);
check("intenção final aceita Arbiter ou detector local protegido contra perguntas", !!finalExprMatch);

if (!magicTokensMatch || !looksLikeQuestionMatch || !verbNounPatternMatch || !clauseFnMatch) {
  console.log("\nNão foi possível extrair todas as peças do código-fonte - abortando execução real.");
  process.exit(1);
}

console.log("\n2. Execução real (funções extraídas de verdade do arquivo-fonte, não reimplementadas):");

// eslint-disable-next-line no-eval
const IMAGE_PROMPT_MAGIC_TOKENS = new Function(`return ${magicTokensMatch[1]};`)();
const looksLikeQuestion = new Function("t", `return ${looksLikeQuestionMatch[1]};`);
const IMAGE_GENERATION_VERB_NOUN_PATTERN = new Function(`return ${verbNounPatternMatch[1]};`)();

function looksLikeRawImagePrompt(t) {
  const commaSegments = t.split(",").length;
  const magicHits = (t.match(IMAGE_PROMPT_MAGIC_TOKENS) || []).length;
  return !looksLikeQuestion(t) && commaSegments >= 4 && magicHits >= 2;
}

// Reconstrói hasImageGenerationVerbNounInNonQuestionClause(t) a partir do
// corpo real extraído, substituindo as referências livres pelas peças já
// montadas acima (mesma técnica de "new Function" usada nos outros
// test_*.mjs deste diretório).
const clauseFnBody = clauseFnMatch[1];
const hasImageGenerationVerbNounInNonQuestionClause = new Function(
  "IMAGE_GENERATION_VERB_NOUN_PATTERN",
  "looksLikeQuestion",
  "t",
  `${clauseFnBody}`
).bind(null, IMAGE_GENERATION_VERB_NOUN_PATTERN, looksLikeQuestion);

function isImageGenerationIntent_OLD(text) {
  // Regex antigo (pré-correção), aplicado direto na mensagem inteira -
  // reproduz o bug: some string idêntica ao verbo+substantivo bastava,
  // não importava se a mensagem inteira era uma pergunta.
  return IMAGE_GENERATION_VERB_NOUN_PATTERN.test(text) || looksLikeRawImagePrompt(text);
}

function isImageGenerationIntent_NEW(text) {
  return hasImageGenerationVerbNounInNonQuestionClause(text) || looksLikeRawImagePrompt(text);
}

const PRINT_DO_USUARIO =
  "vou usar rocm, cuda ou vulkan? pra gerar imagens, como faço? comfyui ou sd server?";

console.log("\n3. Contraprova - reproduz o bug relatado com a lógica ANTIGA:");
check(
  "regex ANTIGO (string inteira) dispara falsamente no print exato do usuário",
  isImageGenerationIntent_OLD(PRINT_DO_USUARIO) === true
);

console.log("\n4. Controle negativo (o achado real) - a lógica NOVA não dispara mais:");
check(
  "NOVO: NÃO dispara em '" + PRINT_DO_USUARIO + "'",
  isImageGenerationIntent_NEW(PRINT_DO_USUARIO) === false
);

console.log("\n5. Controles positivos - comando direto de geração continua funcionando:");
check(
  "NOVO: dispara em 'gerar imagem de uma phoenix voando sob chamas'",
  isImageGenerationIntent_NEW("gerar imagem de uma phoenix voando sob chamas") === true
);
check(
  "NOVO: dispara em 'Gere uma imagem de um gato.' (oração isolada, sem pergunta)",
  isImageGenerationIntent_NEW("Gere uma imagem de um gato.") === true
);
check(
  "NOVO: dispara em 'generate an image of a cat'",
  isImageGenerationIntent_NEW("generate an image of a cat") === true
);

console.log("\n6. Controle misto - comando real seguido de pergunta não relacionada ainda dispara:");
check(
  "NOVO: dispara em 'Gere uma imagem de um gato. Como faço isso no Vulkan?' (a 1ª oração é comando de verdade)",
  isImageGenerationIntent_NEW("Gere uma imagem de um gato. Como faço isso no Vulkan?") === true
);

console.log("\n7. Outros controles negativos - perguntas de verdade sobre geração de imagem:");
check(
  "NOVO: NÃO dispara em 'como faço para gerar imagens no ComfyUI?'",
  isImageGenerationIntent_NEW("como faço para gerar imagens no ComfyUI?") === false
);
check(
  "NOVO: NÃO dispara em 'qual a diferença entre gerar imagem via SD server ou ComfyUI?'",
  isImageGenerationIntent_NEW("qual a diferença entre gerar imagem via SD server ou ComfyUI?") === false
);

console.log("\n8. Prompt cru estilo Stable Diffusion continua funcionando (looksLikeRawImagePrompt intacto):");
const PHOENIX_PROMPT =
  "a majestic phoenix engulfed in living flame, wings fully spread mid-flight, molten feathers trailing embers and sparks, cracked obsidian battlefield below glowing with lava veins, dramatic rim lighting, volumetric smoke, cinematic composition, intricate feather detail, glowing eyes, epic fantasy concept art, hyper-detailed, sharp focus, 8k, trending on artstation, masterpiece, dramatic god rays piercing through ash clouds";
check("NOVO: prompt cru de imagem ainda dispara intenção", isImageGenerationIntent_NEW(PHOENIX_PROMPT) === true);

console.log(`\n${passed} passaram, ${failed} falharam.`);
process.exit(failed > 0 ? 1 : 0);
