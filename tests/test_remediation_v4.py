"""Regression tests for MutaLambda remediation blockers (v4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation_service import EvaluationService, evaluation_key
from models import Individual, LineageGraph, stable_code_hash
from muta_lambda import EvolveConfig, GenerationResult, MutaLambdaAgent
from runners import SubprocessRunner, compare_values, scan_code_security
from sandbox import SandboxEvaluator


ROOT = Path(__file__).resolve().parents[1]


def test_stable_code_hash_is_sha256_hex():
    h = stable_code_hash("def f():\n    return 1\n")
    assert len(h) == 64
    assert h == stable_code_hash("def f():\n    return 1\n")
    assert h != stable_code_hash("def f():\n    return 2\n")


def test_compare_values_float_close_and_equal():
    assert compare_values(1, 1, "equal")
    assert compare_values(1.0, 1.0 + 1e-15, "float_close")
    assert not compare_values(1.0, 2.0, "float_close")
    assert compare_values("abc", "b", "contains")


def test_subprocess_runner_declarative_tests():
    code = "def solution(n):\n    return n * (n + 1) // 2\n"
    tests = [
        {"function": "solution", "args": [5], "expected": 15, "comparison": "equal"},
        {"function": "solution", "args": [10], "expected": 55, "comparison": "equal"},
    ]
    result = SubprocessRunner(timeout_sec=5.0).run(code, tests)
    assert result.passed
    assert result.fitness.correctness == 1.0


def test_empty_tests_are_not_auto_correct():
    code = "def solution(n):\n    return n\n"
    result = SubprocessRunner(timeout_sec=5.0).run(code, [])
    assert result.fitness.correctness == 0.0
    assert not result.passed


def test_expression_tests_blocked_without_dev_flag():
    code = "def f():\n    return 1\n"
    tests = [{"expression": "f() == 1"}]
    result = SubprocessRunner(timeout_sec=5.0, allow_expression_eval=False).run(code, tests)
    assert not result.passed


def test_security_scan_flags_os_system():
    findings = scan_code_security("import os\nos.system('id')\n")
    assert any("import:os" in f or "call:os.system" in f or "system" in f for f in findings)


def test_evaluation_service_cache_hit():
    code = "def f(x):\n    return x + 1\n"
    tests = [{"function": "f", "args": [1], "expected": 2, "comparison": "equal"}]
    svc = EvaluationService(
        test_cases=tests,
        timeout_sec=5.0,
        max_workers=1,
        cache_enabled=True,
    )
    r1 = svc.evaluate_batch([code])[0]
    r2 = svc.evaluate_batch([code])[0]
    assert r1.passed and r2.passed
    assert svc.cache_stats()["size"] >= 1
    key = evaluation_key(code, tests)
    assert len(key) == 64
    svc.shutdown()


def test_sandbox_evaluator_lazy_compatible():
    tests = [{"function": "f", "args": [2], "expected": 4, "comparison": "equal"}]
    ev = SandboxEvaluator(test_cases=tests, timeout_sec=5.0, parallelism=1)
    results = ev.evaluate_batch(["def f(x):\n    return x * 2\n"])
    assert results[0].passed
    ev.shutdown()


def test_require_tests_raises_without_cases():
    cfg = EvolveConfig(
        num_islands=1,
        generations=1,
        population_size=2,
        top_k=1,
        seed_codes=["def f():\n    return 1\n"],
        require_tests=True,
        allow_untested=False,
        archive_solutions=False,
        prompt_evolution=False,
    )
    with pytest.raises(ValueError, match="No test cases"):
        MutaLambdaAgent(
            config=cfg,
            test_cases=[],
            llm_fn=lambda _p: "def f():\n    return 1\n",
            timeout_sec=1.0,
        )


def test_step_generation_api():
    seed = "def solution(n):\n    return sum(range(n+1))\n"
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
    tests = [
        {"function": "solution", "args": [5], "expected": 15, "comparison": "equal"},
    ]
    agent = MutaLambdaAgent(
        config=cfg,
        test_cases=tests,
        llm_fn=lambda _p: seed,
        timeout_sec=5.0,
        task="optimize sum",
    )
    assert hasattr(agent, "step_generation")
    result = agent.step_generation(generation=0, task="optimize sum")
    assert isinstance(result, GenerationResult)
    assert result.generation == 1
    agent.shutdown()


def test_lineage_uses_stable_hash():
    graph = LineageGraph()
    parent = Individual(code="def a():\n    return 1\n", score=1.0)
    child = Individual(code="def a():\n    return 2\n", score=2.0, parent_ids=[parent.id])
    node = graph.record(child, [parent], generation=1, island_id=0)
    assert isinstance(node.code_hash, str)
    assert len(node.code_hash) == 64


def test_examples_target_passes_declared_tests():
    code = (ROOT / "examples" / "target.py").read_text(encoding="utf-8")
    tests = json.loads((ROOT / "examples" / "target_tests.json").read_text(encoding="utf-8"))
    result = SubprocessRunner(timeout_sec=5.0).run(code, tests)
    assert result.passed
    assert result.fitness.correctness == 1.0
