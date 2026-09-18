# Phoenix Forge — Telemetria opcional e privacidade

A telemetria do Forge fica **DESLIGADA por padrão**. Nenhum payload é enviado até o usuário aceitar a versão atual do aviso.

Quando autorizada, a telemetria pode incluir dados técnicos agregados sobre versão do Forge, CPU/GPU/RAM sem números de série, topologia/PCIe, capabilities/providers, NVMe/storage health, sensor fusion, benchmarks resumidos, classes de falha, GPU Safety e workload states.

Por política, o payload de saída remove prompts, mensagens, documentos, OCR/transcrições, conteúdo de chat, caminhos locais, username/hostname, e-mail, MAC, UUID de BIOS/sistema, números de série, PnP instance IDs, senhas, tokens e credenciais. `device_key` é pseudonimizado por instalação antes de sair da máquina.

O usuário pode consultar `/api/telemetry/preview` antes de enviar, revogar o consentimento em `/api/telemetry/revoke` e escolher categorias.

Para clientes públicos, a arquitetura recomendada é um HTTPS ingestion gateway que grava no Google Firestore; **não** se embutem credenciais administrativas do Firestore no aplicativo. Em ambientes privados/controlados, o Forge também aceita Google Cloud Firestore via Application Default Credentials.
