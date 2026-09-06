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

## Permissões

O usuário mantém controle total sobre quais permissões concede à Phoenix — nenhuma ação de sistema é escalada silenciosamente.
