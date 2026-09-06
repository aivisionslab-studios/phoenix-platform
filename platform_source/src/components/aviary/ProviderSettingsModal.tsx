import { useState } from 'react';
import { 
  X, 
  Check, 
  RefreshCw, 
  Server, 
  Terminal, 
  Cpu, 
  Sparkles, 
  AlertCircle,
  CheckCircle2, 
  XCircle,
  Zap,
  AudioWaveform
} from 'lucide-react';
import { ProviderConfig, ProviderType } from '../../types';

interface ProviderSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  providers: ProviderConfig[];
  onUpdateProvider: (updated: ProviderConfig) => void;
  onTestProvider: (providerId: string) => Promise<void>;
  hasGeminiKey: boolean;
}

export const ProviderSettingsModal = ({
  isOpen,
  onClose,
  providers,
  onUpdateProvider,
  onTestProvider,
  hasGeminiKey,
}: ProviderSettingsModalProps) => {
  const [testingId, setTestingId] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleTest = async (providerId: string) => {
    setTestingId(providerId);
    await onTestProvider(providerId);
    setTestingId(null);
  };

  return (
    <div id="provider-settings-modal" className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 overflow-y-auto font-sans">
      <div className="bg-[#14181d] border border-[#262d35] rounded-2xl max-w-3xl w-full shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#262d35] bg-[#0b0d10]">
          <div className="flex items-center space-x-3">
            <div className="p-2 bg-[#ff334b]/10 border border-[#ff334b]/20 rounded-xl">
              <Server className="w-5 h-5 text-[#ff334b]" />
            </div>
            <div>
              <h2 className="text-lg font-bold text-white">Provedores de LLM & Endpoints</h2>
              <p className="text-xs text-slate-400">
                Gerencie conexões locais (Ollama, LM Studio, llama-server) e nuvem (Gemini)
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-[#262d35] transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 overflow-y-auto space-y-4 flex-1">
          {providers.map((p) => (
            <div
              key={p.id}
              className={`border rounded-xl p-4 transition-all ${
                p.enabled
                  ? 'bg-[#0b0d10] border-[#262d35] hover:border-[#ff334b]/40'
                  : 'bg-[#0b0d10]/40 border-[#262d35]/50 opacity-60'
              }`}
            >
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="flex items-center space-x-3">
                  <div className="p-2 rounded-xl bg-[#14181d] border border-[#262d35]">
                    <Cpu className="w-4 h-4 text-[#ff334b]" />
                  </div>
                  <div>
                    <div className="flex items-center space-x-2">
                      <h3 className="font-semibold text-sm text-white">{p.name}</h3>
                      {p.status === 'connected' && (
                        <span className="flex items-center space-x-1 text-[10px] font-mono px-2 py-0.5 rounded-full bg-[#37d67a]/20 text-[#37d67a] border border-[#37d67a]/30">
                          <CheckCircle2 className="w-3 h-3" />
                          <span>Conectado ({p.latencyMs || 0}ms)</span>
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5 font-mono">
                      {p.models.length > 0 
                        ? `${p.models.length} modelos detectados`
                        : 'Nenhum modelo carregado'}
                    </p>
                  </div>
                </div>

                <div className="flex items-center space-x-3">
                  <label className="flex items-center space-x-2 text-xs text-slate-300 cursor-pointer font-mono">
                    <input
                      type="checkbox"
                      checked={p.enabled}
                      onChange={(e) => onUpdateProvider({ ...p, enabled: e.target.checked })}
                      className="rounded border-[#262d35] text-[#ff334b] focus:ring-[#ff334b] bg-[#14181d] w-4 h-4 cursor-pointer"
                    />
                    <span>Ativo</span>
                  </label>

                  <button
                    onClick={() => handleTest(p.id)}
                    disabled={!p.enabled || testingId === p.id}
                    className="flex items-center space-x-1.5 px-3 py-1.5 bg-[#14181d] hover:bg-[#262d35] text-slate-200 text-xs font-mono rounded-lg border border-[#262d35] transition-colors disabled:opacity-40"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${testingId === p.id ? 'animate-spin text-[#ff334b]' : ''}`} />
                    <span>{testingId === p.id ? 'Testando...' : 'Testar Ping'}</span>
                  </button>
                </div>
              </div>

              {p.enabled && (
                <div className="mt-4 pt-3 border-t border-[#262d35] grid grid-cols-1 md:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-medium text-slate-400 mb-1 font-mono">
                      URL Endpoint
                    </label>
                    <input
                      type="text"
                      value={p.baseUrl}
                      onChange={(e) => onUpdateProvider({ ...p, baseUrl: e.target.value })}
                      disabled={p.type === 'gemini'}
                      className="w-full bg-[#14181d] border border-[#262d35] rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:ring-1 focus:ring-[#ff334b] font-mono"
                    />
                  </div>

                  <div>
                    <label className="block text-[11px] font-medium text-slate-400 mb-1 font-mono">
                      {p.type === 'gemini' ? 'Chave Gemini (Injetada automaticamente)' : 'Chave API'}
                    </label>
                    {p.type === 'gemini' ? (
                      <div className="flex items-center justify-between bg-[#ff334b]/10 border border-[#ff334b]/30 rounded-lg px-3 py-1.5 text-xs text-[#ff334b] font-mono">
                        <span>{hasGeminiKey ? 'Injetada via Secrets' : 'Nenhuma chave'}</span>
                        <Check className="w-3 h-3 text-[#ff334b]" />
                      </div>
                    ) : (
                      <input
                        type="password"
                        value={p.apiKey || ''}
                        onChange={(e) => onUpdateProvider({ ...p, apiKey: e.target.value })}
                        className="w-full bg-[#14181d] border border-[#262d35] rounded-lg px-3 py-1.5 text-xs text-slate-200 focus:ring-1 focus:ring-[#ff334b] font-mono"
                        placeholder="sk-..."
                      />
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#262d35] bg-[#0b0d10] flex items-center justify-between">
          <p className="text-xs text-slate-400 font-mono">
            Porta local padrão: <code className="text-[#ff334b]">http://localhost:3000</code>
          </p>
          <button
            onClick={onClose}
            className="px-4 py-2 bg-[#ff334b] hover:bg-[#ff334b]/90 text-white text-xs font-semibold rounded-xl shadow-lg transition-all"
          >
            Concluído
          </button>
        </div>

      </div>
    </div>
  );
};
