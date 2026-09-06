import { useState, useEffect, useRef } from 'react';
import {
  Download,
  Search,
  Copy,
  Check,
  ExternalLink,
  Terminal,
  BrainCircuit,
  HardDriveDownload,
  Loader2,
  CheckCircle2,
  AlertTriangle,
} from 'lucide-react';
import { OPEN_SOURCE_MODELS } from '../../data/modelsData';

// PHX-NEW (2026-08-22, pedido do usuário: "api ou common baixar alguns
// modelos pra pasta padrão dos modelos compatíveis com llama e ollama" -
// feito logo depois de descobrir, nesta mesma sessão, que baixar um .gguf
// na mão via PowerShell/huggingface_hub CLI era a única forma de conseguir
// um modelo novo até agora): tipo do item devolvido por
// GET /api/models/recommended-downloads (novo endpoint, api_server.py) -
// os 2 presets curados (repo_id/filename REAIS, conferidos no Hugging
// Face) pensados pro hardware relatado pelo usuário nesta sessão (RX 580
// 8GB, ~5.5GB de VRAM útil).
interface RecommendedModel {
  key: string;
  label: string;
  note: string;
  repo_id: string;
  filename: string;
  already_downloaded: boolean;
}

type DownloadState =
  | { status: 'idle' }
  | { status: 'starting' }
  | { status: 'downloading'; jobId: string; elapsedSeconds: number }
  | { status: 'done' }
  | { status: 'error'; message: string };

interface ModelHubViewProps {
  onSelectModelForChat: (modelName: string) => void;
  // PHX-NEW: depois de um download terminar, chamar isso reaproveita o
  // MESMO mecanismo que já corrige o achado "baixei um .gguf mas ele não
  // aparece na Phoenix" (handleScanAllProviders, AviaryApp.tsx) - o modelo
  // recém-baixado aparece no Chat/Arena sem precisar recarregar a página.
  onScanProviders?: () => Promise<void>;
}

