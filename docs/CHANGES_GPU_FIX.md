# Correção: Phoenix não subia modelo para a GPU (RX 580 / Vulkan)

## Causa raiz

O `qwen3:8b` (modelo padrão) e quase todo o resto do catálogo de LLMs só
existiam como `ollama://...` em `catalog/models.json`. Isso fazia com que
`ModelManager.download_model()` nunca colocasse um `.gguf` físico em disco
— ele só rodava `docker exec ollama ollama pull`. Sem `.gguf` em disco,
`LlamaCppDriver._find_model_file()` nunca encontrava nada, e a REGRA 1
do driver (modelo padrão = sempre Ollama) travava o caminho nativo Vulkan
incondicionalmente. Resultado: toda inferência ia parar no Ollama, que
roda 100% em CPU nesta máquina (RX 580 é GCN4/Polaris, sem suporte ROCm —
confirmado em `phoenix_kernel/knowledge/machine/known_errors_and_fixes.json`).

Havia ainda um bug de contrato: mesmo quando um modelo tinha `.gguf` real
(ex: `qwen3.5-35b-moe`), `ModelManager.download_model()` devolvia uma
STRING de log (`"[OK] Modelo salvo em ..."`) em vez de um `Path`. O driver
fazia `Path(string).exists()`, que é sempre `False` para essa string —
então mesmo um download bem-sucedido caía no fallback Ollama.

## O que foi alterado

1. **`phoenix_kernel/08_models/model_manager.py`**
   `download_model()` agora devolve `Path | None` (o arquivo físico em
   sucesso, `None` em erro ou quando o modelo é Ollama-only) em vez de
   string de log. Download agora vai para um `.part` e só é renomeado no
   final, evitando arquivo corrompido com o nome final em caso de queda.

2. **`catalog/models.json`**
   `qwen3:8b` ganhou uma URL `.gguf` real
   (`Qwen/Qwen3-8B-GGUF` no Hugging Face, Q4_K_M, ~5GB) em vez de só
   `ollama://qwen3:8b`. O tag Ollama original foi preservado no campo
   `ollama_tag` como referência/fallback documentado.

3. **`phoenix_kernel/04_runtime/drivers/llama_cpp.py`**
   - REGRA 1 revisada: o modelo padrão só cai no Ollama (CPU) se **não**
     houver `.gguf` dele em disco. Se houver, roda nativo via Vulkan —
     deixou de ser incondicional.
   - `_read_vram_mb_from_hardware_profile()` corrigido: lia
     `data/config/hardware_profile.json` com chave `gpu.vram_mb`, que
     nunca existiu. Agora lê o arquivo real
     (`phoenix_kernel/knowledge/machine/hardware_profile.json`,
     chave `hardware.gpu.vram_gb`), com fallback para o caminho antigo.

## Correção adicional (regressão encontrada em teste real)

Ao testar a missão "quero rodar IA LOCAL E CRIAR IMAGENS" (download do Flux
para stable-diffusion.cpp), apareceu:
```
[MissionExecutor] Falha crítica no passo 3: 'WindowsPath' object has no attribute 'startswith'
```
Causa: o patch 1 mudou `ModelManager.download_model()` de string para
`Path | None`, e eu ajustei o `llama_cpp.py` para o novo contrato, mas
esqueci de outro chamador: `phoenix_kernel/13_resident/resident_manager.py`
(o `MissionExecutor`), que ainda fazia `result.startswith("[ERRO]")` —
`Path` não tem esse método.

**5. `phoenix_kernel/13_resident/resident_manager.py`**
Ajustado o passo `DOWNLOAD_MODEL` para tratar `None` como falha e `Path`
como sucesso, em vez de checar prefixo de string.

**6. `setup_environment.py`**
Esse arquivo tinha um **template embutido** (`MODEL_MANAGER_PY`) que
recria `model_manager.py` do zero toda vez que é executado
(`create_file(..., write_text(...))` sempre sobrescreve). Se rodasse de
novo, reverteria o patch 1 silenciosamente. Corrigido para gerar a versão
já com o contrato `Path | None`.

Conferido: `resident_manager.py` e `llama_cpp.py` não têm cópias-template
em nenhum instalador, então não corriam esse mesmo risco.

## Correção nova: geração de imagem nunca chegava a rodar (GPU parada em 9%/1,1GB)

