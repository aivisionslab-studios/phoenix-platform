import express from "express";
import path from "path";
import dns from "dns";
import net from "net";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI } from "@google/genai";
import dotenv from "dotenv";
// PHX-NEW: Document Engine - multer faz o parse de multipart/form-data em
// memória, sem passar pelo express.json({limit:"25mb"}) abaixo. Isso é o
// que resolve de verdade o caso de PDF grande (o describe-image acima já
// tinha esse problema em potencial via "body: req as any" - stream
// passthrough sem duplex:'half' explícito é frágil em Node recente;
// multer é a abordagem testada e comprovada nesta integração).
import multer from "multer";
import { Agent as UndiciAgent, FormData as UndiciFormData, fetch as undiciFetch } from "undici";

// Use fetch e Agent da mesma versão do Undici. Misturar o fetch embutido do
// Node com um dispatcher de outro major quebra os timeouts customizados.
const fetch = undiciFetch as unknown as typeof globalThis.fetch;
const FormData = UndiciFormData as unknown as typeof globalThis.FormData;

dotenv.config();

// PHX-FIX (achado real, depois do conserto do "/v1/v1" duplicado): o
// usuário reportou que o 404 sumiu mas apareceu um erro NOVO e diferente
// - "Proxy request failed: fetch failed" - que vem do catch() genérico
// de rede em /api/proxy/chat (fetch() lançou exceção ANTES de qualquer
// resposta HTTP chegar, não é mais um 404). Isso é a assinatura clássica
// de um bug de Windows+Node: o llama-server é subido com '--host
// 127.0.0.1' (IPv4 puro, ver llama_cpp.py), mas o baseUrl configurado
// usa o literal "localhost" - e no Windows o resolvedor de DNS do
// Node/undici costuma devolver o endereço IPv6 "::1" ANTES do IPv4
// "127.0.0.1" pra "localhost", e o fetch() tenta conectar só no
// primeiro endereço, sem tentar o IPv4 depois. Como nada escuta em
// "::1:8081" (só em 127.0.0.1:8081), a conexão é recusada e o fetch()
// lança "fetch failed" sem nem chegar a fazer a requisição HTTP. Esta é
// a correção oficial documentada pelo próprio Node pra essa classe de
// bug (nodejs.org/api/dns.html#dnssetdefaultresultorderorder) - força
// IPv4 primeiro pra QUALQUER dns.lookup deste processo (usado
// internamente pelo fetch/undici), sem precisar reescrever toda URL
// "localhost" espalhada pelo código. Não muda nada em Linux/Mac, onde
// esse problema normalmente não ocorre.
dns.setDefaultResultOrder("ipv4first");

const configuredPort = Number.parseInt(process.env.PHOENIX_PLATFORM_PORT || "3000", 10);
const PORT = Number.isFinite(configuredPort) ? configuredPort : 3000;
const HOST = process.env.PHOENIX_PLATFORM_HOST || "127.0.0.1";

// Lazy Gemini API Client Initialization
let aiClient: GoogleGenAI | null = null;
function getGeminiClient(): GoogleGenAI | null {
  if (!aiClient) {
    const key = process.env.GEMINI_API_KEY;
    if (!key || key === "MY_GEMINI_API_KEY" || key.trim() === "") {
      return null;
    }
    aiClient = new GoogleGenAI({
      apiKey: key,
      httpOptions: {
        headers: {
          "User-Agent": "aistudio-build",
        }
      }
    });
  }
  return aiClient;
}

const PHOENIX_ENGINE_URL = (process.env.PHOENIX_ENGINE_URL || "http://localhost:8000").replace(/\/$/, "");

// PHX-FIX (varredura 2026-08-21, "verificar e consertar" - achado real
// reportado pelo usuário com screenshots do app rodando de verdade:
// /api/documents/read falhou duas vezes seguidas com "Phoenix Engine
// offline ou inacessível: fetch failed" enquanto o indicador "Engine :8000
// [OK]" no topo continuava verde - ou seja, o /health estava respondendo
// normalmente ao mesmo tempo que este fetch() específico falhava. Uma
// auditoria completa do caminho (server.ts -> api_server.py ->
// ResidentManager -> LlamaCppDriver) não achou nenhum bug de código capaz
// de produzir esse sintoma exato (toda falha interna já conhecida vira uma
// resposta JSON de erro, não uma queda de conexão crua) - o que sobra são
// causas de rede/SO reais (antivírus interceptando POST com anexo binário,
// o processo do Engine reiniciando bem no meio do request, etc). O que ERA
// um bug de verdade: `err.message` sozinho, pra um erro de fetch() do
// Node/undici, quase sempre vem genérico ("fetch failed") - o motivo real
// (ECONNRESET, ECONNREFUSED, timeout de socket...) fica em `err.cause` e
// era descartado em TODOS os ~21 lugares deste arquivo que devolvem essa
// mensagem. Sem isso, nem o usuário nem quem for investigar um relato como
// este tem como saber SE ERA o Engine reiniciando, uma conexão recusada, ou
// outra coisa - próxima vez que isso acontecer, a causa real aparece.
// PHX-FIX (varredura 2026-08-21, achado real confirmado com o próprio log
// de produção do usuário - "Endpoint retornou fetch failed (causa:
// UND_ERR_HEADERS_TIMEOUT)" ao tentar resumir um PDF/DOCX "muito grande"):
// o AbortController de cada rota abaixo (240s/540s/540s/660s) foi pensado
// como O timeout real - mas o `fetch()` nativo do Node roda sobre o
// undici, cujo dispatcher GLOBAL tem seu PRÓPRIO headersTimeout/bodyTimeout
// padrão de 300_000ms (5min), completamente independente do nosso
// AbortController. Pra qualquer requisição que passe de 5min (documento
// grande, PDF com muitas páginas, DOCX com muitas tabelas, transcrição de
// áudio longo), o undici derruba a conexão sozinho ANTES do nosso
// AbortController de 9-11min sequer ter chance de agir - o código de
// "Tempo esgotado esperando o Phoenix Engine..." (isAbort) nunca era
// alcançável nessas 4 rotas, na prática, pra nenhum request realmente
// lento; o usuário só via o "fetch failed" genérico do catch, sem
// explicação nenhuma do que houve. Reproduzido localmente com um servidor
// de teste lento + um Agent do undici com headersTimeout curto: o mesmo
// "fetch failed" com causa "UND_ERR_HEADERS_TIMEOUT" apareceu, confirmando
// a causa raiz. Fix: um dispatcher próprio, com headersTimeout/bodyTimeout
// folgados acima do MAIOR AbortController deste arquivo (660s), passado
// explicitamente pra essas 4 chamadas de fetch() de longa duração -
// dispatcher's timeout nunca dispara primeiro, e o AbortController de cada
// rota volta a ser quem realmente decide quando desistir.
//
// PHX-FIX (2026-08-22, relato real do usuário: "phoenix deu timeout, mas
// gerou imagem" - print do Task Manager com a GPU em 99-100% por vários
// minutos seguidos, erro "fetch failed (causa: UND_ERR_HEADERS_TIMEOUT)" na
// hora, e a imagem aparecendo pronta em disco/na UI logo depois): a rota
// /api/generate-image (abaixo) ficou de fora da varredura de 2026-08-21 que
// adicionou este dispatcher às outras 4 rotas de longa duração - mesma
// causa raiz, exatamente o mesmo sintoma. Geração de imagem com
// --vae-on-cpu (fix anterior pro OOM de VRAM do SDXL - decode do VAE agora
// roda na CPU, bem mais lento que na GPU) pode legitimamente passar dos 5min
// do headersTimeout padrão do undici nesse hardware (Xeon E5-2690 v3 sem
// GPU real pro VAE). O subprocess do sd.cpp em si só desiste depois de
// 2700s/45min (ver `timeout=2700.0` em
// phoenix_kernel/runtime/drivers/sd_cpp.py) - MUITO acima do headersTimeout
// de 720_000ms (12min) deste dispatcher, que também precisa subir, senão só
// trocaríamos "undici mata em 5min" por "undici mata em 12min", mesmo bug.
// Subido pra 2_820_000ms (47min) - 60s de folga acima do novo
// AbortController de 2_760_000ms (46min) da rota /api/generate-image, que
// por sua vez tem 60s de folga acima do teto real de 2700s do driver -
// mesmo padrão de margem usado nas outras 4 rotas.
//
// PHX-FIX (achado real do usuário 2026-08-24, "Falha ao obter resposta do
// modelo... fetch failed (causa: Headers Timeout Error)" numa pergunta
// ampla que gerou resposta longa): duas coisas encontradas ao investigar.
//
// (1) Achado NOVO, principal: /api/proxy/chat (a rota que faz a chamada de
// chat de verdade pro llama-server/Ollama) nunca tinha nem `dispatcher` nem
// `AbortController` nenhum no seu fetch() - dependia 100% do padrão global
// de 300s do undici, exatamente a MESMA causa raiz já documentada acima
// pras outras rotas, só que nunca aplicada a esta. O payload do chat manda
// `stream: false` (ver buildChatRequest) - o llama-server não manda UM
// byte, nem os headers, até terminar de gerar a resposta INTEIRA. Depois da
// v54 (contexto subiu de 8192 pra 16384 tokens) e do próprio pedido do
// usuário por respostas "mais longas e coerentes", uma resposta longa na
// taxa real medida nesta máquina (~4.6 tok/s, CPU pura) passa fácil dos
// 300s do undici bem antes de chegar perto do teto de tokens configurado -
// exatamente o padrão reproduzido no relato (pergunta ampla, resposta
// estruturada longa). Fix: dispatcher + AbortController dinâmico (escalado
// pelo `maxTokens` do pedido, mesmo método já usado no timeout do Kokoro
// TTS) adicionados a /api/proxy/chat - ver PHX-FIX na própria rota abaixo.
//
// (2) Achado ADJACENTE (bug pré-existente, achado de graça auditando o
// mesmo dispatcher): /api/documents/synthesize-audiobook (abaixo) já usava
// este dispatcher com um AbortController de 5_520_000ms (92min) - só que o
// teto do dispatcher em si (2_820_000ms/47min) era MENOR que isso. Ou seja,
// pra qualquer audiolivro que passasse de 47min de geração, o undici já
// derrubava a conexão sozinho bem antes dos 92min "configurados" da rota
// terem qualquer chance de agir - o mesmo bug de fundo, sem ninguém ter
// percebido porque a maioria dos documentos processados até agora deve ter
// terminado antes dos 47min. Corrigido subindo o teto do dispatcher pra
// cobrir o maior AbortController real que o usa (o do audiolivro, ainda o
// maior mesmo depois do fix do chat abaixo).
//
// Novo teto: 5_580_000ms (93min) - 60s de folga acima dos 5_520_000ms
// (92min) do audiolivro, que continua sendo o maior AbortController que usa
// este dispatcher. Isso só AUMENTA a folga de todas as outras rotas que já
// usavam este dispatcher (nenhuma delas fica pior) - o comportamento de
// cada uma continua decidido pelo próprio AbortController, nunca pelo
// dispatcher, exatamente como já era.
//
// PHX-FIX (2026-09-06, mesma rodada do aumento de contexto 16384->32768 em
// /api/proxy/chat, ver PHX-FIX completo na própria rota): o chat agora
// pode legitimamente precisar de até ~165min (CHAT_MAX_TIMEOUT_MS =
// 9_900_000ms, pior caso pra 32768 tokens a 300ms/tok, incluindo o
// "Sem limite" que orça pelo contexto cheio) - isso PASSOU a ser maior
// que o teto de 93min calibrado só pro audiolivro, recriando o mesmo bug
// de fundo já documentado acima (dispatcher mais curto que o
// AbortController real de quem o usa, matando a conexão em silêncio antes
// do timeout "configurado" da rota ter qualquer chance de agir). Subido de
// novo, mesma lógica: 60s de folga acima do maior AbortController real
// (agora o chat, não mais o audiolivro) = 9_960_000ms (~166min).
const longRunningDispatcher = new UndiciAgent({
  headersTimeout: 9_960_000,
  bodyTimeout: 9_960_000,
  connectTimeout: 10_000,
});

function describeFetchError(err: unknown): string {
  const e = err as { message?: string; cause?: unknown } | null | undefined;
  const message = e?.message || "erro de rede";
  const cause = e?.cause as { code?: string; message?: string } | undefined;
  if (cause) {
    const causeDetail = cause.code || cause.message || String(cause);
    if (causeDetail && !message.includes(causeDetail)) {
      return `${message} (causa: ${causeDetail})`;
    }
  }
  return message;
}

// PHX-FIX (auditoria platform_source 2026-08-20, achado A7): /api/proxy/ping
// e /api/proxy/chat recebem `baseUrl` do FRONTEND (uma página no navegador
// do usuário) e o servidor Node faz fetch() nele - útil pra apontar pra
// Ollama/LM Studio/llama-server locais, mas sem validação nenhuma isso é um
// SSRF clássico: qualquer script rodando na página (extensão maliciosa, XSS
// em outra aba, um site aberto ao mesmo tempo fazendo POST pra
// localhost:3000) podia mandar o servidor Node buscar QUALQUER endereço
// acessível pela máquina/rede onde ele roda - incluindo endpoints de
// metadata de nuvem (169.254.169.254, presente em EC2/GCE/Azure e fonte
// clássica de exfiltração de credenciais via SSRF) ou serviços internos que
// nunca deveriam ser alcançáveis a partir de uma página web.
//
// Allowlist, não denylist: só permite loopback (localhost/127.0.0.1/::1) e
// faixas privadas RFC1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) -
// exatamente onde Ollama/LM Studio/llama-server realmente rodam (mesma
// máquina ou mesma rede local). Hostname que não é IP literal é resolvido
// via DNS e TODOS os endereços resolvidos precisam cair numa faixa
// permitida (mitiga DNS rebinding apontando pra um IP interno depois do
// primeiro request). Esquema tem que ser http:/https: - nada de file:,
// gopher:, etc.
function isAllowedProxyAddress(ip: string): boolean {
  // IPv6 loopback e faixa "unique local" (fc00::/7, equivalente privado do IPv6).
  if (ip === "::1") return true;
  if (/^f[cd][0-9a-f]{2}:/i.test(ip)) return true;

  const parts = ip.split(".").map((p) => parseInt(p, 10));
  if (parts.length !== 4 || parts.some((p) => Number.isNaN(p) || p < 0 || p > 255)) {
    return false; // não é um IPv4 literal reconhecível - trata como não permitido
  }
  const [a, b] = parts;
  if (a === 127) return true; // 127.0.0.0/8 - loopback
  if (a === 10) return true; // 10.0.0.0/8
  if (a === 172 && b >= 16 && b <= 31) return true; // 172.16.0.0/12
  if (a === 192 && b === 168) return true; // 192.168.0.0/16
  // Deliberadamente NÃO permitido: 169.254.0.0/16 (link-local, inclui o
  // endpoint de metadata de nuvem 169.254.169.254), 0.0.0.0/8, e qualquer
  // outra faixa pública/reservada.
  return false;
}

