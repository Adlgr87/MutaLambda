"""Tests for FASE 1 framework: ValidationGates + AblationTester + telemetry."""

from __future__ import annotations

import time

import pytest

from benchmarking import AblationTester, AblationVariant, BenchmarkConfig, summarize_ablation
from telemetry import measure, trace_telemetry
from workflow_protocol import (
    GateConfig,
    ValidationGates,
    PASS,
    FAIL,
    RETRYABLE_FAIL,
)


GOOD_CODE = "x = 1\n"
BAD_SYNTAX = "def add(a, b\n    return a + b"
RISKY_CODE = "import os\nos.system('rm -rf /tmp/x')\n"
COMPLEX_CODE = "def f(" + ",".join(f"a{i}" for i in range(60)) + "):\n  " + "\n  ".join(
    f"if a{i}: pass" for i in range(60)
)


def _trivial_correctness(code: str) -> bool:
    """Correctness stand-in: just parses."""
    import ast

    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


class TestValidationGates:
    def test_promotes_clean_code(self):
        gates = ValidationGates(
            GateConfig(run_id="t1", enable_correctness=False),
            on_correctness=_trivial_correctness,
        )
        trace = gates.evaluate({"code": GOOD_CODE})
        assert trace.decision == "promote"
        # correctness gate skipped when enable_correctness=False even with callback
        assert "correctness" not in trace.stage_names()

    def test_correctness_gate_runs_when_enabled(self):
        gates = ValidationGates(GateConfig(run_id="t1c"), on_correctness=_trivial_correctness)
        trace = gates.evaluate({"code": GOOD_CODE})
        assert trace.decision == "promote"
        assert "correctness" in trace.stage_names()

    def test_rejects_syntax_error(self):
        gates = ValidationGates(GateConfig(run_id="t2"))
        trace = gates.evaluate({"code": BAD_SYNTAX})
        assert trace.decision == "reject"
        assert trace.stages[0].status == FAIL

    def test_rejects_risky_calls(self):
        gates = ValidationGates(GateConfig(run_id="t3"))
        trace = gates.evaluate({"code": RISKY_CODE})
        assert trace.decision == "reject"
        assert trace.stages[1].status == FAIL
        assert "risky_call" in trace.stages[1].metadata["findings"][0]

    def test_optional_gates_skip_when_disabled(self):
        gates = ValidationGates(
            GateConfig(run_id="t4", enable_security=False, enable_correctness=False)
        )
        trace = gates.evaluate({"code": GOOD_CODE})
        assert trace.stage_names() == ["syntax_check", "complexity_gate"]
        assert trace.decision == "promote"

    def test_performance_and_resource_optional(self):
        gates = ValidationGates(
            GateConfig(
                run_id="t5",
                enable_security=False,
                enable_correctness=False,
                enable_performance=True,
                enable_resource=True,
            )
        )
        trace = gates.evaluate({"code": GOOD_CODE})
        names = trace.stage_names()
        assert "performance" in names
        assert "resource" in names


class TestAblationTester:
    def _workload(self, flag: bool = True) -> float:
        time.sleep(0.002 if flag else 0.001)
        return flag

    def test_baseline_recorded(self):
        tester = AblationTester(
            self._workload, {"flag": True}, BenchmarkConfig(warmups=1, samples=3)
        )
        results = tester.run_ablation([])
        assert "baseline" in results
        assert results["baseline"].benchmark.n == 3

    def test_variant_compared_to_baseline(self):
        tester = AblationTester(
            self._workload, {"flag": True}, BenchmarkConfig(warmups=1, samples=3)
        )
        results = tester.run_ablation(
            [AblationVariant(name="disabled", enabled_components={"flag": False})]
        )
        b = results["baseline"].benchmark.p50
        v = results["disabled"].benchmark.p50
        # disabled halves sleep => lower p50
        assert v < b

    def test_summarize_flags_impactful(self):
        tester = AblationTester(
            self._workload, {"flag": True}, BenchmarkConfig(warmups=0, samples=5)
        )
        results = tester.run_ablation(
            [AblationVariant(name="disabled", enabled_components={"flag": False})]
        )
        summary = summarize_ablation(results, min_impact_pct=0.0)
        assert summary["baseline_p50"] > 0
        # disabled variant should show up (negative delta_pct)
        names = [c["variant"] for c in summary["impactful_components"]]
        assert "disabled" in names


class TestTelemetry:
    def test_measure_captures_elapsed_and_mem(self):
        def work() -> None:
            x = [0] * 100_000
            time.sleep(0.01)

        snap = measure(work, run_id="m1", tags={"env": "test"})
        assert snap.elapsed_sec >= 0.0
        assert snap.mem_peak_mb >= 0.0
        assert snap.run_id == "m1"
        assert snap.tags["env"] == "test"

    def test_trace_telemetry_yields_snapshot(self):
        with trace_telemetry(run_id="t") as t:
            time.sleep(0.01)
        assert t["snapshot"] is not None
        assert t["snapshot"].run_id == "t"
