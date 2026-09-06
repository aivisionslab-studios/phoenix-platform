import { useState, useEffect } from 'react';
import {
  HardwareProfile,
  InferenceConfig,
  EnvironmentService,
  PortNode,
  BridgePacket,
  AviaryAgent,
  RagDocument,
  TerminalEntry,
  TelemetryPoint
} from '../../types';
import { Header } from '../Header';
import { MetricCards } from '../MetricCards';
import { TelemetryWave } from '../TelemetryWave';
import { TerminalConsole } from '../TerminalConsole';
import { PortBridgePanel } from '../PortBridgePanel';
import { AviarySwarmPanel } from '../AviarySwarmPanel';
import { HardwareDrawer, HARDWARE_PRESETS } from '../HardwareDrawer';
import { RagDrawer } from '../RagDrawer';
import { SystemReportModal } from '../SystemReportModal';

// PHX-NEW (auditoria platform_source 2026-08-20, achado A5): mapeamento
// explícito nome-de-exibição -> chave real devolvida por
// ServicesEngine.get_environment_status() (phoenix_kernel/services/engine.py),
// que é repassada quase sem alteração como `data.environment` em /api/state.
// Substitui a transformação de string frágil (`toLowerCase().replace(...)`)
// que só batia por acidente com 'LLAMA.CPP' e nunca com 'VULKAN SDK',
// 'OLLAMA API' ou 'MCP BRIDGE'. FILESYSTEM e PORT 8000/3000 ficam de fora
// de propósito: não têm chave correspondente em get_environment_status()
// (FILESYSTEM não tem probe real ainda; as portas são sincronizadas
// separadamente a partir de `ports`, ver PORT_SERVICE_NAMES abaixo).
const SERVICE_ENV_KEYS: Record<string, string> = {
  'DOCKER': 'docker',
  'PYTHON': 'python',
  'VULKAN SDK': 'vulkan',
  'LLAMA.CPP': 'llama_cpp',
  'OLLAMA API': 'ollama',
  'MCP BRIDGE': 'mcp',
};

// PHX-NEW (mesmo achado): as duas linhas de porta em `services` não têm
// contrapartida em get_environment_status() - são sincronizadas a partir
// do estado `ports`, que já é atualizado por ping real (pingBridge, 1x/s).
const PORT_SERVICE_NAMES: Record<string, number> = {
  'PORT 8000 (ENGINE)': 8000,
  'PORT 3000 (AVIARY)': 3000,
};