async function resolveAllowedProxyTarget(rawUrl: string): Promise<{ ok: true; url: URL } | { ok: false; reason: string }> {
  // Só assume "http://" quando não há esquema NENHUM (ex: usuário digitou
  // "192.168.1.50:8081", forma abreviada aceita pra conveniência). Se já
  // tem um esquema explícito (ex: "gopher://", "file://"), parseia como
  // está - NÃO reescreve por cima -, senão um "gopher://127.0.0.1:6379/"
  // vira "http://gopher://..." (host vira "gopher", cai no branch de DNS e
  // falha por acidente, não por validação de verdade) em vez de ser
  // rejeitado explicitamente pelo motivo certo (esquema não-http).
  const hasExplicitScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(rawUrl);
  let url: URL;
  try {
    url = new URL(hasExplicitScheme ? rawUrl : `http://${rawUrl}`);
  } catch {
    return { ok: false, reason: "URL inválida." };
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { ok: false, reason: `Esquema '${url.protocol}' não permitido - use http:// ou https://.` };
  }

  const hostname = url.hostname;
  if (hostname.toLowerCase() === "localhost") {
    return { ok: true, url };
  }
  if (net.isIP(hostname)) {
    return isAllowedProxyAddress(hostname)
      ? { ok: true, url }
      : { ok: false, reason: `Endereço '${hostname}' fora das faixas permitidas (localhost/127.0.0.1/rede privada).` };
  }

  try {
    const records = await dns.promises.lookup(hostname, { all: true });
    if (records.length === 0) {
      return { ok: false, reason: `Não foi possível resolver '${hostname}'.` };
    }
    if (!records.every((r) => isAllowedProxyAddress(r.address))) {
      return { ok: false, reason: `'${hostname}' resolve pra fora das faixas permitidas (localhost/127.0.0.1/rede privada).` };
    }
    return { ok: true, url };
  } catch {
    return { ok: false, reason: `Não foi possível resolver '${hostname}'.` };
  }
}

