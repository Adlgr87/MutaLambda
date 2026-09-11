"""Tests for the Headroom LLM pipeline (Fase 1: O1+O3+A1+A3) and the
cost-aware bandit."""

from __future__ import annotations

import ast
import json
import os
from typing import Callable, List, Optional

import pytest

from headroom_integration import HeadroomStats, headroom_available, llm_mutation_candidate
from operator_bandit import (
    COST_AWARE_SCALE,
    OperatorBandit,
    compute_cost_aware_reward,
    compute_operator_reward,
)

SOURCE = """def solution(n: int) -> int:
    total = 0
    i = 1
    while i <= n:
        total = total + i
        i = i + 1
    return total
"""

VALID_DIFF = (
    "@@ -1,7 +1,4 @@\n"
    " def solution(n: int) -> int:\n"
    "-    total = 0\n"
    "-    i = 1\n"
    "-    while i <= n:\n"
    "-        total = total + i\n"
    "-        i = i + 1\n"
    "-    return total\n"
    "+    return n * (n + 1) // 2\n"
)

BIG_SOURCE = "def big(x):\n" + "".join(f"    s{i} = {i} * x\n" for i in range(40)) + "    return s0\n"
LONG_ERROR = "\n".join(
    [f"[INFO] step {i} ok" for i in range(60)]
    + ["[ERROR] Traceback (most recent call last):", "ValueError: boom"]
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MUTALAMBDA_OPT_"):
            monkeypatch.delenv(name)
    from optimization_flags import reset_optimization_flags
    from cost_ledger import reset_cost_ledger

    reset_optimization_flags()
    reset_cost_ledger()
    yield
    reset_optimization_flags()
    reset_cost_ledger()


def _engine():
    from evolution_engine import CoreEvolutionEngine

    return CoreEvolutionEngine()


def _schema_response(n=1):
    return json.dumps(
        {
            "ops": [
                {
                    "op_type": "replace_function_body",
                    "location": "def solution(n: int)",
                    "unified_diff": VALID_DIFF,
                    "rationale": "Closed form sum.",
                    "confidence": 0.9,
                }
                for _ in range(n)
            ]
        }
    )


class TestPipelineModes:
    def test_flags_off_reproduces_legacy(self, monkeypatch):
        """All headroom flags off → legacy prompt path (free prose)."""
        monkeypatch.setenv("MUTALAMBDA_OPT_FITNESS_CACHE__ENABLED", "0")  # unrelated, isolate
        calls: List[str] = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return "```python\ndef solution(n):\n    return n\n```"

        sink: dict = {}
        out = llm_mutation_candidate(
            engine=_engine(),
            code=SOURCE,
            score=0.5,
            error_info="",
            llm_fn=fake_llm,
            stats_sink=sink,
        )
        assert out is not None
        assert sink["mode"] == "legacy"
        # Legacy prompt is the classic free-prose contract.
        assert "SYSTEM: You are MutaLambda Core Evolution Engine" in calls[0]
        assert len(calls) == 1

    def test_schema_mode_applies_ops(self, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED", "1")
        calls: List[str] = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return _schema_response()

        sink: dict = {}
        out = llm_mutation_candidate(
            engine=_engine(), code=SOURCE, score=0.5, error_info="", llm_fn=fake_llm, stats_sink=sink
        )
        assert sink["mode"] == "schema"
        assert sink["schema_valid"] is True
        assert sink["ops_applied"] == 1
        assert sink["fallback"] is False
        assert "JSON object only" in calls[0]
        ast.parse(out)
        ns = {}
        exec(out, ns)
        assert ns["solution"](10) == 55

    def test_schema_mode_input_tokens_drop_with_stubs(self, monkeypatch):
        """O3 acceptance: the prompt carries stubs, not the full bodies."""
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED", "1")
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__AST_STUBS__ENABLED", "1")
        calls: List[str] = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return _schema_response()

        sink: dict = {}
        llm_mutation_candidate(
            engine=_engine(), code=BIG_SOURCE, score=0.5, error_info="", llm_fn=fake_llm, stats_sink=sink
        )
        assert sink["stub_count"] >= 1
        prompt = calls[0]
        # The big body must be OUT of the prompt (retrievable on demand).
        assert "s39 = 39 * x" not in prompt
        assert "headroom_retrieve" in prompt

        # On a large file the stubbed prompt is much smaller than the full
        # source would be: the code block itself drops below 25% of source.
        big = "def huge(x):\n" + "".join(f"    v{i} = {i} * x\n" for i in range(300)) + "    return v0\n"
        calls.clear()
        sink2: dict = {}
        llm_mutation_candidate(
            engine=_engine(), code=big, score=0.5, error_info="", llm_fn=fake_llm, stats_sink=sink2
        )
        code_block = calls[0].split("SOURCE:\n", 1)[1]
        assert len(code_block) < len(big) // 4

    def test_schema_mode_compresses_tracebacks(self, monkeypatch):
        """O1 acceptance: the error block in the prompt is compressed."""
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED", "1")
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED", "1")
        calls: List[str] = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return _schema_response()

        llm_mutation_candidate(
            engine=_engine(),
            code=SOURCE,
            score=0.5,
            error_info=LONG_ERROR,
            llm_fn=fake_llm,
        )
        assert calls, "expected at least one LLM call"
        assert LONG_ERROR not in calls[0]  # full 60-line log must not be inline
        assert "ValueError: boom" in calls[0]  # but the error survives

    def test_repair_round_on_invalid_json(self, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED", "1")
        responses = iter(["total prose, no json", _schema_response()])
        calls: List[str] = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return next(responses)

        sink: dict = {}
        out = llm_mutation_candidate(
            engine=_engine(), code=SOURCE, score=0.5, error_info="", llm_fn=fake_llm, stats_sink=sink
        )
        assert sink["repaired"] is True
        assert sink["schema_valid"] is True
        assert len(calls) == 2
        assert "REJECTED" in calls[1]
        ast.parse(out)

    def test_fallback_to_legacy_extraction(self, monkeypatch):
        """LLM ignores the contract and returns raw code → still a candidate."""
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED", "1")

        def fake_llm(prompt: str) -> str:
            return "Here is the improved code:\n```python\ndef solution(n):\n    return n * (n + 1) // 2\n```"

        sink: dict = {}
        out = llm_mutation_candidate(
            engine=_engine(), code=SOURCE, score=0.5, error_info="", llm_fn=fake_llm, stats_sink=sink
        )
        assert sink["fallback"] is True
        assert sink["schema_valid"] is False
        assert out is not None
        ast.parse(out)

    def test_retrieval_tool_loop(self, monkeypatch):
        """O3: model asks for the full body, gets it, then answers."""
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED", "1")
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__AST_STUBS__ENABLED", "1")
        calls: List[str] = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            if len(calls) == 1:
                return 'headroom_retrieve("stub_000")'
            return _schema_response()

        sink: dict = {}
        llm_mutation_candidate(
            engine=_engine(), code=BIG_SOURCE, score=0.5, error_info="", llm_fn=fake_llm, stats_sink=sink
        )
        assert sink["retrieval_rounds"] == 1
        assert len(calls) == 2
        assert "FULL BODY for stub_000" in calls[1]
        assert "s39" in calls[1]  # the actual body content was delivered


class TestBatching:
    def test_batching_requests_n_ops(self, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED", "1")
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__BATCHING__ENABLED", "1")
        calls: List[str] = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return _schema_response(n=5)

        sink: dict = {}
        out = llm_mutation_candidate(
            engine=_engine(), code=SOURCE, score=0.5, error_info="", llm_fn=fake_llm, stats_sink=sink
        )
        assert sink["ops_requested"] == 5
        assert sink["ops_total"] == 5
        assert len(calls) == 1  # ONE call for N candidates (A3)
        assert out is not None


class TestEngineIntegration:
    def test_mutate_with_llm_schema_path(self, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__JSON_SCHEMA_OUTPUT__ENABLED", "1")
        engine = _engine()
        calls: List[str] = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return _schema_response()

        sink: dict = {}
        out = engine.mutate_with_llm(SOURCE, 0.5, "", fake_llm, stats_sink=sink)
        assert sink["mode"] == "schema"
        assert "JSON object only" in calls[0]
        ast.parse(out)

    def test_mutate_with_llm_legacy_default(self, monkeypatch):
        engine = _engine()

        def fake_llm(prompt: str) -> str:
            return "```python\ndef solution(n):\n    return n + 1\n```"

        sink: dict = {}
        out = engine.mutate_with_llm(SOURCE, 0.5, "", fake_llm, stats_sink=sink)
        assert sink["mode"] == "legacy"
        assert out is not None

    def test_build_mutation_prompt_compresses_errors(self, monkeypatch):
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__SMART_CRUSHER__ENABLED", "1")
        engine = _engine()
        region = engine._top_region(SOURCE)
        prompt = engine.build_mutation_prompt(SOURCE, region, 0.5, LONG_ERROR)
        assert LONG_ERROR not in prompt
        assert "ValueError: boom" in prompt


class TestCostAwareBandit:
    def test_reward_scales_with_delta_per_token(self):
        # Same improvement, cheaper arm wins.
        cheap = compute_cost_aware_reward(improved=True, correct=True, delta_fitness=0.05, tokens=5000)
        pricey = compute_cost_aware_reward(improved=True, correct=True, delta_fitness=0.05, tokens=20000)
        assert cheap > pricey
        # Bigger improvement wins.
        big = compute_cost_aware_reward(improved=True, correct=True, delta_fitness=0.2, tokens=5000)
        assert big > cheap

    def test_rewards_clamped(self):
        r = compute_cost_aware_reward(improved=True, correct=True, delta_fitness=100.0, tokens=1)
        assert -1.0 <= r <= 1.0
        assert r == 1.0

    def test_failures_match_legacy_penalties(self):
        assert compute_cost_aware_reward(syntax_or_security_failure=True, correct=False) == -0.5
        assert compute_cost_aware_reward(correct=False) == -1.0
        assert compute_cost_aware_reward(correct=True) == 0.2

    def test_no_tokens_gives_legacy_improvement_reward(self):
        assert compute_cost_aware_reward(improved=True, correct=True, delta_fitness=0.1, tokens=0) == 1.0

    def test_update_cost_aware_tracks_tokens(self):
        bandit = OperatorBandit(operators=["llm", "ast"])
        bandit.update_cost_aware("llm", 0.5, valid=True, improved=True, gain=0.05, tokens=1200)
        bandit.update_cost_aware("ast", 1.0, valid=True, improved=True, gain=0.02, tokens=0)
        s = bandit.stats["llm"]
        assert s.tokens == 1200
        assert bandit.snapshot()["llm"]["tokens"] == 1200.0

    def test_ucb_prefers_cheap_improver(self):
        import random

        bandit = OperatorBandit(operators=["expensive", "cheap"], rng=random.Random(1))
        # Same improvement, different token spend → different rewards.
        r_expensive = compute_cost_aware_reward(improved=True, correct=True, delta_fitness=0.05, tokens=20000)
        r_cheap = compute_cost_aware_reward(improved=True, correct=True, delta_fitness=0.05, tokens=2000)
        assert r_cheap > r_expensive
        for _ in range(4):
            bandit.update_cost_aware("expensive", r_expensive, valid=True, improved=True, tokens=20000)
            bandit.update_cost_aware("cheap", r_cheap, valid=True, improved=True, tokens=2000)
        # After warm-up, exploitation must dominate: cheap arm wins.
        picks = [bandit.select() for _ in range(30)]
        assert picks.count("cheap") > picks.count("expensive")

    def test_island_uses_cost_aware_when_flag_on(self, monkeypatch):
        """End-to-end: island bandit update path with the flag enabled."""
        monkeypatch.setenv("MUTALAMBDA_OPT_HEADROOM__BANDIT__ENABLED", "1")
        from types import SimpleNamespace

        from island import Island

        bandit = OperatorBandit(operators=["llm", "ast"])
        island = Island.__new__(Island)
        island.migration_bus = SimpleNamespace(operator_bandit=bandit)

        from models import Individual
        from fitness_vector import FitnessVector

        ind = Individual(code="def f():\n    return 1\n", llm_tokens=10000)
        ind.operator = "llm"
        ind.parent_score = 0.9
        island.population = [ind]
        res = SimpleNamespace(
            score=0.95,
            passed=True,
            timed_out=False,
            stderr="",
            fitness=FitnessVector(correctness=1.0),
        )
        island._update_operator_bandit([res])
        s = bandit.stats["llm"]
        assert s.attempts == 1
        assert s.tokens == 10000
        # reward = Δfitness(0.05)/10000*1000 = 0.005
        assert s.total_reward == pytest.approx(0.05 / 10000 * COST_AWARE_SCALE)

    def test_island_uses_legacy_when_flag_off(self, monkeypatch):
        from types import SimpleNamespace

        from island import Island

        bandit = OperatorBandit(operators=["llm"])
        island = Island.__new__(Island)
        island.migration_bus = SimpleNamespace(operator_bandit=bandit)

        from models import Individual
        from fitness_vector import FitnessVector

        ind = Individual(code="def f():\n    return 1\n", llm_tokens=10000)
        ind.operator = "llm"
        ind.parent_score = 0.9
        island.population = [ind]
        res = SimpleNamespace(
            score=0.95, passed=True, timed_out=False, stderr="",
            fitness=FitnessVector(correctness=1.0),
        )
        island._update_operator_bandit([res])
        # Legacy reward for improved: 1.0 + min(1, gain) → 1.05
        assert bandit.stats["llm"].total_reward == pytest.approx(1.0 + min(1.0, 0.05))
        assert bandit.stats["llm"].tokens == 0


def test_headroom_package_available():
    """Fase 1 setup gate: headroom-ai installed & importable."""
    assert headroom_available() is True
    import headroom

    assert hasattr(headroom, "SmartCrusher")
