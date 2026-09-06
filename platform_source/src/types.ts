export type ProviderType = 
  | 'gemini' 
  | 'ollama' 
  | 'lmstudio' 
  | 'llama-server' 
  | 'vllm' 
  | 'localai' 
  | 'koboldcpp' 
  | 'tgi' 
  | 'jan' 
  | 'sglang' 
  | 'open-webui' 
  | 'anythingllm' 
  | 'openai' 
  | 'anthropic' 
  | 'piper-tts'
  | 'custom';

// PHX-NEW (2026-08-23): era PiperVoice (uma voz = um par de arquivos .onnx
// baixado do Hugging Face). Kokoro-82M compartilha UM modelo entre todas as
// vozes/idiomas, então os campos específicos de arquivo (onnxModel,
// downloadUrl, sampleRate, quality) não fazem mais sentido - só sobra o
// necessário pra listar opções no seletor da UI.
export interface TtsVoiceOption {
  id: string;
  name: string;
  language: string;
  gender: 'male' | 'female' | 'n/a';
  description: string;
}

export interface ProviderConfig {
  id: string;
  name: string;
  type: ProviderType;
  baseUrl: string;
  apiKey?: string;
  enabled: boolean;
  status: 'connected' | 'disconnected' | 'testing' | 'error';
  latencyMs?: number;
  models: string[];
  lastChecked?: string;
}

export interface ModelInfo {
  id: string;
  name: string;
  providerType: ProviderType;
  providerId: string;
  contextWindow: number;
  parameterSize?: string;
  description?: string;
  supportsVision?: boolean;
  supportsThinking?: boolean;
}

export interface SystemPromptPreset {
  id: string;
  title: string;
  category: 'General' | 'Coding' | 'Reasoning' | 'Creative' | 'Productivity';
  prompt: string;
  description: string;
}

export interface ChatParameters {
  temperature: number;
  topP: number;
  topK: number;
  maxTokens: number;
  contextWindow: number;
  repeatPenalty: number;
  systemInstruction: string;
  showThinking: boolean;
  // PHX-FIX (auditoria completa 2026-08-28, gap de privacidade real): até
  // aqui, o contexto do RAG (trechos dos SEUS documentos indexados) era
  // anexado ao systemInstruction em TODA chamada de chat, pra qualquer
  // provedor selecionado - inclusive um provedor de nuvem (hoje só
  // 'gemini', ver ChatParameters -> sendToProvider em AviaryApp.tsx), sem
  // nenhum aviso ou opção de desligar isso. Default `true`: por padrão,
  // texto dos seus documentos NUNCA sai da sua máquina via RAG - só é
  // enviado a um provedor de nuvem se você desligar esta trava
  // explicitamente em Parâmetros. Provedores locais (Ollama, llama-server,
  // LM Studio) nunca são afetados por esta flag - o RAG sempre funciona
  // neles, porque o contexto já fica 100% na sua máquina.
  blockRagOnCloudProviders: boolean;
}

export interface AttachedFile {
  id: string;
  name: string;
  size: number;
  type: string;
  content: string;
  isImage: boolean;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  thinking?: string;
  timestamp: string;
  modelId?: string;
  providerType?: ProviderType;
  image?: string;
  files?: AttachedFile[];
  metrics?: {
    promptTokens?: number;
    completionTokens?: number;
    durationMs?: number;
    tokensPerSec?: number;
  };
  error?: string;
  // PHX-NEW (auditoria platform_source 2026-08-20, achado A3): resultado de
  // /api/documents/edit e /api/documents/create (arquivo materializado em
  // base64) anexado a uma mensagem de assistente, pra renderizar um link de download real na UI
  // - ver ChatView.tsx.
  downloadFile?: {
    name: string;
    base64: string;
    mimeType: string;
  };
  // PHX-FIX (achado real do usuário 2026-08-24: perguntou "seu nome e
  // modelo?" pro qwen3-8b e ele respondeu "Nome: Phoenix Aviary Platform...
  // Modelo: Flux 1-Schnell" - um modelo de TEXTO se identificando como o
  // motor de IMAGEM usado na mensagem anterior): mensagens de role
  // 'assistant' que na verdade são AVISOS DE UI sobre uma ação de um
  // subsistema LOCAL separado (imagem gerada, colaboração entre dois
  // outros modelos, documento editado) - não são o modelo de texto
  // "falando" - nunca deveriam ser reenviadas como histórico de conversa
  // pro provedor de texto (sendToProvider em AviaryApp.tsx filtra por este
  // campo). Sem isso, o LLM vê seu próprio "turno" anterior dizendo
  // "Imagem gerada com flux1-schnell" e, combinado com o system prompt
  // ("Você é a Phoenix Aviary Platform"), conclui plausivelmente que ELE é
  // o Flux 1-Schnell. Continuam aparecendo normalmente na tela (React
  // state), só não voltam pro provedor de texto como se fossem falas dele.
  excludeFromHistory?: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  modelId: string;
  providerType: ProviderType;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
  parameters: ChatParameters;
}

