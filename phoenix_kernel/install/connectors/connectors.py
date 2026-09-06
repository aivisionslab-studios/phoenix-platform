import subprocess
import urllib.request
import logging

logger = logging.getLogger(__name__)

class WingetConnector:
    def install(self, name: str, info: dict) -> str:
        winget_id = info.get("winget_id")
        if not winget_id: return "ERRO: Sem winget_id"
        cmd = ["winget", "install", winget_id, "--accept-package-agreements", "--accept-source-agreements", "-h"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode == 0: return "OK"
            return f"Skip (Code {proc.returncode})"
        except Exception as e: return f"ERRO: {str(e)}"

class DockerConnector:
    def _is_docker_running(self) -> bool:
        # PHX-FIX (varredura 2026-08-21 rodada 3, achado secundário - código
        # confirmado morto/não-importado pela rota live, mesmo padrão já
        # achado e consertado em provisioning.py): `subprocess.run(["docker",
        # "info"], ...)` nunca lançava exceção quando o daemon está offline
        # (o comando roda, só sai com código != 0) - só um erro de "docker
        # não existe no PATH" cairia no except. Resultado: com o daemon
        # desligado, isso dizia "Docker está rodando" incondicionalmente.
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
            return r.returncode == 0
        except Exception as e:
            logger.debug(f"DockerConnector: falha ao checar 'docker info': {e}")
            return False

    def install(self, name: str, info: dict) -> str:
        if not self._is_docker_running(): return "ERRO: Docker offline"

        image = info.get("image")
        cmd = ["docker", "run", "-d", f"--name={name}", f"--restart={info.get('restart', 'unless-stopped')}"]
        for p in info.get("ports", []): cmd.extend(["-p", p])
        for v in info.get("volumes", []): cmd.extend(["-v", v])
        for k, v in info.get("environment", {}).items(): cmd.extend(["-e", f"{k}={v}"])
        cmd.append(image)

        # PHX-FIX (varredura 2026-08-21 rodada 3, achado secundário - mesmo
        # anti-padrão do achado mais grave da rodada 2 (provisioning.py):
        # o resultado real do subprocess era descartado, "OK" era devolvido
        # sempre que nenhuma exceção Python fosse lançada - um `docker run`
        # que falha por porta em conflito, imagem inexistente, ou nome já
        # em uso saía com código != 0 sem exceção e ainda assim virava "OK".
        # Agora confere o exit code E confirma via `docker inspect` que o
        # container está de fato rodando, igual ao conserto já aplicado em
        # provisioning.py._install_docker.
        try:
            subprocess.run(["docker", "start", name], capture_output=True, text=True)
            run_result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if run_result.returncode != 0:
                return f"ERRO: docker run falhou (code {run_result.returncode}): {run_result.stderr.strip()}"

            inspect = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", name],
                capture_output=True, text=True, timeout=10,
            )
            if inspect.returncode == 0 and inspect.stdout.strip() == "true":
                return "OK"
            return f"ERRO: container '{name}' não confirmado rodando após 'docker run' (docker inspect: {inspect.stdout.strip() or inspect.stderr.strip()})"
        except Exception as e:
            return f"ERRO: {str(e)}"

class GitConnector:
    def install(self, name: str, info: dict, apps_path: str) -> str:
        url = info.get("url")
        if not url: return "ERRO: Sem URL"
        target_dir = f"{apps_path}\\{name}"
        cmd = ["git", "clone", url, target_dir]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if proc.returncode == 0: return "OK"
            if "already exists" in proc.stderr: return "OK (Already exists)"
            return f"ERRO: {proc.stderr}"
        except Exception as e: return f"ERRO: {str(e)}"
