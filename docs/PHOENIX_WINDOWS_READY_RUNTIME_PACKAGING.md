# Phoenix Windows Ready Runtime Packaging Contract — PHASE7B

## Objetivo

A release `windows-ready` não publica o diretório CMake/MSVC de desenvolvimento do Phoenix Llama Runtime. O build validado é promovido para um bundle estável e autocontido em:

`bin/phoenix-llama-runtime/windows-x64/`

O diretório `src/phoenix-llama-runtime/build/` é sempre excluído da distribuição.

## Conteúdo mínimo do bundle

- `llama-server.exe`
- `llama-mtmd-cli.exe`
- `ggml.dll`
- `ggml-base.dll`
- `ggml-cpu.dll`
- `ggml-vulkan.dll`
- `llama.dll`
- `llama-common.dll`
- `llama-server-impl.dll`
- `mtmd.dll`
- `runtime_bundle_manifest.json`

Além do conjunto mínimo, o empacotador copia todas as DLLs emitidas no mesmo diretório dos targets solicitados. Isso permite carregar DLLs auxiliares específicas de uma revisão do runtime sem publicar executáveis/ferramentas não usados pela Phoenix.

## Pipeline

1. `build_windows_vulkan.ps1` compila somente `llama-server` e `llama-mtmd-cli` com Vulkan.
2. O CLI contract e a enumeração de devices são validados.
3. `package_windows_runtime.py` coleta executáveis e DLLs runtime.
4. O bundle recebe `runtime_bundle_manifest.json` com tamanho e SHA-256 de cada arquivo, versão do runtime e hashes do source lock/integrity.
5. O bundle é promovido transacionalmente para `bin/phoenix-llama-runtime/windows-x64/`.
6. Launcher, drivers e instalador preferem esse bundle.
7. Se o bundle estiver ausente, corrompido ou pertencer a outro source lock, a Phoenix cai para o build/reparo do source vendorizado e promove um bundle novo.

## Ready-to-run não significa source-less

O source vendorizado continua na release. Ele é a rota de reparo auditável e reproduzível. O bundle evita recompilação no caminho normal, mas não remove a capacidade de self-heal.

## Dependências de sistema

O bundle não copia DLLs do Windows, Visual C++ Redistributable ou Vulkan Loader de instalações do sistema. O bootstrap Windows continua responsável pelas dependências do ambiente (incluindo Vulkan/Build Tools quando reparo for necessário). Isso evita redistribuir componentes de terceiros/sistema de forma implícita ou sem contrato de licença.

## Autoridade da release

- `.releaseignore`: exclusões de distribuição.
- `release_manifest.json`: artefatos obrigatórios por perfil.
- `runtime_bundle_manifest.json`: integridade do bundle Llama Windows.
- `.gitignore`: sem efeito na release.

## Fail closed

O perfil `windows-ready` não é gerado se:

- qualquer executável/DLL obrigatório estiver ausente ou vazio;
- o manifest do bundle estiver ausente;
- tamanho ou SHA-256 divergir do manifest;
- o bundle não corresponder à versão/source lock vendorizados.

No Windows, o verificador do bundle também executa `llama-server --version`, `--list-devices`, o Phoenix CLI contract e `llama-mtmd-cli --help`.