export interface ArenaSlot {
  id: string;
  modelId: string;
  providerType: ProviderType;
  providerId: string;
  isLoading: boolean;
  currentResponse: string;
  thinking?: string;
  metrics?: {
    durationMs?: number;
    tokensPerSec?: number;
    promptTokens?: number;
    completionTokens?: number;
  };
  error?: string;
}

export interface HubModel {
  id: string;
  name: string;
  org: string;
  params: string;
  tags: string[];
  description: string;
  context: string;
  license: string;
  ollamaCommand: string;
  huggingFaceUrl: string;
  ggufSizes: {
    quant: string;
    sizeGb: number;
    ramRecommendedGb: number;
    qualityRating: number;
  }[];
  supportsVision?: boolean;
  supportsReasoning?: boolean;
}

// Engine Specific Types
export interface HardwareProfile {
  id: string;
  name: string;
  cpu: string;
  ram: string;
  ramTotalMB: number;
  gpu: string;
  vram: string;
  vramTotalMB: number;
  backend: string;
  driver: string;
  gpuScore: number;
  ramScore: number;
  temperatureC: number;
  fanSpeedPercent: number;
}

export interface EnvironmentService {
  name: string;
  status: 'online' | 'warning' | 'offline' | 'idle';
  detail: string;
  port?: number;
}

export interface InferenceConfig {
  backend: 'OLLAMA' | 'LLAMA.CPP' | 'VULKAN_NATIVE' | 'OPENAI_CLOUD';
  model: string;
  quantization: string;
  contextWindow: number;
  tps: number;
  vramUsedMB: number;
  ramUsedMB: number;
  batchSize: number;
  threads: number;
}

export interface PortNode {
  port: number;
  label: string;
  service: string;
  status: 'ONLINE' | 'ACTIVE' | 'STANDBY' | 'ERROR';
  // PHX-FIX (auditoria completa — "tirar todos os fallbacks", achado do
  // ping falso em PortBridgePanel.tsx): `requestsTotal` e `throughputKbps`
  // eram números fixos desde a inicialização (34120/89450 requests,
  // 420.5/850.4 Kbps), nunca atualizados por nada, e nem sequer eram
  // renderizados em lugar nenhum da UI - dado morto e fabricado ao mesmo
  // tempo. `latencyMs` continua aqui porque agora é real (ver
  // EngineMissionControl.tsx: medido via performance.now() contra
  // /api/ping e /api/health a cada 1s).
  latencyMs: number;
  endpoint: string;
  protocol: 'HTTP/REST' | 'WEBSOCKET' | 'VULKAN_RPC';
  description: string;
}

// PHX-NEW (fix real do "Live Inter-Port Packet Inspector"): antes disso
// era `Array<{...}>` inline em PortBridgePanel.tsx, inicializado com 4
// pacotes fabricados na primeira renderização e nunca mais atualizado
// (sem setInterval nenhum, apesar do rótulo "Stream Auto-Refresh:
// 1000ms"). Agora é alimentado de verdade por EngineMissionControl.tsx,
// que faz 1 ping real por segundo (GET /api/ping local + GET /api/health
// via Python) e empurra o resultado real aqui.
export interface BridgePacket {
  id: string;
  time: string;
  from: number;
  to: number;
  type: string;
  payload: string;
  status: number;
}

