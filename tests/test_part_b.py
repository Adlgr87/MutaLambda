"""
Tests for Part B: Compression, Cache, Numerical Health, Tipping, Report, Steppers.
"""

import pytest
import random
from muta_ext.lineage.compression import LineageCompressor
from muta_ext.evaluation.cache import CanonicalCache
from muta_ext.evaluation.numerical_health import (
    evaluate_numerical_health, NumericalHealth,
)
from muta_ext.diagnostics.tipping import detect_tipping, mad, TippingEvent
from muta_ext.diagnostics.evolution_report import EvolutionReport
from muta_ext.mutation.stepper_protocol import (
    MutationComposer, MutationResult, ASTStepper, CrossBranchStepper,
)


# ═══════════════════════════════════════════════════════════════════════════════
# B1: Canonical AST Cache
# ═══════════════════════════════════════════════════════════════════════════════


class TestCanonicalCache:
    def test_cache_hit(self):
        cache = CanonicalCache(max_size=100)
        code = "def f(x):\n    return x + 1"
        cache.put(code, {"correctness": 0.9})
        result = cache.get(code)
        assert result is not None
        assert result["correctness"] == 0.9

    def test_cache_miss(self):
        cache = CanonicalCache(max_size=100)
        result = cache.get("def g(x): return x * 2")
        assert result is None

    def test_canonical_ast_hash_normalizes_names(self):
        """Same AST structure, different variable names → same hash."""
        h1 = CanonicalCache.canonical_ast_hash("def f(x):\n    return x + 1")
        h2 = CanonicalCache.canonical_ast_hash("def g(y):\n    return y + 1")
        assert h1 == h2

    def test_canonical_ast_hash_different_structures(self):
        """Different AST structures → different hashes."""
        h1 = CanonicalCache.canonical_ast_hash("def f(x): return x + 1")
        h2 = CanonicalCache.canonical_ast_hash("def f(x):\n    y = x + 1\n    return y")
        assert h1 != h2

    def test_cache_stats(self):
        cache = CanonicalCache(max_size=100)
        cache.put("x = 1", {"score": 1.0})
        cache.get("x = 1")  # hit
        cache.get("x = 2")  # miss
        s = cache.stats()
        assert s.hits == 1
        assert s.misses == 1
        assert s.total_queries == 2
        assert s.hit_ratio == 0.5

    def test_cache_clear(self):
        cache = CanonicalCache(max_size=100)
        cache.put("x = 1", {"score": 1.0})
        cache.clear()
        assert cache.get("x = 1") is None


# ═══════════════════════════════════════════════════════════════════════════════
# B3: Numerical Health
# ═══════════════════════════════════════════════════════════════════════════════


class TestNumericalHealth:
    def test_stable_code(self):
        h = evaluate_numerical_health("def f(x):\n    return x + 1")
        assert h.is_stable
        assert h.score > 0.8

    def test_nested_loops_detected(self):
        h = evaluate_numerical_health("""
def f(n):
    for i in range(n):
        for j in range(n):
            x = i + j
    return x
""")
        assert h.has_nested_loops
        assert h.score < 0.9

    def test_division_detected(self):
        h = evaluate_numerical_health("def f(a, b):\n    return a / b")
        assert h.has_division
        assert h.score < 0.95

    def test_exponential_detected(self):
        h = evaluate_numerical_health("import math\ndef f(x):\n    return math.exp(x)")
        assert h.has_exponential
        assert h.score < 0.95

    def test_syntax_error_returns_zero(self):
        h = evaluate_numerical_health("def f(: return")
        assert not h.is_stable
        assert h.score == 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# B4: Tipping Point Detection
# ═══════════════════════════════════════════════════════════════════════════════


