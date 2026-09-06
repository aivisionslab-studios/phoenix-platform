import { useState, useEffect, useRef } from 'react';
import type { ChangeEvent } from 'react';
import {
  Columns3,
  Play,
  Zap,
  Bot,
  Copy,
  Check,
  Trophy,
  Clock,
  BrainCircuit,
  Cpu,
  MessageCircle,
  Globe2,
  CheckCircle2,
  Hourglass,
  Paperclip,
  Image as ImageIcon,
  FileText,
  X,
  History,
  Send,
  FlaskConical,
  AlertTriangle,
} from 'lucide-react';
import { ArenaSlot, ModelInfo, Conversation } from '../../types';

// PHX-NEW (pedido do usuário 2026-08-22: "usuario abre o arena e vai em
// colaboração e os modelos escolhidos tem acesso ao bate papo e conseguem
// entender o contexto... usuario pode continuar via chatbot ou modo
// arena/colaboração"): condensa a conversa ativa do chat num bloco de
// texto pra pré-preencher o tema da colaboração - função PURA (sem
// estado/hooks) pra poder ser testada isoladamente. Prioriza duas coisas
// na hora de cortar por limite de tamanho: (1) a mensagem MAIS RECENTE
// sempre entra inteira (é a pergunta/erro atual, o motivo de abrir a
// colaboração), e (2) quando uma mensagem mais antiga não cabe inteira,
// tenta salvar pelo menos os blocos de código dela (```...```) - o que
// mais importa numa sessão de programação - em vez de perder tudo.
const CHAT_CONTEXT_CHAR_BUDGET = 6000;

function extractCodeBlocksFromText(text: string): string[] {
  const blocks: string[] = [];
  const regex = /```[\s\S]*?```/g;
  let match: RegExpExecArray | null;
  while ((match = regex.exec(text)) !== null) {
    blocks.push(match[0]);
  }
  return blocks;
}

export function buildChatContextSummary(
  conversation: Conversation | null | undefined,
  charBudget: number = CHAT_CONTEXT_CHAR_BUDGET
): string {
  if (!conversation || !Array.isArray(conversation.messages) || conversation.messages.length === 0) return '';
  const messages = conversation.messages.filter((m) => m.role === 'user' || m.role === 'assistant');
  if (messages.length === 0) return '';

  const header = `Contexto da conversa "${conversation.title || 'sem título'}" (chat):\n\n`;
  const included: string[] = [];
  let used = header.length;
  let omittedCount = 0;

  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    const label = m.role === 'user' ? 'Usuário' : 'Assistente';
    const piece = `${label}: ${(m.content || '').trim()}`;

    if (included.length === 0) {
      // A mensagem mais recente entra sempre inteira, nem que estoure
      // sozinha o orçamento.
      included.unshift(piece);
      used += piece.length + 2;
      continue;
    }

    if (used + piece.length + 2 <= charBudget) {
      included.unshift(piece);
      used += piece.length + 2;
      continue;
    }

    // Não coube inteira - tenta salvar pelo menos os blocos de código.
    const codeBlocks = extractCodeBlocksFromText(m.content || '');
    for (const block of codeBlocks) {
      const labeled = `[trecho de código de uma mensagem mais antiga, ${label.toLowerCase()}]\n${block}`;
      if (used + labeled.length + 2 <= charBudget) {
        included.unshift(labeled);
        used += labeled.length + 2;
      }
    }
    omittedCount++;
  }

  let result = header + included.join('\n\n');
  if (omittedCount > 0) {
    result += `\n\n[...${omittedCount} mensagem(ns) mais antiga(s) desta conversa foram omitidas (ou tiveram só o código preservado) por limite de tamanho...]`;
  }
  return result;
}

// PHX-NEW (mesmo pedido acima, "usuario pode continuar via chatbot"):
// formata o resultado da colaboração como uma mensagem de assistente
// legível, pra aparecer na conversa quando o usuário clicar em "Enviar
// resultado pro chat" - também pura, sem estado/hooks.
export function formatCollabResultForChat(result: any): string {
  const header = `**Resultado da colaboração entre dois modelos** (tema: _${(result?.topic || '').trim()}_)\n\n`;
  const statusLine = result?.concluded
    ? `✅ Concluída em ${result?.rounds_completed ?? '?'} rodada(s) - os dois modelos concordaram que o projeto terminou.\n\n`
    : `⏳ Parada (${result?.stopped_reason || 'motivo desconhecido'}) após ${result?.rounds_completed ?? '?'} rodada(s).\n\n`;
  // PHX-FIX (2026-08-22, achado real de auditoria: o usuário mandou o
  // resultado pro chat via "Enviar resultado pro chat" e a linha
  // "VERIFICAÇÃO OBJETIVA: CONFIRMADO..." só apareceu porque o PRÓPRIO
  // MODELO copiou aquele texto do histórico pra dentro da resposta dele -
  // esta função nunca lia `t.objective_check` nem incluía o veredito de
  // verdade. Na tela AO VIVO da Arena (ver bloco JSX logo acima, com
  // `t.objective_check` e a caixa verde/âmbar) o veredito já aparecia
  // desde o v32 - só faltava aqui, no export pro chat. Mesma lógica de
  // confirmado/não-confirmado da caixa colorida da Arena, sem cor
  // (markdown de chat não tem isso) - usa emoji pra distinguir os dois
  // casos igual.
  const transcript = (result?.transcript || [])
    .map((t: any) => {
      const base = `**${t.speaker === 'cpu' ? 'CPU' : 'GPU'} — Rodada ${t.round}:**\n${t.text}`;
      if (!t.objective_check) return base;
      const confirmado = t.objective_check.includes('CONFIRMADO -') && !t.objective_check.includes('NÃO CONFIRMADO');
      const marcador = confirmado ? '🧪' : '⚠️';
      return `${base}\n\n> ${marcador} ${t.objective_check}`;
    })
    .join('\n\n');
  return `${header}${statusLine}${transcript}`;
}

