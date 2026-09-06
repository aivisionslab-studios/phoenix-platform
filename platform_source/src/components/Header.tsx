import React from 'react';
import { Activity, Cpu, Server, Terminal, Shield, Zap, RefreshCw, HardDrive, Database, Layers } from 'lucide-react';
import { PortNode } from '../types';

interface HeaderProps {
  uptime: string;
  clock: string;
  ports: PortNode[];
  activeView: 'dashboard' | 'ports' | 'swarm' | 'vulkan' | 'rag';
  setActiveView: (view: 'dashboard' | 'ports' | 'swarm' | 'vulkan' | 'rag') => void;
  onOpenHardware: () => void;
  onOpenRag: () => void;
  onOpenSystemReport: () => void;
  stressActive: boolean;
  onToggleStress: () => void;
  onOpenStandalone?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  uptime,
  clock,
  ports,
  activeView,
  setActiveView,
  onOpenHardware,
  onOpenRag,
  onOpenSystemReport,
  stressActive,
  onToggleStress,
  onOpenStandalone
}) => {
  // PHX-FIX (auditoria platform_source 2026-08-20, achado A6): antes, quando
  // `ports` ainda não tinha entrada pra 8000/3000 (primeiro render, antes do
  // primeiro ping real completar - ver PortBridgePanel.tsx), o fallback
  // afirmava 'ONLINE' com latência inventada (3.2ms/1.2ms fixos) - exatamente
  // o padrão de dado fabricado que essa auditoria já vem eliminando em outras
  // rotas. Agora o fallback é honesto: 'STANDBY' (não temos confirmação
  // nenhuma ainda) com latencyMs 0, renderizado como "--ms" em vez de um
  // número que nunca veio de ping nenhum.
  const enginePort = ports.find(p => p.port === 8000) || { status: 'STANDBY' as const, latencyMs: 0 };
  const aviaryPort = ports.find(p => p.port === 3000) || { status: 'STANDBY' as const, latencyMs: 0 };

  return (
    <header className="border-b border-[#262d35] bg-[#14181d] px-4 md:px-8 py-3.5 flex-shrink-0">
      <div className="flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
        
        {/* Brand & Identity: RED & WHITE Theme */}
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-[#ff334b]/10 border border-[#ff334b] flex items-center justify-center text-[#ff334b] shadow-[0_0_15px_rgba(255,51,75,0.2)]">
            <Zap className="w-5 h-5 animate-pulse" />
          </div>

          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-lg md:text-xl font-bold tracking-[0.18em] uppercase text-white font-display">
                AIVISIONSLAB <span className="text-[#ff334b] px-2 py-0.5 rounded bg-[#ff334b]/15 border border-[#ff334b]/40 text-sm tracking-widest">STUDIO GROUP</span>
              </h1>
              <span className="text-xs px-2 py-0.5 rounded bg-[#262d35] text-[#8d98a5] border border-[#3a4450]">
                v4.5 REVIVAL
              </span>
            </div>
            <p className="text-[11px] md:text-xs text-[#8d98a5] tracking-wider uppercase mt-0.5 flex items-center gap-2 flex-wrap">
              <span className="text-[#ff334b] font-semibold">PHOENIX ENGINE [PORT 8000]</span>
              <span className="text-[#3a4450]">•</span>
              <span className="text-white font-semibold">PHOENIX AVIARY PLATFORM [PORT 3000]</span>
              <span className="text-[#3a4450]">•</span>
              <span>HARDWARE REVIVAL OS</span>
            </p>
          </div>
        </div>

        {/* Dual Port Quick Status & Telemetry */}
        <div className="flex items-center gap-2 md:gap-3 flex-wrap">
          
          {/* Port 8000 Badge */}
          <button
            onClick={() => setActiveView('ports')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded border text-xs tracking-wider font-mono transition-all ${
              activeView === 'ports'
                ? 'bg-[#ff334b]/20 border-[#ff334b] text-white'
                : 'bg-[#0b0d10] border-[#262d35] hover:border-[#ff334b]/60 text-[#e7e7e7]'
            }`}
            title="Inspect Port 8000: Phoenix Engine (Vulkan & LLM Backend)"
          >
            <span className="relative flex h-2 w-2">
              {enginePort.status === 'ONLINE' && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#37d67a] opacity-75"></span>}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${enginePort.status === 'ONLINE' ? 'bg-[#37d67a]' : 'bg-[#8d98a5]'}`}></span>
            </span>
            <span className="text-[#8d98a5]">ENGINE:</span>
            <span className="text-[#ff334b] font-bold">:8000</span>
            <span className="text-[10px] text-[#37d67a]">{enginePort.latencyMs ? `${enginePort.latencyMs}ms` : '--ms'}</span>
          </button>

          {/* Port 3000 Badge */}
          <button
            onClick={() => setActiveView('ports')}
            className={`flex items-center gap-2 px-3 py-1.5 rounded border text-xs tracking-wider font-mono transition-all ${
              activeView === 'ports'
                ? 'bg-[#4fa3ff]/20 border-[#4fa3ff] text-white'
                : 'bg-[#0b0d10] border-[#262d35] hover:border-[#4fa3ff]/60 text-[#e7e7e7]'
            }`}
            title="Inspect Port 3000: Phoenix Aviary Platform (Mission Control UI & Swarm)"
          >
            <span className="relative flex h-2 w-2">
              {aviaryPort.status === 'ONLINE' && <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#37d67a] opacity-75"></span>}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${aviaryPort.status === 'ONLINE' ? 'bg-[#37d67a]' : 'bg-[#8d98a5]'}`}></span>
            </span>
            <span className="text-[#8d98a5]">AVIARY:</span>
            <span className="text-[#4fa3ff] font-bold">:3000</span>
            <span className="text-[10px] text-[#37d67a]">{aviaryPort.latencyMs ? `${aviaryPort.latencyMs}ms` : '--ms'}</span>
          </button>

          {/* Stress Loop Switch */}
          <button
            onClick={onToggleStress}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-mono font-medium transition-all ${
              stressActive
                ? 'bg-[#ff334b] text-white border border-[#ff334b] shadow-[0_0_12px_rgba(255,51,75,0.4)] animate-pulse'
                : 'bg-[#1a1f26] text-[#8d98a5] border border-[#262d35] hover:text-white hover:border-[#3a4450]'
            }`}
            title="Simulate compute stress test loop across Vulkan compute queues"
          >
            <Activity className="w-3.5 h-3.5" />
            <span>STRESS: {stressActive ? 'ON' : 'OFF'}</span>
          </button>

          {/* Clock & Uptime */}
          <div className="hidden xl:flex flex-col items-end text-[11px] font-mono text-[#8d98a5] pl-2 border-l border-[#262d35]">
            <span className="text-white font-medium">{clock}</span>
            <span>UP: {uptime}</span>
          </div>

        </div>

      </div>

      {/* Navigation Bar / Mode Switches */}
      <div className="mt-3 pt-2.5 border-t border-[#262d35]/60 flex items-center justify-between gap-2 overflow-x-auto">
        <div className="flex items-center gap-1.5">
          <button
            onClick={() => setActiveView('dashboard')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs uppercase tracking-wider font-mono transition-all ${
              activeView === 'dashboard'
                ? 'bg-white text-black font-bold shadow-sm'
                : 'text-[#8d98a5] hover:text-white hover:bg-[#1a1f26]'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>Console Deck</span>
          </button>

          <button
            onClick={() => setActiveView('ports')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs uppercase tracking-wider font-mono transition-all ${
              activeView === 'ports'
                ? 'bg-[#ff334b] text-white font-bold shadow-sm'
                : 'text-[#8d98a5] hover:text-white hover:bg-[#1a1f26]'
            }`}
          >
            <Server className="w-3.5 h-3.5" />
            <span>Port 8000 ↔ 3000 Bridge</span>
          </button>

          <button
            onClick={() => setActiveView('swarm')}
            className={`flex items-center gap-1.5 px-3 py-1 rounded text-xs uppercase tracking-wider font-mono transition-all ${
              activeView === 'swarm'
                ? 'bg-[#4fa3ff] text-black font-bold shadow-sm'
                : 'text-[#8d98a5] hover:text-white hover:bg-[#1a1f26]'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>Aviary Swarm</span>
          </button>
        </div>

        {/* Side Drawers Action Triggers */}
        <div className="flex items-center gap-2">
          <button
            onClick={onOpenSystemReport}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs text-[#8d98a5] hover:text-[#f59e0b] hover:bg-[#1a1f26] border border-transparent hover:border-[#262d35] transition-all"
            title="Gerar relatório real do sistema"
          >
            <Shield className="w-3.5 h-3.5 text-[#f59e0b]" />
            <span className="hidden sm:inline">System Report</span>
          </button>
          <button
            onClick={onOpenHardware}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs text-[#8d98a5] hover:text-[#4fa3ff] hover:bg-[#1a1f26] border border-transparent hover:border-[#262d35] transition-all"
            title="Configure Hardware & Run Vulkan Benchmark"
          >
            <Cpu className="w-3.5 h-3.5 text-[#4fa3ff]" />
            <span className="hidden sm:inline">Hardware Deck</span>
          </button>

          <button
            onClick={onOpenRag}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs text-[#8d98a5] hover:text-[#37d67a] hover:bg-[#1a1f26] border border-transparent hover:border-[#262d35] transition-all"
            title="Manage Vector Documents & Knowledge Base"
          >
            <Database className="w-3.5 h-3.5 text-[#37d67a]" />
            <span className="hidden sm:inline">RAG Docs</span>
          </button>
        </div>
      </div>
    </header>
  );
};
