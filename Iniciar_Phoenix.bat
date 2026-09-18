@echo off
REM Iniciar_Phoenix.bat
REM Launcher UNICO da Phoenix Engine: detecta se e a primeira execucao
REM (instala se precisar) e depois sempre sobe a API. Junta o que antes
REM era Instalar_Phoenix.bat + Iniciar_Phoenix.bat num arquivo so.
REM
REM Por que ainda precisa ser um .bat (e nao chamar o .ps1 direto):
REM arquivos .ps1 sao bloqueados pela Execution Policy do PowerShell
REM ANTES de qualquer linha do script rodar - ou seja, o proprio
REM install_phoenix.ps1 nao consegue se "auto-liberar", porque o Windows
REM PowerShell recusa carregar o arquivo. Um .bat nao sofre essa
REM restricao, entao ele e quem chama o powershell.exe ja com
REM -ExecutionPolicy Bypass.
REM
REM Nota tecnica sobre o "goto" abaixo (em vez de aninhar if dentro de if):
REM dentro de um bloco "if (...)" do batch, todas as variaveis %VAR% sao
REM expandidas de UMA VEZ SO, no momento em que o bloco inteiro e lido -
REM ou seja, se o "if %ERRORLEVEL%" do instalador estivesse aninhado
REM dentro do "if not exist (...)", ele checaria o ERRORLEVEL de ANTES do
REM PowerShell rodar, nao o resultado real da instalacao. Usar "goto"
REM mantem cada "if %ERRORLEVEL%" no nivel principal do script, onde a
REM expansao acontece na hora certa, linha por linha.

cd /d "%~dp0"

REM PHASE7N - recovery gate: nunca iniciar/reinstalar sobre uma atualizacao interrompida.
REM O updater usa somente stdlib, entao preferimos Python de sistema para nao depender
REM da aplicacao potencialmente em transicao. Se nao houver, usamos a venv existente.
set "PHX_RECOVERY_PY="
where python >nul 2>&1
if %ERRORLEVEL% equ 0 set "PHX_RECOVERY_PY=python"
if not defined PHX_RECOVERY_PY if exist ".venv\Scripts\python.exe" set "PHX_RECOVERY_PY=.venv\Scripts\python.exe"
if defined PHX_RECOVERY_PY goto :recover_update
if exist "data\update_recovery_state.json" goto :recovery_python_missing
goto :after_recovery

:recover_update
%PHX_RECOVERY_PY% "upgrade_phoenix.py" recover --root "%CD%"
if %ERRORLEVEL% neq 0 goto :recovery_failed
goto :after_recovery

:recovery_python_missing
echo.
echo [X] Existe uma atualizacao interrompida, mas nenhum Python funcional foi
echo     encontrado para executar a recuperacao segura. A Phoenix NAO sera iniciada.
echo     Restaure o Python e execute: python upgrade_phoenix.py recover
pause
exit /b 1

:recovery_failed
echo.
echo [X] A recuperacao de uma atualizacao interrompida falhou ou ficou ambigua.
echo     A Phoenix NAO sera iniciada em estado misto.
echo     Consulte o transaction.json no backup de upgrades e gere um pacote de suporte.
pause
exit /b 1

:after_recovery

if not exist ".venv\Scripts\python.exe" goto :install

REM PHX-FIX: "if exist" so confere que o ARQUIVO existe - um venv cujo
REM pyvenv.cfg aponta pra um Python que foi desinstalado/movido (ex: apos
REM o instalador reinstalar/reparar o Python numa execucao posterior)
REM ainda passa nesse teste e so quebra depois, na cara do usuario, com a
REM mensagem confusa "No Python at ...". Valida de verdade rodando
REM --version antes de decidir pular a instalacao.
".venv\Scripts\python.exe" --version >nul 2>&1
if %ERRORLEVEL% equ 0 goto :check_integrity

echo.
echo [!] Ambiente virtual encontrado, mas o Python dele nao responde
echo     (provavelmente o Python original foi movido/reinstalado depois
echo     que o venv foi criado). Recriando o ambiente virtual...
echo.
rmdir /s /q ".venv" >nul 2>&1
goto :install

