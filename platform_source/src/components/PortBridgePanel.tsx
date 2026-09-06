import React, { useState } from 'react';
import { Server, ArrowRightLeft, Zap, Shield, RefreshCw, Send, CheckCircle2, AlertTriangle, Radio } from 'lucide-react';
import { PortNode, BridgePacket } from '../types';

// PHX-FIX (auditoria completa — "tirar todos os fallbacks", achado do
// "Execute Port Ping" / "Live Inter-Port Packet Inspector"): este
// componente inteiro era decorativo. `handleTestBridge` não fazia
// nenhuma chamada de rede (só um `setTimeout` de 800ms que sempre
// devolvia "[200 OK] Bridge Response in 2.8ms", ligado ou desligado o
// Engine), `livePackets` nascia com 4 pacotes fabricados e nunca era
// atualizado apesar do rótulo "Stream Auto-Refresh: 1000ms", e os dois
// cards de nó (LATENCY 3.1ms / THROUGHPUT 850.4 Kbps) eram texto solto
// no JSX - nem liam a prop `ports`, que já vinha do componente pai mas
// nunca era usada aqui. Agora `ports` e `packets` vêm de verdade de
// EngineMissionControl.tsx (que faz 1 ping real por segundo contra
// /api/ping e /api/health), e o botão de ping manual chama
// `onManualPing`, a mesma função real usada pelo loop automático - não
// existem mais dois caminhos (um real, um decorativo) fazendo a mesma
// coisa.
interface PortBridgeProps {
  ports: PortNode[];
  packets: BridgePacket[];
  onManualPing: () => Promise<{ engineOnline: boolean; engineLatencyMs: number; aviaryLatencyMs: number }>;
  onTriggerCommand: (cmd: string) => void;
  // PHX-FIX (varredura 2026-08-21, achado 3): "AGENT SWARM: 4 Autonomous
  // Agents" era um texto fixo no JSX, não vinha da contagem real de
  // agentes - batia por coincidência, mas ficaria desatualizado em
  // silêncio se o roster mudasse. Agora vem do array real de agentes
  // (agents.length em EngineMissionControl.tsx).
  agentCount: number;
}

