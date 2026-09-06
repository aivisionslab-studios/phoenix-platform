import React, { useState } from 'react';
import { AviaryAgent } from '../types';
import { Layers, Play, CheckCircle, Clock, Shield, Sparkles, MessageSquare, Cpu, Terminal } from 'lucide-react';

interface AviarySwarmProps {
  agents: AviaryAgent[];
  onDispatchTask: (agentId: string, task: string) => void | Promise<void>;
  onTriggerCommand: (cmd: string) => void;
}

export const AviarySwarmPanel: React.FC<AviarySwarmProps> = ({
  agents,
  onDispatchTask,
  onTriggerCommand
}) => {
  const [selectedAgent, setSelectedAgent] = useState<AviaryAgent>(agents[0]);
  const [customTask, setCustomTask] = useState('');
  const [isDispatching, setIsDispatching] = useState(false);

  const presetTasks = [
    { label: 'Vulkan Memory Garbage Collect', target: 'agent-sentinel', prompt: 'Trigger VRAM compaction and flush unallocated Vulkan memory buffers on Port 8000' },
    { label: 'Compile SIMD GCN Kernel', target: 'agent-synthesizer', prompt: 'Generate SPIR-V shader kernel for 4-queue FP16 matrix operations' },
    { label: 'Re-index Hardware RAG Manuals', target: 'agent-rag', prompt: 'Recalculate cosine similarity embeddings across 46 datacenter manuals' },
    { label: 'Balance Port 8000/3000 Token Bus', target: 'agent-architect', prompt: 'Synchronize WebSocket telemetry stream between Engine and Aviary Web Platform' }
  ];

  // PHX-FIX (varredura 2026-08-21, achado 3): o estado "ocupado" do botão
  // voltava ao normal num `setTimeout(1500)` fixo, independente de quando
  // a chamada real (onDispatchTask, que já é assíncrona e vai até o
  // Phoenix Engine) de fato terminava - o resultado real ainda aparecia
  // depois via latestThought/status do agente, mas o botão podia liberar
  // pra um novo comando antes (dispatch demorado) ou bem depois (dispatch
  // rápido) do que a operação real levava. Agora aguarda a promise real.
  const handleDispatch = async (agentId: string, taskText: string) => {
    if (!taskText) return;
    setIsDispatching(true);
    try {
      await onDispatchTask(agentId, taskText);
    } finally {
      setIsDispatching(false);
      setCustomTask('');
    }
  };

  return (
    <div className="bg-[#101317] border border-[#262d35] rounded-lg p-5 space-y-6">
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 pb-4 border-b border-[#262d35]">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full bg-[#4fa3ff] animate-ping" />
            <h2 className="text-base font-bold text-white tracking-widest uppercase font-display">
              PHOENIX AVIARY PLATFORM // MULTI-AGENT SWARM
            </h2>
          </div>
          <p className="text-xs text-[#8d98a5] mt-1 font-mono">
            Autonomous agent intelligence network executing concurrently on Port 3000 and orchestrating Port 8000 inference.
          </p>
        </div>

        <button
          onClick={() => onTriggerCommand('aviary')}
          className="px-3 py-1.5 rounded bg-[#1a1f26] border border-[#262d35] text-xs font-mono text-white hover:border-[#4fa3ff] transition-all flex items-center gap-1.5"
        >
          <Terminal className="w-3.5 h-3.5 text-[#4fa3ff]" />
          <span>Swarm Terminal Log</span>
        </button>
      </div>

      {/* Agents Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {agents.map((agent) => {
          const isSelected = selectedAgent?.id === agent.id;
          return (
            <div
              key={agent.id}
              onClick={() => setSelectedAgent(agent)}
              className={`p-4 rounded-lg border transition-all cursor-pointer relative ${
                isSelected
                  ? 'bg-[#14181d] border-[#ff334b] shadow-[0_0_15px_rgba(255,51,75,0.2)]'
                  : 'bg-[#0b0d10] border-[#262d35] hover:border-[#3a4450]'
              }`}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-2.5">
                  <div 
                    className="w-8 h-8 rounded-md flex items-center justify-center font-bold text-xs"
                    style={{ backgroundColor: `${agent.avatarColor}20`, color: agent.avatarColor, border: `1px solid ${agent.avatarColor}` }}
                  >
                    {agent.name.slice(0, 2).toUpperCase()}
                  </div>
                  <div>
                    <h3 className="text-xs font-bold text-white tracking-wider">{agent.name}</h3>
                    <p className="text-[10px] text-[#8d98a5] font-mono">{agent.model}</p>
                  </div>
                </div>

                <span className={`text-[10px] px-2 py-0.5 rounded font-mono font-bold ${
                  agent.status === 'ACTIVE' ? 'bg-[#37d67a]/20 text-[#37d67a] border border-[#37d67a]/40' :
                  agent.status === 'THINKING' ? 'bg-[#4fa3ff]/20 text-[#4fa3ff] border border-[#4fa3ff]/40 animate-pulse' :
                  'bg-[#ff334b]/20 text-[#ff334b] border border-[#ff334b]/40 animate-pulse'
                }`}>
                  {agent.status}
                </span>
              </div>

              <p className="text-[11px] text-[#8d98a5] font-mono line-clamp-2 mb-3">
                {agent.role}
              </p>

              <div className="pt-2 border-t border-[#262d35] flex items-center justify-between text-[10px] font-mono text-[#8d98a5]">
                <span>Tasks: <strong className="text-white">{agent.tasksCompleted}</strong></span>
                <span className="text-[#37d67a]">Port 3000 ↔ 8000</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected Agent Control & Dispatch Deck */}
      {selectedAgent && (
        <div className="bg-[#0b0d10] border border-[#262d35] rounded-lg p-4 space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-[#262d35]">
            <div className="flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-[#ff334b]" />
              <h3 className="text-xs font-bold text-white uppercase tracking-wider font-mono">
                Task Dispatch Console: <span className="text-[#ff334b]">{selectedAgent.name}</span>
              </h3>
            </div>
            <span className="text-[11px] text-[#8d98a5] font-mono">
              System Role: {selectedAgent.role}
            </span>
          </div>

          {/* Latest Thought Stream */}
          <div className="bg-[#14181d] border border-[#262d35] rounded p-3 text-xs font-mono text-white">
            <div className="flex items-center gap-2 text-[10px] text-[#8d98a5] mb-1 uppercase tracking-wider">
              <Clock className="w-3 h-3 text-[#4fa3ff]" />
              <span>Current Thought Stream & Telemetry</span>
            </div>
            <p className="text-[#e7e7e7]">{selectedAgent.latestThought || 'Awaiting task queue instructions...'}</p>
          </div>

          {/* Preset Quick Actions */}
          <div>
            <span className="text-[11px] font-mono text-[#8d98a5] uppercase tracking-wider block mb-2">
              Quick Swarm Workflows:
            </span>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {presetTasks.map((pt, i) => (
                <button
                  key={i}
                  onClick={() => handleDispatch(pt.target, pt.prompt)}
                  disabled={isDispatching}
                  className="p-2.5 rounded bg-[#14181d] hover:bg-[#1a1f26] border border-[#262d35] hover:border-[#ff334b] text-left transition-all text-xs font-mono group"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-white font-bold group-hover:text-[#ff334b] transition-colors">{pt.label}</span>
                    <Play className="w-3 h-3 text-[#8d98a5] group-hover:text-[#ff334b] transition-colors" />
                  </div>
                  <p className="text-[10px] text-[#8d98a5] truncate mt-0.5">{pt.prompt}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Custom Task Input */}
          <div className="pt-2">
            <div className="flex gap-2">
              <input
                type="text"
                value={customTask}
                onChange={(e) => setCustomTask(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleDispatch(selectedAgent.id, customTask)}
                placeholder={`Instruct ${selectedAgent.name} (e.g. Execute Vulkan memory benchmark on Port 8000)...`}
                className="flex-grow bg-[#14181d] border border-[#262d35] rounded px-3 py-2 text-xs font-mono text-white focus:outline-none focus:border-[#ff334b]"
              />
              <button
                onClick={() => handleDispatch(selectedAgent.id, customTask)}
                disabled={isDispatching || !customTask.trim()}
                className="px-4 py-2 bg-[#ff334b] hover:bg-[#ff203a] text-white font-bold text-xs uppercase font-mono tracking-wider rounded transition-all disabled:opacity-50 flex items-center gap-1.5 whitespace-nowrap"
              >
                <Play className="w-3.5 h-3.5" />
                <span>Dispatch</span>
              </button>
            </div>
          </div>

        </div>
      )}

    </div>
  );
};