:check_integrity
REM PHASE7O - installed-build integrity gate. Expected hashes come from
REM release_build_manifest.json; heavy binaries use a local TTL cache.
REM Source/dev trees without accepted release state remain usable, but an accepted
REM release with missing/divergent provenance blocks startup.
".venv\Scripts\python.exe" "startup_integrity.py" verify --root "%CD%"
if %ERRORLEVEL% neq 0 goto :integrity_failed
goto :check_storage

:integrity_failed
echo.
echo [X] A integridade da instalacao Phoenix nao corresponde ao ultimo build aceito.
echo     A API NAO sera iniciada. Nao reinstale por cima antes de diagnosticar.
echo     Para rever os bytes sem usar cache ^(isso NAO aceita novos hashes^), execute:
echo     .venv\Scripts\python.exe startup_integrity.py verify --root "%CD%" --refresh
echo     Se necessario, use Recuperar_Phoenix.bat ou gere um pacote de suporte.
pause
exit /b 1

:check_storage
REM PHX-FIX (auditoria 2026-08-04): mesmo problema do venv, mas pro
REM storage.json (workspace no disco NVMe/SSD/HDD mais rapido, escolhido
REM por install/storage_scanner.ps1). Uma vez gravado, nada revalidava se
REM aquele caminho ainda existe - se a letra do drive mudar (disco
REM removido/remapeado, unidade de rede desconectada) entre uma execucao
REM e outra, a Phoenix continuaria confiando cegamente num caminho morto.
REM Revalida de verdade a cada inicializacao, sem custo perceptivel
REM (checagem de arquivo, nao um scan de disco completo).
powershell -NoProfile -Command "$p = Join-Path $env:ProgramData 'Phoenix\storage.json'; if (-not (Test-Path $p)) { exit 1 }; try { $j = Get-Content $p -Raw | ConvertFrom-Json } catch { exit 1 }; if (-not $j.workspace -or -not (Test-Path $j.workspace)) { exit 1 } else { exit 0 }" >nul 2>&1
if %ERRORLEVEL% equ 0 goto :check_llama

REM Trava de seguranca: nunca reinstala mais de uma vez por causa disso -
REM se falhar de novo logo apos reinstalar, e um problema persistente
REM (ex: permissao negada em ProgramData), nao uma unidade que sumiu.
if defined PHX_STORAGE_RETRY (
    echo.
    echo [X] storage.json continua invalido mesmo apos reinstalar. Confira
    echo     permissoes de %ProgramData%\Phoenix\ ou rode
    echo     install\storage_scanner.ps1 manualmente para ver o erro.
    pause
    exit /b 1
)
set PHX_STORAGE_RETRY=1

echo.
echo [!] storage.json ausente, corrompido, ou aponta para um disco que nao
echo     existe mais (ex: unidade removida/remapeada). Rodando o instalador
echo     de novo para redetectar o melhor disco (NVMe/SSD/HDD)...
echo.
goto :install

:install

echo.
echo [i] Rodando o instalador da Phoenix Engine...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_phoenix.ps1"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [X] O instalador terminou com erro. Veja as mensagens acima.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [X] O instalador terminou sem erro, mas o ambiente virtual ainda
    echo     nao existe em .venv\Scripts\python.exe. Alguma coisa no
    echo     install_phoenix.ps1 nao criou o venv onde este launcher espera
    echo     - confira o log da instalacao acima antes de tentar de novo.
    pause
    exit /b 1
)

goto :check_integrity

:check_llama
REM Atualizacoes sobre uma instalacao existente podem trazer o source novo sem
REM o build correspondente. Antes de subir a API, valida/repara o Phoenix Llama Runtime.
if exist "bin\phoenix-llama-runtime\windows-x64\llama-server.exe" goto :verify_llama_bundle
if exist "src\phoenix-llama-runtime\build\bin\Release\llama-server.exe" goto :verify_llama_build
if exist "src\phoenix-llama-runtime\build\bin\llama-server.exe" goto :verify_llama_build
goto :repair_llama

:verify_llama_bundle
set "PHX_LLAMA_SERVER=bin\phoenix-llama-runtime\windows-x64\llama-server.exe"
".venv\Scripts\python.exe" "src\phoenix-llama-runtime\phoenix_runtime\package_windows_runtime.py" --verify-only >nul 2>&1
if %ERRORLEVEL% neq 0 goto :repair_llama
"%PHX_LLAMA_SERVER%" --version >nul 2>&1
if %ERRORLEVEL% neq 0 goto :repair_llama
".venv\Scripts\python.exe" "src\phoenix-llama-runtime\phoenix_runtime\verify_cli_contract.py" --server "%PHX_LLAMA_SERVER%" >nul 2>&1
if %ERRORLEVEL% neq 0 goto :repair_llama
goto :check_diffusion

