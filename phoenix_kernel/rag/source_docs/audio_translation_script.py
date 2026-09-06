# memory_type: rag_reference
# procedure_id: audio_transcription_translation_pipeline (passo 4)
# Requer: pip install deep-translator (gratuito, sem chave de API)
#
# Uso: traduzir um .srt gerado pelo whisper.cpp (idioma origem -> destino)
# sem depender de --translate do Whisper (que só suporta destino=inglês).

from deep_translator import GoogleTranslator


def traduzir_srt(entrada, saida, source="en", target="pt"):
    with open(entrada, "r", encoding="utf-8") as f:
        conteudo = f.read()

    blocos = conteudo.strip().split("\n\n")
    resultado = []

    for bloco in blocos:
        linhas = bloco.split("\n")
        if len(linhas) >= 3:
            numero = linhas[0]
            timestamp = linhas[1]
            texto = " ".join(linhas[2:])
            traduzido = GoogleTranslator(source=source, target=target).translate(texto)
            resultado.append(f"{numero}\n{timestamp}\n{traduzido}")

    with open(saida, "w", encoding="utf-8") as f:
        f.write("\n\n".join(resultado))
    print("Pronto!")


if __name__ == "__main__":
    traduzir_srt(
        r"E:\caminho\video_16k.wav.srt",
        r"E:\caminho\video_16k_ptbr.srt",
        source="en",
        target="pt",
    )
