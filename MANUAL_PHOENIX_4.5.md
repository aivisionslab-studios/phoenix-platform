# Manual de Uso — Phoenix 4.5

Guia de uso da Phoenix 4.5, atualizado para a arquitetura atual de execução, distribuição,
atualização, recuperação, integridade e telemetria técnica.

## Sumário

1. Visão geral
2. Como iniciar
3. Interfaces e serviços
4. Chat e modelos
5. Provedores de nuvem
6. Modos de execução
7. RAG
8. Documentos e planilhas
9. Imagens
10. Voz e transcrição
11. Busca web
12. Arena
13. Mission Control
14. App Store e missões
15. Free x Pro
16. Atualizações e rollback
17. Recuperação após interrupção
18. Integridade e estado da instalação
19. Privacidade, telemetria e diagnóstico
20. Solução de problemas

---

## 1. Visão geral

A Phoenix é uma plataforma de IA **local-first** que orquestra modelos de linguagem, imagem, voz,
RAG, busca e workflows de documentos. O Engine coordena hardware, recursos e execução; a Aviary é a
interface principal para conversar e usar os recursos.

O processamento principal pode permanecer inteiramente local, mas a Phoenix também pode utilizar
rede para downloads, updates, busca, provedores externos e telemetria/diagnóstico técnico.

A arquitetura atual de release/upgrade foi fechada após auditoria integral, com **1.159 testes aprovados**, **3 ignorados por condição de ambiente** e **0 falhas** no ambiente de auditoria.

---

## 2. Instalação e como iniciar

A Phoenix pode ser instalada a partir de uma **release/ZIP** ou de um **clone do repositório**.
Instalação limpa e atualização são fluxos diferentes: para atualizar uma instalação existente, use
o updater da Phoenix em vez de extrair arquivos novos por cima da pasta antiga.

### 2.1 Windows 10/11 — release/ZIP

1. Baixe a release.
2. Extraia em uma pasta nova, por exemplo `C:\PHOENIX 4.5`.
3. Clique com o botão direito em `Iniciar_Phoenix.bat` e escolha **Executar como administrador**.
4. Aguarde o provisionamento inicial. Se o instalador pedir reinício, reinicie e execute o launcher
   novamente.
5. Ao finalizar, acesse `http://localhost:3000` para a Aviary ou `http://localhost:8000` para o
   Mission Control.

O launcher também executa os gates de recovery e integridade antes de subir os serviços.

### 2.2 Windows 10/11 — clone do repositório

Se necessário, instale Git:

```powershell
winget install --id Git.Git -e --source winget
```

Depois:

```powershell
cd C:\
git clone https://github.com/aivisionslab-studios/phoenix-engine.git
cd phoenix-engine
.\Iniciar_Phoenix.bat
```

Para chamar o bootstrap diretamente:

```powershell
.\install_phoenix.ps1
```

O provisionamento pode usar `winget`, instalar/validar PowerShell 7, Node.js, Python/venv, ferramentas
de compilação, Vulkan e componentes auxiliares. Algumas alterações do Windows podem exigir
reinicialização.

### 2.3 Linux — Ubuntu/Debian

Instale Git e confirme PowerShell 7 (`pwsh`). Em seguida:

```bash
sudo apt update
sudo apt install -y git
git clone https://github.com/aivisionslab-studios/phoenix-engine.git
cd phoenix-engine
sudo pwsh ./install_phoenix.ps1
```

Depois do provisionamento:

```bash
./Iniciar_Phoenix.sh
```

Se necessário:

```bash
chmod +x ./Iniciar_Phoenix.sh
./Iniciar_Phoenix.sh
```

A automação Linux pode instalar/validar ferramentas de compilação, Python, Node, FFmpeg, Tesseract,
Mesa/Vulkan, sensores e outros pacotes necessários. A disponibilidade concreta depende da versão do
sistema, kernel e repositórios da distribuição.

Verificação básica do Vulkan:

```bash
vulkaninfo --summary
```

### 2.4 Instalação limpa x atualização

Para uma instalação realmente limpa, use uma pasta nova. Extrair uma release nova por cima de uma
pasta antiga não remove arquivos que deixaram de existir entre versões.

Para atualizar uma instalação já existente:

```text
Atualizar_Phoenix.bat <release.zip> [source|windows-ready]
```

Esse fluxo usa as proteções de upgrade, migrations, rollback, anti-rollback, recovery e integridade
da Phoenix.

---

## 3. Interfaces e serviços

| Serviço | Porta padrão | Finalidade |
|---|---:|---|
| Phoenix Aviary | 3000 | Chat, RAG, imagem, voz, Arena e documentos |
| Phoenix Engine / Mission Control | 8000 | API, hardware, recursos, observabilidade e missões |
| Phoenix Llama Runtime | 8081 | Runtime local de LLM quando ativo |

---

## 4. Chat e modelos

Na Aviary, selecione um modelo disponível e envie sua mensagem.

