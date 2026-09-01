"""Pytest fixtures re-exporting shared helpers (FIX 4.1).

Includes an autouse global-state reset fixture (Fase 5C) that clears
module-level caches, process pools, and metric registries between tests
to eliminate cross-test contamination that produces flaky failures in
hfc_tiers, progressive_pipeline, and evaluation_service tests.
"""

from __future__ import annotations

import pytest

from fitness_vector import FitnessVector
from tests.helpers import make_individual


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Clear all module-level global state before and after each test.

    Addresses flaky failures caused by leaked state across tests:
    - ProcessPoolExecutor caches in evaluation_service
    - micro-mutator memoization in hfc_tiers
    - Metric registry counters in metrics_exporter
    """
    try:
        from evaluation_service import shutdown_all_pools
        shutdown_all_pools()
    except Exception:
        pass
    try:
        import hfc_tiers
        hfc_tiers.HFCLeagueEngine.clear_caches()
    except Exception:
        pass
    try:
        from metrics_exporter import reset_registry
        reset_registry()
    except Exception:
        pass
    yield
    try:
        from evaluation_service import shutdown_all_pools
        shutdown_all_pools()
    except Exception:
        pass
    try:
        import hfc_tiers
        hfc_tiers.HFCLeagueEngine.clear_caches()
    except Exception:
        pass


@pytest.fixture
def perfect_fitness() -> FitnessVector:
    return FitnessVector(
        correctness=1.0,
        latency_p50=0.001,
        latency_p99=0.002,
        throughput=1000.0,
        memory_peak_mb=1.0,
        parsimony=0.9,
    )


@pytest.fixture
def worst_fitness() -> FitnessVector:
    return FitnessVector.worst()


@pytest.fixture
def sample_individual():
    return make_individual("def f():\n    return 1\n")