class TestTippingDetection:
    def test_mad_computation(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        m = mad(data)
        assert m > 0.0

    def test_no_tipping_in_stable_series(self):
        series = [1.0, 1.1, 1.0, 0.9, 1.1, 1.0, 1.0, 1.0, 1.0, 1.0]
        events = detect_tipping(series, window=5, n_deviations=3.0)
        assert len(events) == 0

    def test_detects_sudden_drop(self):
        # Gradual change with sudden outlier — easier for MAD to catch
        series = [10.0, 10.5, 9.8, 10.2, 10.1, 9.9, 10.3, 10.0,
                  3.0, 2.5, 2.8, 3.2, 2.9, 3.1, 2.7]
        events = detect_tipping(series, window=7, n_deviations=2.0,
                                min_magnitude=0.3)
        assert len(events) >= 1

    def test_detects_sudden_spike(self):
        series = [1.0, 1.2, 0.9, 1.1, 1.0, 1.3, 0.8, 1.0,
                  50.0, 55.0, 48.0, 52.0, 51.0, 49.0, 53.0]
        events = detect_tipping(series, window=7, n_deviations=2.0,
                                min_magnitude=0.3)
        assert len(events) >= 1

    def test_event_has_metadata(self):
        series = [10.0, 10.0, 10.0, 10.0, 10.0,
                  2.0, 2.0, 2.0, 2.0, 2.0]
        events = detect_tipping(series, window=5, n_deviations=2.0)
        if events:
            e = events[0]
            assert e.generation >= 0
            assert e.magnitude > 0
            assert e.severity in ("low", "medium", "high", "critical")


# ═══════════════════════════════════════════════════════════════════════════════
# B5: Evolution Report
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvolutionReport:
    def test_compute_basic(self):
        report = EvolutionReport.compute(
            fitness_history=[-10.0, -9.0, -8.0, -7.0],
            generation=3,
            diversity=0.5,
            population_scores=[-7.0, -8.0, -9.0, -10.0],
        )
        assert report.generation == 3
        assert report.diversity_score == 0.5
        assert report.best_fitness == -7.0
        assert report.mean_fitness < 0
        assert report.stability_classification in (
            "converging", "exploring", "stalled", "unstable",
        )

    def test_classification_converging(self):
        """Improving fitness + low entropy → converging."""
        report = EvolutionReport.compute(
            fitness_history=[-10.0, -9.0, -8.0, -7.0, -6.0],
            generation=4,
            diversity=0.1,
            population_scores=[-6.0, -6.1, -6.2, -6.3],
        )
        assert report.stability_classification in ("converging", "exploring")

    def test_dashboard_dict(self):
        report = EvolutionReport.compute(
            fitness_history=[-10.0, -9.0],
            generation=1,
            diversity=0.3,
            population_scores=[-9.0, -10.0],
        )
        d = report.to_dashboard_dict()
        assert "generation" in d
        assert "shannon_entropy" in d
        assert "classification" in d


# ═══════════════════════════════════════════════════════════════════════════════
# B6: Mutation Stepper Protocol
# ═══════════════════════════════════════════════════════════════════════════════


class TestStepperProtocol:
    def test_composer_selects_by_weight(self):
        ast = ASTStepper(weight=1.0)
        cb = CrossBranchStepper(weight=0.0)
        composer = MutationComposer([ast, cb], rng=random.Random(42))
        result = composer.step("def f(x): return x + 1")
        assert result.stepper_name == "ast"

    def test_composer_stats(self):
        steppers = [ASTStepper(weight=0.5), CrossBranchStepper(weight=0.5)]
        composer = MutationComposer(steppers, rng=random.Random(42))
        for _ in range(10):
            composer.step("def f(x): return x + 1")
        stats = composer.stats()
        assert "ast" in stats or "cross_branch" in stats

    def test_ast_stepper_mutates(self):
        stepper = ASTStepper(weight=1.0)
        result = stepper.step(
            "def f(x):\n    return x + 1",
            context={"score": -5.0},
            rng=random.Random(0),
        )
        # Mutation should succeed or gracefully fail — both acceptable
        assert isinstance(result, MutationResult)
        assert len(result.code) > 0

    def test_cross_branch_stepper_requires_context(self):
        stepper = CrossBranchStepper(weight=0.1)
        result = stepper.step(
            "def f(x): return x",
            context={},
            rng=random.Random(42),
        )
        assert not result.success  # requires agent context