Provedores locais podem incluir Phoenix Llama Runtime/llama.cpp, Ollama e LM Studio.

A lista mostrada deve refletir os provedores/modelos realmente detectados.

---

## 5. Provedores de nuvem

Provedores como Gemini são opcionais e exigem configuração do usuário.

Quando um modelo de nuvem é escolhido, o conteúdo enviado a ele é processado também segundo os
termos e a política do fornecedor externo.

A proteção do RAG para provedores de nuvem é uma configuração separada: quando ativa, o contexto
privado do Knowledge Repository não é anexado à requisição ao provedor.

---

## 6. Modos de execução

A Phoenix pode trabalhar em:

- **CPU**
- **GPU**
- **HYBRID**
- **AUTO**

Em modos explícitos, a Phoenix tenta respeitar exatamente a modalidade solicitada e retorna erro
quando ela não pode ser satisfeita com segurança/correção.

Em **AUTO**, a plataforma pode escolher uma alternativa conforme VRAM/RAM disponível, telemetria,
compatibilidade conhecida e características do modelo.

O comportamento real também depende do runtime, quantização, tamanho do contexto e hardware.

---

## 7. RAG — Base de Conhecimento

O Knowledge Repository permite indexar documentos e utilizar trechos relevantes como contexto.

### Formatos

PDF, DOCX, XLSX, PPTX, TXT, MD e formatos de imagem suportados pelo pipeline OCR.

### Limites

| Recurso | Free | Pro |
|---|---:|---:|
| Documentos lógicos | 10 | Sem limite artificial |
| Tamanho máximo por arquivo | 25 MB | 100 MB |
| Texto extraído total | 150.000.000 caracteres | 600.000.000 caracteres |

O orçamento de caracteres é agregado ao repositório e calculado antes do chunking.

### Atualização de documento

Reenviar um documento reconhecido como o mesmo item lógico é tratado como reindexação/atualização,
sem consumir uma nova vaga.

### Integridade e segurança

A Phoenix usa controles multicamadas para garantir que somente documentos autorizados e consistentes
sejam utilizados pelo RAG. Se a integridade necessária não puder ser comprovada, o repositório pode
ficar temporariamente indisponível em modo **fail-closed**, sem apagar automaticamente os documentos.

A documentação pública não detalha a implementação interna desses controles.

### Mudança futura de embeddings

Mudanças incompatíveis de dimensão ou estratégia de embedding não apagam o banco atual. A Phoenix
possui workflow explícito de reindex/migração que trabalha com nova coleção e validação antes de
trocar a coleção ativa.

---

## 8. Documentos e planilhas

A Phoenix pode:

- ler documentos;
- resumir e responder sobre arquivos;
- criar PDF/DOCX/XLSX/PPTX/TXT/MD;
- transformar formatos;
- preencher planilhas a partir de documentos-fonte;
- usar OCR quando necessário.

O pipeline atual separa extração, normalização, identificação, resolução semântica e escrita de
saída. Campos sensíveis a exatidão podem exigir revisão ou evidência adicional em vez de preenchimento
inventado.

---

## 9. Imagens

A geração principal utiliza **Phoenix Diffusion**.

Modelos atualmente priorizados:

- Stable Diffusion 1.5;
- SDXL.

FLUX e SD 3.5 não fazem parte do caminho principal atual.

O backend nativo é executado em worker isolado para reduzir o impacto de crash de biblioteca nativa.

---

## 10. Voz e transcrição

A Phoenix oferece:

- texto para áudio;
- documento para áudio;
- transcrição de áudio;
- seleção/detecção de voz/idioma conforme disponibilidade do motor.

Kokoro é o motor TTS principal da plataforma atual.

---

## 11. Busca web

Quando uma funcionalidade de busca é utilizada, a Phoenix pode consultar serviços configurados, como
SearXNG, e usar os resultados como contexto.

Isso exige comunicação de rede.

---

## 12. Arena

A Arena permite colaboração entre dois modelos em uma mesma tarefa.

A execução possui lifecycle e verificações próprias. O resultado de um modelo não é automaticamente
tratado como prova de correção.

---

## 13. Mission Control

O Mission Control exibe informações de:

- CPU, GPU, VRAM e RAM;
- sensores e temperatura, quando disponíveis;
- processos/runtimes;
- modelos;
- workflows;
- RAG;
- estado de serviços e observabilidade.

Parte dessas informações técnicas também pode compor telemetria diagnóstica da Phoenix, conforme a
política descrita na seção 19.

---

## 14. App Store e missões

Missões agrupam componentes e modelos para objetivos específicos. O provisioning pode envolver
downloads, instalação de dependências, criação de ambientes e uso significativo de armazenamento.

Ações de maior impacto podem exigir confirmação explícita conforme o fluxo aplicável.

---

## 15. Planos Free x Pro

A Phoenix opera como Free quando não existe entitlement Pro válido.

A verificação de licença usa assinatura criptográfica e somente material público de verificação é
distribuído com o cliente. Segredos de emissão não acompanham a Phoenix.