export interface AviaryAgent {
  id: string;
  name: string;
  role: string;
  model: string;
  status: 'ACTIVE' | 'IDLE' | 'THINKING' | 'DISPATCHING' | 'ERROR';
  avatarColor: string;
  systemPrompt: string;
  tasksCompleted: number;
  currentTask?: string;
  latestThought?: string;
}

export interface RagDocument {
  id: string;
  title: string;
  sizeKb: number;
  chunks: number;
  dateAdded: string;
  // PHX-FIX (auditoria completa, achado #3 do LEIA-ME): faltava um estado
  // honesto pra quando a indexação falha - antes disso a UI só sabia
  // mostrar 'INDEXED', então até uma falha de rede/backend virava o mesmo
  // badge verde de sucesso.
  status: 'INDEXED' | 'EMBEDDING' | 'READY' | 'ERROR';
  vectorDimensions: number;
  sourceType: 'PDF' | 'MD' | 'CODE' | 'TXT' | 'API';
}

export interface TerminalEntry {
  id: string;
  type: 'sys' | 'ok' | 'err' | 'cmd' | 'info' | 'agent' | 'vulkan' | 'port';
  text: string;
  timestamp: string;
  source?: 'engine' | 'aviary' | 'system' | 'user';
}

export interface TelemetryPoint {
  time: string;
  tps: number;
  cpuUsage: number;
  gpuUsage: number;
  port8000Load: number;
  port3000Load: number;
  vramUsedMB: number;
}

export type ActiveProcessView = 'aviary' | 'engine' | 'split';

// ============================================================
// AHDE — Tipos de sensores, dispositivos e eventos (PHX-NEW Gemini 2026-09-01)
// Usados por HardwareDrawer.tsx para polling de /api/ahde/sensors,
// /api/ahde/events e /api/ahde/snapshot
// ============================================================

export interface AhdeSensor {
  id: string;
  name: string;
  category: 'cpu' | 'gpu' | 'memory' | 'motherboard' | 'storage' | 'network' | 'power';
  type: 'Temperature' | 'Load' | 'Power' | 'Clock' | 'Voltage' | 'Fan' | 'Data' | 'SmallData' | 'Status';
  value: number | string;
  unit?: string;
  min?: number;
  max?: number;
  criticalThreshold?: number;
  warningThreshold?: number;
  device: string;
  updatedAt?: string;
}

export interface AhdeDevice {
  name: string;
  type: string;
  vendor?: string;
  model?: string;
  category: 'cpu' | 'gpu' | 'memory' | 'motherboard' | 'storage';
  sensors: AhdeSensor[];
}

export interface AhdeCapabilitySnapshot {
  vulkan: boolean;
  cuda: boolean;
  rocm: boolean;
  opencl: boolean;
  docker: boolean;
  wsl: boolean;
  virtualization: boolean;
  ollama: boolean;
  llamacpp: boolean;
}

export interface AhdeDiscoveryEvent {
  event_id: string;
  event_type: 'HARDWARE_CHANGED' | 'TELEMETRY_UPDATED' | 'MODELS_CHANGED' | 'SERVICES_CHANGED' | 'HEALTH_CHANGED' | 'CAPABILITY_CHANGED';
  priority: 'HIGH' | 'NORMAL' | 'LOW';
  timestamp: string;
  source: string;
  machine_id: string;
  trace_id: string;
  payload: any;
}

export interface AhdeSnapshotData {
  machine_id: string;
  timestamp: string;
  snapshot_id: string;
  schema_version: string;
  engine_version: string;
  capabilities: AhdeCapabilitySnapshot;
  hardware: Record<string, any>;
  drivers: Record<string, any>;
  services: Record<string, any>;
  models: any[];
  devices: AhdeDevice[];
  telemetry?: Record<string, any> | null;
  health_score: number | null;
  health_status: 'not_calculated' | 'available';
}
