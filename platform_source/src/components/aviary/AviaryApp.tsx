import { useState, useEffect, useMemo, useRef } from 'react';
import { AviaryHeader } from './AviaryHeader';
import { ChatView } from './ChatView';
import { ArenaView } from './ArenaView';
import { ModelHubView } from './ModelHubView';
import { VramCalculatorView } from './VramCalculatorView';
import { EcosystemView } from './EcosystemView';
import { TextToSpeechView } from './TextToSpeechView';
import { ParametersDrawer } from './ParametersDrawer';
import { ProviderSettingsModal } from './ProviderSettingsModal';
import { ManualModal } from './ManualModal';
import { 
  ProviderConfig, 
  Conversation, 
  ChatMessage, 
  ChatParameters, 
  ModelInfo, 
  ArenaSlot,
  AttachedFile 
} from '../../types';
import { SYSTEM_PROMPT_PRESETS } from '../../data/systemPrompts';
import { parseJsonResponse, describeNonJsonError } from '../../services/httpJson';

const DEFAULT_PROVIDERS: ProviderConfig[] = [
  {
    id: 'gemini-main',
    name: 'Google Gemini Cloud API',
    type: 'gemini',
    baseUrl: 'https://generativelanguage.googleapis.com',
    enabled: true,
    status: 'connected',
    latencyMs: 110,
    models: ['gemini-3.6-flash', 'gemini-3.1-pro-preview', 'gemini-3.1-flash-lite'],
  },
  {
    // PHX-FIX (achado real do usuário 2026-08-24, "jogar fora o piper de
    // vez"): o NOME exibido aqui ainda dizia "Piper", mas o motor por trás
    // desta rota é o Kokoro-82M desde 2026-08-23 (ver comentário completo
    // em piperTtsService.ts) - corrigido pra não alegar um motor que não
    // roda mais. `id`/`type`/`baseUrl` continuam com "piper" no nome
    // interno de propósito (não são exibidos ao usuário, e trocar
    // exigiria atualizar todo lugar que compara com essas strings - ver
    // LEIA-ME desta versão pro raciocínio completo).
    id: 'piper-tts-local',
    name: 'Kokoro TTS Neural (CPU Local)',
    type: 'piper-tts',
    baseUrl: '/api/tts/piper',
    enabled: true,
    status: 'connected',
    latencyMs: 12,
    models: ['pt_BR-faber-medium', 'pt_BR-cadu-medium', 'pt_BR-edresson-low', 'en_US-lessac-high', 'en_US-ryan-medium'],
  },
  // PHX-FIX (auditoria 2026-08-20, "existem falhas e fallbacks - rastrear e
  // tirar tudo", evidência real: usuário selecionou "[OLLAMA] qwen3:8b" no
  // seletor de modelo do chat e tomou "Endpoint retornou (404): File Not
  // Found" em transcrição, chat E geração de imagem - achado real via logs
  // de produção, não hipotético): os três provedores locais abaixo (ollama,
  // llama-server, lmstudio) ANTES vinham com `models: [...]` cheio de nomes
  // de exemplo FABRICADOS (nunca verificados contra a máquina do usuário) -
  // esses nomes ficavam selecionáveis no dropdown de chat desde o primeiro
  // render, mesmo com `status: 'disconnected'` (porque `availableModels`
  // abaixo nunca filtrava por status, só por `enabled`). Selecionar um
  // desses nomes fabricados dispara exatamente a classe de erro relatada.
  // `models` agora começa vazio - só é populado por dado real, vindo de
  // handleScanAllProviders()/handleTestProvider() (ambos já consultam a API
  // de verdade do provedor, nunca inventam nome de modelo).
  //
  // PHX-FIX (pedido do usuário 2026-08-22: "alterar o modelo padrao de
  // ollama para llama porque evita erros"): a ORDEM deste array importa e é
  // a causa raiz do próprio bug documentado no parágrafo acima. O auto-
  // seletor de modelo (useEffect mais abaixo, "achado A9") faz
  // `providers.find(p => ... p.status === 'connected')` e usa o PRIMEIRO
  // provedor local conectado que encontrar - com 'ollama-local' listado
  // antes de 'llama-server-local', se as duas conexões locais estivessem
  // de pé ao mesmo tempo o Ollama sempre "ganhava" o default por pura
  // ordem de array, não por preferência nenhuma, reproduzindo o mesmo 404
  // relatado. Trocando a ordem (llama-server primeiro), o llama.cpp/Vulkan
  // nativo passa a ser o default quando ambos estão conectados - sem
  // remover o Ollama como opção manual no dropdown.
  {
    id: 'llama-server-local',
    name: 'llama-server / Vulkan (Porta :8081)',
    type: 'llama-server',
    baseUrl: 'http://localhost:8081/v1',
    enabled: true,
    status: 'disconnected',
    models: [],
  },
  {
    id: 'ollama-local',
    name: 'Ollama (Porta :11434)',
    type: 'ollama',
    baseUrl: 'http://localhost:11434',
    enabled: true,
    status: 'disconnected',
    models: [],
  },
  {
    id: 'lmstudio-local',
    name: 'LM Studio (Porta :1234)',
    type: 'lmstudio',
    baseUrl: 'http://localhost:1234/v1',
    enabled: true,
    status: 'disconnected',
    models: [],
  },
];

const DEFAULT_PARAMETERS: ChatParameters = {
  temperature: 0.7,
  topP: 0.95,
  topK: 40,
  maxTokens: 4096,
  contextWindow: 32768,
  repeatPenalty: 1.1,
  systemInstruction: SYSTEM_PROMPT_PRESETS[0].prompt,
  showThinking: true,
  // PHX-FIX (auditoria completa 2026-08-28): default seguro - RAG nunca vai
  // pra um provedor de nuvem sem o usuário desligar isto de propósito em
  // Parâmetros. Ver comentário completo em types.ts::ChatParameters.
  blockRagOnCloudProviders: true,
};

// PHX-FIX (auditoria completa 2026-08-28): única lista de tipos de provedor
// considerados "nuvem" pra fins de privacidade do RAG - hoje só 'gemini',
// mas centralizado aqui (em vez de checar `=== 'gemini'` espalhado) pra um
// futuro provedor de nuvem (ex: OpenAI, Anthropic via API) cair na mesma
// trava automaticamente, só precisando entrar nesta lista.
const CLOUD_PROVIDER_TYPES: ReadonlySet<string> = new Set(['gemini']);

