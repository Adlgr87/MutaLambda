"""
Tests for progressive_pipeline — the MutaLambda 2.0 workflow.

Focus: the pipeline must plug into the *real* machinery (SandboxEvaluator for
fast mode, MutaLambdaAgent for deep mode) rather than emitting placeholder
fitness vectors or ``deep_mode_placeholder`` dicts.
"""

import ast

import pytest

from progressive_pipeline import (
    PipelineResult,
    ProgressivePipeline,
    synthesize_regression_tests,
)
from fitness_vector import FitnessVector


def _closed_form_llm(prompt: str) -> str:
    """A deterministic stand-in for an LLM that returns the closed form."""
    return "def sum_squares(n):\n    return n * (n - 1) * (2 * n - 1) // 6\n"


SUM_SQUARES = (
    "def sum_squares(n):\n"
    "    total = 0\n"
    "    for i in range(n):\n"
    "        total += i * i\n"
    "    return total\n"
)

BIG = 2_000_000
BIG_EXPECTED = BIG * (BIG - 1) * (2 * BIG - 1) // 6


def _test_cases():
    return [
        {"function": "sum_squares", "args": [10], "expected": 285, "comparison": "equal"},
        {"function": "sum_squares", "args": [BIG], "expected": BIG_EXPECTED, "comparison": "equal"},
    ]


# ── Module sanity ───────────────────────────────────────────────────────────

class TestModule:
    def test_imports_cleanly(self):
        import progressive_pipeline  # noqa: F401
        # If this file has a syntax error, import fails before reaching here.
        assert hasattr(progressive_pipeline, "ProgressivePipeline")

    def test_summary_renders(self):
        result = PipelineResult(
            success=False,
            phase_reached="exhausted",
            original_code="x = 1\n",
            optimized_code=None,
            fitness=FitnessVector(correctness=1.0, latency_p50=0.01, memory_peak_mb=5.0),
        )
        text = result.summary()
        assert "Success: False" in text
        assert "Correctness: 100.0%" in text


# ── Regression-test synthesis ───────────────────────────────────────────────

class TestSynthesizeRegressionTests:
    def test_produces_declarative_cases(self):
        cases = synthesize_regression_tests(
            "def double(x):\n    return x * 2\n"
        )
        assert cases
        for case in cases:
            assert case["function"] == "double"
            assert "args" in case and "expected" in case

    def test_float_uses_float_close(self):
        cases = synthesize_regression_tests(
            "def scale(x: float) -> float:\n    return x * 1.5\n"
        )
        assert any(c["comparison"] == "float_close" for c in cases)

    def test_expected_matches_baseline_output(self):
        cases = synthesize_regression_tests("def double(x):\n    return x * 2\n")
        by_args = {tuple(c["args"]): c["expected"] for c in cases}
        # Sample inputs come from the default int values [0, 1, 2].
        assert by_args.get((2,)) == 4

    def test_syntax_error_returns_empty(self):
        assert synthesize_regression_tests("def broken(:\n") == []


# ── Improvement calculation ─────────────────────────────────────────────────

class TestImprovement:
    def test_faster_latency_is_positive(self):
        p = ProgressivePipeline()
        baseline = FitnessVector(correctness=1.0, latency_p50=1.0, memory_peak_mb=10.0)
        optimized = FitnessVector(correctness=1.0, latency_p50=0.5, memory_peak_mb=10.0)
        assert p._calculate_improvement(baseline, optimized) == pytest.approx(0.35)

    def test_slower_latency_is_negative(self):
        p = ProgressivePipeline()
        baseline = FitnessVector(correctness=1.0, latency_p50=1.0, memory_peak_mb=10.0)
        optimized = FitnessVector(correctness=1.0, latency_p50=2.0, memory_peak_mb=10.0)
        assert p._calculate_improvement(baseline, optimized) < 0

    def test_zero_baseline_latency_safe(self):
        p = ProgressivePipeline()
        baseline = FitnessVector(correctness=1.0, latency_p50=0.0, memory_peak_mb=10.0)
        optimized = FitnessVector(correctness=1.0, latency_p50=0.0, memory_peak_mb=5.0)
        # No latency term, memory term positive (halved memory).
        assert p._calculate_improvement(baseline, optimized) == pytest.approx(0.15)


