---
memory_type: procedural
procedure_id: run_phoenix_diffusion
triggers: ["rodar flux", "gerar imagem", "phoenix diffusion", "stable diffusion"]
platform: [windows, linux]
prerequisite_check: ["gpu_vulkan_detected", "phoenix_diffusion_bridge_compiled", "model_files_present"]
---

# Procedimento: gerar imagem com Phoenix Diffusion

## 1. Verificar recursos

Consultar `machine/model_compatibility_matrix.json`. Na RX 580 8GB, modelos Flux
acima de aproximadamente 5,5GB ficam restritos a 512x512; Q8 é bloqueado.

## 2. Usar o runtime integrado

Enviar um `ExecutionPlan` com `runtime="sdxl"` (alias público compatível), o ID do
modelo e `parameters` contendo `prompt`, `width`, `height`, `steps` e `seed`. O
`PhoenixDiffusionDriver` carrega a bridge C ABI incluída no projeto em processo
isolado. Nunca executar CLI, servidor intermediário ou clone externo.

Por padrão, `auto_fit=true`, `max_vram=-0.75` e `stream_layers=true` deixam o fork
escolher o split seguro entre Vulkan e RAM. O prompt permanece UTF-8 literal.

## 3. Limites seguros conhecidos

- Flux Q3_K_S: até 768x768 validado no hardware de referência.
- Flux Q4_K_S: 512x512; 768x768 ou mais pode causar OOM.
- Flux Q8: bloqueado na RX 580 8GB.
- Flux.2: exige VAE e encoders próprios.
- SD 3.5 Large: bloqueado nessa configuração por risco de esgotar toda a RAM.

## 4. Após a execução

Validar que o resultado contém `metrics.output_file` e um PNG não truncado. Registrar
tempo, resolução e uso de memória em `machine/model_compatibility_matrix.json`.
