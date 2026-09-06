import { useEffect, useRef, useState } from 'react';
import {
  AudioWaveform,
  Download,
  Loader2,
  AlertTriangle,
  Play,
  Sparkles,
  Type,
  FileText,
  Upload,
  Languages,
  Clock,
} from 'lucide-react';
import { DEFAULT_KOKORO_VOICES, cleanTextForSpeech } from '../../services/piperTtsService';

// PHX-NEW (2026-08-23, pedido do usuário: "o inverso da transcrição" - texto
// vira áudio, com download local, "assim como tem o clipe"). Segunda metade
// do pedido "as duas coisas": além do botão de download inline no chat
// (ChatView.tsx), uma ferramenta dedicada onde QUALQUER texto colado (não
// precisa ser uma mensagem de chat) vira um arquivo de áudio baixável.
//
// Por que chama /api/synthesize-speech e não /api/tts/piper (a mesma rota
// que o chat usa, e desde 2026-08-23 o mesmo motor Kokoro por trás das
// duas): /api/tts/piper tem um AbortController de 15 SEGUNDOS fixo no
// server.ts, pensado pra respostas curtas de chat faladas na hora. Um
// texto colado aqui pode ser bem mais longo (um parágrafo, um artigo
// inteiro) e pode legitimamente demorar mais que isso pra sintetizar no
// hardware do usuário (Xeon E5-2690 v3, sem GPU dedicada pro TTS) - nesse
// caso a rota de chat cairia no fallback de voz do navegador
// silenciosamente, o que aqui seria o pior resultado possível (a pessoa
// pediu pra baixar o ARQUIVO, e a voz do navegador não gera nenhum arquivo
// pra baixar). /api/synthesize-speech não tem esse timeout artificial no
// proxy Node e devolve erro real (não finge sucesso) se o Phoenix Engine
// falhar - por isso é a escolha certa pra esta ferramenta.
//
// Por que não tem controle de velocidade/tom aqui: a rota real do Phoenix
// Engine (api_server.py, SynthesizeSpeechReq) aceita um campo length_scale,
// mas o próprio código do backend documenta que esse parâmetro NÃO é
// repassado pra frente por generate_speech_direct() - ou seja, mudar esse
// valor hoje não muda nada no áudio gerado. Expor um controle que não faz
// nada seria enganar o usuário, então foi deixado de fora de propósito.
//
// PHX-NEW (2026-08-23, pedido do usuário: "pegar um arquivo doc, pdf de 40
// folhas e fazer áudio com voz neural com prosódia bacana tanto em
// português qto em inglês ou outra língua"): segundo modo desta tela -
// "Documento" - sobe um PDF/DOCX/PPTX/TXT/MD inteiro pro novo
// /api/documents/synthesize-audiobook, que usa o mesmo motor Kokoro-82M
// (investigado e testado de verdade nesta sessão contra XTTS-v2 e
// Chatterbox antes de escolher, ver LEIA-ME) pra gerar um ÚNICO arquivo de
// áudio com detecção automática de idioma por trecho do documento. Essa
// chamada pode legitimamente levar dezenas de minutos (documento de 40
// páginas), por isso o polling de progresso em paralelo (ver
// pollAudiobookProgress) - sem isso a tela ficaria travada sem feedback
// nenhum por um tempo que pareceria "quebrado".
const DOCUMENT_ACCEPT = '.pdf,.docx,.pptx,.txt,.md';

interface AudiobookProgress {
  phase?: string;
  current_chunk?: number;
  total_chunks?: number;
  percent?: number;
}

interface AudiobookMeta {
  fileName: string;
  durationSeconds: number | null;
  chunksSynthesized: number | null;
  chunksTotal: number | null;
  languagesUsed: Record<string, number> | null;
  documentLanguage: string | null;
  timedOut: boolean;
}

const LANGUAGE_LABELS: Record<string, string> = {
  pt: 'Português', en: 'Inglês', es: 'Espanhol', fr: 'Francês',
  it: 'Italiano', zh: 'Mandarim', hi: 'Hindi', ja: 'Japonês',
};