Os mecanismos internos de proteção comercial e integridade não são documentados publicamente em
nível de implementação.

---

## 16. Atualizações e rollback

### Atualizar

Use:

```text
Atualizar_Phoenix.bat <release.zip> [source|windows-ready]
```

A atualização valida o artefato, políticas de release e migrations antes do commit.

### Rollback

Use:

```text
Rollback_Phoenix.bat
```

O rollback restaura a aplicação quando permitido, preservando dados locais classificados como
protegidos.

Estados monotônicos de segurança podem permanecer na versão mais recente mesmo se o código da
aplicação voltar.

---

## 17. Recuperação após interrupção

Se o computador desligar ou o processo morrer durante uma atualização, a Phoenix não inicia
silenciosamente uma mistura de versões.

No startup, o recovery gate verifica o journal e o estado real dos arquivos.

Use manualmente:

```text
Recuperar_Phoenix.bat
```

quando solicitado.

Se a situação for ambígua e não puder ser recuperada com segurança, o startup pode ser bloqueado até
intervenção.

---

## 18. Integridade e estado da instalação

### Ver versão/build instalado

```text
Estado_Phoenix.bat
```

A ferramenta mostra a identidade canônica da instalação, incluindo versão, build, canal e sequence
quando disponíveis.

### Verificar arquivos críticos

```text
Verificar_Integridade_Phoenix.bat
```

Para forçar revalidação completa:

```text
Verificar_Integridade_Phoenix.bat REFRESH
```

### Certificação

```text
Certificar_Phoenix.bat
```

Produz diagnóstico pós-instalação sem precisar executar inferência pesada.

---

## 19. Privacidade, telemetria e diagnóstico

### Local-first

Modelos, documentos e workloads podem permanecer locais quando você utiliza apenas recursos locais.

Entretanto, **a Phoenix pode transmitir informações técnicas e diagnósticas aos servidores da
Phoenix/AIVisionsLab** para melhorar compatibilidade, instalação, estabilidade, desempenho, suporte,
plataforma, serviços e evolução dos modelos/runtimes.

### Informações técnicas que podem ser transmitidas

Dependendo da versão, configuração e recurso utilizado:

- inventário produzido pelo scanner de setup;
- CPU/GPU/VRAM/RAM e características de armazenamento;
- sistema operacional, arquitetura, drivers, Vulkan e versões de runtimes;
- versão/build/canal da Phoenix;
- sucesso/falha de instalação, atualização, repair e startup;
- disponibilidade e comportamento de backends;
- nome/família/quantização do modelo e modo de execução;
- tempo de carregamento e inferência;
- tokens por segundo ou métricas equivalentes;
- uso de CPU/GPU/VRAM;
- OOM, crash, timeout, fallback e códigos de erro;
- diagnósticos e stack traces sanitizados;
- métricas técnicas agregadas de uso de recursos/funcionalidades.

### Conteúdo que não faz parte da telemetria técnica normal

A telemetria não é destinada a coletar o conteúdo integral de:

- documentos privados do RAG;
- arquivos pessoais fora da Phoenix;
- senhas;
- chaves de API;
- tokens;
- chaves privadas;
- conteúdo integral de prompts, respostas ou conversas.

Uma solicitação de suporte, relatório enviado pelo usuário ou integração externa pode envolver
informações adicionais conforme o contexto e a política aplicável.

### Provedores externos

Ao usar Gemini ou outro provedor de nuvem, o conteúdo enviado para gerar a resposta será tratado por
esse provedor.

Isso é independente da telemetria técnica da Phoenix.

### Transparência

Consulte:

```text
institutional/legal/PRIVACY_POLICY.md
institutional/legal/DATA_COLLECTION.md
institutional/legal/TELEMETRY_POLICY.md
institutional/legal/TERMS_OF_USE.md
```

para detalhes.

---

## 20. Solução de problemas

### A Phoenix não inicia depois de uma atualização

Execute:

```text
Recuperar_Phoenix.bat
```

Depois:

```text
Verificar_Integridade_Phoenix.bat REFRESH
```

### Diffusion não inicia

Execute:

```text
Reparar_Phoenix_Diffusion.bat
```

### RAG informa inconsistência

Não apague manualmente `data/chroma_db`. Utilize os fluxos de reparo/reindex/migração indicados pela
Phoenix.

### Modelo local não aparece

Confirme que o runtime/provedor está ativo e que o modelo está realmente disponível no disco ou no
serviço correspondente.

### GPU/HYBRID falhou

Use AUTO ou CPU para diagnóstico, verifique VRAM disponível, drivers/Vulkan e execute a certificação.
Modos explícitos podem falhar em vez de fazer fallback silencioso.

---

## Nota final

A Phoenix é uma plataforma em evolução. Componentes de IA podem produzir saídas incorretas e
hardware/drivers podem apresentar comportamento específico de cada máquina. Preserve backups e
revise resultados importantes.
