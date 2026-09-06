import React, { useState } from 'react';
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
          onClick={() => alert("REGRA MÁGICA DOS 6.3GB VRAM (Polaris RX 580):\n\n8.0 GB (VRAM Total) - 1.2 GB (Compute Buffer) - 0.5 GB (Folga) = 6.3 GB Peso Máx.\n\n• FLUX.1 Q3 (5.0GB): Roda em 768x768 (2253s) ✅\n• FLUX.1 Q4 (6.8GB): Exige 512x512 ou gera OOM no buffer ❌\n• SD 3.5 Medium: Roda com --offload-to-cpu ✅")}
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
          <span className="text-white font-bold">● :8081</span>
          <span>|</span>
          <span className="text-amber-400 font-bold">● :11434</span>
          <span>|</span>
          <span className="text-cyan-400 font-bold">● :1234</span>
          <span>|</span>
          <span className="text-purple-400 font-bold">● :8010</span>
        </div>

      </div>

    </div>
  );
};
