import { useState } from 'react';
import { 
  BookOpen,
  ShieldCheck,
  Cpu,
  HardDrive,
  Server,
  Layers, 
  Terminal, 
  Copy, 
  Check, 
  Sparkles,
  AlertTriangle
} from 'lucide-react';

export const ManualModal = ({
  isOpen,
  onClose,
  workspacePath = null,
}: {
  isOpen: boolean;
  onClose: () => void;
  // PHX-FIX (achado real do usuário 2026-08-28: "TIRAR CAMINHO
  // R:\Phoenix\Workstations, PORQUE NAO FAZ SENTIDO NENHUM... JA NAO É
  // MAIS R:\ E SÓ FUNCIONA NA MINHA MAQUINA"): caminho real desta
  // instalação (App.tsx -> /api/state -> PhoenixPaths.get_workspace()),
  // substitui o "R:\Phoenix\Workstations\..." que estava cravado aqui.
  // null enquanto não carregou/Engine offline.
  workspacePath?: string | null;
}) => {
  const [lang, setLang] = useState<'pt' | 'en'>('pt');
  const [copiedText, setCopiedText] = useState<string | null>(null);

  if (!isOpen) return null;

  // PHX-FIX (mesmo achado do usuário acima): antes do PhoenixPaths
  // resolver de verdade (Engine ainda offline/carregando), não inventa
  // um caminho - mostra que ainda não foi detectado.
  const modelsBase = workspacePath ? `${workspacePath}\\Models` : null;
  const pathOrPlaceholder = (suffix: string) =>
    modelsBase ? `${modelsBase}${suffix}` : '(caminho ainda não detectado — abra com o Phoenix Engine online)';

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedText(text);
    setTimeout(() => setCopiedText(null), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-3 sm:p-6 overflow-y-auto font-sans select-none">
      <div className="bg-[#14181d] border border-[#262d35] rounded-2xl max-w-5xl w-full max-h-[92vh] flex flex-col shadow-2xl overflow-hidden font-mono">
        
        {/* Header Modal */}
        <div className="p-4 sm:p-5 border-b border-[#262d35] flex items-center justify-between bg-[#0b0d10]">
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-[#ff334b]/20 border border-[#ff334b]/30 flex items-center justify-center text-[#ff334b]">
              <BookOpen className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base sm:text-lg font-bold text-white flex items-center gap-2">
                <span>Manual de Operação &amp; Documentação Técnica</span>
                <span className="text-[10px] uppercase font-mono px-2 py-0.5 rounded bg-[#ff334b]/20 text-[#ff334b] border border-[#ff334b]/30">
                  v4.5 (projeto integrado)
                </span>
              </h2>
              <p className="text-xs text-slate-400">
                Phoenix Aviary Platform (:3000) &amp; Phoenix Engine (:8000)
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <div className="flex items-center bg-[#0b0d10] p-1 rounded-xl border border-[#262d35] text-xs font-mono">
              <button
                onClick={() => setLang('pt')}
                className={`px-3 py-1 rounded-lg font-bold transition-all cursor-pointer ${
                  lang === 'pt' ? 'bg-[#ff334b] text-white shadow-md' : 'text-slate-400 hover:text-white'
                }`}
              >
                🇧🇷 PT-BR
              </button>
              <button
                onClick={() => setLang('en')}
                className={`px-3 py-1 rounded-lg font-bold transition-all cursor-pointer ${
                  lang === 'en' ? 'bg-[#ff334b] text-white shadow-md' : 'text-slate-400 hover:text-white'
                }`}
              >
                🇺🇸 EN-US
              </button>
            </div>

            <button
              onClick={onClose}
              className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-[#262d35] transition-colors cursor-pointer"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Content Area */}
        <div className="p-5 overflow-y-auto space-y-6 text-slate-200 text-xs sm:text-sm leading-relaxed">
          
          {/* PHX-FIX (achado real do usuário 2026-08-24, "jogar fora o
              piper de vez"): esta caixa inteira ("Solução Rápida: Piper
              TTS & eSpeak-NG no Windows") já se descrevia como "motor
              legado" e só valia "pra quem ainda usa vozes Piper
              manualmente" - com o PiperDriver removido de vez do código
              (drivers/piper.py apagado, ver engine.py), não existe mais
              nenhum jeito de usar vozes Piper na Phoenix, manualmente ou
              não. Removida por completo em vez de deixar uma seção de
              ajuda pra um problema que não pode mais acontecer. */}

          {/* Section 1: PT-BR Content */}
          {lang === 'pt' ? (
            <div className="space-y-6">
              
              {/* 1. Visão Geral */}
              <section className="space-y-2">
                <h3 className="text-base font-bold text-white border-b border-[#262d35] pb-1.5 flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-[#ff334b]" />
                  1. Visão Geral da Plataforma
                </h3>
                <p className="text-xs text-slate-300 leading-relaxed font-sans">
                  A <strong>Phoenix Platform v4.5</strong> constitui um ecossistema integrado para orquestração, execução e monitoramento de Inteligência Artificial Local e em Nuvem. O projeto alterna entre modelos locais (llama.cpp, Phoenix Diffusion, Ollama opcional) e provedores na nuvem (Google Gemini, OpenAI, Anthropic Claude).
                </p>
                {/* PHX-FIX (auditoria 2026-08-20, "política final de runtimes"):
                    o parágrafo acima descreve a troca MANUAL de provedor de
                    chat aqui no Aviary (onde LM Studio de fato é uma opção
                    válida) - mas sem esta nota, um leitor pode achar que
                    LM Studio também é usado pelo motor de missões automáticas
                    do Resident. Não é: o Resident só aceita llama.cpp
                    (padrão) ou Ollama (opcional) como runtime de texto. */}
                <p className="text-[11px] text-[#8d98a5] leading-relaxed font-sans italic">
                  Nota: a lista acima é a seleção <strong>manual</strong> de provedor de chat aqui no Aviary. O motor de missões automáticas do Resident (<code>resident research ...</code> e afins) usa só <strong>llama.cpp</strong> (padrão) ou <strong>Ollama</strong> (opcional, via <code>resident engine set ollama</code>) — LM Studio nunca é acionado automaticamente pelo Resident, só aparece aqui como opção manual de chat.
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 pt-2">
                  <div className="bg-[#0b0d10] p-2.5 rounded-lg border border-[#262d35]">
                    <span className="text-[#ff334b] font-bold block text-xs">Orquestração Multi-Provedor</span>
                    <span className="text-[11px] text-[#8d98a5]">13+ motores suportados simultaneamente.</span>
                  </div>
                  <div className="bg-[#0b0d10] p-2.5 rounded-lg border border-[#262d35]">
                    <span className="text-[#37d67a] font-bold block text-xs">Aceleração Vulkan RADV</span>
                    <span className="text-[11px] text-[#8d98a5]">Polaris RX 580 (2048SP) 8GB VRAM dedicada.</span>
                  </div>
                  <div className="bg-[#0b0d10] p-2.5 rounded-lg border border-[#262d35]">
                    <span className="text-[#4fa3ff] font-bold block text-xs">Síntese Neural Kokoro-82M</span>
                    <span className="text-[11px] text-[#8d98a5]">8 idiomas, detecção automática por trecho, rodando em CPU local.</span>
                  </div>
                  <div className="bg-[#0b0d10] p-2.5 rounded-lg border border-[#262d35]">
                    <span className="text-amber-400 font-bold block text-xs">RAG &amp; Multi-Agent Swarm</span>
                    <span className="text-[11px] text-[#8d98a5]">Busca vetorial em 46 manuais e enxame autônomo.</span>
                  </div>
                </div>
              </section>

              {/* 2. Topologia de Portas */}
              <section className="space-y-2">
                <h3 className="text-base font-bold text-white border-b border-[#262d35] pb-1.5 flex items-center gap-2">
                  <Server className="w-4 h-4 text-[#37d67a]" />
                  2. Topologia de Portas &amp; Endpoints de Rede
                </h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-left border border-[#262d35] rounded-lg overflow-hidden text-xs">
                    <thead className="bg-[#0b0d10] text-slate-400 border-b border-[#262d35]">
                      <tr>
                        <th className="p-2.5">Provedor / Serviço</th>
                        <th className="p-2.5">Tipo</th>
                        <th className="p-2.5">Porta Padrão</th>
                        <th className="p-2.5">Descrição Técnica</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#262d35] bg-[#14181d]">
                      <tr>
                        <td className="p-2.5 font-bold text-white">Google Gemini Cloud API</td>
                        <td className="p-2.5 text-purple-400">Nuvem</td>
                        <td className="p-2.5 font-mono">HTTPS (443)</td>
                        <td className="p-2.5 text-[#8d98a5]">Gemini 3.6 Flash, 3.1 Pro Preview, 3.1 Flash Lite</td>
                      </tr>
                      <tr>
                        <td className="p-2.5 font-bold text-[#ff334b]">Phoenix Aviary Platform</td>
                        <td className="p-2.5 text-white">WebUI / Node</td>
                        <td className="p-2.5 font-mono text-[#ff334b]">3000</td>
                        <td className="p-2.5 text-[#8d98a5]">Interface gráfica ChatGPT/OpenWebUI, TTS, Arena</td>
                      </tr>
                      <tr>
                        <td className="p-2.5 font-bold text-[#37d67a]">Phoenix Python Engine</td>
                        <td className="p-2.5 text-white">Kernel / RPC</td>
                        <td className="p-2.5 font-mono text-[#37d67a]">8000</td>
                        <td className="p-2.5 text-[#8d98a5]">Servidor FastAPI central de gerenciamento e telemetria</td>
                      </tr>
                      <tr>
                        <td className="p-2.5 font-bold text-amber-400">Ollama Local Engine</td>
                        <td className="p-2.5 text-white">Local GGUF</td>
                        <td className="p-2.5 font-mono text-amber-400">11434</td>
                        <td className="p-2.5 text-[#8d98a5]">Servidor de modelos GGUF com tags e REST API</td>
                      </tr>
                      <tr>
                        <td className="p-2.5 font-bold text-cyan-400">LM Studio Server</td>
                        <td className="p-2.5 text-white">Local GUI/API</td>
                        <td className="p-2.5 font-mono text-cyan-400">1234</td>
                        <td className="p-2.5 text-[#8d98a5]">Interface desktop e servidor compatível OpenAI</td>
                      </tr>
                      <tr>
                        <td className="p-2.5 font-bold text-emerald-400">llama-server (llama.cpp)</td>
                        <td className="p-2.5 text-white">Nativo C++/Vulkan</td>
                        <td className="p-2.5 font-mono text-emerald-400">8081</td>
                        <td className="p-2.5 text-[#8d98a5]">Servidor nativo de alta performance no chip Polaris</td>
                      </tr>
                      <tr>
                        <td className="p-2.5 font-bold text-[#4fa3ff]">vLLM Server</td>
                        <td className="p-2.5 text-white">PagedAttention</td>
                        <td className="p-2.5 font-mono text-[#4fa3ff]">8000</td>
                        <td className="p-2.5 text-[#8d98a5]">Servidor de alto throughput para produção</td>
                      </tr>
                      <tr>
                        <td className="p-2.5 font-bold text-purple-400">Open WebUI Gateway</td>
                        <td className="p-2.5 text-white">Proxy Gateway</td>
                        <td className="p-2.5 font-mono text-purple-400">8010</td>
                        <td className="p-2.5 text-[#8d98a5]">Gateway proxy para pipelines de IA e multi-usuário</td>
                      </tr>
                      <tr>
                        <td className="p-2.5 font-bold text-blue-400">AnythingLLM Enterprise</td>
                        <td className="p-2.5 text-white">RAG Engine</td>
                        <td className="p-2.5 font-mono text-blue-400">3001</td>
                        <td className="p-2.5 text-[#8d98a5]">Engine RAG corporativo para documentos</td>
                      </tr>
                      <tr>
                        <td className="p-2.5 font-bold text-rose-400">ComfyUI no WSL2 (Ubuntu)</td>
                        <td className="p-2.5 text-white">Difusão / Shaders</td>
                        <td className="p-2.5 font-mono text-rose-400">7860 / 8188</td>
                        <td className="p-2.5 text-[#8d98a5]">Espelhamento de modelos ln -s /mnt/e/models para SD/FLUX</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </section>

              {/* 3. Estrutura de Diretórios */}
              {/* PHX-FIX (achado real do usuário 2026-08-28: "TIRAR CAMINHO
                  R:\Phoenix\Workstations, PORQUE NAO FAZ SENTIDO NENHUM...
                  JA NAO É MAIS R:\ E SÓ FUNCIONA NA MINHA MAQUINA"): os 4
                  caminhos abaixo eram literais fixos no JSX (drive R:\ de
                  uma máquina específica, que nem reflete mais a instalação
                  de quem escreveu isso). Agora vêm de workspacePath (App.tsx
                  -> /api/state -> PhoenixPaths.get_workspace(), a mesma
                  pasta que o backend de fato resolve e usa) - com um aviso
                  honesto no lugar do caminho enquanto isso não carregou. */}
              <section className="space-y-2">
                <h3 className="text-base font-bold text-white border-b border-[#262d35] pb-1.5 flex items-center gap-2">
                  <HardDrive className="w-4 h-4 text-[#ff334b]" />
                  3. Estrutura de Pastas &amp; Armazenamento (Real, Detectada)
                </h3>
                <div className="bg-[#0b0d10] p-4 rounded-xl font-mono text-xs text-slate-300 border border-[#262d35] space-y-2">
                  <div className="flex items-center justify-between border-b border-[#262d35] pb-1.5">
                    <span className="text-[#ff334b] font-bold">Caminhos Reais desta Instalação:</span>
                    <button
                      onClick={() => modelsBase && copyToClipboard(`${modelsBase}\\`)}
                      disabled={!modelsBase}
                      className="text-xs text-slate-400 hover:text-white flex items-center gap-1 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      {modelsBase && copiedText === `${modelsBase}\\` ? <Check className="w-3 h-3 text-[#37d67a]" /> : <Copy className="w-3 h-3" />}
                      <span>Copiar Raiz</span>
                    </button>
                  </div>
                  <p>• <code className="text-white">C:\AIVisions Platform\PHOENIX 4.5\</code> — Código-fonte e servidor Node.js/Express.</p>
                  <p>• <code className="text-amber-300">{pathOrPlaceholder('\\Chat\\GGUF\\')}</code> — Modelos LLM GGUF (ex: qwen3-8b, mistral-7b, deepseek-r1-8b).</p>
                  <p>• <code className="text-purple-300">{pathOrPlaceholder('\\Vision\\')}</code> — Modelos multimodais (MiniCPM-V 4.6, mmproj-MiniCPM-V-4.6-F16.gguf).</p>
                  <p>• <code className="text-[#37d67a]">{pathOrPlaceholder('\\Voice\\Kokoro\\')}</code> — kokoro-v1.0.onnx + voices-v1.0.bin (motor de voz padrão).</p>
                </div>
              </section>

              {/* 4. MiniCPM-V Multimodal */}
              <section className="space-y-2">
                <h3 className="text-base font-bold text-white border-b border-[#262d35] pb-1.5 flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-purple-400" />
                  4. MiniCPM-V 4.6 (Visão &amp; Narração Multimodal Nativa)
                </h3>
                <p className="text-xs text-slate-300 leading-relaxed font-sans">
                  Para o MiniCPM-V conseguir enxergar e narrar imagens em áudio via <code>llama-mtmd-cli</code>, são necessários <strong>2 arquivos obrigatórios</strong> na pasta <code>Workstations/Models/Chat/GGUF/</code>:
                </p>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
                  <div className="bg-[#0b0d10] p-3 rounded-lg border border-purple-500/30 space-y-1">
                    <span className="font-bold text-xs text-purple-300">1. Projetor de Imagem (OBRIGATÓRIO)</span>
                    <p className="text-[11px] text-[#8d98a5]"><code>mmproj-MiniCPM-V-4.6-F16.gguf</code> (~0.85 GB, estimado): Sem esse projetor o modelo não enxerga os pixels da imagem.</p>
                  </div>
                  <div className="bg-[#0b0d10] p-3 rounded-lg border border-[#262d35] space-y-1">
                    <span className="font-bold text-xs text-cyan-300">2. Pesos de Linguagem (Q4_K_M)</span>
                    <p className="text-[11px] text-[#8d98a5]"><code>MiniCPM-V-4.6-Q4_K_M.gguf</code> (529 MB, confirmado): Pesos do modelo 0.8B (SigLIP2 + Qwen3.5) para raciocínio visual — muito mais leve que a versão 2.6 anterior.</p>
                  </div>
                </div>
              </section>

            </div>
          ) : (
            /* Section 2: EN-US Content */
            <div className="space-y-6">
              <section className="space-y-2">
                <h3 className="text-base font-bold text-white border-b border-[#262d35] pb-1.5 flex items-center gap-2">
                  <ShieldCheck className="w-4 h-4 text-[#ff334b]" />
                  1. Platform Overview (English)
                </h3>
                <p className="text-xs text-slate-300 leading-relaxed font-sans">
                  <strong>Phoenix Platform v4.5</strong> is a unified ecosystem for local and cloud AI orchestration, execution, and hardware telemetry. It supports local runtimes (llama.cpp, native Phoenix Diffusion and optional Ollama) and cloud providers (Google Gemini, OpenAI and Anthropic Claude).
                </p>
                <p className="text-[11px] text-[#8d98a5] leading-relaxed font-sans italic">
                  Note: the list above is the <strong>manual</strong> chat-provider selector here in Aviary. The Resident's automatic mission engine (<code>resident research ...</code> and similar) only uses <strong>llama.cpp</strong> (default) or <strong>Ollama</strong> (optional, via <code>resident engine set ollama</code>) — LM Studio is never invoked automatically by the Resident, it only appears here as a manual chat option.
                </p>
              </section>

              <section className="space-y-2">
                <h3 className="text-base font-bold text-white border-b border-[#262d35] pb-1.5 flex items-center gap-2">
                  <Server className="w-4 h-4 text-[#37d67a]" />
                  2. System Architecture &amp; Port Topology
                </h3>
                <div className="bg-[#0b0d10] p-3.5 rounded-xl font-mono text-xs text-slate-300 border border-[#262d35] space-y-1">
                  <p className="text-[#ff334b]">● Frontend WebUI (Vite + React 19): http://localhost:3000</p>
                  <p className="text-[#ff334b]">● Node.js Server Proxy (server.ts): http://localhost:3000</p>
                  <p className="text-[#37d67a]">● Phoenix Python Engine Core (api_server.py): http://localhost:8000</p>
                  <p className="text-emerald-400">● llama-server Native Engine (Vulkan): http://localhost:8081</p>
                  <p className="text-amber-400">● Ollama Engine: http://localhost:11434</p>
                  <p className="text-cyan-400">● LM Studio: http://localhost:1234</p>
                  <p className="text-purple-400">● Open WebUI Gateway: http://localhost:8010</p>
                </div>
              </section>
            </div>
          )}

        </div>

        {/* Footer */}
        <div className="p-4 border-t border-[#262d35] bg-[#0b0d10] flex items-center justify-between">
          <span className="text-xs text-[#8d98a5] font-mono">
            Documentação baseada em <code className="text-white">MANUAL.md</code> e benchmarks 2026.
          </span>
          <button
            onClick={onClose}
            className="px-5 py-2 bg-[#ff334b] hover:bg-[#ff334b]/90 text-white text-xs font-bold rounded-xl transition-all shadow-md cursor-pointer"
          >
            Fechar Manual
          </button>
        </div>

      </div>
    </div>
  );
};
