# Segurança — AIVisions Phoenix Engine

Documentação técnica de segurança. Para o processo de reporte de vulnerabilidades, ver [SECURITY_POLICY](../legal/SECURITY_POLICY.md).

## Princípios de segurança da arquitetura

A Phoenix nunca:
- Instala software sem autorização explícita do usuário;
- Abre portas de rede automaticamente sem consentimento;
- Altera regras de firewall sem confirmação;
- Acessa documentos pessoais fora do escopo declarado de uma missão.

Por padrão, também não envia o conteúdo de documentos privados (RAG) para servidores externos — nem
mesmo se o usuário escolher um provedor de IA de nuvem (ex.: Gemini) no chat, uma trava dedicada
(ligada por padrão) impede que o conteúdo do RAG saia da máquina nesse caso. Essa proteção específica
**pode ser desligada manualmente pelo usuário** em Parâmetros do chat, caso ele queira usar RAG com um
provedor de nuvem mesmo assim — nesse cenário, e apenas nesse, texto de documentos indexados é enviado
ao provedor escolhido. Fora dessa escolha explícita, nenhum arquivo privado sai da máquina.

## Camadas de proteção

> **Nota de precisão (2026-08-28):** esta seção descrevia um `RiskEngine` (classificação de risco
> por ação) e um `ContractValidator` como camadas já entregues. Auditando o código, nenhuma das
> duas classes existe hoje — eram parte da visão-alvo "Phoenix Engine 5.0" (ver nota no topo do
> [`README.md`](../../README.md)), não da linha Phoenix 3.0 que roda de fato. A lista abaixo
> descreve o que existe de verdade.

1. **Fluxo de aprovação do Mission Kernel** — toda missão com passos (instalar pacote, baixar
   modelo, trocar o modelo de chat carregado, gerar imagem etc.) fica pendente até uma confirmação
   humana explícita (`aprovar`/`rejeitar`). É um portão único e uniforme: hoje **não existe**
   classificação de risco que libere passos "seguros" automaticamente — toda missão passa pelo
   mesmo gate, independente do tipo de ação.
2. **Guardas de hardware (thermal/VRAM)** — antes de trocar de modelo ou iniciar uma tarefa pesada,
   o Resident Manager confere temperatura e VRAM livre (quando o AHDE já tiver dados) e tenta
   liberar espaço soltando modelos GPU-pesados que não são o alvo. São guardas que avisam e tentam
   ajudar, não travas bloqueantes — a decisão de prosseguir continua automática.
3. **Isolamento por processo, não por sandbox dedicado** — trocar o modelo de chat mata o processo
   `llama-server` anterior e sobe um processo novo (nunca dois processos de chat concorrentes na
   mesma porta; a única exceção é a Arena, que sobe uma segunda instância dedicada em outra porta
   de propósito). Análise de imagem/OCR (`llama-mtmd-cli`) e geração de imagem
   (`stable-diffusion.cpp`) rodam como processos "de um tiro" — sobem, processam e encerram
   sozinhos, sem servidor residente entre uma chamada e outra.
4. **Containers Docker** — usados apenas pelos serviços opcionais (Ollama, Open WebUI, SearXNG).
   O runtime padrão da Phoenix (llama.cpp nativo para chat e visão/OCR, stable-diffusion.cpp
   nativo para imagem, ambos compilados com Vulkan) roda como processo nativo, não em container.

## Execution Guard / Sandbox

Hoje **não existe** uma camada dedicada de "Execution Guard" com rollback automático para ações de
sistema (remoção de container, alteração de configuração). A proteção real contra uma ação
destrutiva continua sendo a aprovação manual descrita acima: nada roda sem o usuário confirmar a
missão primeiro. Um guarda de execução com rollback automático é uma melhoria de segurança real
ainda não implementada — não uma camada já entregue.

## Telemetria remota (Firestore) — verificação de consentimento

> **Verificação (2026-08-28, a pedido do usuário):** conferido linha a linha se o scanner de
> hardware (`hardware_engine/`, tick a cada `CLOUD_SYNC_INTERVAL_SEC` = **60 segundos**, ver
> `phoenix_kernel/kernel.py`) envia dado de sensor pro Firestore sem autorização explícita. Não
> envia — mas o mecanismo de consentimento tem uma peça faltando na interface, documentada abaixo.

O que o código faz de fato, hoje:

- O loop de 60s (`Kernel._cloud_sync_loop`) sempre RODA (se a biblioteca `google-cloud-firestore`
  estiver instalada), mas cada operação que de fato manda algo para fora — `sync_machine_state`
  (hardware/telemetria), `sync_knowledge_base`, `sync_install_reports`,
  `push_to_shared_pool`, `pull_shared_knowledge_base` — começa com `if not has_consent(): return`
  (`phoenix_kernel/cloud_sync.py`). Sem o arquivo `data/telemetry_consent.flag`, nenhuma delas
  chega a abrir conexão com o Firestore.
- Esse arquivo só é criado por `grant_consent()`, e `grant_consent()` só é chamado num único lugar
  em todo o código-fonte: a rota `POST /api/telemetry/consent/accept`
  (`api_server.py`). Nenhum script de instalação (`install/*.ps1`, `install_phoenix.ps1`,
  `setup_environment.py`, `setup_platform.py`) e nenhum outro módulo cria ou "pré-aceita" esse
  arquivo. Coleta local (pro dashboard/Resident Manager) sempre acontece — como a própria
  [Política de Telemetria](../legal/TELEMETRY_POLICY.md) já descreve — mas o envio remoto exige
  esse consentimento explícito, sem exceção encontrada na auditoria.
- **Gap real encontrado:** a [Política de Telemetria](../legal/TELEMETRY_POLICY.md), item 5, diz
  que o compartilhamento "pode ser desligado a qualquer momento nas configurações da Phoenix" — mas
  hoje **não existe nenhum botão/toggle na interface** (Aviary nem Mission Control) que chame
  `/api/telemetry/consent/accept` ou `/decline`. As duas rotas existem e funcionam (testável via
  `curl`/API direta), só não estão conectadas a nenhum componente do frontend
  (`platform_source/src/`) ainda. Na prática isso significa o oposto do medo original: um usuário
  comum hoje **não consegue nem ligar** a telemetria remota pela interface, mesmo querendo — não é
  um caso de dado saindo sem autorização, é uma funcionalidade prometida na política que ainda não
  foi conectada na UI.
- **Limite desta verificação:** o histórico do repositório público (`github.com/aivisionslab-
  studios/phoenix-engine`) está como um único commit squashed, sem histórico anterior preservado —
  não há como usar `git blame`/`git log` pra confirmar desde quando este comportamento existe nem
  atribuir uma versão específica a uma sessão de desenvolvimento anterior (ex.: "a última versão
  feita no Gemini AI Studio"). Se houver uma cópia/arquivo daquela versão específica disponível,
  uma comparação direta de `phoenix_kernel/cloud_sync.py` e `phoenix_kernel/kernel.py` entre as
  duas resolveria isso com certeza, em vez de inferência.

## Permissões

O usuário mantém controle total sobre quais permissões concede à Phoenix — nenhuma ação de sistema é escalada silenciosamente.