function formatDuration(seconds: number | null): string {
  if (!seconds && seconds !== 0) return '--';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}min`;
  if (m > 0) return `${m}min ${s}s`;
  return `${s}s`;
}

// PHX-NEW (2026-08-23, pedido do usuário: "achei que a phoenix instalaria o
// programa" - ele viu o aviso "baixe manualmente no GitHub e coloque na
// pasta" e esperava que a Phoenix baixasse sozinha, como já faz pra outros
// modelos, ex: SD1.5 via botão do Model Hub). Estado/tipos do novo fluxo de
// auto-download do Kokoro (backend: /api/tts/kokoro/status,
// /api/tts/kokoro/download, /api/tts/kokoro/download/status em
// api_server.py, usando o AssetManager já existente + os novos
// catalog/assets/kokoro_model.json e kokoro_voices.json).
type KokoroInstallState = 'checking' | 'installed' | 'missing' | 'downloading' | 'download_error';

export const TextToSpeechView = () => {
  const [mode, setMode] = useState<'text' | 'document'>('text');

  // --- status de instalação do Kokoro (novo, vale pros dois modos) ---
  const [kokoroState, setKokoroState] = useState<KokoroInstallState>('checking');
  const [kokoroPhase, setKokoroPhase] = useState<string | null>(null);
  const [kokoroDownloadError, setKokoroDownloadError] = useState<string | null>(null);

  const checkKokoroStatus = async () => {
    try {
      const r = await fetch('/api/tts/kokoro/status');
      const data = await r.json();
      setKokoroState(data.installed ? 'installed' : 'missing');
    } catch {
      // Sem resposta do Engine (porta 8000 fora do ar) - não é o mesmo
      // problema de "modelo não instalado", então não mostra o banner de
      // download errado; deixa os botões de gerar acusarem o erro real de
      // conexão, que já existia antes desta mudança.
      setKokoroState('installed');
    }
  };

  useEffect(() => {
    checkKokoroStatus();
  }, []);

  const handleDownloadKokoro = async () => {
    setKokoroState('downloading');
    setKokoroDownloadError(null);
    setKokoroPhase('Iniciando download...');

    try {
      const startResp = await fetch('/api/tts/kokoro/download', { method: 'POST' });
      const startData = await startResp.json();

      if (!startResp.ok) {
        throw new Error(startData?.detail || `O Phoenix Engine devolveu status ${startResp.status}.`);
      }

      if (startData.already_downloaded || !startData.job_id) {
        setKokoroState('installed');
        return;
      }

      const jobId = startData.job_id;
      // Mesmo padrão de polling já usado no progresso do audiolivro (ver
      // handleGenerateAudiobook abaixo) - um download de ~340MB pode levar
      // minutos, não dá pra segurar numa única requisição.
      await new Promise<void>((resolve, reject) => {
        const interval = window.setInterval(async () => {
          try {
            const statusResp = await fetch(`/api/tts/kokoro/download/status?job_id=${jobId}`);
            const statusData = await statusResp.json();
            setKokoroPhase(statusData.phase || null);

            if (statusData.status === 'done') {
              window.clearInterval(interval);
              resolve();
            } else if (statusData.status === 'error') {
              window.clearInterval(interval);
              reject(new Error(statusData.error || 'Falha desconhecida ao baixar o Kokoro.'));
            }
          } catch {
            // leitura de progresso falhou uma vez - ignora e tenta de novo
            // no próximo tick, não derruba o download em si.
          }
        }, 1500);
      });

      setKokoroState('installed');
      setKokoroPhase(null);
    } catch (err: any) {
      setKokoroState('download_error');
      setKokoroDownloadError(err?.message || 'Erro desconhecido ao baixar o Kokoro.');
    }
  };

  // --- modo "Texto Livre" (já existia) ---
  const [text, setText] = useState<string>('');
  const [voiceId, setVoiceId] = useState<string>('auto');
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [resultAudioUrl, setResultAudioUrl] = useState<string | null>(null);
  const [resultVoiceLabel, setResultVoiceLabel] = useState<string | null>(null);

  const selectedVoice = DEFAULT_KOKORO_VOICES.find((v) => v.id === voiceId);
  const charCount = text.length;
  const cleanPreviewLength = cleanTextForSpeech(text).length;

  const handleGenerate = async () => {
    const clean = cleanTextForSpeech(text);
    if (!clean) {
      setError('Digite ou cole algum texto antes de gerar o áudio.');
      return;
    }

    setIsGenerating(true);
    setError(null);
    setResultAudioUrl(null);
    setResultVoiceLabel(null);

    try {
      const response = await fetch('/api/synthesize-speech', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: clean, voice: voiceId === 'auto' ? '' : voiceId }),
      });

      const data = await response.json().catch(() => null);

      if (!response.ok || !data || data.ok === false || !data.audio_base64) {
        const backendError =
          (data && (data.error || data.detail)) ||
          `O Phoenix Engine devolveu status ${response.status}.`;
        setError(`Não foi possível gerar o áudio: ${backendError}`);
        return;
      }

      const mimeType = data.mime_type || 'audio/wav';
      setResultAudioUrl(`data:${mimeType};base64,${data.audio_base64}`);
      setResultVoiceLabel(data.voice || voiceId);
    } catch (err: any) {
      setError(
        `Falha de comunicação com o Phoenix Engine: ${err?.message || 'erro desconhecido'}. Confira se o processo do Engine (porta 8000) está rodando.`
      );
    } finally {
      setIsGenerating(false);
    }
  };

  // --- modo "Documento" (novo) ---
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [isProcessingDoc, setIsProcessingDoc] = useState<boolean>(false);
  const [docProgress, setDocProgress] = useState<AudiobookProgress | null>(null);
  const [docError, setDocError] = useState<string | null>(null);
  const [docResultAudioUrl, setDocResultAudioUrl] = useState<string | null>(null);
  const [docResultMeta, setDocResultMeta] = useState<AudiobookMeta | null>(null);

  const handleGenerateAudiobook = async () => {
    if (!selectedFile) {
      setDocError('Selecione um arquivo PDF, DOCX, PPTX, TXT ou MD antes de gerar o audiolivro.');
      return;
    }

    setIsProcessingDoc(true);
    setDocError(null);
    setDocResultAudioUrl(null);
    setDocResultMeta(null);
    setDocProgress({ phase: 'enviando documento para o Phoenix Engine...', current_chunk: 0, total_chunks: 0, percent: 0 });

    // PHX-NEW: polling em paralelo à chamada bloqueante abaixo - mesmo
    // padrão do dual_collab (Arena). Se uma leitura falhar (rede
    // momentaneamente instável), simplesmente ignora e tenta de novo no
    // próximo tick - nunca derruba a geração principal por causa disso.
    const pollInterval = window.setInterval(async () => {
      try {
        const r = await fetch('/api/documents/synthesize-audiobook/progress');
        if (r.ok) {
          const data = await r.json();
          setDocProgress(data);
        }
      } catch {
        // silencioso de propósito - é só uma leitura de progresso
      }
    }, 2000);

    try {
      const formData = new FormData();
      formData.append('file', selectedFile);

      const response = await fetch('/api/documents/synthesize-audiobook', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json().catch(() => null);

      if (!response.ok || !data || data.ok === false || !data.audio_base64) {
        const backendError =
          (data && (data.error || data.detail)) ||
          `O Phoenix Engine devolveu status ${response.status}.`;
        setDocError(`Não foi possível gerar o audiolivro: ${backendError}`);
        return;
      }

      setDocResultAudioUrl(`data:${data.mime_type || 'audio/wav'};base64,${data.audio_base64}`);
      setDocResultMeta({
        fileName: data.file_name || selectedFile.name,
        durationSeconds: data.duration_seconds ?? null,
        chunksSynthesized: data.chunks_synthesized ?? null,
        chunksTotal: data.chunks_total ?? null,
        languagesUsed: data.languages_used ?? null,
        documentLanguage: data.document_language ?? null,
        timedOut: !!data.timed_out,
      });
    } catch (err: any) {
      setDocError(
        `Falha de comunicação com o Phoenix Engine: ${err?.message || 'erro desconhecido'}. Confira se o processo do Engine (porta 8000) está rodando.`
      );
    } finally {
      window.clearInterval(pollInterval);
      setIsProcessingDoc(false);
    }
  };

  return (
    <div id="text-to-speech-view" className="flex-1 overflow-y-auto bg-[#0b0d10] text-[#e7e7e7] p-4 sm:p-6 lg:p-8 font-sans">
      <div className="max-w-4xl mx-auto space-y-6">

        {/* Banner */}
        <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-6 shadow-xl flex items-start space-x-4">
          <div className="p-3 bg-[#ff334b]/10 border border-[#ff334b]/20 rounded-2xl shrink-0">
            <AudioWaveform className="w-8 h-8 text-[#ff334b]" />
          </div>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-white mb-1">
              Texto → Áudio
            </h1>
            <p className="text-xs sm:text-sm text-slate-400 leading-relaxed font-sans">
              Cole um texto ou envie um documento inteiro e baixe o áudio gerado localmente pelo Phoenix Engine — sem depender de nenhum serviço externo.
            </p>
          </div>
        </div>

        {/* Mode toggle */}
        <div className="flex items-center bg-[#0b0d10] p-1 rounded-xl border border-[#262d35] w-fit">
          <button
            onClick={() => setMode('text')}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              mode === 'text' ? 'bg-[#ff334b] text-white shadow-md' : 'text-slate-400 hover:text-white'
            }`}
          >
            <Type className="w-3.5 h-3.5" />
            <span>Texto Livre (Kokoro)</span>
          </button>
          <button
            onClick={() => setMode('document')}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              mode === 'document' ? 'bg-[#ff334b] text-white shadow-md' : 'text-slate-400 hover:text-white'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Documento → Audiolivro (Kokoro)</span>
          </button>
        </div>

        {/* PHX-NEW (2026-08-23): banner de auto-download do Kokoro - vale
            pros dois modos, já que os dois usam o mesmo motor. Some sozinho
            assim que checkKokoroStatus() (rodado ao montar a tela e de novo
            após um download bem-sucedido) confirmar os arquivos no disco. */}
        {kokoroState === 'missing' && (
          <div className="flex items-start space-x-2.5 p-3.5 bg-amber-950/30 border border-amber-800/40 rounded-xl text-amber-200 text-xs leading-relaxed">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <div className="flex-1 space-y-2">
              <span>
                O motor de voz <strong>Kokoro-82M</strong> ainda não está instalado (faltam os arquivos do modelo e das vozes, ~340MB no total). Clique para a própria Phoenix baixar e instalar automaticamente.
              </span>
              <button
                onClick={handleDownloadKokoro}
                className="flex items-center space-x-1.5 bg-amber-500/10 hover:bg-amber-500/20 border border-amber-600/40 text-amber-200 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                <span>Baixar Voz Kokoro Agora (~340MB)</span>
              </button>
            </div>
          </div>
        )}

        {kokoroState === 'downloading' && (
          <div className="flex items-center space-x-2.5 p-3.5 bg-[#14181d] border border-[#262d35] rounded-xl text-slate-300 text-xs">
            <Loader2 className="w-4 h-4 shrink-0 animate-spin text-[#ff334b]" />
            <span>{kokoroPhase || 'Baixando o Kokoro...'} Pode continuar usando outras partes da Phoenix enquanto isso.</span>
          </div>
        )}

        {kokoroState === 'download_error' && (
          <div className="flex items-start space-x-2.5 p-3.5 bg-rose-950/50 border border-rose-800/50 rounded-xl text-rose-300 text-xs">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <div className="flex-1 space-y-2">
              <span>Não foi possível baixar o Kokoro automaticamente: {kokoroDownloadError}</span>
              <button
                onClick={handleDownloadKokoro}
                className="block bg-[#0b0d10] hover:bg-[#1a1f26] border border-rose-800/50 text-rose-300 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors"
              >
                Tentar novamente
              </button>
            </div>
          </div>
        )}

        {mode === 'text' && (
          <>
            {/* Text Input */}
            <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-5 shadow-xl space-y-3">
              <label className="flex items-center justify-between text-xs font-semibold text-slate-300 font-mono">
                <span className="flex items-center space-x-2">
                  <Type className="w-3.5 h-3.5 text-[#ff334b]" />
                  <span>Texto a Converter</span>
                </span>
                <span className="text-[10px] text-slate-500">
                  {charCount} caractere{charCount !== 1 ? 's' : ''}
                  {charCount > 0 && cleanPreviewLength !== charCount && ` (${cleanPreviewLength} após limpeza)`}
                </span>
              </label>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="Cole ou digite aqui o texto que você quer transformar em áudio..."
                rows={8}
                className="w-full bg-[#0b0d10] border border-[#262d35] rounded-xl px-3.5 py-3 text-sm text-slate-200 focus:ring-1 focus:ring-[#ff334b] focus:border-[#ff334b] font-sans resize-y placeholder:text-slate-600"
              />
              <p className="text-[10px] text-slate-500 font-mono leading-relaxed">
                Blocos de código, markdown e tags &lt;think&gt; são removidos automaticamente antes da síntese (mesma limpeza usada na leitura de mensagens do chat).
              </p>
            </div>

            {/* Voice Selector + Generate */}
            <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-5 shadow-xl space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5 font-mono">
                  Voz (Kokoro)
                </label>
                <select
                  value={voiceId}
                  onChange={(e) => setVoiceId(e.target.value)}
                  className="w-full bg-[#0b0d10] border border-[#262d35] rounded-lg px-3 py-2 text-sm text-slate-200 focus:ring-1 focus:ring-[#ff334b] font-mono"
                >
                  {DEFAULT_KOKORO_VOICES.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.name}
                    </option>
                  ))}
                </select>
                {selectedVoice && (
                  <p className="text-[11px] text-slate-500 mt-1.5 font-sans">{selectedVoice.description}</p>
                )}
              </div>

              <button
                onClick={handleGenerate}
                disabled={isGenerating || !text.trim()}
                className="w-full flex items-center justify-center space-x-2 bg-[#ff334b] hover:bg-[#ff334b]/90 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold text-sm px-4 py-2.5 rounded-xl transition-colors"
              >
                {isGenerating ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Gerando áudio no Phoenix Engine...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    <span>Gerar Áudio</span>
                  </>
                )}
              </button>
            </div>

            {/* Error */}
            {error && (
              <div className="flex items-start space-x-2.5 p-3.5 bg-rose-950/50 border border-rose-800/50 rounded-xl text-rose-300 text-xs">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            {/* Result */}
            {resultAudioUrl && (
              <div className="bg-[#14181d] border border-[#37d67a]/30 rounded-2xl p-5 shadow-xl space-y-3.5">
                <h2 className="text-sm font-bold text-white flex items-center space-x-2">
                  <Play className="w-4 h-4 text-[#37d67a]" />
                  <span>Áudio Gerado {resultVoiceLabel ? `(${resultVoiceLabel})` : ''}</span>
                </h2>

                <audio controls src={resultAudioUrl} className="w-full h-10" />

                <a
                  href={resultAudioUrl}
                  download={`phoenix-tts-${resultVoiceLabel || voiceId}-${Date.now()}.wav`}
                  className="flex items-center justify-center gap-2 bg-[#0b0d10] hover:bg-[#1a1f26] border border-[#37d67a]/40 hover:border-[#37d67a] text-[#37d67a] px-3 py-2.5 rounded-xl text-xs font-mono transition-colors w-fit"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Baixar Áudio (.wav)</span>
                </a>
              </div>
            )}
          </>
        )}

        {mode === 'document' && (
          <>
            {/* Aviso sobre o motor Kokoro */}
            <div className="flex items-start space-x-2.5 p-3.5 bg-[#ff334b]/5 border border-[#ff334b]/20 rounded-xl text-slate-300 text-xs leading-relaxed">
              <AudioWaveform className="w-4 h-4 shrink-0 mt-0.5 text-[#ff334b]" />
              <span>
                Este modo usa o mesmo motor neural <strong>Kokoro-82M</strong> do chat e do "Texto Livre" (voz nativa em português, inglês, espanhol, francês, italiano, mandarim, hindi e japonês), mas aqui com <strong>detecção automática de idioma por trecho</strong> do documento inteiro, não só do texto todo de uma vez. Se os arquivos do modelo ainda não estiverem instalados, use o botão de download automático que aparece no topo desta tela. Documentos longos podem levar dezenas de minutos — pode fechar esta aba e voltar depois, o processamento continua no Phoenix Engine.
              </span>
            </div>

            {/* Upload */}
            <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-5 shadow-xl space-y-3">
              <label className="flex items-center space-x-2 text-xs font-semibold text-slate-300 font-mono">
                <FileText className="w-3.5 h-3.5 text-[#ff334b]" />
                <span>Documento (PDF, DOCX, PPTX, TXT ou MD)</span>
              </label>

              <input
                ref={fileInputRef}
                type="file"
                accept={DOCUMENT_ACCEPT}
                className="hidden"
                onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
              />

              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isProcessingDoc}
                className="w-full flex items-center justify-center space-x-2 bg-[#0b0d10] hover:bg-[#1a1f26] border border-dashed border-[#262d35] hover:border-[#ff334b]/50 disabled:opacity-40 text-slate-300 text-sm px-4 py-6 rounded-xl transition-colors"
              >
                <Upload className="w-4 h-4" />
                <span>{selectedFile ? selectedFile.name : 'Clique para escolher um arquivo'}</span>
              </button>

              <button
                onClick={handleGenerateAudiobook}
                disabled={isProcessingDoc || !selectedFile}
                className="w-full flex items-center justify-center space-x-2 bg-[#ff334b] hover:bg-[#ff334b]/90 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold text-sm px-4 py-2.5 rounded-xl transition-colors"
              >
                {isProcessingDoc ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    <span>Gerando audiolivro...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-4 h-4" />
                    <span>Gerar Audiolivro</span>
                  </>
                )}
              </button>
            </div>

            {/* Barra de progresso */}
            {isProcessingDoc && docProgress && (
              <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-5 shadow-xl space-y-2.5">
                <div className="flex items-center justify-between text-xs text-slate-300 font-mono">
                  <span className="capitalize">{docProgress.phase || 'processando...'}</span>
                  <span>
                    {docProgress.total_chunks ? `${docProgress.current_chunk || 0}/${docProgress.total_chunks} blocos` : ''}
                  </span>
                </div>
                <div className="w-full h-2.5 bg-[#0b0d10] rounded-full overflow-hidden border border-[#262d35]">
                  <div
                    className="h-full bg-[#ff334b] transition-all duration-500"
                    style={{ width: `${Math.max(3, docProgress.percent || 0)}%` }}
                  />
                </div>
                <p className="text-[10px] text-slate-500 font-mono">{Math.round(docProgress.percent || 0)}%</p>
              </div>
            )}

            {/* Error */}
            {docError && (
              <div className="flex items-start space-x-2.5 p-3.5 bg-rose-950/50 border border-rose-800/50 rounded-xl text-rose-300 text-xs">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <span>{docError}</span>
              </div>
            )}

            {/* Result */}
            {docResultAudioUrl && docResultMeta && (
              <div className="bg-[#14181d] border border-[#37d67a]/30 rounded-2xl p-5 shadow-xl space-y-3.5">
                <h2 className="text-sm font-bold text-white flex items-center space-x-2">
                  <Play className="w-4 h-4 text-[#37d67a]" />
                  <span>Audiolivro Pronto: {docResultMeta.fileName}</span>
                </h2>

                <div className="flex flex-wrap gap-2 text-[11px] font-mono text-slate-400">
                  <span className="flex items-center space-x-1 bg-[#0b0d10] border border-[#262d35] rounded-full px-2.5 py-1">
                    <Clock className="w-3 h-3" />
                    <span>{formatDuration(docResultMeta.durationSeconds)}</span>
                  </span>
                  {docResultMeta.chunksSynthesized !== null && (
                    <span className="bg-[#0b0d10] border border-[#262d35] rounded-full px-2.5 py-1">
                      {docResultMeta.chunksSynthesized}/{docResultMeta.chunksTotal} blocos sintetizados
                    </span>
                  )}
                  {docResultMeta.languagesUsed && (
                    <span className="flex items-center space-x-1 bg-[#0b0d10] border border-[#262d35] rounded-full px-2.5 py-1">
                      <Languages className="w-3 h-3" />
                      <span>
                        {Object.keys(docResultMeta.languagesUsed)
                          .map((code) => LANGUAGE_LABELS[code] || code)
                          .join(', ')}
                      </span>
                    </span>
                  )}
                </div>

                {docResultMeta.timedOut && (
                  <div className="flex items-start space-x-2 p-2.5 bg-amber-950/40 border border-amber-800/40 rounded-lg text-amber-300 text-[11px]">
                    <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                    <span>O documento era tão longo que o tempo máximo de processamento (90 minutos) foi atingido — este áudio contém só a parte que deu tempo de sintetizar, não o documento inteiro.</span>
                  </div>
                )}

                <audio controls src={docResultAudioUrl} className="w-full h-10" />

                <a
                  href={docResultAudioUrl}
                  download={docResultMeta.fileName}
                  className="flex items-center justify-center gap-2 bg-[#0b0d10] hover:bg-[#1a1f26] border border-[#37d67a]/40 hover:border-[#37d67a] text-[#37d67a] px-3 py-2.5 rounded-xl text-xs font-mono transition-colors w-fit"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Baixar Audiolivro</span>
                </a>
              </div>
            )}
          </>
        )}

      </div>
    </div>
  );
};