export const EngineMissionControl = ({
  onOpenStandalone,
}: {
  onOpenStandalone?: () => void;
}) => {
  const [activeView, setActiveView] = useState<'dashboard' | 'ports' | 'swarm' | 'vulkan' | 'rag'>('dashboard');

  const [hardwareDrawerOpen, setHardwareDrawerOpen] = useState(false);
  const [ragDrawerOpen, setRagDrawerOpen] = useState(false);
  const [systemReportOpen, setSystemReportOpen] = useState(false);

  const [hardware, setHardware] = useState<HardwareProfile>(HARDWARE_PRESETS[0]);
  const [isBenchmarking, setIsBenchmarking] = useState(false);
  const [benchmarkLog, setBenchmarkLog] = useState<string[]>([]);

  // PHX-FIX (auditoria platform_source 2026-08-20, achado A5): o comentário
  // do fetchState() logo abaixo ("O estado inicial fica vazio/neutro") já
  // dizia a intenção certa, mas os valores aqui não eram neutros de
  // verdade - "LLAMA 3 (8B)"/"Q4_K_M"/13.84 tok/s/5420MB VRAM/5500MB RAM
  // eram números específicos, plausíveis o bastante pra parecer telemetria
  // real no primeiro render (e "LLAMA 3 (8B)" nem é o modelo default de
  // verdade desta Golden Baseline - é qwen3:8b, ver catalog/models.json).
  // tps/vramUsedMB/ramUsedMB já são corrigidos pelo polling real 3s depois
  // (fetchState abaixo), então zerar aqui é seguro. model/quantization
  // ainda NÃO têm fonte real no /api/state hoje (ResidentManager já
  // rastreia isso via get_active_models(), mas essa rota não está exposta
  // pro frontend ainda) - ficam como placeholder neutro em vez de inventar
  // um nome de modelo, até esse fio ser fechado numa rodada futura.
  const [inference, setInference] = useState<InferenceConfig>({
    backend: 'VULKAN_NATIVE',
    model: '—',
    quantization: '—',
    contextWindow: 8192,
    tps: 0,
    vramUsedMB: 0,
    ramUsedMB: 0,
    batchSize: 512,
    threads: 12
  });

  // PHX-FIX (auditoria completa — "tirar todos os fallbacks", achado do
  // ping falso): antes isto era `useState` SEM setter - `status`,
  // `latencyMs`, `requestsTotal` e `throughputKbps` ficavam congelados
  // pra sempre nos valores da inicialização, alimentando badges no
  // Header.tsx e cards no PortBridgePanel.tsx que pareciam telemetria ao
  // vivo mas nunca mudavam. `requestsTotal`/`throughputKbps` foram
  // removidos de types.ts (nunca eram sequer renderizados - dado morto
  // fabricado). `status`/`latencyMs` agora são reais: começam neutros
  // (STANDBY / 0) e são atualizados de verdade pelo loop de ping abaixo.
  const [ports, setPorts] = useState<PortNode[]>([
    {
      port: 8000,
      label: 'PHOENIX ENGINE',
      service: 'Phoenix Engine API & local runtimes',
      status: 'STANDBY',
      latencyMs: 0,
      endpoint: 'http://localhost:8000',
      protocol: 'HTTP/REST',
      description: 'API do Engine, descoberta de hardware e execução local'
    },
    {
      port: 3000,
      label: 'PHOENIX AVIARY PLATFORM',
      service: 'Mission Control UI & Agent Swarm',
      status: 'STANDBY',
      latencyMs: 0,
      endpoint: 'http://localhost:3000',
      protocol: 'HTTP/REST',
      description: 'Web platform, multi-agent orchestration, mission control dashboard'
    }
  ]);

  // PHX-NEW (fix real do "Live Inter-Port Packet Inspector" e do
  // "Execute Port Ping"): log de pacotes real, alimentado pelo mesmo
  // ping de 1s abaixo - substitui os 4 pacotes fabricados que existiam
  // hardcoded dentro de PortBridgePanel.tsx.
  const [bridgePackets, setBridgePackets] = useState<BridgePacket[]>([]);

  // PHX-NEW: ping real, uma vez por segundo, contra dois endpoints:
  // /api/ping (100% local, mede só a latência do processo Node/Aviary -
  // porta 3000) e /api/health (que por sua vez chama o Phoenix Engine de
  // verdade - porta 8000, mede o round-trip completo e o status real via
  // `engineOnline`). Isto é o que faz "Stream Auto-Refresh: 1000ms" (rótulo
  // que já existia na UI, mas nunca foi verdade) virar um fato, não uma
  // promessa vazia. Devolve o resultado pra quem chamou poder mostrar o
  // número exato do ping manual também (botão "Execute Port Ping").
  const pingBridge = async () => {
    const aviaryT0 = performance.now();
    let aviaryLatencyMs = 0;
    let aviaryOk = false;
    try {
      const r = await fetch('/api/ping');
      aviaryLatencyMs = performance.now() - aviaryT0;
      aviaryOk = r.ok;
    } catch {
      aviaryOk = false;
    }

    const engineT0 = performance.now();
    let engineLatencyMs = 0;
    let engineOnline = false;
    let engineHttpStatus = 0;
    try {
      const r = await fetch('/api/health');
      engineLatencyMs = performance.now() - engineT0;
      engineHttpStatus = r.status;
      const data = await r.json().catch(() => ({}));
      engineOnline = Boolean(data.engineOnline);
    } catch {
      engineOnline = false;
    }

    setPorts(prev => prev.map(p => {
      if (p.port === 8000) {
        return { ...p, status: engineOnline ? 'ONLINE' : 'STANDBY', latencyMs: Math.round(engineLatencyMs * 10) / 10 };
      }
      if (p.port === 3000) {
        return { ...p, status: aviaryOk ? 'ONLINE' : 'ERROR', latencyMs: Math.round(aviaryLatencyMs * 10) / 10 };
      }
      return p;
    }));

    setBridgePackets(prev => [
      {
        id: `${Date.now()}-h`,
        time: new Date().toLocaleTimeString(),
        from: 3000,
        to: 8000,
        type: 'GET /api/health',
        payload: engineOnline ? 'engineOnline: true' : 'engineOnline: false (Engine offline ou inacessível)',
        status: engineHttpStatus,
      },
      ...prev,
    ].slice(0, 8));

    return { engineOnline, engineLatencyMs, aviaryLatencyMs };
  };

  useEffect(() => {
    pingBridge();
    const interval = setInterval(pingBridge, 1000);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // PHX-FIX (auditoria platform_source 2026-08-20, achado A5): todas as 9
  // entradas começavam 'online'/'warning' fixos - mesmo problema do
  // Header.tsx (achado A6), badge de "conectado" antes de qualquer
  // confirmação real. O fetchState() abaixo (efeito "Serviços reais do
  // environment") já busca /api/state de verdade e tenta corrigir isso,
  // mas o cruzamento nome->chave era uma transformação de string frágil
  // (`s.name.toLowerCase().replace(/[^a-z0-9]/g,'_')`) que só batia por
  // acidente com 'LLAMA.CPP'->'llama_cpp' - 'VULKAN SDK'->'vulkan_sdk',
  // 'OLLAMA API'->'ollama_api' e 'MCP BRIDGE'->'mcp_bridge' NUNCA batiam
  // com as chaves reais do backend (services/engine.py.get_environment_
  // status() devolve 'vulkan'/'ollama'/'mcp', não as variantes com sufixo),
  // e 'PORT 8000 (ENGINE)'/'PORT 3000 (AVIARY)' nem estão nesse dict -
  // essas 5 entradas ficavam fabricadas pra sempre, nunca corrigidas pelo
  // polling real. Ver SERVICE_ENV_KEYS (mapeamento explícito) e o efeito
  // que sincroniza as 2 linhas de porta a partir do `ports` real (que já
  // tem ping de verdade) logo abaixo.
  const [services, setServices] = useState<EnvironmentService[]>([
    { name: 'PORT 8000 (ENGINE)', status: 'idle', detail: 'Vulkan LLM Backend' },
    { name: 'PORT 3000 (AVIARY)', status: 'idle', detail: 'Mission Control UI' },
    { name: 'DOCKER', status: 'idle', detail: 'Container runtime' },
    { name: 'PYTHON', status: 'idle', detail: 'PyTorch / GGUF tools' },
    { name: 'VULKAN SDK', status: 'idle', detail: 'RADV Polaris 10' },
    { name: 'LLAMA.CPP', status: 'idle', detail: 'Ready for models' },
    // FILESYSTEM não tem verificação real no backend hoje (nenhum campo
    // em get_environment_status() cobre isso) - fica 'idle' permanente em
    // vez de fingir 'online', até um probe real existir.
    { name: 'FILESYSTEM', status: 'idle', detail: 'Sem verificação real ainda' },
    { name: 'OLLAMA API', status: 'idle', detail: 'Local API active' },
    { name: 'MCP BRIDGE', status: 'idle', detail: 'Tool protocol active' }
  ]);

  // PHX-FIX (auditoria platform_source 2026-08-20, achado A5): os 4 agentes
  // começavam com `status: 'ACTIVE'/'DISPATCHING'/'THINKING'`,
  // `tasksCompleted` fixo (842/1205/429/619) e um `latestThought` de
  // exemplo escrito à mão ("Vulkan command queue: 0 errors...") - tudo
  // fabricado antes de qualquer tarefa real ter sido despachada, e nenhum
  // desses três campos vem de um sync automático como `services`/`ports`
  // (só mudam de verdade quando o usuário despacha uma tarefa via
  // handleDispatchAgentTask, ver abaixo). Ficam neutros aqui: IDLE,
  // 0 tarefas, sem "pensamento" nenhum até a primeira execução real.
  const [agents, setAgents] = useState<AviaryAgent[]>([
    {
      id: 'agent-sentinel',
      name: 'Phoenix Sentinel',
      role: 'Hardware & Vulkan Watchdog',
      model: 'Resolvido pelo catálogo local',
      status: 'IDLE',
      avatarColor: '#ff334b',
      systemPrompt: 'Monitora a telemetria disponível e os canais da porta 8000.',
      tasksCompleted: 0,
    },
    {
      id: 'agent-architect',
      name: 'Aviary Architect',
      role: 'Multi-Agent Task Coordinator',
      model: 'Resolvido pelo catálogo local',
      status: 'IDLE',
      avatarColor: '#ffffff',
      systemPrompt: 'Coordinates sub-agent tasks on Port 3000, balancing token pipelines between nodes.',
      tasksCompleted: 0,
    },
    {
      id: 'agent-synthesizer',
      name: 'Code Synthesizer',
      role: 'SPIR-V & Kernel Generator',
      model: 'Resolvido pelo catálogo local',
      status: 'IDLE',
      avatarColor: '#4fa3ff',
      systemPrompt: 'Generates SPIR-V shader pipelines and vector search optimizers.',
      tasksCompleted: 0,
    },
    {
      id: 'agent-rag',
      name: 'Vector Navigator',
      role: 'RAG Knowledge Specialist',
      model: 'Backend RAG configurado',
      status: 'IDLE',
      avatarColor: '#37d67a',
      systemPrompt: 'Consulta os documentos que estiverem realmente indexados no RAG.',
      tasksCompleted: 0,
    }
  ]);

  // PHX-FIX (auditoria completa, achado #3 do LEIA-ME): eram 4 documentos
  // fake hardcoded (vulkan_compute_kernels_revival.md e outros, nem
  // existentes no ChromaDB de verdade). Com o typo _rag_backend -> rag_backend
  // corrigido em phoenix_kernel/models/engine.py, o efeito de sync abaixo
  // agora recebe os documentos reais do /api/state e substitui isto -
  // começa vazio em vez de mostrar dado fabricado até a primeira resposta
  // chegar.
  const [documents, setDocuments] = useState<RagDocument[]>([]);

  const [terminalLogs, setTerminalLogs] = useState<TerminalEntry[]>([
    { id: '1', type: 'info', text: 'Aguardando o estado e os logs reais do Phoenix Engine na porta 8000…', timestamp: '' }
  ]);

  const [telemetry, setTelemetry] = useState<TelemetryPoint[]>(
    // Inicializa com zeros — substituídos pelos dados reais do backend em 3s
    Array.from({ length: 8 }, (_, i) => ({
      time: String(i + 1), tps: 0, cpuUsage: 0, gpuUsage: 0,
      port8000Load: 0, port3000Load: 0, vramUsedMB: 0,
    }))
  );

  const [clock, setClock] = useState('');
  const [uptimeSeconds, setUptimeSeconds] = useState(0);
  // PHX-FIX (pedido do usuário 2026-08-22: "deixar botao STRESS habilitado
  // por padrao porque deixa 8000 e 3000 conectadas por definição"): este
  // toggle é só um destaque visual local no gráfico de telemetria (ver o
  // handler do comando 'stress' abaixo - não existe rota real no backend, o
  // texto já documenta isso) e não controla de fato o ping de portas 8000/
  // 3000 (isso é PortBridgePanel.tsx, independente). Por pedido explícito do
  // usuário o padrão passa a ser ligado; o botão em Header.tsx continua
  // podendo desligar manualmente quando quiser.
  const [stressActive, setStressActive] = useState(true);
  // PHX-NEW (varredura 2026-08-21, achado 1.2): null = ainda não checado
  // (backend não respondeu desde que a página abriu); true/false = leitura
  // real de env.vulkan (ver fetchState abaixo).
  const [vulkanDetected, setVulkanDetected] = useState<boolean | null>(null);

  // PHX-FIX: busca dados reais do backend a cada 3s em vez de gerar com Math.random().
  // O estado inicial fica vazio/neutro; a UI só mostra valores reais quando chegam.
  useEffect(() => {
    let cancelled = false;
    const fetchState = async () => {
      try {
        const res = await fetch('/api/state');
        if (!res.ok || cancelled) return;
        const data = await res.json();

        // Telemetria real do AHDE
        const tel = data.telemetry || {};
        const now = new Date();
        const newTps = typeof tel.tps === 'number' ? tel.tps : 0;
        setInference(prev => ({
          ...prev,
          tps: newTps,
          vramUsedMB: typeof tel.gpu_vram_used === 'number' ? tel.gpu_vram_used : prev.vramUsedMB,
          ramUsedMB: typeof tel.ram_used_mb === 'number' ? tel.ram_used_mb : prev.ramUsedMB,
        }));
        setTelemetry(prev => {
          const next = [...prev.slice(1), {
            time: now.getSeconds().toString(),
            tps: newTps,
            cpuUsage: typeof tel.cpu_usage === 'number' ? tel.cpu_usage : 0,
            gpuUsage: typeof tel.gpu_load === 'number' ? tel.gpu_load : 0,
            port8000Load: 0,
            port3000Load: 0,
            vramUsedMB: typeof tel.gpu_vram_used === 'number' ? tel.gpu_vram_used : 0,
          }];
          return next;
        });

        // Hardware real do discovery
        const hw = data.hardware || {};
        // PHX-FIX (varredura 2026-08-21, achado 1.2): temperatureC nunca era
        // atualizado aqui - HardwareDrawer.tsx mostrava pra sempre o valor
        // fixo do preset (HARDWARE_PRESETS), nunca a leitura real de
        // TelemetryEngine (sensors -j). Agora usa tel.gpu_temp (já
        // calculado acima, real) quando disponível.
        if (hw.gpu || hw.cpu || typeof tel.gpu_temp === 'number') {
          setHardware(prev => ({
            ...prev,
            cpu: hw.cpu || prev.cpu,
            gpu: hw.gpu || prev.gpu,
            vramTotalMB: typeof hw.vram_mb === 'number' ? hw.vram_mb : prev.vramTotalMB,
            ramTotalMB: typeof hw.ram_mb === 'number' ? hw.ram_mb : prev.ramTotalMB,
            vram: typeof hw.vram_mb === 'number' ? `${hw.vram_mb} MB` : prev.vram,
            ram: typeof hw.ram_mb === 'number' ? `${hw.ram_mb} MB` : prev.ram,
            backend: Array.isArray(hw.backends) && hw.backends.length ? hw.backends.join(' / ').toUpperCase() : prev.backend,
            gpuScore: typeof data.score === 'number' ? data.score : prev.gpuScore,
            ramScore: typeof data.score === 'number' ? data.score : prev.ramScore,
            temperatureC: typeof tel.gpu_temp === 'number' ? tel.gpu_temp : prev.temperatureC,
          }));
        }

        // Serviços reais do environment - ver SERVICE_ENV_KEYS (mapeamento
        // explícito, substitui a transformação de string frágil que não
        // batia com a maioria das chaves reais do backend).
        const env = data.environment || {};
        if (Object.keys(env).length > 0) {
          setServices(prev => prev.map(s => {
            const key = SERVICE_ENV_KEYS[s.name];
            if (!key) return s; // sem correspondência real conhecida (ex: FILESYSTEM) - não mexe
            const isOnline = env[key] === true;
            return { ...s, status: isOnline ? 'online' : 'offline' };
          }));
          // PHX-FIX (varredura 2026-08-21, achado 1.2): "VULKAN API STATUS"
          // em HardwareDrawer.tsx mostrava "v1.3.275 [OK]" fixo sempre -
          // agora usa env.vulkan real (ServicesEngine.get_environment_
          // status(), shutil.which("vulkaninfo")). É uma checagem de
          // presença do binário, não uma verificação completa de
          // capacidade Vulkan - documentado como tal na própria UI.
          if (typeof env.vulkan === 'boolean') {
            setVulkanDetected(env.vulkan);
          }
        }

        // Linhas de PORT 8000/3000 em `services` são as mesmas 2 portas já
        // pingadas de verdade em `ports` (pingBridge, 1x/s) - sincroniza
        // daqui em vez de manter uma cópia congelada separada.
        setServices(prev => prev.map(s => {
          const portEntry = PORT_SERVICE_NAMES[s.name];
          if (portEntry === undefined) return s;
          const port = ports.find(p => p.port === portEntry);
          if (!port) return s;
          const status = port.status === 'ONLINE' ? 'online' : port.status === 'ERROR' ? 'offline' : 'idle';
          return { ...s, status };
        }));

        // Documentos RAG reais do ChromaDB
        // PHX-FIX (achado #3 do LEIA-ME): o guard `ragDocs.length > 0` fazia
        // sentido só enquanto o backend nunca respondia (bug do
        // _rag_backend, corrigido em models/engine.py) - com isso corrigido,
        // uma coleção real vazia (ou depois de deletar o último doc) tem
        // que conseguir zerar a lista também, não só popular quando > 0.
        // 1536 hardcoded como default trocado por 384 (dimensão real do
        // all-MiniLM-L6-v2 em uso, ver ChromaRagBackend).
        const ragDocs = data.rag_documents;
        if (Array.isArray(ragDocs)) {
          setDocuments(ragDocs.map((d: any, idx: number) => ({
            id: d.id || String(idx),
            title: d.title || d.id || `doc_${idx}`,
            sizeKb: typeof d.sizeKb === 'number' ? d.sizeKb : 0,
            chunks: typeof d.chunks === 'number' ? d.chunks : 1,
            dateAdded: d.dateAdded || '',
            status: 'INDEXED' as const,
            vectorDimensions: d.vectorDimensions || 384,
            sourceType: d.sourceType || 'DOC',
          })));
        }

        // Logs de boot reais do kernel Python
        const bootLog = data.boot_log;
        if (Array.isArray(bootLog) && bootLog.length > 0) {
          setTerminalLogs(bootLog.map((entry: any, idx: number) => ({
            id: String(idx),
            type: entry.level === 'ERROR' ? 'err' : entry.level === 'WARNING' ? 'info' : 'sys',
            text: `[${entry.source}] ${entry.message}`,
            timestamp: entry.timestamp || '',
          })));
        }

        // Uptime do estado real
        if (data.uptime_seconds && typeof data.uptime_seconds === 'number') {
          setUptimeSeconds(data.uptime_seconds);
        }
      } catch {
        // Backend offline — mantém os valores anteriores sem resetar pra zero
      }
    };

    fetchState();
    const interval = setInterval(fetchState, 3000);
    // Relógio local (não depende do backend)
    const clockTimer = setInterval(() => {
      setClock(new Date().toLocaleTimeString('pt-BR', { hour12: false }));
      // Incrementa uptime só se não veio do backend
      setUptimeSeconds(prev => prev + 1);
    }, 1000);

    return () => {
      cancelled = true;
      clearInterval(interval);
      clearInterval(clockTimer);
    };
  }, [stressActive]);

  const formatUptime = (sec: number) => {
    const hrs = Math.floor(sec / 3600);
    const mins = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return `${hrs}h ${mins}m ${s}s`;
  };

  const handleExecuteCommand = async (commandText: string) => {
    const trimmed = commandText.trim();
    if (!trimmed) return;

    const userLog: TerminalEntry = {
      id: Date.now().toString(),
      type: 'cmd',
      text: trimmed,
      timestamp: new Date().toLocaleTimeString()
    };

    setTerminalLogs(prev => [...prev, userLog]);

    if (trimmed.toLowerCase() === 'clear' || trimmed.toLowerCase() === 'cls') {
      setTerminalLogs([]);
      return;
    }

    if (trimmed.toLowerCase() === 'stress') {
      // PHX-FIX (auditoria completa — "tirar todos os fallbacks"): o texto
      // alegava "Port 8000 compute queue utilization set to 100%" como se
      // este comando de fato mudasse a carga real do Phoenix Engine — não
      // existe rota nenhuma no backend pra isso (grep em
      // phoenix_kernel/api/engine.py confirma que 'stress' não é um
      // comando real do kernel). É só um destaque visual local no gráfico
      // de telemetria (ver TelemetryWave.tsx / stressActive), sem nenhuma
      // chamada de rede. O log agora descreve o que de fato acontece.
      setStressActive(prev => !prev);
      const state = !stressActive ? 'ATIVADO' : 'DESATIVADO';
      setTerminalLogs(prev => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          type: 'ok',
          text: `[DESTAQUE VISUAL LOCAL ${state}] Realce de pico no gráfico de telemetria (não altera nada no Phoenix Engine — porta 8000 não tem comando 'stress' real).`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
      return;
    }

    // PHX-FIX (auditoria completa — "tirar todos os fallbacks"): o catch
    // abaixo mostrava "[OFFLINE FALLBACK] Command '...' acknowledged. Port
    // 8000 & 3000 running in self-contained node mode." — fingindo que o
    // comando foi reconhecido/executado mesmo quando a chamada real falhou
    // (Phoenix Engine offline, timeout, erro HTTP). Isso escondia a falha
    // real atrás de uma resposta de sucesso genérica. Agora mostra o erro
    // real devolvido pelo servidor (server.ts não fabrica mais um
    // terminal falso quando o Engine está offline — ver /api/command).
    try {
      const res = await fetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: trimmed })
      });

      const data = await res.json().catch(() => ({}));

      if (!res.ok || data.error) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }

      const outputLog: TerminalEntry = {
        id: (Date.now() + 2).toString(),
        type: 'sys',
        text: data.output || '',
        timestamp: new Date().toLocaleTimeString()
      };

      setTerminalLogs(prev => [...prev, outputLog]);
    } catch (err: any) {
      setTerminalLogs(prev => [
        ...prev,
        {
          id: (Date.now() + 3).toString(),
          type: 'err',
          text: `[ERRO] ${err?.message || 'Falha ao executar o comando.'}`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    }
  };

  // PHX-FIX (auditoria completa, achado #2 do LEIA-ME - mesma classe de bug
  // do /api/benchmark, aplicada aqui por consistência): isto era 100%
  // fabricado no cliente - dois setTimeout despejando linhas de log
  // pré-escritas ("Matrix multiplication 4096x4096x4096... [OK] (3.8ms)")
  // e um score fixo de 87.4%, sem NENHUMA chamada de rede. Pior que o
  // /api/benchmark original: nem passava pelo servidor, o "resultado" já
  // vinha escrito no componente. Agora chama o endpoint real (mesmo
  // POST /api/benchmark que mede tokens/s de verdade via kernel.runtime) e
  // mostra o log real, incluindo falha real se a inferência não completar.
  // gpuScore não é mais sobrescrito com um número inventado - ele continua
  // refletindo o preset de hardware selecionado (HardwareDrawer.tsx), que é
  // dado de referência rotulado, não uma medição ao vivo.
  const handleRunBenchmark = async () => {
    setIsBenchmarking(true);
    setBenchmarkLog(['Disparando inferência curta real via Port 8000 (kernel.runtime)...']);

    try {
      const res = await fetch('/api/benchmark', { method: 'POST' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        setBenchmarkLog(prev => [...prev, `[FALHOU] ${data.error || `HTTP ${res.status}`}`]);
        return;
      }
      const r = data.results || {};
      setBenchmarkLog(prev => [
        ...prev,
        `Runtime: ${r.runtime || '?'} / Modelo: ${r.model || '?'}`,
        `Tokens gerados: ${r.tokensGenerated ?? '?'} em ${r.durationMs ?? '?'}ms`,
        `Throughput medido: ${r.tokensPerSec ?? '?'} tokens/s`,
        data.note || '',
      ]);
    } catch (e: any) {
      setBenchmarkLog(prev => [...prev, `[FALHOU] ${e?.message || e}`]);
    } finally {
      setIsBenchmarking(false);
    }
  };

  // PHX-FIX (auditoria completa, achado #3 do LEIA-ME): antes isto era
  // 100% fabricação local - nunca chamava o backend, inventava
  // `chunks: Math.floor(sizeKb/8)+4` e `vectorDimensions: 1536`, e ainda
  // fingia no log que tinha sido "loaded into Port 8000 Vector DB" sem
  // nenhuma chamada de rede. Agora chama POST /api/rag de verdade (que por
  // sua vez chama POST /api/rag/add no Python -> ChromaRagBackend.add_document)
  // e só atualiza o estado/log a partir da resposta real do backend. Em
  // caso de falha, mostra o erro real no terminal em vez de fingir sucesso.
  const handleAddDocument = async (title: string, content: string, type: 'PDF' | 'MD' | 'CODE' | 'TXT') => {
    try {
      const res = await fetch('/api/rag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, content, sourceType: type }),
      });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      const doc = data.doc as RagDocument;
      setDocuments(prev => [doc, ...prev.filter(d => d.id !== doc.id)]);
      setTerminalLogs(prev => [
        ...prev,
        {
          id: Date.now().toString(),
          type: 'ok',
          text: `[RAG INDEXED] ${doc.title} (${doc.sizeKb} KB, ${doc.chunks} chunk) loaded into ChromaDB via Port 8000.`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    } catch (e: any) {
      setTerminalLogs(prev => [
        ...prev,
        {
          id: Date.now().toString(),
          type: 'err',
          text: `[RAG INDEX FAILED] '${title}': ${e?.message || e}`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    }
  };

  const handleAddRagFile = async (file: File) => {
    const form = new FormData();
    form.append('file', file, file.name);
    const res = await fetch('/api/rag/add-file', { method: 'POST', body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.success) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    const doc = data.doc as RagDocument;
    setDocuments(prev => [doc, ...prev.filter(d => d.id !== doc.id)]);
    setTerminalLogs(prev => [...prev, {
      id: Date.now().toString(),
      type: 'ok',
      text: `[RAG INDEXED] ${doc.title}: ${doc.chunks} chunk(s) reais${data.ocr_used ? ' via OCR' : ''}.`,
      timestamp: new Date().toLocaleTimeString(),
    }]);
  };

  // PHX-FIX (mesmo achado): antes só filtrava do estado local
  // (setDocuments(prev => prev.filter(...))) - o documento continuava no
  // ChromaDB pra sempre e reaparecia no próximo poll de /api/state. Agora
  // chama DELETE /api/rag/:id de verdade e só remove da UI se o backend
  // confirmar.
  const handleDeleteDocument = async (id: string) => {
    try {
      const res = await fetch(`/api/rag/${encodeURIComponent(id)}`, { method: 'DELETE' });
      const data = await res.json();
      if (!res.ok || !data.success) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      setDocuments(prev => prev.filter(d => d.id !== id));
    } catch (e: any) {
      setTerminalLogs(prev => [
        ...prev,
        {
          id: Date.now().toString(),
          type: 'err',
          text: `[RAG DELETE FAILED] '${id}': ${e?.message || e}`,
          timestamp: new Date().toLocaleTimeString()
        }
      ]);
    }
  };

  // PHX-FIX (Aviary Swarm virar real): antes isto era 100% simulação local
  // - nenhuma chamada de rede, um setTimeout de 2.5s sempre "completava" a
  // tarefa com uma citação fabricada ("Completed task on Port 8000: ..."),
  // e `tasksCompleted` já era incrementado no disparo, antes de qualquer
  // execução real. server.ts já tinha (e continua tendo) um proxy real
  // para POST /api/agents/dispatch. O que faltava era o Python: agora
  // api_server.py expõe essa rota de verdade, chamando
  // resident.dispatch_agent_task_direct() (ver resident_manager.py), que
  // roteia cada persona pra uma capacidade real do kernel (análise de
  // hardware, planejamento via LLM, inferência de código, busca RAG).
  // O corpo enviado usa `agent_id` (snake_case) porque é isso que o
  // Pydantic AgentDispatchReq do lado Python espera - antes esta função
  // mandava `agentId` (camelCase), que nunca bateria com o schema real.
  const handleDispatchAgentTask = async (agentId: string, taskText: string) => {
    setAgents(prev => prev.map(a => {
      if (a.id === agentId) {
        return {
          ...a,
          status: 'DISPATCHING',
          latestThought: `Dispatching payload to Port 8000: "${taskText.slice(0, 40)}..."`
        };
      }
      return a;
    }));

    setTerminalLogs(prev => [
      ...prev,
      {
        id: Date.now().toString(),
        type: 'agent',
        text: `[AVIARY SWARM // PORT 3000] Task dispatched to ${agentId}: "${taskText}"`,
        timestamp: new Date().toLocaleTimeString()
      }
    ]);

    try {
      const res = await fetch('/api/agents/dispatch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, task: taskText }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.error) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }

      // Cada persona devolve um formato de saída um pouco diferente
      // (ver dispatch_agent_task_direct no ResidentManager) - `output` é
      // o texto comum a todas; algumas acrescentam campos extras reais
      // (model/metrics no Synthesizer, hits no Navigator) que vale
      // anexar ao thought em vez de descartar.
      let thought: string = data.output || `Agente ${agentId} concluiu sem texto de retorno.`;
      if (data.model) thought += `\n[modelo: ${data.model}]`;
      if (Array.isArray(data.hits)) thought += `\n[${data.hits.length} resultado(s) RAG]`;

      setAgents(prev => prev.map(a => {
        if (a.id === agentId) {
          return {
            ...a,
            status: 'ACTIVE',
            tasksCompleted: a.tasksCompleted + 1,
            latestThought: thought,
          };
        }
        return a;
      }));

      setTerminalLogs(prev => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          type: 'agent',
          text: `[AVIARY SWARM // PORT 3000] ${agentId} concluiu: "${(data.output || '').slice(0, 160)}"`,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
    } catch (err: any) {
      setAgents(prev => prev.map(a => {
        if (a.id === agentId) {
          return {
            ...a,
            status: 'ERROR',
            latestThought: `[FALHOU] ${err?.message || 'endpoint indisponível'}`,
          };
        }
        return a;
      }));
      setTerminalLogs(prev => [
        ...prev,
        {
          id: (Date.now() + 1).toString(),
          type: 'err',
          text: `[AVIARY SWARM // PORT 3000] Falha ao despachar tarefa para ${agentId}: ${err?.message || 'endpoint indisponível'}`,
          timestamp: new Date().toLocaleTimeString(),
        },
      ]);
    }
  };

  return (
    <div className="w-full h-full flex flex-col bg-[#0b0d10] text-[#e7e7e7] font-mono overflow-hidden select-none">
      
      {/* 1. Header with Red & White Theme */}
      <Header
        uptime={formatUptime(uptimeSeconds)}
        clock={clock}
        ports={ports}
        activeView={activeView}
        setActiveView={setActiveView}
        onOpenHardware={() => setHardwareDrawerOpen(true)}
        onOpenRag={() => setRagDrawerOpen(true)}
        onOpenSystemReport={() => setSystemReportOpen(true)}
        stressActive={stressActive}
        onToggleStress={() => setStressActive(prev => !prev)}
        onOpenStandalone={onOpenStandalone}
      />

      {/* 2. Metric Datacenter Cards Grid */}
      <MetricCards
        hardware={hardware}
        inference={inference}
        services={services}
        ragCount={documents.length}
        agentCount={agents.length}
        onOpenHardware={() => setHardwareDrawerOpen(true)}
        onOpenRag={() => setRagDrawerOpen(true)}
        onOpenSwarm={() => setActiveView('swarm')}
        onOpenPorts={() => setActiveView('ports')}
      />

      {/* 3. Realtime Telemetry Waveform Bar */}
      <TelemetryWave
        telemetry={telemetry}
        currentTps={inference.tps}
        stressActive={stressActive}
      />

      {/* 4. Active Main Content Deck */}
      <div className="flex-grow flex flex-col min-h-0 relative">
        {activeView === 'dashboard' && (
          <TerminalConsole
            logs={terminalLogs}
            onExecuteCommand={handleExecuteCommand}
            onClearLogs={() => setTerminalLogs([])}
          />
        )}

        {activeView === 'ports' && (
          <div className="flex-grow p-4 md:p-6 overflow-y-auto bg-[#08090b]">
            <PortBridgePanel
              ports={ports}
              packets={bridgePackets}
              onManualPing={pingBridge}
              onTriggerCommand={handleExecuteCommand}
              agentCount={agents.length}
            />
          </div>
        )}

        {activeView === 'swarm' && (
          <div className="flex-grow p-4 md:p-6 overflow-y-auto bg-[#08090b]">
            <AviarySwarmPanel
              agents={agents}
              onDispatchTask={handleDispatchAgentTask}
              onTriggerCommand={handleExecuteCommand}
            />
          </div>
        )}
      </div>

      {/* 5. Datacenter Mission Control Footer */}
      <footer className="px-4 md:px-8 py-2 border-t border-[#262d35] bg-[#14181d] text-[11px] text-[#8d98a5] tracking-wider uppercase flex flex-col sm:flex-row items-center justify-between gap-2 flex-shrink-0">
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${ports.find(p => p.port === 8000)?.status === 'ONLINE' ? 'bg-[#37d67a]' : 'bg-[#8d98a5]'}`}></span>
          <span className="text-white font-bold">AIVISIONSLAB STUDIO GROUP</span>
          <span>// PHOENIX ENGINE v4.5 (PORTA :8000)</span>
        </div>
        <div className="text-[10px] text-[#8d98a5]">
          LOCAL-FIRST AI ORCHESTRATION • CC BY-NC 4.0
        </div>
      </footer>

      {/* 6. Side Drawers */}
      <HardwareDrawer
        isOpen={hardwareDrawerOpen}
        onClose={() => setHardwareDrawerOpen(false)}
        currentProfile={hardware}
        onSelectProfile={(p) => setHardware(p)}
        onRunBenchmark={handleRunBenchmark}
        isBenchmarking={isBenchmarking}
        benchmarkLog={benchmarkLog}
        vulkanDetected={vulkanDetected}
      />

      <RagDrawer
        isOpen={ragDrawerOpen}
        onClose={() => setRagDrawerOpen(false)}
        documents={documents}
        onAddDocument={handleAddDocument}
        onAddFile={handleAddRagFile}
        onDeleteDocument={handleDeleteDocument}
      />

      <SystemReportModal
        isOpen={systemReportOpen}
        onClose={() => setSystemReportOpen(false)}
      />

    </div>
  );
};
