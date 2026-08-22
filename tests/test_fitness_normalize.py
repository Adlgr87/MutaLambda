"""Tests for fitness_normalize (baseline-relative gains)."""

import pytest

from fitness_normalize import (
    NormalizedGains,
    _safe_ratio,
    normalize_against_baseline,
)
from fitness_vector import FitnessVector


def _fv(**kwargs) -> FitnessVector:
    defaults = {
        "correctness": 1.0,
        "latency_p50": 10.0,
        "latency_p99": 20.0,
        "throughput": 100.0,
        "memory_peak_mb": 50.0,
        "parsimony": 0.5,
    }
    defaults.update(kwargs)
    return FitnessVector(**defaults)


@pytest.mark.root
class TestSafeRatio:
    def test_regular_ratio(self):
        assert _safe_ratio(10.0, 4.0) == 2.5

    @pytest.mark.parametrize("denom", [0, None, float("inf")])
    def test_degenerate_denominator_returns_default(self, denom):
        assert _safe_ratio(10.0, denom, default=3.0) == 3.0

    @pytest.mark.parametrize("numer", [None, float("inf")])
    def test_degenerate_numerator_returns_zero(self, numer):
        assert _safe_ratio(numer, 2.0) == 0.0


@pytest.mark.root
class TestNormalizedGains:
    def test_to_dict_roundtrip(self):
        gains = NormalizedGains(
            correctness=1.0,
            latency_gain=2.0,
            throughput_gain=1.5,
            memory_gain=1.2,
            parsimony=0.4,
        )
        assert gains.to_dict() == {
            "correctness": 1.0,
            "latency_gain": 2.0,
            "throughput_gain": 1.5,
            "memory_gain": 1.2,
            "parsimony": 0.4,
        }

    def test_scalar_is_correctness_gated(self):
        gains = NormalizedGains(
            correctness=0.5,
            latency_gain=100.0,
            throughput_gain=100.0,
            memory_gain=100.0,
            parsimony=1.0,
        )
        # Incorrect candidates get a negative score regardless of speed gains.
        assert gains.scalar() == pytest.approx(-0.5)

    def test_scalar_weighted_sum(self):
        gains = NormalizedGains(
            correctness=1.0,
            latency_gain=2.0,
            throughput_gain=2.0,
            memory_gain=2.0,
            parsimony=1.0,
        )
        expected = 1.0 + 0.25 * 2 + 0.25 * 2 + 0.15 * 2 + 0.10 * 1
        assert gains.scalar() == pytest.approx(expected)

    def test_scalar_custom_weights(self):
        gains = NormalizedGains(
            correctness=1.0,
            latency_gain=4.0,
            throughput_gain=0.0,
            memory_gain=0.0,
            parsimony=0.0,
        )
        assert gains.scalar(w_correctness=0.0, w_latency=0.5) == pytest.approx(2.0)

    def test_scalar_rewards_faster_candidate(self):
        slow = NormalizedGains(1.0, 1.0, 1.0, 1.0, 0.5)
        fast = NormalizedGains(1.0, 4.0, 1.0, 1.0, 0.5)
        assert fast.scalar() > slow.scalar()


@pytest.mark.root
class TestNormalizeAgainstBaseline:
    def test_no_baseline_yields_neutral_gains(self):
        candidate = _fv(correctness=0.75, parsimony=0.25)
        gains = normalize_against_baseline(candidate, None)
        assert gains.correctness == 0.75
        assert gains.parsimony == 0.25
        assert (gains.latency_gain, gains.throughput_gain, gains.memory_gain) == (1.0, 1.0, 1.0)

    def test_faster_candidate_has_gain_above_one(self):
        baseline = _fv(latency_p50=10.0, throughput=100.0, memory_peak_mb=50.0)
        candidate = _fv(latency_p50=5.0, throughput=200.0, memory_peak_mb=25.0)
        gains = normalize_against_baseline(candidate, baseline)
        assert gains.latency_gain == pytest.approx(2.0)
        assert gains.throughput_gain == pytest.approx(2.0)
        assert gains.memory_gain == pytest.approx(2.0)

    def test_slower_candidate_has_gain_below_one(self):
        baseline = _fv(latency_p50=10.0)
        candidate = _fv(latency_p50=20.0)
        gains = normalize_against_baseline(candidate, baseline)
        assert gains.latency_gain == pytest.approx(0.5)

    def test_identical_measurements_are_neutral(self):
        baseline = _fv()
        gains = normalize_against_baseline(_fv(), baseline)
        assert gains.latency_gain == pytest.approx(1.0)
        assert gains.throughput_gain == pytest.approx(1.0)
        assert gains.memory_gain == pytest.approx(1.0)

    def test_zero_valued_candidate_metrics_fall_back_to_default(self):
        baseline = _fv(latency_p50=10.0, memory_peak_mb=50.0, throughput=100.0)
        candidate = _fv(latency_p50=0.0, memory_peak_mb=0.0)
        gains = normalize_against_baseline(candidate, baseline)
        assert gains.latency_gain == 1.0
        assert gains.memory_gain == 1.0

    def test_infinite_candidate_latency_scores_zero_gain(self):
        baseline = _fv(latency_p50=10.0)
        candidate = _fv(latency_p50=float("inf"))
        gains = normalize_against_baseline(candidate, baseline)
        # inf latency is worse than any baseline: ratio 10/inf collapses to default 1.0
        assert gains.latency_gain == 1.0

    def test_worst_baseline_throughput_is_handled(self):
        baseline = _fv(throughput=0.0)
        gains = normalize_against_baseline(_fv(throughput=100.0), baseline)
        assert gains.throughput_gain == 1.0
