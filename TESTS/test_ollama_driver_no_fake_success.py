"""
PHX-FIX (auditoria 31/08, achado por agente de varredura ampla, "sucesso
fantasma"): `OllamaDriver.start()` retornava `True` incondicionalmente,
sem nenhuma checagem real do serviço - e `execute()` reportava SUCCESS
mesmo com `message.content` vazio, desde que a chamada HTTP em si desse
200. Nenhum dos dois tinha cobertura de teste antes. Estes testes travam
os dois casos.
"""
import asyncio
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).parents[1]
import sys
sys.path.insert(0, str(ROOT))

from phoenix_kernel.runtime.drivers.ollama import OllamaDriver  # noqa: E402
from core.domain.execution import ExecutionPlan, ExecutionStatus  # noqa: E402


def _fake_urlopen_ctx(payload_bytes: bytes = b"", status: int = 200):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = payload_bytes
    cm.__enter__.return_value.status = status
    return cm


def test_start_returns_false_when_ollama_unreachable():
    driver = OllamaDriver()
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        result = asyncio.run(driver.start())
    assert result is False


def test_start_returns_true_when_ollama_reachable():
    driver = OllamaDriver()
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_ctx(status=200)):
        result = asyncio.run(driver.start())
    assert result is True


def test_execute_fails_on_empty_model_response():
    driver = OllamaDriver()
    plan = ExecutionPlan(id="p1", model="llama3", parameters={"prompt": "oi"})
    empty_response = json.dumps({"message": {"content": ""}}).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_ctx(payload_bytes=empty_response)):
        result = asyncio.run(driver.execute(plan))
    assert result.status == ExecutionStatus.FAILED
    assert "vazia" in result.errors[0].lower()


def test_execute_succeeds_on_real_content():
    driver = OllamaDriver()
    plan = ExecutionPlan(id="p1", model="llama3", parameters={"prompt": "oi"})
    real_response = json.dumps({"message": {"content": "ola, tudo bem?"}}).encode("utf-8")
    with patch("urllib.request.urlopen", return_value=_fake_urlopen_ctx(payload_bytes=real_response)):
        result = asyncio.run(driver.execute(plan))
    assert result.status == ExecutionStatus.SUCCESS
    assert result.output == "ola, tudo bem?"
