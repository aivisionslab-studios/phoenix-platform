# Phoenix Forge 0.10.0 — Delivery Guard

## Objetivo

O Delivery Guard transforma diagnóstico em proteção operacional. A saída produzida pela GPU fica em quarentena até ser validada. Ter vídeo normal na tela não certifica a GPU para inferência de IA.

## Máquina de decisão

1. O ledger decide se o workload pode iniciar na GPU.
2. Se estiver restrito, a Engine executa diretamente em CPU e avisa o usuário.
3. Se estiver permitido ou monitorado, a primeira saída GPU é validada antes da entrega.
4. Uma falha solicita somente uma repetição limpa na GPU.
5. Duas falhas exigem um controle CPU.
6. Se a CPU produzir saída válida, a saída CPU é entregue, o escopo GPU é bloqueado e a evidência fica registrada.
7. Se a CPU também falhar, a Phoenix classifica falha do pipeline/modelo; não atribui o defeito exclusivamente à GPU.

## Gates

### Texto

- crash e `0xC0000005`;
- stream interrompido;
- saída vazia ou curta;
- caracteres inválidos e bytes NUL;
- repetição degenerada e baixa diversidade;
- término por limite de tokens;
- divergência de texto de referência;
- score/veredito de validador CPU opcional.

### Imagem

- assinatura, dimensões e decodificação;
- imagem uniforme ou com informação extremamente baixa;
- blur e artefatos;
- texto esperado comparado por OCR;
- score/veredito de visão;
- em Delivery Guard, evidência independente é obrigatória.

TrOCR, MiniCPM-V ou serviços equivalentes podem ser conectados pelos adaptadores em `quality_providers.py`. As rotas esperadas são `/v1/ocr`, `/v1/vision/quality` e `/v1/text/quality`.

## Integração Python

```python
from phoenix_forge.modules.delivery_guard import execute_guarded

result = execute_guarded(
    kind="text",
    workload="llm",
    gpu_runner=executar_llm_vulkan,
    cpu_runner=executar_llm_cpu,
    device_name="AMD Radeon RX 580 2048SP",
    runtime="llama.cpp",
    model="qwen3-8b",
)

if result["deliver"]:
    enviar_ao_usuario(result["output"])
else:
    exibir_aviso(result["notice"])
```

O runtime nunca deve enviar diretamente o retorno de `gpu_runner`. Somente `result["output"]`, quando `deliver` for verdadeiro, está autorizado para entrega.

## API

`POST /api/output/delivery-guard` recebe:

```json
{
  "kind": "text",
  "workload": "llm",
  "gpu_outputs": [
    {"text": "//////////", "finish_reason": "stop"},
    {"text": "000000000000", "finish_reason": "stop"}
  ],
  "cpu_output": {"text": "Resposta íntegra.", "finish_reason": "stop"},
  "runtime": "llama.cpp",
  "model": "qwen3-8b",
  "device_name": "AMD Radeon RX 580 2048SP"
}
```

O resultado informa `deliver`, `effective_mode`, trace completo, aviso ao usuário e estado de segurança persistente.
