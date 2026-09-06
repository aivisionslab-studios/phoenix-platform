import { TtsVoiceOption } from '../types';

// PHX-NEW (2026-08-23, pedido do usuário: "kokoro será motor pra
// transformar texto em áudio... piper lê texto que llm cospe" - Kokoro-82M
// substitui o Piper como motor de voz PADRÃO de toda a Phoenix, não só do
// audiolivro): esta lista era de vozes Piper (um par de arquivos .onnx por
// voz, baixado manualmente do Hugging Face). Agora são as 8 vozes/idiomas
// do Kokoro-82M - mesmo ID usado em runtime/drivers/kokoro_tts.py
// (LANGUAGE_VOICE_MAP) e em documents/audiobook.py; se um mudar, o outro
// tem que mudar junto. A opção "auto" é nova - deixa o backend detectar o
// idioma do próprio texto (py3langid) em vez de forçar uma voz fixa, o que
// faz sentido pra chat/texto livre com o mesmo motor que já faz isso pro
// audiolivro.
//
// PHX-FIX (achado real do usuário 2026-08-24, "se piper nao funciona e
// kokoro é melhor, jogar fora o piper de vez"): o Piper não é mais
// só "não-padrão" - foi removido de vez do backend (PiperDriver apagado,
// ver runtime/engine.py). O nome deste arquivo (`piperTtsService.ts`), a
// rota `/api/tts/piper` e o `type: 'piper-tts'` no provider de
// AviaryApp.tsx continuam com "piper" no nome por serem identificadores
// internos (nunca exibidos ao usuário) - renomear todos eles tocaria
// muitos arquivos pra zero ganho funcional, então foi deixado assim de
// propósito (ver LEIA-ME da versão que fez essa remoção).
export const DEFAULT_KOKORO_VOICES: TtsVoiceOption[] = [
  {
    id: 'auto',
    name: 'Automático (detecta idioma)',
    language: 'auto',
    gender: 'n/a',
    description: 'Detecta o idioma do texto automaticamente (py3langid) e escolhe a voz Kokoro correspondente - recomendado.',
  },
  {
    id: 'pf_dora',
    name: 'Dora (Português BR)',
    language: 'pt',
    gender: 'female',
    description: 'Voz neural feminina para português do Brasil (Kokoro-82M).',
  },
  {
    id: 'af_heart',
    name: 'Heart (Inglês US)',
    language: 'en',
    gender: 'female',
    description: 'Voz neural feminina para inglês americano (Kokoro-82M).',
  },
  {
    id: 'ef_dora',
    name: 'Dora (Espanhol)',
    language: 'es',
    gender: 'female',
    description: 'Voz neural feminina para espanhol (Kokoro-82M).',
  },
  {
    id: 'ff_siwis',
    name: 'Siwis (Francês)',
    language: 'fr',
    gender: 'female',
    description: 'Voz neural feminina para francês (Kokoro-82M).',
  },
  {
    id: 'if_sara',
    name: 'Sara (Italiano)',
    language: 'it',
    gender: 'female',
    description: 'Voz neural feminina para italiano (Kokoro-82M).',
  },
  {
    id: 'zf_xiaobei',
    name: 'Xiaobei (Mandarim)',
    language: 'zh',
    gender: 'female',
    description: 'Voz neural feminina para mandarim (Kokoro-82M).',
  },
  {
    id: 'hf_alpha',
    name: 'Alpha (Hindi)',
    language: 'hi',
    gender: 'female',
    description: 'Voz neural feminina para hindi (Kokoro-82M).',
  },
  {
    id: 'jf_alpha',
    name: 'Alpha (Japonês)',
    language: 'ja',
    gender: 'female',
    description: 'Voz neural feminina para japonês (Kokoro-82M).',
  },
];

// Mapa só pro fallback client-side (Web Speech API do navegador, quando o
// Phoenix Engine está mesmo offline) - não tem nenhuma relação com o
// backend, é só pra escolher um `lang` BCP-47 razoável pro
// SpeechSynthesisUtterance do navegador.
const VOICE_ID_TO_BCP47: Record<string, string> = {
  pf_dora: 'pt-BR', af_heart: 'en-US', ef_dora: 'es-ES', ff_siwis: 'fr-FR',
  if_sara: 'it-IT', zf_xiaobei: 'zh-CN', hf_alpha: 'hi-IN', jf_alpha: 'ja-JP',
};

