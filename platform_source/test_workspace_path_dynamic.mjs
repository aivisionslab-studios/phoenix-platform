// test_workspace_path_dynamic.mjs
//
// PHX-FIX (achado real do usuário 2026-08-28, via mensagem direta: "TIRAR
// CAMINHO R:\Phoenix\Workstations, PORQUE NAO FAZ SENTIDO NENHUM... JA
// NAO É MAIS R:\ E SÓ FUNCIONA NA MINHA MAQUINA"): três lugares do
// frontend (ProcessLauncherBar.tsx e ManualModal.tsx, renderizado via
// AviaryApp.tsx) tinham "R:\Phoenix\Workstations\Models\..." cravado como
// literal fixo no JSX, como se fosse um caminho universal - era só o
// drive de uma máquina de desenvolvimento antiga, e nem reflete mais a
// instalação real de quem escreveu aquele texto.
//
// PhoenixPaths.get_workspace() (phoenix_kernel/paths.py) já existe
// exatamente pra resolver isso de forma dinâmica (via storage.json,
// nunca um literal de drive) - só nunca tinha sido exposto pro frontend.
// Este script prova, por inspeção do código-fonte real (mesmo padrão dos
// outros test_*.mjs deste diretório - não há vitest/jest configurado em
// platform_source/):
//
// 1. phoenix_kernel/state.py expõe workspace_path em get_state() (que
//    server.ts repassa sem alteração via GET /api/state - passthrough
//    puro, já coberto por outros testes deste projeto).
// 2. App.tsx busca esse valor e repassa pra ProcessLauncherBar E AviaryApp
//    (que por sua vez repassa pra ManualModal).
// 3. Nenhum dos dois componentes ainda tem "R:\Phoenix\Workstations"
//    cravado como literal fixo - o caminho agora vem sempre de
//    workspacePath, com um aviso honesto (nunca um caminho inventado)
//    quando ainda não foi detectado.
//
// Rodar: cd platform_source && node test_workspace_path_dynamic.mjs

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(__dirname, "..");
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

const statePySrc = fs.readFileSync(path.join(PROJECT_ROOT, "phoenix_kernel", "state.py"), "utf8");
const appSrc = fs.readFileSync(path.join(__dirname, "src", "App.tsx"), "utf8");
const launcherSrc = fs.readFileSync(path.join(__dirname, "src", "components", "ProcessLauncherBar.tsx"), "utf8");
const aviarySrc = fs.readFileSync(path.join(__dirname, "src", "components", "aviary", "AviaryApp.tsx"), "utf8");
const manualModalSrc = fs.readFileSync(path.join(__dirname, "src", "components", "aviary", "ManualModal.tsx"), "utf8");

console.log("1. Backend: workspace_path exposto de verdade em /api/state (via PhoenixPaths, nunca um literal de drive):");
check(
  "state.py::get_state() inclui \"workspace_path\": str(PhoenixPaths.get_workspace())",
  /"workspace_path":\s*str\(PhoenixPaths\.get_workspace\(\)\)/.test(statePySrc)
);
check("state.py importa PhoenixPaths (não reimplementa resolução de caminho)", /from phoenix_kernel\.paths import PhoenixPaths/.test(statePySrc));

console.log("\n2. App.tsx busca /api/state e repassa workspacePath pros dois consumidores:");
check("App.tsx tem estado workspacePath", /const \[workspacePath, setWorkspacePath\] = useState<string \| null>\(null\)/.test(appSrc));
check("App.tsx busca /api/state (não inventa/hardcoda o valor)", /fetch\('\/api\/state'\)/.test(appSrc));
check("App.tsx só aceita workspace_path se vier como string não vazia (nunca fabrica um fallback)", /typeof data\.workspace_path === 'string' && data\.workspace_path/.test(appSrc));
check("<ProcessLauncherBar> recebe workspacePath", /<ProcessLauncherBar[\s\S]{0,300}workspacePath=\{workspacePath\}/.test(appSrc));
check("<AviaryApp> recebe workspacePath em pelo menos 2 pontos de renderização (aviary + split)", (appSrc.match(/workspacePath=\{workspacePath\}/g) || []).length >= 3);

console.log("\n3. ProcessLauncherBar.tsx não tem mais 'R:\\Phoenix\\Workstations' cravado:");
check("nenhum literal 'R:\\\\Phoenix\\\\Workstations' restante no arquivo", !/R:\\\\Phoenix\\\\Workstations/.test(launcherSrc));
check("prop workspacePath declarada na interface do componente", /workspacePath\?:\s*string \| null;/.test(launcherSrc));
check("botão usa workspacePath pra montar o caminho real (não um literal)", /\$\{workspacePath\}\\\\Models\\\\Chat\\\\GGUF\\\\/.test(launcherSrc));
check("sem workspacePath ainda carregado, avisa em vez de inventar um caminho", /Caminho de workspace ainda não detectado/.test(launcherSrc));

console.log("\n4. AviaryApp.tsx repassa workspacePath pro ManualModal:");
check("AviaryApp aceita a prop workspacePath", /workspacePath\?:\s*string \| null;/.test(aviarySrc));
check("<ManualModal> recebe workspacePath", /<ManualModal[\s\S]{0,100}workspacePath=\{workspacePath\}/.test(aviarySrc));

console.log("\n5. ManualModal.tsx não tem mais 'R:\\Phoenix\\Workstations' cravado nos 3 caminhos de modelo:");
check("nenhum literal 'R:\\\\Phoenix\\\\Workstations' restante no arquivo", !/R:\\\\Phoenix\\\\Workstations/.test(manualModalSrc));
check("modelsBase é derivado de workspacePath (não hardcoded)", /const modelsBase = workspacePath \? `\$\{workspacePath\}\\\\Models` : null;/.test(manualModalSrc));
check("sem workspacePath ainda carregado, mostra aviso em vez de inventar caminho", /caminho ainda não detectado/.test(manualModalSrc));

console.log(`\n${passed} passaram, ${failed} falharam.`);
process.exit(failed > 0 ? 1 : 0);