async function startServer() {
  const app = express();

  app.use(express.json({ limit: "25mb" }));

  // PHX-FIX (auditoria 2026-08-20, "Frontend JSON error handling" / Seções
  // 10-11): achado real confirmado - áudio anexado no chat era lido como
  // texto por ChatView.tsx (bug já corrigido) e o payload JSON resultante
  // podia passar dos 25mb do express.json() acima. Sem este handler, o
  // erro `PayloadTooLargeError` (e qualquer outro erro de parse de body,
  // como JSON malformado) caía no handler de erro PADRÃO do Express, que
  // devolve uma página de erro HTML - exatamente o "Unexpected token '<',
  // <!DOCTYPE..." relatado pelo usuário quando o frontend tentava
  // response.json() nessa resposta. Agora qualquer erro de parse de body
  // sempre volta como JSON, então mesmo sem o fix do frontend (que já
  // trata isso com parseJsonResponse) o cliente nunca recebe HTML aqui.
  app.use((err: any, _req: express.Request, res: express.Response, next: express.NextFunction) => {
    if (err && (err.type === "entity.too.large" || err.status === 413)) {
      res.status(413).json({
        error: "Corpo da requisição excede o limite de 25MB. Anexos binários (áudio, imagem, documento) devem ir via multipart/form-data, não embutidos no JSON do chat.",
      });
      return;
    }
    if (err && err.type && String(err.type).startsWith("entity.parse")) {
      res.status(400).json({ error: "JSON da requisição malformado." });
      return;
    }
    next(err);
  });

  // PHX-NEW: multer só pra rotas de documento - memória, sem limite de
  // 25mb do express.json() (que não se aplica a multipart de qualquer
  // forma, mas deixamos explícito um limite generoso próprio).
  const documentUpload = multer({
    storage: multer.memoryStorage(),
    limits: { fileSize: 150 * 1024 * 1024 },
  });

  // Teto físico máximo do RAG: Pro = 100 MB. O Engine aplica 25 MB no Free.
  const ragUpload = multer({
    storage: multer.memoryStorage(),
    limits: { fileSize: 100 * 1024 * 1024 },
  });

  // CORS restrito ao próprio host por padrão. Instalações em LAN podem
  // acrescentar origens separadas por vírgula em PHOENIX_ALLOWED_ORIGINS.
  const allowedOrigins = new Set(
    (process.env.PHOENIX_ALLOWED_ORIGINS || "http://localhost:3000,http://127.0.0.1:3000")
      .split(",")
      .map((origin) => origin.trim())
      .filter(Boolean)
  );
  app.use((req, res, next) => {
    const origin = req.header("Origin");
    if (origin && !allowedOrigins.has(origin)) {
      res.status(403).json({ error: "Origem não autorizada." });
      return;
    }
    if (origin) res.header("Access-Control-Allow-Origin", origin);
    res.header("Vary", "Origin");
    res.header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS");
    res.header("Access-Control-Allow-Headers", "Origin, X-Requested-With, Content-Type, Accept, Authorization, x-api-key");
    if (req.method === "OPTIONS") {
      res.sendStatus(200);
      return;
    }
    next();
  });

  // PHX-NEW (fix real do "Execute Port Ping" / Topologia de Portas): rota
  // 100% local, não toca no Phoenix Engine (porta 8000) - serve só pra
  // medir a latência REAL do próprio processo Node/Aviary (porta 3000),
  // isolada do hop até o Python. Sem isso, "latência da Aviary" e
  // "latência do Engine" acabariam usando o mesmo número (ou, como
  // estava antes desta auditoria, um número fixo fabricado). Ver
  // EngineMissionControl.tsx, que chama isto e /api/health juntos a cada
  // 1s pra montar o painel PortBridgePanel.tsx com dado real.
  app.get("/api/ping", (_req, res) => {
    res.json({ ok: true, ts: Date.now() });
  });

  // API: Health check
  // PHX-FIX (auditoria completa — "tirar todos os fallbacks"): o catch
  // abaixo mandava um 502 e a função continuava e mandava uma SEGUNDA
  // resposta logo em seguida (o res.json({status:"ok", ...}) sempre
  // executava, com ou sem exceção) - resposta dupla
  // (ERR_HTTP_HEADERS_SENT), e essa rota específica é chamada pelo
  // frontend a cada 5s (App.tsx, checkHealth) - ou seja, o primeiro
  // health-check feito com o Phoenix Engine (porta 8000) offline já batia
  // nesse bug. O design aqui é intencional (o servidor Aviário em si está
  // "ok" mesmo se o Engine não estiver - por isso `engineOnline` é um
  // campo separado, não o status HTTP da resposta) - só faltava não mandar
  // a resposta de erro solta no meio do caminho.
  app.get("/api/health", async (_req, res) => {
    let engineOnline = false;
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 1500);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/health`, { signal: ctrl.signal });
      clearTimeout(t);
      engineOnline = r.ok;
    } catch {
      engineOnline = false;
    }

    res.json({
      status: "ok",
      hasGeminiKey: Boolean(process.env.GEMINI_API_KEY && process.env.GEMINI_API_KEY !== "MY_GEMINI_API_KEY"),
      phoenixEngineUrl: PHOENIX_ENGINE_URL,
      engineOnline,
      ports: {
        engine: { port: 8000, label: "Phoenix Engine", status: engineOnline ? "ONLINE" : "STANDBY" },
        aviary: { port: 3000, label: "Phoenix Aviary Platform", status: "ONLINE" }
      },
      timestamp: new Date().toISOString()
    });
  });

  // API: State (Phoenix 3.0 State Engine & AHDE bridge)
  app.get("/api/state", async (_req, res) => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/state`, { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        const data = await r.json();
        return res.json(data);
      }
      // Backend respondeu mas com erro HTTP
      const status = r.status;
      return res.status(502).json({ error: `Phoenix Engine devolveu status ${status}.` });
    } catch (err: any) {
      // Backend offline ou timeout — erro real, sem fallback inventado
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  const proxyEngineJson = async (
    res: express.Response,
    enginePath: string,
    method: "GET" | "POST" = "GET",
    timeoutMs = 5000,
  ) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const response = await fetch(`${PHOENIX_ENGINE_URL}${enginePath}`, {
        method,
        signal: ctrl.signal,
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok) {
        return res.status(response.status).json(
          payload || { error: `Phoenix Engine devolveu status ${response.status}.` }
        );
      }
      return res.json(payload);
    } catch (err: any) {
      return res.status(502).json({
        error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    } finally {
      clearTimeout(timer);
    }
  };

  app.get("/api/ahde/sensors", (_req, res) => proxyEngineJson(res, "/api/ahde/sensors"));
  app.get("/api/ahde/events", (req, res) => {
    const limit = Math.max(0, Math.min(Number.parseInt(String(req.query.limit || "50"), 10) || 50, 100));
    return proxyEngineJson(res, `/api/ahde/events?limit=${limit}`);
  });
  app.get("/api/ahde/snapshot", (_req, res) => proxyEngineJson(res, "/api/ahde/snapshot"));
  app.post("/api/ahde/scan", (_req, res) => proxyEngineJson(res, "/api/ahde/scan", "POST", 30000));
  app.get("/api/system/report", (_req, res) => proxyEngineJson(res, "/api/system/report"));
  // API: Pending Chat Messages (Phoenix 3.0 /api/chat/pending)
  // PHX-FIX (varredura 2026-08-21, achado 2): em falha/timeout, devolvia
  // {messages: []} com HTTP 200 - indistinguível de "genuinamente sem
  // mensagens pendentes". Sem consumidor no frontend hoje (rota mantida
  // como proxy honesto, mesmo padrão de /api/agents), mas agora expõe
  // engineOnline/note pra quem for chamar a rota diretamente saber a
  // diferença.
  app.get("/api/chat/pending", async (_req, res) => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 1000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/chat/pending`, { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        const data: any = await r.json();
        return res.json({ ...data, engineOnline: true });
      }
      return res.json({ messages: [], engineOnline: false, note: `Phoenix Engine devolveu status ${r.status}.` });
    } catch (err: any) {
      return res.json({ messages: [], engineOnline: false, note: `Phoenix Engine offline ou inacessível: ${err?.message || "erro de rede"}` });
    }
  });

  // API: Describe Image (MiniCPM-V 4.6 Vision endpoint)
  // PHX-FIX (auditoria platform_source 2026-08-20, achado A11): antes, esta
  // rota fazia stream passthrough bruto do request inteiro
  // (`headers: req.headers, body: req, duplex: "half"`) direto pro Phoenix
  // Engine - funciona, mas é mais frágil que o padrão usado nas rotas de
  // documento (multer + FormData): depende de comportamento consistente de
  // stream/duplex entre versões do Node, encaminha cabeçalhos do cliente
  // que não deveriam necessariamente ir pro upstream (ex: Host, Connection),
  // e não dá pra validar/limitar o upload antes de repassar. Como imagem
  // também é multipart, mesma receita de /api/documents/read: multer recebe
  // em memória, e reconstrói um FormData novo e limpo pro Phoenix Engine.
  app.post("/api/describe-image", documentUpload.single("file"), async (req, res) => {
    const file = req.file;
    const prompt = (req.body?.prompt as string) || "";
    if (!file) {
      res.status(400).json({ error: "Nenhuma imagem enviada (campo 'file' ausente)." });
      return;
    }
    try {
      const formData = new FormData();
      formData.append("file", new Blob([new Uint8Array(file.buffer)], { type: file.mimetype || "application/octet-stream" }), file.originalname);
      if (prompt.trim()) formData.append("prompt", prompt);

      // PHX-FIX (auditoria 2026-08-21, "corrigir tudo" - achado real de uma
      // auditoria externa: mismatch de timeout entre este proxy e o driver
      // Python): este AbortController estava em 180_000ms - o MESMO valor,
      // sem nenhuma margem, do timeout interno do subprocesso no
      // MtmdDriver (phoenix_kernel/runtime/drivers/mtmd_driver.py,
      // asyncio.wait_for(..., timeout=180.0)). Zero margem = corrida real:
      // o Node podia abortar bem na hora em que o Engine ia devolver seu
      // próprio erro controlado, trocando uma mensagem clara por um 504
      // genérico. Subido pra 240_000ms (4min), dando 60s de folga acima do
      // teto do driver - mesma margem usada em /api/documents/read|edit.
      //
      // PHX-FIX (pedido do usuário 2026-08-22, OCR real): mode=ocr (ver
      // api_server.py/resident_manager.py) usa um teto de driver maior
      // (OCR_PAGE_TIMEOUT_SECONDS=200s, contra 180s do describe comum) e
      // mais tokens de saída - subido pra 270_000ms (4.5min) pra manter a
      // mesma folga de 60s acima do MAIOR dos dois modos, já que este
      // proxy não sabe de antemão qual modo a requisição vai usar.
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 270_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/describe-image`, { method: "POST", body: formData, signal: controller.signal, dispatcher: longRunningDispatcher } as RequestInit & { dispatcher: UndiciAgent });
      clearTimeout(timeoutId);

      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      // PHX-FIX: antes, qualquer falha aqui (rede, timeout, Phoenix Engine
      // offline) caía num catch{} vazio que devolvia um texto fixo alegando
      // "imagem analisada com sucesso via MiniCPM-V" - uma resposta
      // fabricada, nunca vinda de análise real nenhuma. Isso escondia
      // falhas reais atrás de uma aparência de sucesso. Agora erro real
      // aparece como erro real.
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort ? "Tempo esgotado esperando o Phoenix Engine analisar a imagem (4min)." : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });

  // API: Synthesize Speech (Kokoro TTS native endpoint - motor trocado de
  // Piper pra Kokoro-82M em 2026-08-23, ver resident_manager.py). Sem
  // timeout artificial de propósito (diferente de /api/tts/piper acima) -
  // esta rota alimenta a ferramenta "Texto Livre", onde o usuário já sabe
  // que colou um texto grande e está disposto a esperar.
  app.post("/api/synthesize-speech", async (req, res) => {
    const { text, voice, length_scale } = req.body;
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/synthesize-speech`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: voice || "", length_scale }),
      });
      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      // PHX-FIX: mesmo motivo do describe-image acima - antes devolvia
      // ok:true com audio_base64 vazio numa falha real, fingindo sucesso.
      res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  // API: Generate Image (FLUX.1 / SDXL native endpoint)
  app.post("/api/generate-image", async (req, res) => {
    const { prompt, model_hint } = req.body;
    try {
      // PHX-FIX (auditoria platform_source 2026-08-20, achado A10): antes,
      // um model_hint ausente/vazio virava "flux" hardcoded aqui no proxy
      // Node - prendia a UI em Flux mesmo quando o Model Registry do Engine
      // (catalog/models.json, default_for_roles de "image_generation") já
      // sabe escolher o modelo certo sozinho. ModelRegistry.resolve() trata
      // hint vazio exatamente como "sem hint" (cai no default declarado no
      // catálogo), então repassar sem forçar nada dá o mesmo resultado hoje
      // e continua correto se o default do catálogo mudar no futuro.
      //
      // PHX-FIX (2026-08-22, "phoenix deu timeout, mas gerou imagem" - ver
      // comentário completo na declaração de `longRunningDispatcher` acima):
      // esta rota não tinha dispatcher NEM AbortController nenhum - rodava
      // no dispatcher global padrão do undici (headersTimeout de 5min), bem
      // abaixo do que uma geração SDXL com --vae-on-cpu pode legitimamente
      // levar neste hardware. Agora usa o mesmo longRunningDispatcher (já
      // com headroom pra isso) e um AbortController de 2_760_000ms (46min) -
      // 60s de folga acima do teto real de 2700s/45min do subprocess do
      // sd.cpp (ver `timeout=2700.0` em
      // phoenix_kernel/runtime/drivers/sd_cpp.py) - mesmo padrão de margem
      // das outras rotas de longa duração deste arquivo.
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2_760_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/generate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(model_hint ? { prompt, model_hint } : { prompt }),
        signal: controller.signal,
        dispatcher: longRunningDispatcher,
      } as RequestInit & { dispatcher: UndiciAgent });
      clearTimeout(timeoutId);
      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      // PHX-FIX: mesmo motivo acima - antes devolvia ok:true com
      // image_base64 vazio numa falha real, fingindo sucesso. Mais o novo
      // caso isAbort, mesmo padrão das outras rotas de longa duração.
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort ? "Tempo esgotado esperando o Phoenix Engine gerar a imagem (46min)." : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });

  // PHX-NEW (achado real do usuário 2026-08-24: "pesquisar acidente com 2
  // helicópteros no rj em 2026" no chat normal foi respondido direto pelo
  // qwen3-8b sem nenhuma busca real - o web_search.py/search_web() do
  // Phoenix Engine já existia e já funcionava, mas só estava conectado ao
  // /colaborar, nunca ao chat de um único modelo). Proxy simples pro novo
  // /api/web-search do Phoenix Engine - mesmo padrão de AbortController com
  // margem das outras rotas deste arquivo: o httpx do lado Python usa
  // timeout=10.0 (ver web_search.py), aqui 20_000ms (20s) dá 10s de folga.
  app.post("/api/web-search", async (req, res) => {
    const { query, max_results } = req.body;
    if (!query || typeof query !== "string" || !query.trim()) {
      res.status(400).json({ error: "Query de busca vazia." });
      return;
    }
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 20_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/web-search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, max_results: typeof max_results === "number" ? max_results : 5 }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);
      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao buscar na web.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort ? "Tempo esgotado esperando o Phoenix Engine buscar na web (20s)." : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });

  // ==========================================
  // PHX-NEW 2026-08-30 — proxy do Execution Arbiter.
  // Aviary consulta isto UMA vez antes das heurísticas antigas. Se vier
  // NOT_CLAIMED, o frontend está explicitamente autorizado a seguir o fluxo
  // legado sem interferência.
  app.post("/api/intent/intercept", async (req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/intent/intercept`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body || {}),
        dispatcher: longRunningDispatcher,
      } as RequestInit & { dispatcher: UndiciAgent });
      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data as any)?.detail || "Execution Arbiter indisponível." });
        return;
      }
      res.json(data);
    } catch (err: any) {
      res.status(502).json({ error: `Execution Arbiter inacessível: ${describeFetchError(err)}` });
    }
  });


  // DOCUMENT ENGINE - proxy multipart real pro /api/documents/read e
  // /api/documents/edit do Phoenix Engine (porta 8000). Substitui o antigo
  // /api/documents/ingest, que (a) fazia stream passthrough frágil do
  // request bruto e (b) devolvia um resumo de RAG COMPLETAMENTE INVENTADO
  // quando o Phoenix Engine falhava - sem relação nenhuma com o documento
  // enviado de verdade.
  // ==========================================
  app.post("/api/documents/read", documentUpload.single("file"), async (req, res) => {
    const file = req.file;
    const question = (req.body?.question as string) || "";
    if (!file) {
      res.status(400).json({ error: "Nenhum arquivo enviado (campo 'file' ausente)." });
      return;
    }
    try {
      const formData = new FormData();
      formData.append("file", new Blob([new Uint8Array(file.buffer)], { type: file.mimetype || "application/octet-stream" }), file.originalname);
      if (question.trim()) formData.append("question", question);

      // PHX-FIX (auditoria 2026-08-21, "corrigir tudo" - achado real de uma
      // auditoria externa, confirmado lendo o código: mismatch de timeout
      // entre este proxy e o guard interno do Engine): este AbortController
      // estava em 300_000ms (5min) contra os 240s do
      // DOCUMENT_EXECUTE_TIMEOUT_SECONDS em resident_manager.py - só 60s de
      // margem, apertado pro hardware real relatado (Xeon E5-2690 v3 + RX
      // 580 via Vulkan). Subido pra 540_000ms (9min), acompanhando o novo
      // teto de 480s (8min) do Engine - ver comentário de
      // DOCUMENT_EXECUTE_TIMEOUT_SECONDS em resident_manager.py.
      //
      // PHX-FIX (pedido do usuário 2026-08-22, OCR real): PDF escaneado
      // agora tenta OCR automático ANTES da leitura pelo LLM (ver
      // OCR_EXTRACT_TIMEOUT_SECONDS=330s em resident_manager.py) - pior
      // caso passou a ser OCR (330s) + leitura (480s) = 810s. Subido pra
      // 900_000ms (15min), mantendo ~90s de folga acima desse novo pior caso.
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 900_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/documents/read`, { method: "POST", body: formData, signal: controller.signal, dispatcher: longRunningDispatcher } as RequestInit & { dispatcher: UndiciAgent });
      clearTimeout(timeoutId);

      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao ler o documento.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort ? "Tempo esgotado esperando o Phoenix Engine analisar o documento (15min)." : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });

  // PHX-NEW (pedido do usuário 2026-08-28: "aceitar dois arquivos - um
  // fonte, um template alvo - e editar o segundo em vez de gerar do
  // zero"): trocado de documentUpload.single("file") pra
  // documentUpload.fields([...]) pra aceitar um segundo arquivo
  // opcional "reference" - um documento extra cujo conteúdo é dobrado
  // no prompt como contexto (ver edit_document_direct no Engine).
  app.post("/api/documents/edit", documentUpload.fields([{ name: "file", maxCount: 1 }, { name: "reference", maxCount: 1 }]), async (req, res) => {
    const files = req.files as { [field: string]: Express.Multer.File[] } | undefined;
    const file = files?.file?.[0];
    const reference = files?.reference?.[0];
    const instruction = (req.body?.instruction as string) || "";
    if (!file) {
      res.status(400).json({ error: "Nenhum arquivo enviado (campo 'file' ausente)." });
      return;
    }
    if (!instruction.trim()) {
      res.status(400).json({ error: "Campo 'instruction' é obrigatório." });
      return;
    }
    try {
      const formData = new FormData();
      formData.append("file", new Blob([new Uint8Array(file.buffer)], { type: file.mimetype || "application/octet-stream" }), file.originalname);
      formData.append("instruction", instruction);
      if (reference) {
        formData.append("reference", new Blob([new Uint8Array(reference.buffer)], { type: reference.mimetype || "application/octet-stream" }), reference.originalname);
      }

      // PHX-FIX (auditoria 2026-08-21, "corrigir tudo"): mesmo ajuste de
      // /api/documents/read acima - ver comentário lá.
      //
      // PHX-FIX (pedido do usuário 2026-08-22, OCR real): mesmo ajuste de
      // /api/documents/read acima (editar um PDF escaneado também tenta
      // OCR automático antes de reescrever o documento) - ver comentário lá.
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 900_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/documents/edit`, { method: "POST", body: formData, signal: controller.signal, dispatcher: longRunningDispatcher } as RequestInit & { dispatcher: UndiciAgent });
      clearTimeout(timeoutId);

      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao editar o documento.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort ? "Tempo esgotado esperando o Phoenix Engine editar o documento (15min)." : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });


  // PHX-NEW: criação/transformação universal de documentos.
  // Arquivo-base é opcional; os campos textuais sempre chegam via multipart.
  //
  // PHX-FIX (pedido explícito do usuário 2026-08-28, testando Gemma 4 12B
  // com pesquisa web + relatório longo em PDF): o llama-server responde
  // sem streaming - o modelo gera o documento INTEIRO e só devolve no
  // final, então uma geração legítima com um modelo grande, majoritariamente
  // em CPU, pode passar dos 30min que este teto tinha antes sem estar
  // travada. Subido pra bater com o novo DOCUMENT_CREATE_TIMEOUT_LARGE_
  // SECONDS=3600s (1h) do resident_manager.py + o piso espelhado em
  // llama_cpp.py - os três precisam subir JUNTOS (driver < Resident <
  // proxy), senão o elo mais fraco corta a chamada antes dos outros dois
  // terem qualquer chance de agir.
  app.post("/api/documents/create", documentUpload.single("file"), async (req, res) => {
    const file = req.file;
    const instruction = String(req.body?.instruction || "");
    const outputFormat = String(req.body?.output_format || "").replace(/^\./, "").toLowerCase();
    const filename = String(req.body?.filename || "");
    const useWeb = String(req.body?.use_web || "").toLowerCase() === "true";
    const webQuery = String(req.body?.web_query || "");
    const modelHint = String(req.body?.model_hint || "");

    if (!instruction.trim()) {
      res.status(400).json({ error: "Campo 'instruction' é obrigatório." });
      return;
    }
    if (!["pdf", "docx", "xlsx", "pptx", "txt", "md"].includes(outputFormat)) {
      res.status(422).json({ error: `Formato de saída '${outputFormat}' não suportado.` });
      return;
    }

    try {
      const formData = new FormData();
      formData.append("instruction", instruction);
      formData.append("output_format", outputFormat);
      if (filename.trim()) formData.append("filename", filename);
      formData.append("use_web", useWeb ? "true" : "false");
      if (webQuery.trim()) formData.append("web_query", webQuery);
      if (modelHint.trim()) formData.append("model_hint", modelHint);
      if (file) {
        formData.append(
          "file",
          new Blob([new Uint8Array(file.buffer)], { type: file.mimetype || "application/octet-stream" }),
          file.originalname,
        );
      }

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 3_660_000); // 61min: Resident max 60min + margem
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/documents/create`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
        dispatcher: longRunningDispatcher,
      } as RequestInit & { dispatcher: UndiciAgent });
      clearTimeout(timeoutId);

      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({
          error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao criar/transformar o documento.`,
        });
        return;
      }
      res.json(data);
    } catch (err: any) {
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort
          ? "Tempo esgotado esperando a criação/transformação do documento (61min)."
          : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });


  // PHX-NEW (pedido do usuário 2026-08-28: "aceitar dois arquivos - um
  // fonte, um template alvo - e editar o segundo em vez de gerar do
  // zero, pra qualquer documento que a Phoenix já lê e edita"): proxy
  // multipart pro /api/documents/fill-template do Phoenix Engine - dois
  // arquivos ("source" = qualquer formato lido pela Phoenix, "template"
  // = planilha .xlsx a preencher), preservando o template em vez de
  // recriar do zero.
  //
  // PHX-FIX (achado real do usuário 2026-08-28, catálogo de construção
  // real de ~430 mil caracteres): este endpoint herdava o mesmo teto de
  // 31min de /api/documents/create, calculado pra UMA chamada só ao
  // modelo. Depois que resident_manager.py passou a dividir o
  // documento-fonte em pedaços (ver PHX-FIX de
  // _SPREADSHEET_FILL_CHUNK_CHAR_BUDGET em resident_manager.py) pra não
  // truncar documentos grandes em silêncio, o mesmo request passou a
  // fazer várias chamadas SEQUENCIAIS ao modelo (uma por pedaço - o
  // documento real que motivou a correção precisa de 21). Resultado
  // observado de verdade: o Node abortava a conexão em 31min mesmo com o
  // Phoenix Engine ainda processando pedaços normalmente por trás -
  // trocou um bug (corte silencioso de dados) por outro (timeout cedo
  // demais), sem nenhuma correção adicional aqui. Teto aumentado pra
  // comportar o caso real (21 pedaços) com margem folgada, mesmo numa
  // máquina mais lenta - documentos raríssimos perto do teto de segurança
  // de 60 pedaços do lado do Python ainda podem, em tese, superar mesmo
  // este teto maior; a correção certa pra esse extremo seria processar
  // pedaços em paralelo (não sequencial) do lado do Python, fora do
  // escopo desta correção pontual.
  //
  // (Nota histórica: os "31min" mencionados acima eram o teto de
  // /api/documents/create NA ÉPOCA desta correção - essa rota irmã foi
  // pra 61min depois, por um motivo diferente - ver PHX-FIX na
  // declaração de /api/documents/create, mais acima neste arquivo. As
  // duas rotas têm orçamentos próprios e independentes; um teto mudar
  // não implica o outro mudar junto.)
  // PHX-NEW (2026-09-03): proxy do preenchimento DETERMINÍSTICO. O
  // /fill-template abaixo usa o LLM (lento, chegou a >90min num catálogo
  // real e virou processo órfão). Este roteia pro /pipeline-fill do Engine,
  // que faz o mesmo 100% em Python (Document Pipeline V2 + Smart Filler) em
  // SEGUNDOS. Por isso o timeout aqui é curto (10min é folga enorme): se
  // passar disso, algo está errado e é melhor abortar cedo do que deixar o
  // usuário esperando 90min. O AbortController propaga o cancelamento pro
  // fetch; o Engine, ao ver o cliente sumir, não fica preso num modelo (não
  // há inferência neste caminho).
  app.post(
    "/api/documents/pipeline-fill",
    documentUpload.fields([{ name: "source", maxCount: 1 }, { name: "template", maxCount: 1 }]),
    async (req, res) => {
      try {
        const files = req.files as { [k: string]: Express.Multer.File[] } | undefined;
        const source = files?.source?.[0];
        const template = files?.template?.[0];
        if (!source || !template) {
          res.status(400).json({ error: "Envie 'source' (documento) e 'template' (.xlsx)." });
          return;
        }
        const formData = new FormData();
        formData.append("source", new Blob([new Uint8Array(source.buffer)], { type: source.mimetype || "application/octet-stream" }), source.originalname);
        formData.append("template", new Blob([new Uint8Array(template.buffer)], { type: template.mimetype || "application/octet-stream" }), template.originalname);

        const PIPELINE_FILL_TIMEOUT_MS = 600_000; // 10min — determinístico é questão de segundos
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), PIPELINE_FILL_TIMEOUT_MS);
        const r = await fetch(`${PHOENIX_ENGINE_URL}/api/documents/pipeline-fill`, {
          method: "POST",
          body: formData,
          signal: controller.signal,
          dispatcher: longRunningDispatcher,
        } as RequestInit & { dispatcher: UndiciAgent });
        clearTimeout(timeoutId);

        const data = await r.json().catch(() => null);
        if (!r.ok || !data) {
          res.status(r.status || 502).json({
            error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao preencher a planilha.`,
          });
          return;
        }
        res.json(data);
      } catch (err: any) {
        const isAbort = err?.name === "AbortError";
        res.status(isAbort ? 504 : 502).json({
          error: isAbort
            ? "Tempo esgotado no preenchimento determinístico (10min) — algo está errado, o normal são segundos."
            : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
        });
      }
    },
  );

  app.post(
    "/api/documents/fill-template",
    documentUpload.fields([{ name: "source", maxCount: 1 }, { name: "template", maxCount: 1 }]),
    async (req, res) => {
      const files = req.files as { [field: string]: Express.Multer.File[] } | undefined;
      const source = files?.source?.[0];
      const template = files?.template?.[0];
      const instruction = String(req.body?.instruction || "");
      const useWeb = String(req.body?.use_web || "").toLowerCase() === "true";
      const webQuery = String(req.body?.web_query || "");
      const modelHint = String(req.body?.model_hint || "");

      if (!source) {
        res.status(400).json({ error: "Nenhum documento-fonte enviado (campo 'source' ausente)." });
        return;
      }
      if (!template) {
        res.status(400).json({ error: "Nenhum template enviado (campo 'template' ausente)." });
        return;
      }
      if (!/\.xlsx$/i.test(template.originalname || "")) {
        res.status(422).json({ error: "O template precisa ser um arquivo .xlsx." });
        return;
      }

      try {
        const formData = new FormData();
        formData.append("source", new Blob([new Uint8Array(source.buffer)], { type: source.mimetype || "application/octet-stream" }), source.originalname);
        formData.append("template", new Blob([new Uint8Array(template.buffer)], { type: template.mimetype || "application/octet-stream" }), template.originalname);
        if (instruction.trim()) formData.append("instruction", instruction);
        formData.append("use_web", useWeb ? "true" : "false");
        if (webQuery.trim()) formData.append("web_query", webQuery);
        if (modelHint.trim()) formData.append("model_hint", modelHint);

        // PHX-FIX (ver comentário completo acima, na declaração da rota):
        // 90min comporta os 21 pedaços do documento real que motivou esta
        // correção com folga real, mesmo numa máquina lenta (~4min/pedaço
        // em média) - bem acima do antigo teto de 31min, que era
        // calculado pra uma chamada só ao modelo e não para N chamadas
        // sequenciais.
        const FILL_TEMPLATE_TIMEOUT_MS = 5_400_000; // 90min
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), FILL_TEMPLATE_TIMEOUT_MS);
        const r = await fetch(`${PHOENIX_ENGINE_URL}/api/documents/fill-template`, {
          method: "POST",
          body: formData,
          signal: controller.signal,
          dispatcher: longRunningDispatcher,
        } as RequestInit & { dispatcher: UndiciAgent });
        clearTimeout(timeoutId);

        const data = await r.json().catch(() => null);
        if (!r.ok || !data) {
          res.status(r.status || 502).json({
            error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao preencher a planilha.`,
          });
          return;
        }
        res.json(data);
      } catch (err: any) {
        const isAbort = err?.name === "AbortError";
        res.status(isAbort ? 504 : 502).json({
          error: isAbort
            ? "Tempo esgotado esperando o preenchimento da planilha (90min)."
            : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
        });
      }
    },
  );


  // PHX-NEW (pedido do usuário 2026-08-22: "pode por o clip igual no
  // chatbot" na aba Colaboração do Arena): proxy multipart real pro novo
  // /api/documents/extract-raw do Phoenix Engine - extrai o texto do
  // documento SEM chamar nenhum modelo de IA (ao contrário de
  // /api/documents/read acima), pra injetar direto no "topic" de uma
  // colaboração entre dois modelos. Mesmo padrão de multer/FormData das
  // rotas de documento acima. Timeout de 480_000ms (8min): pior caso é
  // extração (120s) + OCR automático de PDF escaneado (330s) = 450s,
  // com ~30s de folga - bem mais rápido que /api/documents/read porque
  // não tem a etapa de inferência do LLM no final.
  app.post("/api/documents/extract-raw", documentUpload.single("file"), async (req, res) => {
    const file = req.file;
    if (!file) {
      res.status(400).json({ error: "Nenhum arquivo enviado (campo 'file' ausente)." });
      return;
    }
    try {
      const formData = new FormData();
      formData.append("file", new Blob([new Uint8Array(file.buffer)], { type: file.mimetype || "application/octet-stream" }), file.originalname);

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 480_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/documents/extract-raw`, { method: "POST", body: formData, signal: controller.signal, dispatcher: longRunningDispatcher } as RequestInit & { dispatcher: UndiciAgent });
      clearTimeout(timeoutId);

      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao extrair o documento.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort ? "Tempo esgotado esperando o Phoenix Engine extrair o documento (8min)." : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });

  // PHX-NEW (pedido do usuário 2026-08-23: "pegar um arquivo doc, pdf de 40
  // folhas e fazer áudio com voz neural com prosódia bacana tanto em
  // português qto em inglês ou outra língua"): proxy multipart pro novo
  // /api/documents/synthesize-audiobook do Phoenix Engine - documento
  // inteiro vira UM áudio só, com detecção automática de idioma por bloco
  // e voz neural Kokoro-82M. Mesmo padrão de longRunningDispatcher já usado
  // em /api/dual-collab e /api/generate-image acima - isso pode
  // legitimamente levar dezenas de minutos pra um documento de várias
  // dezenas de páginas. AbortController de 5_520_000ms (92min), 120s de
  // folga acima do AUDIOBOOK_TOTAL_TIME_BUDGET_SECONDS=5400s (90min) do
  // Engine (resident_manager.py) - mesmo padrão de margem das outras rotas
  // de longa duração deste arquivo.
  app.post("/api/documents/synthesize-audiobook", documentUpload.single("file"), async (req, res) => {
    const file = req.file;
    if (!file) {
      res.status(400).json({ error: "Nenhum arquivo enviado (campo 'file' ausente)." });
      return;
    }
    try {
      const formData = new FormData();
      formData.append("file", new Blob([new Uint8Array(file.buffer)], { type: file.mimetype || "application/octet-stream" }), file.originalname);

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5_520_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/documents/synthesize-audiobook`, { method: "POST", body: formData, signal: controller.signal, dispatcher: longRunningDispatcher } as RequestInit & { dispatcher: UndiciAgent });
      clearTimeout(timeoutId);

      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao gerar o audiolivro.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort ? "Tempo esgotado esperando o Phoenix Engine gerar o audiolivro (92min)." : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });

  // PHX-NEW (mesmo padrão de GET /api/dual-collab/progress acima): proxy
  // simples e RÁPIDO (timeout curto de 2s) pro novo
  // GET /api/documents/synthesize-audiobook/progress do Phoenix Engine -
  // pensado pra ser chamado em polling pelo frontend ENQUANTO o POST acima
  // ainda está processando, pra mostrar uma barra de progresso real em vez
  // de uma tela travada sem feedback.
  app.get("/api/documents/synthesize-audiobook/progress", async (_req, res) => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/documents/synthesize-audiobook/progress`, { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        res.json(await r.json());
        return;
      }
      res.json({ phase: "ocioso", current_chunk: 0, total_chunks: 0, percent: 0 });
    } catch {
      res.json({ phase: "ocioso", current_chunk: 0, total_chunks: 0, percent: 0 });
    }
  });

  // PHX-NEW (pedido do usuário 2026-08-22): proxy JSON simples pro novo
  // /api/dual-collab do Phoenix Engine - colaboração real entre dois
  // modelos de texto (um inteiro na CPU, outro inteiro na GPU via
  // Vulkan). Isso sobe uma SEGUNDA instância de llama-server (porta 8090)
  // e faz várias rodadas de inferência alternadas - pode legitimamente
  // levar minutos. AbortController de 1_320_000ms (22min), 120s de folga
  // acima do orçamento de tempo total do próprio Engine
  // (dual_collab.TOTAL_TIME_BUDGET_SECONDS=1200s/20min) - mesmo padrão de
  // margem das outras rotas de longa duração deste arquivo.
  app.post("/api/dual-collab", async (req, res) => {
    // PHX-NEW (2026-08-22, modelo padrão não coube na VRAM do usuário com a
    // margem de segurança): cpu_model/gpu_model são opcionais - vazios
    // preservam o comportamento original (os dois lados usam o mesmo
    // modelo padrão da Phoenix).
    const { topic, max_rounds, cpu_model, gpu_model } = req.body || {};
    if (!topic || !String(topic).trim()) {
      res.status(400).json({ error: "Campo 'topic' é obrigatório." });
      return;
    }
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 1_320_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/dual-collab`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic, max_rounds: max_rounds || 6,
          cpu_model: cpu_model || "", gpu_model: gpu_model || "",
        }),
        signal: controller.signal,
        dispatcher: longRunningDispatcher,
      } as RequestInit & { dispatcher: UndiciAgent });
      clearTimeout(timeoutId);
      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} na colaboração.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort ? "Tempo esgotado esperando a colaboração entre os dois modelos terminar (22min)." : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });

  // PHX-NEW (2026-08-22, pedido do usuário depois de ver a Arena com a
  // ampulheta piscando o tempo inteiro até as 6 rodadas terminarem TODAS
  // de uma vez, dando a impressão de que travou): proxy simples e RÁPIDO
  // (timeout curto de 2s, mesmo padrão de GET /api/state acima) pro novo
  // GET /api/dual-collab/progress do Phoenix Engine - pensado pra ser
  // chamado em polling pelo frontend ENQUANTO o POST /api/dual-collab
  // acima ainda está em andamento (bloqueante, pode levar minutos).
  app.get("/api/dual-collab/progress", async (_req, res) => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/dual-collab/progress`, { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        const data = await r.json();
        return res.json(data);
      }
      return res.status(502).json({ error: `Phoenix Engine devolveu status ${r.status}.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  // PHX-NEW (auditoria completa, achado #4 do LEIA-ME): proxy multipart
  // real pro novo /api/transcribe do Phoenix Engine (porta 8000). Antes
  // desta rota, o WhisperDriver já compilava (fix deste mesmo pacote) e já
  // estava registrado no runtime/models.json, mas não existia NENHUM
  // caminho de UI -> API -> ResidentManager.transcribe_direct() -> driver -
  // STT ficava inacessível mesmo com tudo pronto por baixo. Mesmo padrão
  // multer + FormData dos proxies de documento acima.
  app.post("/api/transcribe", documentUpload.single("file"), async (req, res) => {
    const file = req.file;
    const language = (req.body?.language as string) || "pt";
    if (!file) {
      res.status(400).json({ error: "Nenhum arquivo de áudio enviado (campo 'file' ausente)." });
      return;
    }
    try {
      const formData = new FormData();
      formData.append("file", new Blob([new Uint8Array(file.buffer)], { type: file.mimetype || "application/octet-stream" }), file.originalname);
      formData.append("language", language);

      // PHX-FIX (auditoria 2026-08-21, "corrigir tudo" - mesma classe de
      // achado do describe-image acima): este AbortController estava em
      // 600_000ms (10min), o MESMO valor, sem margem nenhuma, do timeout
      // interno em WhisperDriver.execute()
      // (phoenix_kernel/runtime/drivers/whisper.py,
      // asyncio.wait_for(process.communicate(), timeout=600)). Subido pra
      // 660_000ms (11min) - o driver continua em 600s (áudio longo
      // legitimamente pode precisar de quase 10min via whisper.cpp em CPU),
      // só o proxy ganha a mesma folga de 60s usada nas outras rotas.
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 660_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/transcribe`, { method: "POST", body: formData, signal: controller.signal, dispatcher: longRunningDispatcher } as RequestInit & { dispatcher: UndiciAgent });
      clearTimeout(timeoutId);

      const data = await r.json().catch(() => null);
      if (!r.ok || !data) {
        res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao transcrever o áudio.` });
        return;
      }
      res.json(data);
    } catch (err: any) {
      const isAbort = err?.name === "AbortError";
      res.status(isAbort ? 504 : 502).json({
        error: isAbort ? "Tempo esgotado esperando o Phoenix Engine transcrever o áudio (11min)." : `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`,
      });
    }
  });

  // PHX-FIX (auditoria completa — "tirar todos os fallbacks"): todas as
  // rotas abaixo (missions/license/telemetry-consent) tinham DOIS problemas
  // ao mesmo tempo:
  // 1) Fallback fabricado: quando o Phoenix Engine (porta 8000) estava
  //    offline OU respondia com erro, a rota devolvia dado 100% inventado
  //    como se fosse real (catálogo de 7 missões hardcoded, "Missão
  //    iniciada com sucesso" sem ter instalado nada, licença "accepted:
  //    true" sem checar nada, consentimento de telemetria sempre "true",
  //    "sent: 4" documentos sincronizados que nunca foram enviados).
  // 2) Bug de resposta dupla: o bloco catch chamava res.status(502).json()
  //    SEM `return` — quando a exceção vinha de um erro de rede (fetch
  //    lançando), a função continuava executando depois do catch e tentava
  //    mandar uma SEGUNDA resposta (o fallback fabricado), o que no
  //    Express gera "ERR_HTTP_HEADERS_SENT" (Cannot set headers after they
  //    are sent) — uma exceção não tratada dentro de um handler async, que
  //    pode derrubar o processo Node inteiro dependendo da versão/runtime.
  // Correção: uma única resposta por requisição, sempre. Sucesso real
  // devolve dado real; qualquer falha (rede OU status HTTP não-OK do
  // Engine) devolve erro real com o código de status apropriado — nunca os
  // dois juntos, nunca fabricado.
  //
  // Nenhuma destas rotas é chamada por nenhum componente do frontend hoje
  // (confirmado por busca em src/ - são resquícios de uma versão anterior
  // com fluxo de missões/licença/consentimento que não está mais na UI).
  // Mantidas como proxies honestos (podem servir clientes externos ou uma
  // UI futura) em vez de removidas, já que fabricar dado nelas seria o
  // mesmo bug independente de terem UI conectada ou não.
  app.get("/api/missions", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/missions`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao listar missões.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.get("/api/missions/:package_id", async (req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/missions/${req.params.package_id}`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao resolver a missão.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.post("/api/missions/install", async (req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/missions/install`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body),
      });
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao instalar a missão.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  // API: License & Telemetry Consent
  app.get("/api/license", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/license`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao obter a licença.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.post("/api/license/accept", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/license/accept`, { method: "POST" });
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao aceitar a licença.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.get("/api/telemetry/consent", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/telemetry/consent`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao ler o consentimento.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.post("/api/telemetry/consent/accept", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/telemetry/consent/accept`, { method: "POST" });
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao aceitar o consentimento.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.post("/api/telemetry/consent/decline", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/telemetry/consent/decline`, { method: "POST" });
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao recusar o consentimento.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.post("/api/telemetry/sync", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/telemetry/sync`, { method: "POST" });
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao sincronizar telemetria.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  // PHX-FIX (auditoria completa — "tirar todos os fallbacks"): esta rota
  // (GET /api/telemetry) foi REMOVIDA. Ela nunca chamava o Phoenix Engine —
  // era um gerador 100% fabricado via Math.random() (latência, throughput,
  // uso de CPU/GPU/VRAM/RAM, temperatura, tudo inventado a cada chamada) e,
  // confirmado por busca em todo o src/, NENHUM componente do frontend a
  // chama. A telemetria real da plataforma já vem de GET /api/state (usada
  // por EngineMissionControl.tsx), que reflete o AHDE de verdade — não
  // fazia sentido manter uma segunda rota inteiramente inventada ao lado
  // dela, mesmo sem UI consumindo.

  // API: RAG Docs
  app.get("/api/rag", async (_req, res) => {
    // PHX-FIX: lista real de documentos RAG do ChromaDB via /api/state
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/state`, { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        const data: any = await r.json();
        const docs = data.rag_documents || [];
        return res.json({ documents: docs, totalDocs: data.rag_docs || docs.length });
      }
    } catch {}
    res.json({ documents: [], totalDocs: 0 });
  });

  // PHX-FIX (auditoria completa, achado #3 do LEIA-ME): esta rota fabricava
  // `status: "INDEXED"` e `vectorDimensions: 1536` como fallback sempre que
  // o Python não respondia (inclusive quando /api/rag/add simplesmente não
  // existia ali, o que era sempre, antes deste pacote). Um documento que
  // nunca foi vetorizado aparecia com o mesmo badge "INDEXED" de um
  // documento real. Agora POST /api/rag/add existe de verdade no Python
  // (api_server.py) e este proxy encaminha title/content/sourceType e
  // devolve erro real (nunca sucesso fabricado) se a chamada falhar.
  app.post("/api/rag", async (req, res) => {
    const { title, content, sourceType } = req.body || {};
    if (!title || !content) {
      return res.status(400).json({ success: false, error: "Campos 'title' e 'content' são obrigatórios." });
    }
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 30000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/rag/add`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, content, source_type: sourceType || "MD" }),
        signal: ctrl.signal,
      });
      clearTimeout(t);
      const data: any = await r.json().catch(() => ({}));
      if (r.ok) {
        return res.json({ success: true, doc: data.document });
      }
      return res.status(r.status).json({ success: false, error: data.detail || "Falha ao indexar documento." });
    } catch (e: any) {
      return res.status(502).json({ success: false, error: `Phoenix Engine indisponível: ${e?.message || e}` });
    }
  });


  app.get("/api/rag/limits", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/rag/limits`);
      const data: any = await r.json().catch(() => ({}));
      if (r.ok) return res.json(data);
      return res.status(r.status).json({ ok: false, error: data.detail || "Falha ao obter limites do RAG." });
    } catch (e: any) {
      return res.status(502).json({ ok: false, error: `Phoenix Engine indisponível: ${describeFetchError(e)}` });
    }
  });

  // PHX-RAG v57: upload binário real -> Engine extrai/OCR e indexa em chunks.
  app.post("/api/rag/add-file", ragUpload.single("file"), async (req, res) => {
    const file = req.file;
    if (!file) return res.status(400).json({ success: false, error: "Nenhum arquivo enviado." });
    try {
      const form = new FormData();
      // Copia o Buffer do Node para um Uint8Array com ArrayBuffer próprio.
      // Isso evita expor um SharedArrayBuffer ao Blob e funciona de forma
      // consistente com os tipos atuais de Node/Undici.
      form.append("file", new Blob([Uint8Array.from(file.buffer)]), file.originalname);
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 660_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/rag/add-file`, {
        method: "POST", body: form, signal: ctrl.signal, dispatcher: longRunningDispatcher,
      } as any);
      clearTimeout(t);
      const data: any = await r.json().catch(() => ({}));
      if (r.ok) return res.json({
        ...data,
        success: true,
        doc: data.document,
        ocrUsed: Boolean(data.ocr_used),
        ocrMeta: data.ocr_meta || null,
      });
      return res.status(r.status).json({ success: false, error: data.detail || "Falha ao indexar arquivo no RAG." });
    } catch (e: any) {
      return res.status(502).json({ success: false, error: `Phoenix Engine indisponível: ${describeFetchError(e)}` });
    }
  });

  app.post("/api/rag/query", async (req, res) => {
    const query = String(req.body?.query || "").trim();
    if (!query) return res.status(400).json({ ok: false, success: false, hits: [], error: "Query RAG vazia." });
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 30_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/rag/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query,
          n_results: Number(req.body?.n_results || 5),
          min_score: Number(req.body?.min_score || 0),
        }),
        signal: ctrl.signal,
      });
      clearTimeout(t);
      const data: any = await r.json().catch(() => ({}));
      if (r.ok) return res.json(data);
      return res.status(r.status).json({ ok: false, success: false, hits: [], error: data.detail || "Falha na consulta RAG." });
    } catch (e: any) {
      return res.status(502).json({ ok: false, success: false, hits: [], error: `Phoenix Engine indisponível: ${describeFetchError(e)}` });
    }
  });

  // PHX-FIX (mesmo achado #3): igual ao POST acima, delete não fabrica mais
  // sucesso quando o Python não responde — o documento continuaria no
  // ChromaDB de verdade, então reportar `success: true` sem ter apagado nada
  // é exatamente o tipo de dado fabricado que essa auditoria vem removendo.
  app.delete("/api/rag/:id", async (req, res) => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 10000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/rag/${req.params.id}`, { method: "DELETE", signal: ctrl.signal });
      clearTimeout(t);
      const data: any = await r.json().catch(() => ({}));
      if (r.ok) return res.json({ success: true });
      return res.status(r.status).json({ success: false, error: data.detail || "Falha ao remover documento." });
    } catch (e: any) {
      return res.status(502).json({ success: false, error: `Phoenix Engine indisponível: ${e?.message || e}` });
    }
  });

  // API: Aviary Agents — busca do Python real
  app.get("/api/agents", async (_req, res) => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/agents`, { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) return res.json(await r.json());
    } catch {}
    // Python ainda não tem endpoint /api/agents — devolve estrutura neutra
    res.json({ agents: [], total: 0, note: "Swarm Agents não configurados ainda no Phoenix Engine." });
  });

  // PHX-FIX (auditoria completa — "tirar todos os fallbacks"): quando
  // `r.ok` era false (Phoenix Engine respondia mas com erro - ex: rota
  // ainda não implementada no Python, que é o caso hoje), NENHUMA resposta
  // era enviada - a função simplesmente terminava sem chamar res.json()
  // nem uma vez, deixando a requisição do cliente pendurada até o timeout
  // dele. Agora todo caminho manda exatamente uma resposta.
  app.post("/api/agents/dispatch", async (req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/agents/dispatch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body),
      });
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao despachar o agente.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  // PHX-FIX (auditoria completa, achado #2 do LEIA-ME): esta rota devolvia
  // números fixos hardcoded, sempre os mesmos, em toda chamada - nunca
  // executava nada de verdade. O botão que a chama (ProcessLauncherBar.tsx,
  // "Vulkan Bench (RX 580)") tinha o title "Disparar benchmark real de
  // shaders Vulkan no chip RX 580", prometendo medição ao vivo que não
  // existia. Agora encaminha pra POST /api/benchmark no Python
  // (api_server.py), que executa uma inferência curta real e mede tokens/s
  // de verdade via ExecutionResult.metrics. TFLOPs/largura de
  // banda/latência de shader Vulkan não são medidos (exigiria compute
  // shader dedicado, fora do escopo deste conserto) e não aparecem mais na
  // resposta - nada fabricado no lugar deles.
  // PHX-FIX (auditoria 2026-08-21, "corrigir tudo" - achado real de uma
  // auditoria externa, confirmado lendo o código: este AbortController
  // estava em 60_000ms (60s), mas `run_token_benchmark_direct()`
  // (resident_manager.py) chamava `self.runtime.execute(plan)` sem NENHUM
  // teto próprio antes desta rodada - o teto real era o timeout interno de
  // cada driver, 600s. Gap de 10x: um benchmark que precisasse primeiro
  // carregar o modelo (cold start, servidor ainda não rodando) podia
  // facilmente passar de 60s só no carregamento, antes até de gerar o
  // primeiro token do benchmark em si - o Node abortava com "Phoenix Engine
  // indisponível", mesmo com o Engine são e ainda processando. Agora
  // `run_token_benchmark_direct()` tem seu próprio teto de 300s
  // (BENCHMARK_EXECUTE_TIMEOUT_SECONDS, ver resident_manager.py) - este
  // AbortController sobe pra 360_000ms (6min), com a mesma folga de 60s
  // usada nas outras rotas, e o catch abaixo passa a distinguir abort
  // (timeout, 504) de falha de rede real (502), igual às outras rotas.
  app.post("/api/benchmark", async (_req, res) => {
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 360_000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/benchmark`, { method: "POST", signal: ctrl.signal });
      clearTimeout(t);
      const data: any = await r.json().catch(() => ({}));
      if (r.ok) {
        return res.json({ success: true, results: data.results, note: data.note });
      }
      return res.status(r.status).json({ success: false, error: data.detail || "Benchmark falhou no Phoenix Engine." });
    } catch (e: any) {
      const isAbort = e?.name === "AbortError";
      return res.status(isAbort ? 504 : 502).json({
        success: false,
        error: isAbort ? "Tempo esgotado esperando o Phoenix Engine rodar o benchmark (6min)." : `Phoenix Engine indisponível: ${e?.message || e}`,
      });
    }
  });

  // API: Engine & Local Models Scanner
  // PHX-FIX (varredura 2026-08-21, achado 2): as duas chamadas abaixo
  // (Phoenix Engine e Ollama) tinham `catch {}` vazio - offline/timeout e
  // "genuinamente zero modelos instalados" resultavam na mesma lista
  // vazia, sem nenhum jeito de saber qual dos dois aconteceu. Nenhum nome
  // de modelo é inventado aqui (isso já estava certo), só a causa da
  // lista vazia se perdia. Agora expõe engineOnline/ollamaOnline.
  app.get("/api/engine/models", async (_req, res) => {
    const result: Record<string, any> = {
      phoenixModels: [] as string[],
      ollamaModels: [] as string[],
      // PHX-FIX (varredura 2026-08-21, "verificar e consertar" - achado real
      // encontrado investigando um bug reportado pelo usuário com
      // screenshot: um chat via provedor "llama-server" falhou com 404
      // "File Not Found" do llama-server real): `lmstudioModels` e
      // `llamaServerModels` eram lidos no frontend (AviaryApp.tsx,
      // handleScanAllProviders - "if (p.type === 'lmstudio' &&
      // trackedData.lmstudioModels?.length > 0)" / mesma coisa pra
      // 'llama-server') mas este endpoint NUNCA os preenchia - só
      // Phoenix Engine e Ollama eram consultados aqui. As duas condições no
      // frontend eram, portanto, sempre falsas - código morto que parecia
      // real. Na prática isso não deixava o dropdown de modelos
      // desatualizado (handleTestProvider(), chamado logo depois no mesmo
      // scan, já faz um ping ao vivo em cada provedor via /api/proxy/ping e
      // é quem realmente populava a lista) - mas destoava do resto do
      // objeto (Ollama JÁ era consultado aqui) e deixava o "Detectar
      // Locais" reportar dados incompletos até o ping individual terminar.
      // Implementado de verdade agora, mesmo padrão já usado pra Ollama:
      // consulta o endpoint OpenAI-compatible /v1/models de cada um nos
      // mesmos hosts/portas padrão usados em DEFAULT_PROVIDERS
      // (AviaryApp.tsx: llama-server em :8081, LM Studio em :1234).
      lmstudioModels: [] as string[],
      llamaServerModels: [] as string[],
      // PHX-NEW (2026-08-22, achado real: usuário baixou
      // DeepSeek-R1-Distill-Qwen-7B-Q6_K.gguf na pasta certa e ele não
      // aparecia em lugar nenhum do Aviary): `llamaServerModels` acima só
      // reflete o ÚNICO modelo que o llama-server nativo já tem carregado
      // agora (ele roda com `-m <arquivo>`, nunca `--models-dir` - ver
      // LlamaCppDriver.start()) - um arquivo baixado mas nunca carregado
      // fica invisível ali, mesmo estando certinho no disco. `diskChatModels`
      // é a varredura de disco de verdade (novo /api/models/chat-gguf no
      // Python, que reusa o ModelScanner já usado em outros lugares do
      // projeto, filtrando só categoria "Chat"/formato GGUF e excluindo
      // arquivos "mmproj-*" que não são modelos de chat sozinhos) - inclui
      // TODO .gguf de chat baixado, carregado ou não.
      diskChatModels: [] as string[],
      allDownloadedModels: [] as string[],
      engineOnline: false,
      ollamaOnline: false,
      lmstudioOnline: false,
      llamaServerOnline: false,
    };

    // Phoenix Engine: modelos instalados em disco (via /api/state)
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/state`, { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        const data: any = await r.json();
        const models: string[] = data.models || [];
        result.phoenixModels = models;
        result.allDownloadedModels = [...models];
        result.engineOnline = true;
      }
    } catch {}

    // Phoenix Engine: varredura de disco dedicada a modelos de chat GGUF
    // (todo arquivo baixado na pasta certa, carregado ou não - ver
    // /api/models/chat-gguf no api_server.py pro porquê disso ser
    // separado de /api/state acima).
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 2000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/models/chat-gguf`, { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        const data: any = await r.json();
        if (Array.isArray(data.models)) {
          result.diskChatModels = data.models;
          result.allDownloadedModels = [...new Set([...result.allDownloadedModels, ...result.diskChatModels])];
        }
      }
    } catch {}

    // Ollama: modelos disponíveis via API local
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 1200);
      const r = await fetch("http://localhost:11434/api/tags", { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        const data: any = await r.json();
        result.ollamaOnline = true;
        if (Array.isArray(data.models)) {
          result.ollamaModels = data.models.map((m: any) => m.name || m.model);
          result.allDownloadedModels = [...new Set([...result.allDownloadedModels, ...result.ollamaModels])];
        }
      }
    } catch {}

    // LM Studio: modelos disponíveis via endpoint OpenAI-compatible local
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 1200);
      const r = await fetch("http://localhost:1234/v1/models", { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        const data: any = await r.json();
        result.lmstudioOnline = true;
        if (Array.isArray(data.data)) {
          result.lmstudioModels = data.data.map((m: any) => m.id).filter(Boolean);
          result.allDownloadedModels = [...new Set([...result.allDownloadedModels, ...result.lmstudioModels])];
        }
      }
    } catch {}

    // llama-server: modelos disponíveis via endpoint OpenAI-compatible local
    // (em modo com --models-dir, "id" aqui é o caminho real do .gguf que
    // /api/proxy/chat depois manda de volta no campo "model" - a MESMA
    // string, sem transformação, então uma listagem desatualizada aqui é
    // exatamente o tipo de coisa que produziria um 404 "File Not Found" no
    // llama-server ao tentar conversar com um modelo que já não existe mais
    // nesse caminho).
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 1200);
      const r = await fetch("http://localhost:8081/v1/models", { signal: ctrl.signal });
      clearTimeout(t);
      if (r.ok) {
        const data: any = await r.json();
        result.llamaServerOnline = true;
        if (Array.isArray(data.data)) {
          result.llamaServerModels = data.data.map((m: any) => m.id).filter(Boolean);
          result.allDownloadedModels = [...new Set([...result.allDownloadedModels, ...result.llamaServerModels])];
        }
      }
    } catch {}

    // PHX-FIX (2026-08-22, achado real: usuário aplicou todos os fixes de
    // disco corretamente - conferido ao vivo, tanto /api/models/chat-gguf
    // no Python quanto este /api/engine/models já devolviam os 5 modelos
    // certos via curl/navegador direto, e o bundle JS do frontend (dist/
    // assets/*.js) já continha a lógica de mistura correta - mas o
    // dropdown do Aviary continuava mostrando só 1 modelo. Como nenhuma
    // outra causa sobrou depois de confirmar TUDO isso, o suspeito que
    // fica é cache HTTP do navegador: esta rota nunca mandou nenhum
    // cabeçalho de cache, e o conteúdo muda toda vez que o usuário baixa
    // ou remove um modelo - sem "Cache-Control: no-store" explícito, um
    // navegador pode reaproveitar (por heurística) uma resposta antiga
    // desta MESMA rota que ele já tinha buscado antes, numa aba que ficou
    // aberta a sessão inteira, mesmo depois do backend já estar
    // atualizado. Isso nunca deveria ficar em cache - a lista de modelos
    // instalados é dinâmica por natureza.
    res.set("Cache-Control", "no-store");
    res.json(result);
  });

  // API: download de modelos recomendados (pedido do usuário 2026-08-22:
  // "api ou common baixar alguns modelos pra pasta padrão dos modelos
  // compatíveis com llama e ollama") — proxies simples pro Phoenix Engine
  // (Python), mesmo padrão de erro-real-repassado usado no resto deste
  // arquivo. O download em si (rede + gravação em disco) acontece 100% no
  // Python, em thread de fundo — aqui é só ida-e-volta rápida (listar
  // presets, iniciar o job, consultar status), nunca precisa de timeout
  // longo como /api/documents/read.
  app.get("/api/models/recommended-downloads", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/models/recommended-downloads`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.post("/api/models/download", async (req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/models/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: req.body?.key }),
      });
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.get("/api/models/download/status", async (req, res) => {
    try {
      const jobId = String(req.query.job_id || "");
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/models/download/status?job_id=${encodeURIComponent(jobId)}`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  // PHX-NEW (2026-08-23, pedido do usuário: "achei que a phoenix instalaria
  // o programa" - ele viu a tela Texto->Áudio recusar com "baixe manualmente
  // e coloque na pasta" e esperava um download automático, do mesmo jeito
  // que /api/models/download já faz pra modelos de chat GGUF acima). Mesmo
  // padrão exato de proxy: ida-e-volta rápida pro Phoenix Engine (o download
  // pesado em si roda em thread de fundo lá, aqui é só status/start/poll).
  app.get("/api/tts/kokoro/status", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/tts/kokoro/status`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.post("/api/tts/kokoro/download", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/tts/kokoro/download`, { method: "POST" });
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.get("/api/tts/kokoro/download/status", async (req, res) => {
    try {
      const jobId = String(req.query.job_id || "");
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/tts/kokoro/download/status?job_id=${encodeURIComponent(jobId)}`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  // PHX-FIX (2026-08-22, achado real do usuário: "foi usado somente flux
  // porque é o unico modelo baixado" - o seletor "IMAGEM" do ChatView era
  // 3 opções fixas, Flux/SDXL/SD1.5, sem ler o disco de verdade). Proxy
  // simples pro novo GET /api/models/image-models do api_server.py, mesmo
  // padrão de /api/models/chat-gguf acima - o backend já sabia escanear
  // Models/Image corretamente (ResidentManager._discover_installed_image_models,
  // usado há tempos pra resolução automática), só faltava expor pro
  // frontend montar o seletor com o que existe de verdade.
  app.get("/api/models/image-models", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/models/image-models`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.`, models: [] });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}`, models: [] });
    }
  });

  // API: Text Engine Preference (destravar Ollama como 2ª opção, a pedido
  // explícito) — proxy simples pro Phoenix Engine, mesmo padrão de
  // /api/agents/dispatch acima: uma única resposta por caminho, erro real
  // do Python repassado no corpo, nunca um "sucesso" fabricado quando o
  // Engine está offline.
  app.get("/api/engine/text-runtime", async (_req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/engine/text-runtime`);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status}.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  app.post("/api/engine/text-runtime", async (req, res) => {
    try {
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/engine/text-runtime`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req.body),
      });
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao trocar engine de texto.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  // API: Provider Ping Proxy
  app.post("/api/proxy/ping", async (req, res) => {
    const { providerType, baseUrl, apiKey } = req.body;

    // PHX-FIX (achado A7): valida o destino ANTES de montar/disparar o
    // fetch - ver resolveAllowedProxyTarget() no topo do arquivo.
    const targetCheck = await resolveAllowedProxyTarget(baseUrl || "");
    if (targetCheck.ok === false) {
      res.status(400).json({ online: false, latencyMs: 0, message: targetCheck.reason, models: [] });
      return;
    }

    const controller = new AbortController();
    // PHX-FIX (2026-09-06, achado real do usuário: o dropdown de chat
    // perdeu os modelos locais e caiu só pro Gemini com o sistema sob
    // carga pesada - GPU a 99%, descrição de imagem + geração de
    // documento rodando junto. 2500ms era curto demais pra um
    // llama-server ocupado processando outra requisição responder um
    // simples GET /v1/models - o servidor estava vivo, só devagar; o
    // timeout tratava isso como "offline". Aumentado pra 6000ms - ainda
    // limitado (nunca trava a UI indefinidamente), mas com folga real pra
    // um processo local sob carga normal de uso.
    const timeoutId = setTimeout(() => controller.abort(), 6000);

    try {
      let testUrl = baseUrl || "";
      const headers: Record<string, string> = { "Content-Type": "application/json" };
      if (apiKey) headers["Authorization"] = `Bearer ${apiKey}`;

      if (providerType === "ollama") {
        testUrl = `${baseUrl.replace(/\/$/, "")}/api/tags`;
      } else {
        const cleanBase = (baseUrl || "").replace(/\/$/, "");
        testUrl = cleanBase.endsWith("/v1") ? `${cleanBase}/models` : `${cleanBase}/v1/models`;
      }

      if (!testUrl.startsWith("http")) testUrl = `http://${testUrl}`;

      const startTime = Date.now();
      const response = await fetch(testUrl, { method: "GET", headers, signal: controller.signal });
      clearTimeout(timeoutId);

      const latencyMs = Date.now() - startTime;
      let modelsList: string[] = [];

      try {
        const data: any = await response.json();
        if (providerType === "ollama" && Array.isArray(data.models)) {
          modelsList = data.models.map((m: any) => m.name || m.model);
        } else if (Array.isArray(data.data)) {
          modelsList = data.data.map((m: any) => m.id || m.name || m.model);
        }
      } catch {}

      res.json({
        online: response.ok,
        latencyMs,
        status: response.status,
        models: modelsList,
      });
    } catch (err: any) {
      clearTimeout(timeoutId);
      res.json({
        online: false,
        latencyMs: 0,
        message: err.name === "AbortError" ? "Timeout" : "Endpoint indisponível",
        models: [],
      });
    }
  });

  // API: Gemini Cloud Chat Completion
  app.post("/api/gemini/chat", async (req, res) => {
    try {
      const { model, messages, systemInstruction, temperature, topP, topK, maxTokens } = req.body;
      const ai = getGeminiClient();

      const selectedModel = model || "gemini-3.6-flash";
      const contents: Array<{ role: string; parts: Array<{ text?: string; inlineData?: { mimeType: string; data: string } }> }> = [];

      if (Array.isArray(messages)) {
        for (const msg of messages) {
          const parts: Array<{ text?: string; inlineData?: { mimeType: string; data: string } }> = [];
          if (msg.content || msg.text) parts.push({ text: msg.content || msg.text });
          if (msg.image) {
            const matches = msg.image.match(/^data:(image\/[a-zA-Z]+);base64,(.+)$/);
            if (matches) {
              parts.push({ inlineData: { mimeType: matches[1], data: matches[2] } });
            }
          }
          if (parts.length > 0) {
            contents.push({
              role: msg.role === "assistant" || msg.role === "model" ? "model" : "user",
              parts,
            });
          }
        }
      }

      if (contents.length === 0) {
        contents.push({ role: "user", parts: [{ text: "Olá" }] });
      }

      if (!ai) {
        // PHX-FIX (auditoria completa — "tirar todos os fallbacks"): sem
        // chave Gemini configurada, esta rota devolvia uma resposta
        // fabricada com `usage: { promptTokens: 35, completionTokens: 48,
        // durationMs: 240, tokensPerSec: 200.0 }` — números inventados
        // apresentados como se uma inferência real tivesse rodado, texto
        // fixo alegando "Recebi sua mensagem com sucesso". O frontend
        // (AviaryApp.tsx) já trata `data.error` lançando e mostrando uma
        // mensagem de erro real na conversa — não precisa de uma resposta
        // de sucesso fabricada pra funcionar.
        return res.status(503).json({
          error: `Nenhuma chave Gemini configurada (GEMINI_API_KEY). Configure a chave para usar modelos Gemini, ou selecione um provedor local (Ollama / LM Studio / llama-server).`,
        });
      }

      const config: any = {
        systemInstruction: systemInstruction || "Você é a Phoenix Aviary Platform.",
      };
      if (typeof temperature === "number") config.temperature = temperature;
      if (typeof topP === "number") config.topP = topP;
      if (typeof topK === "number") config.topK = topK;
      // PHX-FIX (2026-09-06, achado real do usuário: "qualquer resposta...
      // fica cortada", acontecendo nos DOIS provedores sem erro nenhum -
      // ver PHX-FIX espelhado em llama_cpp.py/AviaryApp.tsx pro caso do
      // llama-server): confirmado (documentação oficial do Gemini +
      // múltiplos relatos de bug reproduzidos por outros projetos) que
      // modelos Gemini 2.5+/3.x vêm com "pensamento" LIGADO por padrão
      // quando nenhum thinkingConfig é enviado - e os tokens de
      // raciocínio contam contra o MESMO maxOutputTokens da resposta
      // visível. Sem folga extra, um maxTokens "razoável" pedido pelo
      // usuário pode ser consumido inteiro só "pensando" (finishReason
      // MAX_TOKENS, candidatesTokenCount=0) - resposta vazia ou cortada,
      // sem nenhum erro (é um término "normal" do lado da API, só que sem
      // texto nenhum sobrando). Mesmo sintoma do <think> não fechado nos
      // modelos locais, causa técnica completamente diferente (aqui não é
      // parsing de tag, é orçamento de token realmente compartilhado no
      // lado do Google).
      //
      // Corrigido com uma reserva de folga: quando o usuário pede um
      // maxTokens específico, mandamos maxOutputTokens MAIOR (+ reserva
      // pro raciocínio) - o usuário continua tendo a garantia de até
      // `maxTokens` pra resposta VISÍVEL, o raciocínio usa a folga extra
      // sem competir por esse espaço. "Sem limite" (maxTokens=0) não
      // define maxOutputTokens nenhum - fica livre pros dois.
      // `includeThoughts: true` expõe o resumo do raciocínio (quando o
      // modelo pensa) pra extrair como `reasoning` na resposta, mesmo
      // padrão do llama-server - ver extração abaixo.
      const GEMINI_THINKING_BUDGET_RESERVE = 4096;
      if (typeof maxTokens === "number" && maxTokens > 0) {
        config.maxOutputTokens = maxTokens + GEMINI_THINKING_BUDGET_RESERVE;
      }
      config.thinkingConfig = { includeThoughts: true };

      const startTime = Date.now();
      const response = await ai.models.generateContent({
        model: selectedModel,
        contents,
        config,
      });
      const endTime = Date.now();

      const outputText = response.text || "";
      const durationMs = endTime - startTime;

      // PHX-FIX (2026-09-06, mesma correção acima): `response.text` já
      // exclui os "thought parts" (é o que a própria SDK documenta) - pra
      // repassar o raciocínio pro front-end mostrar (mesmo campo
      // `reasoning` já usado no caminho do llama-server), extrai
      // manualmente as partes marcadas `thought: true` direto de
      // `candidates[0].content.parts`. Sem thoughts presentes (modelo não
      // pensou, ou includeThoughts não retornou nada nesta chamada),
      // fica como string vazia - nunca quebra a resposta principal.
      const thoughtParts = (response as any).candidates?.[0]?.content?.parts?.filter((p: any) => p?.thought) || [];
      const reasoningResult = thoughtParts.map((p: any) => p?.text || "").join("\n").trim();

      // PHX-FIX (varredura 2026-08-21, achado 3): promptTokens/
      // completionTokens/tokensPerSec vinham SEMPRE de uma heurística de
      // contagem de caracteres (`length/4`), mesmo quando o SDK do Gemini
      // já devolve a contagem real de tokens em `response.usageMetadata`
      // (promptTokenCount/candidatesTokenCount) - os números apareciam com
      // precisão decimal ("200.0") como se fossem medidos, sem nunca
      // avisar que eram estimativa. Agora usa o valor real do provedor
      // quando presente; só cai pra estimativa (marcada como tal) quando
      // o SDK não devolve usageMetadata.
      const usageMeta: any = (response as any).usageMetadata;
      const hasRealUsage = !!usageMeta && (typeof usageMeta.promptTokenCount === 'number' || typeof usageMeta.candidatesTokenCount === 'number');
      const promptTokens = hasRealUsage && typeof usageMeta.promptTokenCount === 'number'
        ? usageMeta.promptTokenCount
        : Math.ceil(JSON.stringify(contents).length / 4);
      const completionTokens = hasRealUsage && typeof usageMeta.candidatesTokenCount === 'number'
        ? usageMeta.candidatesTokenCount
        : Math.ceil(outputText.length / 4);
      const tokensPerSec = durationMs > 0 ? parseFloat(((completionTokens / durationMs) * 1000).toFixed(1)) : 0;

      res.json({
        text: outputText,
        reasoning: reasoningResult,
        usage: {
          promptTokens,
          completionTokens,
          durationMs,
          tokensPerSec,
          estimated: !hasRealUsage,
        },
      });
    } catch (error: any) {
      console.error("Gemini API Error:", error);
      res.status(500).json({ error: error.message || "Failed to generate response" });
    }
  });

  // API: Proxy Chat for Local / Custom providers
  //
  // PHX-NEW (achado real via screenshot do usuário: "[LLAMA-SERVER]
  // qwen3-8b-q4_k_m" falhava com 404 "File Not Found" em TODA mensagem,
  // até um "ola" - pedido explícito do usuário: "qualquer comando deveria
  // matar processo e subir modelo padrao e nao dar erro"): pra
  // "llama-server" especificamente (o único provedor local cujo processo
  // É gerenciado pela própria Phoenix Engine via RuntimeEngine -
  // Ollama/LM Studio são apps externos que o usuário controla, matar o
  // processo deles não é papel deste proxy), uma falha na primeira
  // tentativa agora aciona POST /api/engine/runtime/recover no Phoenix
  // Engine (mata o processo e sobe de novo com o modelo default do
  // catálogo) e tenta a MESMA mensagem mais uma vez, automaticamente, sem
  // o usuário precisar fazer nada. Só mostra erro pro usuário se a
  // recuperação ou a segunda tentativa também falharem. Quando a
  // recuperação funciona, a resposta inclui `recovered`/`recoveredModel`
  // pra a UI avisar que o modelo mudou pro default (ver AviaryApp.tsx) -
  // nunca troca de modelo em silêncio.
  function buildChatRequest(providerType: string, baseUrl: string, modelForRequest: string, messages: any, systemInstruction: string, temperature: number, maxTokens: number) {
    if (providerType === "ollama") {
      const formattedMsgs = [{ role: "system", content: systemInstruction || "Você é a Phoenix Aviary Platform." }];
      if (Array.isArray(messages)) {
        formattedMsgs.push(...messages.map((m: any) => ({ role: m.role, content: m.content || m.text || "" })));
      }
      return {
        endpointUrl: `${baseUrl.replace(/\/$/, "")}/api/chat`,
        payload: {
          model: modelForRequest,
          messages: formattedMsgs,
          stream: false,
          options: {
            temperature: typeof temperature === "number" ? temperature : 0.7,
            num_predict: typeof maxTokens === "number" ? maxTokens : 2048,
          },
        },
      };
    }
    const formattedMsgs = [{ role: "system", content: systemInstruction || "Você é a Phoenix Aviary Platform." }];
    if (Array.isArray(messages)) {
      formattedMsgs.push(...messages.map((m: any) => ({ role: m.role, content: m.content || m.text || "" })));
    }
    // PHX-FIX (achado real: 404 "File Not Found" em TODA mensagem pro
    // llama-server-local e lmstudio-local): DEFAULT_PROVIDERS em
    // AviaryApp.tsx já define baseUrl TERMINANDO em "/v1"
    // (ex: "http://localhost:8081/v1"), mas aqui embaixo sempre
    // grudávamos mais um "/v1/chat/completions" em cima, virando
    // ".../v1/v1/chat/completions" - rota que não existe, daí o 404
    // genérico do llama-server em TODA mensagem, sempre. Provado ao vivo
    // via PowerShell: chamando a URL correta (sem duplicar) direto no
    // llama-server, funciona perfeitamente. O /api/proxy/ping (scan de
    // modelos) já tinha essa mesma proteção - `cleanBase.endsWith("/v1")`
    // - e por isso o scan sempre funcionou enquanto o chat nunca
    // funcionou. Replicando a mesma lógica aqui.
    const cleanBase = baseUrl.replace(/\/$/, "");
    const endpointUrl = cleanBase.endsWith("/v1") ? `${cleanBase}/chat/completions` : `${cleanBase}/v1/chat/completions`;
    // PHX-NEW (2026-09-06, pedido do usuário: "aumentar contexto de
    // caracteres ou deixar livre pra modelo ter liberdade de escrita"):
    // antes, TODA chamada de chat mandava um teto de max_tokens (2048 se o
    // front-end não mandasse nada) - o backend Python já tinha essa opção
    // pra criação de documentos (unlimited_output, que OMITE max_tokens do
    // payload e deixa o llama-server parar sozinho por EOS ou fim físico
    // do contexto), mas o chat normal nunca ganhou o equivalente.
    // maxTokens===0 é o sinal explícito do checkbox "Sem limite" em
    // ParametersDrawer.tsx - omitir o campo inteiro (não mandar
    // "max_tokens: 0", que a maioria dos servidores OpenAI-compatible
    // trata como erro ou como "gerar zero tokens", o oposto do desejado).
    const payload: Record<string, unknown> = {
      model: modelForRequest,
      messages: formattedMsgs,
      temperature: typeof temperature === "number" ? temperature : 0.7,
      stream: false,
    };
    if (typeof maxTokens === "number" && maxTokens > 0) {
      payload.max_tokens = maxTokens;
    } else if (maxTokens !== 0) {
      // nem "sem limite" explícito nem um número válido - mantém o
      // default seguro de antes (não deixa a requisição sem noção
      // nenhuma de teto se o campo vier ausente/malformado por acidente)
      payload.max_tokens = 4096;
    }
    // maxTokens === 0: campo omitido de propósito - resposta livre.
    return { endpointUrl, payload };
  }

  app.post("/api/proxy/chat", async (req, res) => {
    const { providerType, baseUrl, apiKey, model, messages, temperature, maxTokens, systemInstruction } = req.body;

    // PHX-FIX (achado A7): mesma validação de destino do /api/proxy/ping -
    // ver resolveAllowedProxyTarget() no topo do arquivo.
    const targetCheck = await resolveAllowedProxyTarget(baseUrl || "");
    if (targetCheck.ok === false) {
      res.status(400).json({ error: targetCheck.reason });
      return;
    }

    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (apiKey) headers["Authorization"] = `Bearer ${apiKey}`;

    // PHX-FIX (achado real do usuário 2026-08-24, "Headers Timeout Error" -
    // ver PHX-FIX completo em cima da definição de `longRunningDispatcher`,
    // acima neste arquivo, pra causa raiz inteira): este fetch() nunca teve
    // `dispatcher` nem `AbortController` - ficava exposto ao teto global de
    // 300s do undici, e como o payload manda `stream: false` (nenhum byte
    // volta até a resposta INTEIRA terminar de ser gerada), uma resposta
    // longa em CPU pura (taxa real medida nesta máquina: ~4.6 tok/s) passa
    // desse teto bem antes de chegar no limite de tokens configurado.
    //
    // Timeout dinâmico, escalado pelo `maxTokens` do próprio pedido - mesmo
    // método já usado no timeout do Kokoro TTS (escalado por tamanho do
    // texto): CHAT_MS_PER_TOKEN vem de 1000/4.6 ≈ 217ms/tok (taxa real medida
    // nesta máquina, mesmo número citado no LEIA-ME da v54) arredondado pra
    // cima com margem de segurança (~40%) pra cobrir variação de carga da
    // CPU e modelos um pouco mais lentos - 300ms/tok. Quando o pedido não
    // manda `maxTokens`, usa o mesmo default de 2048 que buildChatRequest já
    // usa pro payload em si (consistência entre o timeout e o que de fato é
    // pedido ao modelo). Piso de 60s evita timeout curto demais pra
    // respostas pequenas (cold start do modelo, rede local, etc).
    //
    // PHX-FIX (2026-09-06, mesma rodada do aumento de contexto 16384->32768
    // e do checkbox "Sem limite" em ParametersDrawer.tsx): dois problemas
    // achados AQUI, nesta mesma conta de timeout, causados pelas duas
    // mudanças acima:
    //
    // (1) `effectiveMaxTokens = typeof maxTokens === "number" ? maxTokens :
    // 2048` tratava maxTokens===0 (o sinal de "sem limite" que acabamos de
    // criar) como um número válido igual a QUALQUER outro - 0*300ms=0ms,
    // e o piso de 60s (CHAT_MIN_TIMEOUT_MS) viraria o timeout INTEIRO de
    // uma resposta "sem limite". Nesta máquina (~4.6 tok/s), até uma
    // resposta modesta de 300 tokens já passa de 60s - toda requisição
    // "sem limite" seria abortada quase imediatamente, o EXATO problema que
    // o checkbox deveria resolver. Corrigido: maxTokens===0 agora orça o
    // timeout pelo CONTEXTO CHEIO (32768) - o pior caso real, já que uma
    // resposta sem teto pode em tese usar todo o contexto disponível.
    //
    // (2) O slider "Máximo de Tokens" subiu de 16384 pra 32768 (dobro) -
    // no pior caso (300ms/tok * 32768 = 9.830.400ms, ~164min), o
    // CHAT_MAX_TIMEOUT_MS antigo (5_000_000ms, ~83min) cortaria a conexão
    // ANTES do modelo terminar uma resposta genuinamente longa no novo
    // teto - recriando o mesmo sintoma ("resposta cortada") por um
    // mecanismo diferente (timeout de rede, não teto de tokens). Subido
    // pra 9_900_000ms (~165min, ~70s de margem acima do pior caso exato).
    // Isso por sua ver exige subir o teto do `longRunningDispatcher`
    // (definido acima, compartilhado com o audiolivro) - ver ajuste lá.
    const CHAT_MS_PER_TOKEN = 300;
    const CHAT_MIN_TIMEOUT_MS = 60_000;
    const CHAT_MAX_TIMEOUT_MS = 9_900_000;
    const effectiveMaxTokens =
      typeof maxTokens === "number" && maxTokens > 0
        ? maxTokens
        : maxTokens === 0
          ? 32768 // "sem limite" - orça pelo pior caso (contexto cheio), nunca por 0
          : 2048; // ausente/inválido - default seguro de sempre
    const chatTimeoutMs = Math.min(
      CHAT_MAX_TIMEOUT_MS,
      Math.max(CHAT_MIN_TIMEOUT_MS, effectiveMaxTokens * CHAT_MS_PER_TOKEN)
    );

    async function attempt(modelForRequest: string) {
      const { endpointUrl, payload } = buildChatRequest(providerType, baseUrl, modelForRequest, messages, systemInstruction, temperature, maxTokens);
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), chatTimeoutMs);
      const startTime = Date.now();
      try {
        const response = await fetch(endpointUrl, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
          signal: controller.signal,
          dispatcher: longRunningDispatcher,
        } as RequestInit & { dispatcher: UndiciAgent });
        const durationMs = Date.now() - startTime;
        if (!response.ok) {
          const errText = await response.text();
          return { ok: false as const, status: response.status, errText, payload };
        }
        const data: any = await response.json();
        return { ok: true as const, data, payload, durationMs };
      } finally {
        clearTimeout(timeoutId);
      }
    }

    try {
      let result = await attempt(model);
      let recovered = false;
      let recoveredModel: string | null = null;

      if (!result.ok && providerType === "llama-server") {
        try {
          const recoverRes = await fetch(`${PHOENIX_ENGINE_URL}/api/engine/runtime/recover`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ runtime: "llama.cpp" }),
          });
          const recoverData: any = await recoverRes.json().catch(() => null);
          if (recoverRes.ok && recoverData?.ok && recoverData?.model) {
            recovered = true;
            recoveredModel = recoverData.model;
            result = await attempt(recoverData.model);
          }
        } catch {
          // Phoenix Engine inacessível pra recuperar - segue com o erro
          // original abaixo, não inventa uma recuperação que não aconteceu.
        }
      }

      if (!result.ok) {
        const detail = recovered
          ? `Endpoint retornou (${result.status}): ${result.errText.slice(0, 200)} (tentei recuperar automaticamente com o modelo default e também falhou)`
          : `Endpoint retornou (${result.status}): ${result.errText.slice(0, 200)}`;
        res.status(result.status).json({ error: detail });
        return;
      }

      const { data, payload, durationMs } = result;
      // PHX-FIX (2026-09-06, mesma investigação do achado "resposta corta
      // sem erro nenhum" - ver PHX-FIX em llama_cpp.py/_build_server_args
      // sobre --jinja): antes, só `content` era lido - quando o servidor
      // já separa corretamente o "pensamento" de Qwen3/modelos de
      // raciocínio num campo `reasoning_content` à parte (o que --jinja
      // agora garante), essa separação era jogada fora aqui e nunca
      // chegava no front-end, que dependia 100% de um regex frágil
      // tentando separar de novo a partir de um blob só (e falhava quando
      // a tag <think> vinha cortada no meio, sem fechar). Agora repassamos
      // os dois campos separados pro front-end usar diretamente quando
      // disponíveis - o regex em AviaryApp.tsx continua como rede de
      // segurança pra quando o servidor não faz essa separação (modelo/
      // template sem suporte), mas deixa de ser a ÚNICA linha de defesa.
      const textResult = providerType === "ollama" ? (data.message?.content || "") : (data.choices?.[0]?.message?.content || "");
      const reasoningContentResult = providerType === "ollama" ? "" : (data.choices?.[0]?.message?.reasoning_content || "");
      // PHX-FIX (varredura 2026-08-21, achado 3): `tokensPerSec` era
      // calculado SEMPRE a partir da estimativa por contagem de
      // caracteres (`completionTokensEst`), mesmo quando o provedor real
      // já informava `data.usage.completion_tokens` - só o campo
      // `completionTokens` da resposta usava o valor real quando
      // disponível. Resultado: o número de tokens mostrado e o
      // tokens/s mostrado podiam descrever contagens diferentes de
      // token. Agora os dois usam a mesma fonte (real quando o provedor
      // informa, estimativa só quando não informa), e a resposta marca
      // explicitamente quando é estimativa.
      const hasRealCompletionTokens = typeof data.usage?.completion_tokens === 'number';
      const completionTokens = hasRealCompletionTokens ? data.usage.completion_tokens : Math.ceil(textResult.length / 4);
      const tokensPerSec = durationMs > 0 ? parseFloat(((completionTokens / durationMs) * 1000).toFixed(1)) : 0;

      res.json({
        text: textResult,
        reasoning: reasoningContentResult,
        usage: {
          promptTokens: typeof data.usage?.prompt_tokens === 'number' ? data.usage.prompt_tokens : Math.ceil(JSON.stringify(payload.messages).length / 4),
          completionTokens,
          durationMs,
          tokensPerSec,
          estimated: !hasRealCompletionTokens,
        },
        recovered,
        recoveredModel,
      });
    } catch (err: any) {
      // PHX-FIX: fetch() do Node/undici lança um TypeError genérico
      // "fetch failed" com a causa REAL escondida em err.cause (ex:
      // "connect ECONNREFUSED ::1:8081", "ETIMEDOUT", etc.) - sem isso
      // aparecer na mensagem, é impossível diferenciar "processo caiu",
      // "porta errada" e "resolução de IPv6/IPv4 errada" só olhando o
      // erro que a UI mostra. Agora o motivo real vem junto.
      //
      // PHX-FIX (mesmo achado do timeout dinâmico acima, 2026-08-24): agora
      // que este fetch() tem um AbortController de verdade, um estouro do
      // `chatTimeoutMs` lança um AbortError puro - sem tratar esse caso à
      // parte ele cairia no `causeMsg` genérico abaixo (AbortError nativo
      // não tem `err.cause` útil nenhum), voltando a mostrar um "fetch
      // failed" confuso pro usuário mesmo já sabendo a causa exata. Mesmo
      // padrão `isAbort` já usado em todas as outras rotas de longa duração
      // deste arquivo (describe-image, generate-image, documents/*, etc).
      const isAbort = err?.name === "AbortError";
      if (isAbort) {
        const timeoutSec = Math.round(chatTimeoutMs / 1000);
        res.status(504).json({
          error: `Tempo esgotado esperando o modelo terminar de gerar a resposta (${timeoutSec}s, calculado a partir do limite de tokens do pedido). Se a resposta era mesmo muito longa, isso pode ser esperado num modelo rodando em CPU - tente reduzir "Máximo de Tokens" nos parâmetros ou aguardar mais.`,
        });
        return;
      }
      const causeMsg = err?.cause?.message || (err?.cause ? String(err.cause) : null);
      const fullMsg = causeMsg ? `${err.message || "Network error"} (causa: ${causeMsg})` : (err.message || "Network error");
      res.status(500).json({ error: `Proxy request failed: ${fullMsg}` });
    }
  });

  // API: síntese de voz local (Kokoro) - proxy RÁPIDO pro botão de voz do
  // chat (timeout curto de propósito, ver PHX-NEW abaixo). Rota mantida em
  // /api/tts/piper por compatibilidade (nome interno, não visível pro
  // usuário) - o motor por trás não é mais o Piper desde 2026-08-23.
  app.post("/api/tts/piper", async (req, res) => {
    const { text, voice } = req.body;
    if (!text) {
      return res.status(400).json({ error: "Campo 'text' obrigatório." });
    }

    // PHX-FIX (auditoria completa — "tirar todos os fallbacks"): o catch
    // abaixo mandava res.status(502).json(...) SEM `return` e, logo em
    // seguida, o código sempre mandava uma SEGUNDA resposta (o 503 de
    // fallback) — resposta dupla (ERR_HTTP_HEADERS_SENT). O 503 em si não é
    // fabricação de dado (o client trata qualquer !ok como sinal honesto
    // pra usar a Web Speech API real do navegador, ver piperTtsService.ts),
    // só precisava virar UMA resposta por caminho, nunca duas.
    //
    // PHX-NEW (2026-08-23, troca Piper -> Kokoro-82M como motor padrão):
    // timeout subiu de 3s pra 15s. Medição real feita nesta auditoria: a
    // PRIMEIRA síntese Kokoro depois de o Phoenix Engine subir (carrega o
    // modelo ONNX de ~310MB na memória) levou ~2.3s numa máquina de teste
    // BEM mais fraca (2 vCPUs) que a do usuário final (Xeon 12
    // núcleos/24 threads) - 3s arriscava estourar exatamente na primeira
    // mensagem de cada sessão. Sínteses seguintes (modelo já carregado)
    // ficaram em ~1.4s pra um texto de tamanho de resposta de chat.
    //
    // PHX-FIX (achado real do usuário 2026-08-24, "kokoro ora funciona ora
    // não" no botão de voz do chat - relatado JUNTO com um pedido de
    // respostas mais longas, o que torna o problema mais provável, não
    // menos): os 15s acima eram FIXOS, calibrados só pra "um texto de
    // tamanho de resposta de chat" TÍPICA (curta). O botão de voz sintetiza
    // QUALQUER texto de chat, incluindo as respostas longas e estruturadas
    // que a busca na web (v52) passou a produzir com frequência (múltiplas
    // seções, podendo passar de mil caracteres). A síntese do Kokoro é
    // CPU-bound e seu tempo cresce com o tamanho do texto (documentado em
    // documents/audiobook.py: ~0.4-0.5x a duração do áudio resultante,
    // nesta mesma máquina de referência) - mas o timeout nunca mudava. Pra
    // textos longos, dependendo também da carga momentânea da CPU (o
    // próprio modelo de chat roda em CPU), a síntese ora terminava a tempo,
    // ora não - exatamente o padrão intermitente relatado.
    //
    // Correção: o timeout agora escala com o tamanho do texto em vez de
    // ficar fixo. A taxa (30ms/caractere) é uma ESTIMATIVA conservadora
    // derivada da MESMA medição real citada acima (não é um número novo
    // inventado agora): ~150 palavras/min de fala x ~6 caracteres/palavra
    // (com espaço) dá ~15 caracteres de áudio por segundo; aplicando o pior
    // caso já medido (0.5x tempo real) chega em ~33ms de síntese por
    // caractere - arredondado pra 30ms/caractere. Aplicando essa taxa a um
    // texto de ~400 caracteres (tamanho típico de resposta curta) dá ~12s,
    // perto o suficiente dos 15s já calibrados manualmente nesta mesma
    // máquina pra dar confiança na estimativa (a diferença é a folga do
    // cold-start do modelo, também já documentada acima). O piso de 15s é
    // mantido pra textos curtos (preserva a falha rápida já testada, se o
    // motor estiver mesmo fora do ar); o teto de 120s evita espera
    // indefinida se algo estiver de fato quebrado (nesse caso, sugerir a
    // ferramenta "Texto Livre", que não tem limite de tempo - ver rota
    // /api/synthesize-speech acima). Isto é uma estimativa documentada, não
    // uma medição de laboratório na máquina real do usuário - os logs do
    // Phoenix Engine agora registram a duração real de cada síntese (ver
    // resident_manager.py) pra permitir recalibrar com dado real no futuro.
    const KOKORO_MS_PER_CHAR = 30;
    const KOKORO_MIN_TIMEOUT_MS = 15000;
    const KOKORO_MAX_TIMEOUT_MS = 120000;
    const kokoroTimeoutMs = Math.min(
      KOKORO_MAX_TIMEOUT_MS,
      Math.max(KOKORO_MIN_TIMEOUT_MS, text.length * KOKORO_MS_PER_CHAR)
    );
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), kokoroTimeoutMs);
      const engineRes = await fetch(`${PHOENIX_ENGINE_URL}/api/synthesize-speech`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: voice || "" }),
        signal: controller.signal,
      });
      clearTimeout(timer);

      if (engineRes.ok) {
        const engineData: any = await engineRes.json();
        if (engineData.audio_base64) {
          return res.json({
            success: true,
            engine: `Kokoro TTS (${engineData.voice || voice || 'auto'} / Phoenix Engine)`,
            audioUrl: `data:audio/wav;base64,${engineData.audio_base64}`,
          });
        }
      }
    } catch {
      // Rede/timeout - cai no mesmo 503 honesto abaixo, não fabrica áudio.
    }

    // 503: sinal honesto pro client tocar via Web Speech API real do
    // navegador (não é dado fabricado — é uma síntese de voz de verdade,
    // só que num motor diferente do Kokoro).
    res.status(503).json({
      success: false,
      fallback: true,
      error: "Síntese de voz local (Kokoro) indisponível no Phoenix Engine — utilizando síntese de voz do navegador.",
    });
  });

  // PHX-FIX (auditoria completa — "tirar todos os fallbacks", o maior
  // achado desta rodada): quando o fetch pro Phoenix Engine falhava (rede/
  // timeout) OU respondia com status não-OK, ~200 linhas de comandos
  // hardcoded assumiam o lugar do kernel real - "status", "ports",
  // "manager analyze", "resident research/approve/reject", "search",
  // "ocr", "infer", "models", "logs", "validate", "security", "install
  // list/package" e até um catch-all genérico ("Comando '...' processado
  // com sucesso") respondiam com texto de terminal fabricado, sempre
  // alegando sucesso, sempre com os mesmos números fixos de hardware
  // (Xeon E5-2690 v3, RX 580, GPU Score 95%, temperatura 52°C) - nenhuma
  // dessas informações vinha de uma leitura real. O Resident Manager
  // "aprovando missões" e o OCR "extraindo texto" eram só strings prontas.
  // Pior: o catch já mandava uma resposta de erro (502) sem `return`, e a
  // função sempre continuava e tentava mandar essa segunda resposta
  // fabricada por cima - resposta dupla (ERR_HTTP_HEADERS_SENT).
  //
  // O processamento real de comandos já existe no Python
  // (phoenix_kernel/api/engine.py: ApiEngine.process_command), incluindo
  // 'help'/'status'/'ports'/etc - nada de funcionalidade real se perde
  // removendo a cópia JS fabricada. Agora: sucesso real passa direto;
  // qualquer falha (rede OU status não-OK) devolve um erro real e claro,
  // nunca um terminal de mentira fingindo que o comando rodou.
  //
  // Exceção: 'ai <prompt>' continua tratado aqui quando há chave Gemini
  // configurada, porque ele dispara uma chamada de IA em nuvem de verdade
  // (não fabrica nada - é um caminho de execução real, alternativo ao
  // Phoenix Engine local). Só a resposta "local" de qualquer prompt quando
  // NÃO há chave Gemini (texto fixo fingindo ser uma resposta computada)
  // foi removida.
  app.post("/api/command", async (req, res) => {
    const rawCmd = (req.body.command || "").trim();
    const cmd = rawCmd.toLowerCase();

    if (!cmd) {
      return res.json({ output: "" });
    }

    if (cmd.startsWith("ai ")) {
      const query = rawCmd.substring(3).trim();
      const ai = getGeminiClient();
      if (ai) {
        try {
          const resp = await ai.models.generateContent({
            model: "gemini-3.6-flash",
            contents: `Consulta de Engenharia: ${query}`,
            config: {
              systemInstruction: `Você é o Engenheiro Chefe da Phoenix Engine (Porta 8000) e da Phoenix Aviary Platform (Porta 3000). Responda com precisão técnica em Português do Brasil, formato de console conciso e objetivo.`
            }
          });
          return res.json({ output: resp.text || "Sem resposta do núcleo AI." });
        } catch (e: any) {
          return res.status(502).json({ error: `[AI CORE ERROR] ${e.message}` });
        }
      }
      // Sem chave Gemini configurada e sem depender do Phoenix Engine local
      // pra esse caminho específico - erro real, não uma resposta fabricada
      // fingindo ter processado a pergunta.
      return res.status(503).json({
        error: "Nenhum provedor de IA disponível para 'ai <prompt>': configure GEMINI_API_KEY ou use o Phoenix Engine local (porta 8000) via 'ai' processado pelo kernel.",
      });
    }

    // Execução real via Phoenix Engine (Port 8000) - ApiEngine.process_command
    try {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 6000);
      const r = await fetch(`${PHOENIX_ENGINE_URL}/api/command`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: rawCmd }),
        signal: ctrl.signal,
      });
      clearTimeout(t);
      const data = await r.json().catch(() => null);
      if (r.ok && data) return res.json(data);
      return res.status(r.status || 502).json({ error: (data && (data as any).detail) || `Phoenix Engine devolveu status ${r.status} ao processar o comando.` });
    } catch (err: any) {
      return res.status(502).json({ error: `Phoenix Engine offline ou inacessível: ${describeFetchError(err)}` });
    }
  });

  // PHX-FIX (auditoria 2026-08-20, "Frontend JSON error handling" / Seção
  // 10): achado real - uma rota de API não encontrada (ex: /api/algumacoisa
  // com typo, ou método HTTP errado) caía no catch-all `app.get('*', ...)`
  // do SPA logo abaixo e devolvia index.html (HTML) em vez de um 404 JSON.
  // Isso é exatamente o padrão do bug "Unexpected token '<'" quando o
  // frontend esperava JSON de /api/*. Fecha esse buraco: qualquer /api/*
  // sem rota correspondente responde 404 JSON aqui, ANTES do fallback do
  // SPA, que só deve tratar rotas de navegação de página (não-API).
  app.use("/api", (_req, res) => {
    res.status(404).json({ error: "Rota de API não encontrada." });
  });

  // Vite development middleware or static production serving
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    // RegExp funciona em Express 4 e 5. A string "*" deixou de ser válida
    // no path-to-regexp usado pelo Express 5.
    app.get(/.*/, (_req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, HOST, () => {
    console.log(`[PHOENIX CORE] Dual process platform online at http://${HOST}:${PORT}`);
  });
}

startServer();