Print do Gerenciador de Tarefas confirmou: depois de rodar a missão
"quero rodar IA local e criar imagens", a GPU nunca saiu do baseline do
Windows. Causa raiz, sem relação com os bugs anteriores (esses eram do
caminho de texto/LLM; este é do caminho de imagem):

1. **`reasoning_engine.py`** — o `SYSTEM_PROMPT` que ensina o planejador
   (a IA que monta a missão) só conhecia 4 ações, e nenhuma delas mandava
   efetivamente *rodar* uma geração de imagem. `DOWNLOAD_MODEL` só baixa o
   `.gguf`. Por isso a missão "terminava com sucesso" logo depois do
   download — segundo as regras que a IA recebeu, não faltava nada.
2. **`sd_cpp.py`** — mesmo se a IA tentasse iniciar esse runtime, o
   `SdCppDriver` não tinha `start()`, `stop()` nem `status()`. O
   `RuntimeEngine` sempre chama `driver.start()` antes de `execute()`;
   sem esses métodos, dava `AttributeError` na hora.
3. **`sd_cpp.py`** (bug adicional) — `execute()` esperava receber o
   *nome do arquivo* em `plan.model` (ex: `flux1-schnell-Q4_0.gguf`), mas
   qualquer chamador real passaria o *id do catálogo* (ex: `flux`). Path
   nunca batia.
4. **`reasoning_engine.py`** (bug adicional) — o parser que monta os
   `MissionStep` a partir do JSON da IA descartava o campo `parameters`
   silenciosamente, então mesmo um prompt customizado nunca chegava no
   driver.

**O que foi feito:**

- **`core/enums.py`**: nova ação `GENERATE_IMAGE`.
- **`reasoning_engine.py`**: `SYSTEM_PROMPT` ensina a IA a sempre fechar
  pedidos de imagem com um passo `GENERATE_IMAGE` (com um prompt de teste
  default se o usuário não descreveu nada); parser agora repassa
  `parameters` para o `MissionStep`.
- **`sd_cpp.py`**: ganhou `start()`/`stop()`/`status()`; `execute()`
  agora resolve o id do catálogo pro `.gguf` real via
  `catalog/models.json` (com fallback por busca de nome parecido).
- **`resident_manager.py`**: `MissionExecutor` agora sabe executar
  `GENERATE_IMAGE` — monta um `ExecutionPlan(runtime="sdxl", ...)` e
  chama `RuntimeEngine.execute()`.

**Não relacionado, mas veio junto:** o zip que você mandou nessa mensagem
(`factory.py`, `windows.py`, `linux.py`, `provisioning.py`,
`connectors.json`, de outra conversa) é sobre detecção Windows/Linux para
trocar `winget` por `apt`/AppImage na instalação de pacotes. É trabalho
separado, válido, mas não tem relação com esse bug — não foi integrado
aqui ainda.

## O que ainda depende de você

- Os demais modelos do catálogo (`mistral7b`, `llama3:8b`, `phi3:mini`,
  etc.) continuam só como `ollama://` — ou seja, continuam CPU-only nesta
  máquina. Se quiser rodar algum deles na GPU, é preciso trocar a `url`
  dele por um `.gguf` real do Hugging Face, do mesmo jeito que foi feito
  para o `qwen3:8b`.
- O Ollama em si (via Docker) **não tem como usar a RX 580** — não é bug
  de configuração, é falta de suporte ROCm para GCN4/Polaris. Não adianta
  adicionar `--gpus`/`--device` no `docker run`; isso não muda o fato.
- Na primeira execução do `qwen3:8b` após este patch, a Phoenix vai baixar
  ~5GB do Hugging Face antes de conseguir rodar nativo — é esperado.

## Rodada 3 — `stable-diffusion.cpp` era clonado, mas nunca compilado

**Sintoma:** com os bugs anteriores corrigidos, a missão de imagem chegava
até o fim e falhava com uma mensagem clara: `SdCppDriver: sd-server/sd não
encontrado ... Compile o stable-diffusion.cpp via CMake antes de gerar
imagens.` — progresso real (não travava mais silenciosamente), mas ainda
sem gerar a imagem.

**Causa raiz:** `phoenix_kernel/07_services/provisioning.py`
(`ProvisioningManager._install_git`) só compilava o repo clonado se
`"llama"` estivesse no nome do conector. `stable-diffusion.cpp` é clonado
certinho pra `repos/stable-diffusion.cpp/`, mas a etapa de CMake nunca
rodava pra ele — ficava só como código-fonte, sem `sd-server`/`sd.exe`.

