"""
Tests for FitnessVector — multi-objective fitness for MutaLambda.
Runs with pytest (fixes CI exit-code-5 issue).
"""

import pytest
from fitness_vector import FitnessVector


class TestFitnessVector:
    """Unit tests for the 6-dimensional fitness vector."""

    def test_constructor_defaults(self):
        fv = FitnessVector()
        assert fv.correctness == 0.0
        assert fv.latency_p50 == 0.0
        assert fv.latency_p99 == 0.0
        assert fv.throughput == 0.0
        assert fv.memory_peak_mb == 0.0
        assert fv.parsimony == 0.0

    def test_constructor_explicit(self):
        fv = FitnessVector(
            correctness=1.0,
            latency_p50=0.05,
            latency_p99=0.10,
            throughput=200.0,
            memory_peak_mb=15.5,
            parsimony=0.8,
        )
        assert fv.correctness == 1.0
        assert fv.throughput == 200.0

    def test_dominates_strictly_better(self):
        """A dominates B when A is better in all dimensions and strictly in one."""
        a = FitnessVector(correctness=1.0, latency_p50=0.01, latency_p99=0.02,
                          throughput=100, memory_peak_mb=5, parsimony=0.9)
        b = FitnessVector(correctness=0.5, latency_p50=0.05, latency_p99=0.10,
                          throughput=50, memory_peak_mb=20, parsimony=0.3)
        assert a.dominates(b)
        assert not b.dominates(a)

    def test_dominates_equal(self):
        """Equal vectors do NOT dominate each other."""
        a = FitnessVector(correctness=1.0, latency_p50=0.01)
        b = FitnessVector(correctness=1.0, latency_p50=0.01)
        assert not a.dominates(b)
        assert not b.dominates(a)

    def test_dominates_partial(self):
        """A is better in correctness but worse in latency → no dominance."""
        a = FitnessVector(correctness=1.0, latency_p50=0.10)
        b = FitnessVector(correctness=0.5, latency_p50=0.01)
        assert not a.dominates(b)
        assert not b.dominates(a)

    def test_weighted_sum_default(self):
        fv = FitnessVector(correctness=1.0, latency_p50=0.01, latency_p99=0.02,
                           throughput=100, memory_peak_mb=5, parsimony=0.9)
        s = fv.weighted_sum()
        assert s > 0  # positive score for good solution

    def test_weighted_sum_worst(self):
        fv = FitnessVector.worst()
        s = fv.weighted_sum()
        # worst should be negative (latency inf → -inf contribution)
        assert s < 0

    def test_to_scalar_delegates_for_fully_correct(self):
        fv = FitnessVector(correctness=1.0)
        assert fv.to_scalar() == fv.weighted_sum()

    def test_to_scalar_gates_incorrect_candidates_below_correct_ones(self):
        incorrect_fast = FitnessVector(
            correctness=0.0,
            latency_p50=0.001,
            latency_p99=0.001,
            throughput=1000.0,
            memory_peak_mb=1.0,
            parsimony=0.5,
        )
        correct_slow = FitnessVector(
            correctness=1.0,
            latency_p50=1.0,
            latency_p99=1.0,
            throughput=1.0,
            memory_peak_mb=1.0,
            parsimony=0.5,
        )

        assert incorrect_fast.to_scalar() < correct_slow.to_scalar()
        assert incorrect_fast.to_scalar() < 0.0
        assert correct_slow.to_scalar() > 0.0

    def test_to_scalar_partial_correctness_is_negative(self):
        fv = FitnessVector(correctness=0.99, throughput=1000.0)

        assert fv.to_scalar() == pytest.approx(-0.01)

    def test_worst_sentinel(self):
        w = FitnessVector.worst()
        assert w.correctness == 0.0
        assert w.latency_p50 == float("inf")
        assert w.is_worst()

    def test_worst_not_dominates(self):
        """Worst vector should never dominate anything."""
        worst = FitnessVector.worst()
        best = FitnessVector(correctness=1.0, latency_p50=0.001, latency_p99=0.001,
                             throughput=1000, memory_peak_mb=1, parsimony=1.0)
        assert not worst.dominates(best)

    def test_dominates_transitive(self):
        """Pareto dominance is transitive (not full order, but for this case)."""
        a = FitnessVector(correctness=1.0, latency_p50=0.01)
        b = FitnessVector(correctness=0.8, latency_p50=0.05)
        c = FitnessVector(correctness=0.5, latency_p50=0.10)
        assert a.dominates(b)
        assert b.dominates(c)
        assert a.dominates(c)

    def test_repr(self):
        fv = FitnessVector(correctness=0.95)
        rep = repr(fv)
        assert "correct=0.95" in rep
        assert "FitnessVector" in rep
