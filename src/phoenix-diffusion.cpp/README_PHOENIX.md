# Phoenix Diffusion.cpp

**Phoenix-maintained diffusion runtime for Phoenix Engine / Phoenix Aviary.**

This repository is a stability-focused fork/distribution based on
`leejet/stable-diffusion.cpp` at the frozen base commit:

`6b3edaaf32cc19e5bb2d819c788bd557eddc8eba` (`6b3edaa`).

Essa base corresponde ao release upstream `master-841-6b3edaa`, publicado em
30/08/2026. Para esta revisão, a opção de Vulkan do stable-diffusion.cpp é
`SD_VULKAN`; `GGML_VULKAN` continua sendo a opção direta do GGML/llama.cpp, mas
não deve ser usada como substituta no nível superior deste projeto.

The goal is deliberately different from following upstream `master`: Phoenix
imports upstream changes only after they pass the Phoenix compatibility matrix.
This protects the production runtime from API/CLI/backend changes landing in a
fast-moving upstream project.

## What Phoenix adds

- a direct C ABI: `phoenix_sd_bridge`
- Python bindings for Phoenix Engine
- model contexts that can remain resident between generations
- resource-plan inputs (`backend`, `params_backend`, `max_vram`, `split_mode`, `auto_fit`)
- a Windows RX580/Vulkan build preset
- dependency commit locking
- an update-candidate workflow that never mutates the production base automatically
- explicit source/license separation; no KoboldCpp source is included

## Windows / RX580 build

```powershell
cd C:\src\phoenix-diffusion.cpp
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap_dependencies.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows_rx580.ps1 -Force
```

O reparador configura `SD_VULKAN=ON`, usa `/bigobj`, limita a compilação a quatro
jobs e mantém o build temporário em `C:\pxb\phxsd` para não estourar o limite de
caminho do MSBuild. Antes de declarar sucesso, ele carrega a DLL e testa a ABI.
O artefato aprovado é copiado para `bin\phoenix_sd_bridge.dll` na raiz Phoenix.
The production Phoenix path calls the library directly; `sd-cli` and
`sd-server` are not required for internal image generation.

## Update policy

Do **not** run `git pull` from leejet into the production branch. To inspect a
new upstream version:

```powershell
.\scripts\check_upstream.ps1
```

This clones a candidate into `.upstream-candidate` and leaves the frozen base
untouched. Only port changes after SD1.5, SDXL, FLUX, Vulkan, CPU/GPU placement,
load/unload and repeated-generation tests pass.

## Licensing

The original stable-diffusion.cpp source remains under its upstream MIT license
and attribution. Phoenix-specific additions are also MIT licensed. See
`LICENSE`, `NOTICE`, and `LICENSES/`.

This is a fork/maintained derivative, not a claim that the original inference
engine was authored from scratch by Phoenix or OpenAI.
