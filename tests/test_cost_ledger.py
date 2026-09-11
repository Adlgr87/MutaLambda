"""Tests for the cost ledger (Fase 0, A5).

Covers:
* log_llm / log_eval / log_event + totals math (incl. GPU $ conversion),
* dump_json validity (schema_version, totals == sum of entries),
* disabled-flag no-op behaviour,
* interception in the LLM wrapper (LLMBackend.generate),
* interception in regression_gate.evaluate_gate,
* interception in EvaluationService.evaluate_batch.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import cost_ledger as cl
from cost_ledger import CostLedger, get_cost_ledger, reset_cost_ledger


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MUTALAMBDA_OPT_"):
            monkeypatch.delenv(name)
    from optimization_flags import reset_optimization_flags

    reset_optimization_flags()
    reset_cost_ledger()
    yield
    reset_cost_ledger()
    from optimization_flags import reset_optimization_flags

    reset_optimization_flags()


def test_log_llm_totals():
    ledger = CostLedger(enabled=True, gpu_hour_usd=0.5)
    ledger.log_llm(prompt_tokens=100, completion_tokens=50, cost_usd=0.001, model="m", backend="ollama")
    ledger.log_llm(prompt_tokens=400, completion_tokens=100, cost_usd=0.004)
    t = ledger.totals()
    assert t["llm"]["calls"] == 2
    assert t["llm"]["prompt_tokens"] == 500
    assert t["llm"]["completion_tokens"] == 150
    assert t["llm"]["cost_usd"] == pytest.approx(0.005)


def test_log_eval_gpu_cost_conversion():
    ledger = CostLedger(enabled=True, gpu_hour_usd=3600.0)  # $3600/h → $1/sec
    ledger.log_eval(kind="sandbox_eval", seconds=2.0, gpu_seconds=5.0)
    t = ledger.totals()
    assert t["eval"]["count"] == 1
    assert t["eval"]["seconds"] == pytest.approx(2.0)
    assert t["eval"]["gpu_seconds"] == pytest.approx(5.0)
    assert t["eval"]["cost_usd"] == pytest.approx(5.0)
    assert t["total_cost_usd"] == pytest.approx(5.0)


def test_log_event_and_entries():
    ledger = CostLedger()
    ledger.log_event(kind="gate_decision", extra={"passed": True})
    entries = ledger.entries()
    assert len(entries) == 1
    assert entries[0]["kind"] == "event"
    assert entries[0]["event_kind"] == "gate_decision"
    assert entries[0]["extra"] == {"passed": True}
    assert ledger.totals()["events"] == 1


def test_dump_json_valid_and_consistent(tmp_path: Path):
    ledger = CostLedger(enabled=True, gpu_hour_usd=0.5)
    ledger.log_llm(prompt_tokens=10, completion_tokens=5, cost_usd=0.0001)
    ledger.log_eval(seconds=1.5, extra={"n": 4})
    ledger.log_event(kind="cache_stats", extra={"hits": 3})
    out = ledger.dump_json(tmp_path / "out" / "ledger.json")
    assert out.exists()
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1
    assert doc["totals"]["llm"]["calls"] == 1
    assert doc["totals"]["eval"]["count"] == 1
    assert doc["totals"]["events"] == 1
    # totals must equal the sum of the entries (acceptance: dump válido).
    llm_cost = sum(e["cost_usd"] for e in doc["entries"] if e["kind"] == "llm")
    assert doc["totals"]["llm"]["cost_usd"] == pytest.approx(llm_cost, abs=1e-12)
    assert len(doc["entries"]) == 3


def test_disabled_ledger_is_noop():
    ledger = CostLedger(enabled=False)
    ledger.log_llm(prompt_tokens=1, completion_tokens=1)
    ledger.log_eval(seconds=1.0)
    ledger.log_event(kind="x")
    assert len(ledger) == 0
    assert ledger.totals()["total_cost_usd"] == 0.0


def test_flag_disable_via_env(monkeypatch):
    monkeypatch.setenv("MUTALAMBDA_OPT_COST_LEDGER__ENABLED", "0")
    reset_cost_ledger()
    ledger = get_cost_ledger()
    assert ledger.enabled is False
    ledger.log_llm(prompt_tokens=1, completion_tokens=1)
    assert len(ledger) == 0


def test_singleton_and_reset():
    a = get_cost_ledger()
    b = get_cost_ledger()
    assert a is b
    a.log_event(kind="ping")
    reset_cost_ledger()
    c = get_cost_ledger()
    assert c is not a
    assert len(c) == 0


def test_reset_clears_entries():
    ledger = CostLedger()
    ledger.log_event(kind="a")
    ledger.log_event(kind="b")
    ledger.reset()
    assert len(ledger) == 0


def test_guarded_helpers_never_raise(monkeypatch):
    """record_* swallow errors — observability must never break a run."""
    import cost_ledger

    def boom(*_a, **_k):
        raise RuntimeError("ledger exploded")

    monkeypatch.setattr(cost_ledger, "get_cost_ledger", boom)
    # Must not raise.
    cost_ledger.record_llm_call(prompt_tokens=1, completion_tokens=1)
    cost_ledger.record_eval(seconds=1.0)
    cost_ledger.record_event("x")


# ── Interception in the LLM wrapper ──────────────────────────────────────────


def test_llm_wrapper_feeds_ledger(monkeypatch):
    from llm_backend import LLMBackend

    reset_cost_ledger()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-ledger")
    backend = LLMBackend(
        backend="openai",
        model="gpt-4o-mini",  # priced model → non-zero cost
        timeout_sec=1.0,
    )
    captured = {}

    def fake_request(prompt: str) -> str:
        captured["prompt"] = prompt
        return "def f():\n    return 1\n"

    monkeypatch.setattr(backend, "_single_request", fake_request)
    backend.generate("optimize this please")

    ledger = get_cost_ledger()
    entries = [e for e in ledger.entries() if e["kind"] == "llm"]
    assert len(entries) == 1
    assert entries[0]["call_kind"] == "generate"
    assert entries[0]["model"] == "gpt-4o-mini"
    assert entries[0]["prompt_tokens"] > 0
    assert entries[0]["completion_tokens"] > 0
    assert entries[0]["cost_usd"] > 0.0  # priced model
    assert captured["prompt"] == "optimize this please"


def test_llm_batch_feeds_ledger(monkeypatch):
    from llm_backend import LLMBackend

    reset_cost_ledger()
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-ledger")
    backend = LLMBackend(backend="openai", model="gpt-4o-mini", timeout_sec=1.0)
    monkeypatch.setattr(
        backend, "_single_request", lambda p: "def g():\n    return 2\n"
    )
    backend.generate_batch(["p1", "p2", "p3"])
    entries = [e for e in get_cost_ledger().entries() if e["kind"] == "llm"]
    assert len(entries) == 3
    assert all(e["call_kind"] == "generate_batch" for e in entries)


def test_llm_unpriced_model_zero_cost(monkeypatch):
    from llm_backend import LLMBackend

    reset_cost_ledger()
    backend = LLMBackend(backend="ollama", model="llama3.2:3b", timeout_sec=1.0)
    monkeypatch.setattr(backend, "_single_request", lambda p: "ok")
    backend.generate("hi")
    entries = [e for e in get_cost_ledger().entries() if e["kind"] == "llm"]
    assert entries[0]["cost_usd"] == 0.0
    assert entries[0]["prompt_tokens"] >= 1


# ── Interception in the regression gate ──────────────────────────────────────


def test_regression_gate_feeds_ledger():
    from regression_gate import GateConfig, evaluate_gate

    reset_cost_ledger()
    comparison = {
        "metrics": {
            "baseline": {"latency_p50": 10.0},
            "optimized": {"latency_p50": 8.0},
        }
    }
    result = evaluate_gate(comparison, GateConfig())
    assert result.passed
    entries = get_cost_ledger().entries()
    assert any(e["kind"] == "eval" and e["eval_kind"] == "regression_gate" for e in entries)
    events = [e for e in entries if e["kind"] == "event" and e["event_kind"] == "gate_decision"]
    assert len(events) == 1
    assert events[0]["extra"]["passed"] is True
    assert events[0]["extra"]["metric"] == "latency_p50"


# ── Interception in the evaluation service (sandbox) ─────────────────────────


def test_evaluation_service_feeds_ledger(tmp_path: Path):
    from evaluation_service import EvaluationService

    reset_cost_ledger()
    service = EvaluationService(
        test_cases=[{"function": "f", "args": [1], "expected": 2, "comparison": "equal"}],
        timeout_sec=5.0,
        memory_mb=64,
        max_workers=1,
        cache_enabled=False,
    )
    try:
        service.evaluate_batch(["def f(x):\n    return x + 1\n"])
        entries = [
            e for e in get_cost_ledger().entries() if e["kind"] == "eval"
        ]
        assert any(e["eval_kind"] == "sandbox_eval" for e in entries)
        entry = next(e for e in entries if e["eval_kind"] == "sandbox_eval")
        assert entry["seconds"] >= 0.0
        assert entry["extra"]["n"] == 1
    finally:
        service.shutdown(wait=False)