:verify_llama_build
set "PHX_LLAMA_SERVER="
if exist "src\phoenix-llama-runtime\build\bin\Release\llama-server.exe" set "PHX_LLAMA_SERVER=src\phoenix-llama-runtime\build\bin\Release\llama-server.exe"
if not defined PHX_LLAMA_SERVER if exist "src\phoenix-llama-runtime\build\bin\llama-server.exe" set "PHX_LLAMA_SERVER=src\phoenix-llama-runtime\build\bin\llama-server.exe"
if not defined PHX_LLAMA_SERVER goto :repair_llama
"%PHX_LLAMA_SERVER%" --version >nul 2>&1
if %ERRORLEVEL% neq 0 goto :repair_llama
".venv\Scripts\python.exe" "src\phoenix-llama-runtime\phoenix_runtime\verify_cli_contract.py" --server "%PHX_LLAMA_SERVER%" >nul 2>&1
if %ERRORLEVEL% neq 0 goto :repair_llama
".venv\Scripts\python.exe" "src\phoenix-llama-runtime\phoenix_runtime\runtime_install_state.py" verify --server "%PHX_LLAMA_SERVER%" >nul 2>&1
if %ERRORLEVEL% neq 0 goto :repair_llama
".venv\Scripts\python.exe" "src\phoenix-llama-runtime\phoenix_runtime\package_windows_runtime.py" >nul 2>&1
goto :check_diffusion

:repair_llama
echo.
echo [!] Phoenix Llama Runtime ausente, antigo ou incompativel.
echo     Executando reparo automatico do runtime de texto...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\phoenix-llama-runtime\phoenix_runtime\scripts\build_windows_vulkan.ps1"
if %ERRORLEVEL% neq 0 goto :llama_repair_failed
goto :verify_llama

:llama_repair_failed
echo.
echo [X] O Phoenix Llama Runtime nao pode ser compilado automaticamente.
echo     A API pode subir para recursos de nuvem, mas modelos locais/Arena ficarao indisponiveis.
echo     Veja a mensagem de CMake/MSVC/Vulkan acima.
echo.
goto :check_diffusion

:check_diffusion
REM A .venv sozinha nao significa instalacao completa. Atualizacoes extraidas
REM sobre uma pasta antiga podem preservar uma DLL de outra ABI. Nao basta
REM conferir se o arquivo existe: carrega a bridge, confere a versao esperada
REM e cria/destroi um handle antes de liberar a inicializacao da API.
if not exist "bin\phoenix_sd_bridge.dll" goto :repair_diffusion
".venv\Scripts\python.exe" "src\phoenix-diffusion.cpp\scripts\verify_bridge.py" "bin\phoenix_sd_bridge.dll" >nul 2>&1
if %ERRORLEVEL% equ 0 goto :start

:repair_diffusion

echo.
echo [!] Phoenix Diffusion Bridge ausente, antiga ou incompativel.
echo     Executando reparo automatico
echo     direcionado ^(modelos, .venv e dados nao serao reinstalados^)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0src\phoenix-diffusion.cpp\scripts\build_windows_rx580.ps1" -Force
if %ERRORLEVEL% neq 0 goto :diffusion_repair_failed
if not exist "bin\phoenix_sd_bridge.dll" goto :diffusion_repair_failed
".venv\Scripts\python.exe" "src\phoenix-diffusion.cpp\scripts\verify_bridge.py" "bin\phoenix_sd_bridge.dll" >nul 2>&1
if %ERRORLEVEL% neq 0 goto :diffusion_repair_failed
goto :start

:diffusion_repair_failed
echo.
echo [X] A Phoenix Diffusion nao pode ser compilada automaticamente.
echo     O chat continuara disponivel, mas a geracao de imagens nao.
echo     Veja a mensagem de CMake/Visual Studio/Vulkan logo acima.
echo.
goto :start

:start
".venv\Scripts\python.exe" api_server.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [X] A Phoenix encerrou com erro. Veja as mensagens acima.
    pause
)