Duas armadilhas extras que a correção precisou cobrir, senão o build
quebraria de outro jeito assim que a compilação passasse a rodar:

1. **Flag CMake errada pro alvo**: `-DGGML_VULKAN=ON` é do llama.cpp;
   stable-diffusion.cpp usa `-DSD_VULKAN=ON`.
2. **Clone sem `--recursive`**: stable-diffusion.cpp depende de
   submódulos git (ggml, libwebp, libwebm). Sem `--recursive` no clone
   (e `git submodule update --init --recursive` num repo já existente),
   o CMake falharia por submódulo vazio mesmo com a flag certa.

**Bônus, achado ao revisar o método:** `subprocess.run([...], shell=True)`
com uma lista de argumentos é um bug latente em Linux — com `shell=True`
e uma lista, o POSIX só executa o primeiro item como comando (`cmake`) e
trata o resto (`..`, `-DGGML_VULKAN=ON`) como argumentos do próprio shell,
não do cmake — silenciosamente ignorados. Em Windows isso não aparece
porque o comportamento de `shell=True` com lista é diferente lá. Removido
o `shell=True` (desnecessário pro `cmake`), corrigindo os dois SOs de
uma vez.

**O que foi feito em `provisioning.py`:**

- `_install_git` agora tem um mapa `_VULKAN_BUILD_TARGETS` (nome do repo
  → flag CMake correta) em vez de um `if "llama" in name` isolado —
  cobre `llama.cpp` (`GGML_VULKAN`) e `stable-diffusion.cpp` (`SD_VULKAN`);
  adicionar um novo repo compilável no futuro é só adicionar uma linha.
- Clone novo agora usa `git clone --recursive`; repo já existente roda
  `git submodule update --init --recursive` depois do `pull` — isso
  também conserta, de forma retroativa, o clone parcial (sem submódulos)
  que já está no seu `repos/stable-diffusion.cpp/` de tentativas
  anteriores.
- Removido `shell=True` das duas chamadas de `cmake`.

**Como testar:** rode a instalação/missão de novo. O log deve mostrar
`Provisioning: Compilando stable-diffusion.cpp com Vulkan (CMake,
-DSD_VULKAN=ON)...` e, no fim, `[OK] Repo 'stable-diffusion.cpp' clonado
e COMPILADO com Vulkan com sucesso!`. Isso pode demorar — é compilação
C++ real, não download. Depois disso, a mesma missão de gerar imagem deve
achar o `sd-server`/`sd.exe` e seguir pra geração de fato.

**Pré-requisito que não é bug de código:** compilar com `-DSD_VULKAN=ON`
exige o Vulkan SDK instalado (headers + `glslc`) — o mesmo SDK que o
llama.cpp já precisa pra compilar com Vulkan. Se o conector `vulkan_sdk`
já rodou com sucesso antes (necessário pro llama.cpp funcionar), esse
pré-requisito já está atendido.

## Rodada 4 — MSVC C1128 ("too many sections") compilando stable-diffusion.cpp

