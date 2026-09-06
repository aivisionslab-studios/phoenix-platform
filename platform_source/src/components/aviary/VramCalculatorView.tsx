import { useState } from 'react';
import { 
  Cpu, 
  Zap, 
  CheckCircle2, 
  AlertTriangle, 
  Sliders, 
  Database,
  Sparkles
} from 'lucide-react';

export const VramCalculatorView = () => {
  const [gpuName, setGpuName] = useState<string>('rx580');
  const [paramSizeNum, setParamSizeNum] = useState<number>(8);
  const [quantType, setQuantType] = useState<string>('Q4_K_M');
  const [contextTokens, setContextTokens] = useState<number>(32768);

  const gpuProfiles: Record<string, { name: string; vramGb: number; bandwidthGbs: number }> = {
    rx580: { name: 'AMD Radeon RX 580 2048SP (8 GB)', vramGb: 8, bandwidthGbs: 224 },
    rtx3060: { name: 'NVIDIA RTX 3060 (12 GB)', vramGb: 12, bandwidthGbs: 360 },
    rtx4070: { name: 'NVIDIA RTX 4070 (12 GB)', vramGb: 12, bandwidthGbs: 504 },
    rtx4090: { name: 'NVIDIA RTX 4090 (24 GB)', vramGb: 24, bandwidthGbs: 1008 },
    m3max36: { name: 'Apple M3/M4 Max (36 GB)', vramGb: 36, bandwidthGbs: 300 },
  };

  const currentGpu = gpuProfiles[gpuName] || gpuProfiles.rx580;

  const quantBits: Record<string, number> = {
    Q2_K: 2.5,
    Q3_K_M: 3.4,
    Q4_K_M: 4.5,
    Q5_K_M: 5.5,
    Q8_0: 8.5,
    FP16: 16.0,
  };

  const bitsPerWeight = quantBits[quantType] || 4.5;
  const modelWeightsGb = (paramSizeNum * 1e9 * bitsPerWeight) / (8 * 1024 * 1024 * 1024);
  const kvCacheGb = ((paramSizeNum * contextTokens * 500000) / (1024 * 1024 * 1024));
  const overheadGb = 1.2;

  const totalVramNeeded = parseFloat((modelWeightsGb + kvCacheGb + overheadGb).toFixed(2));
  const availableVram = currentGpu.vramGb;

  const totalLayers = paramSizeNum <= 8 ? 32 : paramSizeNum <= 14 ? 48 : 64;
  const offloadedLayers = Math.min(totalLayers, Math.floor((availableVram / totalVramNeeded) * totalLayers));
  const theoreticalTokSec = Math.round(currentGpu.bandwidthGbs / Math.max(1, totalVramNeeded));

  return (
    <div id="vram-calculator-view" className="flex-1 overflow-y-auto bg-[#0b0d10] text-[#e7e7e7] p-4 sm:p-6 lg:p-8 font-sans">
      <div className="max-w-5xl mx-auto space-y-6">
        
        {/* Banner */}
        <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-6 shadow-xl flex items-start space-x-4">
          <div className="p-3 bg-[#ff334b]/10 border border-[#ff334b]/20 rounded-2xl shrink-0">
            <Cpu className="w-8 h-8 text-[#ff334b]" />
          </div>
          <div>
            <h1 className="text-xl sm:text-2xl font-bold text-white mb-1">
              Calculadora de VRAM & Hardware
            </h1>
            <p className="text-xs sm:text-sm text-slate-400 leading-relaxed font-sans">
              Estime com precisão a memória VRAM necessária para rodar modelos GGUF locais no Ollama, llama-server ou LM Studio.
            </p>
          </div>
        </div>

        {/* Inputs & Outputs Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-5 space-y-5 shadow-xl">
            <h2 className="text-sm font-bold text-white flex items-center space-x-2 border-b border-[#262d35] pb-3">
              <Sliders className="w-4 h-4 text-[#ff334b]" />
              <span>Configuração de Hardware</span>
            </h2>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5 font-mono">
                Placa de Vídeo / Hardware
              </label>
              <select
                value={gpuName}
                onChange={(e) => setGpuName(e.target.value)}
                className="w-full bg-[#0b0d10] border border-[#262d35] rounded-xl p-2.5 text-xs text-white focus:ring-1 focus:ring-[#ff334b] font-mono"
              >
                {Object.entries(gpuProfiles).map(([key, gpu]) => (
                  <option key={key} value={key}>
                    {gpu.name} ({gpu.vramGb} GB VRAM)
                  </option>
                ))}
              </select>
            </div>

            <div>
              <div className="flex justify-between items-center mb-1.5 font-mono text-xs">
                <label className="text-slate-300">Tamanho dos Parâmetros</label>
                <span className="font-bold text-[#ff334b]">{paramSizeNum}B</span>
              </div>
              <div className="grid grid-cols-4 gap-2 font-mono">
                {[3, 8, 14, 32, 70].map((size) => (
                  <button
                    key={size}
                    onClick={() => setParamSizeNum(size)}
                    className={`py-1.5 px-2 rounded-lg text-xs font-bold transition-all ${
                      paramSizeNum === size
                        ? 'bg-[#ff334b] text-white shadow-md'
                        : 'bg-[#0b0d10] text-slate-400 border border-[#262d35] hover:bg-[#262d35]'
                    }`}
                  >
                    {size}B
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5 font-mono">
                Formato de Quantização GGUF
              </label>
              <div className="grid grid-cols-3 gap-2 font-mono">
                {Object.keys(quantBits).map((q) => (
                  <button
                    key={q}
                    onClick={() => setQuantType(q)}
                    className={`py-1.5 px-2 rounded-lg text-xs font-medium transition-all ${
                      quantType === q
                        ? 'bg-[#ff334b] text-white shadow-md'
                        : 'bg-[#0b0d10] text-slate-400 border border-[#262d35] hover:bg-[#262d35]'
                    }`}
                  >
                    {q} ({quantBits[q]}b)
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="flex justify-between items-center mb-1.5 font-mono text-xs">
                <label className="text-slate-300">Tamanho do Contexto</label>
                <span className="font-bold text-[#ff334b]">{(contextTokens / 1024).toFixed(0)}K Tokens</span>
              </div>
              <input
                type="range"
                min="2048"
                max="131072"
                step="2048"
                value={contextTokens}
                onChange={(e) => setContextTokens(Number(e.target.value))}
                className="w-full accent-[#ff334b] cursor-pointer"
              />
            </div>
          </div>

          {/* Right Column: Output & Breakdown */}
          <div className="bg-[#14181d] border border-[#262d35] rounded-2xl p-5 space-y-5 shadow-xl flex flex-col justify-between">
            <div>
              <h2 className="text-sm font-bold text-white flex items-center space-x-2 border-b border-[#262d35] pb-3 font-mono">
                <Database className="w-4 h-4 text-[#ff334b]" />
                <span>Estimativa de Memória VRAM</span>
              </h2>

              <div className="my-4">
                {totalVramNeeded <= availableVram ? (
                  <div className="p-3 bg-emerald-950/40 border border-emerald-800/50 rounded-xl flex items-center space-x-3 text-emerald-300">
                    <CheckCircle2 className="w-5 h-5 text-[#37d67a] shrink-0" />
                    <div>
                      <span className="font-bold text-xs block">Offload 100% na GPU Suportado</span>
                      <span className="text-[11px] text-[#37d67a]/80">O modelo cabe totalmente na VRAM para velocidade máxima.</span>
                    </div>
                  </div>
                ) : (
                  <div className="p-3 bg-amber-950/40 border border-amber-800/50 rounded-xl flex items-center space-x-3 text-amber-300">
                    <AlertTriangle className="w-5 h-5 text-amber-400 shrink-0" />
                    <div>
                      <span className="font-bold text-xs block">Offload Parcial (Spillover na RAM)</span>
                      <span className="text-[11px] text-amber-400/80">
                        {offloadedLayers} de {totalLayers} camadas rodarão na VRAM. O restante na RAM do Xeon.
                      </span>
                    </div>
                  </div>
                )}
              </div>

              <div className="space-y-3 font-mono text-xs">
                <div>
                  <div className="flex justify-between text-slate-300 mb-1">
                    <span>Pesos do Modelo ({quantType}):</span>
                    <span className="text-[#ff334b] font-bold">{modelWeightsGb.toFixed(2)} GB</span>
                  </div>
                  <div className="w-full bg-[#0b0d10] h-2 rounded-full overflow-hidden">
                    <div
                      className="bg-[#ff334b] h-full rounded-full"
                      style={{ width: `${Math.min(100, (modelWeightsGb / availableVram) * 100)}%` }}
                    />
                  </div>
                </div>

                <div>
                  <div className="flex justify-between text-slate-300 mb-1">
                    <span>KV Cache (Contexto {(contextTokens / 1024).toFixed(0)}K):</span>
                    <span className="text-[#37d67a] font-bold">{kvCacheGb.toFixed(2)} GB</span>
                  </div>
                  <div className="w-full bg-[#0b0d10] h-2 rounded-full overflow-hidden">
                    <div
                      className="bg-[#37d67a] h-full rounded-full"
                      style={{ width: `${Math.min(100, (kvCacheGb / availableVram) * 100)}%` }}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div className="p-4 bg-[#0b0d10] border border-[#262d35] rounded-xl space-y-3 font-mono">
              <div className="flex justify-between items-center text-sm font-bold text-white border-b border-[#262d35] pb-2">
                <span>VRAM Total Necessária:</span>
                <span className="text-[#ff334b] text-base">{totalVramNeeded} GB</span>
              </div>

              <div className="flex justify-between items-center text-xs text-slate-300">
                <span className="flex items-center space-x-1">
                  <Zap className="w-3.5 h-3.5 text-[#37d67a]" />
                  <span>Velocidade Teórica:</span>
                </span>
                <span className="font-bold text-[#37d67a]">~{theoreticalTokSec} tok/s</span>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
};
