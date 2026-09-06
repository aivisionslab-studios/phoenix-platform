import { useState, useEffect } from 'react';
import { ProcessLauncherBar } from './components/ProcessLauncherBar';
import { AviaryApp } from './components/aviary/AviaryApp';
import { EngineMissionControl } from './components/engine/EngineMissionControl';
import { ActiveProcessView } from './types';
import { Bot, Cpu, ExternalLink } from 'lucide-react';

export default function App() {
  // Read initial process from URL query params or hash
  const [activeProcess, setActiveProcess] = useState<ActiveProcessView>(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const processParam = params.get('process') || params.get('app') || params.get('view');
      if (processParam === 'engine' || window.location.hash === '#engine') return 'engine';
      if (processParam === 'split' || window.location.hash === '#split') return 'split';
      if (processParam === 'aviary' || window.location.hash === '#aviary') return 'aviary';
    }
    return 'aviary';
  });

  const [isStandaloneWindow, setIsStandaloneWindow] = useState(false);
  const [engineOnline, setEngineOnline] = useState(true);
  // PHX-FIX (auditoria platform_source 2026-08-20, achado A9): antes,
  // AviaryApp.tsx tinha seu PRÓPRIO estado local `hasGeminiKey` inicializado
  // em `true` e NUNCA atualizado (nenhum `setHasGeminiKey` em lugar nenhum
  // do arquivo) - ou seja, a UI sempre assumia "tem chave Gemini
  // configurada" mesmo quando não tinha, o que já era enganoso por si só
  // (afeta o texto "Injetada via Secrets" vs "Nenhuma chave" no modal de
  // provedores) além de nunca permitir escolher automaticamente um
  // provedor local quando não há chave. Movido pra cá porque /api/health
  // (já consultado a cada 5s pra `engineOnline`) devolve `hasGeminiKey` no
  // mesmo payload - uma fonte real em vez de estado nunca sincronizado.
  const [hasGeminiKey, setHasGeminiKey] = useState(false);
  // PHX-FIX (achado real do usuário 2026-08-28: "TIRAR CAMINHO
  // R:\Phoenix\Workstations, PORQUE NAO FAZ SENTIDO NENHUM... JA NAO É
  // MAIS R:\ E SÓ FUNCIONA NA MINHA MAQUINA"): ProcessLauncherBar.tsx e
  // ManualModal.tsx (via AviaryApp.tsx) mostravam esse caminho como
  // literal fixo no JSX - certo só na máquina de quem escreveu aquele
  // texto, e nem nela mais. phoenix_kernel/state.py agora expõe o
  // caminho REAL desta instalação (resolvido por PhoenixPaths.
  // get_workspace(), nunca um literal de drive) em /api/state.
  // workspace_path=null enquanto não carregou ainda (ou Engine offline)
  // é o estado honesto - os componentes abaixo não inventam um caminho
  // no lugar disso.
  const [workspacePath, setWorkspacePath] = useState<string | null>(null);

  // Check if opened as dedicated standalone window
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const isStandalone = params.get('standalone') === 'true' || params.has('process') || params.has('app');
      setIsStandaloneWindow(isStandalone);
    }
  }, []);

  // Update browser URL hash/params cleanly on process change
  const handleProcessChange = (view: ActiveProcessView) => {
    setActiveProcess(view);
    if (typeof window !== 'undefined' && window.history) {
      const newUrl = `${window.location.pathname}?process=${view}`;
      window.history.replaceState({ process: view }, '', newUrl);
    }
  };

  // Open Aviary in a separate window/tab
  const handleOpenAviaryNewWindow = () => {
    if (typeof window !== 'undefined') {
      const url = `${window.location.origin}${window.location.pathname}?process=aviary&standalone=true`;
      window.open(url, '_blank');
    }
  };

  // Open Engine in a separate window/tab
  const handleOpenEngineNewWindow = () => {
    if (typeof window !== 'undefined') {
      const url = `${window.location.origin}${window.location.pathname}?process=engine&standalone=true`;
      window.open(url, '_blank');
    }
  };

  // Check Engine health periodically
  // PHX-FIX (auditoria completa — "tirar todos os fallbacks"): /api/health
  // sempre responde 200 (o servidor Aviary em si está de pé mesmo quando o
  // Phoenix Engine na porta 8000 está offline) - o campo real que diz se o
  // Engine está acessível é `engineOnline` no corpo da resposta, não o
  // status HTTP. Antes, `if (res.ok)` marcava engineOnline=true mesmo com
  // o Phoenix Engine (porta 8000) totalmente offline, e nunca marcava
  // false em resposta bem-sucedida - só no catch de erro de rede do
  // próprio /api/health, que quase nunca falha (é local, porta 3000).
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch('/api/health');
        if (res.ok) {
          const data = await res.json();
          setEngineOnline(Boolean(data.engineOnline));
          setHasGeminiKey(Boolean(data.hasGeminiKey));
        } else {
          setEngineOnline(false);
          setHasGeminiKey(false);
        }
      } catch {
        setEngineOnline(false);
        setHasGeminiKey(false);
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 5000);
    return () => clearInterval(interval);
  }, []);

  // PHX-FIX (mesmo achado do usuário acima): busca o caminho real de
  // workspace via /api/state (passthrough puro do Phoenix Engine, ver
  // server.ts). Repete junto do health-check pra pegar o valor assim
  // que o Engine sobe, sem exigir F5 manual.
  useEffect(() => {
    const fetchWorkspacePath = async () => {
      try {
        const res = await fetch('/api/state');
        if (res.ok) {
          const data = await res.json();
          if (typeof data.workspace_path === 'string' && data.workspace_path) {
            setWorkspacePath(data.workspace_path);
          }
        }
      } catch {
        // Engine offline/inacessível — mantém o valor anterior (ou null)
        // em vez de inventar um caminho.
      }
    };
    fetchWorkspacePath();
    const interval = setInterval(fetchWorkspacePath, 5000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div id="phoenix-app-root" className="w-screen h-screen flex flex-col bg-[#0b0d10] text-[#e7e7e7] overflow-hidden select-none font-sans">
      
      {/* Top Process Launcher & Separated Process Router */}
      <ProcessLauncherBar
        activeProcess={activeProcess}
        onChangeProcess={handleProcessChange}
        onOpenAviaryNewWindow={handleOpenAviaryNewWindow}
        onOpenEngineNewWindow={handleOpenEngineNewWindow}
        engineOnline={engineOnline}
        workspacePath={workspacePath}
      />

      {/* Main Workspace Frame */}
      <div className="flex-1 flex overflow-hidden relative">
        
        {/* VIEW 1: Standalone Aviary Platform (Porta 3000 - ChatGPT / OpenWebUI / LM Studio) */}
        {activeProcess === 'aviary' && (
          <div className="w-full h-full flex flex-col overflow-hidden">
            <AviaryApp
              onOpenStandalone={handleOpenAviaryNewWindow}
              engineOnline={engineOnline}
              hasGeminiKey={hasGeminiKey}
              workspacePath={workspacePath}
            />
          </div>
        )}

        {/* VIEW 2: Standalone Phoenix Engine (Porta 8000 - Vulkan Mission Control & Datacenter) */}
        {activeProcess === 'engine' && (
          <div className="w-full h-full flex flex-col overflow-hidden">
            <EngineMissionControl
              onOpenStandalone={handleOpenEngineNewWindow}
            />
          </div>
        )}

        {/* VIEW 3: Dual Process Split Screen (Lado a Lado) */}
        {activeProcess === 'split' && (
          <div className="w-full h-full flex flex-col lg:flex-row overflow-hidden divide-y lg:divide-y-0 lg:divide-x divide-[#262d35]">
            
            {/* Left Side: Phoenix Aviary Platform (Port 3000) */}
            <div className="flex-1 flex flex-col h-full overflow-hidden min-w-0">
              <div className="bg-[#14181d] px-4 py-1.5 border-b border-[#262d35] flex items-center justify-between text-xs font-mono">
                <div className="flex items-center space-x-2">
                  <Bot className="w-4 h-4 text-[#ff334b]" />
                  <span className="font-bold text-white">PROCESSO 1: PHOENIX AVIARY (PORTA :3000)</span>
                  <span className="text-[10px] bg-[#ff334b]/20 text-[#ff334b] px-1.5 py-0.2 rounded">ChatGPT / OpenWebUI</span>
                </div>
                <button
                  onClick={handleOpenAviaryNewWindow}
                  className="text-slate-400 hover:text-white flex items-center space-x-1 text-[11px]"
                  title="Abrir em Janela Separada"
                >
                  <ExternalLink className="w-3 h-3" />
                  <span className="hidden sm:inline">Desacoplar</span>
                </button>
              </div>
              <div className="flex-1 overflow-hidden">
                <AviaryApp engineOnline={engineOnline} hasGeminiKey={hasGeminiKey} workspacePath={workspacePath} />
              </div>
            </div>

            {/* Right Side: Phoenix Engine (Port 8000) */}
            <div className="flex-1 flex flex-col h-full overflow-hidden min-w-0">
              <div className="bg-[#14181d] px-4 py-1.5 border-b border-[#262d35] flex items-center justify-between text-xs font-mono">
                <div className="flex items-center space-x-2">
                  <Cpu className="w-4 h-4 text-[#37d67a]" />
                  <span className="font-bold text-white">PROCESSO 2: PHOENIX ENGINE (PORTA :8000)</span>
                  <span className="text-[10px] bg-[#37d67a]/20 text-[#37d67a] px-1.5 py-0.2 rounded">Vulkan Kernel</span>
                </div>
                <button
                  onClick={handleOpenEngineNewWindow}
                  className="text-slate-400 hover:text-white flex items-center space-x-1 text-[11px]"
                  title="Abrir em Janela Separada"
                >
                  <ExternalLink className="w-3 h-3" />
                  <span className="hidden sm:inline">Desacoplar</span>
                </button>
              </div>
              <div className="flex-1 overflow-hidden">
                <EngineMissionControl />
              </div>
            </div>

          </div>
        )}

      </div>

    </div>
  );
}