interface ArenaViewProps {
  availableModels: ModelInfo[];
  onExecuteArena: (
    slots: ArenaSlot[],
    prompt: string,
    onUpdateSlots: (updatedSlots: ArenaSlot[]) => void
  ) => Promise<void>;
  // PHX-NEW (pedido do usuário 2026-08-22: "poderíamos usar o arena pra
  // fazer isso... deixar debate tanto no chat qto no arena"): a
  // colaboração de dois modelos (CPU+GPU) ganha um modo dedicado aqui,
  // ao lado do comparador de sempre - continua existindo também via
  // comando /colaborar no chat, esta é só uma segunda porta de entrada
  // com dropdowns em vez de flags de texto.
  onExecuteCollab: (topic: string, cpuModelId: string, gpuModelId: string) => Promise<any>;
  // PHX-NEW (2026-08-22, pedido do usuário depois de ver a tela com a
  // ampulheta piscando o tempo inteiro até as 6 rodadas terminarem TODAS
  // de uma vez, "dá aquela ideia de que travou"): leitura de progresso ao
  // vivo, chamada em POLLING enquanto onExecuteCollab acima ainda está
  // pendente - devolve null quando a leitura falha (rede momentânea) ou
  // quando ainda não há nada publicado; nunca lança.
  onPollCollabProgress: () => Promise<{ active: boolean; topic: string; transcript: any[] } | null>;
  // PHX-NEW (pedido do usuário 2026-08-22: "pode por o clip igual no
  // chatbot pra usuário subir (pescar) qualquer arquivo compatível como
  // ja funciona no chatbot"): processa um arquivo anexado (imagem via
  // /api/describe-image, documento via /api/documents/extract-raw, áudio
  // via /api/transcribe - exatamente as mesmas pontes que o chat normal
  // já usa) e devolve o texto extraído/descrito/transcrito, pra ser
  // injetado no "topic" mandado pro onExecuteCollab acima. `currentTopic`
  // é passado como contexto pro describe-image (mesmo padrão do chat -
  // um prompt do usuário guia a descrição da imagem).
  onProcessAttachment: (file: File, currentTopic: string) => Promise<string>;
  // PHX-NEW (pedido do usuário 2026-08-22: "usuario abre o arena e vai em
  // colaboração e os modelos escolhidos tem acesso ao bate papo... usuario
  // pode continuar via chatbot ou modo arena/colaboração"): a conversa
  // ativa do chat (ou null se nenhuma) - usada só pra pré-preencher o tema
  // da colaboração com o contexto do que já foi discutido (ver
  // buildChatContextSummary acima). Nunca é modificada aqui.
  activeConversation: Conversation | null;
  // Envia o resultado formatado da colaboração de volta pra conversa ativa
  // do chat (ou cria uma nova, se nenhuma existir) - dá ao usuário a opção
  // de continuar de onde a colaboração parou, no chatbot normal.
  onSendResultToChat: (text: string) => void;
  isLoading: boolean;
}

