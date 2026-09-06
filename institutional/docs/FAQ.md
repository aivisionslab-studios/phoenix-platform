# Perguntas Frequentes — AIVisions Phoenix Engine

**A Phoenix envia meus prompts para algum servidor?**
Não para a AIVisionsLab — por padrão, tudo roda local. Exceção: se você escolher explicitamente um
provedor de nuvem no chat da Aviary (hoje, Gemini), seu prompt vai para os servidores desse provedor,
sob a política de privacidade dele, não da AIVisionsLab. Documentos indexados no RAG continuam
bloqueados de ir para provedores de nuvem mesmo nesse caso, a menos que você desligue essa proteção
manualmente. Ver [Política de Privacidade](../legal/PRIVACY_POLICY.md).

**Como configuro o Gemini na Phoenix?**
Não tem login — é uma chave de API do Google AI Studio, colada uma vez no `.env` da Aviary. Ver
["Configurando o Gemini (opcional)"](../../README.md#configurando-o-gemini-opcional) no README ou
["Aviary WebUI — Gemini opcional"](./INSTALLATION.md#aviary-webui-porta-3000--gemini-opcional) aqui.

**Preciso de GPU para usar a Phoenix?**
Não necessariamente. A Phoenix escolhe automaticamente entre execução CPU, GPU ou híbrida conforme o hardware disponível.

**A Phoenix funciona com GPUs antigas, tipo RX 580?**
Sim — essa é inclusive uma das configurações de referência validadas no projeto (ver [HARDWARE.md](./HARDWARE.md)).

**A Phoenix redistribui modelos de IA?**
Não. Ela detecta, recomenda e baixa modelos de fontes oficiais, mas cada modelo mantém sua licença original.

**Windows ou Linux?**
Ambos são suportados: Windows 10/11 e Ubuntu/Debian, com instaladores dedicados (`install/windows.ps1` / `install/linux.ps1`) a partir de um bootstrapper comum (`install_phoenix.ps1`).

**O que acontece se eu não aprovar uma ação sugerida pelo Resident Manager?**
Nada é executado. Ações de risco médio/alto sempre aguardam aprovação explícita (`aprovar`/`rejeitar`).

**A telemetria é obrigatória?**
Não. Telemetria remota (Firestore) é opt-in e desativada por padrão. Telemetria local sempre existe para alimentar o dashboard e o Resident Manager.