**Sintoma:** com o fix da Rodada 3 aplicado, o build avançou de verdade —
clonou com `--recursive`, configurou com `-DSD_VULKAN=ON` ("Use Vulkan as
backend stable-diffusion" no log), compilou ggml, libwebp, libwebm — e só
quebrou no arquivo fonte principal:
`stable-diffusion.cpp\src\stable-diffusion.cpp(1,1): error C1128: o número
de seções excedeu o limite de formato de arquivo do objeto: compile com
/bigobj`.

**Causa raiz:** não é bug do projeto nem do fix anterior — é um limite
conhecido do compilador MSVC. `stable-diffusion.cpp` junta o código de
vários modelos de imagem (SD, Flux, Qwen Image, Z-Image...) num único
arquivo `.cpp` gigante, e esse arquivo estoura o limite de ~65.535 seções
por objeto COFF que o MSVC usa por padrão. A própria Microsoft documenta
`/bigobj` como a correção para esse erro específico.

**O que foi feito em `provisioning.py`:** quando o SO é Windows
(`os.name == "nt"`), a etapa de configure do CMake agora passa
`-DCMAKE_CXX_FLAGS=/bigobj`. Isso é condicional de propósito: `/bigobj` é
uma flag exclusiva do MSVC — em GCC/Clang (Linux) ela nem existe e
quebraria a build lá, por isso só entra no branch Windows.

**Como testar:** rode a mesma missão de novo. Como o `build/` do
stable-diffusion.cpp já foi configurado numa tentativa anterior (sem
`/bigobj`), o CMake vai reconfigurar o cache com a flag nova
automaticamente ao rodar de novo — não precisa apagar a pasta `build`
manualmente. O log deve passar do arquivo `stable-diffusion.cpp` sem o
erro C1128 e continuar até `sd-server.exe`/`sd.exe` aparecerem em
`build/bin/Release/` (ou `build/Release/`).

## Rodada 5 — Build single-thread e timeout curto demais (`--parallel` + timeout 1800s)

**Sintoma esperado (preventivo, ainda não reportado em log):** com o
`/bigobj` resolvido, a compilação do `stable-diffusion.cpp` passaria a
avançar, mas o passo `cmake --build . --config Release` não paraleliza
builds MSBuild/MSVC por padrão — o CMake compila essencialmente em
single-thread mesmo havendo 24 threads disponíveis no Xeon E5-2690 v3.
Combinado com o timeout de 600s (10 min) que já existia no código, um
arquivo tão grande quanto `stable-diffusion.cpp` (o mesmo que estourou o
C1128) corria risco real de estourar o timeout no meio da compilação — o
processo seria morto pelo `subprocess.run(..., timeout=600)` sem nenhum
erro de compilador no log, parecendo um travamento sem causa aparente.

**O que foi feito em `provisioning.py`:** o comando de build agora inclui
`--parallel` (suportado nativamente pelo CMake desde a v3.12, funciona
tanto com MSBuild no Windows quanto com Make/Ninja no Linux) e o timeout
subiu de 600s para 1800s (30 min) como margem de segurança adicional,
já que tempo de build C++ real varia bastante por máquina mesmo com
paralelismo.

**Como testar:** rode a missão de compilação novamente. O log deve
mostrar múltiplos arquivos `.cpp` compilando em paralelo (uso de CPU
Xeon subindo em várias threads simultâneas, visível no Gerenciador de
Tarefas) em vez de um único processo `cl.exe` isolado.

## Rodada 6 — Driver chamando o binário errado (`sd_cpp.py`: `sd-cli` vs `sd-server`)

**Sintoma real reportado:**
```
SdCppDriver: Falha. stderr: [ERROR] common.cpp:325 - error: unknown argument: -o
RuntimeEngine: Execution failed on 'sdxl'. Attempting fallback...
```
A compilação (Rodadas 1-5) funcionou 100%: o log confirma
`sd-cli.vcxproj -> ...\sd-cli.exe` e `sd-server.vcxproj -> ...\sd-server.exe`
gerados com sucesso. Esse já não é mais bug de build — é bug de runtime
no driver Python.

**Causa raiz:** `_find_executable()` em `sd_cpp.py` procurava primeiro por
`sd-server.exe`, que existe (foi compilado), e é esse que o driver acaba
chamando. Só que `sd-server.exe` é um **servidor HTTP** (sobe, escuta
porta, espera requisições POST via `/sdapi/v1/txt2img` ou rotas OpenAI) —
não é uma ferramenta de linha de comando que gera uma imagem e termina.
O driver, porém, foi escrito para invocar um processo por chamada e
esperar ele terminar (`asyncio.create_subprocess_exec` + `communicate`),
passando flags de geração de imagem (`-p`, `-o`, `-H`, `-W`) direto na
linha de comando — isso só existe no `sd-cli`, não no `sd-server`.

Duas outras flags inválidas foram encontradas na mesma chamada, conferindo
a documentação atual do CLI (`examples/cli/README.md` do repositório
leejet/stable-diffusion.cpp):
- `-ngl` e `--device vulkan` não existem no `sd-cli` — são flags do
  `llama.cpp`. O backend Vulkan já vem embutido no binário compilado
  com `-DSD_VULKAN=ON`; não se escolhe em runtime.
- `-s` no `sd-cli` atual significa `--seed`, não "steps" — o driver
  passava `-s 4` pretendendo dizer 4 steps, mas isso rodaria sem erro e
  silenciosamente fixaria a seed em 4 em vez de controlar os steps.

**O que foi feito em `sd_cpp.py`:**
- `_find_executable()` agora procura `sd-cli.exe`/`sd-cli` primeiro, com
  `sd.exe`/`sd` como fallback (builds antigas, pré-split cli/server, que
  geravam um único binário monolítico). `sd-server.exe` foi removido
  dessa lista — não serve para o padrão de invocação deste driver.
- Removidas as flags `-ngl` e `--device vulkan` do comando.
- Trocado `-s 4` por `--steps 4` (nome de flag por extenso, sem
  ambiguidade com seed).

**Como testar:** rode a mesma missão de geração de imagem. O log deve
mostrar o comando sendo montado com `sd-cli.exe` (não `sd-server.exe`)
e a imagem aparecer em `output/images/`.

## Rodada 7 — Flux não é um checkpoint único (`get sd version from file failed`)

**Sintoma real reportado:**
```
ggml_vulkan: 0 = AMD Radeon RX 580 2048SP (AMD proprietary driver) | ...
[ERROR] stable-diffusion.cpp:862 - get sd version from file failed: 'E:\Phoenix\Workstations\Models\StableDiffusion\flux1-schnell-Q4_0.gguf'
RuntimeEngine: Execution failed on 'sdxl'. Attempting fallback...
```
Progresso confirmado: a Rodada 6 funcionou - o `sd-cli.exe` certo foi
chamado, a GPU foi detectada via Vulkan corretamente. O erro agora é
outro, e não é arquivo corrompido nem bug de flag simples.

(A mensagem `Execution failed on 'sdxl'` não é um bug à parte - "sdxl" é
só o nome interno com que o `SdCppDriver` é registrado no dicionário de
drivers do `RuntimeEngine` (cobre toda a família SD1.5/SDXL/Flux, já que
todos rodam no mesmo `sd-cli.exe`), não o modelo real usado.)

**Causa raiz:** Flux não é um checkpoint monolítico como SD1.5/SDXL. O
`.gguf` baixado pelo catálogo (`city96/FLUX.1-schnell-gguf`) contém
*só os pesos do transformer* (DiT) - sem VAE, sem CLIP-L, sem T5XXL
embutidos. Passar esse arquivo em `-m` (flag pensada para checkpoints
completos) faz o `sd-cli` tentar ler um cabeçalho de checkpoint que não
existe nesse arquivo, e falhar com exatamente esse erro - confirmado
contra issues idênticos no repositório oficial (leejet/stable-diffusion.cpp
#1105, SD3.5 com o mesmo sintoma usando `-m` em vez de
`--diffusion-model`). O uso correto documentado no `examples/cli/README.md`
do próprio repo exige `--diffusion-model` para o arquivo do transformer,
mais `--vae`, `--clip_l` e `--t5xxl` apontando para arquivos separados.

**O que foi feito:**
- `catalog/models.json`: entrada `flux` ganhou um bloco `components` com
  URLs e nomes de arquivo para os 3 componentes que faltavam, de mirrors
  não-gated: VAE (`licyk/flux-model`), CLIP-L e T5XXL fp8 (ambos de
  `comfyanonymous/flux_text_encoders` - fp8 em vez de fp16 pra caber
  melhor nos 8GB de VRAM da RX 580).
- `model_manager.py`: novo método `_download_components()`, chamado
  depois do download do modelo principal, baixa qualquer componente
  listado no catálogo (mesmo padrão de `.part` + rename do download
  principal). Contrato de retorno de `download_model()` não mudou -
  ainda devolve só o Path do arquivo principal, então nada que dependa
  desse retorno (como `llama_cpp.py`) foi afetado.
- `sd_cpp.py`: novo `_get_model_info()` lê a entrada crua do catálogo. Em
  `execute()`, se `architecture == "FLUX"`, monta o comando com
  `--diffusion-model` + `--vae`/`--clip_l`/`--t5xxl` (falhando cedo com
  mensagem clara se algum componente ainda não foi baixado); qualquer
  outro modelo continua usando `-m` como antes, sem mudança de
  comportamento para SD1.5/SDXL.

**Como testar:** rode `DOWNLOAD_MODEL` para `flux` de novo primeiro (vai
baixar os ~5.5GB de componentes que faltam: VAE ~335MB, CLIP-L ~246MB,
T5XXL fp8 ~4.9GB). Depois rode a missão de geração de imagem - o log
deve mostrar o comando com `--diffusion-model` em vez de `-m`, e a
imagem deve aparecer em `output/images/` sem o erro `get sd version
from file failed`.