export const AviaryApp = ({
  onOpenStandalone,
  engineOnline = false,
  hasGeminiKey = false,
  workspacePath = null,
}: {
  onOpenStandalone?: () => void;
  engineOnline?: boolean;
  hasGeminiKey?: boolean;
  // PHX-FIX (achado real do usuário 2026-08-28, ver App.tsx/ProcessLauncherBar.tsx):
  // repassado só pra alimentar o ManualModal abaixo, que trocou o
  // caminho fixo "R:\Phoenix\Workstations\..." pelo caminho real desta
  // instalação.
  workspacePath?: string | null;
}) => {
  const [activeTab, setActiveTab] = useState<'chat' | 'arena' | 'hub' | 'vram' | 'stack' | 'voice'>('chat');
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isParamsOpen, setIsParamsOpen] = useState(false);
  const [isManualOpen, setIsManualOpen] = useState(false);

  const [providers, setProviders] = useState<ProviderConfig[]>(() => {
    try {
      const saved = localStorage.getItem('aviary_providers');
      return saved ? JSON.parse(saved) : DEFAULT_PROVIDERS;
    } catch {
      return DEFAULT_PROVIDERS;
    }
  });

  // PHX-FIX (2026-08-22, achado real - a causa de verdade por trás de TODA
  // a investigação do dia: usuário confirmou, com prova, que o Python
  // (/api/models/chat-gguf), o Node (/api/engine/models) e até o bundle JS
  // já compilado tinham os 5 modelos certos e a lógica de mistura certa -
  // mesmo assim o dropdown persistia mostrando só 1. A causa não estava em
  // NENHUM dos lugares já investigados: handleScanAllProviders() (abaixo)
  // faz a mistura certa e guarda em `providers` - mas logo em seguida,
  // dentro do MESMO scan, chama handleTestProvider() pra cada provider
  // habilitado (ping ao vivo via /api/proxy/ping). handleTestProvider()
  // SEMPRE substituía `p.models` pelo que o ping devolvesse, sem exceção -
  // e o ping do llama-server bate direto em `<baseUrl>/v1/models`, que
  // (ver LlamaCppDriver.start() no Python: sobe com `-m <um arquivo só>`,
  // nunca `--models-dir`) SEMPRE devolve só o modelo atualmente carregado,
  // nunca a lista completa do disco. Resultado: a mistura de 5 modelos era
  // feita, funcionava por uma fração de segundo, e o PRÓPRIO scan a
  // apagava de volta pra 1 modelo, sempre, todas as vezes - por isso
  // nenhum rebuild/cache-fix jamais resolvia, o bug nunca esteve lá.
  //
  // Guarda aqui (fora de estado React, não precisa causar re-render) a
  // última lista de disco conhecida pro llama-server, pra handleTestProvider
  // poder UNIR com o resultado do ping em vez de substituir - Ollama e LM
  // Studio não têm esse problema (a API deles já lista TUDO que está
  // instalado, não só o carregado), então só o llama-server precisa dessa
  // rede de segurança.
  const diskChatModelsRef = useRef<string[]>([]);

  const [parameters, setParameters] = useState<ChatParameters>(() => {
    try {
      const saved = localStorage.getItem('aviary_parameters');
      return saved ? JSON.parse(saved) : DEFAULT_PARAMETERS;
    } catch {
      return DEFAULT_PARAMETERS;
    }
  });

  const [conversations, setConversations] = useState<Conversation[]>(() => {
    try {
      const saved = localStorage.getItem('aviary_conversations');
      return saved ? JSON.parse(saved) : [];
    } catch {
      return [];
    }
  });

  const [activeConversationId, setActiveConversationId] = useState<string | null>(() => {
    try {
      const saved = localStorage.getItem('aviary_conversations');
      if (saved) {
        const parsed = JSON.parse(saved);
        return parsed[0]?.id || null;
      }
    } catch {}
    return null;
  });

  const [selectedModelId, setSelectedModelId] = useState<string>('gemini-3.6-flash');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [isScanning, setIsScanning] = useState<boolean>(false);

  useEffect(() => {
    try {
      // PHX-FIX (auditoria platform_source 2026-08-20, achado A8): antes,
      // `providers` inteiro (ProviderConfig[], que inclui `apiKey?: string`
      // pra provedores customizados/OpenAI-compatíveis) ia pro localStorage
      // sem filtro nenhum - chave de API ficava salva em texto claro no
      // navegador, legível por qualquer extensão ou script com acesso ao
      // localStorage da origem. Chave nunca é persistida por padrão agora;
      // fica só em memória (`providers` no estado do React) pela duração da
      // aba/sessão - o usuário reconfigura ao reabrir, mesma UX de qualquer
      // app que trata credencial como sensível.
      const providersWithoutKeys = providers.map(({ apiKey: _apiKey, ...rest }) => rest);
      localStorage.setItem('aviary_providers', JSON.stringify(providersWithoutKeys));
    } catch {}
  }, [providers]);

  useEffect(() => {
    try {
      localStorage.setItem('aviary_parameters', JSON.stringify(parameters));
    } catch {}
  }, [parameters]);

  useEffect(() => {
    try {
      localStorage.setItem('aviary_conversations', JSON.stringify(conversations));
    } catch {}
  }, [conversations]);

  const availableModels: ModelInfo[] = useMemo(() => {
    const list: ModelInfo[] = [];
    providers.forEach((p) => {
      if (!p.enabled) return;
      // PHX-FIX (2026-08-23, pedido do usuário: "retirar/bloquear o
      // caminho piper/tts da caixa de diálogo/seleção - esse caminho só
      // pra chatbot ou modelos híbridos de chatbot/imagens/OCR"): antes,
      // 'piper-tts' só ficava de fora da checagem de `status === 'connected'`
      // logo abaixo - mas nada impedia as 5 VOZES do Piper (nomes tipo
      // "pt_BR-faber-medium") de entrarem na lista final como se fossem
      // modelos de chat selecionáveis. Resultado real visto pelo usuário:
      // o seletor MODELO (o que decide quem responde no chat) mostrava
      // "[PIPER-TTS] pt_BR-faber-medium" ao lado de "[LLAMA-SERVER]
      // Qwen3-4B" - uma voz de síntese de fala não tem absolutamente
      // nenhuma capacidade de gerar texto/responder chat, e selecioná-la
      // ali quebraria a conversa. Vozes Piper já têm seletor dedicado e
      // correto (VOZ PIPER, ao lado deste) - não pertencem também aqui.
      // Por isso 'piper-tts' agora é excluído por completo desta lista,
      // não só da checagem de status.
      if (p.type === 'piper-tts') return;

      // PHX-FIX (auditoria 2026-08-20, mesma seção do achado acima): esta
      // função montava o dropdown a partir de QUALQUER `p.models`, sem
      // olhar `p.status` - um provedor local marcado 'disconnected' (nunca
      // pingado com sucesso, ou último ping falhou) ainda oferecia seus
      // modelos como se estivessem prontos pra uso. 'gemini' (cloud, erro
      // 503 honesto e claro se faltar chave - ver PHX-FIX A9 abaixo) fica
      // de fora desta checagem; todo provedor LOCAL (ollama/llama-server/
      // lmstudio) só contribui modelos pro seletor quando
      // `status === 'connected'` - ou seja, só depois de uma resposta real
      // e recente da API do provedor.
      // PHX-FIX (2026-09-06, achado real do usuário com print de tela: o
      // dropdown de modelo passou a mostrar SÓ Gemini, sumindo com
      // Qwen3-4B-Q4_K_M que funcionava minutos antes na mesma sessão - os
      // logs mostravam o sistema sob carga pesada (GPU a 99%, descrição de
      // imagem + tentativa de geração de documento rodando junto) bem
      // antes do sumiço): a checagem `p.status !== 'connected'` era rígida
      // demais - um ping AO VIVO (handleTestProvider, timeout de 2.5s no
      // server.ts) que simplesmente demora um pouco mais porque o
      // llama-server está ocupado processando outra coisa (não porque
      // caiu de verdade) marca `status: 'error'`, e essa checagem escondia
      // os modelos imediatamente - mesmo que `p.models` já tivesse a lista
      // real e confirmada de um scan anterior bem-sucedido na MESMA sessão
      // (handleTestProvider preserva `p.models` no catch, só muda o
      // status - os dados não somem, só ficavam ocultos aqui).
      // Distingue dois casos que a checagem antiga tratava como um só:
      // - 'disconnected' com `models: []` (nunca conectou com sucesso
      //   nesta sessão - o cenário que a correção original de 2026-08-20
      //   queria bloquear, nomes fabricados/placeholder) -> continua
      //   corretamente excluído.
      // - 'error' com `models.length > 0` (JÁ confirmou modelos reais
      //   antes; a falha é do ping mais recente, não da existência do
      //   provedor) -> não esconde mais uma lista que sabemos ser real.
      const isUsable = p.type === 'gemini' || p.status === 'connected' || (p.status === 'error' && p.models.length > 0);
      if (!isUsable) return;
      p.models.forEach((m) => {
        list.push({
          id: m,
          name: m,
          providerType: p.type,
          providerId: p.id,
          // PHX-FIX (achado real do usuário 2026-08-24, "aumentar contexto
          // de caracteres"): "128000" era um número fixo pra QUALQUER
          // provedor local (llama-server/Ollama/LM Studio), nunca
          // verificado contra o que cada processo real usa - o mesmo
          // padrão de dado fabricado já corrigido em outras partes desta
          // auditoria. Pra 'llama-server' (o motor nativo que a própria
          // Phoenix inicia) o valor real É conhecido: `-c 16384` no
          // comando de lançamento (ver llama_cpp.py) - usa esse número de
          // verdade em vez de um chute. Ollama/LM Studio são processos
          // externos configurados pelo próprio usuário fora da Phoenix -
          // o contexto real deles depende do Modelfile/config de cada um,
          // que a Phoenix não lê hoje; "128000" continua sendo uma
          // estimativa não verificada pra esses dois casos (não corrigido
          // agora por falta de uma fonte real pra consultar - diferente do
          // llama-server, que a própria Phoenix controla).
          contextWindow: p.type === 'gemini' ? 1000000 : p.type === 'llama-server' ? 32768 : 128000,
          supportsThinking: m.includes('deepseek-r1') || m.includes('r1') || m.includes('reasoner'),
        });
      });
    });

    if (list.length === 0) {
      list.push({
        id: 'gemini-3.6-flash',
        name: 'gemini-3.6-flash',
        providerType: 'gemini',
        providerId: 'gemini-main',
        contextWindow: 1000000,
      });
    }
    return list;
  }, [providers]);

  const handleUpdateProvider = (updated: ProviderConfig) => {
    setProviders((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
  };

  const handleTestProvider = async (providerId: string) => {
    const provider = providers.find((p) => p.id === providerId);
    if (!provider) return;

    try {
      const response = await fetch('/api/proxy/ping', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          providerType: provider.type,
          baseUrl: provider.baseUrl,
          apiKey: provider.apiKey,
        }),
      });

      const data = await response.json();
      setProviders((prev) =>
        prev.map((p) => {
          if (p.id === providerId) {
            return {
              ...p,
              status: data.online ? 'connected' : 'disconnected',
              latencyMs: data.latencyMs || 0,
              // PHX-FIX (auditoria 2026-08-20, "existem falhas e fallbacks -
              // rastrear e tirar tudo"): antes, só substituía `p.models`
              // quando a resposta real trazia PELO MENOS 1 modelo
              // (`data.models.length > 0`) - se o ping tivesse sucesso
              // (`data.online: true`) mas o provedor genuinamente não
              // tivesse nenhum modelo instalado (ex: Ollama rodando mas sem
              // `ollama pull` feito), o código mantinha silenciosamente a
              // lista ANTERIOR (que podia ser os nomes fabricados do
              // DEFAULT_PROVIDERS ou um resultado real, porém já
              // desatualizado, de um scan passado) - o dropdown mentia que
              // esses modelos ainda existiam. Agora, sempre que o ping teve
              // sucesso (`data.online`), a lista real (mesmo vazia) é a
              // fonte da verdade; só preserva `p.models` quando o próprio
              // ping falhou (`data.online: false` - nesse caso não temos
              // informação nova nenhuma pra confiar).
              //
              // PHX-FIX (2026-08-22, achado real - ver diskChatModelsRef
              // acima): para 'llama-server' especificamente, `data.models`
              // do ping é SEMPRE só o único modelo carregado agora (nunca a
              // lista completa do disco - limitação real de como o
              // llama-server nativo é iniciado, não um bug do ping em si).
              // Um `models: data.models` puro aqui apagava de volta a
              // mistura de 5 modelos que handleScanAllProviders acabou de
              // montar, TODA VEZ que o scan rodava (no mount e em "Detectar
              // Locais") - o usuário via o dropdown completo por uma
              // fração de segundo, sempre revertido pro estado antigo.
              // Agora, só pra este tipo, UNE o ping com a última varredura
              // de disco conhecida - nunca perde um modelo que o
              // ModelScanner já viu, mesmo que ele não esteja carregado
              // agora. Ollama/LM Studio não precisam disso: a API deles já
              // lista TUDO que está instalado, não só o que está rodando.
              models: data.online
                ? p.type === 'llama-server'
                  ? [...new Set([...(data.models || []), ...diskChatModelsRef.current])]
                  : (data.models || [])
                : p.models,
              lastChecked: new Date().toLocaleTimeString(),
            };
          }
          return p;
        })
      );
    } catch {
      setProviders((prev) =>
        prev.map((p) => (p.id === providerId ? { ...p, status: 'error' } : p))
      );
    }
  };

  const handleScanAllProviders = async () => {
    setIsScanning(true);
    try {
      // PHX-FIX (2026-08-22): 'cache: no-store' explícito - esta lista
      // muda toda vez que um modelo é baixado/removido, nunca deveria ser
      // servida de um cache do navegador (ver mesmo PHX-FIX em server.ts,
      // na rota /api/engine/models - "Cache-Control: no-store" ali cobre
      // o lado do servidor, isto cobre o lado do fetch no cliente).
      const engineRes = await fetch('/api/engine/models', { cache: 'no-store' }).catch(() => null);
      if (engineRes && engineRes.ok) {
        const trackedData = await engineRes.json().catch(() => null);
        // PHX-FIX (2026-08-22): guarda a varredura de disco mais recente
        // ANTES de qualquer coisa - handleTestProvider() (chamado logo
        // abaixo, no fim desta função) precisa dela pra não apagar a
        // mistura de volta pra 1 modelo só (ver diskChatModelsRef acima).
        diskChatModelsRef.current = trackedData?.diskChatModels || [];
        if (trackedData && trackedData.allDownloadedModels?.length > 0) {
          // PHX-FIX (auditoria 2026-08-20, mesma seção): antes usava união
          // (`[...p.models, ...trackedData.XModels]`) - um nome fabricado
          // ou obsoleto que já estivesse em `p.models` NUNCA saía dali,
          // só crescia. `trackedData.*Models` vem de uma consulta real e
          // atual (ver /api/engine/models em server.ts); quando ela responde
          // com sucesso, ela é a lista completa e correta AGORA - substitui
          // `p.models` em vez de só somar a ele.
          setProviders((prev) =>
            prev.map((p) => {
              if (p.type === 'ollama' && trackedData.ollamaModels?.length > 0) {
                return { ...p, models: [...new Set(trackedData.ollamaModels)], status: 'connected' };
              }
              if (p.type === 'lmstudio' && trackedData.lmstudioModels?.length > 0) {
                return { ...p, models: [...new Set(trackedData.lmstudioModels)], status: 'connected' };
              }
              if (
                p.type === 'llama-server' &&
                (trackedData.llamaServerModels?.length > 0 || trackedData.diskChatModels?.length > 0)
              ) {
                // PHX-FIX (2026-08-22, achado real via relato do usuário:
                // "baixei DeepSeek-R1-Distill-Qwen-7B-Q6_K.gguf, mas nao
                // consigo usar porque nao aparece na phoenix"): antes, só
                // `trackedData.llamaServerModels` entrava aqui - e essa
                // lista só reflete o ÚNICO modelo que o llama-server nativo
                // já tem carregado agora (ele sobe com `-m <arquivo>`, nunca
                // `--models-dir` - ver LlamaCppDriver.start()), então um
                // .gguf baixado mas nunca carregado nesta sessão ficava
                // invisível no seletor do Chat E do Arena, mesmo estando
                // certinho na pasta (ModelScanner já enxergava o arquivo -
                // `trackedData.diskChatModels`, novo campo vindo de
                // /api/models/chat-gguf, só nunca era lido aqui). Agora a
                // lista é a UNIÃO das duas: o que já está carregado (pode
                // incluir um alias momentâneo específico) + tudo que o
                // ModelScanner vê no disco - selecionar qualquer um e mandar
                // uma mensagem já é suficiente pra LlamaCppDriver carregar o
                // arquivo de verdade (find_model_file faz o match por nome).
                const merged = [
                  ...new Set([...(trackedData.llamaServerModels || []), ...(trackedData.diskChatModels || [])]),
                ];
                return { ...p, models: merged, status: 'connected' };
              }
              return p;
            })
          );
        }
      }

      await Promise.all(
        providers.filter((p) => p.enabled).map((p) => handleTestProvider(p.id))
      );
    } catch {}
    finally {
      setIsScanning(false);
    }
  };

  useEffect(() => {
    handleScanAllProviders();
  }, []);

  // PHX-FIX (auditoria platform_source 2026-08-20, achado A9): antes,
  // `selectedModelId` sempre começava em 'gemini-3.6-flash' hardcoded -
  // sem GEMINI_API_KEY configurada, a primeira experiência do usuário caía
  // direto em erro (/api/gemini/chat devolve 503 honesto, mas ainda assim é
  // a primeira coisa que a pessoa vê). Depois que handleScanAllProviders()
  // termina de pingar os provedores locais de verdade (não é fabricado -
  // vem de /api/proxy/ping), se não tiver chave Gemini e existir um
  // provedor local já conectado, troca o modelo selecionado pra ele - só
  // uma vez (autoSelectedRef), e só se o usuário ainda não tiver escolhido
  // outro modelo manualmente (selectedModelId ainda no default original).
  //
  // PHX-FIX (pedido do usuário 2026-08-22: "alterar o modelo padrao de
  // ollama para llama porque evita erros"): a versão original usava
  // `providers.find(...)` puro - ou seja, o default dependia da ORDEM do
  // array `providers`, que vem de `DEFAULT_PROVIDERS` só na primeira visita;
  // depois disso vem do localStorage ('aviary_providers', ver useState mais
  // acima), que continua com a ordem antiga (Ollama primeiro) pra quem já
  // usava o app antes deste ajuste - só reordenar DEFAULT_PROVIDERS não
  // corrigiria nada pra esses usuários. A causa raiz documentada no
  // PHX-FIX acima (usuário caindo em "Endpoint retornou (404)" com Ollama
  // selecionado) é resolvida de verdade tornando a PREFERÊNCIA explícita e
  // independente da ordem do array: llama-server (Vulkan nativo, é o motor
  // que o Kernel já sobe por padrão no boot) é preferido a qualquer outro
  // provedor local; só cai pra outro (ollama, lmstudio) se llama-server não
  // estiver conectado.
  const LOCAL_PROVIDER_PREFERENCE_ORDER: ProviderConfig['type'][] = ['llama-server', 'ollama', 'lmstudio'];
  const autoSelectedProviderRef = useRef(false);
  useEffect(() => {
    if (autoSelectedProviderRef.current) return;
    if (hasGeminiKey) return;
    if (selectedModelId !== 'gemini-3.6-flash') return;

    const isEligibleLocalProvider = (p: ProviderConfig) =>
      p.enabled && p.type !== 'gemini' && p.type !== 'piper-tts' && p.status === 'connected' && p.models.length > 0;

    let connectedLocalProvider = LOCAL_PROVIDER_PREFERENCE_ORDER
      .map((preferredType) => providers.find((p) => p.type === preferredType && isEligibleLocalProvider(p)))
      .find((p) => p !== undefined);
    if (!connectedLocalProvider) {
      connectedLocalProvider = providers.find(isEligibleLocalProvider);
    }
    if (!connectedLocalProvider) return;

    autoSelectedProviderRef.current = true;
    setSelectedModelId(connectedLocalProvider.models[0]);
  }, [hasGeminiKey, providers, selectedModelId]);

  const handleNewConversation = () => {
    const newConv: Conversation = {
      id: Math.random().toString(36).substring(2, 9),
      title: 'Nova Conversa IA',
      modelId: selectedModelId,
      providerType: availableModels.find((m) => m.id === selectedModelId)?.providerType || 'gemini',
      createdAt: new Date().toLocaleDateString(),
      updatedAt: new Date().toLocaleTimeString(),
      messages: [],
      parameters: { ...parameters },
    };

    setConversations((prev) => [newConv, ...prev]);
    setActiveConversationId(newConv.id);
  };

  const handleDeleteConversation = (id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeConversationId === id) {
      setActiveConversationId(null);
    }
  };

  const activeConversation = conversations.find((c) => c.id === activeConversationId) || null;

  // PHX-NEW (pedido do usuário: "já temos [Flux/SDXL/SD1.5] baixados...
  // só trocar via phoenix" - o backend já suportava escolher o modelo de
  // imagem via `model_hint` (ver ResidentManager.generate_image_direct e
  // ModelRegistry.resolve em registry.py), mas o frontend nunca mandava
  // esse campo - sempre caía no default do catálogo (Flux). Parâmetro
  // novo e opcional, threadeado desde o seletor em ChatView.tsx.
  const handleSendMessage = async (text: string, files: AttachedFile[], rawFiles?: Map<string, File>, imageModelHint?: string) => {
    let convId = activeConversationId;
    let convList = [...conversations];

    if (!convId || !activeConversation) {
      const newConv: Conversation = {
        id: Math.random().toString(36).substring(2, 9),
        title: text.slice(0, 30) || 'Nova Conversa IA',
        modelId: selectedModelId,
        providerType: availableModels.find((m) => m.id === selectedModelId)?.providerType || 'gemini',
        createdAt: new Date().toLocaleDateString(),
        updatedAt: new Date().toLocaleTimeString(),
        messages: [],
        parameters: { ...parameters },
      };
      convList = [newConv, ...convList];
      convId = newConv.id;
      setActiveConversationId(newConv.id);
    }

    const userMsg: ChatMessage = {
      id: Math.random().toString(36).substring(2, 9),
      role: 'user',
      content: text,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      files,
      image: files.find((f) => f.isImage)?.content,
    };

    const targetConv = convList.find((c) => c.id === convId)!;
    const updatedMessages = [...targetConv.messages, userMsg];

    setConversations(
      convList.map((c) => (c.id === convId ? { ...c, messages: updatedMessages, title: c.title === 'Nova Conversa IA' ? text.slice(0, 30) : c.title } : c))
    );

    setIsLoading(true);

    // PHX-NEW 2026-08-30 — PRIMEIRO PORTÃO DE INTENÇÃO.
    // Consulta o Execution Arbiter antes das heurísticas antigas. CLAIMED
    // tem precedência; NOT_CLAIMED significa explicitamente PASS_THROUGH.
    let arbiterDecision: any = null;
    try {
      const arbiterResponse = await fetch('/api/intent/intercept', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text,
          attachments: files.map((f) => ({ name: f.name, isImage: !!f.isImage })),
        }),
      });
      const parsed = await parseJsonResponse<any>(arbiterResponse);
      if (arbiterResponse.ok && parsed && !parsed.error) arbiterDecision = parsed;
    } catch {
      arbiterDecision = null; // árbitro indisponível => legado preservado
    }
    const arbiterClaimed = !!arbiterDecision?.claimed;

    // PHX-NEW (pedido do usuário 2026-08-22: "dois modelos de texto
    // conversando num projeto... até finalizarem"): comando de chat
    // dedicado /colaborar (ou /debate, alias) - desviado ANTES de
    // qualquer outro fluxo (documento/imagem/transcrição), mesmo padrão
    // de desvio já usado abaixo. Sintaxe EXPLÍCITA de propósito (não é
    // detecção de linguagem natural como os outros casos abaixo) porque
    // esta ação é cara (pode levar até ~20 minutos, sobe uma 2ª instância
    // dedicada de GPU) - não deve disparar sem querer numa frase parecida.
    const collabMatch = text.trim().match(/^\/(?:colaborar|debate)\s+(.+)$/is);
    if (collabMatch) {
      // PHX-NEW (2026-08-22, modelo padrão não coube na VRAM útil do
      // usuário com a margem de segurança): flags opcionais "--cpu <hint>"
      // e "--gpu <hint>" deixam escolher um modelo DIFERENTE pra cada
      // lado (ex: um modelo pequeno que caiba na VRAM disponível na GPU,
      // outro maior na CPU) - sem as flags, comportamento original
      // preservado (os dois lados usam o modelo padrão da Phoenix).
      // Extraída como função pura pra poder ser testada isoladamente com
      // o código real do arquivo, mesmo padrão já usado em isOcrIntent/
      // formatOcrNote acima.
      const parseCollabFlags = (body: string): { topic: string; cpuModelHint: string; gpuModelHint: string } => {
        let rest = body;
        let cpuModelHint = '';
        let gpuModelHint = '';
        const cpuFlag = rest.match(/--cpu[= ]+(\S+)/i);
        if (cpuFlag) {
          cpuModelHint = cpuFlag[1];
          rest = rest.replace(cpuFlag[0], '');
        }
        const gpuFlag = rest.match(/--gpu[= ]+(\S+)/i);
        if (gpuFlag) {
          gpuModelHint = gpuFlag[1];
          rest = rest.replace(gpuFlag[0], '');
        }
        return { topic: rest.replace(/\s{2,}/g, ' ').trim(), cpuModelHint, gpuModelHint };
      };

      const { topic: collabTopic, cpuModelHint, gpuModelHint } = parseCollabFlags(collabMatch[1].trim());
      const modelsNote = (cpuModelHint || gpuModelHint)
        ? ` (CPU: ${cpuModelHint || 'padrão'}, GPU: ${gpuModelHint || 'padrão'})`
        : ' (um inteiro na CPU, outro inteiro na GPU/Vulkan)';
      const startMsg: ChatMessage = {
        id: Math.random().toString(36).substring(2, 9),
        role: 'assistant',
        content: `🤝 Iniciando colaboração entre os dois modelos sobre **"${collabTopic}"**${modelsNote} - isso pode levar vários minutos...`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        modelId: selectedModelId,
        // PHX-FIX (ver comentário completo em types.ts::ChatMessage.excludeFromHistory):
        // este aviso e os turnos/resumo da colaboração abaixo são falas de
        // OUTROS dois modelos (um CPU, um GPU), nunca do modelo de texto
        // selecionado - não podem ser reenviados como se fossem o próprio
        // histórico de conversa dele.
        excludeFromHistory: true,
      };
      setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, startMsg] } : c)));

      try {
        const response = await fetch('/api/dual-collab', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ topic: collabTopic, max_rounds: 6, cpu_model: cpuModelHint, gpu_model: gpuModelHint }),
        });
        const data = await parseJsonResponse<any>(response);
        if (!response.ok || !data || data.error) {
          throw new Error((data && data.error) || `Erro ${response.status} na colaboração.`);
        }

        const turnMsgs: ChatMessage[] = (data.transcript || []).map((t: any) => ({
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant' as const,
          content:
            `**[${t.speaker === 'cpu' ? '🧠 CPU' : '⚡ GPU'} — Rodada ${t.round}]**\n\n${t.text}` +
            (t.searches && t.searches.length ? `\n\n_🔎 Buscou na internet: ${t.searches.join('; ')}_` : ''),
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
          excludeFromHistory: true,
        }));

        const summaryMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: data.concluded
            ? `✅ Colaboração concluída em ${data.rounds_completed} rodada(s) - os dois modelos concordaram que o projeto terminou.`
            : `⏱️ Colaboração parada (${data.stopped_reason}) após ${data.rounds_completed} rodada(s).`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
          excludeFromHistory: true,
        };

        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...c.messages, ...turnMsgs, summaryMsg] } : c)));
      } catch (err: any) {
        const errorMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: 'Falha na colaboração entre os dois modelos.',
          error: err.message || 'Verifique se o Phoenix Engine (porta 8000) está ativo e se há VRAM/RAM suficiente para os dois modelos inteiros.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...c.messages, errorMsg] } : c)));
      } finally {
        setIsLoading(false);
      }
      return;
    }

    // ============================================================
    // PHX NEW — preenchimento de template (fonte + planilha-alvo)
    // ============================================================
    // Pedido do usuário 2026-08-28: "aceitar dois arquivos - um fonte, um
    // template alvo - e editar o segundo em vez de gerar do zero, pra
    // qualquer documento que a Phoenix já lê e edita". Até aqui, TODO
    // fluxo de documento acima (e os de imagem/áudio) usa files.find(...)
    // (singular) - só o PRIMEIRO anexo compatível de cada tipo é usado, o
    // resto é ignorado silenciosamente. Quando o usuário anexa DOIS
    // documentos não-imagem e exatamente um deles é .xlsx, a intenção real
    // quase sempre é "leia o outro e preencha esta planilha" - roteado
    // pro novo /api/documents/fill-template ANTES de qualquer outro
    // desvio de documento, pra não cair no fluxo de arquivo único (que só
    // enxergaria o primeiro dos dois e ignoraria o outro).
    const nonImageDocFiles = files.filter((f) => !f.isImage && /\.(pdf|docx|xlsx|pptx|md|txt)$/i.test(f.name));
    const xlsxAttachments = nonImageDocFiles.filter((f) => /\.xlsx$/i.test(f.name));
    const legacyTemplateFillIntent =
      nonImageDocFiles.length === 2 && xlsxAttachments.length === 1 &&
      nonImageDocFiles.every((f) => rawFiles?.has(f.id));
    const isTemplateFillIntent = arbiterClaimed
      ? arbiterDecision.intent === 'document_fill_template' && legacyTemplateFillIntent
      : legacyTemplateFillIntent;

    if (isTemplateFillIntent) {
      const templateFile = xlsxAttachments[0];
      const sourceFile = nonImageDocFiles.find((f) => f.id !== templateFile.id)!;
      const rawSource = rawFiles!.get(sourceFile.id)!;
      const rawTemplate = rawFiles!.get(templateFile.id)!;

      const WEB_IN_TEMPLATE_PATTERN =
        /\b(pesquis\w*|busqu\w*|procure\w*|search\b|web\b|internet\b|dados\s+atuais|informa[cç][oõ]es\s+atuais)\b/i;
      const useWeb = WEB_IN_TEMPLATE_PATTERN.test(text);

      try {
        const formData = new FormData();
        formData.append('source', rawSource, rawSource.name);
        formData.append('template', rawTemplate, rawTemplate.name);
        if (text.trim()) formData.append('instruction', text.trim());
        formData.append('use_web', useWeb ? 'true' : 'false');
        if (useWeb) formData.append('web_query', text.trim());
        if (selectedModelId) formData.append('model_hint', selectedModelId);

        // PHX-FIX (2026-09-03): usa o caminho DETERMINÍSTICO (/pipeline-fill),
        // não o por-LLM (/fill-template). O LLM levava >90min num catálogo
        // real e virava processo órfão; o determinístico faz o mesmo em
        // segundos. A pesquisa web fica de fora deste caminho (é
        // determinístico); se o usuário pedir web, o fill-template por LLM
        // ainda existe, mas não é o default.
        const response = await fetch('/api/documents/pipeline-fill', { method: 'POST', body: formData });
        const data = await parseJsonResponse<any>(response);
        if (!response.ok || !data || data.error || data.ok === false) {
          throw new Error((data && (data.error || data.detail)) || `Erro ${response.status} ao preencher a planilha.`);
        }

        const columnsNote = data.auto_created_columns && Object.keys(data.auto_created_columns).length
          ? `\n\n_Colunas novas criadas no template: ${JSON.stringify(data.auto_created_columns)}_`
          : '';
        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: `✅ Planilha **${data.file_name}** preenchida a partir de **${data.source_file}** (${data.rows_written} linha(s) na planilha "${data.sheet_used}").${columnsNote}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
          downloadFile: {
            name: data.file_name,
            base64: data.file_base64,
            mimeType: data.mime_type,
          },
          // PHX-FIX (ver types.ts::ChatMessage.excludeFromHistory): quem
          // preenche a planilha é o Document Engine, não o modelo de texto
          // selecionado - mesma classe de bug do achado da imagem/edição.
          excludeFromHistory: true,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, assistantMsg] } : c)));
      } catch (err: any) {
        const errorMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: 'Falha ao preencher a planilha a partir do documento-fonte.',
          error: describeNonJsonError(err) || 'Verifique se o Phoenix Engine (porta 8000) está ativo.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, errorMsg] } : c)));
      } finally {
        setIsLoading(false);
      }
      return;
    }

    // ============================================================
    // PHX DOCUMENT TRANSFORM — criação/conversão universal
    // ============================================================
    // Um pedido explícito de arquivo final tem prioridade sobre o chat comum,
    // sobre o web-search isolado e sobre read/edit legado. Pode criar do zero
    // ou usar um documento anexado como base.
    const detectDocumentOutputFormat = (t: string): 'pdf' | 'docx' | 'xlsx' | 'pptx' | 'md' | 'txt' | null => {
      const s = t.toLowerCase();
      // PHX-FIX (2026-09-06, achado real do usuário: "a phoenix nao muda o
      // formato de nenhum arquivo" - ex.: "converta esse excel pra
      // markdown"): a versão antiga pegava o PRIMEIRO formato mencionado
      // na frase inteira, em ordem fixa (pdf > docx > xlsx > ...) - sem
      // distinguir o formato de ORIGEM (o arquivo já anexado, "excel") do
      // formato de DESTINO (o que o usuário realmente quer, "markdown").
      // "converta esse excel pra markdown" detectava xlsx (a origem, por
      // vir primeiro na checagem) em vez de md (o destino de verdade) -
      // o sistema tentava "converter" pro MESMO formato do arquivo,
      // parecendo não fazer nada. Corrigido: prioriza o formato que vem
      // logo depois de uma preposição de destino ("pra"/"para"/"em"/
      // "como"/"por") - o padrão mais comum em português pra indicar o
      // alvo de uma conversão. Sem essa preposição na frase, cai pro
      // comportamento antigo (primeiro formato mencionado) como fallback.
      const targetPatterns: Array<{ re: RegExp; fmt: 'pdf' | 'docx' | 'xlsx' | 'pptx' | 'md' | 'txt' }> = [
        { re: /\b(?:pra|para|em|como|por)\s+(?:um\s+|uma\s+)?pdf\b/, fmt: 'pdf' },
        { re: /\b(?:pra|para|em|como|por)\s+(?:um\s+|uma\s+)?(?:word|docx)\b/, fmt: 'docx' },
        { re: /\b(?:pra|para|em|como|por)\s+(?:um\s+|uma\s+)?(?:excel|xlsx|planilha)\b/, fmt: 'xlsx' },
        { re: /\b(?:pra|para|em|como|por)\s+(?:um\s+|uma\s+)?(?:powerpoint|pptx|apresenta[cç][aã]o)\b/, fmt: 'pptx' },
        { re: /\b(?:pra|para|em|como|por)\s+(?:um\s+|uma\s+)?(?:markdown|md)\b/, fmt: 'md' },
        { re: /\b(?:pra|para|em|como|por)\s+(?:um\s+|uma\s+)?(?:txt|texto\s+puro)\b/, fmt: 'txt' },
      ];
      for (const { re, fmt } of targetPatterns) {
        if (re.test(s)) return fmt;
      }
      if (/\bpdf\b|\.pdf\b/.test(s)) return 'pdf';
      if (/\b(word|docx)\b|\.docx\b/.test(s)) return 'docx';
      if (/\b(excel|xlsx|planilha)\b|\.xlsx\b/.test(s)) return 'xlsx';
      if (/\b(powerpoint|pptx|apresenta[cç][aã]o)\b|\.pptx\b/.test(s)) return 'pptx';
      if (/\b(markdown|md)\b|\.md\b/.test(s)) return 'md';
      if (/\b(txt|texto\s+puro)\b|\.txt\b/.test(s)) return 'txt';
      return null;
    };

    // PHX-FIX (2026-09-06, mesmo achado): verbos coloquiais comuns em
    // português pra pedir conversão ("passa esse doc pra pdf", "muda pra
    // excel", "troque por word") não disparavam a ação - só as formas
    // mais "formais" (converta/converter/transforme) estavam cobertas.
    // Trocado por RADICAIS de palavra (com \w* no final) em vez de listar
    // cada conjugação exata - cobre variações de tempo/pessoa
    // automaticamente. "troc" vira "tro(?:c|qu)" porque o português muda
    // c->qu antes de "e" (troco/trocar, mas troQUE) - regra ortográfica,
    // não erro de digitação.
    const DOCUMENT_ACTION_PATTERN =
      /\b(cri\w*|ger\w*|fa[çc]\w*|produz\w*|mont\w*|convert\w*|transform\w*|export\w*|salv\w*|mud\w*|tro(?:c|qu)\w*|vir\w*|pass\w*|documento|arquivo|relat[oó]rio|planilha|apresenta[cç][aã]o)\b/i;
    const requestedDocumentFormat = detectDocumentOutputFormat(text);
    const legacyDocumentCreateIntent = !!requestedDocumentFormat && DOCUMENT_ACTION_PATTERN.test(text);
    const isDocumentCreateIntent = arbiterClaimed
      ? ['document_create', 'document_transform'].includes(String(arbiterDecision.intent)) && !!requestedDocumentFormat
      : legacyDocumentCreateIntent;
    const documentBaseFile = files.find((f) => !f.isImage && /\.(pdf|docx|xlsx|pptx|md|txt)$/i.test(f.name));

    if (isDocumentCreateIntent) {
      const WEB_IN_DOCUMENT_PATTERN =
        /\b(pesquis\w*|busqu\w*|procure\w*|search\b|web\b|internet\b|dados\s+atuais|informa[cç][oõ]es\s+atuais)\b/i;
      const useWeb = WEB_IN_DOCUMENT_PATTERN.test(text);

      try {
        const formData = new FormData();
        formData.append('instruction', text.trim());
        formData.append('output_format', requestedDocumentFormat!);
        formData.append('use_web', useWeb ? 'true' : 'false');
        if (useWeb) formData.append('web_query', text.trim());
        if (selectedModelId) formData.append('model_hint', selectedModelId);

        // Tenta preservar um nome explicitamente citado pelo usuário.
        const filenameMatch = text.match(/["“']([^"”']+\.(?:pdf|docx|xlsx|pptx|md|txt))["”']/i)
          || text.match(/\b([\wÀ-ÿ._-]+\.(?:pdf|docx|xlsx|pptx|md|txt))\b/i);
        if (filenameMatch?.[1]) formData.append('filename', filenameMatch[1]);

        if (documentBaseFile && rawFiles?.has(documentBaseFile.id)) {
          const rawBase = rawFiles.get(documentBaseFile.id)!;
          formData.append('file', rawBase, rawBase.name);
        }

        const response = await fetch('/api/documents/create', { method: 'POST', body: formData });
        const data = await parseJsonResponse<any>(response);
        if (!response.ok || !data || data.error || data.ok === false) {
          throw new Error((data && (data.error || data.detail)) || `Erro ${response.status} ao criar/transformar documento.`);
        }

        const origin = data.source_file ? ` a partir de **${data.source_file}**` : '';
        const webNote = data.web_used ? ' com pesquisa web real' : '';
        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: `✅ Documento criado${origin}${webNote}: **${data.file_name}**`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
          downloadFile: {
            name: data.file_name,
            base64: data.file_base64,
            mimeType: data.mime_type,
          },
          excludeFromHistory: true,
        };
        setConversations((prev) =>
          prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, assistantMsg] } : c))
        );
      } catch (err: any) {
        const errorMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: 'Falha ao criar/transformar o documento.',
          error: describeNonJsonError(err) || 'Verifique se o Phoenix Engine (porta 8000) está ativo.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        setConversations((prev) =>
          prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, errorMsg] } : c))
        );
      } finally {
        setIsLoading(false);
      }
      return;
    }

    // PHX-NEW: Document Engine - se tem algum anexo binário (PDF/DOCX/
    // XLSX/PPTX), desvia pro /api/documents/read via multipart ANTES do
    // fluxo normal de chat. Documento nunca vai embutido no JSON da
    // mensagem (era assim que o payload de 25MB estourava com PDF grande,
    // e mesmo sem estourar, PDF binário lido como texto no navegador
    // sempre virava conteúdo corrompido - ver ChatView.tsx).
    // PHX-FIX (auditoria completa): "descrever imagem" nunca chegava no
    // MiniCPM-V em NENHUM backend. A imagem anexada só ficava em
    // userMsg.image (pra exibir a miniatura na UI) e o fluxo caía direto
    // no chat genérico logo abaixo - que manda pra /api/gemini/chat (Gemini
    // enxerga a imagem, mas não é o motor de visão local da Phoenix) ou pro
    // /api/proxy/chat (Ollama/LM Studio/llama-server), cujo endpoint em
    // server.ts só encaminha `m.content || m.text`, descartando a imagem
    // por completo - nunca chegava nem no Ollama. O /api/describe-image já
    // existia e já rotea de verdade pro MiniCPM-V via llama-mtmd-cli
    // (mtmd_driver.py), mas nenhum componente do frontend o chamava. Segue
    // o mesmo padrão do desvio de documento logo abaixo: se tem imagem
    // anexada, desvia pro motor de visão nativo ANTES do fluxo de chat
    // genérico, sempre - visão é uma capacidade local, não depende do
    // provedor de texto selecionado.
    // PHX-NEW (pedido do usuário 2026-08-22: "habilitar todas as funçoes
    // do modelo de ocr pra qualquer função"): quando o texto pede
    // explicitamente para extrair/ler o TEXTO da imagem (em vez de
    // descrevê-la), manda mode=ocr pro /api/describe-image - troca o
    // prompt livre por um prompt fixo de transcrição e usa limites de
    // tokens/timeout maiores (ver resident_manager.py::ocr_image_direct).
    // Heurística simples de palavra-chave (não precisa ser tão elaborada
    // quanto isBareTranscriptionRequest abaixo - aqui os dois modos
    // convivem no mesmo endpoint, então um falso negativo só cai de volta
    // pro "describe" de sempre, nunca quebra nada).
    const OCR_INTENT_PATTERN = /\b(ocr|extrair?\s+(o\s+)?texto|extra[çc][ãa]o\s+de\s+texto|transcrever?\s+(o\s+)?texto|ler\s+o\s+texto|qual\s+(o\s+)?texto|texto\s+da\s+imagem)\b/i;
    const isOcrIntent = (t: string): boolean => OCR_INTENT_PATTERN.test(t);

    const imageFile = files.find((f) => f.isImage);
    if (imageFile && rawFiles?.has(imageFile.id)) {
      const rawFile = rawFiles.get(imageFile.id)!;
      try {
        const ocrMode = isOcrIntent(text);
        const formData = new FormData();
        formData.append('file', rawFile, rawFile.name);
        formData.append('mode', ocrMode ? 'ocr' : 'describe');
        if (text.trim() && !ocrMode) formData.append('prompt', text);

        const response = await fetch('/api/describe-image', { method: 'POST', body: formData });
        const data = await parseJsonResponse<any>(response);
        if (!response.ok || !data || data.error) {
          throw new Error((data && data.error) || `Erro ${response.status} ao analisar a imagem.`);
        }

        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: ocrMode
            ? `**Texto extraído (OCR):**\n\n${data.text || '(nenhum texto encontrado)'}`
            : (data.text || '(sem resposta)'),
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, assistantMsg] } : c)));
      } catch (err: any) {
        const errorMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: 'Falha ao analisar a imagem.',
          error: err.message || 'Verifique se o Phoenix Engine (porta 8000) está ativo e o llama-mtmd-cli está compilado.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, errorMsg] } : c)));
      } finally {
        setIsLoading(false);
      }
      return;
    }

    const documentFile = files.find((f) => !f.isImage && /\.(pdf|docx|xlsx|pptx|md|txt)$/i.test(f.name));
    if (documentFile && rawFiles?.has(documentFile.id)) {
      const rawFile = rawFiles.get(documentFile.id)!;

      // PHX-FIX (auditoria platform_source 2026-08-20, achado A3): antes,
      // TODA mensagem com documento anexado ia pra /api/documents/read
      // (leitura/resumo) - /api/documents/edit já existia no backend
      // (server.ts e api_server.py), mas nada no frontend o chamava, então
      // "corrija este PDF"/"edite este documento" era tratado como se
      // fosse uma pergunta de leitura. Detecta intenção de edição no texto
      // e desvia pra /api/documents/edit em vez de /api/documents/read -
      // sem heurística nenhuma no meio, o texto do usuário vira a própria
      // instrução mandada pro Document Engine.
      const legacyEditIntent = /\b(edit\w*|corrij\w*|corrig\w*|reescrev\w*|reformul\w*|revis[ae]\w*|altere|alterar|modifiqu\w*|ajuste|ajustar|rewrite|fix\s+this)\b/i.test(text);
      const isEditIntent = arbiterClaimed
        ? arbiterDecision.intent === 'document_edit'
        : legacyEditIntent;

      // PHX-NEW (pedido do usuário 2026-08-28): quando dão dois documentos
      // não-imagem e a intenção é de edição, mas nenhum é .xlsx (senão já
      // teria caído no fluxo de fill-template acima), o segundo documento
      // vira contexto de referência ("edite este contrato usando os dados
      // deste outro arquivo") em vez de ser silenciosamente ignorado -
      // dobrado no prompt do Document Engine via edit_document_direct.
      const referenceDocFile = isEditIntent
        ? nonImageDocFiles.find((f) => f.id !== documentFile.id)
        : undefined;
      const rawReferenceFile = referenceDocFile && rawFiles?.has(referenceDocFile.id)
        ? rawFiles.get(referenceDocFile.id)!
        : undefined;

      // PHX-NEW (pedido do usuário 2026-08-22, OCR real): /api/documents/read
      // e /api/documents/edit agora tentam OCR automático via visão quando o
      // PDF anexado é escaneado (sem texto nativo) - ver resident_manager.py.
      // Nunca deve ser silencioso: quando a resposta traz `ocr_used`, o chat
      // mostra isso explicitamente (quantas páginas foram processadas, se
      // sobrou alguma de fora por limite de tempo/páginas), em vez do
      // usuário só ver um resumo sem saber que veio de OCR (que pode ter
      // pequenos erros de reconhecimento de caractere).
      const formatOcrNote = (data: any): string => {
        if (!data?.ocr_used) return '';
        const processed = data.ocr_pages_processed ?? '?';
        const total = data.ocr_pages_total ?? '?';
        const truncatedNote = data.ocr_truncated
          ? ' (algumas páginas não foram processadas por limite de tempo/páginas)'
          : '';
        return `_Texto obtido via OCR automático (PDF escaneado, ${processed}/${total} página(s))${truncatedNote}._\n\n`;
      };

      try {
        const formData = new FormData();
        formData.append('file', rawFile, rawFile.name);

        if (isEditIntent) {
          formData.append('instruction', text.trim() || 'Revise e melhore o documento.');
          if (rawReferenceFile) formData.append('reference', rawReferenceFile, rawReferenceFile.name);
          const response = await fetch('/api/documents/edit', { method: 'POST', body: formData });
          const data = await parseJsonResponse<any>(response);
          if (!response.ok || !data || data.error) {
            throw new Error((data && data.error) || `Erro ${response.status} ao editar o documento.`);
          }

          const assistantMsg: ChatMessage = {
            id: Math.random().toString(36).substring(2, 9),
            role: 'assistant',
            content: `${formatOcrNote(data)}Documento editado com sucesso: **${data.file_name}**`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            modelId: selectedModelId,
            downloadFile: { name: data.file_name, base64: data.file_base64, mimeType: data.mime_type },
            // PHX-FIX (ver types.ts::ChatMessage.excludeFromHistory): é o
            // Document Engine (motor separado) que edita o arquivo, não o
            // modelo de texto selecionado - mesma classe de bug do achado
            // da imagem gerada logo abaixo.
            excludeFromHistory: true,
          };
          setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, assistantMsg] } : c)));
        } else {
          if (text.trim()) formData.append('question', text);
          const response = await fetch('/api/documents/read', { method: 'POST', body: formData });
          const data = await parseJsonResponse<any>(response);
          if (!response.ok || !data || data.error) {
            throw new Error((data && data.error) || `Erro ${response.status} ao ler o documento.`);
          }

          const assistantMsg: ChatMessage = {
            id: Math.random().toString(36).substring(2, 9),
            role: 'assistant',
            content: `${formatOcrNote(data)}${data.text || '(sem resposta)'}`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            modelId: selectedModelId,
          };
          setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, assistantMsg] } : c)));
        }
      } catch (err: any) {
        const errorMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: isEditIntent ? 'Falha ao editar o documento.' : 'Falha ao ler o documento.',
          error: err.message || 'Verifique se o Phoenix Engine (porta 8000) está ativo.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, errorMsg] } : c)));
      } finally {
        setIsLoading(false);
      }
      return;
    }

    // PHX-NEW (auditoria 2026-08-20, "Aviary Chat audio routing" / Seção 10):
    // achado real do usuário - anexar áudio no chat com "transcreva este
    // áudio" nunca chegava no Whisper. O arquivo caía no `else` de
    // ChatView.handleFileUpload() (lido como texto, corrompendo os bytes) e
    // esse conteúdo corrompido ia embutido no JSON mandado pro
    // /api/gemini/chat ou /api/proxy/chat - produzindo o erro
    // "Unexpected token '<'" relatado (a mensagem ficava grande/inválida e
    // o backend devolvia uma resposta que não era o JSON esperado). Áudio
    // agora SEMPRE é roteado pro /api/transcribe (Whisper) via multipart
    // ANTES do fluxo de chat genérico, igual documento/imagem acima -
    // nunca cai no chat de texto normal.
    const audioFile = files.find((f) => !f.isImage && /\.(mp3|wav|m4a|ogg|flac|aac|webm)$/i.test(f.name));

    // PHX-FIX (achado real via screenshot do usuário: mandou "transcrever
    // audio" com o .wav anexado, funcionou certinho via Whisper - depois
    // mandou a MESMA frase "transcrever audio" de novo, SEM anexar nada
    // dessa vez, e recebeu uma segunda "transcrição" completa, com uma
    // seção extra de "Observações técnicas" e até um indicador de
    // tokens/s no rodapé). Isso não é o Whisper rodando de novo - é
    // exatamente o buraco que os desvios de áudio/imagem/documento acima
    // foram criados pra fechar, só que faltava fechar ESTE caso: sem
    // audioFile nesta mensagem, a execução simplesmente cai no chat de
    // texto normal (sendToProvider), e o LLM (qwen3-8b) vê a transcrição
    // real anterior no histórico da conversa e "responde" reescrevendo
    // uma versão plausível, mas 100% inventada - inclusive fabricando
    // uma seção de "Observações técnicas" descrevendo um pipeline de
    // áudio que nunca rodou. Diferente dos outros bugs desta sessão, esse
    // não aparece como erro na tela - é um sucesso falso silencioso, o
    // tipo mais perigoso: parece uma resposta real, mas é ficção do
    // modelo se fazendo passar pelo resultado de um pipeline que ele
    // nunca executou. Fechado aqui, ANTES de qualquer chamada de rede: se
    // o texto expressa intenção de transcrição mas não tem áudio novo
    // anexado NESTA mensagem, bloqueia local com um aviso claro - nunca
    // deixa a pergunta chegar no LLM de texto pra ele "preencher a
    // lacuna" com o que acha que devia ter acontecido.
    if (!audioFile && /\btranscrev\w*\b|\bwhisper\b/i.test(text)) {
      const warnMsg: ChatMessage = {
        id: Math.random().toString(36).substring(2, 9),
        role: 'assistant',
        content:
          '⚠️ Nenhum áudio anexado nesta mensagem. Clique no clipe e anexe um .mp3/.wav/.m4a/.ogg/.flac/.aac/.webm para transcrever — não reaproveito uma transcrição anterior do histórico, e o modelo de texto não tem acesso a nenhum áudio.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        modelId: selectedModelId,
      };
      setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, warnMsg] } : c)));
      setIsLoading(false);
      return;
    }

    // PHX-FIX (auditoria 2026-08-20, "Frontend JSON error handling" / Seção
    // 11): a lógica de escolha de endpoint/provedor + chamada de chat foi
    // extraída pra uma função interna reutilizável, pra que o branch de
    // áudio (resumo de transcrição) possa reusar exatamente a mesma lógica
    // sem duplicar ~65 linhas. Chamar handleSendMessage(...) recursivamente
    // aqui dentro seria incorreto: a closure desta execução tem uma cópia
    // "congelada" de `conversations` do render atual, então uma chamada
    // recursiva ignoraria a mensagem de transcrição que acabamos de
    // adicionar via setConversations (race de estado). sendToProvider()
    // recebe a lista de mensagens explicitamente, sem depender do estado
    // React ainda não commitado.
    const sendToProvider = async (msgList: ChatMessage[]) => {
      const activeModelObj = availableModels.find((m) => m.id === selectedModelId);
      const providerObj = providers.find((p) => p.id === activeModelObj?.providerId) || providers[0];

      // PHX-RAG v57: consulta automática do repositório em TODA chamada de chat.
      // O contexto é transitório: entra no systemInstruction da requisição e
      // não polui o histórico visual da conversa.
      //
      // PHX-FIX (auditoria completa 2026-08-28, gap de privacidade real): sem
      // esta checagem, os trechos dos documentos do usuário eram anexados ao
      // systemInstruction pra QUALQUER provedor - inclusive um provedor de
      // nuvem (gemini), sem nenhum aviso ou opção de desligar. Por padrão
      // (blockRagOnCloudProviders = true), a consulta ao RAG nem é feita
      // quando o provedor ativo é de nuvem - o texto dos seus documentos
      // nunca chega a sair da máquina. Provedores locais (Ollama,
      // llama-server, LM Studio) nunca são afetados por esta trava.
      let ragSystemContext = '';
      const ragQuery = [...msgList].reverse().find(m => m.role === 'user')?.content?.trim() || '';
      const isCloudProvider = CLOUD_PROVIDER_TYPES.has(providerObj.type);
      const ragBlockedForCloudPrivacy = isCloudProvider && parameters.blockRagOnCloudProviders;
      if (ragBlockedForCloudPrivacy) {
        if (ragQuery) {
          console.debug(
            `[PHX-RAG] consulta ao RAG pulada de propósito: provedor ativo ('${providerObj.type}') é de nuvem e ` +
            `"Bloquear RAG em provedores de nuvem" está ativado em Parâmetros. Nenhum trecho de documento foi ` +
            `enviado pra fora da máquina para: "${ragQuery.slice(0, 80)}"`
          );
        }
      } else if (ragQuery) {
        try {
          const ragResponse = await fetch('/api/rag/query', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: ragQuery, n_results: 5, min_score: 0.15 }),
          });
          if (ragResponse.ok) {
            const ragData = await parseJsonResponse<any>(ragResponse);
            const hits = Array.isArray(ragData?.hits) ? ragData.hits : [];
            if (hits.length > 0) {
              ragSystemContext =
                '\n\n--- PHOENIX RAG KNOWLEDGE REPOSITORY ---\n' +
                'Use estes trechos quando forem relevantes. Não invente conteúdo ausente.\n\n' +
                hits.map((h: any, i: number) =>
                  `[R${i + 1}] Fonte: ${h.title || h.parent_id || 'documento'} | similaridade=${Number(h.score || 0).toFixed(3)}\n${h.text || ''}`
                ).join('\n\n') +
                '\n--- FIM DO PHOENIX RAG ---';
            } else {
              // PHX-FIX (auditoria completa 2026-08-28): antes, "consulta OK
              // mas 0 hits acima de min_score" e "consulta falhou/rede fora"
              // (branches abaixo) eram indistinguíveis - os dois resultavam
              // em ragSystemContext vazio, sem nenhum sinal em lugar
              // nenhum. Isso torna impossível diagnosticar se min_score=0.15
              // está calibrado direito (ver README/auditoria: all-MiniLM-
              // L6-v2 não é explicitamente multilíngue - uma query em PT
              // contra documento em EN pode legitimamente cair abaixo do
              // limiar mesmo havendo conteúdo relevante). Não muda nenhum
              // comportamento do chat (RAG continua "nice to have", nunca
              // bloqueia) - só deixa rastreável no console, pra calibrar
              // min_score com dados reais de uso em vez de só teoria sobre
              // o modelo de embedding.
              console.debug(`[PHX-RAG] consulta OK, 0 hits acima de min_score=0.15 para: "${ragQuery.slice(0, 80)}"`);
            }
          } else {
            console.debug(`[PHX-RAG] consulta falhou com status ${ragResponse.status} para: "${ragQuery.slice(0, 80)}"`);
          }
        } catch (e) {
          // RAG é enriquecimento: falha de consulta não derruba o chat normal.
          console.debug(`[PHX-RAG] consulta lançou exceção (rede/parse) para: "${ragQuery.slice(0, 80)}"`, e);
        }
      }

      // PHX-FIX (achado real do usuário 2026-08-24: pediu "gerar imagem",
      // Phoenix respondeu "Imagem gerada com **flux1-schnell-Q4_K_M**." (só
      // um aviso de UI sobre o motor SDXL/Flux local) - na mensagem
      // SEGUINTE, perguntou "ola, seu nome e modelo?" pro qwen3-8b, e ele
      // respondeu "Nome: Phoenix Aviary Platform... Modelo: Flux 1-Schnell
      // (Q4_K_M)". Causa raiz: `messages: msgList` mandava o histórico
      // INTEIRO pro provedor de texto sem filtro nenhum - incluindo aquele
      // aviso de imagem como se fosse uma fala real de role 'assistant' do
      // próprio qwen3-8b. Combinado com o system prompt padrão ("Você é a
      // Phoenix Aviary Platform" / preset "Assistente Geral Conciso"), o
      // modelo simplesmente sintetizou os dois fatos que via no seu próprio
      // contexto - concluindo (de forma plausível, mas errada) que ele
      // MESMO era o Flux 1-Schnell. Mesma classe de bug já corrigida nesta
      // sessão pro caso de transcrição de áudio fantasma (ver comentário
      // "PHX-FIX (achado real via screenshot..." mais acima neste arquivo) -
      // o modelo de texto não tem como saber que um "turno" no seu próprio
      // histórico não foi ele quem gerou. Filtra aqui, no único lugar onde
      // o histórico de fato sai pra rede, qualquer mensagem marcada como
      // excludeFromHistory (imagem gerada, colaboração entre outros dois
      // modelos, documento editado) - continuam aparecendo normalmente na
      // tela, só não voltam pro provedor como se fossem falas dele.
      const historyForProvider = msgList.filter((m) => !m.excludeFromHistory);

      try {
        let endpoint = '/api/gemini/chat';
        let requestPayload: any = {
          model: selectedModelId,
          messages: historyForProvider,
          systemInstruction: parameters.systemInstruction + ragSystemContext,
          temperature: parameters.temperature,
          topP: parameters.topP,
          topK: parameters.topK,
          maxTokens: parameters.maxTokens,
        };

        if (providerObj.type !== 'gemini') {
          endpoint = '/api/proxy/chat';
          requestPayload = {
            providerType: providerObj.type,
            baseUrl: providerObj.baseUrl,
            apiKey: providerObj.apiKey,
            model: selectedModelId,
            messages: historyForProvider,
            // PHX-FIX (achado real do usuário 2026-08-28, comparando esta
            // base com uma linha de trabalho paralela): o ragSystemContext
            // calculado acima (PHX-RAG v57) só era anexado ao
            // systemInstruction no branch do Gemini logo abaixo - este
            // branch, usado por TODO provedor local (Ollama, llama-server,
            // LM Studio - o caso de uso principal da Phoenix num hardware
            // como este), continuava mandando só o systemInstruction cru.
            // Resultado: o RAG consultava /api/rag/query em TODA mensagem
            // e descartava silenciosamente o resultado sempre que o
            // provedor selecionado não era o Gemini - nenhum modelo local
            // jamais recebeu contexto do RAG, apesar da consulta rodar.
            systemInstruction: parameters.systemInstruction + ragSystemContext,
            temperature: parameters.temperature,
            maxTokens: parameters.maxTokens,
          };
        }

        const response = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestPayload),
        });

        // PHX-FIX (Seção 11): antes chamava response.json() direto - se o
        // backend/proxy devolvesse HTML (rota errada, erro 502, fallback
        // do SPA), o SyntaxError bruto ("Unexpected token '<'") vazava pro
        // usuário sem nenhuma pista do que houve. parseJsonResponse checa
        // o Content-Type antes e lança um erro com mensagem acionável.
        const data = await parseJsonResponse<any>(response);
        if (!response.ok || data.error) {
          throw new Error(data.error || 'Erro no provedor');
        }

        let responseText = data.text || '';
        let thinkingText = '';

        // PHX-FIX (2026-09-06, achado real: "qualquer resposta... fica
        // cortada", sem erro, nos dois provedores - ver PHX-FIX em
        // server.ts/llama_cpp.py sobre --jinja e reasoning_content):
        // 1) prioridade pro campo `reasoning` já separado pelo servidor -
        //    quando presente, `text` já vem limpo, sem <think> nenhum.
        // 2) fallback pro regex antigo só quando o servidor NÃO separou
        //    (modelo/template sem suporte, ou provedor que não repassa o
        //    campo).
        // 3) dentro do fallback, corrigido o caso da tag NUNCA FECHAR
        //    (resposta cortada enquanto o modelo ainda "pensava"): antes,
        //    sem `</think>`, o regex não achava nada e o texto bruto (tag
        //    e raciocínio incompleto juntos) vazava pra tela, parecendo
        //    resposta corrompida/cortada no meio. Agora trata tudo a
        //    partir de `<think>` sem fechamento como pensamento
        //    incompleto (nunca mostrado como resposta final) e mantém só
        //    o que veio ANTES da tag como resposta visível.
        if (data.reasoning) {
          thinkingText = data.reasoning;
        } else {
          const thinkMatch = responseText.match(/<think>([\s\S]*?)<\/think>/i);
          if (thinkMatch) {
            thinkingText = thinkMatch[1].trim();
            responseText = responseText.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
          } else {
            const openThinkIdx = responseText.search(/<think>/i);
            if (openThinkIdx !== -1) {
              thinkingText = responseText.slice(openThinkIdx + '<think>'.length).trim();
              responseText = responseText.slice(0, openThinkIdx).trim();
            }
          }
        }

        // PHX-NEW (pedido explícito do usuário: "qualquer comando deveria
        // matar processo e subir modelo padrao e nao dar erro"): quando
        // /api/proxy/chat precisou matar e reerguer o llama-server nativo
        // pra conseguir responder (ver server.ts), a resposta vem marcada
        // com `recovered`/`recoveredModel` - avisa isso de forma visível
        // na própria mensagem em vez de trocar de modelo em silêncio, pra
        // o usuário entender por que a resposta veio de um modelo
        // diferente do que ele tinha selecionado.
        if (data.recovered && data.recoveredModel) {
          responseText = `⚠ *O servidor LLM nativo travou e foi reiniciado automaticamente com o modelo padrão '${data.recoveredModel}'.*\n\n${responseText}`;
        }

        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: responseText,
          thinking: thinkingText,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
          providerType: providerObj.type,
          metrics: data.usage,
        };

        setConversations((prev) =>
          prev.map((c) =>
            c.id === convId ? { ...c, messages: [...msgList, assistantMsg] } : c
          )
        );
      } catch (err: any) {
        const errorMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: 'Falha ao obter resposta do modelo.',
          error: describeNonJsonError(err) || 'Verifique se o servidor local (Ollama / llama-server / LM Studio) está ativo.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };

        setConversations((prev) =>
          prev.map((c) =>
            c.id === convId ? { ...c, messages: [...msgList, errorMsg] } : c
          )
        );
      } finally {
        setIsLoading(false);
      }
    };

    if (audioFile && rawFiles?.has(audioFile.id)) {
      const rawFile = rawFiles.get(audioFile.id)!;
      // PHX-FIX (auditoria 2026-08-20, "áudio no ChatView/Aviary" - achado
      // real de uma auditoria externa lendo este arquivo linha a linha):
      // antes, a ÚNICA instrução do usuário que sobrevivia ao anexar áudio
      // era o keyword "resum*/summar*" - qualquer outra coisa digitada
      // junto ("traduza pro inglês", "responda a pergunta feita no áudio",
      // "liste os itens de ação") era silenciosamente DESCARTADA: nem ia
      // pro backend, nem aparecia em lugar nenhum, e o usuário só recebia a
      // transcrição crua sem explicação do porquê a instrução foi ignorada.
      // Isso também é inconsistente com o branch de documento logo acima
      // (`isEditIntent`/`question`), que sempre encaminha o texto real do
      // usuário pro Document Engine, nunca um heurístico único. Generalizado
      // aqui do mesmo jeito: transcrição sempre acontece (continua sendo o
      // único uso sensato pra um anexo de áudio num chat de texto), mas
      // agora QUALQUER instrução digitada junto (não só "resuma") é
      // reenviada de verdade pro provedor de texto junto com a transcrição
      // como contexto - "resuma"/"traduza"/"responda X" funcionam igual,
      // sem lista fixa de gatilhos.
      // PHX-FIX (2026-08-22, achado real do usuário: barulho de GPU/CPU
      // subindo LOGO depois de uma transcrição real terminar, e a resposta
      // seguinte reproduzindo quase palavra por palavra um aviso que já
      // tinha aparecido antes na MESMA conversa — agora com um indicador de
      // tok/s de verdade grudado, provando que veio do LLM, não de um
      // efeito colateral cosmético): `hasExplicitInstruction` tratava
      // QUALQUER texto não vazio como uma instrução real a repassar pro
      // LLM de texto junto com a transcrição pronta - inclusive quando esse
      // texto era só o PRÓPRIO pedido de transcrição ("transcrever audio",
      // "transcreva isso"), que não sobra nenhuma instrução de verdade
      // depois que a transcrição já foi entregue. Resultado: toda
      // transcrição pedida do jeito mais comum ("transcrever audio")
      // disparava uma SEGUNDA chamada ao LLM sem necessidade nenhuma -
      // subindo o llama-server (o barulho de ventoinha relatado) só pra ele
      // "reagir" a um pedido já 100% atendido; vendo o aviso de "sem áudio"
      // de uma rodada de teste anterior no histórico da mesma conversa, o
      // modelo acabava reproduzindo ele quase mudo, parecendo (mas não
      // sendo) o bloqueio local funcionando.
      //
      // isBareTranscriptionRequest() tokeniza o texto, remove acentos (pra
      // "áudio"/"audio" caírem no mesmo balde), tira a palavra-gatilho
      // (transcrev*/whisper/roda/executa/faz...) e as palavras de
      // preenchimento em volta dela ("o", "esse", "áudio", "isso",
      // "nisso"...) - se NADA sobrar depois disso, é só o pedido de
      // transcrever, sem instrução extra nenhuma pra repassar. Qualquer
      // palavra REAL sobrando ("resuma", "traduza", "responda") continua
      // contando como instrução explícita, exatamente como antes.
      const TRANSCRIPTION_TRIGGER_WORDS = new Set([
        'transcreva', 'transcrever', 'transcricao', 'transcreve', 'transcrevam',
        'whisper', 'roda', 'rodar', 'executa', 'executar', 'faz', 'faca',
      ]);
      const TRANSCRIPTION_FILLER_WORDS = new Set([
        'o', 'a', 'os', 'as', 'esse', 'essa', 'esses', 'essas', 'este', 'esta', 'estes', 'estas',
        'isso', 'isto', 'aquilo', 'nisso', 'nisto', 'aqui', 'ai', 'audio', 'arquivo',
        'meu', 'minha', 'dele', 'dela', 'por', 'favor', 'pode', 'podes', 'de', 'do', 'da', 'pra', 'para', 'em', 'no', 'na',
      ]);

      function isBareTranscriptionRequest(t: string): boolean {
        const tokens = t
          .toLowerCase()
          .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
          .replace(/[.,!?;:]/g, ' ')
          .split(/\s+/)
          .filter(Boolean);
        if (tokens.length === 0) return false;
        const isTriggerOrFiller = (tok: string) =>
          TRANSCRIPTION_TRIGGER_WORDS.has(tok) || tok.startsWith('transcrev') || tok === 'whisper' || TRANSCRIPTION_FILLER_WORDS.has(tok);
        const hasTrigger = tokens.some((tok) => TRANSCRIPTION_TRIGGER_WORDS.has(tok) || tok.startsWith('transcrev') || tok === 'whisper');
        if (!hasTrigger) return false;
        return tokens.every(isTriggerOrFiller);
      }

      const hasExplicitInstruction = text.trim().length > 0 && !isBareTranscriptionRequest(text);

      try {
        const formData = new FormData();
        formData.append('file', rawFile, rawFile.name);
        formData.append('language', 'pt');

        const response = await fetch('/api/transcribe', { method: 'POST', body: formData });
        const data = await parseJsonResponse<any>(response);
        if (!response.ok || !data || data.ok === false || data.error) {
          throw new Error((data && (data.error || data.detail)) || `Erro ${response.status} ao transcrever o áudio.`);
        }

        const transcript: string = data.text || '';

        if (hasExplicitInstruction && transcript.trim()) {
          const transcriptMsg: ChatMessage = {
            id: Math.random().toString(36).substring(2, 9),
            role: 'assistant',
            content: `**Transcrição do áudio:**\n\n${transcript}`,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            modelId: selectedModelId,
          };
          const messagesWithTranscript = [...updatedMessages, transcriptMsg];
          setConversations((prev) =>
            prev.map((c) => (c.id === convId ? { ...c, messages: messagesWithTranscript } : c))
          );
          // Pede pro provedor de texto agir sobre a transcrição SEGUINDO A
          // INSTRUÇÃO REAL DO USUÁRIO (`text`, o que ele digitou junto do
          // anexo) - não mais um pedido de resumo hardcoded em português
          // independente do que foi pedido. Reusa a mesma lógica de
          // endpoint/erro da conversa normal - sem recursão em
          // handleSendMessage (ver comentário acima).
          await sendToProvider([
            ...messagesWithTranscript,
            {
              id: Math.random().toString(36).substring(2, 9),
              role: 'user',
              content: text,
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
            },
          ]);
          return;
        }

        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: transcript || '(transcrição vazia — áudio sem fala detectável)',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, assistantMsg] } : c)));
      } catch (err: any) {
        const errorMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: 'Falha ao transcrever o áudio.',
          error: describeNonJsonError(err) || 'Verifique se o Phoenix Engine (porta 8000) está ativo e o whisper-cli está compilado (repos/whisper.cpp).',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, errorMsg] } : c)));
      } finally {
        setIsLoading(false);
      }
      return;
    }

    // PHX-NEW (achado real do usuário 2026-08-24, screenshot: digitou
    // "pesquisar acidente com 2 helicópteros no rj em 2026" no chat normal
    // e o qwen3-8b respondeu direto da própria memória - "a data de 2026
    // ainda não chegou, não há registros" - sem buscar nada de verdade na
    // internet). Causa raiz achada lendo o código real: o Phoenix Engine já
    // tem uma busca real via SearXNG local funcionando de verdade
    // (phoenix_kernel/intelligence/web_search.py::search_web(), já provado
    // em uso real - ver /areas/phoenix-engine.md, "comandos search
    // digitados no terminal da Phoenix retornaram resultados reais da
    // web") - mas ela só estava conectada ao recurso /colaborar
    // (dual_collab.py), nunca ao chat comum de um único modelo. O usuário
    // mandou um guia genérico de "Open WebUI + SearXNG" (projeto
    // completamente diferente da Aviary, com um toggle manual de "Web
    // Search" por conversa dentro de um Admin Panel que não existe aqui) -
    // a Aviary não replica esse toggle; em vez disso, segue o MESMO padrão
    // já usado nesta função pra imagem/OCR/documento: detecta a intenção
    // no próprio texto digitado e desvia ANTES do chat genérico. Só
    // dispara quando a mensagem começa de fato com um verbo de busca
    // explícito (não no meio da frase) pra não confundir uma pergunta
    // comum tipo "onde procuro isso no menu" com um pedido de busca real.
    const WEB_SEARCH_TRIGGER_PATTERN =
      /^\s*(pesquis(ar|e|a)|busca|busque|buscar|procur[ae]|procurar|google|search(\s+for)?|find\s+out(\s+about)?)\b[:\-]?\s*/i;
    const isWebSearchIntent = (t: string): boolean => WEB_SEARCH_TRIGGER_PATTERN.test(t);

    if (isWebSearchIntent(text)) {
      const searchQuery = text.replace(WEB_SEARCH_TRIGGER_PATTERN, '').trim() || text;

      try {
        const response = await fetch('/api/web-search', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: searchQuery, max_results: 5 }),
        });
        const data = await parseJsonResponse<any>(response);
        if (!response.ok || !data || data.error || data.ok === false) {
          throw new Error((data && (data.error || data.detail)) || `Erro ${response.status} ao buscar na web.`);
        }

        // PHX-FIX: diferente do aviso "Imagem gerada com X" (ver
        // types.ts::ChatMessage.excludeFromHistory), este conteúdo tem
        // informação real que o modelo de texto PRECISA pra responder a
        // pergunta original - mesmo padrão da transcrição de áudio (ver
        // "hasExplicitInstruction" mais acima neste arquivo): não leva
        // excludeFromHistory, porque não é um aviso vazio sobre outro
        // subsistema, é o próprio contexto que faltava pro modelo
        // responder direito.
        const searchResultsMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: `🔎 **Resultados da busca na web** para "${searchQuery}":\n\n${data.results}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        const messagesWithSearch = [...updatedMessages, searchResultsMsg];
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: messagesWithSearch } : c)));

        // Pede pro modelo de texto responder de verdade usando os
        // resultados que acabaram de entrar no histórico - reenvia a
        // pergunta como uma nova mensagem de usuário (sem o verbo
        // "pesquisar" na frente, pra não incentivar o modelo a tentar
        // "pesquisar" de novo em texto livre em vez de responder).
        await sendToProvider([
          ...messagesWithSearch,
          {
            id: Math.random().toString(36).substring(2, 9),
            role: 'user',
            content: searchQuery,
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          },
        ]);
      } catch (err: any) {
        const errorMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: 'Falha ao buscar na web.',
          error: describeNonJsonError(err) || 'Verifique se o Phoenix Engine (porta 8000) está ativo e o container do SearXNG (porta 8080) está rodando.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: selectedModelId,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, errorMsg] } : c)));
        setIsLoading(false);
      }
      return;
    }

    // PHX-NEW (achado real via screenshot do usuário: pedir "gerar uma
    // imagem de uma phoenix voando sob chamas" pro chat de texto
    // (Ollama/Gemini/llama-server) sempre produzia só uma DESCRIÇÃO em
    // texto/markdown do que a imagem teria - nenhum modelo de CHAT aqui
    // gera pixels de verdade, e nada no frontend desviava esse pedido pro
    // motor de imagem real. O motor real (SDXL/Flux via sd_cpp.py) já
    // está completo e funcional, exposto em POST /api/generate-image
    // (api_server.py -> resident.generate_image_direct() -> PNG real em
    // base64) - só nunca era chamado por este componente. Mesmo padrão dos
    // desvios de imagem-anexada/documento/áudio acima: detecta a intenção
    // no TEXTO (sem precisar de anexo) e desvia ANTES do fluxo de chat
    // genérico - geração de imagem é uma capacidade local, não depende do
    // provedor de texto selecionado no seletor de modelo.
    // PHX-FIX (achado real via screenshot do usuário, depois que o chat
    // nativo voltou a responder): o regex explícito acima não pega um
    // prompt "cru" de geração de imagem (estilo Stable Diffusion /
    // Midjourney - cheio de tags separadas por vírgula, sem nenhum verbo
    // tipo "gere"/"crie"/"generate"). O usuário colou um prompt assim
    // ("a majestic phoenix engulfed in living flame, ... 8k, trending on
    // artstation, masterpiece, ...") e o chat tratou como texto normal,
    // devolvendo uma DESCRIÇÃO em markdown em vez de gerar a imagem.
    // Heurística nova: se o texto tem várias tags separadas por vírgula
    // (>=4) e pelo menos 2 "palavras mágicas" clássicas desse tipo de
    // prompt (8k, sharp focus, trending on artstation, masterpiece,
    // cinematic lighting etc. - termos que praticamente só aparecem em
    // prompt de imagem, nunca em conversa normal) E não parece uma
    // pergunta (sem "?" e sem palavras interrogativas), trata como
    // intenção de gerar imagem também. Comprovado com controles
    // positivos (o prompt exato do print, outro prompt cru diferente) e
    // negativos (mensagem do dia a dia com vírgulas, pergunta técnica
    // mencionando os mesmos termos, mensagem fraca com só 1 termo) - ver
    // prova_testes/test_image_intent_heuristic.mjs.
    const IMAGE_PROMPT_MAGIC_TOKENS =
      /\b(8k|4k|hyper-?detailed|ultra-?detailed|highly detailed|sharp focus|cinematic (lighting|composition)|trending on artstation|artstation|octane render|unreal engine|concept art|masterpiece|volumetric (lighting|smoke)|god rays|photorealistic|ultra realistic|digital painting|dramatic (lighting|rim lighting)|intricate (detail|feather detail))\b/gi;

    // PHX-FIX (achado real via screenshot do usuário 2026-08-28: pergunta
    // genuína "vou usar rocm, cuda ou vulkan? pra gerar imagens, como
    // faço? comfyui ou sd server?" gerou uma imagem em vez de responder -
    // "gerar imagem" tem duplo sentido, e ali era claramente uma dúvida,
    // não um comando). Antes só existia dentro de looksLikeRawImagePrompt();
    // virou função compartilhada porque agora o regex de verbo+substantivo
    // logo abaixo também precisa dela, por ORAÇÃO (ver comentário mais
    // abaixo do porquê).
    function looksLikeQuestion(t: string): boolean {
      return /\?|\b(o que|como|por que|porque|qual|quando|onde|quem|será que|why|how|what|when|where|who|explain|explique)\b/i.test(t);
    }

    function looksLikeRawImagePrompt(t: string): boolean {
      const commaSegments = t.split(",").length;
      const magicHits = (t.match(IMAGE_PROMPT_MAGIC_TOKENS) || []).length;
      return !looksLikeQuestion(t) && commaSegments >= 4 && magicHits >= 2;
    }

    const IMAGE_GENERATION_VERB_NOUN_PATTERN =
      /\b(ger[ae]\w*|cri[ae]\w*|desenh[ae]\w*|produz[ae]\w*|generate|create|draw)\b[^.!?\n]{0,40}\b(imagem|imagens|figura|ilustra[cç][aã]o|foto|picture|image|images|artwork)\b/i;

    // PHX-FIX (mesmo achado acima): o regex de verbo+substantivo batia na
    // MENSAGEM INTEIRA como uma string só - "pra gerar imagens, como
    // faço?" contém o par "gerar"..."imagens" (dispara o regex) mesmo a
    // mensagem sendo, como um todo, uma pergunta técnica sobre backend de
    // GPU (rocm/cuda/vulkan) pra geração de imagem, não um pedido pra
    // gerar uma imagem agora. looksLikeQuestion() já existia mas só era
    // usado dentro de looksLikeRawImagePrompt() (heurística separada, pra
    // prompt "cru" estilo Stable Diffusion) - nunca entrava aqui. Fix:
    // separa o texto em orações (delimitadas por . ! ?) e só considera
    // intenção de imagem se ALGUMA oração isolada bate no regex de
    // verbo+substantivo E aquela mesma oração, sozinha, não parece uma
    // pergunta - "Gere uma imagem de um gato." ainda dispara mesmo se a
    // frase seguinte for uma pergunta; "pra gerar imagens, como faço?"
    // não dispara porque a própria oração termina em "?". Comprovado com
    // controle negativo (o exato print do usuário) e positivo (comando
    // direto de geração intacto) - ver prova_testes/test_image_intent_double_meaning.mjs.
    function hasImageGenerationVerbNounInNonQuestionClause(t: string): boolean {
      const clauses = t.split(/(?<=[.!?])\s*/).filter((c) => c.trim().length > 0);
      const clausesToCheck = clauses.length > 0 ? clauses : [t];
      return clausesToCheck.some(
        (clause) => IMAGE_GENERATION_VERB_NOUN_PATTERN.test(clause) && !looksLikeQuestion(clause)
      );
    }

    const legacyImageGenerationIntent = hasImageGenerationVerbNounInNonQuestionClause(text) || looksLikeRawImagePrompt(text);
    // O detector local é uma segunda trava deliberada. Se uma versão antiga
    // do Arbiter classificar um comando explícito em inglês como "chat", o
    // prompt ainda vai para Phoenix Diffusion em vez do provedor de texto.
    // A heurística local já exclui perguntas por oração, portanto o OR não
    // reintroduz o falso positivo "como faço para gerar imagens?".
    const isImageGenerationIntent =
      arbiterDecision.intent === 'image_generation' || legacyImageGenerationIntent;

    if (isImageGenerationIntent) {
      try {
        const response = await fetch('/api/generate-image', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ prompt: text, model_hint: imageModelHint || '' }),
        });
        const data = await parseJsonResponse<any>(response);
        if (!response.ok || !data || data.error || data.ok === false) {
          throw new Error((data && (data.error || data.detail)) || `Erro ${response.status} ao gerar a imagem.`);
        }

        const assistantMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: `Imagem gerada com **${data.model || 'modelo local de imagem'}**.`,
          image: `data:${data.mime_type || 'image/png'};base64,${data.image_base64}`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: 'Phoenix Diffusion',
          // PHX-FIX (achado real do usuário 2026-08-24: perguntou "seu nome
          // e modelo?" pro qwen3-8b logo depois de gerar uma imagem, e ele
          // respondeu se identificando como "Phoenix Aviary Platform...
          // Flux 1-Schnell" - o motor de IMAGEM, não ele mesmo): esta
          // mensagem é um AVISO da Phoenix sobre o que o motor SDXL/Flux
          // (sd_cpp.py) fez, nunca algo que o modelo de texto selecionado
          // realmente disse. Ver types.ts::ChatMessage.excludeFromHistory -
          // sendToProvider() em AviaryApp.tsx não reenvia mensagens com esta
          // flag como histórico de conversa pro provedor de texto.
          excludeFromHistory: true,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, assistantMsg] } : c)));
      } catch (err: any) {
        const errorMsg: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: 'Falha ao gerar a imagem.',
          error: describeNonJsonError(err) || 'Verifique se o Phoenix Engine (porta 8000) está ativo e um modelo de imagem (SDXL/Flux) já foi baixado.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          modelId: 'Phoenix Diffusion',
          excludeFromHistory: true,
        };
        setConversations((prev) => prev.map((c) => (c.id === convId ? { ...c, messages: [...updatedMessages, errorMsg] } : c)));
      } finally {
        setIsLoading(false);
      }
      return;
    }

    await sendToProvider(updatedMessages);
  };

  const handleRegenerate = async () => {
    if (!activeConversation || activeConversation.messages.length === 0) return;
    const lastUserMsgIndex = [...activeConversation.messages].reverse().findIndex((m) => m.role === 'user');
    if (lastUserMsgIndex === -1) return;

    const actualUserIndex = activeConversation.messages.length - 1 - lastUserMsgIndex;
    const trimmedMsgs = activeConversation.messages.slice(0, actualUserIndex + 1);
    const lastUserMsg = trimmedMsgs[trimmedMsgs.length - 1];

    // PHX-FIX (auditoria platform_source 2026-08-20, achado A4): antes,
    // regenerar uma resposta chamava handleSendMessage(content, files) SEM
    // o 3º argumento (rawFiles) - o Map<string,File> com os bytes brutos de
    // imagem/documento, que só existe efemeramente em ChatView.tsx durante
    // o envio original e nunca é persistido (File não é serializável, não
    // vai pro localStorage). Resultado: pra uma pergunta original como
    // "descreva esta imagem"/"resuma este PDF", regenerar SILENCIOSAMENTE
    // caía no chat de texto genérico sem a imagem/documento anexado -
    // resposta sem relação com o que foi realmente pedido, sem avisar o
    // usuário que o anexo binário tinha ficado pra trás. Agora, se a
    // mensagem original tinha um anexo binário (imagem ou PDF/DOCX/XLSX/
    // PPTX), regenerar é bloqueado com um aviso claro em vez de mandar um
    // request degradado - pede pro usuário reanexar o arquivo.
    const hadBinaryAttachment = (lastUserMsg.files || []).some(
      (f) => f.isImage || /\.(pdf|docx|xlsx|pptx)$/i.test(f.name)
    );
    if (hadBinaryAttachment) {
      const warnMsg: ChatMessage = {
        id: Math.random().toString(36).substring(2, 9),
        role: 'assistant',
        content: 'Não é possível regenerar esta resposta automaticamente.',
        error: 'A mensagem original tinha uma imagem ou documento anexado. O arquivo bruto não fica guardado entre uma resposta e outra (não é salvo no navegador) - reanexe o arquivo e envie a pergunta novamente.',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        modelId: selectedModelId,
      };
      setConversations((prev) =>
        prev.map((c) => (c.id === activeConversation.id ? { ...c, messages: [...trimmedMsgs, warnMsg] } : c))
      );
      return;
    }

    setConversations((prev) =>
      prev.map((c) => (c.id === activeConversation.id ? { ...c, messages: trimmedMsgs } : c))
    );
    await handleSendMessage(lastUserMsg.content, lastUserMsg.files || []);
  };

  const handleExecuteArena = async (
    arenaSlots: ArenaSlot[],
    prompt: string,
    onUpdateSlots: (updatedSlots: ArenaSlot[]) => void
  ) => {
    setIsLoading(true);
    onUpdateSlots(
      arenaSlots.map((s) => ({
        ...s,
        isLoading: true,
        currentResponse: '',
        thinking: undefined,
        error: undefined,
        metrics: undefined,
      }))
    );

    const updatedSlotsPromises = arenaSlots.map(async (slot) => {
      const modelObj = availableModels.find((m) => m.id === slot.modelId);
      const providerObj = providers.find((p) => p.id === modelObj?.providerId) || providers[0];

      try {
        let endpoint = '/api/gemini/chat';
        let payload: any = {
          model: slot.modelId,
          messages: [{ role: 'user', text: prompt }],
          systemInstruction: parameters.systemInstruction,
          temperature: parameters.temperature,
        };

        if (providerObj.type !== 'gemini') {
          endpoint = '/api/proxy/chat';
          payload = {
            providerType: providerObj.type,
            baseUrl: providerObj.baseUrl,
            apiKey: providerObj.apiKey,
            model: slot.modelId,
            messages: [{ role: 'user', text: prompt }],
            systemInstruction: parameters.systemInstruction,
            temperature: parameters.temperature,
          };
        }

        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok || data.error) {
          throw new Error(data.error || 'Erro no provedor');
        }

        let respText = data.text || '';
        let thinkingText = '';
        // PHX-FIX (2026-09-06): mesma correção do outro caminho de chat -
        // ver comentário completo em sendToProvider() acima.
        if (data.reasoning) {
          thinkingText = data.reasoning;
        } else {
          const thinkMatch = respText.match(/<think>([\s\S]*?)<\/think>/i);
          if (thinkMatch) {
            thinkingText = thinkMatch[1].trim();
            respText = respText.replace(/<think>[\s\S]*?<\/think>/gi, '').trim();
          } else {
            const openThinkIdx = respText.search(/<think>/i);
            if (openThinkIdx !== -1) {
              thinkingText = respText.slice(openThinkIdx + '<think>'.length).trim();
              respText = respText.slice(0, openThinkIdx).trim();
            }
          }
        }

        return {
          ...slot,
          isLoading: false,
          currentResponse: respText,
          thinking: thinkingText,
          metrics: data.usage,
          error: undefined,
        };
      } catch (err: any) {
        return {
          ...slot,
          isLoading: false,
          currentResponse: '',
          error: err.message || 'Falha ao conectar com o modelo',
        };
      }
    });

    const finalSlots = await Promise.all(updatedSlotsPromises);
    onUpdateSlots(finalSlots);
    setIsLoading(false);
  };

  // PHX-NEW (pedido do usuário 2026-08-22: "poderíamos usar o arena pra
  // fazer isso... deixar debate tanto no chat qto no arena"): mesma chamada
  // ao /api/dual-collab que o comando /colaborar do chat já usa - só uma
  // segunda porta de entrada (dropdowns no Arena em vez de flags de texto).
  // Não duplica lógica de orquestração nenhuma; devolve o JSON cru pro
  // ArenaView renderizar o transcript à sua maneira.
  const handleExecuteCollab = async (topic: string, cpuModelId: string, gpuModelId: string): Promise<any> => {
    const response = await fetch('/api/dual-collab', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, max_rounds: 6, cpu_model: cpuModelId, gpu_model: gpuModelId }),
    });
    const data = await parseJsonResponse<any>(response);
    if (!response.ok || !data || data.error) {
      throw new Error((data && data.error) || `Erro ${response.status} na colaboração.`);
    }
    return data;
  };

  // PHX-NEW (2026-08-22, pedido do usuário depois de ver a Arena com a
  // ampulheta piscando o tempo inteiro até as 6 rodadas terminarem TODAS
  // de uma vez, "dá aquela ideia de que travou"): leitura RÁPIDA e
  // não-bloqueante do progresso da colaboração em andamento - chamada em
  // POLLING pelo ArenaView ENQUANTO handleExecuteCollab acima ainda está
  // pendente, pra mostrar cada rodada assim que ela termina. Uma falha
  // aqui (rede momentânea, etc.) NUNCA deve interromper a colaboração
  // principal - devolve null em vez de lançar, e quem chama simplesmente
  // ignora aquela leitura e tenta de novo na próxima.
  const handlePollCollabProgress = async (): Promise<{ active: boolean; topic: string; transcript: any[] } | null> => {
    try {
      const response = await fetch('/api/dual-collab/progress');
      if (!response.ok) return null;
      const data = await parseJsonResponse<any>(response);
      if (!data || data.error) return null;
      return data;
    } catch {
      return null;
    }
  };

  // PHX-NEW (pedido do usuário 2026-08-22: "pode por o clip igual no
  // chatbot pra usuário subir (pescar) qualquer arquivo compatível como
  // ja funciona no chatbot" - na aba Colaboração do Arena): processa um
  // arquivo anexado e devolve o texto pra injetar no "topic" da
  // colaboração. Reaproveita EXATAMENTE as mesmas pontes que
  // handleSendMessage já usa pro chat normal - /api/describe-image,
  // /api/transcribe - e a única rota nova é /api/documents/extract-raw
  // (extração de texto pura, sem chamada de LLM, ao contrário de
  // /api/documents/read que o chat usa - ver LEIA-ME desta entrega pro
  // porquê). `currentTopic` vira o `prompt` da descrição de imagem, igual
  // ao texto digitado pelo usuário no chat guia a descrição lá.
  const handleProcessCollabAttachment = async (file: File, currentTopic: string): Promise<string> => {
    const lowerName = file.name.toLowerCase();
    const isImg = file.type.startsWith('image/');
    const isDocument = /\.(pdf|docx|xlsx|pptx)$/i.test(lowerName);
    const isAudio = /\.(mp3|wav|m4a|ogg|flac|aac|webm)$/i.test(lowerName);

    if (isImg) {
      const formData = new FormData();
      formData.append('file', file, file.name);
      formData.append('mode', 'describe');
      if (currentTopic.trim()) formData.append('prompt', currentTopic);
      const response = await fetch('/api/describe-image', { method: 'POST', body: formData });
      const data = await parseJsonResponse<any>(response);
      if (!response.ok || !data || data.error) {
        throw new Error((data && data.error) || `Erro ${response.status} ao analisar a imagem anexada.`);
      }
      return data.text || '';
    }

    if (isDocument) {
      const formData = new FormData();
      formData.append('file', file, file.name);
      const response = await fetch('/api/documents/extract-raw', { method: 'POST', body: formData });
      const data = await parseJsonResponse<any>(response);
      if (!response.ok || !data || data.error) {
        throw new Error((data && data.error) || `Erro ${response.status} ao extrair o documento anexado.`);
      }
      return data.text || '';
    }

    if (isAudio) {
      const formData = new FormData();
      formData.append('file', file, file.name);
      formData.append('language', 'pt');
      const response = await fetch('/api/transcribe', { method: 'POST', body: formData });
      const data = await parseJsonResponse<any>(response);
      if (!response.ok || !data || data.ok === false || data.error) {
        throw new Error((data && (data.error || data.detail)) || `Erro ${response.status} ao transcrever o áudio anexado.`);
      }
      return data.text || '';
    }

    throw new Error(`Tipo de arquivo não suportado: ${file.name}`);
  };

  // PHX-NEW (pedido do usuário 2026-08-22: "usuario pode continuar via
  // chatbot ou modo arena/colaboração"): leva o resultado da colaboração
  // de volta pra conversa ativa do chat - se nenhuma conversa existir
  // ainda (usuário abriu direto no Arena), cria uma nova, mesmo padrão de
  // handleSendMessage acima. Depois troca de volta pra aba do chat, pra
  // o usuário já ver o resultado e continuar dali.
  const handleSendCollabResultToChat = (resultText: string) => {
    let convId = activeConversationId;
    let convList = [...conversations];

    if (!convId || !activeConversation) {
      const newConv: Conversation = {
        id: Math.random().toString(36).substring(2, 9),
        title: 'Colaboração entre dois modelos',
        modelId: selectedModelId,
        providerType: availableModels.find((m) => m.id === selectedModelId)?.providerType || 'gemini',
        createdAt: new Date().toLocaleDateString(),
        updatedAt: new Date().toLocaleTimeString(),
        messages: [],
        parameters: { ...parameters },
      };
      convList = [newConv, ...convList];
      convId = newConv.id;
      setActiveConversationId(newConv.id);
    }

    const resultMsg: ChatMessage = {
      id: Math.random().toString(36).substring(2, 9),
      role: 'assistant',
      content: resultText,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    };

    const targetConv = convList.find((c) => c.id === convId)!;
    setConversations(
      convList.map((c) => (c.id === convId ? { ...c, messages: [...targetConv.messages, resultMsg] } : c))
    );
    setActiveTab('chat');
  };

  return (
    <div className="flex-1 flex flex-col h-full overflow-hidden bg-[#0b0d10] text-[#e7e7e7]">
      {/* Aviary Header */}
      <AviaryHeader
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        providers={providers}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onToggleParameters={() => setIsParamsOpen(!isParamsOpen)}
        onOpenManual={() => setIsManualOpen(true)}
        onOpenStandalone={onOpenStandalone}
        engineOnline={engineOnline}
      />

      {/* Main Aviary View Area */}
      <div className="flex-1 flex overflow-hidden relative">
        {activeTab === 'chat' && (
          <ChatView
            conversations={conversations}
            activeConversation={activeConversation}
            onSelectConversation={(id) => setActiveConversationId(id)}
            onNewConversation={handleNewConversation}
            onDeleteConversation={handleDeleteConversation}
            onSendMessage={handleSendMessage}
            onRegenerateMessage={handleRegenerate}
            isLoading={isLoading}
            providers={providers}
            availableModels={availableModels}
            selectedModelId={selectedModelId}
            onSelectModel={(modelId) => setSelectedModelId(modelId)}
            parameters={parameters}
            onToggleParameters={() => setIsParamsOpen(!isParamsOpen)}
            onScanProviders={handleScanAllProviders}
            isScanning={isScanning}
            onOpenStandalone={onOpenStandalone}
            engineOnline={engineOnline}
          />
        )}

        {activeTab === 'arena' && (
          <ArenaView
            availableModels={availableModels}
            onExecuteArena={handleExecuteArena}
            onExecuteCollab={handleExecuteCollab}
            onPollCollabProgress={handlePollCollabProgress}
            onProcessAttachment={handleProcessCollabAttachment}
            activeConversation={activeConversation}
            onSendResultToChat={handleSendCollabResultToChat}
            isLoading={isLoading}
          />
        )}

        {activeTab === 'hub' && (
          <ModelHubView
            onScanProviders={handleScanAllProviders}
            onSelectModelForChat={(modelName) => {
              setSelectedModelId(modelName);
              setActiveTab('chat');
            }}
          />
        )}

        {activeTab === 'vram' && <VramCalculatorView />}

        {activeTab === 'stack' && (
          <EcosystemView
            providers={providers}
            onOpenSettings={() => setIsSettingsOpen(true)}
            onUpdateProvider={handleUpdateProvider}
            onTestProvider={handleTestProvider}
            hasGeminiKey={hasGeminiKey}
          />
        )}

        {/* PHX-NEW (2026-08-23, pedido do usuário: "o inverso da transcrição" -
            ferramenta dedicada de texto para áudio, "as duas coisas" junto com
            o botão de download inline no chat). Zero props, igual ao padrão
            do VramCalculatorView - é uma ferramenta autocontida. */}
        {activeTab === 'voice' && <TextToSpeechView />}

        {/* Parameters Sidebar */}
        <ParametersDrawer
          isOpen={isParamsOpen && activeTab === 'chat'}
          onClose={() => setIsParamsOpen(false)}
          parameters={parameters}
          onChangeParameters={(updated) => setParameters(updated)}
        />
      </div>

      {/* Modals */}
      <ProviderSettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        providers={providers}
        onUpdateProvider={handleUpdateProvider}
        onTestProvider={handleTestProvider}
        hasGeminiKey={hasGeminiKey}
      />

      <ManualModal
        isOpen={isManualOpen}
        onClose={() => setIsManualOpen(false)}
        workspacePath={workspacePath}
      />
    </div>
  );
};