export const ArenaView = ({
  availableModels,
  onExecuteArena,
  onExecuteCollab,
  onPollCollabProgress,
  onProcessAttachment,
  activeConversation,
  onSendResultToChat,
  isLoading,
}: ArenaViewProps) => {
  const [mode, setMode] = useState<'comparar' | 'colaborar'>('comparar');
  const [promptText, setPromptText] = useState('Escreva uma função em C++ otimizada com AVX2/Vulkan para multiplicação de tensores e analise a complexidade Big-O.');
  const [copiedSlot, setCopiedSlot] = useState<string | null>(null);
  const [winnerId, setWinnerId] = useState<string | null>(null);

  // --- Estado do modo "Colaboração" ---
  // Só modelos do runtime llama.cpp/Vulkan aparecem aqui - é o único motor
  // que sabe rodar um modelo inteiro na CPU e outro inteiro na GPU (ver
  // hardware_fit.py/dual_collab.py no backend). Modelos de nuvem (Gemini)
  // ou outros proxies não se aplicam a essa função.
  const llamaModels = availableModels.filter((m) => m.providerType === 'llama-server');
  const [collabTopic, setCollabTopic] = useState('');
  const [collabCpuModel, setCollabCpuModel] = useState('');
  const [collabGpuModel, setCollabGpuModel] = useState('');
  const [collabLoading, setCollabLoading] = useState(false);
  const [collabResult, setCollabResult] = useState<any | null>(null);
  const [collabError, setCollabError] = useState<string | null>(null);
  // PHX-NEW (2026-08-22, pedido do usuário depois de ver a tela com a
  // ampulheta piscando o tempo inteiro até as 6 rodadas terminarem TODAS
  // de uma vez, "dá aquela ideia de que travou"): turnos que já chegaram
  // via polling de /api/dual-collab/progress ENQUANTO a colaboração ainda
  // está rodando - populado progressivamente, rodada a rodada, e
  // descartado assim que o resultado final autoritativo (collabResult)
  // chega (que é sempre a fonte de verdade final). `collabPollRef` guarda
  // o id do setInterval pra sempre conseguir limpá-lo (sucesso, erro, ou
  // se o usuário sair da aba no meio) - nunca deixar um polling órfão
  // rodando depois que a colaboração já terminou.
  const [liveTranscript, setLiveTranscript] = useState<any[]>([]);
  const collabPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopCollabPolling = () => {
    if (collabPollRef.current !== null) {
      clearInterval(collabPollRef.current);
      collabPollRef.current = null;
    }
  };

  // Extraída à parte (não direto dentro de handleRunCollab) de propósito -
  // mantém handleRunCollab enxuto e testável isoladamente (mesmo padrão já
  // usado aqui pra onExecuteCollab/onProcessAttachment: uma dependência
  // injetável, não lógica de timer misturada no meio do fluxo principal).
  // setInterval nunca espera a leitura anterior terminar por padrão, mas
  // cada leitura já é rápida e não-bloqueante (2s de timeout no proxy).
  const startCollabPolling = () => {
    stopCollabPolling();
    collabPollRef.current = setInterval(async () => {
      const progress = await onPollCollabProgress();
      if (progress && Array.isArray(progress.transcript)) {
        setLiveTranscript(progress.transcript);
      }
    }, 1500);
  };

  // Nunca deixa o polling rodando órfão se o componente desmontar (troca
  // de aba, fecha o Arena) no meio de uma colaboração em andamento.
  useEffect(() => stopCollabPolling, []);
  // PHX-NEW (pedido do usuário 2026-08-22, contexto do chat na
  // colaboração): controla o botão "Enviar resultado pro chat" - reseta
  // sempre que um resultado NOVO chega, pra permitir enviar de novo se o
  // usuário rodar outra colaboração.
  const [sentToChat, setSentToChat] = useState(false);
  const hasChatContext = !!activeConversation && activeConversation.messages.length > 0;
  // PHX-NEW (pedido do usuário 2026-08-22, "clip igual no chatbot"):
  // anexo de arquivo na colaboração - mesmo padrão de ChatView.tsx
  // (rawFilesRef guarda o File bruto do navegador, nunca lido como texto
  // aqui; a extração/descrição/transcrição de verdade acontece do lado
  // do backend via onProcessAttachment).
  const [collabAttachedFiles, setCollabAttachedFiles] = useState<
    { id: string; name: string; isImage: boolean }[]
  >([]);
  const collabRawFilesRef = useRef<Map<string, File>>(new Map());
  const collabFileInputRef = useRef<HTMLInputElement>(null);
  // Indica qual etapa está rodando - lendo os anexos (mais rápido, sem
  // LLM) ou a colaboração de verdade (bem mais lenta) - pra não deixar o
  // usuário achando que a colaboração já começou enquanto ainda está só
  // extraindo texto de um PDF grande.
  const [collabAttachStage, setCollabAttachStage] = useState<string | null>(null);

  // Pré-seleciona os dois dropdowns assim que modelos llama.cpp forem
  // detectados, sem sobrescrever uma escolha que o usuário já tenha feito.
  useEffect(() => {
    if (llamaModels.length === 0) return;
    setCollabCpuModel((prev) => prev || llamaModels[0].id);
    setCollabGpuModel((prev) => prev || llamaModels[Math.min(1, llamaModels.length - 1)].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [llamaModels.length]);

  // PHX-NEW (pedido do usuário 2026-08-22: "usuario abre o arena e vai em
  // colaboração e os modelos escolhidos tem acesso ao bate papo"): ao
  // entrar no modo Colaboração vindo de uma conversa ativa no chat, o tema
  // já vem pré-preenchido com o contexto dela - só quando o campo ainda
  // está vazio (nunca sobrescreve algo que o usuário já digitou).
  useEffect(() => {
    if (mode !== 'colaborar') return;
    if (collabTopic.trim()) return;
    const summary = buildChatContextSummary(activeConversation);
    if (summary) setCollabTopic(summary);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);

  // Botão manual "Usar contexto do chat" - pra recarregar o contexto (ex:
  // a conversa avançou depois que o Arena foi aberto) mesmo que o campo já
  // tenha algo digitado - substitui o texto atual por um resumo fresco.
  const handleUseChatContext = () => {
    const summary = buildChatContextSummary(activeConversation);
    if (summary) setCollabTopic(summary);
  };

  const handleCollabFileUpload = (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;

    for (const file of Array.from(files)) {
      const fileId = Math.random().toString();
      // Não lê o conteúdo no navegador (nunca readAsText/readAsDataURL
      // aqui) - só guarda o File bruto, igual ChatView.tsx faz pra
      // documento/áudio. A extração de verdade acontece no backend via
      // onProcessAttachment (imagem/documento/áudio, cada um na ponte
      // certa) quando a colaboração for iniciada.
      collabRawFilesRef.current.set(fileId, file);
      setCollabAttachedFiles((prev) => [
        ...prev,
        { id: fileId, name: file.name, isImage: file.type.startsWith('image/') },
      ]);
    }

    if (collabFileInputRef.current) collabFileInputRef.current.value = '';
  };

  const removeCollabAttachedFile = (fileId: string) => {
    setCollabAttachedFiles((prev) => prev.filter((f) => f.id !== fileId));
    collabRawFilesRef.current.delete(fileId);
  };

  const handleRunCollab = async () => {
    if (!collabTopic.trim() || collabLoading) return;

    // Captura os anexos atuais e limpa o estado ANTES de começar - mesmo
    // padrão de ChatView.handleSend, pra não deixar arquivos "presos" se
    // o usuário anexar algo novo enquanto uma colaboração anterior ainda
    // está processando (o botão já fica desabilitado durante isso, mas
    // seguimos a mesma disciplina do chat de qualquer forma).
    const currentAttachedFiles = [...collabAttachedFiles];
    const currentRawFiles = new Map(collabRawFilesRef.current);
    setCollabAttachedFiles([]);
    collabRawFilesRef.current.clear();

    setCollabLoading(true);
    setCollabError(null);
    setCollabResult(null);
    setSentToChat(false);
    try {
      let finalTopic = collabTopic.trim();

      // PHX-NEW (pedido do usuário 2026-08-22): cada arquivo anexado vira
      // um bloco extra de texto injetado no tema, na ordem em que foi
      // anexado - os dois modelos da colaboração leem isso como parte do
      // próprio tema deles, sem gastar uma chamada de LLM adicional (o
      // caso de documento usa /api/documents/extract-raw, que NUNCA chama
      // um modelo - ver resident_manager.extract_document_raw_direct).
      for (const f of currentAttachedFiles) {
        const rawFile = currentRawFiles.get(f.id);
        if (!rawFile) continue;
        setCollabAttachStage(`Lendo anexo '${f.name}'...`);
        const extractedText = await onProcessAttachment(rawFile, finalTopic);
        finalTopic += `\n\n[Conteúdo do arquivo anexado: ${f.name}]\n${extractedText}`;
      }
      setCollabAttachStage(null);

      // PHX-NEW (2026-08-22, ver liveTranscript/startCollabPolling acima):
      // só começa a perguntar progresso AGORA, logo antes de disparar a
      // colaboração de verdade - perguntar mais cedo (durante o
      // processamento de anexo acima, por exemplo) poderia mostrar por
      // engano o transcript de uma colaboração ANTERIOR que ainda não foi
      // sobrescrita no backend (o buffer só reseta quando a rodada nova
      // realmente começa).
      setLiveTranscript([]);
      startCollabPolling();

      const data = await onExecuteCollab(finalTopic, collabCpuModel, collabGpuModel);
      stopCollabPolling();
      setCollabResult(data);
    } catch (err: any) {
      stopCollabPolling();
      setCollabError(err.message || 'Falha na colaboração entre os dois modelos.');
    } finally {
      stopCollabPolling();
      setCollabAttachStage(null);
      setCollabLoading(false);
    }
  };

  // PHX-NEW (pedido do usuário 2026-08-22: "usuario pode continuar via
  // chatbot"): formata o resultado e chama o callback que anexa isso na
  // conversa ativa do chat (ou cria uma nova, se nenhuma existir).
  const handleSendResultToChat = () => {
    if (!collabResult) return;
    onSendResultToChat(formatCollabResultForChat(collabResult));
    setSentToChat(true);
  };

  const [slots, setSlots] = useState<ArenaSlot[]>([
    {
      id: 'slot-1',
      modelId: availableModels[0]?.id || 'gemini-3.6-flash',
      providerType: availableModels[0]?.providerType || 'gemini',
      providerId: availableModels[0]?.providerId || 'gemini-main',
      isLoading: false,
      currentResponse: '',
    },
    {
      id: 'slot-2',
      modelId: availableModels[1]?.id || 'deepseek-r1:8b',
      providerType: availableModels[1]?.providerType || 'ollama',
      providerId: availableModels[1]?.providerId || 'ollama-main',
      isLoading: false,
      currentResponse: '',
    },
  ]);

  const updateSlotModel = (slotId: string, modelId: string) => {
    const selectedModel = availableModels.find((m) => m.id === modelId);
    if (!selectedModel) return;

    setSlots((prev) =>
      prev.map((s) =>
        s.id === slotId
          ? {
              ...s,
              modelId: selectedModel.id,
              providerType: selectedModel.providerType,
              providerId: selectedModel.providerId,
            }
          : s
      )
    );
  };

  const addSlot = () => {
    if (slots.length >= 3) return;
    // PHX-FIX (varredura 2026-08-21 rodada 2, achado cosmético): se
    // availableModels vier vazio (nenhum provedor configurado ainda),
    // thirdModel ficava undefined e o `.id` logo abaixo quebrava a UI
    // inteira com uma exceção não tratada. Agora sai sem adicionar slot
    // em vez de travar.
    const thirdModel = availableModels[2] || availableModels[0];
    if (!thirdModel) return;
    setSlots((prev) => [
      ...prev,
      {
        id: `slot-${prev.length + 1}`,
        modelId: thirdModel.id,
        providerType: thirdModel.providerType,
        providerId: thirdModel.providerId,
        isLoading: false,
        currentResponse: '',
      },
    ]);
  };

  const removeSlot = (slotId: string) => {
    if (slots.length <= 2) return;
    setSlots((prev) => prev.filter((s) => s.id !== slotId));
  };

  const handleRunArena = async () => {
    if (!promptText.trim() || isLoading) return;
    setWinnerId(null);
    await onExecuteArena(slots, promptText, (updatedSlots) => setSlots(updatedSlots));
  };

  const copyText = (text: string, slotId: string) => {
    navigator.clipboard.writeText(text);
    setCopiedSlot(slotId);
    setTimeout(() => setCopiedSlot(null), 2000);
  };

  return (
    <div id="arena-view-container" className="flex-1 flex flex-col bg-[#0b0d10] text-[#e7e7e7] overflow-hidden font-sans">

      {/* Header Banner */}
      <div className="p-4 border-b border-[#262d35] bg-[#14181d] flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center space-x-2">
            <Columns3 className="w-5 h-5 text-[#ff334b]" />
            <h2 className="text-base font-bold text-white">
              {mode === 'comparar' ? 'Arena de Comparação Lado a Lado' : 'Arena de Colaboração (CPU + GPU)'}
            </h2>
            <span className="text-[10px] bg-[#ff334b]/20 text-[#ff334b] px-2 py-0.5 rounded-full font-mono border border-[#ff334b]/30">
              {mode === 'comparar' ? 'Benchmark em Tempo Real' : 'Dois Modelos, Uma Missão'}
            </span>
          </div>
          <p className="text-xs text-slate-400 mt-0.5 font-sans">
            {mode === 'comparar'
              ? 'Compare a velocidade de geração e precisão entre modelos locais e na nuvem simultaneamente.'
              : 'Um modelo inteiro na CPU e outro inteiro na GPU/Vulkan conversam entre si até concluírem o projeto - o mesmo motor do comando /colaborar no chat.'}
          </p>
        </div>

        <div className="flex items-center space-x-2">
          {/* Alternância Comparação <-> Colaboração */}
          <div className="flex items-center bg-[#0b0d10] border border-[#262d35] rounded-lg p-0.5 mr-1">
            <button
              onClick={() => setMode('comparar')}
              className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-xs font-semibold transition-colors ${
                mode === 'comparar' ? 'bg-[#ff334b] text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Columns3 className="w-3.5 h-3.5" />
              <span>Comparação</span>
            </button>
            <button
              onClick={() => setMode('colaborar')}
              className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-md text-xs font-semibold transition-colors ${
                mode === 'colaborar' ? 'bg-[#ff334b] text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <MessageCircle className="w-3.5 h-3.5" />
              <span>Colaboração</span>
            </button>
          </div>

          {mode === 'comparar' && slots.length < 3 && (
            <button
              onClick={addSlot}
              className="px-3 py-1.5 bg-[#0b0d10] hover:bg-[#262d35] text-slate-200 text-xs font-semibold rounded-lg border border-[#262d35] transition-colors"
            >
              + Adicionar Modelo 3
            </button>
          )}
        </div>
      </div>

      {mode === 'colaborar' ? (
        <>
          {/* Painel de configuração da colaboração */}
          <div className="p-4 sm:p-6 border-b border-[#262d35] bg-[#14181d]/50">
            {llamaModels.length === 0 ? (
              <div className="p-3 bg-amber-950/30 border border-amber-800/40 rounded-xl text-amber-300 text-xs">
                ⚠️ Nenhum modelo llama.cpp/Vulkan detectado ainda. A colaboração só funciona com o motor local
                (llama-server) - clique em "Detectar Locais" no chat, ou confira se o Phoenix Engine está ativo.
              </div>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 max-w-3xl">
                <div>
                  <label className="flex items-center space-x-1.5 text-[11px] font-semibold text-slate-400 mb-1">
                    <Cpu className="w-3.5 h-3.5" />
                    <span>Modelo do lado CPU</span>
                  </label>
                  <select
                    value={collabCpuModel}
                    onChange={(e) => setCollabCpuModel(e.target.value)}
                    disabled={collabLoading}
                    className="w-full bg-[#0b0d10] border border-[#262d35] rounded-lg px-2.5 py-1.5 text-xs text-white font-semibold focus:ring-1 focus:ring-[#ff334b] font-mono"
                  >
                    <option value="">Padrão da Phoenix</option>
                    {llamaModels.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="flex items-center space-x-1.5 text-[11px] font-semibold text-slate-400 mb-1">
                    <Zap className="w-3.5 h-3.5" />
                    <span>Modelo do lado GPU (offload total)</span>
                  </label>
                  <select
                    value={collabGpuModel}
                    onChange={(e) => setCollabGpuModel(e.target.value)}
                    disabled={collabLoading}
                    className="w-full bg-[#0b0d10] border border-[#262d35] rounded-lg px-2.5 py-1.5 text-xs text-white font-semibold focus:ring-1 focus:ring-[#ff334b] font-mono"
                  >
                    <option value="">Padrão da Phoenix</option>
                    {llamaModels.map((m) => (
                      <option key={m.id} value={m.id}>{m.name}</option>
                    ))}
                  </select>
                </div>
              </div>
            )}
          </div>

          {/* Transcript da colaboração */}
          {/* PHX-NEW (2026-08-22, pedido do usuário: "seria interessante a
              CPU responder e aparecer num terminal, e aí depois aparecer a
              GPU respondendo... não [esperar] até o final das sessões" -
              antes disso, a tela só mostrava a ampulheta girando o tempo
              inteiro e cuspia tudo de uma vez no fim, dando a impressão de
              que travou). `displayTranscript` é o resultado final
              (autoritativo) quando já chegou, ou o progresso ao vivo
              (`liveTranscript`, atualizado por polling a cada 1.5s
              enquanto `collabLoading`) enquanto a colaboração ainda está
              rodando - o MESMO bloco de renderização abaixo já cobria o
              resultado final, então cada rodada agora aparece assim que
              termina, sem precisar de nenhum componente novo. */}
          {(() => {
            const displayTranscript = collabResult?.transcript ?? (collabLoading ? liveTranscript : []);
            return (
          <div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-3 max-w-4xl mx-auto w-full">
            {collabLoading && displayTranscript.length === 0 && (
              <div className="p-8 text-center text-slate-500 space-y-2">
                <Hourglass className="w-6 h-6 text-[#ff334b] animate-pulse mx-auto" />
                <p className="font-mono text-[11px]">
                  {collabAttachStage
                    ? collabAttachStage
                    : 'Colaboração em andamento - isso pode levar vários minutos (dois modelos inteiros, um em cada hardware)...'}
                </p>
              </div>
            )}

            {collabError && (
              <div className="p-3 bg-rose-950/40 border border-rose-800/50 rounded-xl text-rose-300 text-xs">
                ⚠️ {collabError}
              </div>
            )}

            {!collabLoading && !collabError && !collabResult && (
              <div className="h-full flex items-center justify-center text-slate-600 text-[11px] italic py-16">
                Escolha os modelos, digite o tema do projeto abaixo e clique em "Iniciar Colaboração".
              </div>
            )}

            {displayTranscript.map((t: any, idx: number) => (
              <div
                key={idx}
                className={`p-3 rounded-xl border text-xs leading-relaxed ${
                  t.speaker === 'cpu'
                    ? 'bg-[#14181d] border-[#262d35]'
                    : 'bg-purple-950/20 border-purple-800/30'
                }`}
              >
                <div className="flex items-center space-x-1.5 mb-1.5 font-semibold text-[11px]">
                  {t.speaker === 'cpu' ? (
                    <Cpu className="w-3.5 h-3.5 text-slate-300" />
                  ) : (
                    <Zap className="w-3.5 h-3.5 text-purple-300" />
                  )}
                  <span className={t.speaker === 'cpu' ? 'text-slate-300' : 'text-purple-300'}>
                    {t.speaker === 'cpu' ? 'CPU' : 'GPU'} — Rodada {t.round}
                  </span>
                </div>
                <div className="whitespace-pre-wrap font-sans text-slate-200">{t.text}</div>
                {t.searches && t.searches.length > 0 && (
                  <div className="flex items-center space-x-1.5 mt-2 text-[10px] text-sky-300">
                    <Globe2 className="w-3 h-3" />
                    <span>Buscou na internet: {t.searches.join('; ')}</span>
                  </div>
                )}
                {/* PHX-NEW (pedido do usuário 2026-08-22, depois de ver 6
                    rodadas seguidas "corrigindo" um bug de cache que nunca
                    resolvia nada de verdade): quando dá pra rodar o código
                    proposto de verdade (ver patch_verification.py), o
                    resultado REAL aparece aqui - visualmente separado do
                    texto do modelo, porque é um fato medido, não a opinião
                    de nenhum dos dois lados. */}
                {t.objective_check && (
                  <div
                    className={`flex items-start space-x-1.5 mt-2 p-2 rounded-lg text-[10px] leading-relaxed ${
                      t.objective_check.includes('CONFIRMADO -') && !t.objective_check.includes('NÃO CONFIRMADO')
                        ? 'bg-emerald-950/30 border border-emerald-800/40 text-emerald-300'
                        : 'bg-amber-950/30 border border-amber-800/40 text-amber-300'
                    }`}
                  >
                    {t.objective_check.includes('CONFIRMADO -') && !t.objective_check.includes('NÃO CONFIRMADO') ? (
                      <FlaskConical className="w-3 h-3 mt-0.5 shrink-0" />
                    ) : (
                      <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
                    )}
                    <span>{t.objective_check}</span>
                  </div>
                )}
              </div>
            ))}

            {/* PHX-NEW (2026-08-22, mesmo pedido do topo deste bloco): uma
                vez que a primeira rodada já apareceu, troca a ampulheta
                centralizada e grande por um indicador pequeno no rodapé -
                deixa claro que ainda tem coisa rodando (não travou) sem
                empurrar as rodadas já visíveis pra fora da tela. */}
            {collabLoading && displayTranscript.length > 0 && (
              <div className="flex items-center space-x-2 text-slate-500 text-[11px] p-2">
                <Hourglass className="w-3.5 h-3.5 text-[#ff334b] animate-pulse shrink-0" />
                <span className="font-mono">Colaboração continua - próxima rodada em andamento...</span>
              </div>
            )}

            {collabResult && !collabLoading && (
              <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 p-3 rounded-xl bg-[#0b0d10] border border-[#262d35] text-[11px]">
                <div className="flex items-center space-x-1.5">
                  {collabResult.concluded ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-[#37d67a]" />
                  ) : (
                    <Hourglass className="w-3.5 h-3.5 text-amber-400" />
                  )}
                  <span className="text-slate-300">
                    {collabResult.concluded
                      ? `Colaboração concluída em ${collabResult.rounds_completed} rodada(s) - os dois modelos concordaram que o projeto terminou.`
                      : `Colaboração parada (${collabResult.stopped_reason}) após ${collabResult.rounds_completed} rodada(s).`}
                  </span>
                </div>
                {/* PHX-NEW (pedido do usuário 2026-08-22: "usuario pode
                    continuar via chatbot"): leva o resultado de volta pra
                    conversa (cria uma nova se nenhuma existir) e volta pro
                    chat, pra continuar de onde a colaboração parou. */}
                <button
                  onClick={handleSendResultToChat}
                  disabled={sentToChat}
                  className="flex items-center space-x-1.5 px-3 py-1.5 bg-[#262d35] hover:bg-[#262d35]/70 disabled:opacity-50 text-slate-200 text-[11px] font-semibold rounded-lg shrink-0 cursor-pointer transition-colors"
                >
                  <Send className="w-3.5 h-3.5" />
                  <span>{sentToChat ? 'Enviado pro chat' : 'Enviar resultado pro chat'}</span>
                </button>
              </div>
            )}
          </div>
            );
          })()}

          {/* Barra do tema + anexo + botão de iniciar */}
          <div className="p-4 border-t border-[#262d35] bg-[#14181d]">
            <div className="max-w-4xl mx-auto">
              {collabAttachedFiles.length > 0 && (
                <div className="flex flex-wrap gap-2 mb-2 p-2 bg-[#0b0d10] border border-[#262d35] rounded-xl">
                  {collabAttachedFiles.map((f) => (
                    <div
                      key={f.id}
                      className="flex items-center space-x-1.5 px-2.5 py-1 bg-[#14181d] border border-[#262d35] rounded-lg text-xs font-mono text-slate-300"
                    >
                      {f.isImage ? <ImageIcon className="w-3.5 h-3.5 text-[#ff334b]" /> : <FileText className="w-3.5 h-3.5 text-slate-400" />}
                      <span className="truncate max-w-[120px]">{f.name}</span>
                      <button
                        onClick={() => removeCollabAttachedFile(f.id)}
                        disabled={collabLoading}
                        className="text-slate-500 hover:text-rose-400 disabled:opacity-40"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {hasChatContext && (
                <button
                  type="button"
                  onClick={handleUseChatContext}
                  disabled={collabLoading}
                  title="Preenche o tema com um resumo da conversa ativa do chat, pra os dois modelos entenderem o que já foi discutido"
                  className="flex items-center space-x-1.5 mb-2 text-[11px] text-slate-400 hover:text-[#ff334b] disabled:opacity-40 transition-colors"
                >
                  <History className="w-3.5 h-3.5" />
                  <span>Usar contexto da conversa atual do chat</span>
                </button>
              )}

              <div className="flex items-center space-x-3">
                <input
                  type="file"
                  ref={collabFileInputRef}
                  onChange={handleCollabFileUpload}
                  multiple
                  disabled={collabLoading}
                  className="hidden"
                  // Mesmos tipos aceitos do clipe do chat (ChatView.tsx) -
                  // imagem, áudio, e os 4 formatos de documento que o
                  // Document Engine sabe extrair (pdf/docx/xlsx/pptx).
                  accept="image/*,audio/*,.pdf,.docx,.xlsx,.pptx,.mp3,.wav,.m4a,.ogg,.flac,.aac,.webm"
                />
                <button
                  type="button"
                  onClick={() => collabFileInputRef.current?.click()}
                  disabled={collabLoading}
                  title="Anexar arquivo ou imagem"
                  className="p-3 text-slate-400 hover:text-[#ff334b] disabled:opacity-40 transition-colors cursor-pointer shrink-0"
                >
                  <Paperclip className="w-5 h-5" />
                </button>
                {/* PHX-FIX (2026-08-22, achado real de auditoria - ver
                    patch_verification.py, item 4 da docstring do módulo):
                    isto ERA um <input type="text">, que por definição do
                    HTML nunca guarda quebra de linha nenhuma - colar um
                    tema multi-linha (ex.: um bug de código com a função
                    inteira) grudava tudo numa linha só sem espaço nenhum
                    entre as linhas originais, o que quebrava silenciosamente
                    o reconhecimento do nome da função no verificador
                    objetivo. Virou <textarea> pra o usuário conseguir
                    digitar/colar texto multi-linha de verdade. */}
                <textarea
                  value={collabTopic}
                  onChange={(e) => setCollabTopic(e.target.value)}
                  placeholder="Digite o tema do projeto que os dois modelos vão colaborar... (pode colar código multi-linha)"
                  disabled={collabLoading}
                  rows={2}
                  className="flex-1 bg-[#0b0d10] border border-[#262d35] rounded-xl py-3 px-4 text-xs sm:text-sm text-white focus:ring-1 focus:ring-[#ff334b] resize-y font-mono"
                />
                <button
                  onClick={handleRunCollab}
                  disabled={!collabTopic.trim() || collabLoading || llamaModels.length === 0}
                  className="flex items-center space-x-2 px-5 py-3 bg-[#ff334b] hover:bg-[#ff334b]/90 disabled:opacity-40 text-white text-xs sm:text-sm font-bold rounded-xl shadow-lg shadow-[#ff334b]/30 transition-all shrink-0 cursor-pointer"
                >
                  <MessageCircle className={`w-4 h-4 ${collabLoading ? 'animate-pulse' : ''}`} />
                  <span>{collabLoading ? 'Colaborando...' : 'Iniciar Colaboração'}</span>
                </button>
              </div>
            </div>
          </div>
        </>
      ) : (
      <>
      {/* Arena Slots Grid */}
      <div className="flex-1 overflow-y-auto p-4 sm:p-6">
        <div className={`grid grid-cols-1 ${slots.length === 3 ? 'md:grid-cols-3' : 'md:grid-cols-2'} gap-4 h-full min-h-[400px]`}>
          {slots.map((slot) => {
            const isWinner = winnerId === slot.id;

            return (
              <div
                key={slot.id}
                id={`arena-slot-card-${slot.id}`}
                className={`bg-[#14181d] border rounded-2xl p-4 flex flex-col relative transition-all shadow-xl ${
                  isWinner
                    ? 'border-[#ff334b] ring-2 ring-[#ff334b]/30'
                    : 'border-[#262d35] hover:border-slate-700'
                }`}
              >
                
                {/* Slot Model Picker Header */}
                <div className="flex items-center justify-between pb-3 border-b border-[#262d35]">
                  <div className="flex items-center space-x-2 flex-1 mr-2">
                    <div className="p-1.5 bg-[#ff334b]/10 border border-[#ff334b]/20 rounded-lg shrink-0">
                      <Bot className="w-4 h-4 text-[#ff334b]" />
                    </div>
                    
                    <select
                      value={slot.modelId}
                      onChange={(e) => updateSlotModel(slot.id, e.target.value)}
                      className="w-full bg-[#0b0d10] border border-[#262d35] rounded-lg px-2.5 py-1 text-xs text-white font-semibold focus:ring-1 focus:ring-[#ff334b] font-mono"
                    >
                      {availableModels.map((m) => (
                        <option key={m.id} value={m.id}>
                          [{m.providerType.toUpperCase()}] {m.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  {slots.length > 2 && (
                    <button
                      onClick={() => removeSlot(slot.id)}
                      className="p-1 text-slate-500 hover:text-rose-400 text-xs"
                      title="Remover Slot"
                    >
                      ✕
                    </button>
                  )}
                </div>

                {/* Metrics Banner */}
                {slot.metrics && (
                  <div className="my-2 p-2 bg-[#0b0d10] border border-[#262d35] rounded-xl flex items-center justify-around text-[11px] font-mono">
                    <div className="flex items-center space-x-1 text-[#37d67a] font-bold">
                      <Zap className="w-3.5 h-3.5" />
                      <span>{slot.metrics.tokensPerSec || 0} tok/s</span>
                    </div>
                    <div className="flex items-center space-x-1 text-slate-400">
                      <Clock className="w-3.5 h-3.5" />
                      <span>{((slot.metrics.durationMs || 0) / 1000).toFixed(2)}s</span>
                    </div>
                  </div>
                )}

                {/* Response Content Body */}
                <div className="flex-1 overflow-y-auto my-3 text-xs leading-relaxed space-y-3 pr-1">
                  {slot.isLoading ? (
                    <div className="p-8 text-center text-slate-500 space-y-2">
                      <Zap className="w-6 h-6 text-[#ff334b] animate-pulse mx-auto" />
                      <p className="font-mono text-[11px]">Gerando resposta no {slot.providerType}...</p>
                    </div>
                  ) : slot.error ? (
                    <div className="p-3 bg-rose-950/40 border border-rose-800/50 rounded-xl text-rose-300">
                      ⚠️ {slot.error}
                    </div>
                  ) : slot.currentResponse ? (
                    <>
                      {slot.thinking && (
                        <div className="p-2.5 bg-purple-950/30 border border-purple-800/40 rounded-xl font-mono text-[10px] text-purple-200">
                          <div className="flex items-center space-x-1 font-semibold text-purple-400 mb-1">
                            <BrainCircuit className="w-3.5 h-3.5" />
                            <span>Raciocínio (&lt;think&gt;)</span>
                          </div>
                          <div className="line-clamp-4 hover:line-clamp-none transition-all">
                            {slot.thinking}
                          </div>
                        </div>
                      )}
                      
                      <div className="whitespace-pre-wrap font-sans text-slate-200">
                        {slot.currentResponse}
                      </div>
                    </>
                  ) : (
                    <div className="h-full flex items-center justify-center text-slate-600 text-[11px] italic">
                      Aguardando execução do benchmark...
                    </div>
                  )}
                </div>

                {/* Footer Winner Button */}
                {slot.currentResponse && !slot.isLoading && (
                  <div className="pt-2 border-t border-[#262d35] flex items-center justify-between">
                    <button
                      onClick={() => setWinnerId(slot.id)}
                      className={`flex items-center space-x-1 px-2.5 py-1 rounded-lg text-[11px] font-semibold transition-all ${
                        isWinner
                          ? 'bg-[#ff334b] text-white shadow-md'
                          : 'bg-[#0b0d10] hover:bg-[#262d35] text-slate-300'
                      }`}
                    >
                      <Trophy className="w-3.5 h-3.5" />
                      <span>{isWinner ? 'Vencedor Escolhido!' : 'Marcar como Melhor'}</span>
                    </button>

                    <button
                      onClick={() => copyText(slot.currentResponse, slot.id)}
                      className="p-1.5 text-slate-400 hover:text-white rounded hover:bg-[#262d35]"
                      title="Copiar Resposta"
                    >
                      {copiedSlot === slot.id ? (
                        <Check className="w-3.5 h-3.5 text-[#37d67a]" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                )}

              </div>
            );
          })}
        </div>
      </div>

      {/* Shared Prompt Bar */}
      <div className="p-4 border-t border-[#262d35] bg-[#14181d]">
        <div className="max-w-4xl mx-auto flex items-center space-x-3">
          <input
            type="text"
            value={promptText}
            onChange={(e) => setPromptText(e.target.value)}
            placeholder="Digite o prompt para comparar a execução..."
            disabled={isLoading}
            className="flex-1 bg-[#0b0d10] border border-[#262d35] rounded-xl py-3 px-4 text-xs sm:text-sm text-white focus:ring-1 focus:ring-[#ff334b]"
          />

          <button
            onClick={handleRunArena}
            disabled={!promptText.trim() || isLoading}
            className="flex items-center space-x-2 px-5 py-3 bg-[#ff334b] hover:bg-[#ff334b]/90 disabled:opacity-40 text-white text-xs sm:text-sm font-bold rounded-xl shadow-lg shadow-[#ff334b]/30 transition-all shrink-0 cursor-pointer"
          >
            <Play className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
            <span>{isLoading ? 'Executando...' : 'Executar Comparação'}</span>
          </button>
        </div>
      </div>
      </>
      )}

    </div>
  );
};
