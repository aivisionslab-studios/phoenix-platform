#!/usr/bin/env python3
"""Phoenix Llama Runtime Stable launcher.

A thin compatibility layer over llama.cpp. It deliberately avoids modifying ggml/llama
internals. The contract is encoded as named hardware profiles and an upstream lock.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

RUNTIME_DIR = Path(__file__).resolve().parent
ROOT = RUNTIME_DIR.parent
PROFILES_DIR = RUNTIME_DIR / "profiles"
LOCK_FILE = RUNTIME_DIR / "upstream.lock.json"


class RuntimeErrorPhoenix(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    description: str
    args: tuple[str, ...]


def load_profile(name: str) -> RuntimeProfile:
    path = PROFILES_DIR / f"{name}.json"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in PROFILES_DIR.glob("*.json")))
        raise RuntimeErrorPhoenix(f"Perfil desconhecido: {name}. Disponíveis: {available}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return RuntimeProfile(str(data["name"]), str(data.get("description", "")), tuple(map(str, data["args"])))


def load_lock() -> dict:
    return json.loads(LOCK_FILE.read_text(encoding="utf-8"))


def server_candidates() -> list[Path]:
    names = ["llama-server.exe", "llama-server"]
    bases = [
        ROOT / "build" / "bin" / "Release",
        ROOT / "build" / "bin",
        ROOT / "build-vulkan" / "bin" / "Release",
        ROOT / "build-vulkan" / "bin",
        ROOT / "bin",
    ]
    return [base / name for base in bases for name in names]


def find_server(explicit: str | None = None) -> Path:
    choices: list[Path] = []
    if explicit:
        choices.append(Path(explicit))
    env = os.environ.get("PHOENIX_LLAMA_SERVER")
    if env:
        choices.append(Path(env))
    choices.extend(server_candidates())
    for p in choices:
        if p.is_file():
            return p.resolve()
    raise RuntimeErrorPhoenix(
        "llama-server não encontrado. Compile o runtime ou informe --server / PHOENIX_LLAMA_SERVER."
    )


def _combined_output(cp: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(x for x in [cp.stdout or "", cp.stderr or ""] if x)


def list_devices(server: Path) -> list[str]:
    cp = subprocess.run([str(server), "--list-devices"], text=True, capture_output=True, check=False)
    out = _combined_output(cp)
    if cp.returncode != 0:
        raise RuntimeErrorPhoenix(f"--list-devices falhou ({cp.returncode}):\n{out[-4000:]}")

    # The output format has changed across llama.cpp revisions. Parse conservatively:
    # accept canonical backend IDs (Vulkan0, CUDA0, ROCm0, SYCL0, etc.) when present.
    ids: list[str] = []
    seen = set()
    patterns = [
        r"\b(Vulkan\d+)\b", r"\b(CUDA\d+)\b", r"\b(ROCm\d+)\b", r"\b(HIP\d+)\b",
        r"\b(SYCL\d+)\b", r"\b(MUSA\d+)\b", r"\b(Metal\d+)\b", r"\b(CANN\d+)\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, out, flags=re.IGNORECASE):
            value = match.group(1)
            # restore common canonical capitalization
            low = value.lower()
            if low.startswith("vulkan"): value = "Vulkan" + value[len("Vulkan"):]
            elif low.startswith("cuda"): value = "CUDA" + value[len("CUDA"):]
            elif low.startswith("rocm"): value = "ROCm" + value[len("ROCm"):]
            elif low.startswith("hip"): value = "HIP" + value[len("HIP"):]
            elif low.startswith("sycl"): value = "SYCL" + value[len("SYCL"):]
            elif low.startswith("musa"): value = "MUSA" + value[len("MUSA"):]
            elif low.startswith("metal"): value = "Metal" + value[len("Metal"):]
            elif low.startswith("cann"): value = "CANN" + value[len("CANN"):]
            if value not in seen:
                seen.add(value); ids.append(value)
    return ids


def resolve_device(server: Path, requested: str, prefer_backend: str = "Vulkan") -> str:
    if requested and requested.lower() not in {"auto", "default"}:
        return requested
    devices = list_devices(server)
    if not devices:
        raise RuntimeErrorPhoenix("Nenhum device de offload reportado por llama-server --list-devices.")
    preferred = [d for d in devices if d.lower().startswith(prefer_backend.lower())]
    return preferred[0] if preferred else devices[0]


def expand_args(profile: RuntimeProfile, device: str | None) -> list[str]:
    out: list[str] = []
    for item in profile.args:
        if "{device}" in item:
            if not device:
                raise RuntimeErrorPhoenix(f"Perfil {profile.name} exige device.")
            item = item.replace("{device}", device)
        out.append(item)
    return out


def build_command(
    server: Path,
    model: Path,
    profile_name: str,
    device: str = "auto",
    host: str = "127.0.0.1",
    port: int = 8081,
    ctx: int | None = None,
    threads: int | None = None,
    extra: Iterable[str] = (),
) -> tuple[list[str], str | None]:
    profile = load_profile(profile_name)
    needs_device = any("{device}" in x for x in profile.args)
    resolved = resolve_device(server, device) if needs_device else None
    cmd = [str(server), "-m", str(model.resolve()), "--host", host, "--port", str(port), "--jinja", "--reasoning-format", "auto"]
    if ctx is not None:
        cmd += ["-c", str(ctx)]
    if threads is not None:
        cmd += ["-t", str(threads)]
    cmd += expand_args(profile, resolved)
    cmd += list(extra)
    return cmd, resolved


def _http_json(url: str, payload: dict | None = None, timeout: float = 5.0) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def wait_ready(host: str, port: int, timeout: float) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            _http_json(f"http://{host}:{port}/health", timeout=2.0)
            return
        except Exception as e:  # server may still be loading the model
            last = str(e)
            time.sleep(0.5)
    raise RuntimeErrorPhoenix(f"llama-server não ficou pronto em {timeout:.0f}s. Último erro: {last}")


def correctness_gate(host: str, port: int, timeout: float = 30.0) -> tuple[bool, str]:
    payload = {
        "model": "phoenix-runtime-self-test",
        "messages": [
            {"role": "system", "content": "You are a deterministic runtime self-test."},
            {"role": "user", "content": "Reply with the exact ASCII text PHOENIX_OK and nothing else."},
        ],
        "temperature": 0,
        "max_tokens": 24,
        "stream": False,
    }
    try:
        obj = _http_json(f"http://{host}:{port}/v1/chat/completions", payload, timeout=timeout)
        text = str(obj.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
    except Exception as e:
        return False, f"HTTP/self-test falhou: {e}"
    compact = re.sub(r"\s+", "", text).upper()
    if "PHOENIX_OK" in compact:
        return True, text
    # Reject known corruption patterns without pretending that HTTP 200 means correctness.
    qratio = text.count("?") / max(1, len(text))
    replacement = "\ufffd" in text
    if qratio >= 0.35 or replacement:
        return False, f"saída aparentemente corrompida: {text[:160]!r}"
    return False, f"resposta inesperada: {text[:240]!r}"


def print_runtime_info() -> None:
    lock = load_lock()
    print(f"{lock['runtime_name']} {lock['runtime_version']} [{lock['channel']}]")
    print(f"Upstream: {lock['upstream']['repository']}")
    print(f"Commit:   {lock['upstream']['commit']}")
    print("Auto-update upstream: DISABLED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phoenix Llama Runtime Stable")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="Mostra a versão pinada do runtime")

    pdev = sub.add_parser("devices", help="Lista devices reportados pelo llama.cpp")
    pdev.add_argument("--server")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--server")
    common.add_argument("--model", required=True)
    common.add_argument("--profile", default="cpu", choices=sorted(p.stem for p in PROFILES_DIR.glob("*.json")))
    common.add_argument("--device", default="auto")
    common.add_argument("--prefer-backend", default="Vulkan")
    common.add_argument("--host", default="127.0.0.1")
    common.add_argument("--port", type=int, default=8081)
    common.add_argument("--ctx", type=int)
    common.add_argument("--threads", type=int)
    common.add_argument("extra", nargs=argparse.REMAINDER, help="Argumentos extras após --")

    sub.add_parser("command", parents=[common], help="Imprime o comando efetivo e não executa")
    prun = sub.add_parser("run", parents=[common], help="Executa llama-server com o perfil Phoenix")
    prun.add_argument("--ready-timeout", type=float, default=180.0)
    prun.add_argument("--self-test", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "info":
            print_runtime_info(); return 0
        if args.command == "devices":
            server = find_server(args.server)
            print(f"server={server}")
            for dev in list_devices(server): print(dev)
            return 0

        server = find_server(args.server)
        model = Path(args.model)
        if not model.is_file():
            raise RuntimeErrorPhoenix(f"Modelo não encontrado: {model}")
        cmd, resolved = build_command(
            server, model, args.profile, args.device, args.host, args.port,
            args.ctx, args.threads, args.extra,
        )
        print_runtime_info()
        print(f"Profile:  {args.profile}")
        if resolved: print(f"Device:   {resolved}")
        print("Command:")
        print(subprocess.list2cmdline(cmd) if os.name == "nt" else " ".join(map(_shell_quote, cmd)))
        if args.command == "command":
            return 0

        proc = subprocess.Popen(cmd)
        try:
            wait_ready(args.host, args.port, args.ready_timeout)
            print("Phoenix Runtime: server READY")
            if args.self_test:
                ok, detail = correctness_gate(args.host, args.port)
                if not ok:
                    print(f"Phoenix Runtime: correctness gate FAILED: {detail}", file=sys.stderr)
                    proc.terminate()
                    try: proc.wait(timeout=10)
                    except subprocess.TimeoutExpired: proc.kill()
                    return 23
                print(f"Phoenix Runtime: correctness gate OK ({detail!r})")
            return proc.wait()
        except KeyboardInterrupt:
            proc.send_signal(signal.SIGINT)
            return proc.wait()
        except Exception:
            proc.terminate()
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill()
            raise
    except RuntimeErrorPhoenix as e:
        print(f"Phoenix Runtime ERROR: {e}", file=sys.stderr)
        return 2


def _shell_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@+=,-]+", value):
        return value
    return "'" + value.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    raise SystemExit(main())
