import os
import subprocess
import urllib.request
import logging
import sys
from pathlib import Path
from .catalog import CatalogEngine

logger = logging.getLogger(__name__)

class ProvisioningManager:
    def __init__(self):
        self.catalog = CatalogEngine()

    def install(self, connector_name: str) -> str:
        conn_info = self.catalog.get_connector(connector_name)
        if not conn_info: return f"[ERRO] Conector '{connector_name}' não existe no catálogo."
        provider = conn_info.get("provider")
        if provider == "docker": return self._install_docker(connector_name, conn_info)
        elif provider == "git": return self._install_git(connector_name, conn_info)
        elif provider == "winget": return self._install_winget(connector_name, conn_info)
        elif provider == "pip": return self._install_pip(connector_name, conn_info)
        elif provider == "bundled": return self._install_bundled(connector_name, conn_info)
        else: return f"[ERRO] Provider '{provider}' não suportado."

    def _install_bundled(self, name, info):
        source = Path(info.get("path", ""))
        if not source.is_dir() or not (source / "CMakeLists.txt").is_file():
            return f"[ERRO] Componente incluído '{name}' está ausente ou incompleto: {source}"
        if name == "phoenix-diffusion" and not (source / "ggml" / "CMakeLists.txt").is_file():
            return "[ERRO] GGML empacotado está ausente; reextraia o pacote Phoenix oficial."
        return f"[OK] Componente incluído '{name}' verificado em '{source}'. Use install.ps1 para compilar a bridge."

    # PHX-FIX (varredura 2026-08-21 rodada 2, achado #1 — o mais grave desta
    # rodada): os returncodes de `docker run`/`docker start` eram
    # descartados por completo - "[OK] Container subiu" era devolvido
    # sempre que nenhuma EXCEÇÃO Python acontecia, mesmo com pull
    # falhando, porta em conflito, nome duplicado ou daemon fora do ar
    # (todos saem com código != 0 sem lançar exceção). Isso chega direto
    # no usuário via `api "install package"` -> package_manager.py ->
    # aqui: "Missão concluída!" mentindo sobre uma instalação que nunca
    # funcionou. Agora confere o exit code de cada etapa e, no fim,
    # confirma de verdade que o container está rodando via `docker
    # inspect` - mesmo padrão já usado em lmstudio_service.py ("confirma
    # de verdade, não confia só no exit code do comando").
    def _install_docker(self, name, info):
        cmd = ["docker", "run", "-d", f"--name={name}", f"--restart={info.get('restart', 'unless-stopped')}"]
        for p in info.get("ports", []): cmd.extend(["-p", p])
        for v in info.get("volumes", []): cmd.extend(["-v", v])
        cmd.append(info.get("image"))
        try:
            run_result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            # `docker run` falha com "name already in use" se o container já
            # existe - nesse caso o `docker start` abaixo é o caminho de
            # recuperação esperado, não um erro real. Por isso o sucesso
            # final é decidido pelo `docker inspect` no fim, não pelo
            # returncode isolado do `docker run`.
            start_result = subprocess.run(["docker", "start", name], capture_output=True, text=True, timeout=30)
            if start_result.returncode != 0:
                err = (start_result.stderr or run_result.stderr or "erro desconhecido").strip()
                return f"[ERRO] Docker: falha ao subir '{name}': {err[:500]}"
            check = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name], capture_output=True, text=True, timeout=10)
            if check.returncode != 0 or check.stdout.strip() != "true":
                detail = (check.stdout or check.stderr or "sem detalhes").strip()
                return f"[ERRO] Docker: '{name}' não está rodando depois do start ({detail[:300]})."
            return f"[OK] Container '{name}' subiu."
        except Exception as e: return f"[ERRO] Docker: {e}"

    # Mapa de repositórios que precisam ser compilados com Vulkan, e a flag
    # CMake correta pra cada um (cada projeto ggml-based usa um nome de flag
    # próprio - GGML_VULKAN pro llama.cpp. Phoenix Diffusion é incluído e
    # compilado pelo instalador principal, nunca por clone dinâmico.
    # Adicionar um novo repo compilável = adicionar uma linha aqui.
    _VULKAN_BUILD_TARGETS = {
        "llama": "GGML_VULKAN",
    }

    # PHX-FIX (varredura 2026-08-21 rodada 2, achado #2): os returncodes de
    # `git pull`/`git submodule update`/`git clone` eram descartados -
    # rede fora do ar, URL errada ou falha de autenticação (todos saem com
    # código != 0 sem lançar exceção) caíam direto pra "[OK] clonado",
    # inclusive quando `dest` nunca chegou a existir de verdade. Agora
    # confere o exit code de cada etapa antes de seguir.
    def _install_git(self, name, info):
        url = info.get("url")
        if not url: return "[ERRO] URL Git vazia"
        dest = Path("repos") / name

        # 1. Clona ou atualiza o repositório.
        # --recursive cobre conectores externos que tenham submódulos.
        if dest.exists():
            pull = subprocess.run(["git", "-C", str(dest), "pull"], capture_output=True, text=True, timeout=60)
            if pull.returncode != 0:
                return f"[ERRO] git pull falhou pra '{name}': {(pull.stderr or pull.stdout).strip()[:500]}"
            sub = subprocess.run(["git", "-C", str(dest), "submodule", "update", "--init", "--recursive"],
                            capture_output=True, text=True, timeout=180)
            if sub.returncode != 0:
                return f"[ERRO] git submodule update falhou pra '{name}': {(sub.stderr or sub.stdout).strip()[:500]}"
        else:
            clone = subprocess.run(["git", "clone", "--recursive", url, str(dest)], capture_output=True, text=True, timeout=300)
            if clone.returncode != 0:
                return f"[ERRO] git clone falhou pra '{name}': {(clone.stderr or clone.stdout).strip()[:500]}"

        # 2. RECEITA DE BOLO: se o repo estiver no mapa, compila com Vulkan.
        vulkan_flag = next((flag for key, flag in self._VULKAN_BUILD_TARGETS.items() if key in name.lower()), None)
        if vulkan_flag:
            logger.info("Provisioning: Compilando %s com Vulkan (CMake, -D%s=ON)...", name, vulkan_flag)
            build_dir = dest / "build"
            build_dir.mkdir(exist_ok=True)

            configure_cmd = ["cmake", "..", f"-D{vulkan_flag}=ON"]
            if os.name == "nt":
                # /bigobj evita o limite de seções COFF em conectores C++
                # grandes. Não existe em GCC/Clang, por isso só no Windows.
                configure_cmd.append("-DCMAKE_CXX_FLAGS=/bigobj")

            try:
                # shell=True com lista de argumentos é um bug em POSIX: só o
                # primeiro item roda como comando, o resto vira argumento do
                # próprio shell (não do cmake) e é silenciosamente ignorado.
                # Sem shell=True funciona igual nas duas plataformas.
                subprocess.run(configure_cmd, cwd=str(build_dir), check=True, timeout=120)
                # --parallel: sem isso o CMake não paraleliza builds MSBuild/MSVC
                # (compila essencialmente em single-thread mesmo com 24 threads
                # disponíveis no Xeon). Um conector C++ grande pode passar
                # de 10 min, matando o processo pelo timeout sem erro claro.
                # Timeout subiu de 600s pra 1800s (30 min) por segurança mesmo
                # com paralelismo - build C++ real varia bastante por máquina.
                subprocess.run(
                    ["cmake", "--build", ".", "--config", "Release", "--parallel"],
                    cwd=str(build_dir), check=True, timeout=1800,
                )
                return f"[OK] Repo '{name}' clonado e COMPILADO com Vulkan com sucesso!"
            except subprocess.CalledProcessError as e:
                return f"[ERRO] Falha ao compilar {name}: {e}"
            except Exception as e:
                return f"[ERRO] Tempo limite ou outro erro na compilação: {e}"

        return f"[OK] Repo '{name}' clonado."

    # PHX-FIX (varredura 2026-08-21 rodada 2, achados #3 e #4): mesmo
    # padrão - "pacote não encontrado" ou "precisa de elevação" (winget) e
    # "pacote não encontrado"/erro de rede/permissão negada (pip) saem com
    # código != 0 sem lançar exceção Python, e caíam direto no "[OK]".
    def _install_winget(self, name, info):
        winget_id = info.get("winget_id")
        try:
            result = subprocess.run(["winget", "install", "--id", winget_id, "--accept-package-agreements", "--accept-source-agreements"], capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                return f"[ERRO] Winget: falha ao instalar '{name}' (código {result.returncode}): {(result.stderr or result.stdout).strip()[:500]}"
            return f"[OK] Winget '{name}' instalado."
        except Exception as e: return f"[ERRO] Winget: {e}"

    def _install_pip(self, name, info):
        pip_package = info.get("pip_package", name)
        try:
            result = subprocess.run([sys.executable, "-m", "pip", "install", pip_package], capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return f"[ERRO] Pip: falha ao instalar '{pip_package}' (código {result.returncode}): {(result.stderr or result.stdout).strip()[:500]}"
            return f"[OK] Pip '{pip_package}' instalado."
        except Exception as e: return f"[ERRO] Pip: {e}"