export const PortBridgePanel: React.FC<PortBridgeProps> = ({ ports, packets, onManualPing, onTriggerCommand, agentCount }) => {
  const [testResult, setTestResult] = useState<string | null>(null);
  const [isTesting, setIsTesting] = useState(false);

  const enginePort = ports.find(p => p.port === 8000);
  const aviaryPort = ports.find(p => p.port === 3000);

  const handleTestBridge = async () => {
    setIsTesting(true);
    setTestResult('Enviando ping real Port 3000 (Aviary) ➔ Port 8000 (Engine)...');
    try {
      const r = await onManualPing();
      setTestResult(
        r.engineOnline
          ? `[ONLINE] Phoenix Engine respondeu em ${r.engineLatencyMs.toFixed(1)}ms (round-trip via Port 3000). Aviary local: ${r.aviaryLatencyMs.toFixed(1)}ms.`
          : `[OFFLINE] Ponte Port 3000 respondeu (${r.aviaryLatencyMs.toFixed(1)}ms), mas o Phoenix Engine (porta 8000) não respondeu a tempo ou está desligado.`
      );
    } catch (err: any) {
      setTestResult(`[FALHOU] ${err?.message || 'Erro de rede ao tentar pingar a ponte.'}`);
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <div className="bg-[#101317] border border-[#262d35] rounded-lg p-5 space-y-6">
      
      {/* Title & Red/White Technical Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pb-4 border-b border-[#262d35]">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-[#ff334b] animate-ping" />
            <h2 className="text-base font-bold text-white tracking-widest uppercase font-display">
              PHOENIX DUAL-PORT TOPOLOGY ROUTER
            </h2>
          </div>
          <p className="text-xs text-[#8d98a5] mt-1 font-mono">
            High-speed inter-process communication bridge between Port 8000 (Backend Engine) and Port 3000 (Aviary Web Platform).
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => onTriggerCommand('ports')}
            className="px-3 py-1.5 rounded bg-[#1a1f26] border border-[#262d35] text-xs font-mono text-white hover:border-[#ff334b] transition-all flex items-center gap-1.5"
          >
            <Radio className="w-3.5 h-3.5 text-[#ff334b]" />
            <span>CLI Port Scan</span>
          </button>
        </div>
      </div>

      {/* Visual Dual Node Bridge */}
      <div className="grid grid-cols-1 md:grid-cols-11 gap-4 items-center">
        
        {/* NODE 1: PORT 8000 - PHOENIX ENGINE */}
        <div className="md:col-span-5 bg-[#0b0d10] border-2 border-[#ff334b] rounded-lg p-4 relative overflow-hidden shadow-[0_0_20px_rgba(255,51,75,0.15)]">
          <div className="absolute top-0 right-0 bg-[#ff334b] text-white font-bold text-[10px] tracking-widest px-2.5 py-0.5 rounded-bl uppercase">
            PORT 8000
          </div>
          
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded bg-[#ff334b]/20 flex items-center justify-center text-[#ff334b]">
              <Zap className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white tracking-wider">PHOENIX ENGINE</h3>
              <p className="text-[11px] text-[#ff334b] font-mono">Local Runtime & RAG Backend</p>
            </div>
          </div>

          <div className="space-y-2 text-xs font-mono text-[#8d98a5]">
            <div className="flex justify-between py-1 border-b border-[#262d35]">
              <span>ENDPOINT</span>
              <span className="text-white font-bold">http://localhost:8000</span>
            </div>
            <div className="flex justify-between py-1 border-b border-[#262d35]">
              <span>COMPUTE TARGET</span>
              <span className="text-[#4fa3ff]">Detectado pelo Engine</span>
            </div>
            <div className="flex justify-between py-1 border-b border-[#262d35]">
              <span>SYSTEM MEMORY</span>
              <span className="text-white">Consulte System Report</span>
            </div>
            <div className="flex justify-between py-1">
              <span>STATUS</span>
              <span className={`font-bold ${enginePort?.status === 'ONLINE' ? 'text-[#37d67a]' : 'text-[#ff334b]'}`}>
                {enginePort?.status || 'STANDBY'}
              </span>
            </div>
            <div className="flex justify-between py-1">
              <span>LATENCY</span>
              <span className="text-[#37d67a] font-bold">
                {enginePort ? `${enginePort.latencyMs.toFixed(1)} ms (via Port 3000)` : 'Aguardando ping...'}
              </span>
            </div>
          </div>
        </div>

        {/* BRIDGE ARROWS / LINK */}
        <div className="md:col-span-1 flex flex-col items-center justify-center py-2">
          <div className="w-10 h-10 rounded-full bg-[#1a1f26] border border-[#ff334b]/60 flex items-center justify-center text-[#ff334b] shadow-[0_0_15px_rgba(255,51,75,0.3)]">
            <ArrowRightLeft className="w-4 h-4 animate-pulse" />
          </div>
          <span className="text-[10px] font-mono text-[#8d98a5] mt-1 text-center">IPC BUS</span>
        </div>

        {/* NODE 2: PORT 3000 - PHOENIX AVIARY PLATFORM */}
        <div className="md:col-span-5 bg-[#0b0d10] border-2 border-white rounded-lg p-4 relative overflow-hidden shadow-[0_0_20px_rgba(255,255,255,0.1)]">
          <div className="absolute top-0 right-0 bg-white text-black font-bold text-[10px] tracking-widest px-2.5 py-0.5 rounded-bl uppercase">
            PORT 3000
          </div>
          
          <div className="flex items-center gap-3 mb-3">
            <div className="w-8 h-8 rounded bg-white/20 flex items-center justify-center text-white">
              <Server className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-white tracking-wider">PHOENIX AVIARY PLATFORM</h3>
              <p className="text-[11px] text-[#4fa3ff] font-mono">Mission Control & Multi-Agent UI</p>
            </div>
          </div>

          <div className="space-y-2 text-xs font-mono text-[#8d98a5]">
            <div className="flex justify-between py-1 border-b border-[#262d35]">
              <span>ENDPOINT</span>
              <span className="text-white font-bold">http://localhost:3000</span>
            </div>
            <div className="flex justify-between py-1 border-b border-[#262d35]">
              <span>AGENT SWARM</span>
              <span className="text-[#37d67a] font-bold">{agentCount} Autonomous Agent{agentCount === 1 ? '' : 's'}</span>
            </div>
            <div className="flex justify-between py-1 border-b border-[#262d35]">
              <span>PROTOCOL</span>
              <span className="text-white">HTTP/REST + WebSocket Bus</span>
            </div>
            <div className="flex justify-between py-1">
              <span>LATENCY</span>
              <span className="text-[#4fa3ff] font-bold">
                {aviaryPort ? `${aviaryPort.latencyMs.toFixed(1)} ms (Local, sem hop no Python)` : 'Aguardando ping...'}
              </span>
            </div>
          </div>
        </div>

      </div>

      {/* Manual Bridge Ping */}
      <div className="bg-[#0b0d10] border border-[#262d35] rounded-lg p-4">
        <h4 className="text-xs font-bold text-white uppercase tracking-wider mb-2 flex items-center gap-2">
          <Send className="w-3.5 h-3.5 text-[#ff334b]" />
          <span>Ping Manual da Ponte (Port 3000 ➔ Port 8000)</span>
        </h4>
        <p className="text-[11px] text-[#8d98a5] font-mono mb-3">
          Dispara imediatamente o mesmo health-check real que já roda sozinho a cada 1s
          em segundo plano (ver tabela abaixo) — útil pra confirmar o estado exato na hora.
        </p>

        <button
          onClick={handleTestBridge}
          disabled={isTesting}
          className="px-4 py-2 bg-[#ff334b] hover:bg-[#ff203a] text-white font-bold text-xs uppercase font-mono tracking-wider rounded transition-all disabled:opacity-50 flex items-center justify-center gap-1.5 whitespace-nowrap"
        >
          {isTesting ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Zap className="w-3.5 h-3.5" />}
          <span>Execute Port Ping</span>
        </button>

        {testResult && (
          <div className="mt-3 p-2.5 rounded bg-[#14181d] border border-[#ff334b]/40 text-xs font-mono text-white flex items-center gap-2 animate-fadeIn">
            <CheckCircle2 className="w-4 h-4 text-[#37d67a] flex-shrink-0" />
            <span>{testResult}</span>
          </div>
        )}
      </div>

      {/* Live Inter-Port Packet Stream */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h4 className="text-xs font-bold text-white uppercase tracking-wider font-mono">
            Live Inter-Port Packet Inspector
          </h4>
          <span className="text-[11px] text-[#8d98a5] font-mono">Stream Auto-Refresh: 1000ms (real)</span>
        </div>
        <p className="text-[10px] text-[#8d98a5] font-mono mb-2">
          Captura só o canal de health-check real (GET /api/health, 1x/s) — não é uma
          sniffagem de todo o tráfego entre as duas portas, isso exigiria instrumentar
          cada rota do server.ts individualmente.
        </p>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono border border-[#262d35]">
            <thead className="bg-[#14181d] text-[#8d98a5] uppercase text-[10px] tracking-wider border-b border-[#262d35]">
              <tr>
                <th className="py-2 px-3">Time</th>
                <th className="py-2 px-3">Route</th>
                <th className="py-2 px-3">Type</th>
                <th className="py-2 px-3">Payload Details</th>
                <th className="py-2 px-3 text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#262d35] bg-[#0b0d10]">
              {packets.length === 0 && (
                <tr>
                  <td colSpan={5} className="py-3 px-3 text-center text-[#8d98a5]">
                    Aguardando primeiro ping real...
                  </td>
                </tr>
              )}
              {packets.map((pkt) => (
                <tr key={pkt.id} className="hover:bg-[#14181d] transition-colors">
                  <td className="py-2 px-3 text-[#8d98a5]">{pkt.time}</td>
                  <td className="py-2 px-3">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                      pkt.from === 3000 ? 'bg-white text-black' : 'bg-[#ff334b] text-white'
                    }`}>
                      :{pkt.from} ➔ :{pkt.to}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-white font-medium">{pkt.type}</td>
                  <td className="py-2 px-3 text-[#8d98a5] truncate max-w-[250px]">{pkt.payload}</td>
                  <td className="py-2 px-3 text-right">
                    {/* PHX-FIX: o badge era sempre verde "[status OK]" antes,
                        mesmo quando o pacote representava uma falha - agora
                        reflete o `engineOnline` real embutido no payload
                        (GET /api/health sempre devolve HTTP 200, mesmo com o
                        Engine desligado - `engineOnline:false` vai no corpo,
                        não no status HTTP, então o status sozinho não basta
                        pra saber se deu certo). */}
                    <span className={`font-bold ${pkt.status >= 200 && pkt.status < 300 && !pkt.payload.includes('false') ? 'text-[#37d67a]' : 'text-[#ff334b]'}`}>
                      [{pkt.status || 'ERR'}]
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

    </div>
  );
};