export const ModelHubView = ({ onSelectModelForChat, onScanProviders }: ModelHubViewProps) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedTag, setSelectedTag] = useState<string>('All');
  const [copiedCommand, setCopiedCommand] = useState<string | null>(null);

  const [recommendedModels, setRecommendedModels] = useState<RecommendedModel[]>([]);
  const [recommendedError, setRecommendedError] = useState<string | null>(null);
  const [downloadStates, setDownloadStates] = useState<Record<string, DownloadState>>({});
  const pollTimersRef = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  const fetchRecommendedModels = async () => {
    try {
      const res = await fetch('/api/models/recommended-downloads');
      const data = await res.json().catch(() => null);
      if (!res.ok || !data) {
        setRecommendedError((data && data.error) || 'Não foi possível consultar os modelos recomendados.');
        return;
      }
      setRecommendedError(null);
      setRecommendedModels(data.models || []);
    } catch (err) {
      setRecommendedError('Phoenix Engine offline ou inacessível - não deu pra consultar os modelos recomendados.');
    }
  };

  useEffect(() => {
    fetchRecommendedModels();
    // Limpa qualquer polling pendente se o componente desmontar no meio de um download.
    return () => {
      for (const timer of Object.values(pollTimersRef.current)) {
        clearInterval(timer);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pollDownloadStatus = (key: string, jobId: string) => {
    const timer = setInterval(async () => {
      try {
        const res = await fetch(`/api/models/download/status?job_id=${encodeURIComponent(jobId)}`);
        const data = await res.json().catch(() => null);
        if (!res.ok || !data) {
          clearInterval(timer);
          delete pollTimersRef.current[key];
          setDownloadStates((prev) => ({ ...prev, [key]: { status: 'error', message: (data && data.error) || 'Falha ao consultar o progresso do download.' } }));
          return;
        }
        if (data.status === 'done') {
          clearInterval(timer);
          delete pollTimersRef.current[key];
          setDownloadStates((prev) => ({ ...prev, [key]: { status: 'done' } }));
          await fetchRecommendedModels();
          if (onScanProviders) await onScanProviders();
        } else if (data.status === 'error') {
          clearInterval(timer);
          delete pollTimersRef.current[key];
          setDownloadStates((prev) => ({ ...prev, [key]: { status: 'error', message: data.error || 'O download falhou (motivo desconhecido).' } }));
        } else {
          setDownloadStates((prev) => ({ ...prev, [key]: { status: 'downloading', jobId, elapsedSeconds: data.elapsed_seconds || 0 } }));
        }
      } catch (err) {
        clearInterval(timer);
        delete pollTimersRef.current[key];
        setDownloadStates((prev) => ({ ...prev, [key]: { status: 'error', message: 'Conexão perdida com a Phoenix durante o download.' } }));
      }
    }, 2000);
    pollTimersRef.current[key] = timer;
  };

  const handleDownloadRecommended = async (model: RecommendedModel) => {
    setDownloadStates((prev) => ({ ...prev, [model.key]: { status: 'starting' } }));
    try {
      const res = await fetch('/api/models/download', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: model.key }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data || !data.ok) {
        setDownloadStates((prev) => ({ ...prev, [model.key]: { status: 'error', message: (data && data.error) || 'Não foi possível iniciar o download.' } }));
        return;
      }
      if (data.already_downloaded) {
        setDownloadStates((prev) => ({ ...prev, [model.key]: { status: 'done' } }));
        await fetchRecommendedModels();
        return;
      }
      setDownloadStates((prev) => ({ ...prev, [model.key]: { status: 'downloading', jobId: data.job_id, elapsedSeconds: 0 } }));
      pollDownloadStatus(model.key, data.job_id);
    } catch (err) {
      setDownloadStates((prev) => ({ ...prev, [model.key]: { status: 'error', message: 'Phoenix Engine offline ou inacessível.' } }));
    }
  };

  const tags = ['All', 'Reasoning', 'Coding', 'General', 'Vision', 'Compact'];

  const filteredModels = OPEN_SOURCE_MODELS.filter((model) => {
    const matchesSearch = 
      model.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      model.org.toLowerCase().includes(searchTerm.toLowerCase()) ||
      model.description.toLowerCase().includes(searchTerm.toLowerCase());

    const matchesTag = selectedTag === 'All' || model.tags.includes(selectedTag);

    return matchesSearch && matchesTag;
  });

  const copyCommand = (cmd: string) => {
    navigator.clipboard.writeText(cmd);
    setCopiedCommand(cmd);
    setTimeout(() => setCopiedCommand(null), 2000);
  };

  return (
    <div id="model-hub-view" className="flex-1 overflow-y-auto bg-[#0b0d10] text-[#e7e7e7] p-4 sm:p-6 lg:p-8 font-sans">
      <div className="max-w-6xl mx-auto space-y-6">
        
        {/* Banner */}
        <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-6 shadow-xl relative overflow-hidden">
          <div className="relative z-10 max-w-2xl">
            <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-[#ff334b]/10 border border-[#ff334b]/20 text-[#ff334b] text-xs font-semibold mb-3">
              <Download className="w-3.5 h-3.5" />
              <span>GGUF & Open Weights Explorer</span>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight mb-2">
              Hub de Modelos Open-Source
            </h1>
            <p className="text-slate-300 text-xs sm:text-sm leading-relaxed">
              Descubra e copie comandos de carregamento para Ollama, llama-server e LM Studio.
            </p>
          </div>
        </div>

        {/* PHX-NEW: Download direto pra pasta do Phoenix, sem PowerShell -
            presets curados pro hardware relatado pelo usuário (RX 580 8GB,
            ~5.5GB de VRAM útil). */}
        <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-5 shadow-xl">
          <div className="flex items-center space-x-2 mb-1">
            <HardDriveDownload className="w-4 h-4 text-[#37d67a]" />
            <h2 className="text-sm font-bold text-white">Baixar direto pro Phoenix</h2>
          </div>
          <p className="text-xs text-slate-400 mb-4">
            Sem precisar de PowerShell ou linha de comando - baixa o .gguf direto pra pasta certa
            (Models/Chat/GGUF), pronto pro llama-server usar no Chat e no Arena.
          </p>

          {recommendedError && (
            <div className="p-3 bg-rose-950/40 border border-rose-800/50 rounded-xl text-rose-300 text-xs mb-3">
              ⚠️ {recommendedError}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {recommendedModels.map((model) => {
              const state = downloadStates[model.key] || { status: 'idle' as const };
              return (
                <div key={model.key} className="bg-[#0b0d10] border border-[#262d35] rounded-xl p-4 flex flex-col justify-between">
                  <div>
                    <h3 className="text-sm font-bold text-white">{model.label}</h3>
                    <p className="text-[11px] text-slate-400 mt-1 leading-relaxed">{model.note}</p>
                    <p className="text-[10px] font-mono text-slate-500 mt-2">{model.repo_id}</p>
                  </div>
                  <div className="mt-3">
                    {model.already_downloaded && state.status !== 'downloading' && state.status !== 'starting' ? (
                      <div className="flex items-center space-x-1.5 text-emerald-400 text-xs font-semibold">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Já está na sua pasta de modelos</span>
                      </div>
                    ) : state.status === 'starting' ? (
                      <div className="flex items-center space-x-1.5 text-slate-400 text-xs font-mono">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        <span>Iniciando...</span>
                      </div>
                    ) : state.status === 'downloading' ? (
                      <div className="flex items-center space-x-1.5 text-[#ff334b] text-xs font-mono">
                        <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        <span>Baixando... {Math.round(state.elapsedSeconds)}s decorridos</span>
                      </div>
                    ) : state.status === 'done' ? (
                      <div className="flex items-center space-x-1.5 text-emerald-400 text-xs font-semibold">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        <span>Baixado com sucesso</span>
                      </div>
                    ) : state.status === 'error' ? (
                      <div className="space-y-2">
                        <div className="flex items-start space-x-1.5 text-rose-400 text-[11px]">
                          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                          <span>{state.message}</span>
                        </div>
                        <button
                          onClick={() => handleDownloadRecommended(model)}
                          className="w-full flex items-center justify-center space-x-1.5 bg-[#0b0d10] hover:bg-[#262d35] text-slate-200 text-xs font-semibold py-1.5 px-3 rounded-lg border border-[#262d35] transition-colors"
                        >
                          <span>Tentar de novo</span>
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => handleDownloadRecommended(model)}
                        className="w-full flex items-center justify-center space-x-1.5 bg-[#ff334b] hover:bg-[#e02d43] text-white text-xs font-semibold py-1.5 px-3 rounded-lg transition-colors"
                      >
                        <Download className="w-3.5 h-3.5" />
                        <span>Baixar agora</span>
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Filters & Search */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="relative w-full sm:w-80">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-3 pointer-events-none" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Buscar modelos..."
              className="w-full bg-[#14181d] border border-[#262d35] rounded-xl pl-9 pr-4 py-2 text-xs text-white placeholder-slate-500 focus:ring-1 focus:ring-[#ff334b]"
            />
          </div>

          <div className="flex flex-wrap items-center gap-1.5 w-full sm:w-auto">
            {tags.map((tag) => (
              <button
                key={tag}
                onClick={() => setSelectedTag(tag)}
                className={`px-3 py-1 rounded-lg text-xs font-medium transition-all ${
                  selectedTag === tag
                    ? 'bg-[#ff334b] text-white shadow-md'
                    : 'bg-[#14181d] text-slate-400 hover:text-white border border-[#262d35]'
                }`}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>

        {/* Models List Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {filteredModels.map((model) => (
            <div
              key={model.id}
              className="bg-[#14181d] border border-[#262d35] hover:border-[#ff334b]/40 rounded-2xl p-5 shadow-xl transition-all flex flex-col justify-between"
            >
              <div>
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <div className="flex items-center space-x-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-[#ff334b] bg-[#ff334b]/10 px-2 py-0.5 rounded border border-[#ff334b]/20">
                        {model.org}
                      </span>
                      <span className="text-[10px] font-mono text-slate-400">
                        {model.params} • Contexto: {model.context}
                      </span>
                    </div>
                    <h3 className="text-base font-bold text-white mt-1">{model.name}</h3>
                  </div>

                  {model.supportsReasoning && (
                    <span className="p-1.5 bg-purple-500/10 border border-purple-500/20 text-purple-300 rounded-lg text-[10px] font-mono flex items-center space-x-1 shrink-0">
                      <BrainCircuit className="w-3.5 h-3.5" />
                      <span>Raciocínio</span>
                    </span>
                  )}
                </div>

                <p className="text-xs text-slate-300 leading-relaxed mb-4 font-sans">
                  {model.description}
                </p>

                {/* GGUF Sizes Table */}
                <div className="bg-[#0b0d10] border border-[#262d35] rounded-xl p-3 mb-4 space-y-2">
                  <span className="text-[11px] font-bold text-slate-300 block font-mono">
                    Formatos GGUF & VRAM Requerida:
                  </span>
                  <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
                    {model.ggufSizes.map((g, idx) => (
                      <div key={idx} className="bg-[#14181d] p-1.5 rounded border border-[#262d35] flex items-center justify-between">
                        <span className="text-[#ff334b] font-semibold">{g.quant}</span>
                        <span className="text-slate-400">{g.sizeGb}GB (~{g.ramRecommendedGb}GB RAM)</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="pt-3 border-t border-[#262d35] flex items-center justify-between gap-2">
                <button
                  onClick={() => copyCommand(model.ollamaCommand)}
                  className="flex-1 flex items-center justify-center space-x-2 bg-[#0b0d10] hover:bg-[#262d35] text-slate-200 text-xs font-mono py-2 px-3 rounded-xl border border-[#262d35] transition-colors"
                  title="Copiar comando de carregamento"
                >
                  <Terminal className="w-3.5 h-3.5 text-[#37d67a]" />
                  <span className="truncate">{model.ollamaCommand}</span>
                  {copiedCommand === model.ollamaCommand ? (
                    <Check className="w-3.5 h-3.5 text-[#37d67a] shrink-0" />
                  ) : (
                    <Copy className="w-3.5 h-3.5 text-slate-500 shrink-0" />
                  )}
                </button>

                <a
                  href={model.huggingFaceUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="p-2 bg-[#0b0d10] hover:bg-[#262d35] text-slate-400 hover:text-white border border-[#262d35] rounded-xl transition-colors"
                  title="Ver no HuggingFace"
                >
                  <ExternalLink className="w-4 h-4" />
                </a>
              </div>

            </div>
          ))}
        </div>

      </div>
    </div>
  );
};
