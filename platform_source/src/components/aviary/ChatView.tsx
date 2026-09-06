import React, { useState, useRef, useEffect } from 'react';
import { 
  Plus, 
  Send, 
  Bot, 
  Paperclip, 
  Image as ImageIcon, 
  Volume2, 
  VolumeX,
  Copy, 
  Check, 
  BrainCircuit, 
  ChevronDown, 
  ChevronUp, 
  Trash2, 
  FileText, 
  X,
  Sliders,
  Terminal,
  Cpu,
  Zap,
  RefreshCw,
  AudioWaveform,
  ExternalLink,
  Download,
  ShieldCheck
} from 'lucide-react';
import { Conversation, AttachedFile, ModelInfo, ProviderConfig, ChatParameters } from '../../types';
import { synthesizeAndPlaySpeech, stopSpeech, DEFAULT_KOKORO_VOICES } from '../../services/piperTtsService';

interface ChatViewProps {
  conversations: Conversation[];
  activeConversation: Conversation | null;
  onSelectConversation: (id: string) => void;
  onNewConversation: () => void;
  onDeleteConversation: (id: string) => void;
  // PHX-FIX: onSendMessage agora recebe também um Map<id, File> com os
  // arquivos brutos (não decodificados) - necessário pra documentos
  // (PDF/DOCX/XLSX/PPTX/MD/TXT), que precisam ser enviados como bytes de verdade
  // via multipart, não como texto/base64 embutido na mensagem de chat.
  // PHX-NEW: 4º parâmetro opcional - qual modelo de imagem usar quando a
  // mensagem disparar a ponte de geração de imagem (ver
  // isImageGenerationIntent em AviaryApp.tsx). '' = automático (default
  // do catálogo, hoje é o Flux); 'sdxl'/'sd15' força o modelo escolhido
  // no seletor abaixo, desde que já esteja baixado no disco.
  onSendMessage: (text: string, files: AttachedFile[], rawFiles?: Map<string, File>, imageModelHint?: string) => Promise<void>;
  onRegenerateMessage: () => Promise<void>;
  isLoading: boolean;
  providers: ProviderConfig[];
  availableModels: ModelInfo[];
  selectedModelId: string;
  onSelectModel: (modelId: string) => void;
  parameters: ChatParameters;
  onToggleParameters: () => void;
  onScanProviders?: () => Promise<void>;
  isScanning?: boolean;
  onOpenStandalone?: () => void;
  // PHX-FIX (varredura 2026-08-21, achado 1.3): o rodapé dizia "Conectado à
  // Phoenix Engine (Porta :8000)" incondicionalmente, sem essa prop -
  // mesmo com o Engine desligado. AviaryHeader.tsx já recebe e usa
  // engineOnline corretamente (linha ~145); só faltava repassar pra cá.
  engineOnline?: boolean;
}

