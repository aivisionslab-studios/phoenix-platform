from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'phoenix_runtime'))
import phoenix_llama_runtime as pr


def test_correctness_gate_accepts_expected_marker(monkeypatch):
    monkeypatch.setattr(pr, '_http_json', lambda *a, **k: {'choices':[{'message':{'content':'PHOENIX_OK'}}]})
    ok, detail = pr.correctness_gate('127.0.0.1', 8081)
    assert ok


def test_correctness_gate_rejects_question_mark_corruption(monkeypatch):
    monkeypatch.setattr(pr, '_http_json', lambda *a, **k: {'choices':[{'message':{'content':'????????????????'}}]})
    ok, detail = pr.correctness_gate('127.0.0.1', 8081)
    assert not ok and 'corrompida' in detail
