# Licenças de Terceiros — AIVisions Phoenix Engine

A Phoenix Engine **não versiona nem distribui** código de terceiros. Ela clona diretamente das fontes oficiais durante o provisionamento (ver [`install/common.ps1`](../../install/common.ps1), dicionário `$Repos`), com 45+ repositórios integrados. Cada projeto mantém sua própria licença, em vigor independentemente da orquestração feita pela Phoenix.

## Tecnologias integradas (lista principal)

| Categoria | Projetos |
|---|---|
| Runtime de Inferência | [llama.cpp](https://github.com/ggml-org/llama.cpp), [Ollama](https://github.com/ollama/ollama), [vLLM](https://github.com/vllm-project/vllm), [KoboldCpp](https://github.com/LostRuins/koboldcpp), [LocalAI](https://github.com/mudler/LocalAI), [ExLlamaV2](https://github.com/turboderp-org/exllamav2), [MLC-LLM](https://github.com/mlc-ai/mlc-llm), [SGLang](https://github.com/sgl-project/sglang) |
| Geração de Imagem | [stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp), [ComfyUI](https://github.com/comfyanonymous/ComfyUI), [Automatic1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui), [Forge](https://github.com/lllyasviel/stable-diffusion-webui-forge), [InvokeAI](https://github.com/invoke-ai/InvokeAI), [SwarmUI](https://github.com/mcmonkeyprojects/SwarmUI) |
| Áudio | [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [Piper](https://github.com/rhasspy/piper), [Coqui-TTS](https://github.com/idiap/coqui-ai-TTS), [Kokoro](https://github.com/hexgrad/kokoro), [Applio](https://github.com/IAHispano/Applio) |
| Interfaces | [OpenWebUI](https://github.com/open-webui/open-webui), [LibreChat](https://github.com/danny-avila/LibreChat), [SillyTavern](https://github.com/SillyTavern/SillyTavern), [LobeChat](https://github.com/lobehub/lobe-chat), [Big-AGI](https://github.com/enricoros/big-AGI) |
| Agentes / AI OS | [CrewAI](https://github.com/crewAIInc/crewAI), [AutoGen](https://github.com/microsoft/autogen), [LangGraph](https://github.com/langchain-ai/langgraph), [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter), [OpenHands](https://github.com/All-Hands-AI/OpenHands) |
| Hardware (Windows) | [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) — componente primordial, clonado só no Windows |
| Busca | [SearXNG](https://github.com/searxng/searxng) — não clonado, roda via Docker |

Lista completa e sempre atualizada: [`install/common.ps1`](../../install/common.ps1) (dicionário `$Repos`).

## Créditos de origem

A prova de conceito original — LLM + geração de imagem via Vulkan em uma RX 580, sem CUDA — foi documentada por [Amihart](https://medium.com/@amihart) (primeiro LLM via Vulkan no RX 580, jan/2025) e [DadHacks](https://dadhacks.org) (stable-diffusion.cpp via Vulkan, dez/2025). A Phoenix também se apoia no trabalho de [ggerganov](https://github.com/ggerganov) (llama.cpp, whisper.cpp) e [leejet](https://github.com/leejet) (stable-diffusion.cpp).

## Responsabilidade do usuário

Ao autorizar a instalação de qualquer uma dessas tecnologias através da Phoenix, o usuário concorda automaticamente com os termos de licença do respectivo projeto. A AIVisionsLab recomenda a leitura das licenças originais antes do uso comercial.

## Modelos de IA

Modelos como Qwen, Gemma, Llama, DeepSeek e outros listados no catálogo (`catalog/`) possuem licenças próprias, definidas por seus criadores. A Phoenix apenas detecta, recomenda, baixa e organiza esses modelos — nunca os redistribui sob licença própria.
