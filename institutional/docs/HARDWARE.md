# Hardware — AIVisions Phoenix Engine

## Filosofia de suporte a hardware

A Phoenix foi desenhada para aproveitar hardware existente, incluindo máquinas com CPUs de servidor mais antigas e GPUs de gerações passadas, antes de assumir que um upgrade é necessário. A plataforma não é exclusiva para o hardware de referência abaixo — ela classifica e se adapta a qualquer combinação de CPU/GPU/RAM.

## Backends suportados

- **CPU** — sempre disponível como fallback, usado para todo modelo de texto (LLM/chat)
- **Vulkan** — usado em GPUs AMD (incluindo placas mais antigas), usado para toda geração de imagem

## Hardware de referência (testado)

| Componente | Especificação |
|---|---|
| CPU | Intel Xeon E5-2690 v3 · 12c/24t · 3.5GHz (2014) |
| GPU | AMD Radeon RX 580 2048SP · 8GB GDDR5 (Polaris/GCN4) |
| RAM | 32GB DDR4 REG ECC Quad Channel |
| Storage | NVMe + HDD (o instalador escolhe automaticamente o disco mais rápido com espaço suficiente) |
| Backends | CPU, Vulkan |
| OS | Windows 10/11 + WSL2 Ubuntu 22.04 / Ubuntu 26.04 LTS; nativamente também Ubuntu 24.04+ e Debian 12+ |
| Vulkan SDK | 1.4.341.1 |
| Driver AMD | 31.0.21924.61 |

## Política de roteamento de hardware (definitiva)

Diferente de uma estratégia de split dinâmico, a Phoenix usa uma **política fixa**: modelos de texto (LLM/chat) rodam 100% em CPU via llama.cpp; modelos de imagem (SD 1.5/SDXL) rodam 100% em GPU via stable-diffusion.cpp/Vulkan. Isso evita que as duas cargas disputem VRAM ao mesmo tempo.

## GPU Score / Machine Class

O Discovery Engine classifica a máquina em **LOW / MEDIUM / HIGH** (Machine Class) e calcula um **GPU Score** (0–100%), usados pelo Model Catalog para recomendar apenas modelos compatíveis com o hardware detectado — sem tentativa e erro.

## Limites de segurança

A Phoenix respeita:
- Temperatura de operação e sensores em tempo real (via LibreHardwareMonitor no Windows; `/proc`, `/sys`, `lm-sensors`, `lspci`, `lsblk` no Linux);
- Limites de VRAM e RAM antes de iniciar downloads ou provisionamento;
- Compatibilidade de driver/backend antes de tentar execução (`vulkaninfo --summary` valida o backend Vulkan no Linux).

Ver também [RESPONSIBLE_AI](../legal/RESPONSIBLE_AI.md) e [Telemetry Policy](../legal/TELEMETRY_POLICY.md) para o que é monitorado.