# ── Fast phase: real evaluation ─────────────────────────────────────────────

class TestFastPhase:
    def test_no_llm_returns_no_llm(self):
        p = ProgressivePipeline(llm_fn=None)
        res = p._fast_phase(SUM_SQUARES, [])
        assert res["success"] is False
        assert res["reason"] == "no_llm"

    def test_detects_real_improvement(self):
        p = ProgressivePipeline(
            llm_fn=_closed_form_llm,
            test_cases=_test_cases(),
            min_improvement=0.1,
            timeout_sec=60.0,
        )
        p._resolved_test_cases = _test_cases()
        baseline = p._evaluate(SUM_SQUARES)
        assert baseline.correctness == 1.0  # baseline passes its own tests

        res = p._fast_phase(SUM_SQUARES, [])
        assert res["success"] is True
        assert res["phase_reached"] == "fast_mode"
        assert res["fitness"].correctness == 1.0
        # Real fitness, not the old placeholder (10.0 ms / 50.0 MB magic values).
        assert res["improvement"] >= 0.1
        p._shutdown_evaluator()

    def test_fitness_is_not_placeholder(self):
        p = ProgressivePipeline(
            llm_fn=_closed_form_llm,
            test_cases=_test_cases(),
            timeout_sec=60.0,
        )
        p._resolved_test_cases = _test_cases()
        fitness = p._evaluate(SUM_SQUARES)
        # The old placeholder was exactly (correctness=1.0, latency_p50=10.0, memory=50.0).
        assert not (
            fitness.correctness == 1.0
            and fitness.latency_p50 == 10.0
            and fitness.memory_peak_mb == 50.0
        )
        p._shutdown_evaluator()


# ── Deep phase: real engine ─────────────────────────────────────────────────

class TestDeepPhase:
    # Flaky bajo carga de la suite completa (ver docs/PRODUCTION_CHECKLIST.md §1);
    # falla rápido, así que reintentar es barato.
    @pytest.mark.flaky(reruns=2, reruns_delay=2)
    def test_runs_real_engine(self):
        p = ProgressivePipeline(
            llm_fn=_closed_form_llm,
            test_cases=_test_cases(),
            min_improvement=0.1,
            timeout_sec=120.0,
        )
        p._resolved_test_cases = _test_cases()
        res = p._deep_phase(SUM_SQUARES, [])
        # Must NOT be the old "deep_mode_placeholder".
        assert res.get("reason") != "deep_mode_placeholder"
        assert res["success"] is True
        assert res["phase_reached"] == "deep_evolution"
        assert res["fitness"].correctness == 1.0
        assert ast.parse(res["optimized_code"])  # valid Python
        p._shutdown_evaluator()


# ── End-to-end ──────────────────────────────────────────────────────────────

class TestEndToEnd:
    def test_full_run_fast_mode(self):
        p = ProgressivePipeline(
            llm_fn=_closed_form_llm,
            test_cases=_test_cases(),
            min_improvement=0.1,
            timeout_sec=60.0,
        )
        result = p.run(SUM_SQUARES, mode="fast")
        assert result.success is True
        assert result.phase_reached == "fast_mode"
        assert result.fitness.correctness == 1.0

    # Flaky bajo carga de la suite completa (ver docs/PRODUCTION_CHECKLIST.md §1).
    @pytest.mark.flaky(reruns=2, reruns_delay=2)
    def test_full_run_deep_mode(self):
        p = ProgressivePipeline(
            llm_fn=_closed_form_llm,
            test_cases=_test_cases(),
            min_improvement=0.1,
            timeout_sec=120.0,
        )
        result = p.run(SUM_SQUARES, mode="deep")
        assert result.success is True
        assert result.phase_reached == "deep_evolution"

    def test_run_without_llm_exhausts(self):
        p = ProgressivePipeline(llm_fn=None, test_cases=_test_cases(), timeout_sec=30.0)
        result = p.run(SUM_SQUARES, mode="auto")
        assert result.success is False
        assert result.phase_reached == "exhausted"
