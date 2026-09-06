import { Sliders, X, RotateCcw, BookOpen, ShieldCheck } from 'lucide-react';
import { ChatParameters, SystemPromptPreset } from '../../types';
import { SYSTEM_PROMPT_PRESETS } from '../../data/systemPrompts';

interface ParametersDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  parameters: ChatParameters;
  onChangeParameters: (updated: ChatParameters) => void;
}

export const ParametersDrawer = ({
  isOpen,
  onClose,
  parameters,
  onChangeParameters,
}: ParametersDrawerProps) => {
  if (!isOpen) return null;

  const handlePresetSelect = (preset: SystemPromptPreset) => {
    onChangeParameters({
      ...parameters,
      systemInstruction: preset.prompt,
    });
  };

  const handleReset = () => {
    onChangeParameters({
      temperature: 0.7,
      topP: 0.95,
      topK: 40,
      maxTokens: 4096,
      contextWindow: 32768,
      repeatPenalty: 1.1,
      systemInstruction: SYSTEM_PROMPT_PRESETS[0].prompt,
      showThinking: true,
      // PHX-FIX (auditoria completa 2026-08-28): reset também deve manter o
      // default seguro (bloqueado), não voltar pra um estado que vaza RAG
      // pra nuvem sem o usuário ter escolhido isso de novo.
      blockRagOnCloudProviders: true,
    });
  };

  return (
    <aside id="parameters-drawer" className="w-80 border-l border-[#262d35] bg-[#14181d] text-[#e7e7e7] flex flex-col h-full shadow-2xl z-20 shrink-0 font-sans">
      
      {/* Header */}
      <div className="p-4 border-b border-[#262d35] flex items-center justify-between bg-[#0b0d10]">
        <div className="flex items-center space-x-2">
          <Sliders className="w-4 h-4 text-[#ff334b]" />
          <h3 className="font-bold text-sm text-white">Parâmetros do Modelo</h3>
        </div>
        <div className="flex items-center space-x-1">
          <button
            onClick={handleReset}
            className="p-1 text-slate-400 hover:text-white rounded-lg hover:bg-[#262d35] transition-colors"
            title="Resetar"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-white rounded-lg hover:bg-[#262d35] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Controls */}
      <div className="p-4 overflow-y-auto space-y-5 flex-1 text-xs font-mono">
        <div>
          <label className="font-semibold text-slate-300 flex items-center space-x-1 mb-2">
            <BookOpen className="w-3.5 h-3.5 text-[#ff334b]" />
            <span>Instrução de Sistema (System Prompt)</span>
          </label>

          <div className="space-y-1.5 mb-2 max-h-36 overflow-y-auto pr-1">
            {SYSTEM_PROMPT_PRESETS.map((preset) => (
              <button
                key={preset.id}
                onClick={() => handlePresetSelect(preset)}
                className={`w-full text-left p-2 rounded-lg border text-[11px] transition-all ${
                  parameters.systemInstruction === preset.prompt
                    ? 'bg-[#ff334b]/20 border-[#ff334b]/50 text-white'
                    : 'bg-[#0b0d10] border-[#262d35] text-slate-400 hover:bg-[#262d35]'
                }`}
              >
                <span className="font-medium block text-slate-200">{preset.title}</span>
                <span className="text-[10px] text-slate-500 line-clamp-1">{preset.description}</span>
              </button>
            ))}
          </div>

          <textarea
            value={parameters.systemInstruction}
            onChange={(e) => onChangeParameters({ ...parameters, systemInstruction: e.target.value })}
            rows={3}
            className="w-full bg-[#0b0d10] border border-[#262d35] rounded-lg p-2.5 text-slate-200 focus:ring-1 focus:ring-[#ff334b] font-sans text-xs"
            placeholder="Instruções de sistema..."
          />
        </div>

        {/* Temperature */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="font-semibold text-slate-300">Temperatura</label>
            <span className="text-[#ff334b] font-bold">{parameters.temperature.toFixed(2)}</span>
          </div>
          <input
            type="range"
            min="0"
            max="2"
            step="0.05"
            value={parameters.temperature}
            onChange={(e) => onChangeParameters({ ...parameters, temperature: parseFloat(e.target.value) })}
            className="w-full accent-[#ff334b] cursor-pointer bg-[#0b0d10] rounded-lg"
          />
          <div className="flex justify-between text-[10px] text-slate-500">
            <span>0.0 (Preciso)</span>
            <span>1.0 (Equilibrado)</span>
            <span>2.0 (Criativo)</span>
          </div>
        </div>

        {/* Max Tokens */}
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label className="font-semibold text-slate-300">Máximo de Tokens</label>
            <span className="text-[#ff334b] font-bold">
              {parameters.maxTokens === 0 ? "Sem limite" : parameters.maxTokens}
            </span>
          </div>
          <input
            type="range"
            min="256"
            max="32768"
            step="256"
            disabled={parameters.maxTokens === 0}
            value={parameters.maxTokens === 0 ? 32768 : parameters.maxTokens}
            onChange={(e) => onChangeParameters({ ...parameters, maxTokens: parseInt(e.target.value) })}
            className="w-full accent-[#ff334b] cursor-pointer bg-[#0b0d10] rounded-lg disabled:opacity-40"
          />
          {/* PHX-NEW (2026-09-06, pedido do usuário: "aumentar contexto...
              ou deixar livre pra modelo ter liberdade de escrita"): antes só
              a criação de documentos tinha essa opção (unlimited_output no
              backend Python) - o chat normal sempre mandava um teto fixo de
              tokens de saída. maxTokens=0 é o sinal que o server.ts (ver
              buildLocalChatRequest) interpreta como "omitir max_tokens da
              requisição" - o modelo para sozinho (fim de resposta natural)
              ou quando o contexto físico acabar, nunca por um teto
              arbitrário de tokens de saída. */}
          <label className="flex items-center gap-2 text-[11px] text-[#8d98a5] cursor-pointer pt-1">
            <input
              type="checkbox"
              checked={parameters.maxTokens === 0}
              onChange={(e) =>
                onChangeParameters({
                  ...parameters,
                  maxTokens: e.target.checked ? 0 : 4096,
                })
              }
              className="accent-[#ff334b]"
            />
            Sem limite (liberdade de escrita - o modelo escreve até terminar sozinho)
          </label>
        </div>

        {/* PHX-FIX (auditoria completa 2026-08-28): trava de privacidade do
            RAG - antes desta rodada, o texto dos documentos indexados era
            sempre anexado ao prompt, mesmo quando o provedor selecionado
            era de nuvem (Gemini). Default seguro: bloqueado. */}
        <div className="space-y-1.5 pt-2 border-t border-[#262d35]">
          <label className="flex items-start gap-2 cursor-pointer select-none">
            <input
              type="checkbox"
              id="block-rag-cloud-toggle"
              checked={parameters.blockRagOnCloudProviders}
              onChange={(e) =>
                onChangeParameters({ ...parameters, blockRagOnCloudProviders: e.target.checked })
              }
              className="mt-0.5 w-3.5 h-3.5 accent-[#ff334b] cursor-pointer shrink-0"
            />
            <span>
              <span className="font-semibold text-slate-300 flex items-center gap-1">
                <ShieldCheck className="w-3.5 h-3.5 text-[#37d67a]" />
                Bloquear RAG em provedores de nuvem
              </span>
              <span className="block text-[10px] text-slate-500 font-sans mt-0.5 leading-snug">
                {parameters.blockRagOnCloudProviders ? (
                  <>Ativado (recomendado): trechos dos seus documentos indexados nunca são enviados a um provedor de nuvem (ex: Gemini). Provedores locais (Ollama, llama-server, LM Studio) continuam recebendo o RAG normalmente.</>
                ) : (
                  <>Desativado: ao usar um provedor de nuvem, trechos dos seus documentos indexados serão enviados junto com a pergunta pela rede.</>
                )}
              </span>
            </span>
          </label>
        </div>
      </div>

    </aside>
  );
};
