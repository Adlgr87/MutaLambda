"""Tests para Scientific Validation Layer."""
import pytest
from muta_ext.scientific.validation import (
    evaluate_invariants,
    run_scientific_validation_stage,
    ScientificValidationResult,
)
from muta_ext.scientific.invariants import ScientificInvariant, BASE_INVARIANTS

try:
    from workflow_protocol import PASS, FAIL
except ImportError:
    PASS = "PASS"
    FAIL = "FAIL"


class TestEvaluateInvariants:
    """Tests para evaluate_invariants."""

    def test_all_pass(self):
        r = evaluate_invariants({"total_energy": 100.0, "mass_delta": 1e-10}, {})
        assert r.passed and r.scientific_score == 1.0

    def test_hard_failure(self):
        r = evaluate_invariants({"total_energy": -5.0}, {})
        assert not r.passed and r.hard_failed >= 1

    def test_soft_failure_only(self):
        r = evaluate_invariants({"total_energy": 100.0, "temperature": 1e20}, {})
        assert r.passed  # soft no falla
        assert r.scientific_score < 1.0

    def test_empty_result(self):
        r = evaluate_invariants({}, {})
        assert r.passed

    def test_custom_invariant(self):
        custom = [ScientificInvariant("fail", "fails", lambda r, c: False, "hard")]
        r = evaluate_invariants({"x": 1}, {}, invariants=custom)
        assert not r.passed

    def test_nan_triggers_hard(self):
        r = evaluate_invariants({"value": float('nan')}, {})
        assert not r.passed


class TestStageRunner:
    """Tests para run_scientific_validation_stage."""

    def test_disabled(self):
        sr = run_scientific_validation_stage({"scientific_config": {"enabled": False}})
        assert sr.status == PASS

    def test_enabled_all_pass(self):
        from types import SimpleNamespace
        ctx = {
            "eval_result": SimpleNamespace(
                passed=True,
                fitness=SimpleNamespace(
                    correctness=1.0, latency_p50=0.1, latency_p99=0.2,
                    throughput=1000, memory=50
                ),
                metrics={"total_energy": 100.0, "mass_delta": 0.0},
            ),
            "scientific_config": {"enabled": True, "validation": {
                "invariants": True, "numerical_stability": True,
                "conservation_checks": True, "property_based": True,
            }},
        }
        sr = run_scientific_validation_stage(ctx)
        assert sr.status == PASS

    def test_hard_failure_stage(self):
        from types import SimpleNamespace
        ctx = {
            "eval_result": SimpleNamespace(
                passed=True,
                fitness=SimpleNamespace(
                    correctness=1.0, latency_p50=0.1, latency_p99=0.2,
                    throughput=1000, memory=50
                ),
                metrics={"total_energy": -5.0},
            ),
            "scientific_config": {"enabled": True, "validation": {
                "invariants": True, "numerical_stability": True,
                "conservation_checks": True, "property_based": True,
            }},
        }
        sr = run_scientific_validation_stage(ctx)
        assert sr.status == FAIL