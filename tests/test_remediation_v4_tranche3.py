"""Tranche-3 tests: EventBus, LLM retries/budget/structured, core resume."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import requests

from event_bus import (
    GENERATION_COMPLETED,
    GENERATION_STARTED,
    EventBus,
    CommandQueue,
    EvolutionEvent,
)
from llm_backend import (
    LLMBackend,
    LLMBackendError,
    LLMBudgetExceeded,
    parse_structured_response,
)
from muta_lambda import EvolveConfig, MutaLambdaAgent, MutaLambdaSession
from models import Individual


class FlakySession:
    def __init__(self, fail_times: int = 2, payload=None):
        self.fail_times = fail_times
        self.calls = 0
        self.payload = payload or {"response": "def f():\n    return 1\n"}

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise requests.ConnectionError("boom")

        class R:
            def raise_for_status(self_inner):
                return None

            def json(self_inner):
                return self.payload

        return R()


def test_event_bus_publish_subscribe():
    bus = EventBus(history_size=10)
    seen = []
    bus.subscribe(lambda e: seen.append(e.name))
    bus.emit(GENERATION_STARTED, {"g": 0}, run_id="abc", generation=0)
    bus.emit(GENERATION_COMPLETED, {"g": 1}, run_id="abc", generation=1)
    assert seen == [GENERATION_STARTED, GENERATION_COMPLETED]
    assert bus.counts()[GENERATION_STARTED] == 1
    hist = bus.history(GENERATION_COMPLETED)
    assert len(hist) == 1
    assert hist[0].run_id == "abc"


def test_command_queue_pause_resume_stop():
    q = CommandQueue()
    q.push("pause")
    assert q.paused is True
    cmds = q.drain()
    assert cmds[0]["command"] == "pause"
    q.push("resume")
    assert q.paused is False
    q.push("stop")
    assert q.stop_requested is True


def test_parse_structured_response_json_and_fence():
    j = parse_structured_response(
        json.dumps(
            {
                "code": "def f():\n    return 1\n",
                "changed_functions": ["f"],
                "reason": "simplify",
                "confidence": 0.9,
            }
        )
    )
    assert "def f" in j.code
    assert j.changed_functions == ["f"]
    assert j.confidence == 0.9

    fenced = parse_structured_response("here\n```python\ndef g():\n    return 2\n```\n")
    assert "def g" in fenced.code


def test_llm_retries_then_succeeds(monkeypatch):
    session = FlakySession(fail_times=2)
    monkeypatch.setattr(requests, "Session", lambda: session)
    llm = LLMBackend(
        backend="ollama",
        model="t",
        timeout_sec=5,
        max_retries=3,
        backoff_base_sec=0.0,
    )
    out = llm.generate("prompt")
    assert "def f" in out
    assert session.calls == 3
    assert llm.metrics()["total_calls"] == 1


def test_llm_budget_exceeded(monkeypatch):
    session = FlakySession(fail_times=0)
    monkeypatch.setattr(requests, "Session", lambda: session)
    llm = LLMBackend(
        backend="ollama",
        model="t",
        timeout_sec=5,
        max_retries=0,
        max_total_calls=1,
        backoff_base_sec=0.0,
    )
    llm.generate("a")
    with pytest.raises(LLMBudgetExceeded):
        llm.generate("b")


def test_agent_emits_generation_events():
    seed = "def solution(n):\n    return n\n"
    cfg = EvolveConfig(
        num_islands=1,
        generations=2,
        population_size=2,
        top_k=1,
        seed_codes=[seed],
        archive_solutions=False,
        prompt_evolution=False,
        checkpoint_enabled=False,
        allow_untested=True,
    )
    agent = MutaLambdaAgent(
        config=cfg,
        test_cases=[{"function": "solution", "args": [1], "expected": 1}],
        llm_fn=lambda _p: seed,
        timeout_sec=5.0,
        task="t",
    )
    names = []
    agent.event_bus.subscribe(lambda e: names.append(e.name))
    agent.step_generation(generation=0, task="t")
    agent.shutdown()
    assert GENERATION_STARTED in names
    assert GENERATION_COMPLETED in names


def test_core_checkpoint_resume_roundtrip(tmp_path):
    from checkpoint_manager import save_full_checkpoint, resume_agent, load_checkpoint

    seed = "def solution(n):\n    return n * (n + 1) // 2\n"
    cfg = EvolveConfig(
        num_islands=1,
        generations=5,
        population_size=2,
        top_k=1,
        seed_codes=[seed],
        archive_solutions=False,
        prompt_evolution=False,
        checkpoint_enabled=True,
        checkpoint_dir=str(tmp_path / "ckpts"),
        checkpoint_interval=1,
        allow_untested=True,
    )
    tests = [{"function": "solution", "args": [5], "expected": 15}]
    agent = MutaLambdaAgent(
        config=cfg,
        test_cases=tests,
        llm_fn=lambda _p: seed,
        timeout_sec=5.0,
        task="sum",
    )
    agent.step_generation(generation=0, task="sum")
    agent._early_stop._best = 1.23
    agent._early_stop._no_improve = 2
    path = save_full_checkpoint(agent, generation=1, config=cfg)
    agent.shutdown()

    cp = load_checkpoint(path)
    assert cp.generation == 1
    assert cp.current_generation >= 1
    assert cp.format if hasattr(cp, "format") else True
    data = json.loads((Path(path) / "checkpoint.json").read_text())
    assert data.get("format") == "mutalambda-core-json"
    assert data.get("early_stop_no_improve") == 2

    resumed = resume_agent(path, cfg, test_cases=tests, llm_fn=lambda _p: seed)
    assert resumed._current_generation >= 1
    assert resumed._early_stop._no_improve == 2
    assert resumed._global_best is not None
    # Continue without restarting from zero
    before = resumed._current_generation
    resumed.step_generation(generation=before, task="sum")
    assert resumed._current_generation == before + 1
    resumed.shutdown()


def test_mutalambda_session_shutdown():
    seed = "def f():\n    return 1\n"
    cfg = EvolveConfig(
        num_islands=1,
        generations=1,
        population_size=2,
        top_k=1,
        seed_codes=[seed],
        archive_solutions=False,
        prompt_evolution=False,
        checkpoint_enabled=False,
        allow_untested=True,
    )
    agent = MutaLambdaAgent(
        config=cfg,
        test_cases=[],
        llm_fn=lambda _p: seed,
        timeout_sec=1.0,
    )
    with MutaLambdaSession(agent) as session:
        assert session is agent
    # shutdown should be idempotent-ish