export const ChatView: React.FC<ChatViewProps> = ({
  conversations,
  activeConversation,
  onSelectConversation,
  onNewConversation,
  onDeleteConversation,
  onSendMessage,
  isLoading,
  availableModels,
  selectedModelId,
  onSelectModel,
  parameters,
  onToggleParameters,
  onScanProviders,
  isScanning = false,
  onOpenStandalone,
  engineOnline = false,
}) => {
  const [inputText, setInputText] = useState('');
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  // PHX-NEW: guarda o File bruto do navegador ao lado do AttachedFile
  // decodificado - só usado internamente aqui, nunca sai deste componente
  // exceto via onSendMessage(). Não entra no AttachedFile em si porque
  // esse tipo é serializado pro cache local de conversas (File não é
  // serializável em JSON).
  const rawFilesRef = useRef<Map<string, File>>(new Map());
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  // PHX-FIX (varredura 2026-08-21 rodada 2, achado do piperTtsService):
  // synthesizeAndPlaySpeech() já devolve honestamente qual motor falou de
  // verdade (`engine: 'Kokoro TTS (Local)'` vs `'Web Speech API
  // (Fallback)'` quando o backend falha) - mas o retorno era descartado
  // aqui, então o rótulo do botão continuava aparecendo mesmo quando quem
  // falou foi a voz genérica do navegador. Agora guarda o motor real pra
  // mostrar isso na UI.
  const [speakingEngine, setSpeakingEngine] = useState<string | null>(null);
  // PHX-NEW (2026-08-23, pedido do usuário: "reverso da transcrição" - botão
  // de download do áudio gerado por mensagem, igual ao "clipe" que já existe
  // pra msg.downloadFile). Guarda por msg.id porque o áudio de uma resposta
  // antiga continua baixável mesmo depois de já ter tocado (não expira ao
  // trocar de mensagem, só é sobrescrito se a MESMA mensagem for relida com
  // uma voz diferente). Só é preenchido quando o motor real foi o Kokoro
  // (data.audioUrl) - a voz de fallback do navegador (Web Speech API) nunca
  // produz um arquivo, então nunca aparece aqui, de propósito.
  const [messageAudioUrls, setMessageAudioUrls] = useState<Record<string, string>>({});
  // PHX-NEW (2026-08-23, troca Piper -> Kokoro-82M): default virou 'auto'
  // (detecção automática de idioma pelo backend) em vez de uma voz Piper
  // fixa em português.
  const [selectedVoiceId, setSelectedVoiceId] = useState<string>('auto');
  // PHX-NEW (pedido do usuário: "já temos [Flux/SDXL/SD1.5] baixados...
  // só trocar via phoenix"): '' = automático/default do catálogo (Flux
  // hoje); 'sdxl'/'sd15' força esse modelo na ponte direta de imagem do
  // chat (POST /api/generate-image -> model_hint -> ModelRegistry.resolve,
  // que já suportava isso - só faltava o frontend deixar escolher).
  const [selectedImageModelHint, setSelectedImageModelHint] = useState<string>('');
  // PHX-FIX (2026-08-22, achado real: usuário reportou "foi usado somente
  // flux porque é o unico modelo baixado" - o seletor acima era 3 opções
  // FIXAS (Flux/SDXL/SD1.5), escritas quando essa era a situação real do
  // usuário na época - qualquer outro modelo de imagem baixado depois
  // (Kontext, Flux2, Juggernaut, DreamShaper, ou até um Flux com nome de
  // arquivo diferente) nunca aparecia, porque o seletor não lia o disco,
  // só mostrava rótulos escritos à mão. Agora busca em
  // GET /api/models/image-models (novo endpoint - reaproveita o mesmo
  // scanner que o backend já usa pra resolver sozinho, ver
  // ResidentManager._discover_installed_image_models) o que está
  // REALMENTE baixado, e monta as opções a partir disso. "Auto" continua
  // sendo a primeira opção (deixa o backend decidir, mesma lógica de
  // sempre) - só some o hardcode das outras.
  const [installedImageModels, setInstalledImageModels] = useState<{ name: string; architecture: string }[]>([]);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      fetch('/api/models/image-models')
        .then((r) => (r.ok ? r.json() : { models: [], ready: false }))
        .then((data) => {
          // Não apaga uma lista válida quando o Engine ainda está subindo ou
          // quando o scan falha transitoriamente. Quando ready=true, inclusive
          // uma lista vazia é um resultado real e pode substituir a anterior.
          if (!cancelled && data?.ready !== false && Array.isArray(data?.models)) {
            setInstalledImageModels(data.models);
          }
        })
        .catch(() => {
          // O polling tenta novamente; falha da Engine nunca quebra o chat.
        });
    };
    refresh();
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener('focus', refresh);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener('focus', refresh);
    };
  }, []);

  const [expandedThinking, setExpandedThinking] = useState<Record<string, boolean>>({});

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [activeConversation?.messages, isLoading]);

  const handleSend = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if ((!inputText.trim() && attachedFiles.length === 0) || isLoading) return;

    const currentText = inputText;
    const currentFiles = [...attachedFiles];
    const currentRawFiles = new Map(rawFilesRef.current);

    setInputText('');
    setAttachedFiles([]);
    rawFilesRef.current.clear();

    await onSendMessage(currentText, currentFiles, currentRawFiles, selectedImageModelHint);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    Array.from(files).forEach((file: File) => {
      const isImg = file.type.startsWith('image/');
      // PHX-FIX: extensões binárias que precisam ir pro Document Engine
      // via multipart (bytes de verdade), nunca lidas como texto - ler um
      // PDF/DOCX/XLSX/PPTX com readAsText() corrompe o conteúdo (são
      // formatos binários, não UTF-8), produzindo uma string ilegível que
      // nunca foi utilizável em lugar nenhum.
      const lowerName = file.name.toLowerCase();
      const isDocument = /\.(pdf|docx|xlsx|pptx|md|txt)$/i.test(lowerName);
      // PHX-FIX (auditoria 2026-08-20, "Aviary Chat audio routing"): achado
      // real - áudio anexado no chat (.mp3/.wav/etc.) caía no `else` de
      // baixo e era lido com readAsText(), corrompendo os bytes binários E
      // nunca guardando o File bruto em rawFilesRef.current. Sem o File
      // bruto, AviaryApp.tsx não tinha como montar o multipart pro
      // /api/transcribe e o áudio corrompido acabava indo pro chat de texto
      // normal - a causa raiz do erro "Unexpected token '<'" relatado pelo
      // usuário. Áudio agora é tratado igual documento/imagem: guarda o
      // File bruto, nunca lê como texto.
      const isAudio = /\.(mp3|wav|m4a|ogg|flac|aac|webm)$/i.test(lowerName);
      const fileId = Math.random().toString();

      if (isDocument || isAudio) {
        // Não lê o conteúdo no navegador - guarda só o File bruto pra
        // mandar como multipart depois. O "content" fica vazio de
        // propósito (nunca foi usado de verdade pra documento/áudio binário).
        rawFilesRef.current.set(fileId, file);
        setAttachedFiles((prev) => [
          ...prev,
          { id: fileId, name: file.name, size: file.size, type: file.type, content: '', isImage: false },
        ]);
        return;
      }

      if (isImg) {
        // PHX-FIX: além do data URL (usado só pra preview/thumbnail na UI),
        // guarda o File bruto no mesmo rawFilesRef.current dos documentos -
        // é o que AviaryApp.tsx precisa pra mandar a imagem de verdade como
        // multipart pro /api/describe-image (MiniCPM-V via mtmd-cli). Sem
        // isso, o handler de imagem em AviaryApp.tsx não teria como montar
        // o FormData (o data URL sozinho não reconstrói o File original
        // sem uma conversão extra, e nenhum código fazia essa conversão).
        rawFilesRef.current.set(fileId, file);
      }

      const reader = new FileReader();
      reader.onload = (event) => {
        const content = event.target?.result as string;
        setAttachedFiles((prev) => [
          ...prev,
          { id: fileId, name: file.name, size: file.size, type: file.type, content, isImage: isImg },
        ]);
      };

      if (isImg) {
        reader.readAsDataURL(file);
      } else {
        reader.readAsText(file);
      }
    });

    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removeAttachedFile = (fileId: string) => {
    setAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
    rawFilesRef.current.delete(fileId);
  };

  const copyToClipboard = (text: string, msgId: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(msgId);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const speakText = async (text: string, msgId: string) => {
    if (speakingId === msgId) {
      stopSpeech();
      setSpeakingId(null);
      setSpeakingEngine(null);
      return;
    }

    setSpeakingId(msgId);
    setSpeakingEngine(null);
    const result = await synthesizeAndPlaySpeech(text, {
      voiceId: selectedVoiceId,
      onStart: () => setSpeakingId(msgId),
      onEnd: () => { setSpeakingId(null); setSpeakingEngine(null); },
      onError: () => { setSpeakingId(null); setSpeakingEngine(null); },
    });
    setSpeakingEngine(result.engine);
    // PHX-NEW (2026-08-23): só guarda o link de download quando quem falou
    // de verdade foi o Kokoro (audioUrl presente) - se caiu no fallback do
    // navegador não existe arquivo nenhum pra baixar.
    if (result.audioUrl) {
      setMessageAudioUrls((prev) => ({ ...prev, [msgId]: result.audioUrl! }));
    }
  };

  const toggleThinking = (msgId: string) => {
    setExpandedThinking((prev) => ({
      ...prev,
      [msgId]: !prev[msgId],
    }));
  };

  const selectedModelObj = availableModels.find((m) => m.id === selectedModelId);

  return (
    <div id="chat-view-container" className="flex-1 flex overflow-hidden bg-[#0b0d10] text-[#e7e7e7] h-full font-sans">
      
      {/* Sidebar - Chat History */}
      <aside id="chat-sidebar" className="w-64 border-r border-[#262d35] bg-[#14181d]/90 flex flex-col hidden md:flex shrink-0 h-full overflow-hidden">
        
        {/* New Chat Button */}
        <div className="p-3 border-b border-[#262d35]">
          <button
            id="new-chat-btn"
            onClick={onNewConversation}
            className="w-full flex items-center justify-center space-x-2 py-2.5 px-4 bg-[#ff334b] hover:bg-[#ff334b]/90 text-white font-bold text-xs rounded-xl shadow-lg shadow-[#ff334b]/20 transition-all cursor-pointer"
          >
            <Plus className="w-4 h-4" />
            <span>Nova Conversa</span>
          </button>
        </div>

        {/* Conversation List */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {conversations.length === 0 ? (
            <div className="text-center p-4 text-xs text-slate-500">
              Nenhuma conversa salva ainda.
            </div>
          ) : (
            conversations.map((c) => (
              <div
                key={c.id}
                onClick={() => onSelectConversation(c.id)}
                className={`group flex items-center justify-between p-2.5 rounded-xl text-xs font-medium cursor-pointer transition-all ${
                  activeConversation?.id === c.id
                    ? 'bg-[#ff334b]/15 text-white border border-[#ff334b]/40 font-semibold'
                    : 'text-slate-400 hover:bg-[#262d35]/40 hover:text-white border border-transparent'
                }`}
              >
                <div className="flex items-center space-x-2.5 truncate">
                  <Bot className="w-3.5 h-3.5 text-[#ff334b] shrink-0" />
                  <span className="truncate">{c.title || 'Conversa sem título'}</span>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeleteConversation(c.id);
                  }}
                  className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-rose-400 rounded transition-opacity"
                  title="Excluir conversa"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))
          )}
        </div>

        {/* Sidebar Footer */}
        <div className="p-3 border-t border-[#262d35] text-[11px] text-slate-500 flex items-center justify-between font-mono">
          <span>Aviary WebUI</span>
          <span className="text-[#ff334b]">Porta :3000</span>
        </div>
      </aside>

      {/* Main Chat Workspace */}
      <main id="chat-main-area" className="flex-1 flex flex-col h-full overflow-hidden bg-[#0b0d10]">
        
        {/* Top Chat Bar: Model Selector, Kokoro TTS & Actions (nome interno da rota continua 'piper' por compatibilidade - ver piperTtsService.ts) */}
        <div className="p-3 border-b border-[#262d35] bg-[#14181d]/80 flex items-center justify-between px-4 sm:px-6 shrink-0">
          
          <div className="flex items-center space-x-3">
            <span className="text-xs font-medium text-slate-400 hidden sm:inline font-mono">MODELO:</span>
            
            {/* Model Dropdown */}
            <div className="relative">
              <select
                id="active-model-select"
                value={selectedModelId}
                onChange={(e) => onSelectModel(e.target.value)}
                className="bg-[#0b0d10] border border-[#262d35] rounded-xl px-3 py-1.5 text-xs text-white font-semibold focus:ring-1 focus:ring-[#ff334b] focus:border-[#ff334b] appearance-none pr-8 cursor-pointer shadow-sm font-mono"
              >
                {availableModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    [{m.providerType.toUpperCase()}] {m.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-4 h-4 text-slate-400 absolute right-2.5 top-2.5 pointer-events-none" />
            </div>

            {/* PHX-FIX (auditoria completa 2026-08-28): indicativo visual e
                permanente (não é um toast que some) de que o RAG está
                bloqueado pra este provedor por ser de nuvem - ver a trava
                'blockRagOnCloudProviders' em ParametersDrawer.tsx. Só
                aparece quando de fato se aplica, pra não gerar ruído visual
                com provedores locais (Ollama/llama-server/LM Studio), que
                nunca são afetados por esta flag. */}
            {selectedModelObj?.providerType === 'gemini' && parameters.blockRagOnCloudProviders && (
              <span
                title="Este é um provedor de nuvem: o RAG (seus documentos indexados) não é enviado a ele. Desligue em Parâmetros se quiser permitir."
                className="hidden sm:flex items-center gap-1 text-[10px] font-mono text-[#37d67a] bg-[#37d67a]/10 border border-[#37d67a]/30 rounded-lg px-2 py-1"
              >
                <ShieldCheck className="w-3 h-3" />
                RAG bloqueado (nuvem)
              </span>
            )}

            {/* Auto Detect Button */}
            {onScanProviders && (
              <button
                id="auto-detect-models-btn"
                onClick={onScanProviders}
                disabled={isScanning}
                title="Detectar modelos locais no Ollama, llama-server e LM Studio"
                className="flex items-center space-x-1.5 px-2.5 py-1.5 bg-[#0b0d10] hover:bg-[#262d35] text-slate-300 border border-[#262d35] hover:border-[#ff334b] rounded-xl text-xs font-semibold transition-all shadow-sm shrink-0"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${isScanning ? 'animate-spin text-[#ff334b]' : 'text-[#ff334b]'}`} />
                <span className="hidden sm:inline">
                  {isScanning ? 'Varrendo...' : 'Detectar Locais'}
                </span>
              </button>
            )}

            {/* Kokoro Neural Voice Selector */}
            <div className="relative flex items-center bg-[#0b0d10] border border-[#262d35] rounded-xl px-2.5 py-1 text-xs text-slate-200">
              <AudioWaveform className="w-3.5 h-3.5 text-[#ff334b] mr-1.5 shrink-0" />
              <span className="text-[10px] font-mono font-bold text-[#ff334b] mr-1 hidden sm:inline">VOZ (KOKORO):</span>
              <select
                value={selectedVoiceId}
                onChange={(e) => setSelectedVoiceId(e.target.value)}
                className="bg-transparent border-none text-xs font-semibold text-slate-200 focus:outline-none appearance-none pr-5 cursor-pointer"
                title="Selecione o idioma/voz neural (Kokoro-82M) ou deixe em automático"
              >
                {DEFAULT_KOKORO_VOICES.map((v) => (
                  <option key={v.id} value={v.id} className="bg-[#14181d] text-white">
                    {v.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3 h-3 text-slate-400 absolute right-2 pointer-events-none" />
            </div>

            {/* PHX-FIX (2026-08-22): seletor de modelo de imagem - qual
                modelo usar quando o chat detectar intenção de gerar
                imagem (ver isImageGenerationIntent em AviaryApp.tsx).
                Antes: 3 opções fixas (Flux/SDXL/SD1.5) hardcoded, cegas
                pro que está de fato baixado. Agora: "Auto" (deixa o
                backend escolher, mesma lógica de sempre - o que já está
                instalado, mais recente primeiro) + uma opção por modelo
                REALMENTE encontrado em Models/Image (installedImageModels,
                buscado via GET /api/models/image-models acima). */}
            <div className="relative flex items-center bg-[#0b0d10] border border-[#262d35] rounded-xl px-2.5 py-1 text-xs text-slate-200">
              <ImageIcon className="w-3.5 h-3.5 text-[#ff334b] mr-1.5 shrink-0" />
              <span className="text-[10px] font-mono font-bold text-[#ff334b] mr-1 hidden sm:inline">IMAGEM:</span>
              <select
                value={selectedImageModelHint}
                onChange={(e) => setSelectedImageModelHint(e.target.value)}
                className="bg-transparent border-none text-xs font-semibold text-slate-200 focus:outline-none appearance-none pr-5 cursor-pointer"
                title="Modelo usado quando o chat gerar uma imagem (lista o que já está baixado no disco)"
              >
                {/* PHX-FIX: rótulo fica só "Auto" (sem chutar qual nome
                    vai ser escolhido) - a resolução real do backend
                    (ModelRegistry.resolve + _resolve_image_model_target)
                    prioriza o que casa com o default do catálogo (Flux)
                    antes do "mais recente baixado", então adivinhar o
                    nome aqui podia mostrar um modelo diferente do que
                    realmente seria usado. */}
                <option value="" className="bg-[#14181d] text-white">Auto</option>
                {installedImageModels.map((m) => (
                  <option key={m.name} value={m.name} className="bg-[#14181d] text-white">
                    {m.name}
                  </option>
                ))}
              </select>
              <ChevronDown className="w-3 h-3 text-slate-400 absolute right-2 pointer-events-none" />
            </div>

            {selectedModelObj?.supportsThinking && (
              <span className="hidden sm:flex items-center space-x-1 text-[10px] bg-purple-500/20 text-purple-300 border border-purple-500/30 px-2 py-0.5 rounded-full font-mono">
                <BrainCircuit className="w-3 h-3" />
                <span>Raciocínio &lt;think&gt;</span>
              </span>
            )}
          </div>

          <div className="flex items-center space-x-2">
            {onOpenStandalone && (
              <button
                onClick={onOpenStandalone}
                className="px-2.5 py-1.5 bg-[#0b0d10] hover:bg-[#262d35] text-slate-300 rounded-lg text-xs font-mono flex items-center space-x-1.5 border border-[#262d35]"
                title="Abrir Aviary em Janela / Aba Separada"
              >
                <ExternalLink className="w-3.5 h-3.5 text-[#ff334b]" />
                <span className="hidden sm:inline">Nova Janela</span>
              </button>
            )}

            <button
              onClick={onToggleParameters}
              className="px-2.5 py-1.5 bg-[#0b0d10] hover:bg-[#262d35] text-slate-300 rounded-lg text-xs font-medium border border-[#262d35] flex items-center space-x-1.5 transition-colors font-mono"
            >
              <Sliders className="w-3.5 h-3.5 text-[#ff334b]" />
              <span className="hidden sm:inline">Temp: {parameters.temperature.toFixed(1)}</span>
            </button>
          </div>

        </div>

        {/* Message Stream */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
          {!activeConversation || activeConversation.messages.length === 0 ? (
            
            /* Welcome Empty Screen */
            <div className="max-w-2xl mx-auto my-auto text-center py-12 px-4">
              <div className="w-16 h-16 rounded-2xl bg-[#ff334b]/10 border border-[#ff334b]/30 mx-auto flex items-center justify-center mb-4 shadow-xl">
                <Bot className="w-8 h-8 text-[#ff334b]" />
              </div>
              <h1 className="text-2xl font-bold text-white mb-2 tracking-tight">
                Phoenix Aviary AI Workspace
              </h1>
              <p className="text-slate-400 text-xs sm:text-sm max-w-md mx-auto mb-8">
                Interface estilo ChatGPT, OpenWebUI e LM Studio para interação de alta performance com modelos locais e nuvem.
              </p>

              {/* Quick Prompt Cards */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-left font-mono">
                <button
                  onClick={() => setInputText("Explique como o Vulkan acelera a inferência de LLMs no chip Polaris RX 580.")}
                  className="p-3 bg-[#14181d] hover:bg-[#262d35]/50 border border-[#262d35] hover:border-[#ff334b]/50 rounded-xl transition-all group"
                >
                  <div className="flex items-center space-x-2 mb-1">
                    <Zap className="w-4 h-4 text-[#ff334b] group-hover:scale-110 transition-transform" />
                    <span className="text-xs font-bold text-white">Vulkan & LLMs Locais</span>
                  </div>
                  <p className="text-[11px] text-slate-400 font-sans">Aceleração de tensores e gerenciamento de VRAM.</p>
                </button>

                <button
                  onClick={() => setInputText("Escreva uma função otimizada em C++ com SIMD para multiplicação de matrizes.")}
                  className="p-3 bg-[#14181d] hover:bg-[#262d35]/50 border border-[#262d35] hover:border-[#ff334b]/50 rounded-xl transition-all group"
                >
                  <div className="flex items-center space-x-2 mb-1">
                    <Terminal className="w-4 h-4 text-[#37d67a] group-hover:scale-110 transition-transform" />
                    <span className="text-xs font-bold text-white">Código de Baixo Nível</span>
                  </div>
                  <p className="text-[11px] text-slate-400 font-sans">Algoritmos de alta densidade e precisão matemática.</p>
                </button>
              </div>

            </div>

          ) : (

            /* Message Thread */
            activeConversation.messages.map((msg) => {
              const isUser = msg.role === 'user';
              const isThinkingExpanded = expandedThinking[msg.id];

              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-4xl mx-auto`}
                >
                  
                  {/* Sender Name */}
                  <div className="flex items-center space-x-2 mb-1 px-1">
                    {!isUser && (
                      <div className="w-5 h-5 rounded-md bg-[#ff334b]/20 border border-[#ff334b]/40 flex items-center justify-center">
                        <Bot className="w-3 h-3 text-[#ff334b]" />
                      </div>
                    )}
                    <span className="text-[11px] font-semibold text-slate-400 font-mono">
                      {isUser ? 'Você' : msg.modelId || 'Phoenix Aviary'}
                    </span>
                    {msg.timestamp && (
                      <span className="text-[10px] font-mono text-slate-600">{msg.timestamp}</span>
                    )}
                  </div>

                  {/* Message Card */}
                  <div
                    className={`rounded-2xl p-4 text-xs sm:text-sm leading-relaxed max-w-full shadow-lg ${
                      isUser
                        ? 'bg-[#ff334b] text-white rounded-tr-none font-medium'
                        : 'bg-[#14181d] border border-[#262d35] text-slate-200 rounded-tl-none'
                    }`}
                  >
                    {msg.image && (
                      <div className="mb-3">
                        <img
                          src={msg.image}
                          alt="Anexo"
                          className="max-h-60 rounded-lg object-contain border border-[#262d35]"
                        />
                      </div>
                    )}

                    {msg.files && msg.files.length > 0 && (
                      <div className="mb-3 space-y-1.5">
                        {msg.files.map((f) => (
                          <div
                            key={f.id}
                            className="flex items-center space-x-2 bg-[#0b0d10] p-2 rounded-lg border border-[#262d35] text-xs font-mono"
                          >
                            <FileText className="w-4 h-4 text-[#ff334b]" />
                            <span className="truncate">{f.name}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Reasoning Block for DeepSeek-R1 */}
                    {msg.thinking && (
                      <div className="mb-3 bg-purple-950/30 border border-purple-800/40 rounded-xl overflow-hidden">
                        <button
                          onClick={() => toggleThinking(msg.id)}
                          className="w-full flex items-center justify-between p-2.5 bg-purple-900/20 text-purple-300 font-mono text-[11px] font-semibold hover:bg-purple-900/30 transition-colors"
                        >
                          <div className="flex items-center space-x-2">
                            <BrainCircuit className="w-3.5 h-3.5 text-purple-400" />
                            <span>Processo de Raciocínio (&lt;think&gt;)</span>
                          </div>
                          {isThinkingExpanded ? (
                            <ChevronUp className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronDown className="w-3.5 h-3.5" />
                          )}
                        </button>
                        {isThinkingExpanded && (
                          <div className="p-3 text-[11px] font-mono text-purple-200/80 bg-purple-950/40 border-t border-purple-800/30 whitespace-pre-wrap leading-relaxed max-h-60 overflow-y-auto">
                            {msg.thinking}
                          </div>
                        )}
                      </div>
                    )}

                    <div className="whitespace-pre-wrap font-sans">
                      {msg.content}
                    </div>

                    {/* PHX-NEW (auditoria platform_source 2026-08-20, achado A3): link de
                        download pro arquivo reconstruído por /api/documents/edit - antes,
                        a rota existia no backend mas o resultado (file_base64) não tinha
                        pra onde ir na UI; o usuário nunca conseguia baixar o documento
                        editado, só via o texto bruto na conversa. */}
                    {msg.downloadFile && (
                      <a
                        href={`data:${msg.downloadFile.mimeType};base64,${msg.downloadFile.base64}`}
                        download={msg.downloadFile.name}
                        className="mt-2 flex items-center gap-2 bg-[#0b0d10] hover:bg-[#1a1f26] border border-[#37d67a]/40 hover:border-[#37d67a] text-[#37d67a] px-3 py-2 rounded-lg text-xs font-mono transition-colors w-fit"
                      >
                        <Download className="w-3.5 h-3.5" />
                        <span>Baixar {msg.downloadFile.name}</span>
                      </a>
                    )}

                    {msg.error && (
                      <div className="mt-2 p-2.5 bg-rose-950/50 border border-rose-800/50 rounded-lg text-rose-300 text-xs">
                        ⚠️ {msg.error}
                      </div>
                    )}

                    {/* Assistant Actions & Kokoro TTS (nome interno da rota continua 'piper' por compatibilidade) */}
                    {!isUser && (
                      <div className="mt-3 pt-2.5 border-t border-[#262d35] flex items-center justify-between text-[11px] text-slate-500">
                        {msg.metrics && (
                          <div className="flex items-center space-x-3 font-mono text-[10px]">
                            {msg.metrics.tokensPerSec !== undefined && (
                              <span className="text-[#37d67a] font-semibold flex items-center space-x-1">
                                <Zap className="w-3 h-3" />
                                <span>{msg.metrics.tokensPerSec} tok/s</span>
                              </span>
                            )}
                          </div>
                        )}

                        <div className="flex items-center space-x-1 ml-auto">
                          <button
                            onClick={() => speakText(msg.content, msg.id)}
                            className={`flex items-center space-x-1.5 px-2 py-1 rounded-lg transition-all ${
                              speakingId === msg.id 
                                ? 'bg-[#ff334b]/30 text-[#ff334b] border border-[#ff334b]/40 animate-pulse font-medium text-[10px]' 
                                : 'text-slate-400 hover:text-white hover:bg-[#262d35]'
                            }`}
                            title={speakingId === msg.id && speakingEngine === 'Web Speech API (Fallback)'
                              ? 'Kokoro indisponível — reproduzindo com a voz do navegador'
                              : 'Ouvir Resposta (Kokoro TTS)'}
                          >
                            {speakingId === msg.id ? (
                              <>
                                <AudioWaveform className="w-3.5 h-3.5 text-[#ff334b] animate-spin" />
                                <span className="font-mono text-[10px]">
                                  {speakingEngine === 'Web Speech API (Fallback)' ? 'Lendo (navegador)...' : 'Lendo...'}
                                </span>
                                <VolumeX className="w-3 h-3 text-rose-400 ml-0.5" />
                              </>
                            ) : (
                              <>
                                <Volume2 className="w-3.5 h-3.5" />
                                <span className="text-[10px] font-mono hidden sm:inline">Voz</span>
                              </>
                            )}
                          </button>

                          {/* PHX-NEW (2026-08-23, pedido do usuário: "reverso da
                              transcrição" com download, "assim como tem o clipe"):
                              o backend sempre devolveu o áudio completo em
                              data.audioUrl, mas era descartado depois de tocar -
                              agora que synthesizeAndPlaySpeech() propaga esse valor,
                              basta um <a download> nativo, sem rota nova nenhuma. */}
                          {messageAudioUrls[msg.id] && (
                            <a
                              href={messageAudioUrls[msg.id]}
                              download={`kokoro-audio-${msg.id}.wav`}
                              className="p-1.5 text-slate-400 hover:text-[#37d67a] rounded hover:bg-[#262d35] transition-colors"
                              title="Baixar Áudio Gerado (.wav)"
                            >
                              <Download className="w-3.5 h-3.5" />
                            </a>
                          )}

                          <button
                            onClick={() => copyToClipboard(msg.content, msg.id)}
                            className="p-1.5 text-slate-400 hover:text-white rounded hover:bg-[#262d35] transition-colors"
                            title="Copiar Texto"
                          >
                            {copiedId === msg.id ? (
                              <Check className="w-3.5 h-3.5 text-[#37d67a]" />
                            ) : (
                              <Copy className="w-3.5 h-3.5" />
                            )}
                          </button>
                        </div>
                      </div>
                    )}

                  </div>

                </div>
              );
            })
          )}

          {isLoading && (
            <div className="flex items-center space-x-3 max-w-4xl mx-auto p-4 bg-[#14181d] border border-[#262d35] rounded-2xl">
              <Bot className="w-5 h-5 text-[#ff334b] animate-bounce" />
              <div className="space-y-1">
                <span className="text-xs font-semibold text-slate-300">Processando com {selectedModelId}...</span>
                <p className="text-[11px] text-slate-500 font-mono">Gerando tokens em tempo real</p>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Bottom Input Area */}
        <div className="p-4 border-t border-[#262d35] bg-[#14181d]">
          <div className="max-w-4xl mx-auto">
            
            {attachedFiles.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-2 p-2 bg-[#0b0d10] border border-[#262d35] rounded-xl">
                {attachedFiles.map((f) => (
                  <div
                    key={f.id}
                    className="flex items-center space-x-1.5 px-2.5 py-1 bg-[#14181d] border border-[#262d35] rounded-lg text-xs font-mono text-slate-300"
                  >
                    {f.isImage ? <ImageIcon className="w-3.5 h-3.5 text-[#ff334b]" /> : <FileText className="w-3.5 h-3.5 text-slate-400" />}
                    <span className="truncate max-w-[120px]">{f.name}</span>
                    <button
                      onClick={() => removeAttachedFile(f.id)}
                      className="text-slate-500 hover:text-rose-400"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </div>
                ))}
              </div>
            )}

            <form onSubmit={handleSend} className="relative flex items-center bg-[#0b0d10] border border-[#262d35] focus-within:border-[#ff334b] rounded-2xl shadow-xl transition-all">
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                multiple
                className="hidden"
                // PHX-FIX (auditoria 2026-08-20, "áudio no ChatView/Aviary" -
                // achado real de teste ponta a ponta com Playwright real,
                // não só leitura de código): o handler JS (isAudio, linha
                // ~128) já sabia rotear .mp3/.wav/.m4a/.ogg/.flac/.aac/.webm
                // pro /api/transcribe desde a correção anterior, mas o
                // atributo `accept` deste <input> nunca foi atualizado - o
                // diálogo nativo de seleção de arquivo do navegador filtra
                // por PADRÃO só pros tipos listados aqui, então um usuário
                // clicando no clipe de anexo nem VIA os arquivos de áudio no
                // seletor (precisaria trocar manualmente pra "Todos os
                // arquivos" no diálogo do SO). Confirmado com
                // page.setInputFiles() do Playwright, que contorna o
                // filtro do SO e mascarava esse gap - só apareceu testando
                // a UI de verdade.
                accept="image/*,audio/*,.txt,.md,.json,.js,.ts,.py,.cpp,.java,.pdf,.docx,.xlsx,.pptx,.mp3,.wav,.m4a,.ogg,.flac,.aac,.webm"
              />

              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="p-3 text-slate-400 hover:text-[#ff334b] transition-colors cursor-pointer"
                title="Anexar arquivo ou imagem"
              >
                <Paperclip className="w-5 h-5" />
              </button>

              <input
                type="text"
                value={inputText}
                onChange={(e) => setInputText(e.target.value)}
                placeholder="Envie uma mensagem para o modelo de IA..."
                disabled={isLoading}
                className="flex-1 bg-transparent py-3 px-2 text-xs sm:text-sm text-white placeholder-slate-500 focus:outline-none"
              />

              <button
                type="submit"
                disabled={(!inputText.trim() && attachedFiles.length === 0) || isLoading}
                className="m-1.5 p-2.5 bg-[#ff334b] hover:bg-[#ff334b]/90 disabled:opacity-40 text-white rounded-xl shadow-lg shadow-[#ff334b]/30 transition-all cursor-pointer"
              >
                <Send className="w-4 h-4" />
              </button>
            </form>

            <div className="flex items-center justify-between mt-2 text-[10px] text-slate-500 px-1 font-mono">
              <span>Phoenix Aviary WebUI (Porta :3000)</span>
              <span className={engineOnline ? 'text-[#37d67a]' : 'text-[#8d98a5]'}>
                {engineOnline ? 'Conectado à Phoenix Engine (Porta :8000)' : 'Phoenix Engine offline (Porta :8000)'}
              </span>
            </div>

          </div>
        </div>

      </main>

    </div>
  );
};
