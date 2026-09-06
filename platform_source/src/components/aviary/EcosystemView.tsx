import React, { useState } from 'react';
import { 
  Cpu, 
  Server, 
  Globe, 
  Monitor, 
  Terminal, 
  ExternalLink, 
  CheckCircle2, 
  Sparkles, 
  Search, 
  Layers,
  ArrowUpRight,
  Workflow,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Check
} from 'lucide-react';
import { ProviderConfig } from '../../types';
// PHX-FIX (varredura 2026-08-21 rodada 2, achado cosmético): Volume2,
// AudioWaveform, synthesizeAndPlayPiper e DEFAULT_PIPER_VOICES eram
// importados mas nunca usados neste arquivo (os controles de TTS vivem em
// ChatView.tsx/ProcessLauncherBar.tsx) - código morto, removido.
import { BenchmarkSection } from './BenchmarkSection';

interface EcosystemViewProps {
  providers: ProviderConfig[];
  onOpenSettings: () => void;
  onUpdateProvider?: (updated: ProviderConfig) => void;
  onTestProvider?: (providerId: string) => Promise<void>;
  hasGeminiKey?: boolean;
}

export const EcosystemView: React.FC<EcosystemViewProps> = ({ 
  providers, 
  onOpenSettings,
  onUpdateProvider,
  onTestProvider,
  hasGeminiKey = true
}) => {
  const [selectedCategory, setSelectedCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [showEndpointsPanel, setShowEndpointsPanel] = useState<boolean>(true);
  const [testingId, setTestingId] = useState<string | null>(null);

  const handleTest = async (providerId: string) => {
    if (!onTestProvider) return;
    setTestingId(providerId);
    await onTestProvider(providerId);
    setTestingId(null);
  };

  return (
    <div id="ecosystem-view-container" className="flex-1 bg-[#0b0d10] text-[#e7e7e7] overflow-y-auto p-4 sm:p-6 lg:p-8 space-y-8 font-sans">
      <div className="max-w-7xl mx-auto space-y-8">
        
        {/* Banner */}
        <div className="bg-[#14181d] border border-[#262d35] rounded-3xl p-6 sm:p-8 shadow-2xl relative overflow-hidden">
          <div className="relative z-10 space-y-4 max-w-4xl">
            <div className="flex flex-wrap items-center gap-2">
              <span className="px-3 py-1 rounded-full text-xs font-semibold bg-[#ff334b]/20 text-[#ff334b] border border-[#ff334b]/30 flex items-center space-x-1.5 font-mono">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Centro de Comando & Ecossistema de IA</span>
              </span>
              <span className="px-3 py-1 rounded-full text-xs font-mono bg-[#37d67a]/10 text-[#37d67a] border border-[#37d67a]/20">
                {providers.length} Provedores Configurados
              </span>
            </div>

            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-white">
              Arquitetura da Stack & Gestão de Endpoints
            </h1>

            <p className="text-sm text-slate-300 leading-relaxed font-sans">
              Gerencie conexões com Ollama, llama-server, LM Studio, vLLM e APIs em nuvem com teste de latência em tempo real.
            </p>
          </div>
        </div>

        {/* Benchmark Section */}
        <BenchmarkSection />

        {/* Unified Endpoints Panel */}
        <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-6 shadow-xl space-y-5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-[#262d35] pb-4">
            <div className="flex items-center space-x-3">
              <div className="p-2.5 bg-[#ff334b]/10 border border-[#ff334b]/20 rounded-xl text-[#ff334b]">
                <Server className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-lg font-bold text-white flex items-center space-x-2 font-sans">
                  <span>Provedores & Endpoints Ativos</span>
                  <span className="text-xs font-mono font-normal px-2 py-0.5 rounded-full bg-[#ff334b]/20 text-[#ff334b] border border-[#ff334b]/30">
                    {providers.filter(p => p.enabled).length}/{providers.length} Ativos
                  </span>
                </h2>
                <p className="text-xs text-slate-400 font-sans">
                  Portas locais (Ollama :11434, llama-server :8081, LM Studio :1234, Phoenix Engine :8000)
                </p>
              </div>
            </div>

            <button
              onClick={() => setShowEndpointsPanel(!showEndpointsPanel)}
              className="flex items-center space-x-1.5 px-3 py-1.5 bg-[#0b0d10] hover:bg-[#262d35] text-slate-200 text-xs font-mono rounded-xl border border-[#262d35] transition-colors"
            >
              {showEndpointsPanel ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              <span>{showEndpointsPanel ? 'Ocultar' : 'Expandir'}</span>
            </button>
          </div>

          {showEndpointsPanel && (
            <div className="space-y-4 pt-2">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 font-mono">
                {providers.map((p) => (
                  <div
                    key={p.id}
                    className={`border rounded-xl p-4 transition-all ${
                      p.enabled
                        ? 'bg-[#0b0d10] border-[#262d35] hover:border-[#ff334b]/40'
                        : 'bg-[#0b0d10]/40 border-[#262d35]/40 opacity-60'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center space-x-2.5">
                        <div className="p-2 rounded-lg bg-[#14181d] border border-[#262d35] text-[#ff334b]">
                          <Cpu className="w-4 h-4" />
                        </div>
                        <div>
                          <div className="flex items-center space-x-2">
                            <h3 className="font-semibold text-xs text-white">{p.name}</h3>
                            {p.status === 'connected' && (
                              <span className="flex items-center space-x-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#37d67a]/20 text-[#37d67a] border border-[#37d67a]/30">
                                <CheckCircle2 className="w-3 h-3" />
                                <span>{p.latencyMs || 0}ms</span>
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-slate-400 mt-0.5">
                            {p.models.length > 0 ? `${p.models.length} modelos` : 'Sem modelos'}
                          </p>
                        </div>
                      </div>

                      <div className="flex items-center space-x-2">
                        <label className="flex items-center space-x-1.5 text-xs text-slate-300 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={p.enabled}
                            onChange={(e) => onUpdateProvider && onUpdateProvider({ ...p, enabled: e.target.checked })}
                            className="rounded border-[#262d35] text-[#ff334b] focus:ring-[#ff334b] bg-[#14181d] w-3.5 h-3.5 cursor-pointer"
                          />
                          <span className="text-[11px]">Ativo</span>
                        </label>

                        {onTestProvider && (
                          <button
                            onClick={() => handleTest(p.id)}
                            disabled={!p.enabled || testingId === p.id}
                            className="flex items-center space-x-1 px-2.5 py-1 bg-[#14181d] hover:bg-[#262d35] text-slate-200 text-[11px] rounded-lg border border-[#262d35] transition-colors disabled:opacity-40 font-medium"
                          >
                            <RefreshCw className={`w-3 h-3 ${testingId === p.id ? 'animate-spin text-[#ff334b]' : ''}`} />
                            <span>{testingId === p.id ? 'Ping...' : 'Ping'}</span>
                          </button>
                        )}
                      </div>
                    </div>

                    {p.enabled && onUpdateProvider && (
                      <div className="mt-3 pt-3 border-t border-[#262d35] grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                        <div>
                          <label className="block text-[10px] text-slate-400 mb-1 font-mono">URL Endpoint</label>
                          <input
                            type="text"
                            value={p.baseUrl}
                            onChange={(e) => onUpdateProvider({ ...p, baseUrl: e.target.value })}
                            disabled={p.type === 'gemini'}
                            className="w-full bg-[#14181d] border border-[#262d35] rounded px-2.5 py-1 text-[11px] text-slate-200 focus:ring-1 focus:ring-[#ff334b] font-mono disabled:opacity-50"
                          />
                        </div>
                        <div>
                          <label className="block text-[10px] text-slate-400 mb-1 font-mono">Chave API / Token</label>
                          {p.type === 'gemini' ? (
                            <div className="bg-[#ff334b]/10 border border-[#ff334b]/30 rounded px-2.5 py-1 text-[11px] text-[#ff334b] font-mono flex items-center justify-between">
                              <span>{hasGeminiKey ? 'Injetada via Secrets' : 'Nenhuma chave'}</span>
                              <Check className="w-3 h-3 text-[#ff334b]" />
                            </div>
                          ) : (
                            <input
                              type="password"
                              value={p.apiKey || ''}
                              onChange={(e) => onUpdateProvider({ ...p, apiKey: e.target.value })}
                              placeholder="sk-..."
                              className="w-full bg-[#14181d] border border-[#262d35] rounded px-2.5 py-1 text-[11px] text-slate-200 focus:ring-1 focus:ring-[#ff334b] font-mono"
                            />
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
};
