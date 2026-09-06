# AIVisions Phoenix Engine 4.5 — Licença

**Copyright © 2026 AIVisionsLab Studio Group — Creative & Tech Solutions**

Este projeto (código-fonte, arquitetura de orquestração, documentação e
ativos associados) é distribuído sob a licença:

**Creative Commons Atribuição-NãoComercial 4.0 Internacional (CC BY-NC 4.0)**

Texto completo da licença: https://creativecommons.org/licenses/by-nc/4.0/deed.pt-BR

## Resumo em linguagem simples

Você tem permissão para:

- ✅ Usar este projeto livremente, para fins pessoais ou educacionais
- ✅ Copiar, modificar e redistribuir o código
- ✅ Compartilhar suas próprias versões/modificações

Desde que:

- 📌 **Atribuição** — dê crédito ao AIVisionsLab Studio Group como autor original, com link para o repositório oficial
- 🚫 **Não-Comercial** — não venda, revenda ou monetize este projeto (ou versões modificadas dele) sem autorização expressa e por escrito do AIVisionsLab Studio Group

## Sobre softwares e componentes de terceiros

A Phoenix Engine 4.5 combina código original com dependências externas e
componentes vendorizados. Cada componente de terceiro permanece sujeito à
sua licença e aos avisos preservados no respectivo diretório. Entre os
componentes instalados, invocados ou integrados estão:

- Docker / Docker Desktop (Windows) e Docker Engine (Ubuntu)
- Ollama
- llama.cpp
- Phoenix Diffusion (fork baseado em stable-diffusion.cpp) e GGML
- Open WebUI
- ChromaDB
- Vulkan SDK
- Visual Studio Build Tools (Windows)
- Git
- LibreHardwareMonitor / HardwareMonitor (Windows) e lm-sensors (Ubuntu)

A Phoenix detecta, decide, provisiona e orquestra essas ferramentas. O código
vendorizado de Phoenix Diffusion e GGML está em `src/phoenix-diffusion.cpp/`;
os textos MIT correspondentes foram preservados em `LICENSE`, `ggml/LICENSE`,
`thirdparty/` e `LICENSES/`. Ao utilizar ou redistribuir a Phoenix, também é
necessário respeitar esses termos de terceiros.

Esta licença cobre exclusivamente:

- O código-fonte deste repositório (kernel, engines, event bus, contratos, terminal web/CLI)
- A arquitetura de decisão e orquestração (Knowledge Engine/RAG, Rules Engine, Runtime Engine, Mission Planner)
- Os scripts de instalação multiplataforma (`install_phoenix.ps1`, `install/windows.ps1`, `install/linux.ps1`, `install/common.ps1`)
- A documentação e os ativos (textos, manifesto, templates, interface visual) originais deste projeto

## Sobre os módulos irmãos do ecossistema AIVisions

A Phoenix Engine consome, via SDK/contrato público, dados fornecidos
por módulos irmãos do ecossistema AIVisions — como o **AIVisions
Hardware Discovery Core** (descoberta de hardware) e o **AIVisions
Hardware Telemetry Core** (observação contínua de estado da máquina).
Esses módulos são projetos próprios, com suas próprias licenças e
ciclos de distribuição — esta licença **não** cobre o código-fonte
deles, apenas a forma como a Phoenix os consome através do seu SDK
público.

## Licenciamento comercial

O AIVisionsLab Studio Group reserva-se o direito de oferecer, em
paralelo, licenças comerciais específicas (com termos de suporte, uso
empresarial ou distribuição comercial) mediante acordo separado. A
disponibilização deste projeto sob CC BY-NC 4.0 não impede o titular
original dos direitos autorais de licenciar a mesma obra sob termos
adicionais para terceiros interessados em uso comercial.

Para consultas sobre licenciamento comercial, entre em contato através
dos canais oficiais do AIVisionsLab.

## Nota sobre dependências externas

Alguns motores continuam sendo instalados ou invocados como processos externos;
outros, como Phoenix Diffusion/GGML, têm código-fonte incluído no pacote e uma bridge
nativa. A presença de uma dependência no repositório não altera a licença do
projeto inteiro automaticamente, mas exige preservar e cumprir a licença daquele
componente. O motor de voz gerenciado nesta versão é Kokoro; referências antigas
ao Piper não descrevem a arquitetura atual.

---

*Este documento é uma licença de código aberto e não constitui
aconselhamento jurídico. Para questões contratuais específicas
(especialmente relacionadas a licenciamento comercial futuro),
recomenda-se consultoria jurídica especializada.*
