# Instalação — AIVisions Phoenix Engine 4.5

A Phoenix pode ser obtida por **release/ZIP** ou por **clone do repositório**. Instalação limpa e
atualização são operações distintas: use uma pasta nova para instalação limpa e o updater da Phoenix
para atualizar uma instalação existente.

## Windows 10/11 — release/ZIP

1. Baixe a release.
2. Extraia em uma pasta nova, por exemplo `C:\PHOENIX 4.5`.
3. Clique com o botão direito em `Iniciar_Phoenix.bat` e escolha **Executar como administrador**.
4. Aguarde o provisionamento. Se houver solicitação de reinício, reinicie e execute o launcher novamente.

Na primeira execução a Phoenix prepara ambiente, dependências e componentes necessários. Nas
execuções seguintes o launcher executa, em ordem, recovery e startup integrity antes de subir
Engine/Aviary.

## Windows 10/11 — clone do GitHub

Instale Git se necessário:

```powershell
winget install --id Git.Git -e --source winget
```

Clone e inicie:

```powershell
cd C:\
git clone https://github.com/aivisionslab-studios/phoenix-engine.git
cd phoenix-engine
.\Iniciar_Phoenix.bat
```

Bootstrap explícito:

```powershell
.\install_phoenix.ps1
```

O bootstrap pode instalar ou validar PowerShell 7, Node.js, Python/venv, ferramentas de build, Vulkan
e componentes auxiliares. Dependendo do estado da máquina, certas alterações podem exigir reinício.

## Linux — Ubuntu/Debian

A automação Linux usa PowerShell 7 (`pwsh`) e ferramentas nativas do sistema.

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

O instalador pode provisionar/validar Python, venv, ferramentas de compilação, FFmpeg, Tesseract,
Node.js, Mesa/Vulkan, sensores e outras dependências. A compatibilidade concreta depende do kernel,
drivers e pacotes disponíveis na distribuição.

Verifique Vulkan com:

```bash
vulkaninfo --summary
```

## Scanner de setup

Durante instalação/provisionamento a Phoenix pode inspecionar:

- CPU;
- GPU;
- VRAM;
- RAM;
- discos e espaço;
- sistema operacional;
- drivers;
- Vulkan/backends;
- ferramentas e runtimes instalados.

Esses dados são usados localmente para decidir provisionamento e execução e **podem compor telemetria
técnica enviada aos serviços Phoenix/AIVisionsLab** para melhorar compatibilidade, suporte,
instalador, runtimes, modelos e a plataforma.

## Serviços padrão

| Serviço | Endereço |
|---|---|
| Phoenix Aviary | `http://localhost:3000` |
| Phoenix Engine / Mission Control | `http://localhost:8000` |
| Phoenix Llama Runtime, quando ativo | `http://localhost:8081` |

## Atualização

```text
Atualizar_Phoenix.bat <release.zip> [source|windows-ready]
```

A atualização verifica o artefato, release policy, migrations, integridade e estado protegido antes
do commit. Não use extração manual por cima de uma instalação existente como substituto do updater.

## Rollback

```text
Rollback_Phoenix.bat
```

## Recovery

```text
Recuperar_Phoenix.bat
```

O startup também tenta resolver automaticamente transações interrompidas quando existe prova
suficiente para fazê-lo com segurança.

## Certificação

```text
Certificar_Phoenix.bat
```

## Integridade

```text
Verificar_Integridade_Phoenix.bat
Verificar_Integridade_Phoenix.bat REFRESH
```

## Estado instalado

```text
Estado_Phoenix.bat
```

## Observação

Instalação, repair e provisioning podem acessar a internet para baixar componentes, dependências,
modelos ou atualizações de fontes externas. Os termos e licenças dos respectivos fornecedores
continuam aplicáveis.
