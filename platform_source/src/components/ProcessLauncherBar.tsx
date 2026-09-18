import React, { useEffect, useState } from 'react';
import {
  Bot,
  Cpu,
  ExternalLink,
  Columns,
  Activity,
  Zap,
  Volume2,
  Folder,
  Flame,
  Terminal,
  Layers,
  BookOpen,
  Sparkles,
  ShieldCheck,
  RefreshCw,
  Play,
  Square,
  X,
  AlertTriangle,
} from 'lucide-react';
import { ActiveProcessView } from '../types';
import { synthesizeAndPlaySpeech } from '../services/piperTtsService';

interface ProcessLauncherBarProps {
  activeProcess: ActiveProcessView;
  onChangeProcess: (view: ActiveProcessView) => void;
  onOpenAviaryNewWindow: () => void;
  onOpenEngineNewWindow: () => void;
  engineOnline?: boolean;
  // PHX-FIX (achado real do usuário 2026-08-28: "TIRAR CAMINHO
  // R:\Phoenix\Workstations, PORQUE NAO FAZ SENTIDO NENHUM... JA NAO É
  // MAIS R:\ E SÓ FUNCIONA NA MINHA MAQUINA"): caminho real desta
  // instalação, vindo de /api/state (App.tsx) - null enquanto não
  // carregou ou o Engine está offline.
  workspacePath?: string | null;
}

