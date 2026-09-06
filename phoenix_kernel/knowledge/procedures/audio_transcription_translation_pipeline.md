---
memory_type: procedural
procedure_id: audio_transcription_translation_pipeline
triggers: ["transcrever audio", "whisper", "legendas", "traduzir video", "srt"]
platform: [windows, linux]
prerequisite_check: ["ffmpeg_installed", "whisper_cpp_compiled", "whisper_model_present"]
---

# Procedimento: Transcrever vídeo/áudio e opcionalmente traduzir para PT-BR

## Passo 1 — Extrair áudio compatível com FFmpeg
Whisper exige WAV cru 16kHz mono 16-bit:
```
ffmpeg -i "<video>.mp4" -ar 16000 -ac 1 -c:a pcm_s16le "<saida>.wav"
```

## Passo 2 — Transcrever com whisper.cpp via Vulkan
```
whisper-cli.exe -m models\ggml-large-v3-turbo.bin -f "<audio>.wav" -l <idioma_origem> --output-txt
```
Confirmar que a linha `ggml_vulkan: Found 1 Vulkan devices: AMD Radeon RX 580 2048SP`
aparece no início — se não aparecer, caiu para CPU (muito mais lento).

## Passo 3 — Regra crítica de idioma
- `-l <idioma_origem>` deve ser o idioma REAL falado no áudio, nunca o idioma
  de destino desejado. Se o áudio é em inglês e o usuário passar `-l pt`, o
  Whisper força padrões fonéticos errados e gera texto sem sentido.
- `--translate` sempre gera **inglês**, nunca outro idioma de destino
  (limitação do Whisper, não configuração).

## Passo 4 — Se o destino for português (ou outro idioma não-inglês)
NÃO usar `--translate`. Em vez disso:
1. Transcrever em inglês com `-l en --output-srt`.
2. Traduzir o `.srt` gerado com um script Python usando `deep-translator`
   (gratuito, sem chave de API) — ver `rag/audio_translation_script.py`.

## Passo 5 — Localização do arquivo gerado
Por padrão, o `.srt`/`.txt` é salvo na MESMA pasta física do WAV processado,
não na pasta do script ou do Whisper.

## Passo 6 — Performance esperada nesta máquina
- Windows: ~150x mais rápido que CPU pura, ~2.6GB VRAM, ~5min para 15min de vídeo.
- Linux (Mesa RADV): dramaticamente mais rápido ainda (23.58s vs 307s para o
  mesmo áudio de 106s nos testes realizados). Preferir Linux se disponível.

## Passo 7 — Importação em editor de vídeo
Arquivo `.srt` traduzido pode ser importado diretamente em softwares como
Filmora/Premiere via Arquivo → Importar → Importar arquivos de legenda.
