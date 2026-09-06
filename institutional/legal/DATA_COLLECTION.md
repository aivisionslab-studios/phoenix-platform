# Política de Coleta de Dados — AIVisions Phoenix Engine

Complementa a [Política de Privacidade](./PRIVACY_POLICY.md) detalhando exatamente o que pode ser armazenado ou transmitido.

## 1. Dados que PODEM ser coletados (local, e opcionalmente enviados ao Firestore)

| Categoria | Exemplos |
|---|---|
| Hardware | CPU, GPU, VRAM, RAM, armazenamento disponível |
| Sistema | Sistema operacional, versão, drivers instalados |
| Telemetria de sensores | Temperatura, uso de CPU/GPU, uso de disco |
| Operação da Phoenix | Missões instaladas, containers ativos, logs de execução |
| Erros | Logs de falhas para diagnóstico (sem conteúdo de prompts) |

## 2. Dados que NUNCA são coletados (pela AIVisionsLab)

- ❌ Documentos pessoais
- ❌ Imagens processadas pelo usuário
- ❌ Prompts enviados a modelos de IA
- ❌ Conversas/chats
- ❌ Senhas, chaves de API ou credenciais
- ❌ Conteúdo de arquivos do sistema fora do escopo da Phoenix

> **Escopo desta seção:** "nunca coletado" descreve o que a **AIVisionsLab** recebe ou armazena. É
> diferente de "nunca sai da sua máquina": se você optar por um provedor de IA de nuvem de terceiros no
> chat (ex.: Gemini, configurado por você com sua própria chave de API), seu prompt é processado pelos
> servidores desse terceiro, sob a política de privacidade dele — a AIVisionsLab não recebe nem coleta
> esse conteúdo em nenhum dos dois casos. O conteúdo do RAG (documentos indexados) continua bloqueado
> por padrão de ir para qualquer provedor de nuvem, mesmo nesse cenário — ver
> [Política de Privacidade](./PRIVACY_POLICY.md).

## 3. Anonimização

Quando a telemetria é enviada ao Firestore (mediante opt-in), os dados são associados a um identificador técnico de instalação, **não** a dados pessoais identificáveis, salvo se o usuário fornecer voluntariamente essas informações em outro contexto (ex.: suporte).

## 4. Retenção

Dados armazenados localmente permanecem sob controle do usuário. Dados eventualmente enviados ao Firestore seguem prazos de retenção definidos para fins de melhoria de produto, podendo ser removidos mediante solicitação.