export const ProcessLauncherBar = ({
  activeProcess,
  onChangeProcess,
  onOpenAviaryNewWindow,
  onOpenEngineNewWindow,
  engineOnline = true,
  workspacePath = null,
}: ProcessLauncherBarProps) => {
  // PHX-FIX (varredura 2026-08-21 rodada 2, achado do piperTtsService):
  // synthesizeAndPlaySpeech() já devolve honestamente qual motor falou de
  // verdade (motor local real vs voz de fallback do navegador quando o
  // backend falha) - o botão de teste descartava esse retorno e sempre
  // dizia "Voz Kokoro PT-BR", mesmo quando quem falou foi a voz genérica.
  const [lastVoiceTestEngine, setLastVoiceTestEngine] = useState<string | null>(null);
  const [forgePanelOpen, setForgePanelOpen] = useState(false);
  const [forgeLoading, setForgeLoading] = useState(false);
  const [forgeStatus, setForgeStatus] = useState<any>(null);
  const [forgeExecutions, setForgeExecutions] = useState<any[]>([]);
  const [forgeSafety, setForgeSafety] = useState<any>(null);
  const [forgeError, setForgeError] = useState<string | null>(null);
  const [forgeBenchmarkProfile, setForgeBenchmarkProfile] = useState<'quick' | 'standard' | 'deep'>('quick');
  const [forgeBenchmarkLoading, setForgeBenchmarkLoading] = useState(false);
  const [forgeBenchmarkResult, setForgeBenchmarkResult] = useState<any>(null);
  const [forgeBenchmarkJob, setForgeBenchmarkJob] = useState<any>(null);

  const refreshForge = async (withDetails = false) => {
    try {
      const statusResponse = await fetch('/api/forge/status');
      const statusData = await statusResponse.json().catch(() => null);
      if (!statusResponse.ok) {
        throw new Error(statusData?.detail || statusData?.error || `Falha ao consultar o Forge (HTTP ${statusResponse.status})`);
      }
      setForgeStatus(statusData);
      setForgeError(null);
      if (withDetails && statusData.forge_online) {
        const [executionsResponse, safetyResponse] = await Promise.all([
          fetch('/api/forge/executions?limit=20'),
          fetch('/api/forge/gpu-safety'),
        ]);
        const executionsData = await executionsResponse.json();
        const safetyData = await safetyResponse.json();
        setForgeExecutions(executionsResponse.ok ? (executionsData.entries || []) : []);
        setForgeSafety(safetyResponse.ok ? safetyData : null);
      }
    } catch (error: any) {
      setForgeError(error?.message || String(error));
      setForgeStatus(null);
    }
  };

  const operateForge = async (action: 'start' | 'restart' | 'stop') => {
    setForgeLoading(true);
    setForgeError(null);
    try {
      const response = await fetch(`/api/forge/${action}`, { method: 'POST' });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data?.ok) {
        throw new Error(data?.detail || data?.error || data?.operation?.detail || `Falha ao executar ${action} (HTTP ${response.status})`);
      }
      await new Promise(resolve => setTimeout(resolve, action === 'stop' ? 500 : 1800));
      await refreshForge(true);
    } catch (error: any) {
      setForgeError(error?.message || String(error));
    } finally {
      setForgeLoading(false);
    }
  };

  const runForgeBenchmark = async (includeGpu: boolean) => {
    if (!forgeStatus?.forge_online) {
      setForgeError('O Forge precisa estar online para executar o benchmark.');
      return;
    }
    if (includeGpu && !window.confirm(
      'Benchmark de GPU pode elevar temperatura e expor instabilidade da placa. A RX 580 está marcada como DEGRADED. Deseja continuar?'
    )) return;
    setForgeBenchmarkLoading(true);
    setForgeBenchmarkResult(null);
    setForgeError(null);
    try {
      const query = new URLSearchParams({ profile: forgeBenchmarkProfile, include_gpu: String(includeGpu), confirm_gpu_risk: String(includeGpu) });
      const response = await fetch(`/api/forge/benchmark/jobs?${query.toString()}`, { method: 'POST' });
      const data = await response.json().catch(() => null);
      if (!response.ok) throw new Error(data?.detail || data?.error || `Benchmark falhou (HTTP ${response.status})`);
      setForgeBenchmarkJob(data);let current=data;
      while (['QUEUED','RUNNING'].includes(current?.status)) {
        await new Promise(resolve=>setTimeout(resolve,1000));
        const statusResponse=await fetch(`/api/forge/benchmark/jobs/${encodeURIComponent(data.job_id)}`);current=await statusResponse.json().catch(()=>null);
        if(!statusResponse.ok)throw new Error(current?.detail||current?.error||'Falha ao acompanhar benchmark.');setForgeBenchmarkJob(current);
      }
      if(current?.status==='FAILED')throw new Error(current.error||'Benchmark falhou.');setForgeBenchmarkResult(current?.result||null);
    } catch (error: any) {
      setForgeError(error?.message || String(error));
    } finally {
      setForgeBenchmarkLoading(false);
    }
  };
  const cancelForgeBenchmark=async()=>{if(!forgeBenchmarkJob?.job_id)return;await fetch(`/api/forge/benchmark/jobs/${encodeURIComponent(forgeBenchmarkJob.job_id)}/cancel`,{method:'POST'});setForgeBenchmarkJob((current:any)=>({...current,progress:{...(current?.progress||{}),phase:'cancelling'}}));};

  const benchmarkMetric = (entry: any) => {
    const metrics = entry?.result?.metrics || {};
    if (metrics.operations_per_second != null) return `${Number(metrics.operations_per_second).toFixed(1)} ops/s`;
    if (metrics.throughput_mb_s != null) return `${Number(metrics.throughput_mb_s).toFixed(1)} MB/s`;
    if (metrics.median_mb_s != null) return `${Number(metrics.median_mb_s).toFixed(1)} MB/s`;
    if (metrics.nanoseconds_per_access != null) return `${Number(metrics.nanoseconds_per_access).toFixed(1)} ns/acesso`;
    return '—';
  };

  useEffect(() => {
    refreshForge(false);
    const interval = setInterval(() => refreshForge(false), 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (forgePanelOpen) refreshForge(true);
  }, [forgePanelOpen]);

  // PHX-FIX (pedido do usuário 2026-08-22: "tirar o botao 'transcrever
  // audio' porque alem de abrir popup, é muito pequeno em contexto e fica
  // redundante"): este botão era um caminho de transcrição INDEPENDENTE do
  // fluxo principal (anexar/arrastar áudio no chat da Aviary e pedir
  // "transcrever áudio" - já corrigido nesta mesma sessão para não disparar
  // uma segunda chamada de LLM desnecessária). Ele: (1) só sabia responder
  // via `alert()` nativo do navegador - um popup bloqueante, pequeno demais
  // pra mostrar uma transcrição inteira, e destoante do resto da UI que usa
  // chat/toasts; (2) exigia manter DUAS listas de extensão de áudio em
  // sincronia manual com ChatView.tsx/AviaryApp.tsx (ver comentário antigo
  // removido junto, achado #4 do LEIA-ME - fonte de bug se alguém
  // esquecesse de atualizar aqui). Removidos junto: `handleAudioFileSelected`,
  // `audioInputRef`, `isTranscribing` e o `<input type="file">` oculto que só
  // serviam a este botão - nenhum outro ponto deste arquivo os usava (ver
  // prova_testes/test_remove_transcribe_button.mjs).

  return (
    <div id="process-launcher-bar" className="bg-[#0b0d10] border-b border-[#262d35] px-2 sm:px-4 py-2 flex flex-col gap-2 text-xs font-mono select-none z-40">
      
      {/* Top Row: Primary Process Modes & Direct External Links */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        
        {/* Left: Process Switchers */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] text-[#8d98a5] uppercase font-bold tracking-wider mr-1 hidden xl:inline">
            CORE PROCESS:
          </span>

          {/* Process 1 Button: Aviary (Port 3000) */}
          <button
            id="btn-process-aviary"
            onClick={() => onChangeProcess('aviary')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-lg border font-semibold transition-all cursor-pointer ${
              activeProcess === 'aviary'
                ? 'bg-[#ff334b] text-white border-[#ff334b] shadow-[0_0_12px_rgba(255,51,75,0.4)]'
                : 'bg-[#14181d] text-[#8d98a5] hover:text-white border-[#262d35] hover:border-[#ff334b]/50'
            }`}
            title="Phoenix Aviary Platform: Interface ChatGPT / OpenWebUI / LM Studio (Porta 3000)"
          >
            <Bot className="w-3.5 h-3.5 text-white" />
            <span className="font-bold text-xs">AVIARY PLATFORM</span>
            <span className={`text-[9px] px-1 py-0.2 rounded font-mono ${
              activeProcess === 'aviary' ? 'bg-black/40 text-white font-bold' : 'bg-[#ff334b]/20 text-[#ff334b]'
            }`}>
              PORTA :3000
            </span>
          </button>

          {/* Process 2 Button: Engine (Port 8000) */}
          <button
            id="btn-process-engine"
            onClick={() => onChangeProcess('engine')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded-lg border font-semibold transition-all cursor-pointer ${
              activeProcess === 'engine'
                ? 'bg-white text-black border-white shadow-[0_0_12px_rgba(255,255,255,0.3)]'
                : 'bg-[#14181d] text-[#8d98a5] hover:text-white border-[#262d35] hover:border-white/50'
            }`}
            title="Phoenix Engine: Kernel de Inferência Vulkan, Telemetria e Hardware (Porta 8000)"
          >
            <Cpu className="w-3.5 h-3.5 text-[#ff334b]" />
            <span className="font-bold text-xs">PHOENIX ENGINE</span>
            <span className={`text-[9px] px-1 py-0.2 rounded font-mono ${
              activeProcess === 'engine' ? 'bg-black/30 text-black font-bold' : 'bg-emerald-500/20 text-[#37d67a]'
            }`}>
              PORTA :8000 [VULKAN]
            </span>
          </button>

          {/* Dual Split Mode */}
          <button
            id="btn-phoenix-forge"
            onClick={() => setForgePanelOpen(true)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border transition-all cursor-pointer ${
              forgeStatus?.forge_online
                ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/50 hover:bg-emerald-500/20'
                : 'bg-amber-500/10 text-amber-300 border-amber-500/50 hover:bg-amber-500/20'
            }`}
            title="Abrir controle, saúde, decisões e diário do Phoenix Forge"
          >
            <ShieldCheck className="w-3.5 h-3.5" />
            <span className="font-bold text-xs">FORGE</span>
            <span className="text-[9px] font-mono">
              {forgeStatus?.forge_online ? `:${forgeStatus?.ports?.forge?.port || 8787} OK` : ':8787 OFF'}
            </span>
          </button>

          <button
            id="btn-process-split"
            onClick={() => onChangeProcess('split')}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border transition-all cursor-pointer ${
              activeProcess === 'split'
                ? 'bg-[#4fa3ff] text-black font-bold border-[#4fa3ff] shadow-[0_0_12px_rgba(79,163,255,0.4)]'
                : 'bg-[#14181d] text-[#8d98a5] hover:text-white border-[#262d35] hover:border-[#4fa3ff]/50'
            }`}
            title="Visualizar ambos os processos lado a lado em tela dividida"
          >
            <Columns className="w-3.5 h-3.5" />
            <span className="text-xs">DUAL PROCESS (SPLIT)</span>
          </button>
        </div>

        {/* Right: New Window / Tab Dispatchers */}
        <div className="flex items-center gap-1.5 shrink-0 flex-wrap">
          <button
            onClick={onOpenAviaryNewWindow}
            className="flex items-center gap-1 px-2 py-1 rounded bg-[#14181d] hover:bg-[#262d35] text-[#e7e7e7] border border-[#262d35] hover:border-[#ff334b] transition-all text-[10px] cursor-pointer"
            title="Abrir a Aviary Platform em nova aba"
          >
            <ExternalLink className="w-3 h-3 text-[#ff334b]" />
            <span>Aviary (:3000)</span>
          </button>

          <button
            onClick={onOpenEngineNewWindow}
            className="flex items-center gap-1 px-2 py-1 rounded bg-[#14181d] hover:bg-[#262d35] text-[#e7e7e7] border border-[#262d35] hover:border-white transition-all text-[10px] cursor-pointer"
            title="Abrir a Phoenix Engine em nova aba"
          >
            <ExternalLink className="w-3 h-3 text-[#37d67a]" />
            <span>Engine (:8000)</span>
          </button>
        </div>

      </div>

      {/* Bottom Row: Hyper-Action Buttons & Stimulus Matrix (100% dos MDs) */}
      <div className="flex items-center gap-1.5 flex-wrap pt-1 border-t border-[#262d35]/60 text-[10px]">
        <span className="text-[#8d98a5] font-bold uppercase mr-1 flex items-center gap-1">
          <Zap className="w-3 h-3 text-amber-400" />
          AÇÕES RÁPIDAS:
        </span>

        {/* Action 1: Test Kokoro Voice */}
        <button
          onClick={async () => {
            setLastVoiceTestEngine(null);
            const result = await synthesizeAndPlaySpeech("Phoenix Engine e Aviary Platform operando em sincronia total.", { voiceId: 'pf_dora' });
            setLastVoiceTestEngine(result.engine);
          }}
          className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#14181d] hover:bg-[#ff334b]/20 text-[#e7e7e7] hover:text-[#ff334b] border border-[#262d35] hover:border-[#ff334b] transition-all cursor-pointer font-semibold"
          title={lastVoiceTestEngine === 'Web Speech API (Fallback)'
            ? 'Último teste: Kokoro indisponível, falou a voz do navegador'
            : 'Testar síntese neural Kokoro TTS em português (PT-BR)'}
        >
          <Volume2 className="w-3 h-3 text-[#ff334b]" />
          <span>Voz Kokoro PT-BR</span>
          {lastVoiceTestEngine === 'Web Speech API (Fallback)' && (
            <span className="text-[9px] text-[#f7b731] font-mono">(fallback navegador)</span>
          )}
        </button>

        {/* Action 2: Trigger Real Token Throughput Benchmark */}
        {/* PHX-FIX (auditoria completa, achado #2 do LEIA-ME): o title
            prometia "benchmark real de shaders Vulkan" mas /api/benchmark
            sempre devolvia os mesmos números fixos, nunca media nada. Com
            o endpoint real (api_server.py: inferência curta via
            kernel.runtime, tokens/s medido de verdade), o alerta mostra só
            o que é de fato medido - throughput de tokens - e trata falha
            real como falha real em vez de nunca poder falhar. */}
        <button
          onClick={() => {
            fetch('/api/benchmark', { method: 'POST' })
              .then(async r => {
                const d = await r.json();
                if (!r.ok || !d.success) {
                  alert(`Benchmark falhou: ${d.error || 'erro desconhecido'}`);
                  return;
                }
                const res = d.results || {};
                alert(`Benchmark real (${res.runtime || '?'} / ${res.model || '?'}):\nTokens/s: ${res.tokensPerSec}\nTokens gerados: ${res.tokensGenerated}\nDuração: ${res.durationMs}ms\n\n${d.note || ''}`);
              })
              .catch(e => alert(`Benchmark falhou: ${e?.message || e}`));
          }}
          className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#14181d] hover:bg-[#37d67a]/20 text-[#e7e7e7] hover:text-[#37d67a] border border-[#262d35] hover:border-[#37d67a] transition-all cursor-pointer font-semibold"
          title="Disparar benchmark real de throughput de tokens (inferência curta medida de verdade)"
        >
          <Activity className="w-3 h-3 text-[#37d67a]" />
          <span>Token Bench (Real)</span>
        </button>

        <button
          onClick={() => setForgePanelOpen(true)}
          className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#14181d] hover:bg-amber-500/20 text-[#e7e7e7] hover:text-amber-300 border border-[#262d35] hover:border-amber-400 transition-all cursor-pointer font-semibold"
          title="Abrir benchmark de CPU, memória, armazenamento e GPU supervisionado pelo Forge"
        >
          <ShieldCheck className="w-3 h-3 text-amber-400" />
          <span>Forge Benchmark</span>
        </button>

        {/* Action 3: Haswell EFI Unlock Status */}
        <button
          onClick={() => alert("Xeon E5-2690 v3 (Haswell 12C/24T):\n• All-Core Turbo: 3.10 GHz Fixado\n• EFI Lock / Undervolt: -70mV Ativo\n• Quad-Channel DDR4: 2133 MHz (32.6 GB)\n• Largura de Banda RAM: ~55 GB/s")}
          className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#14181d] hover:bg-white/20 text-[#e7e7e7] hover:text-white border border-[#262d35] hover:border-white transition-all cursor-pointer font-semibold"
          title="Inspecionar perfil do Xeon E5 Haswell e Turbo Unlock"
        >
          <Flame className="w-3 h-3 text-amber-400" />
          <span>Xeon Turbo 3.1GHz [EFI Lock]</span>
        </button>

        {/* Action 4: Regra dos 6.3GB VRAM */}
        <button
          onClick={() => alert("REGRA DOS 6.3GB VRAM (Polaris RX 580):\n\n8.0 GB (VRAM total) - 1.2 GB (compute buffer) - 0.5 GB (folga) = 6.3 GB para pesos.\n\n• SD 1.5: baseline rápido e estável.\n• SDXL: melhor qualidade; use AUTO para o placement seguro.\n• Flux e SD 3.5: retirados da linha operacional desta máquina.")}
          className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#14181d] hover:bg-[#4fa3ff]/20 text-[#e7e7e7] hover:text-[#4fa3ff] border border-[#262d35] hover:border-[#4fa3ff] transition-all cursor-pointer font-semibold"
          title="Visualizar a regra matemática de VRAM calculada nos testes"
        >
          <Sparkles className="w-3 h-3 text-[#4fa3ff]" />
          <span>Regra 6.3GB VRAM</span>
        </button>

        {/* Action 5: Path Shortcuts */}
        {/* PHX-FIX (achado real do usuário 2026-08-28: "TIRAR CAMINHO
            R:\Phoenix\Workstations, PORQUE NAO FAZ SENTIDO NENHUM... JA
            NAO É MAIS R:\ E SÓ FUNCIONA NA MINHA MAQUINA"): este botão
            tinha "R:\Phoenix\Workstations\..." cravado no JSX, como se
            fosse universal - era só o drive de uma máquina antiga.
            Agora monta o caminho a partir de workspacePath (vindo de
            /api/state -> PhoenixPaths.get_workspace(), a mesma pasta
            que o backend de fato usa) e, sem esse valor ainda (Engine
            offline/carregando), avisa isso em vez de inventar um
            caminho. */}
        <button
          onClick={() => {
            if (!workspacePath) {
              alert("Caminho de workspace ainda não detectado — verifique se o Phoenix Engine (porta 8000) está online e tente novamente.");
              return;
            }
            alert(`ESTRUTURA DE DIRETÓRIOS (REAL, detectada por PhoenixPaths):\n\n• ${workspacePath}\\Models\\Chat\\GGUF\\\n• ${workspacePath}\\Models\\Vision\\ (MiniCPM-V 2.6)\n• ${workspacePath}\\Models\\Voice\\Kokoro\\ (kokoro-v1.0.onnx + voices-v1.0.bin - motor de voz padrão)`);
          }}
          className="flex items-center gap-1 px-2 py-0.5 rounded bg-[#14181d] hover:bg-purple-500/20 text-[#e7e7e7] hover:text-purple-300 border border-[#262d35] hover:border-purple-400 transition-all cursor-pointer font-semibold"
          title="Ver caminhos reais do sistema de arquivos e modelos desta instalação"
        >
          <Folder className="w-3 h-3 text-purple-400" />
          <span>Pastas de Modelos</span>
        </button>

        {/* PHX-FIX (achado real do usuário 2026-08-24, "jogar fora o piper
            de vez"): "Action 6" era um atalho pra baixar o instalador
            oficial do eSpeak-NG, um fix que só fazia sentido pra quem
            ainda usava o Piper TTS (motor legado) - o Kokoro (motor padrão
            desde 2026-08-23) já traz seu próprio eSpeak-NG embutido e
            nunca precisou deste botão. Com o Piper removido de vez do
            código (drivers/piper.py apagado), este atalho ficaria
            resolvendo um problema que não existe mais - removido junto. */}

        {/* Action 7: Multi-Port Matrix Badge */}
        <div className="flex items-center gap-1 text-[9px] text-[#8d98a5] bg-[#14181d] px-2 py-0.5 rounded border border-[#262d35] ml-auto">
          <span className="text-[#37d67a] font-bold">● :3000</span>
          <span>|</span>
          <span className="text-[#ff334b] font-bold">● :8000</span>
          <span>|</span>
          <span className="text-orange-400 font-bold" title="Phoenix Forge API / Delivery Guard">● :8787</span>
          <span>|</span>
          <span className="text-white font-bold">● :8081</span>
          <span>|</span>
          <span className="text-amber-400 font-bold">● :11434</span>
          <span>|</span>
          <span className="text-cyan-400 font-bold">● :1234</span>
          <span>|</span>
          <span className="text-purple-400 font-bold">● :8010</span>
        </div>

      </div>

      {forgePanelOpen && (
        <div className="fixed inset-0 z-[100] bg-black/75 backdrop-blur-sm flex items-center justify-center p-4" onMouseDown={() => setForgePanelOpen(false)}>
          <div className="w-full max-w-5xl max-h-[88vh] overflow-hidden rounded-xl border border-[#38424d] bg-[#101419] shadow-2xl" onMouseDown={event => event.stopPropagation()}>
            <div className="flex items-center justify-between px-5 py-3 border-b border-[#2a323b] bg-[#151a20]">
              <div className="flex items-center gap-3">
                <ShieldCheck className={forgeStatus?.forge_online ? 'w-5 h-5 text-emerald-400' : 'w-5 h-5 text-amber-400'} />
                <div>
                  <div className="font-bold text-sm text-white">Phoenix Forge — Centro de Controle</div>
                  <div className="text-[10px] text-[#8d98a5]">Supervisão da Engine, segurança de GPU e validação de entregas</div>
                </div>
              </div>
              <button onClick={() => setForgePanelOpen(false)} className="p-1.5 rounded hover:bg-white/10 text-[#8d98a5] hover:text-white"><X className="w-4 h-4" /></button>
            </div>

            <div className="p-5 overflow-y-auto max-h-[calc(88vh-58px)] space-y-4">
              {forgeError && <div className="flex gap-2 p-3 rounded border border-red-500/40 bg-red-500/10 text-red-300"><AlertTriangle className="w-4 h-4 shrink-0" /><span>{forgeError}</span></div>}

              <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                {[
                  ['Estado', forgeStatus?.forge_online ? 'ONLINE' : 'OFFLINE'],
                  ['Versão', forgeStatus?.version || '—'],
                  ['Orquestração', forgeStatus?.orchestration_state || '—'],
                  ['Propriedade', forgeStatus?.supervisor?.ownership || '—'],
                  ['PID', forgeStatus?.supervisor?.pid || '—'],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg border border-[#2a323b] bg-[#0b0e12] p-3">
                    <div className="text-[9px] uppercase text-[#77818d]">{label}</div>
                    <div className="mt-1 text-xs font-bold text-white break-all">{value}</div>
                  </div>
                ))}
              </div>

              <div className="flex flex-wrap gap-2">
                <button disabled={forgeLoading} onClick={() => operateForge('start')} className="flex items-center gap-1.5 px-3 py-2 rounded bg-emerald-500/15 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/25 disabled:opacity-50"><Play className="w-3.5 h-3.5" />Iniciar supervisão</button>
                <button disabled={forgeLoading} onClick={() => operateForge('restart')} className="flex items-center gap-1.5 px-3 py-2 rounded bg-blue-500/15 border border-blue-500/40 text-blue-300 hover:bg-blue-500/25 disabled:opacity-50"><RefreshCw className={`w-3.5 h-3.5 ${forgeLoading ? 'animate-spin' : ''}`} />Reiniciar Forge</button>
                <button disabled={forgeLoading} onClick={() => operateForge('stop')} className="flex items-center gap-1.5 px-3 py-2 rounded bg-red-500/15 border border-red-500/40 text-red-300 hover:bg-red-500/25 disabled:opacity-50"><Square className="w-3.5 h-3.5" />Parar Forge</button>
                <button disabled={forgeLoading} onClick={() => refreshForge(true)} className="flex items-center gap-1.5 px-3 py-2 rounded bg-[#1b222a] border border-[#38424d] text-white hover:bg-[#252e38] disabled:opacity-50"><RefreshCw className="w-3.5 h-3.5" />Atualizar</button>
                <select value={forgeBenchmarkProfile} onChange={event => setForgeBenchmarkProfile(event.target.value as 'quick' | 'standard' | 'deep')} disabled={forgeBenchmarkLoading} className="px-3 py-2 rounded bg-[#0b0e12] border border-[#38424d] text-white disabled:opacity-50" title="Perfil do benchmark">
                  <option value="quick">Rápido</option><option value="standard">Padrão</option><option value="deep">Profundo</option>
                </select>
                <button disabled={forgeLoading || forgeBenchmarkLoading || !forgeStatus?.forge_online} onClick={() => runForgeBenchmark(false)} className="flex items-center gap-1.5 px-3 py-2 rounded bg-amber-500/15 border border-amber-500/40 text-amber-300 hover:bg-amber-500/25 disabled:opacity-50"><Activity className={`w-3.5 h-3.5 ${forgeBenchmarkLoading ? 'animate-pulse' : ''}`} />{forgeBenchmarkLoading ? 'Medindo…' : 'Benchmark seguro'}</button>
                <button disabled={forgeLoading || forgeBenchmarkLoading || !forgeStatus?.forge_online} onClick={() => runForgeBenchmark(true)} className="flex items-center gap-1.5 px-3 py-2 rounded bg-red-500/10 border border-red-500/35 text-red-300 hover:bg-red-500/20 disabled:opacity-50"><Zap className="w-3.5 h-3.5" />Benchmark GPU</button>
                {forgeBenchmarkLoading && <button onClick={cancelForgeBenchmark} className="flex items-center gap-1.5 px-3 py-2 rounded bg-red-500/20 border border-red-500/50 text-red-200"><Square className="w-3.5 h-3.5" />Cancelar</button>}
              </div>
              {forgeBenchmarkLoading && forgeBenchmarkJob && <div className="rounded-lg border border-amber-500/30 bg-[#0b0e12] p-3"><div className="flex justify-between text-[10px] mb-2"><span>{forgeBenchmarkJob.progress?.module||forgeBenchmarkJob.progress?.phase||'Preparando'}</span><span>{forgeBenchmarkJob.progress?.percent??0}%</span></div><div className="h-2 rounded bg-[#222a33] overflow-hidden"><div className="h-full bg-amber-400 transition-all" style={{width:`${forgeBenchmarkJob.progress?.percent??0}%`}}/></div></div>}

              {forgeBenchmarkResult && (
                <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 overflow-hidden">
                  <div className="px-4 py-3 border-b border-amber-500/20 flex flex-wrap items-center justify-between gap-2">
                    <div className="font-bold text-xs text-white">Resultado do benchmark — {forgeBenchmarkResult.profile}</div>
                    <div className={forgeBenchmarkResult.status === 'PASS' ? 'text-emerald-400 font-bold' : 'text-red-400 font-bold'}>{forgeBenchmarkResult.status || 'CONCLUÍDO'} · qualidade {forgeBenchmarkResult.quality_score ?? '—'}</div>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[10px]"><thead className="text-[#8d98a5]"><tr><th className="text-left p-2">Módulo</th><th className="text-left p-2">Estado</th><th className="text-left p-2">Duração</th><th className="text-left p-2">Métrica principal</th></tr></thead><tbody>
                      {(forgeBenchmarkResult.benchmarks || []).map((entry: any, index: number) => <tr key={entry.name || index} className="border-t border-amber-500/10"><td className="p-2 text-white">{entry.name || entry.result?.module || '—'}</td><td className={`p-2 ${entry.valid_score === false || entry.result?.passed === false ? 'text-red-400' : 'text-emerald-400'}`}>{entry.valid_score === false || entry.result?.passed === false ? 'FALHOU' : 'OK'}</td><td className="p-2">{entry.result?.duration_s ?? '—'} s</td><td className="p-2">{benchmarkMetric(entry)}</td></tr>)}
                    </tbody></table>
                  </div>
                </div>
              )}

              <div className="grid md:grid-cols-2 gap-3">
                <div className="rounded-lg border border-[#2a323b] bg-[#0b0e12] p-4">
                  <div className="font-bold text-xs text-white mb-3">Segurança da GPU</div>
                  <div className="space-y-1.5 text-[11px]">
                    <div>Dispositivo: <span className="text-white">{forgeSafety?.device?.name || '—'}</span></div>
                    <div>Saúde: <span className="text-amber-300">{forgeSafety?.device_health || '—'}</span></div>
                    <div>Autorização: <span className="text-white">{forgeSafety?.authorization?.state || '—'}</span></div>
                    <div>Modo efetivo: <span className="text-white">{forgeSafety?.authorization?.effective_mode || '—'}</span></div>
                    <div>Falhas registradas: <span className="text-white">{forgeSafety?.failure_count ?? '—'}</span></div>
                  </div>
                </div>
                <div className="rounded-lg border border-[#2a323b] bg-[#0b0e12] p-4">
                  <div className="font-bold text-xs text-white mb-3">Supervisor da Engine</div>
                  <div className="space-y-1.5 text-[11px]">
                    <div>Supervisor: <span className="text-white">{forgeStatus?.supervisor?.supervisor_active ? 'ATIVO' : 'INATIVO'}</span></div>
                    <div>Processo gerenciado: <span className="text-white">{forgeStatus?.supervisor?.process_managed ? 'SIM' : 'NÃO'}</span></div>
                    <div>Uptime: <span className="text-white">{forgeStatus?.supervisor?.uptime_s ?? '—'} s</span></div>
                    <div className="break-all">Raiz: <span className="text-white">{forgeStatus?.supervisor?.forge_root || '—'}</span></div>
                    <div>Último código de saída: <span className="text-white">{forgeStatus?.supervisor?.last_exit_code ?? '—'}</span></div>
                  </div>
                </div>
              </div>

              <div className="rounded-lg border border-[#2a323b] bg-[#0b0e12] overflow-hidden">
                <div className="px-4 py-3 border-b border-[#2a323b] font-bold text-xs text-white">Últimas decisões de entrega</div>
                <div className="overflow-x-auto">
                  <table className="w-full text-[10px]">
                    <thead className="text-[#8d98a5] bg-[#11161c]"><tr><th className="text-left p-2">Data</th><th className="text-left p-2">Status</th><th className="text-left p-2">Modo</th><th className="text-left p-2">Entrega</th><th className="text-left p-2">Runtime</th><th className="text-left p-2">Forge</th></tr></thead>
                    <tbody>
                      {forgeExecutions.slice().reverse().map((entry: any, index: number) => (
                        <tr key={entry.execution_id || index} className="border-t border-[#202730]">
                          <td className="p-2 whitespace-nowrap">{entry.recorded_at ? new Date(entry.recorded_at).toLocaleTimeString() : '—'}</td>
                          <td className="p-2 text-white">{entry.status || '—'}</td>
                          <td className="p-2">{entry.effective_mode || '—'}</td>
                          <td className={`p-2 ${entry.deliver ? 'text-emerald-400' : 'text-red-400'}`}>{entry.deliver ? 'SIM' : 'NÃO'}</td>
                          <td className="p-2">{entry.runtime_latency_s ?? '—'} s</td>
                          <td className="p-2">{entry.timing?.total_s ?? '—'} s</td>
                        </tr>
                      ))}
                      {!forgeExecutions.length && <tr><td colSpan={6} className="p-5 text-center text-[#77818d]">Nenhuma execução registrada ou Forge offline.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
};
