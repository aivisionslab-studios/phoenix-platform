import React, { useEffect, useState } from 'react';
import { HardwareProfile, InferenceConfig, EnvironmentService } from '../types';
import { Cpu, HardDrive, Zap, Layers, Server, Activity, Shield, RefreshCw } from 'lucide-react';

interface MetricCardsProps {
  hardware: HardwareProfile;
  inference: InferenceConfig;
  services: EnvironmentService[];
  ragCount: number;
  agentCount: number;
  onOpenHardware: () => void;
  onOpenRag: () => void;
  onOpenSwarm: () => void;
  onOpenPorts: () => void;
}

export const MetricCards: React.FC<MetricCardsProps> = ({
  hardware,
  inference,
  services,
  ragCount,
  agentCount,
  onOpenHardware,
  onOpenRag,
  onOpenSwarm,
  onOpenPorts,
}) => {
  // PHX-NEW (destravar Ollama como 2ª opção de engine de texto, a pedido
  // explícito): estado real, buscado de /api/engine/text-runtime -
  // `infer`, `resident research` e o Aviary Architect do Swarm passam a
  // resolver "chat"/"reasoning" no catalog/models.json usando essa
  // preferência (ver resident_manager.py / evaluator.py /
  // reasoning_engine.py). Ollama é sempre a segunda opção - mais lenta
  // (roda via Docker, porta 11434), nunca troca sozinha, só quando o
  // usuário clica aqui.
  const [textEngine, setTextEngineState] = useState<string | null>(null);
  const [textEngineOptions, setTextEngineOptions] = useState<string[]>(['llama.cpp', 'ollama']);
  const [textEngineBusy, setTextEngineBusy] = useState(false);
  const [textEngineError, setTextEngineError] = useState<string | null>(null);

  // PHX-FIX (varredura 2026-08-21, achado 1.1): RULES/MISSION/PLANNER
  // mostravam "[✓] ACTIVE"/"[!] READY"/"[✓] READY" fixos no JSX, sem
  // nenhum prop ou state por trás - ficava "ACTIVE"/"READY" mesmo com o
  // backend inteiro desligado. Não existe hoje, em lugar nenhum do
  // kernel, um health-check real de "rules" ou "planner" exposto por
  // HTTP (RuleEvaluator/PlannerEngine são só usados internamente por
  // /api/command, sem endpoint de status próprio) - inventar um agora
  // seria criar uma métrica sem lastro só pra preencher o espaço, o
  // mesmo erro que estamos corrigindo. RULES e PLANNER foram removidos.
  // MISSION virou uma checagem real: GET /api/missions já existe e
  // devolve o catálogo de pacotes de verdade (CatalogEngine, catalog/
  // essentials|studios|suites) - agora mostramos o resultado real dessa
  // chamada (quantidade carregada, vazio, ou erro), nunca mais um
  // "READY" incondicional.
  const [missionsStatus, setMissionsStatus] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [missionsCount, setMissionsCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    fetch('/api/engine/text-runtime')
      .then(r => r.json().catch(() => null))
      .then(data => {
        if (cancelled || !data) return;
        if (data.engine) setTextEngineState(data.engine);
        if (Array.isArray(data.available)) setTextEngineOptions(data.available);
      })
      .catch(() => {});

    fetch('/api/missions')
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(data => {
        if (cancelled) return;
        const list = Array.isArray(data) ? data : [];
        setMissionsCount(list.length);
        setMissionsStatus(list.length > 0 ? 'ready' : 'empty');
      })
      .catch(() => {
        if (!cancelled) setMissionsStatus('error');
      });

    return () => { cancelled = true; };
  }, []);

  const handleSetTextEngine = async (engine: string) => {
    if (engine === textEngine || textEngineBusy) return;
    setTextEngineBusy(true);
    setTextEngineError(null);
    try {
      const res = await fetch('/api/engine/text-runtime', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ engine }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      setTextEngineState(data.engine);
    } catch (err: any) {
      setTextEngineError(err?.message || 'Falha ao trocar engine de texto.');
    } finally {
      setTextEngineBusy(false);
    }
  };

  // Helper for ASCII bars
  const renderBar = (percent: number, colorClass: string = 'text-[#ff334b]') => {
    const totalChars = 20;
    const filledChars = Math.round((percent / 100) * totalChars);
    const emptyChars = totalChars - filledChars;
    return (
      <div className="font-mono text-sm tracking-tighter mt-1 flex items-center justify-between">
        <span>
          <span className={colorClass}>{'█'.repeat(filledChars)}</span>
          <span className="text-[#262d35]">{'░'.repeat(emptyChars)}</span>
        </span>
        <span className="text-xs font-bold text-white ml-2">{percent}%</span>
      </div>
    );
  };

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-px bg-[#262d35] border-b border-[#262d35] flex-shrink-0">
      
      {/* CARD 1: HARDWARE PROFILE */}
      <div className="bg-[#0b0d10] p-4 sm:p-5 flex flex-col justify-between group hover:bg-[#0e1115] transition-colors relative">
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button 
            onClick={onOpenHardware}
            className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-[#ff334b]/20 text-[#ff334b] border border-[#ff334b]/40 hover:bg-[#ff334b] hover:text-white transition-all"
          >
            Config
          </button>
        </div>

        <div>
          <div className="text-[#ff334b] text-xs font-bold tracking-[0.2em] mb-3 pb-2 border-b border-[#262d35] uppercase flex items-center justify-between">
            <span>━━ HARDWARE PROFILE ━━</span>
            <Cpu className="w-3.5 h-3.5 text-[#ff334b]" />
          </div>

          <div className="space-y-1.5 text-xs font-mono">
            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">CPU</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-white font-bold truncate max-w-[150px]">{hardware.cpu}</span>
            </div>

            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">RAM</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-[#4fa3ff] font-bold">{hardware.ram}</span>
            </div>

            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">GPU</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-[#ff334b] font-bold">{hardware.gpu}</span>
            </div>

            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">VRAM</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-white font-bold">{hardware.vram}</span>
            </div>

            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">BACKEND</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-[#37d67a] font-bold">{hardware.backend}</span>
            </div>
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-[#262d35]">
          <div className="flex items-center justify-between text-[11px] font-mono mb-1">
            <span className="text-[#8d98a5] uppercase">MACHINE BUDGET SCORE</span>
            <span className="text-[#ff334b] font-bold">{hardware.temperatureC > 0 ? `${hardware.temperatureC}°C` : 'TEMP. N/D'}</span>
          </div>
          {renderBar(hardware.gpuScore, 'text-[#ff334b]')}
        </div>
      </div>

      {/* CARD 2: ENVIRONMENT & PORTS */}
      <div className="bg-[#0b0d10] p-4 sm:p-5 flex flex-col justify-between group hover:bg-[#0e1115] transition-colors relative">
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button 
            onClick={onOpenPorts}
            className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-[#4fa3ff]/20 text-[#4fa3ff] border border-[#4fa3ff]/40 hover:bg-[#4fa3ff] hover:text-black transition-all"
          >
            Ports
          </button>
        </div>

        <div>
          <div className="text-white text-xs font-bold tracking-[0.2em] mb-3 pb-2 border-b border-[#262d35] uppercase flex items-center justify-between">
            <span>━━ ENVIRONMENT ━━</span>
            <Server className="w-3.5 h-3.5 text-[#37d67a]" />
          </div>

          <div className="space-y-1.5 text-xs font-mono">
            {services.slice(0, 4).map((srv) => (
              <div 
                key={srv.name} 
                className="flex items-center"
                title={`Estado verificado: ${srv.detail}`}
              >
                <span className="text-[#8d98a5] uppercase">{srv.name}</span>
                <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
                <span className={
                  srv.status === 'online' ? 'text-[#37d67a] font-bold' :
                  srv.status === 'warning' ? 'text-[#f7b731] font-bold' :
                  'text-[#ff334b] font-bold'
                }>
                  {srv.status === 'online' ? '[●] ONLINE' : srv.status === 'warning' ? '[!] STANDBY' : '[X] OFFLINE'}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-[#262d35] space-y-1 text-xs font-mono">
          {services.slice(4).map((srv) => (
            <div 
              key={srv.name} 
              className="flex items-center"
            >
              <span className="text-[#8d98a5] uppercase">{srv.name}</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className={srv.status === 'online' ? 'text-[#37d67a]' : 'text-[#8d98a5]'}>
                {srv.status === 'online' ? '[✓] ONLINE' : '[○] STANDBY'}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* CARD 3: INFERENCE ENGINE */}
      <div className="bg-[#0b0d10] p-4 sm:p-5 flex flex-col justify-between group hover:bg-[#0e1115] transition-colors relative">
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-[#37d67a]/20 text-[#37d67a] border border-[#37d67a]/40">
            Port 8000
          </span>
        </div>

        <div>
          <div className="text-[#4fa3ff] text-xs font-bold tracking-[0.2em] mb-3 pb-2 border-b border-[#262d35] uppercase flex items-center justify-between">
            <span>━━ INFERENCE ━━</span>
            <Activity className="w-3.5 h-3.5 text-[#4fa3ff]" />
          </div>

          <div className="space-y-1.5 text-xs font-mono">
            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">BACKEND</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-white font-bold">{inference.backend}</span>
            </div>

            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">MODEL</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-[#ff334b] font-bold truncate max-w-[130px]">{inference.model}</span>
            </div>

            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">VRAM USAGE</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-white font-bold">{inference.vramUsedMB} MB / 8GB</span>
            </div>

            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">RAM USAGE</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-white font-bold">{inference.ramUsedMB} MB / 32GB</span>
            </div>

            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">TPS</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-[#37d67a] font-bold text-sm">{inference.tps.toFixed(2)}</span>
            </div>
          </div>

          {/* PHX-NEW (destravar Ollama como 2ª opção, a pedido explícito):
              única linha real deste card - o resto acima (BACKEND/MODEL/
              VRAM/RAM/TPS) é estado estático da UI, ainda não ligado a
              telemetria ao vivo (fora do escopo desta rodada). Esta troca
              É real: chama POST /api/engine/text-runtime de verdade, que
              o Phoenix Engine persiste e passa a usar em `infer`,
              `resident research` e no Aviary Architect do Swarm. */}
          <div className="mt-3 pt-3 border-t border-[#262d35]">
            <div className="flex items-center justify-between text-[10px] font-mono text-[#8d98a5] uppercase mb-1.5">
              <span>Text Engine (real)</span>
              {textEngineBusy && <RefreshCw className="w-3 h-3 animate-spin text-[#4fa3ff]" />}
            </div>
            <div className="flex gap-1.5">
              {textEngineOptions.map(opt => (
                <button
                  key={opt}
                  onClick={() => handleSetTextEngine(opt)}
                  disabled={textEngineBusy || textEngine === null}
                  title={opt === 'ollama' ? 'Segunda opção - roda via Docker/Ollama (porta 11434), mais lenta que o llama.cpp nativo' : 'Motor nativo Vulkan/CPU - default da Phoenix'}
                  className={`flex-1 px-2 py-1 rounded text-[10px] font-mono font-bold uppercase tracking-wide transition-all disabled:opacity-50 ${
                    textEngine === opt
                      ? 'bg-[#ff334b] text-white'
                      : 'bg-[#14181d] text-[#8d98a5] border border-[#262d35] hover:text-white hover:border-[#3a4450]'
                  }`}
                >
                  {opt}
                </button>
              ))}
            </div>
            {textEngineError && (
              <p className="text-[10px] text-[#ff334b] font-mono mt-1.5">{textEngineError}</p>
            )}
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-[#262d35]">
          <div className="flex items-center justify-between text-[11px] font-mono mb-1">
            <span className="text-[#8d98a5] uppercase">RAM SCORE</span>
            <span className="text-[#37d67a] font-bold">QUAD CHANNEL</span>
          </div>
          {renderBar(hardware.ramScore, 'text-[#37d67a]')}
        </div>
      </div>

      {/* CARD 4: PHOENIX STATUS */}
      <div className="bg-[#0b0d10] p-4 sm:p-5 flex flex-col justify-between group hover:bg-[#0e1115] transition-colors relative">
        <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <button 
            onClick={onOpenSwarm}
            className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-white text-black font-bold hover:bg-[#ff334b] hover:text-white transition-all"
          >
            Swarm
          </button>
        </div>

        <div>
          <div className="text-white text-xs font-bold tracking-[0.2em] mb-3 pb-2 border-b border-[#262d35] uppercase flex items-center justify-between">
            <span>━━ PHOENIX STATUS ━━</span>
            <Shield className="w-3.5 h-3.5 text-[#ff334b]" />
          </div>

          <div className="space-y-1.5 text-xs font-mono">
            <div 
              onClick={onOpenRag}
              className="flex items-center cursor-pointer hover:text-[#37d67a] transition-colors"
              title="Click to view RAG knowledge documents"
            >
              <span className="text-[#8d98a5] uppercase">RAG DOCS</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-white font-bold">{ragCount} [OPEN]</span>
            </div>

            <div 
              onClick={onOpenSwarm}
              className="flex items-center cursor-pointer hover:text-[#4fa3ff] transition-colors"
              title="Click to view Aviary Agent Swarm on Port 3000"
            >
              <span className="text-[#8d98a5] uppercase">SWARM AGENTS</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              <span className="text-[#ff334b] font-bold">{agentCount} ACTIVE</span>
            </div>

            <div className="flex items-center">
              <span className="text-[#8d98a5] uppercase">MISSIONS</span>
              <span className="flex-grow border-b border-dotted border-[#8d98a5]/30 mx-2 h-3.5"></span>
              {missionsStatus === 'loading' && <span className="text-[#8d98a5] font-bold">...</span>}
              {missionsStatus === 'ready' && <span className="text-[#37d67a] font-bold">{missionsCount} [READY]</span>}
              {missionsStatus === 'empty' && <span className="text-[#f7b731] font-bold">[!] CATALOG EMPTY</span>}
              {missionsStatus === 'error' && <span className="text-[#ff334b] font-bold">[X] LOAD FAILED</span>}
            </div>
          </div>
        </div>

        {/* PHX-FIX (varredura 2026-08-21, achado 1.1): este bloco mostrava
            "OLLAMA [✓] INSTALLED", "WEBUI [✓] INSTALLED", "LOCALAI [○]
            STANDBY" fixos, sem verificação nenhuma - duplicando (e
            contradizendo, quando o Ollama real está fora do ar) a linha
            "OLLAMA API" do card ENVIRONMENT ao lado, que já reflete o
            status real (ServicesEngine.get_environment_status() ->
            environment.ollama, sincronizado de verdade em
            EngineMissionControl). WEBUI e LOCALAI não têm NENHUMA
            checagem real no backend hoje - não existe rota, campo ou
            processo que verifique se um WebUI ou um servidor LocalAI
            estão rodando. Bloco removido em vez de inventar uma
            capacidade que não existe; o status real do Ollama já está
            visível no card ao lado. */}
      </div>

    </div>
  );
};
