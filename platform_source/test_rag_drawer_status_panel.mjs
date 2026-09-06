// test_rag_drawer_status_panel.mjs
//
// Teste pro achado real do usuário + análise técnica detalhada trazida
// por ele: "phoenix nao diz estado atual do RAG de usuario e deveria
// dizer ou direcionar usuario a entender contexto: 25mb ou 10/10 ou 500
// mil caracteres" - e "mensagens de erro precisam virar mensagens
// explicativas em vez de 500/422 opacos".
//
// Achados corrigidos:
// 1. RagDrawer.tsx nunca consumia /api/rag/limits (a rota já existia e já
//    devolvia praticamente tudo - plano, documentos atual/máximo, MB
//    máximo, caracteres máximo, integridade) - painel de estado ausente.
// 2. Erros lançados por onAddFile/onAddDocument (ex.: limite de produto
//    excedido) propagavam sem tratamento - nunca apareciam nesta tela,
//    só um erro silencioso no console do navegador.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const RAG_DRAWER_PATH = path.join(__dirname, "src", "components", "RagDrawer.tsx");
const src = fs.readFileSync(RAG_DRAWER_PATH, "utf-8");

let passed = 0;
let failed = 0;
function check(label, cond) {
  if (cond) { console.log(`  OK   ${label}`); passed++; }
  else { console.log(`  FALHOU ${label}`); failed++; }
}

console.log("\n-- Parte 1: painel de estado consome /api/rag/limits --");
check("busca /api/rag/limits", /fetch\('\/api\/rag\/limits'\)/.test(src));
check("busca ao abrir o drawer (useEffect com isOpen)", /useEffect\(\(\) => \{\s*if \(isOpen\) refreshLimits\(\);/.test(src));
check("exibe documentos atual/máximo", /limits\.current_documents.*limits\.max_documents/.test(src));
check("exibe limite de MB por arquivo", /limits\.max_upload_mb/.test(src));
check("exibe limite de caracteres por documento", /limits\.max_characters/.test(src));
check("exibe status de integridade do repositório", /repository_security/.test(src));

console.log("\n-- Parte 2: erros de upload/adição manual não somem mais em silêncio --");
check("uploadFile captura erro de onAddFile", /const uploadFile = async[\s\S]{0,300}catch \(err: any\)/.test(src));
check("handleManualAdd captura erro de onAddDocument", /const handleManualAdd = async[\s\S]{0,600}catch \(err: any\)/.test(src));
check("estado addError existe", /const \[addError, setAddError\] = useState/.test(src));
check("erro é exibido na tela (não só no console)", /\{addError && \(/.test(src));

console.log("\n-- Parte 3: estado é atualizado após ações que mudam a contagem --");
check("refreshLimits chamado após upload bem-sucedido", /await onAddFile\(file\);\s*await refreshLimits\(\);/.test(src));
check("refreshLimits chamado após adição manual bem-sucedida", /await onAddDocument\(newTitle\.trim\(\), newContent\.trim\(\), selectedType\);[\s\S]{0,200}await refreshLimits\(\);/.test(src));
check("refreshLimits chamado após deletar documento", /await onDeleteDocument\(doc\.id\); await refreshLimits\(\);/.test(src));

console.log(`\n${passed} passaram, ${failed} falharam.`);
process.exit(failed > 0 ? 1 : 0);
