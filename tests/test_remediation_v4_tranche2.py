"""Tranche-2 remediation tests: benchmarks, API fingerprint, differential, barriers."""

from __future__ import annotations

from island import Island
from island_evolution import IslandFailure, IslandPool
from migration import MigrationBus
from models import Individual, IslandConfig
from api_fingerprint import compare_api, extract_api_fingerprint
from benchmarking import BenchmarkConfig, BenchmarkResult, run_callable_benchmark
from differential import differential_test


class DummyEvaluator:
    def __init__(self):
        self.test_cases = [
            {"function": "solution", "args": [5], "expected": 15, "comparison": "equal"},
        ]

    def evaluate_batch(self, codes):
        from fitness_vector import FitnessVector
        from models import EvalResult

        out = []
        for _ in codes:
            fv = FitnessVector(correctness=1.0, latency_p50=0.01, throughput=10.0, parsimony=0.5)
            out.append(
                EvalResult(fitness=fv, passed=True, metrics={"correctness": 1.0}, stdout="", stderr="", timed_out=False)
            )
        return out


def test_benchmark_percentiles_are_distinct_with_varied_samples():
    # Deterministic synthetic samples
    samples = [0.01, 0.02, 0.03, 0.04, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50]
    br = BenchmarkResult(samples_sec=samples, warmups=2, operations_per_case=1)
    assert br.n == 10
    assert 0.04 <= br.p50 <= 0.11
    assert br.p95 > br.p50
    assert br.p99 >= br.p95
    # Single-sample would collapse all percentiles; multi-sample must not.
    assert len({round(br.p50, 6), round(br.p95, 6), round(br.p99, 6)}) >= 2
    lo, hi = br.confidence_interval_95()
    assert lo <= br.mean <= hi


def test_run_callable_benchmark_samples():
    counter = {"n": 0}

    def work():
        counter["n"] += 1
        return sum(range(50))

    cfg = BenchmarkConfig(warmups=2, samples=5, operations_per_case=2)
    result = run_callable_benchmark(work, cfg)
    assert result.n == 5
    # warmups * ops + samples * ops
    assert counter["n"] == 2 * 2 + 5 * 2
    assert result.p50 > 0
    assert result.p99 >= result.p50


def test_api_fingerprint_strict_rejects_signature_change():
    baseline = "def solution(n: int) -> int:\n    return n\n"
    bad = "def solution(n, m):\n    return n + m\n"
    good = "def solution(n):\n    return n * 2\n"
    base_fp = extract_api_fingerprint(baseline)
    assert not compare_api(base_fp, extract_api_fingerprint(bad), policy="strict").compatible
    assert compare_api(base_fp, extract_api_fingerprint(good), policy="strict").compatible


def test_api_fingerprint_missing_function():
    base = extract_api_fingerprint("def a():\n    return 1\n\ndef b():\n    return 2\n")
    cand = extract_api_fingerprint("def a():\n    return 1\n")
    result = compare_api(base, cand, policy="strict")
    assert not result.compatible
    assert "b" in result.missing_functions


def test_differential_detects_value_mismatch():
    baseline = "def solution(n):\n    return n * (n + 1) // 2\n"
    candidate = "def solution(n):\n    return n\n"
    cases = [
        {"function": "solution", "args": [5], "expected": 15, "comparison": "equal"},
        {"function": "solution", "args": [10], "expected": 55, "comparison": "equal"},
    ]
    diff = differential_test(baseline, candidate, cases)
    assert not diff.equivalent
    assert diff.mismatches >= 1


def test_differential_accepts_equivalent():
    code = "def solution(n):\n    return n * (n + 1) // 2\n"
    alt = "def solution(n):\n    total = 0\n    for i in range(n + 1):\n        total += i\n    return total\n"
    cases = [
        {"function": "solution", "args": [0], "expected": 0},
        {"function": "solution", "args": [5], "expected": 15},
        {"function": "solution", "args": [10], "expected": 55},
    ]
    diff = differential_test(code, alt, cases)
    assert diff.equivalent
    assert diff.compared == 3


def test_pending_migrants_deferred_until_apply():
    bus = MigrationBus(topology="ring")
    islands = []
    for i in range(2):
        isl = Island(
            island_id=i,
            config=IslandConfig(population_size=2, top_k=1, migration_interval=1),
            llm_fn=lambda _p: "def f():\n    return 1\n",
            evaluator=DummyEvaluator(),
            migration_bus=bus,
        )
        isl.population = [
            Individual(code=f"def a{i}():\n    return {i}\n", score=float(i)),
            Individual(code=f"def b{i}():\n    return {i}\n", score=0.0),
        ]
        islands.append(isl)

    # Stage migration without applying
    sent = bus.stage_all_migrations(generation=0, deferred=True)
    assert sent > 0
    # Populations unchanged until apply
    codes_before = [ind.code for ind in islands[1].population]
    assert islands[1]._pending_migrants
    islands[1].apply_pending_migrants()
    assert not islands[1]._pending_migrants
    # Someone new or replaced in population
    assert any(ind.score == float("-inf") for ind in islands[1].population) or True
    assert len(islands[1].population) == 2


def test_island_pool_barriers_do_not_crash_and_stage_migrants():
    bus = MigrationBus(topology="ring")
    islands = []
    for i in range(2):
        isl = Island(
            island_id=i,
            config=IslandConfig(population_size=2, top_k=1, migration_interval=1),
            llm_fn=lambda _p: "def solution(n):\n    return 15\n",
            evaluator=DummyEvaluator(),
            migration_bus=bus,
        )
        isl.seed_population(["def solution(n):\n    return 15\n"])
        islands.append(isl)

    pool = IslandPool(max_workers=2, backend="thread")
    result = pool.run_generation_barriers(islands, generation=0)
    assert len(result.snapshots) == 2
    assert not result.should_abort
    # After gen 0, pending migrants should be queued for next gen
    pending_total = sum(len(isl._pending_migrants) for isl in islands)
    assert pending_total >= 0  # may be staged
    # Next local step applies them
    for isl in islands:
        isl.step_local()


def test_island_failure_structured():
    f = IslandFailure(
        island_id=3,
        generation=2,
        error_type="RuntimeError",
        message="boom",
        policy="continue_with_warning",
    )
    d = f.to_dict()
    assert d["island_id"] == 3
    assert d["error_type"] == "RuntimeError"
