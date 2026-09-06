---
memory_type: procedural
procedure_id: run_flux_stable_diffusion_cpp
triggers: ["rodar flux", "gerar imagem", "stable diffusion", "sd-cli", "sd-server"]
platform: [windows, linux]
prerequisite_check: ["gpu_vulkan_detected", "sdcpp_compiled", "model_files_present"]
---

# Procedimento: Executar geração de imagem com stable-diffusion.cpp (Flux / SD)

## Passo 1 — Verificar VRAM disponível antes de escolher o modelo
Consultar `machine/model_compatibility_matrix.json`. Regra dura desta máquina:
modelo Flux (arquivo GGUF do diffusion model) deve ter **≤ ~5GB** para não estourar
a VRAM de 8GB da RX 580 (o resto é ocupado por CLIP/T5/VAE).

## Passo 2 — Montar o comando base
```
sd-cli.exe (ou sd-server.exe) \
  --diffusion-model "<caminho>/flux1-dev-Q3_K_S.gguf" \
  --vae "<caminho>/ae.safetensors" \
  --clip_l "<caminho>/clip_l.safetensors" \
  --t5xxl "<caminho>/t5xxl_fp8_e4m3fn.safetensors" \
  --vae-on-cpu --clip-on-cpu --offload-to-cpu \
  --cfg-scale 3.5 \
  -W 768 -H 768 --steps 28 --seed 42 \
  -p "<prompt>" \
  -o "<saida>.png"
```

## Passo 3 — Flags obrigatórias por plataforma
- **Windows**: `--vae-on-cpu --clip-on-cpu --offload-to-cpu` sempre, para modelos Flux.
- **Linux**: adicionar `--vae-tiling` obrigatoriamente. Sem essa flag, o decode do VAE
  estoura a memória física e derruba o GNOME inteiro (visto em incidente de 2026-06-16).
  Evitar `--backend vulkan0` explícito neste cenário.

## Passo 4 — Resolução segura
- Q3_K_S → até 768x768 (testado, 28 steps, ~2253s / ~37min).
- Q4_K_S → 512x512 seguro (705-1660s dependendo dos steps). 768x768+ dá OOM no
  compute buffer da Vulkan.
- Q8_0 → NÃO recomendar nesta máquina (12.7GB necessários, sempre OOM).

## Passo 5 — Casos especiais
- **Flux.2**: requer VAE próprio (diferente do `ae.safetensors` do Flux 1). Se
  aparecer erro `got shape [3,3,16,512], expected [3,3,32,512]`, é isso — baixar
  o VAE dedicado do Flux.2, não reaproveitar o do Flux 1.
- **Flux Kontext / GGUF "não encontrado"**: checar se o arquivo foi baixado do
  repositório certo. Ver `errors/known_errors_sdcpp.json` → regra do repositório
  leejet vs city96.
- **SD 3.5 Large**: NUNCA sugerir sem confirmação explícita do usuário e sem
  `--offload-to-cpu` testado. Já travou a máquina inteira por exaustão de RAM
  (não só a GPU) nesta máquina.

## Passo 6 — Após execução
Registrar resultado (sucesso/falha, tempo, VRAM) em
`machine/model_compatibility_matrix.json` para a Phoenix aprender com este teste.
