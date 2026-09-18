import {
  Bot,
  Columns3,
  Download,
  Cpu,
  Settings,
  Zap,
  CheckCircle2,
  XCircle,
  Activity,
  Sliders,
  Layers,
  BookOpen,
  ExternalLink,
  AudioWaveform
} from 'lucide-react';
import { ProviderConfig } from '../../types';
import phoenixAviaryLogo from '../../assets/phoenix-logo.png';

interface AviaryHeaderProps {
  activeTab: 'chat' | 'arena' | 'hub' | 'vram' | 'stack' | 'voice';
  setActiveTab: (tab: 'chat' | 'arena' | 'hub' | 'vram' | 'stack' | 'voice') => void;
  providers: ProviderConfig[];
  onOpenSettings: () => void;
  onToggleParameters: () => void;
  onOpenManual?: () => void;
  onOpenStandalone?: () => void;
  engineOnline?: boolean;
}

export const AviaryHeader = ({
  activeTab,
  setActiveTab,
  providers,
  onOpenSettings,
  onToggleParameters,
  onOpenManual,
  onOpenStandalone,
  engineOnline = false,
}: AviaryHeaderProps) => {
  const activeProvidersCount = providers.filter((p) => p.enabled && p.status === 'connected').length;
  const totalEnabled = providers.filter((p) => p.enabled).length;

  return (
    <header id="aviary-header" className="bg-[#14181d] border-b border-[#262d35] text-[#e7e7e7] sticky top-0 z-30 shadow-md font-sans">
      <div className="w-full px-3 sm:px-5 lg:px-6">
        <div className="flex items-center justify-between h-14 gap-3">
          
          {/* Left Brand + Navigation */}
          <div className="flex items-center space-x-3 lg:space-x-4 min-w-0">
            <div 
              className="flex items-center space-x-2 cursor-pointer shrink-0"
              onClick={() => setActiveTab('chat')}
            >
              {/* PHX-NEW (2026-08-23, pedido do usuário: "colocar esse ícone
                  como padrão da plataforma"): antes era um quadrado
                  vermelho genérico com um ícone de robô (lucide `Bot`) -
                  nenhuma relação com a marca real da Phoenix. Agora usa o
                  emblema oficial "Phoenix Aviary Platform" (o mesmo par de
                  logos onde "Phoenix Engine" já usa o dele em
                  assets/phoenix_engine.ico para o atalho do Windows). */}
              <img
                src={phoenixAviaryLogo}
                alt="Phoenix Aviary Platform"
                className="w-8 h-8 rounded-lg shadow-lg shadow-[#ff334b]/20 object-contain bg-[#0b0d10]"
              />
              <div className="shrink-0">
                <div className="flex items-center space-x-1.5">
                  <span className="font-bold text-sm sm:text-base tracking-tight text-white whitespace-nowrap">
                    Phoenix Aviary
                  </span>
                  <span className="text-[9px] font-mono font-bold uppercase tracking-wider px-1.5 py-0.5 rounded bg-[#ff334b]/20 text-[#ff334b] border border-[#ff334b]/30 hidden sm:inline-block">
                    WebUI
                  </span>
                </div>
              </div>
            </div>

            {/* Navigation Tabs */}
            <nav className="flex items-center space-x-1 bg-[#0b0d10] p-1 rounded-xl border border-[#262d35] shrink-0 whitespace-nowrap overflow-x-auto">
              <button
                onClick={() => setActiveTab('chat')}
                className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'chat'
                    ? 'bg-[#ff334b] text-white shadow-md'
                    : 'text-slate-400 hover:text-white hover:bg-[#14181d]'
                }`}
              >
                <Bot className="w-3.5 h-3.5" />
                <span>Chat WebUI</span>
              </button>

              <button
                onClick={() => setActiveTab('arena')}
                className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'arena'
                    ? 'bg-[#ff334b] text-white shadow-md'
                    : 'text-slate-400 hover:text-white hover:bg-[#14181d]'
                }`}
              >
                <Columns3 className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Model Arena</span>
              </button>

              <button
                onClick={() => setActiveTab('hub')}
                className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'hub'
                    ? 'bg-[#ff334b] text-white shadow-md'
                    : 'text-slate-400 hover:text-white hover:bg-[#14181d]'
                }`}
              >
                <Download className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Model Hub</span>
              </button>

              <button
                onClick={() => setActiveTab('vram')}
                className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'vram'
                    ? 'bg-[#ff334b] text-white shadow-md'
                    : 'text-slate-400 hover:text-white hover:bg-[#14181d]'
                }`}
              >
                <Cpu className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">VRAM</span>
              </button>

              <button
                onClick={() => setActiveTab('stack')}
                className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'stack'
                    ? 'bg-[#ff334b] text-white shadow-md'
                    : 'text-slate-400 hover:text-white hover:bg-[#14181d]'
                }`}
              >
                <Layers className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Ecossistema</span>
              </button>

              {/* PHX-NEW (2026-08-23, pedido do usuário: "o inverso da
                  transcrição" - ferramenta dedicada de texto para áudio,
                  independente do chat, com download do arquivo gerado). */}
              <button
                onClick={() => setActiveTab('voice')}
                className={`flex items-center space-x-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold transition-all ${
                  activeTab === 'voice'
                    ? 'bg-[#ff334b] text-white shadow-md'
                    : 'text-slate-400 hover:text-white hover:bg-[#14181d]'
                }`}
              >
                <AudioWaveform className="w-3.5 h-3.5" />
                <span className="hidden sm:inline">Texto→Áudio</span>
              </button>
            </nav>
          </div>

          {/* Right Action Tools */}
          <div className="flex items-center space-x-2 shrink-0">
            
            {/* Engine Link Status */}
            <div
              className={`hidden md:flex items-center space-x-1.5 px-2 py-0.5 rounded text-[10px] font-mono border font-semibold ${
                engineOnline
                  ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                  : 'bg-[#ff334b]/10 text-[#ff334b] border-[#ff334b]/30'
              }`}
              title="Comunicação com o Processo da Phoenix Engine (:8000)"
            >
              <Zap className="w-3 h-3 text-[#ff334b]" />
              <span>Engine :8000 [{engineOnline ? 'OK' : 'STANDBY'}]</span>
            </div>

            {/* Parameters Drawer Toggle */}
            {activeTab === 'chat' && (
              <button
                onClick={onToggleParameters}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#0b0d10] transition-colors border border-[#262d35]"
                title="Ajustar Parâmetros de Temperatura"
              >
                <Sliders className="w-4 h-4" />
              </button>
            )}

            {/* Provider Status Pill */}
            <button
              onClick={onOpenSettings}
              className="flex items-center space-x-1.5 px-2.5 py-1 rounded-lg bg-[#0b0d10] hover:bg-[#262d35] border border-[#262d35] text-xs text-slate-300 transition-all font-mono"
            >
              <Activity className="w-3 h-3 text-[#ff334b]" />
              <span className="hidden sm:inline text-[11px]">
                {activeProvidersCount}/{totalEnabled} On
              </span>
              {activeProvidersCount > 0 ? (
                <CheckCircle2 className="w-3 h-3 text-[#37d67a]" />
              ) : (
                <XCircle className="w-3 h-3 text-amber-400" />
              )}
            </button>

            {/* Open in Separate Tab / Window */}
            {onOpenStandalone && (
              <button
                onClick={onOpenStandalone}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#0b0d10] transition-colors border border-[#262d35]"
                title="Abrir Aviary em Nova Janela/Aba"
              >
                <ExternalLink className="w-4 h-4" />
              </button>
            )}

            {/* Manual */}
            {onOpenManual && (
              <button
                onClick={onOpenManual}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#0b0d10] transition-colors border border-[#262d35]"
                title="Manual do Usuário"
              >
                <BookOpen className="w-4 h-4" />
              </button>
            )}

            {/* Settings */}
            <button
              onClick={onOpenSettings}
              className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-[#0b0d10] transition-colors border border-[#262d35]"
              title="Configurar Provedores de LLM"
            >
              <Settings className="w-4 h-4" />
            </button>
          </div>

        </div>
      </div>
    </header>
  );
};
