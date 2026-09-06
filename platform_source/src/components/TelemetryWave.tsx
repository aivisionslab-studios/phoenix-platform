import React from 'react';
import { TelemetryPoint } from '../types';
import { Activity, Radio, Cpu, Zap } from 'lucide-react';

interface TelemetryWaveProps {
  telemetry: TelemetryPoint[];
  currentTps: number;
  stressActive: boolean;
}

export const TelemetryWave: React.FC<TelemetryWaveProps> = ({
  telemetry,
  currentTps,
  stressActive
}) => {
  // Generate SVG path from points
  const width = 600;
  const height = 70;
  const padding = 5;

  const points = telemetry.map((pt, idx) => {
    const x = padding + (idx / Math.max(telemetry.length - 1, 1)) * (width - 2 * padding);
    // Normalize TPS between 0 and 30
    const normalizedVal = Math.min(Math.max(pt.tps / 25, 0), 1);
    const y = height - padding - normalizedVal * (height - 2 * padding);
    return { x, y };
  });

  const pathD = points.length > 0
    ? points.reduce((acc, pt, idx) => `${acc} ${idx === 0 ? 'M' : 'L'} ${pt.x.toFixed(1)} ${pt.y.toFixed(1)}`, '')
    : `M 0 ${height / 2} L ${width} ${height / 2}`;

  return (
    <div className="bg-[#101317] border-b border-[#262d35] px-4 md:px-8 py-2.5 flex flex-col md:flex-row items-start md:items-center justify-between gap-4 flex-shrink-0">
      
      {/* Label and Current Metrics */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-[#ff334b] animate-pulse" />
          <span className="text-xs font-bold text-white uppercase tracking-wider font-mono">
            LIVE TELEMETRY WAVEFORM
          </span>
        </div>

        <div className="flex items-center gap-3 text-xs font-mono">
          <div className="flex items-center gap-1.5">
            <span className="text-[#8d98a5]">ENGINE [8000]:</span>
            <span className="text-[#ff334b] font-bold">{currentTps.toFixed(2)} TPS</span>
          </div>

          {/* PHX-FIX (auditoria completa — "tirar todos os fallbacks"):
              "AVIARY [3000]: 850 Kbps" era um número fixo, nunca mudava,
              apresentado ao lado de uma métrica real (ENGINE TPS, vindo de
              /api/state) dentro de um painel chamado "LIVE TELEMETRY
              WAVEFORM" - não existe nenhuma medição real de throughput da
              Aviary Platform em lugar nenhum do projeto pra alimentar isso.
              Removido em vez de continuar fabricando um número que nunca
              teve fonte real. */}

          <div className="flex items-center gap-1.5">
            <span className="text-[#8d98a5]">VULKAN QUEUE:</span>
            <span className="text-[#37d67a] font-bold">4 COMPUTE PIPES</span>
          </div>
        </div>
      </div>

      {/* Mini SVG Dynamic Waveform */}
      <div className="w-full md:w-80 h-10 bg-[#0b0d10] border border-[#262d35] rounded overflow-hidden relative">
        <svg viewBox={`0 0 ${width} ${height}`} className="w-full h-full preserve-3d">
          <defs>
            <linearGradient id="waveGradRed" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#ff334b" stopOpacity="0.4" />
              <stop offset="100%" stopColor="#ff334b" stopOpacity="0.0" />
            </linearGradient>
          </defs>
          <path
            d={`${pathD} L ${width} ${height} L 0 ${height} Z`}
            fill="url(#waveGradRed)"
          />
          <path
            d={pathD}
            fill="none"
            stroke="#ff334b"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
        
        {stressActive && (
          <div className="absolute inset-0 bg-[#ff334b]/10 animate-pulse pointer-events-none flex items-center justify-end px-2">
            <span className="text-[9px] font-mono text-[#ff334b] font-bold uppercase tracking-widest">
              STRESS PEAK
            </span>
          </div>
        )}
      </div>

    </div>
  );
};