let currentAudio: HTMLAudioElement | null = null;

export interface SpeakOptions {
  voiceId?: string;
  speed?: number;
  pitch?: number;
  onStart?: () => void;
  onEnd?: () => void;
  onError?: (err: any) => void;
}

export const stopSpeech = () => {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio.currentTime = 0;
    currentAudio = null;
  }
  if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
    window.speechSynthesis.cancel();
  }
};

export const cleanTextForSpeech = (text: string): string => {
  return text
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/```[\s\S]*?```/g, ' Código omitido na leitura. ')
    .replace(/`([^`]+)`/g, '$1')
    .replace(/[*#_~]/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\n+/g, '. ')
    .trim();
};

export const synthesizeAndPlaySpeech = async (
  text: string,
  options: SpeakOptions = {}
): Promise<{ success: boolean; engine: string; audioUrl?: string }> => {
  stopSpeech();

  const clean = cleanTextForSpeech(text);
  if (!clean) {
    options.onEnd?.();
    return { success: false, engine: 'empty_text' };
  }

  // PHX-NEW (2026-08-23): default virou 'auto' (detecção automática de
  // idioma pelo backend, mesmo motor Kokoro do audiolivro) em vez de uma
  // voz Piper fixa em português.
  const voiceId = options.voiceId || 'auto';
  const speed = options.speed || 1.0;

  options.onStart?.();

  try {
    const response = await fetch('/api/tts/piper', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        text: clean,
        voice: voiceId === 'auto' ? '' : voiceId,
        speed,
        pitch: options.pitch || 1.0,
      }),
    });

    if (response.ok) {
      const data = await response.json();
      if (data.audioUrl) {
        const audio = new Audio(data.audioUrl);
        currentAudio = audio;
        audio.playbackRate = speed;

        audio.onended = () => {
          currentAudio = null;
          options.onEnd?.();
        };

        audio.onerror = () => {
          currentAudio = null;
          fallbackToWebSpeech(clean, options);
        };

        await audio.play();
        // PHX-NEW (2026-08-23, pedido do usuário: "reverso da transcrição" -
        // botão de download do áudio gerado, igual ao "clipe" já existente
        // pra outros arquivos). O backend (/api/tts/piper) já devolvia esse
        // data URI completo (data.audioUrl) desde sempre - só que era usado
        // só pra tocar no <audio> aqui dentro e descartado depois. Agora
        // devolve pro chamador (ChatView) poder oferecer o download real,
        // sem nenhuma chamada extra ao backend.
        return { success: true, engine: data.engine || 'Kokoro TTS (Local)', audioUrl: data.audioUrl };
      }
    }

    fallbackToWebSpeech(clean, options);
    return { success: true, engine: 'Web Speech API (Fallback)' };
  } catch {
    fallbackToWebSpeech(clean, options);
    return { success: true, engine: 'Web Speech API (Fallback)' };
  }
};

const fallbackToWebSpeech = (text: string, options: SpeakOptions) => {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
    options.onError?.('Síntese de voz não suportada neste navegador.');
    options.onEnd?.();
    return;
  }

  window.speechSynthesis.cancel();
  // 'auto'/vazio ou um id não reconhecido cai em pt-BR (idioma padrão da
  // Phoenix) - o fallback do navegador não tem como rodar a MESMA detecção
  // de idioma do backend (py3langid não roda no navegador), então isso é
  // só uma aproximação razoável pro caminho de emergência.
  const bcp47 = (options.voiceId && VOICE_ID_TO_BCP47[options.voiceId]) || 'pt-BR';

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = bcp47;
  utterance.rate = options.speed || 1.0;
  utterance.pitch = options.pitch || 1.0;

  utterance.onend = () => options.onEnd?.();
  utterance.onerror = (e) => {
    options.onError?.(e);
    options.onEnd?.();
  };

  window.speechSynthesis.speak(utterance);
};
